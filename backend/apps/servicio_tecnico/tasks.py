import logging

from celery import shared_task
from django.db import InterfaceError, OperationalError
from django.utils import timezone

from . import notificaciones, proveedores
from .models import EstadoNotificacion, NotificacionServicio

logger = logging.getLogger(__name__)

MAXIMO_INTENTOS = 4


@shared_task(
    bind=True,
    name="servicio_tecnico.enviar_notificacion",
    autoretry_for=(OperationalError, InterfaceError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def enviar_notificacion(self, notificacion_id: int) -> str:
    """Manda un aviso de la bandeja de salida. Se reintenta solo si el fallo es pasajero."""
    nota = (
        NotificacionServicio.objects.sin_ambito()
        .select_related("orden__cliente", "orden__empresa")
        .filter(pk=notificacion_id)
        .first()
    )
    if nota is None or nota.estado != EstadoNotificacion.PENDIENTE:
        return "omitido"  # ya salió, ya falló o no existe: enviar dos veces sería peor
    proveedor = proveedores.obtener()
    nota.intentos += 1
    try:
        externo = proveedor.enviar(
            proveedores.Mensaje(
                telefono=nota.telefono,
                evento=nota.evento,
                texto=nota.mensaje,
                parametros=notificaciones.parametros_de(nota),
            )
        )
    except proveedores.ErrorTemporal as error:
        if nota.intentos >= MAXIMO_INTENTOS:
            _cerrar(nota, EstadoNotificacion.FALLIDO, f"Se agotaron los reintentos: {error}")
            return "fallido"
        nota.detalle = str(error)[:255]
        nota.save(update_fields=["intentos", "detalle"])
        raise self.retry(exc=error, countdown=60 * 2**nota.intentos) from error
    except proveedores.ErrorProveedor as error:
        _cerrar(nota, EstadoNotificacion.FALLIDO, str(error))
        return "fallido"
    nota.estado = EstadoNotificacion.ENVIADO
    nota.externo_id = externo
    nota.enviado_en = timezone.now()
    nota.detalle = ""
    nota.save(update_fields=["estado", "externo_id", "enviado_en", "detalle", "intentos"])
    return "enviado"


def _cerrar(nota: NotificacionServicio, estado: str, detalle: str) -> None:
    nota.estado = estado
    nota.detalle = detalle[:255]
    nota.save(update_fields=["estado", "detalle", "intentos"])
    logger.warning(
        "aviso_whatsapp_fallido", extra={"notificacion_id": nota.pk, "orden_id": nota.orden_id}
    )
