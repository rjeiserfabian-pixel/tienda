"""Cuota mensual de consultas a Decolecta (el plan gratuito trae 100 al mes).

El proveedor no entrega su contador por API, así que el sistema cuenta cada consulta que sale y se
detiene al llegar al límite. Es una cuenta propia (puede diferir un poco de la oficial, que está
en https://decolecta.com/profile): ``manage.py consumo_decolecta --fijar N`` la calibra.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .exceptions import CuotaAgotada
from .models import ConsumoApi

logger = logging.getLogger(__name__)


def _mes() -> str:
    return timezone.localdate().strftime("%Y-%m")


def usadas() -> int:
    fila = ConsumoApi.objects.filter(proveedor="decolecta", mes=_mes()).first()
    return fila.cantidad if fila else 0


def limite() -> int:
    return settings.DECOLECTA_LIMITE_MENSUAL


def estado() -> dict:
    gastadas, tope = usadas(), limite()
    return {"mes": _mes(), "usadas": gastadas, "limite": tope, "restantes": max(tope - gastadas, 0)}


def exigir_disponible() -> None:
    """No se llama al proveedor si ya se gastó toda la cuota del mes."""
    if usadas() >= limite():
        raise CuotaAgotada()


def hay_margen_para_lo_automatico() -> bool:
    """Lo automático se detiene antes de agotar la cuota: se reserva el resto para lo manual."""
    return usadas() < limite() * settings.TIPO_CAMBIO_UMBRAL_AUTOMATICO


@transaction.atomic
def registrar_uso(cantidad: int = 1) -> None:
    fila, _ = ConsumoApi.objects.get_or_create(proveedor="decolecta", mes=_mes())
    ConsumoApi.objects.filter(pk=fila.pk).update(cantidad=F("cantidad") + cantidad)
    gastadas = usadas()
    if gastadas >= limite() * 0.8:
        logger.warning(
            "cuota_decolecta_casi_agotada", extra={"usadas": gastadas, "limite": limite()}
        )


@transaction.atomic
def fijar(cantidad: int) -> None:
    """Calibra el contador con la cifra oficial del perfil del proveedor."""
    fila, _ = ConsumoApi.objects.get_or_create(proveedor="decolecta", mes=_mes())
    ConsumoApi.objects.filter(pk=fila.pk).update(cantidad=cantidad)
