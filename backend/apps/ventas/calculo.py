"""Totales de un comprobante de venta: cálculo puro, sin base de datos.

Los precios no incluyen IGV. Cada línea se redondea a céntimos (``cantidad × precio``) y el IGV se
calcula sobre la suma de las líneas de la misma tasa; los céntimos que sobran o faltan van a la
línea de mayor importe, así las líneas siempre suman el total del comprobante. Es la misma regla
de redondeo que usa Compras.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from apps.compras.calculo import (
    EXONERADO,
    GRAVADO,
    IGV,
    INAFECTO,
    NINGUNO,
    EntradaLinea,
    bases_e_impuestos,
)

from .exceptions import VentaInvalida

CERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class LineaCalculada:
    valor_venta: Decimal  # base de la línea, sin IGV
    igv: Decimal
    total: Decimal


@dataclass(frozen=True, slots=True)
class TotalesComprobante:
    lineas: tuple[LineaCalculada, ...]
    op_gravada: Decimal
    op_exonerada: Decimal
    op_inafecta: Decimal
    igv: Decimal
    total: Decimal


def calcular_comprobante(lineas: Sequence[EntradaLinea]) -> TotalesComprobante:
    """Importes de cada línea y totales del comprobante (precios sin IGV)."""
    if not lineas:
        raise VentaInvalida("Agregue al menos un producto.")
    for ln in lineas:
        if ln.cantidad <= 0:
            raise VentaInvalida("La cantidad debe ser mayor que cero.")
        if ln.precio_unitario < 0:
            raise VentaInvalida("El precio no puede ser negativo.")
        if ln.grupo not in (GRAVADO, EXONERADO, INAFECTO) or ln.impuesto not in (IGV, NINGUNO):
            raise VentaInvalida("La afectación de una línea no está disponible para vender.")
        if (ln.grupo == GRAVADO) != (ln.impuesto == IGV):
            raise VentaInvalida("Una línea gravada lleva IGV; las demás, ninguno.")
    bases, impuestos = bases_e_impuestos(lineas, incluye_igv=False)
    calculadas = tuple(
        LineaCalculada(base, impuesto, base + impuesto)
        for base, impuesto in zip(bases, impuestos, strict=True)
    )

    def base_de(grupo: str) -> Decimal:
        return sum((bases[i] for i, ln in enumerate(lineas) if ln.grupo == grupo), CERO)

    igv = sum(impuestos, CERO)
    return TotalesComprobante(
        lineas=calculadas,
        op_gravada=base_de(GRAVADO),
        op_exonerada=base_de(EXONERADO),
        op_inafecta=base_de(INAFECTO),
        igv=igv,
        total=sum((c.total for c in calculadas), CERO),
    )
