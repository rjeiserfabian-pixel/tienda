"""Recuperación de contraseña por correo.

Diseño contra abuso:

* La solicitud responde SIEMPRE lo mismo (exista o no la cuenta) y el trabajo real ocurre en
  una tarea en segundo plano: ni el mensaje ni el tiempo de respuesta revelan si existe.
* El token se genera DENTRO de la tarea (nunca viaja por el broker), tiene 256 bits, vence
  y es de un solo uso; en la base solo se guarda su huella SHA-256.
* Pedir un enlace nuevo invalida los anteriores. Máximo ``RECUPERACION_MAX_SOLICITUDES_HORA``
  correos por identificador, además del límite por IP de la vista.
* Si la cuenta tiene segundo factor, también se exige un código: el correo solo no basta.
* Al recuperar se cierran TODAS las sesiones y se levanta el bloqueo por intentos fallidos.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.organizacion.models import Estado
from apps.seguridad.exceptions import MfaCodigoInvalido, TokenRecuperacionInvalido
from apps.seguridad.models import MotivoRevocacion, TokenRecuperacion, Usuario
from apps.seguridad.services import auth, mfa, passwords, sesiones

logger = logging.getLogger(__name__)


def _huella(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def solicitar(identificador: str, ip: str | None = None) -> None:
    """Punto de entrada de la vista: aplica el límite por identificador y encola el envío."""
    from apps.seguridad.tasks import enviar_recuperacion

    ident = (identificador or "").strip().lower()[:254]
    if not ident:
        return
    clave = f"seguridad:recuperacion:{_huella(ident)[:32]}"
    cache.add(clave, 0, 3600)
    if cache.incr(clave) > settings.RECUPERACION_MAX_SOLICITUDES_HORA:
        logger.warning("recuperacion_limitada", extra={"ip": ip})
        return
    enviar_recuperacion.delay(ident, ip)


def procesar_solicitud(identificador: str, ip: str | None = None) -> bool:
    """Crea el token y envía el correo. Devuelve si se envió (para pruebas y registros)."""
    usuario = auth.buscar_usuario(identificador)
    organizacion = usuario.organizacion if usuario else None
    if (
        usuario is None
        or not usuario.is_active
        or not usuario.email
        or (organizacion is not None and organizacion.estado != Estado.ACTIVO)
    ):
        logger.info("recuperacion_sin_cuenta_valida")
        return False

    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        TokenRecuperacion.objects.filter(usuario=usuario, usado_en__isnull=True).delete()
        TokenRecuperacion.objects.create(
            usuario=usuario,
            huella=_huella(token),
            expira_en=timezone.now() + timedelta(minutes=settings.RECUPERACION_VIGENCIA_MIN),
            ip=ip,
        )
    enlace = f"{settings.FRONTEND_URL.rstrip('/')}/recuperar/confirmar#token={token}"
    send_mail(
        subject="Recuperación de contraseña",
        message=(
            f"Hola {usuario.first_name or usuario.username},\n\n"
            "Recibimos una solicitud para restablecer su contraseña. Abra este enlace "
            f"(vale {settings.RECUPERACION_VIGENCIA_MIN} minutos y se usa una sola vez):\n\n"
            f"{enlace}\n\n"
            "Si usted no lo pidió, ignore este mensaje: su contraseña no cambia."
        ),
        from_email=None,
        recipient_list=[usuario.email],
        fail_silently=False,
    )
    registrar(
        "password.recuperacion_solicitada",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Se envió un enlace de recuperación de contraseña",
        inmediato=True,
    )
    return True


def confirmar(*, token: str, nueva: str, codigo_mfa: str = "", ip: str | None = None) -> None:
    huella = _huella(token or "")
    ahora = timezone.now()
    pendiente = (
        TokenRecuperacion.objects.select_related("usuario__organizacion")
        .filter(huella=huella, usado_en__isnull=True, expira_en__gt=ahora)
        .first()
    )
    if pendiente is None or not pendiente.usuario.is_active:
        raise TokenRecuperacionInvalido()
    usuario: Usuario = pendiente.usuario

    if usuario.mfa_activo:
        if not (codigo_mfa or "").strip():
            raise MfaCodigoInvalido()
        mfa.verificar(usuario, codigo_mfa)

    with transaction.atomic():
        bloqueado = (
            TokenRecuperacion.objects.select_for_update()
            .filter(pk=pendiente.pk, usado_en__isnull=True, expira_en__gt=ahora)
            .first()
        )
        if bloqueado is None:  # otra petición lo consumió entre tanto
            raise TokenRecuperacionInvalido()
        validate_password(nueva, usuario)
        passwords.exigir_no_reutilizada(usuario, nueva)
        passwords.establecer_password(usuario, nueva)
        bloqueado.usado_en = ahora
        bloqueado.save(update_fields=["usado_en"])
        TokenRecuperacion.objects.filter(usuario=usuario, usado_en__isnull=True).delete()
        sesiones.revocar_sesiones_de_usuario(usuario, MotivoRevocacion.RECUPERACION)

    auth.limpiar_bloqueo(usuario.email)
    auth.limpiar_bloqueo(usuario.username)
    registrar(
        "password.recuperada",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="Contraseña restablecida con el enlace de recuperación",
        detalle={"con_mfa": usuario.mfa_activo},
        inmediato=True,
    )
