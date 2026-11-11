"""Inicio de sesión (con segundo factor opcional) y renovación (refresh rotativo)."""

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from functools import cache as memoizar

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.organizacion.models import Estado
from apps.seguridad.exceptions import (
    CredencialesInvalidas,
    CuentaBloqueadaTemporalmente,
    DesafioMfaInvalido,
    OrganizacionInactiva,
    RefreshConcurrente,
    SesionInvalida,
    SinAccesoEmpresas,
)
from apps.seguridad.models import MotivoRevocacion, Sesion, Usuario
from apps.seguridad.services import mfa, sesiones, tokens
from apps.seguridad.services.accesos import EmpresaHabilitada, empresas_habilitadas

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoAutenticacion:
    access: str
    refresh: str
    sesion: Sesion
    usuario: Usuario
    empresas: list[EmpresaHabilitada]


@dataclass(frozen=True, slots=True)
class DesafioMfa:
    """Contraseña correcta, falta el segundo factor: aún NO existe sesión."""

    desafio: str


_SAL_DESAFIO = "seguridad.mfa.desafio"


# ---------------------------------------------------------------------------
# Bloqueo progresivo por identificador (sirve también para usuarios inexistentes,
# así la respuesta no revela si la cuenta existe).
# ---------------------------------------------------------------------------
def _claves_bloqueo(identificador: str) -> tuple[str, str]:
    huella = hashlib.sha256(identificador.encode()).hexdigest()[:32]
    return f"seguridad:login:fallos:{huella}", f"seguridad:login:bloqueo:{huella}"


def _verificar_bloqueo(identificador: str) -> None:
    _, clave_bloqueo = _claves_bloqueo(identificador)
    hasta = cache.get(clave_bloqueo)
    if hasta is not None and hasta > timezone.now().timestamp():
        raise CuentaBloqueadaTemporalmente(int(hasta - timezone.now().timestamp()) + 1)


def _registrar_fallo(identificador: str, usuario: Usuario | None = None) -> None:
    clave_fallos, clave_bloqueo = _claves_bloqueo(identificador)
    cache.add(clave_fallos, 0, settings.LOGIN_FALLOS_VIGENCIA_SEG)
    fallos = cache.incr(clave_fallos)
    umbral = settings.LOGIN_FALLOS_PARA_BLOQUEO
    if fallos >= umbral:
        minutos = min(2 ** (fallos - umbral), settings.LOGIN_BLOQUEO_MAX_MINUTOS)
        cache.set(clave_bloqueo, timezone.now().timestamp() + minutos * 60, minutos * 60)
        logger.warning("login_bloqueado", extra={"fallos": fallos, "minutos": minutos})
        registrar(
            "sesion.login_bloqueado",
            recurso_tipo="usuario",
            recurso_id=usuario.pk if usuario else "",
            usuario_id=usuario.pk if usuario else None,
            organizacion_id=usuario.organizacion_id if usuario else None,
            resumen="Ingreso bloqueado temporalmente por intentos fallidos",
            detalle={"fallos": fallos, "minutos": minutos},
            exito=False,
            inmediato=True,
        )


def _limpiar_fallos(identificador: str) -> None:
    cache.delete_many(list(_claves_bloqueo(identificador)))


def limpiar_bloqueo(identificador: str) -> None:
    """Levanta el bloqueo por intentos fallidos (p. ej. tras recuperar la contraseña)."""
    _limpiar_fallos(identificador.strip().lower())


@memoizar
def _hash_ficticio() -> str:
    return make_password("contraseña-ficticia-para-igualar-tiempos")


def buscar_usuario(identificador: str) -> Usuario | None:
    filtro = (
        {"email": identificador} if "@" in identificador else {"username__iexact": identificador}
    )
    return Usuario.objects.select_related("organizacion").filter(**filtro).first()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def _auditar_login_fallido(usuario: Usuario | None, ident: str, motivo: str) -> None:
    registrar(
        "sesion.login_fallido",
        recurso_tipo="usuario",
        recurso_id=usuario.pk if usuario else "",
        usuario_id=usuario.pk if usuario else None,
        organizacion_id=usuario.organizacion_id if usuario else None,
        resumen="Intento de ingreso fallido",
        # Solo una referencia corta del identificador: pudo ser una contraseña mal escrita.
        detalle={"motivo": motivo, "ident_ref": hashlib.sha256(ident.encode()).hexdigest()[:12]},
        exito=False,
        inmediato=True,
    )


