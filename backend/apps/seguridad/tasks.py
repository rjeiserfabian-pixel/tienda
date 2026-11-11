import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.seguridad.models import Sesion, TokenRecuperacion

logger = logging.getLogger(__name__)


@shared_task(name="seguridad.enviar_recuperacion")
def enviar_recuperacion(identificador: str, ip: str | None = None) -> bool:
    """Crea el token y envía el correo fuera de la petición (ver ``services.recuperacion``)."""
    from apps.seguridad.services import recuperacion

    return recuperacion.procesar_solicitud(identificador, ip)


@shared_task(name="seguridad.purgar_sesiones")
def purgar_sesiones() -> dict:
    """Retención: borra sesiones revocadas o vencidas hace más de ``SESIONES_RETENCION_DIAS``
    y los tokens de recuperación ya vencidos o usados."""
    limite = timezone.now() - timedelta(days=settings.SESIONES_RETENCION_DIAS)
    sesiones, _ = Sesion.objects.filter(
        Q(revocada=True, revocada_en__lt=limite) | Q(expira_en__lt=limite)
    ).delete()
    tokens, _ = TokenRecuperacion.objects.filter(
        Q(expira_en__lt=timezone.now()) | Q(usado_en__isnull=False)
    ).delete()
    logger.info("sesiones_purgadas", extra={"sesiones": sesiones, "tokens": tokens})
    return {"sesiones": sesiones, "tokens": tokens}
