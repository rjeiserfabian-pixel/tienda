"""Qué meses de comisiones ya están cerrados (y adónde van los hechos que llegan tarde)."""

from datetime import date, timedelta

from .models import LiquidacionComision


def ultimo_cerrado(organizacion_id: int) -> LiquidacionComision | None:
    return (
        LiquidacionComision.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .order_by("-periodo")
        .first()
    )


def fin_de_periodo(periodo: str) -> date:
    """El último día de «2026-11»."""
    año, mes = int(periodo[:4]), int(periodo[5:7])
    siguiente = date(año + (mes == 12), mes % 12 + 1, 1)
    return siguiente - timedelta(days=1)


def mes_cerrado(organizacion_id: int, año: int, mes: int) -> bool:
    return (
        LiquidacionComision.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, periodo=f"{año:04d}-{mes:02d}")
        .exists()
    )


def fecha_abierta(organizacion_id: int, fecha: date) -> date:
    """La fecha a la que se puede anotar algo: si el mes ya cerró, el día siguiente al cierre.

    Así una venta con fecha atrasada o un abono anulado tarde no mueven un mes ya liquidado: su
    efecto cae en el mes que sigue.
    """
    ultimo = ultimo_cerrado(organizacion_id)
    if ultimo is None:
        return fecha
    return max(fecha, fin_de_periodo(ultimo.periodo) + timedelta(days=1))
