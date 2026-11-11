import logging

from celery import shared_task
from django.conf import settings

from apps.organizacion.models import Estado, Organizacion

from . import cuota, tipo_cambio

logger = logging.getLogger(__name__)


@shared_task(name="mantenimiento.actualizar_tipo_cambio")
def actualizar_tipo_cambio() -> int:
    """Trae el tipo de cambio del día para cada organización activa.

    Solo corre si se activó a propósito (``TIPO_CAMBIO_AUTOMATICO``) y se detiene antes de gastar
    toda la cuota: el resto se reserva para las consultas de DNI y RUC.
    """
    if not cuota.hay_margen_para_lo_automatico():
        logger.warning("tipo_cambio_automatico_omitido_por_cuota", extra=cuota.estado())
        return 0
    organizaciones = list(
        Organizacion.objects.filter(estado=Estado.ACTIVO).values_list("pk", flat=True)
    )
    for organizacion_id in organizaciones:
        resultados = tipo_cambio.sincronizar(
            organizacion_id, fuentes=settings.TIPO_CAMBIO_FUENTES_AUTOMATICAS
        )
        fallidas = [r["fuente"] for r in resultados if r["estado"] == "error"]
        if fallidas:
            logger.warning(
                "tipo_cambio_incompleto",
                extra={"organizacion_id": organizacion_id, "fuentes": fallidas},
            )
    return len(organizaciones)
