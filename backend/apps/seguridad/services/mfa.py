"""Verificación en dos pasos (TOTP, RFC 6238) con códigos de recuperación.

* El secreto se guarda cifrado; los códigos de recuperación, solo como huella (HMAC).
* Un código TOTP no se acepta dos veces (anti repetición) y cada intento fallido cuenta:
  tras ``MFA_MAX_FALLOS`` seguidos se bloquean los intentos ``MFA_BLOQUEO_SEG`` segundos.
* Las operaciones sensibles (activar, desactivar, regenerar) piden además la contraseña.
"""

import hashlib
import hmac
import logging
import secrets
import time

import pyotp
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.seguridad.exceptions import (
    CuentaBloqueadaTemporalmente,
    MfaCodigoInvalido,
    MfaNoActivo,
    MfaObligatoria,
    MfaYaActivo,
    PasswordActualIncorrecta,
)
from apps.seguridad.models import CodigoRecuperacionMfa, MfaConfig, Usuario
from apps.seguridad.services import politicas

logger = logging.getLogger(__name__)

_PASO_SEG = 30
_VENTANA = 1  # tolera un intervalo de desfase de reloj a cada lado


# ---------------------------------------------------------------------------
# Intentos fallidos
# ---------------------------------------------------------------------------
def _claves(usuario) -> tuple[str, str]:
    return f"seguridad:mfa:fallos:{usuario.pk}", f"seguridad:mfa:bloqueo:{usuario.pk}"


def _exigir_no_bloqueado(usuario) -> None:
    _, clave_bloqueo = _claves(usuario)
    hasta = cache.get(clave_bloqueo)
    ahora = timezone.now().timestamp()
    if hasta is not None and hasta > ahora:
        raise CuentaBloqueadaTemporalmente(int(hasta - ahora) + 1)


def _registrar_fallo(usuario, motivo: str) -> None:
    clave_fallos, clave_bloqueo = _claves(usuario)
    cache.add(clave_fallos, 0, settings.MFA_BLOQUEO_SEG)
    fallos = cache.incr(clave_fallos)
    if fallos >= settings.MFA_MAX_FALLOS:
        cache.set(
            clave_bloqueo,
            timezone.now().timestamp() + settings.MFA_BLOQUEO_SEG,
            settings.MFA_BLOQUEO_SEG,
        )
        cache.delete(clave_fallos)
    registrar(
        "mfa.intento_fallido",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Código o contraseña incorrectos en una operación de segundo factor",
        detalle={"motivo": motivo, "fallos_seguidos": fallos},
        exito=False,
        inmediato=True,
    )


def _limpiar_fallos(usuario) -> None:
    cache.delete_many(list(_claves(usuario)))


def _exigir_password(usuario, password: str) -> None:
    if not usuario.check_password(password):
        _registrar_fallo(usuario, "password")
        raise PasswordActualIncorrecta()


# ---------------------------------------------------------------------------
# Códigos
# ---------------------------------------------------------------------------
def _huella(codigo: str) -> str:
    normalizado = codigo.strip().lower().replace("-", "").replace(" ", "")
    return hmac.new(settings.SECRET_KEY.encode(), normalizado.encode(), hashlib.sha256).hexdigest()


def _generar_codigos_recuperacion(usuario) -> list[str]:
    """Reemplaza los códigos del usuario; devuelve los nuevos EN CLARO (única vez que existen)."""
    CodigoRecuperacionMfa.objects.filter(usuario=usuario).delete()
    codigos = []
    for _ in range(settings.MFA_CODIGOS_RECUPERACION):
        crudo = secrets.token_hex(5)  # 40 bits; ver bloqueo de intentos arriba
        codigos.append(f"{crudo[:5]}-{crudo[5:]}")
    CodigoRecuperacionMfa.objects.bulk_create(
        CodigoRecuperacionMfa(usuario=usuario, huella=_huella(c)) for c in codigos
    )
    return codigos


