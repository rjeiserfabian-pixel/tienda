"""Métodos de pago y cronograma de cuotas.

* ``generar_cronograma``: reparte un monto en cuotas con sus fechas de vencimiento.
* ``sembrar_catalogos_pago``: carga los métodos de pago y periodicidades iniciales.
"""

import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.auditoria.servicios import registrar

from . import pagos_datos
from .models import MedioPago, Periodicidad

logger = logging.getLogger(__name__)

CENTAVO = Decimal("0.01")
MAXIMO_CUOTAS = 60
MAXIMO_MONTO = Decimal("99999999999999.99")


@dataclass(frozen=True, slots=True)
class Cuota:
    numero: int
    fecha: date
    monto: Decimal


def _sumar_meses(base: date, meses: int) -> date:
    """``base`` más ``meses`` con el mismo día; si el mes no lo tiene, el último (31/01 → 28/02)."""
    indice = base.year * 12 + (base.month - 1) + meses
    anio, mes = divmod(indice, 12)
    mes += 1
    return date(anio, mes, min(base.day, calendar.monthrange(anio, mes)[1]))


def fecha_de_cuota(primera: date, periodicidad: Periodicidad, posicion: int) -> date:
    """Vencimiento de la cuota ``posicion`` períodos después de la primera (0 = la primera)."""
    if periodicidad.unidad == Periodicidad.Unidad.MESES:
        return _sumar_meses(primera, posicion * periodicidad.cantidad)
    return primera + timedelta(days=posicion * periodicidad.cantidad)


def generar_cronograma(
    monto: Decimal, cuotas: int, primera_fecha: date, periodicidad: Periodicidad
) -> list[Cuota]:
    """Reparte ``monto`` en ``cuotas`` partes iguales, en centavos exactos.

    Los centavos que sobran se reparten de a uno en las primeras cuotas, así que la suma da
    exactamente el monto y ninguna cuota queda en cero ni en negativo
    (1 390,99 en 4 cuotas → 347,75 + 347,75 + 347,75 + 347,74). Lanza ``ValueError`` con un
    mensaje claro si los datos no sirven.
    """
    if not isinstance(monto, Decimal) or not monto.is_finite() or monto != monto.quantize(CENTAVO):
        raise ValueError("El monto debe tener hasta 2 decimales.")
    if monto <= 0 or monto > MAXIMO_MONTO:
        raise ValueError("El monto debe ser mayor que cero.")
    if not isinstance(cuotas, int) or not (1 <= cuotas <= MAXIMO_CUOTAS):
        raise ValueError(f"Las cuotas deben ser de 1 a {MAXIMO_CUOTAS}.")
    if monto < CENTAVO * cuotas:
        raise ValueError("El monto es muy pequeño para tantas cuotas.")

    centavos = int(monto * 100)
    base, sobrantes = divmod(centavos, cuotas)
    return [
        Cuota(
            posicion + 1,
            fecha_de_cuota(primera_fecha, periodicidad, posicion),
            Decimal(base + (1 if posicion < sobrantes else 0)) / 100,
        )
        for posicion in range(cuotas)
    ]


@transaction.atomic
def sembrar_catalogos_pago(organizacion_id: int) -> dict[str, int]:
    """Agrega lo que falte; no cambia lo editado ni vuelve a crear lo que se eliminó."""
    creados = {"medios_pago": 0, "periodicidades": 0}

    existentes = {
        n.lower()
        for n in MedioPago.objects.sin_ambito(incluir_eliminados=True)
        .filter(organizacion_id=organizacion_id)
        .values_list("nombre", flat=True)
    }
    for nombre, tipo, referencia in pagos_datos.MEDIOS_DE_PAGO:
        if nombre.lower() in existentes:
            continue
        MedioPago.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            nombre=nombre,
            tipo=tipo,
            requiere_referencia=referencia,
        )
        creados["medios_pago"] += 1

    existentes = {
        n.lower()
        for n in Periodicidad.objects.sin_ambito(incluir_eliminados=True)
        .filter(organizacion_id=organizacion_id)
        .values_list("nombre", flat=True)
    }
    for nombre, unidad, cantidad in pagos_datos.PERIODICIDADES:
        if nombre.lower() in existentes:
            continue
        Periodicidad.objects.sin_ambito().create(
            organizacion_id=organizacion_id, nombre=nombre, unidad=unidad, cantidad=cantidad
        )
        creados["periodicidades"] += 1

    if any(creados.values()):
        registrar(
            "pagos.catalogos_sembrados",
            recurso_tipo="organizacion",
            recurso_id=organizacion_id,
            organizacion_id=organizacion_id,
            resumen="Se cargaron los métodos de pago y periodicidades iniciales",
            detalle=creados,
        )
        logger.info("catalogos_pago_sembrados", extra={"organizacion_id": organizacion_id})
    return creados
