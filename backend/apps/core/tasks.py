import logging

from celery import shared_task
from django.utils import timezone

from .models import RegistroIdempotencia

logger = logging.getLogger(__name__)


@shared_task(name="core.purgar_idempotencia")
def purgar_idempotencia() -> int:
    """Elimina registros de idempotencia vencidos. Programar a diario en el VPS."""
    eliminados, _ = RegistroIdempotencia.objects.filter(expira_en__lt=timezone.now()).delete()
    logger.info("Registros de idempotencia purgados", extra={"cantidad": eliminados})
    return eliminados