def _totp_valido(config: MfaConfig, codigo: str) -> bool:
    """Valida el código y consume su intervalo (no se puede repetir). Requiere fila bloqueada."""
    if not (len(codigo) == 6 and codigo.isdigit()):
        return False
    totp = pyotp.TOTP(config.secreto)
    paso_actual = int(time.time() // _PASO_SEG)
    for paso in range(paso_actual - _VENTANA, paso_actual + _VENTANA + 1):
        if hmac.compare_digest(totp.at(paso * _PASO_SEG), codigo):
            if paso <= config.ultimo_paso:
                return False  # ya usado (o más antiguo que uno ya usado)
            config.ultimo_paso = paso
            config.save(update_fields=["ultimo_paso"])
            return True
    return False


# ---------------------------------------------------------------------------
# API del servicio
# ---------------------------------------------------------------------------
def codigos_restantes(usuario) -> int:
    return CodigoRecuperacionMfa.objects.filter(usuario=usuario, usado_en__isnull=True).count()


def _intentar(usuario: Usuario, codigo: str) -> str | None:
    """Prueba el código dentro de una transacción corta. ``None`` si no es válido."""
    with transaction.atomic():
        config = (
            MfaConfig.objects.select_for_update()
            .filter(usuario=usuario, confirmado_en__isnull=False)
            .first()
        )
        if config is None:
            raise MfaNoActivo()
        if _totp_valido(config, codigo):
            return "totp"
        pendiente = (
            CodigoRecuperacionMfa.objects.select_for_update()
            .filter(usuario=usuario, huella=_huella(codigo), usado_en__isnull=True)
            .first()
        )
        if pendiente is not None and len(codigo) > 6:
            pendiente.usado_en = timezone.now()
            pendiente.save(update_fields=["usado_en"])
            return "recuperacion"
    return None


def verificar(usuario: Usuario, codigo: str) -> str:
    """Valida un código TOTP o de recuperación. Devuelve ``"totp"`` o ``"recuperacion"``.

    El fallo se registra FUERA de la transacción de la prueba, para que no se revierta con ella.
    """
    _exigir_no_bloqueado(usuario)
    resultado = _intentar(usuario, (codigo or "").strip())
    if resultado is None:
        _registrar_fallo(usuario, "codigo")
        raise MfaCodigoInvalido()
    _limpiar_fallos(usuario)
    if resultado == "recuperacion":
        registrar(
            "mfa.codigo_recuperacion_usado",
            recurso_tipo="usuario",
            recurso_id=usuario.pk,
            usuario_id=usuario.pk,
            organizacion_id=usuario.organizacion_id,
            resumen="Ingreso con un código de recuperación",
            detalle={"restantes": codigos_restantes(usuario)},
        )
    return resultado


def iniciar_configuracion(usuario: Usuario, password: str) -> dict:
    """Genera un secreto nuevo (aún sin confirmar) y devuelve lo necesario para el autenticador."""
    _exigir_no_bloqueado(usuario)
    if usuario.mfa_activo:
        raise MfaYaActivo()
    _exigir_password(usuario, password)
    secreto = pyotp.random_base32()
    MfaConfig.objects.update_or_create(
        usuario=usuario, defaults={"secreto": secreto, "confirmado_en": None, "ultimo_paso": 0}
    )
    uri = pyotp.TOTP(secreto).provisioning_uri(name=usuario.email, issuer_name=settings.MFA_EMISOR)
    return {"secreto": secreto, "uri": uri}


def confirmar_configuracion(usuario: Usuario, codigo: str) -> list[str]:
    """Activa el factor al probar un código válido. Devuelve los códigos de recuperación."""
    _exigir_no_bloqueado(usuario)
    if usuario.mfa_activo:
        raise MfaYaActivo()
    with transaction.atomic():
        config = MfaConfig.objects.select_for_update().filter(usuario=usuario).first()
        valido = config is not None and _totp_valido(config, (codigo or "").strip())
        if valido:
            config.confirmado_en = timezone.now()
            config.save(update_fields=["confirmado_en"])
            usuario.mfa_activo = True
            usuario.save(update_fields=["mfa_activo"])
            codigos = _generar_codigos_recuperacion(usuario)
    if not valido:
        _registrar_fallo(usuario, "confirmacion")
        raise MfaCodigoInvalido()
    _limpiar_fallos(usuario)
    registrar(
        "mfa.activado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Verificación en dos pasos activada",
    )
    return codigos


def desactivar(usuario: Usuario, password: str, codigo: str) -> None:
    if not usuario.mfa_activo:
        raise MfaNoActivo()
    if politicas.mfa_obligatorio(usuario.organizacion_id):
        raise MfaObligatoria()
    _exigir_password(usuario, password)
    verificar(usuario, codigo)
    with transaction.atomic():
        _eliminar(usuario)
    registrar(
        "mfa.desactivado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Verificación en dos pasos desactivada por el propio usuario",
    )


def regenerar_codigos(usuario: Usuario, password: str, codigo: str) -> list[str]:
    if not usuario.mfa_activo:
        raise MfaNoActivo()
    _exigir_password(usuario, password)
    verificar(usuario, codigo)
    with transaction.atomic():
        codigos = _generar_codigos_recuperacion(usuario)
    registrar(
        "mfa.codigos_regenerados",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Códigos de recuperación regenerados",
    )
    return codigos


def _eliminar(usuario: Usuario) -> None:
    MfaConfig.objects.filter(usuario=usuario).delete()
    CodigoRecuperacionMfa.objects.filter(usuario=usuario).delete()
    usuario.mfa_activo = False
    usuario.save(update_fields=["mfa_activo"])
    _limpiar_fallos(usuario)


@transaction.atomic
def restablecer(usuario: Usuario) -> None:
    """Quita el factor SIN pedir código (pérdida del dispositivo). Autoriza quien llama."""
    _eliminar(usuario)
