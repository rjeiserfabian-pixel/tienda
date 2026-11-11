"""Crédito de los clientes: cuánto deben y cuánto más se les puede vender.

La deuda de un cliente es lo que falta cobrar de TODAS sus ventas a crédito vigentes, en cualquiera
de las empresas de la organización, expresada en soles (lo vendido en dólares se convierte con el
tipo de cambio de su venta). El límite es único por cliente y también es en soles.
"""

from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from apps.mantenimiento.models import Cliente

from .exceptions import LimiteDeCreditoExcedido, VentaInvalida
from .models import ComprobanteVenta, CuotaVenta

CERO = Decimal("0")
DOS = Decimal("0.01")


def deuda_en_soles(cliente: Cliente) -> Decimal:
    """Lo que el cliente debe hoy en todas las empresas, en soles."""
    pendiente = ExpressionWrapper(
        (F("monto") - F("pagado")) * F("comprobante__venta__tipo_cambio"),
        output_field=DecimalField(max_digits=22, decimal_places=6),
    )
    total = (
        CuotaVenta.objects.sin_ambito()
        .filter(
            comprobante__venta__cliente=cliente,
            comprobante__estado=ComprobanteVenta.Estado.EMITIDO,
            pagado__lt=F("monto"),
        )
        .aggregate(total=Sum(pendiente))["total"]
    )
    return (total or CERO).quantize(DOS)


def situacion(cliente: Cliente) -> dict:
    """Límite, deuda y lo que todavía se le puede vender (todo en soles).

    Sin tope, ``limite`` y ``disponible`` son ``None``: se le vende a crédito sin límite.
    """
    deuda = deuda_en_soles(cliente)
    if cliente.credito_sin_limite:
        return {"limite": None, "sin_limite": True, "deuda": deuda, "disponible": None}
    return {
        "limite": cliente.limite_credito,
        "sin_limite": False,
        "deuda": deuda,
        "disponible": max(cliente.limite_credito - deuda, CERO),
    }


def tiene_credito(cliente: Cliente) -> bool:
    """¿Tiene crédito autorizado, con tope o sin él?"""
    return cliente.credito_sin_limite or cliente.limite_credito > 0


def exigir_limite(cliente: Cliente, nuevo_en_soles: Decimal, *, puede_exceder: bool) -> None:
    """Lanza un error claro si el crédito no está autorizado o la venta pasa el límite."""
    if puede_exceder:
        return
    if not tiene_credito(cliente):
        raise VentaInvalida(f"{cliente.nombre} no tiene crédito autorizado.")
    if cliente.credito_sin_limite:
        return
    datos = situacion(cliente)
    if nuevo_en_soles > datos["disponible"]:
        raise LimiteDeCreditoExcedido(
            f"{cliente.nombre} tiene un límite de S/ {datos['limite']:,.2f} y ya debe "
            f"S/ {datos['deuda']:,.2f}: solo se le pueden vender S/ {datos['disponible']:,.2f} "
            "más a crédito."
        )
