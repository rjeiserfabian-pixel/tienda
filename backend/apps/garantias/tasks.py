import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="garantias.avisar_por_vencer")
def avisar_por_vencer() -> int:
    """Cada día avisa por correo a quienes tienen garantías por vencer (si el negocio lo activó)."""
    from . import avisos

    enviados = avisos.avisar_todas()
    logger.info("avisos_garantia_enviados", extra={"cantidad": enviados})
    return enviados
