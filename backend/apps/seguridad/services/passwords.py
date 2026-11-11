"""Política de contraseñas: validadores, historial de las últimas N y revocación de sesiones."""

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.seguridad.exceptions import PasswordActualIncorrecta, PasswordReutilizada
from apps.seguridad.models import HistorialPassword, MotivoRevocacion
from apps.seguridad.services import sesiones


def _registrar_en_historial(usuario) -> None:
    HistorialPassword.objects.create(usuario=usuario, password_hash=usuario.password)
    conservar = list(
        HistorialPassword.objects.filter(usuario=usuario)
        .order_by("-creado_en", "-id")
        .values_list("pk", flat=True)[: settings.HISTORIAL_PASSWORDS]
    )
    HistorialPassword.objects.filter(usuario=usuario).exclude(pk__in=conservar).delete()


def _fue_usada_recientemente(usuario, nueva: str) -> bool:
    hashes = HistorialPassword.objects.filter(usuario=usuario).values_list(
        "password_hash", flat=True
    )
    return any(check_password(nueva, hash_guardado) for hash_guardado in hashes)


def exigir_no_reutilizada(usuario, nueva: str) -> None:
    """La nueva no puede ser la actual ni una de las últimas ``HISTORIAL_PASSWORDS``."""
    if usuario.check_password(nueva) or _fue_usada_recientemente(usuario, nueva):
        raise PasswordReutilizada()


@transaction.atomic
def establecer_password(usuario, nueva: str, *, debe_cambiar: bool = False) -> None:
    """Fija una contraseña ya validada y la registra en el historial."""
    usuario.set_password(nueva)
    usuario.debe_cambiar_password = debe_cambiar
    usuario.password_cambiada_en = timezone.now()
    usuario.save(update_fields=["password", "debe_cambiar_password", "password_cambiada_en"])
    _registrar_en_historial(usuario)


@transaction.atomic
def cambiar_password(usuario, *, actual: str, nueva: str, sesion_actual_id=None) -> int:
    """Cambia la contraseña del propio usuario y cierra sus OTRAS sesiones.

    Devuelve cuántas sesiones se cerraron. ``ValidationError`` de Django si la nueva
    no cumple los validadores (el manejador de errores la convierte en 400).
    """
    if not usuario.check_password(actual):
        raise PasswordActualIncorrecta()
    validate_password(nueva, usuario)
    exigir_no_reutilizada(usuario, nueva)
    establecer_password(usuario, nueva)
    cerradas = sesiones.revocar_sesiones_de_usuario(
        usuario, MotivoRevocacion.CAMBIO_PASSWORD, excepto_id=sesion_actual_id
    )
    registrar(
        "password.cambiada",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        usuario_id=usuario.pk,
        organizacion_id=usuario.organizacion_id,
        resumen="El usuario cambió su contraseña",
        detalle={"sesiones_cerradas": cerradas},
    )
    return cerradas
