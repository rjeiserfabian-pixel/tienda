import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import InterfaceError, OperationalError
from django.utils import timezone

from .models import AuditoriaEvento

logger = logging.getLogger(__name__)


@shared_task(
    name="auditoria.registrar_evento",
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def registrar_evento(carga: dict) -> int:
    """Inserta un evento. Reintenta ante caídas momentáneas de la base de datos."""
    return AuditoriaEvento.objects.create(**carga).pk


@shared_task(name="auditoria.purgar")
def purgar() -> int:
    """Retención: elimina eventos más antiguos que ``AUDITORIA_RETENCION_DIAS``."""
    limite = timezone.now() - timedelta(days=settings.AUDITORIA_RETENCION_DIAS)
    eliminados = AuditoriaEvento.objects.purgar_anteriores(limite)
    logger.info("auditoria_purgada", extra={"cantidad": eliminados})
    return eliminados
