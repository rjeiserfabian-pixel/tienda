"""Stock apartado para pedidos que todavía se están pagando (ver ``ReservaStock``)."""

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from django.db.models import Sum

from .models import ReservaStock


def apartado(
    almacen_ids: Iterable[int], producto_ids: Iterable[int]
) -> dict[tuple[int, int], Decimal]:
    """Lo apartado hoy: ``{(almacén, producto): cantidad}`` (solo reservas sin liberar)."""
    filas = (
        ReservaStock.objects.sin_ambito()
        .filter(
            almacen_id__in=list(almacen_ids),
            producto_id__in=list(producto_ids),
            liberada_en__isnull=True,
        )
        .values("almacen_id", "producto_id")
        .annotate(total=Sum("cantidad"))
    )
    salida: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for fila in filas:
        salida[(fila["almacen_id"], fila["producto_id"])] += fila["total"]
    return salida