def _validar_acceso(usuario: Usuario) -> list[EmpresaHabilitada]:
    if usuario.organizacion is not None and usuario.organizacion.estado != Estado.ACTIVO:
        raise OrganizacionInactiva()
    empresas = empresas_habilitadas(usuario)
    if not empresas and not usuario.es_admin_plataforma:
        raise SinAccesoEmpresas()
    return empresas


def _abrir_sesion(
    usuario: Usuario,
    empresas: list[EmpresaHabilitada],
    *,
    plataforma: str,
    dispositivo: str,
    push_token: str,
    ip,
    user_agent: str,
    metodo: str,
    persistente: bool = True,
) -> ResultadoAutenticacion:
    with transaction.atomic():
        sesion = sesiones.crear_sesion(
            usuario,
            plataforma=plataforma,
            dispositivo=dispositivo,
            user_agent=user_agent,
            ip=ip,
            push_token=push_token,
            persistente=persistente,
        )
        usuario.last_login = timezone.now()
        usuario.save(update_fields=["last_login"])

    access, refresh = tokens.emitir_tokens(
        usuario=usuario,
        sesion_id=sesion.pk,
        jti=sesion.jti_actual,
        empresa_ids=[e.id for e in empresas],
    )
    logger.info(
        "login_exitoso",
        extra={"usuario_id": str(usuario.pk), "sesion_id": str(sesion.pk), "ip": ip},
    )
    registrar(
        "sesion.login_ok",
        recurso_tipo="sesion",
        recurso_id=sesion.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Ingreso al sistema",
        detalle={"plataforma": plataforma, "dispositivo": dispositivo, "metodo": metodo},
        inmediato=True,
    )
    return ResultadoAutenticacion(access, refresh, sesion, usuario, empresas)


def iniciar_sesion(
    *,
    identificador: str,
    password: str,
    plataforma: str,
    dispositivo: str = "",
    push_token: str = "",
    ip=None,
    user_agent: str = "",
    recordar: bool = True,
) -> ResultadoAutenticacion | DesafioMfa:
    ident = identificador.strip().lower()
    _verificar_bloqueo(ident)

    usuario = buscar_usuario(ident)
    if usuario is None:
        check_password(password, _hash_ficticio())  # mismo costo que un usuario real
        _registrar_fallo(ident)
        logger.info("login_fallido", extra={"motivo": "usuario_inexistente", "ip": ip})
        _auditar_login_fallido(None, ident, "usuario_inexistente")
        raise CredencialesInvalidas()

    if not usuario.check_password(password) or not usuario.is_active:
        _registrar_fallo(ident, usuario)
        logger.info("login_fallido", extra={"usuario_id": str(usuario.pk), "ip": ip})
        _auditar_login_fallido(usuario, ident, "password" if usuario.is_active else "inactivo")
        raise CredencialesInvalidas()

    empresas = _validar_acceso(usuario)
    _limpiar_fallos(ident)

    if usuario.mfa_activo:
        desafio = signing.dumps(
            {
                "u": str(usuario.pk),
                "p": plataforma,
                "d": dispositivo[:200],
                "t": push_token[:255],
                "r": recordar,
            },
            salt=_SAL_DESAFIO,
        )
        return DesafioMfa(desafio)

    return _abrir_sesion(
        usuario,
        empresas,
        plataforma=plataforma,
        dispositivo=dispositivo,
        push_token=push_token,
        ip=ip,
        user_agent=user_agent,
        metodo="password",
        persistente=recordar,
    )


def completar_login_mfa(
    *, desafio: str, codigo: str, ip=None, user_agent: str = ""
) -> ResultadoAutenticacion:
    """Segundo paso: valida el código y recién entonces crea la sesión."""
    try:
        datos = signing.loads(desafio, salt=_SAL_DESAFIO, max_age=settings.MFA_DESAFIO_SEG)
        usuario = Usuario.objects.select_related("organizacion").get(pk=datos["u"])
    except (signing.BadSignature, Usuario.DoesNotExist, KeyError, ValidationError, ValueError):
        raise DesafioMfaInvalido() from None
    if not usuario.is_active or not usuario.mfa_activo:
        raise DesafioMfaInvalido()

    empresas = _validar_acceso(usuario)
    metodo = mfa.verificar(usuario, codigo)  # lanza MfaCodigoInvalido o bloqueo temporal
    return _abrir_sesion(
        usuario,
        empresas,
        plataforma=datos["p"],
        dispositivo=datos["d"],
        push_token=datos["t"],
        ip=ip,
        user_agent=user_agent,
        metodo=f"mfa_{metodo}",
        persistente=datos.get("r", True),
    )


