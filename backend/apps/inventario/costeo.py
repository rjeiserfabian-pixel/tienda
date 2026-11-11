"""Costo promedio ponderado: cálculo puro, sin base de datos.

Es el método del Kardex valorizado (Formato 13.1):

* Una **entrada** suma su importe al costo total y recalcula el promedio (costo total ÷ cantidad).
* Una **salida** se valoriza al promedio vigente, nunca al precio de venta; el promedio no cambia.
* El costo total manda: el promedio siempre se deriva de él, así no se acumulan errores de
  redondeo. Cuando una salida deja el saldo en cero, el costo total también queda en cero.
* No existe stock negativo.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .exceptions import StockInsuficiente

DOS = Decimal("0.01")
SEIS = Decimal("0.000001")
CERO = Decimal("0")


def a_dos(valor: Decimal) -> Decimal:
    return valor.quantize(DOS, rounding=ROUND_HALF_UP)


def a_seis(valor: Decimal) -> Decimal:
    return valor.quantize(SEIS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Saldo:
    """Existencias de un producto en un almacén: cantidad, costo total y costo promedio."""

    cantidad: Decimal = CERO
    costo_total: Decimal = CERO
    costo_unitario: Decimal = CERO  # promedio vigente; con saldo en cero conserva el último


def aplicar_entrada(saldo: Saldo, cantidad: Decimal, importe: Decimal) -> Saldo:
    """Saldo después de ingresar ``cantidad`` unidades por un ``importe`` (en soles, sin IGV)."""
    nueva_cantidad = saldo.cantidad + cantidad
    nuevo_total = saldo.costo_total + importe
    return Saldo(nueva_cantidad, nuevo_total, a_seis(nuevo_total / nueva_cantidad))


def aplicar_salida(
    saldo: Saldo, cantidad: Decimal, importe_fijo: Decimal | None = None
) -> tuple[Saldo, Decimal]:
    """Saldo después de la salida y su importe.

    Sin ``importe_fijo`` se valoriza al costo promedio. Con él (extorno de una entrada, que debe
    restar exactamente lo que sumó) se descuenta ese valor. Si el costo no alcanza, o no hay
    unidades, lanza ``StockInsuficiente``.
    """
    if cantidad > saldo.cantidad:
        raise StockInsuficiente(
            f"hay {saldo.cantidad:f} y se necesitan {cantidad:f}.",
            detalle={"disponible": str(saldo.cantidad), "solicitado": str(cantidad)},
        )
    if cantidad == saldo.cantidad:
        importe = saldo.costo_total  # no queda valor sin unidades, ni unidades sin valor
        if importe_fijo is not None and importe_fijo > saldo.costo_total:
            raise StockInsuficiente(
                "el costo disponible no alcanza para esta salida.",
                detalle={"costo_disponible": str(saldo.costo_total)},
            )
    elif importe_fijo is not None:
        importe = importe_fijo
        if importe > saldo.costo_total:
            raise StockInsuficiente(
                "el costo disponible no alcanza para esta salida.",
                detalle={"costo_disponible": str(saldo.costo_total)},
            )
    else:
        importe = a_dos(cantidad * saldo.costo_total / saldo.cantidad)
    nueva_cantidad = saldo.cantidad - cantidad
    nuevo_total = saldo.costo_total - importe
    unitario = a_seis(nuevo_total / nueva_cantidad) if nueva_cantidad > 0 else saldo.costo_unitario
    return Saldo(nueva_cantidad, nuevo_total, unitario), importe
