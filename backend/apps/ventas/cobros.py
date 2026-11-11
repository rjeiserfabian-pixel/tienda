"""Reparto del cobro entre los comprobantes de una venta: cálculo puro.

El cliente paga una sola vez, pero cada empresa debe cobrar lo suyo en su propia caja o cuenta.
Los cobros se aplican en el orden en que se dieron y los comprobantes en el suyo (la empresa
principal primero): cada cobro llena lo que falta del primer comprobante y, si le sobra, sigue con
el siguiente. Así la suma de lo cobrado en cada comprobante es exactamente su total, sin céntimos
perdidos, y un mismo cobro puede partirse entre dos empresas.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from apps.compras.calculo import repartir_por_peso

from .exceptions import VentaInvalida

CERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class Fragmento:
    comprobante: int  # posición del comprobante
    cobro: int  # posición del cobro que dio el cliente
    monto: Decimal


def repartir_cobros(totales: Sequence[Decimal], montos: Sequence[Decimal]) -> list[Fragmento]:
    """Reparte ``montos`` (lo cobrado) entre los comprobantes de total ``totales``."""
    if sum(montos, CERO) != sum(totales, CERO):
        raise VentaInvalida("Los cobros deben sumar exactamente el total de la venta.")
    pendientes = list(totales)
    fragmentos: list[Fragmento] = []
    destino = 0
    for posicion, monto in enumerate(montos):
        restante = monto
        while restante > 0:
            while pendientes[destino] == 0:
                destino += 1
            parte = min(restante, pendientes[destino])
            fragmentos.append(Fragmento(destino, posicion, parte))
            pendientes[destino] -= parte
            restante -= parte
    return fragmentos


def calcular_vuelto(monto: Decimal, recibido: Decimal | None) -> Decimal:
    """Lo que se devuelve al cliente cuando entregó más efectivo de lo que pagaba."""
    if recibido is None:
        return CERO
    if recibido < monto:
        raise VentaInvalida("El efectivo recibido no alcanza para lo que se cobra.")
    return recibido - monto


def repartir_credito(totales: Sequence[Decimal], credito: Decimal) -> list[Decimal]:
    """Cuánto de cada comprobante queda a crédito: ``credito`` repartido según lo que vale cada uno.

    Cada empresa financia lo suyo en proporción a su comprobante (método del mayor resto: la suma
    es exacta). Lo que no queda a crédito es lo que se paga al momento.
    """
    total = sum(totales, CERO)
    if credito <= 0 or credito > total:
        raise VentaInvalida("Lo que queda a crédito debe ser mayor que cero y no pasar del total.")
    partes = repartir_por_peso(credito, totales)
    if any(parte > t for parte, t in zip(partes, totales, strict=True)):
        raise VentaInvalida("El pago inicial es muy pequeño para repartirlo entre las empresas.")
    return partes