# ---------------------------------------------------------------------------
# Refresh rotativo
# ---------------------------------------------------------------------------
def refrescar_sesion(*, refresh_token: str, ip=None) -> ResultadoAutenticacion:
    """Canjea un refresh token por un par nuevo e invalida el anterior.

    Usa un patrón "decidir dentro de la transacción, lanzar fuera": una revocación
    por reutilización debe CONFIRMARSE aunque la petición termine en error.
    """
    par = tokens.leer_refresh(refresh_token)
    ahora = timezone.now()
    error: Exception | None = None
    resultado: ResultadoAutenticacion | None = None

    with transaction.atomic():
        try:
            sesion = (
                Sesion.objects.select_for_update(of=("self",))
                .select_related("usuario__organizacion")
                .get(pk=par.sid, usuario_id=par.user_id)
            )
        except (Sesion.DoesNotExist, ValidationError, ValueError):
            raise SesionInvalida() from None

        usuario = sesion.usuario
        limite_absoluto = sesion.creado_en + timedelta(days=settings.SESION_MAXIMA_DIAS)

        if sesion.revocada:
            error = SesionInvalida()
        elif sesion.expira_en <= ahora or limite_absoluto <= ahora:
            sesiones.revocar_sesion(sesion, MotivoRevocacion.EXPIRADA)
            error = SesionInvalida()
        elif not usuario.is_active:
            sesiones.revocar_sesion(sesion, MotivoRevocacion.USUARIO_INACTIVO)
            error = SesionInvalida()
        elif par.jti != sesion.jti_actual:
            reciente = (
                par.jti == sesion.jti_anterior
                and sesion.rotado_en is not None
                and ahora - sesion.rotado_en < timedelta(seconds=settings.REFRESH_GRACIA_SEG)
            )
            if reciente:
                error = RefreshConcurrente()
            else:
                sesiones.revocar_sesion(sesion, MotivoRevocacion.REUSO)
                logger.warning(
                    "refresh_reutilizado",
                    extra={"sesion_id": str(sesion.pk), "usuario_id": str(usuario.pk), "ip": ip},
                )
                registrar(
                    "sesion.refresh_reutilizado",
                    recurso_tipo="sesion",
                    recurso_id=sesion.pk,
                    usuario_id=usuario.pk,
                    organizacion_id=usuario.organizacion_id,
                    resumen="Se reutilizó un refresh token: sesión revocada",
                    exito=False,
                )
                error = SesionInvalida()
        else:
            empresas = empresas_habilitadas(usuario)
            if not empresas and not usuario.es_admin_plataforma:
                sesiones.revocar_sesion(sesion, MotivoRevocacion.SIN_ACCESO)
                error = SinAccesoEmpresas()
            elif usuario.organizacion is not None and usuario.organizacion.estado != Estado.ACTIVO:
                sesiones.revocar_sesion(sesion, MotivoRevocacion.USUARIO_INACTIVO)
                error = OrganizacionInactiva()
            else:
                sesion.jti_anterior = sesion.jti_actual
                sesion.jti_actual = tokens.nuevo_jti()
                sesion.rotado_en = ahora
                sesion.ultimo_uso = ahora
                sesion.expira_en = ahora + sesiones.vigencia_de(sesion.persistente)
                if ip:
                    sesion.ip = ip
                sesion.save(
                    update_fields=[
                        "jti_anterior",
                        "jti_actual",
                        "rotado_en",
                        "ultimo_uso",
                        "expira_en",
                        "ip",
                    ]
                )
                access, refresh = tokens.emitir_tokens(
                    usuario=usuario,
                    sesion_id=sesion.pk,
                    jti=sesion.jti_actual,
                    empresa_ids=[e.id for e in empresas],
                )
                resultado = ResultadoAutenticacion(access, refresh, sesion, usuario, empresas)

    if error is not None:
        raise error
    assert resultado is not None  # noqa: S101 - invariante: sin error hay resultado
    return resultado
