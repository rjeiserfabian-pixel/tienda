"""Consultas de gastos que usan otros módulos (avisos y proyección de caja)."""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.organizacion.models import Empresa

from .models import Gasto, GastoRecurrente, PagoGasto

CERO = Decimal("0")
_DINERO = DecimalField(max_digits=16, decimal_places=2)


def por_pagar(empresa: Empresa, hasta: date | None = None):
    """Gastos vigentes con algo por pagar y vencimiento (hasta una fecha, si se indica).

    Cada gasto trae ``pagado_calc``; el saldo es ``total - pagado_calc``.
    """
    pagado = (
        PagoGasto.objects.filter(gasto=OuterRef("pk"), anulado=False)
        .order_by()
        .values("gasto")
        .annotate(s=Sum("monto"))
        .values("s")
    )
    consulta = (
        Gasto.objects.filter(
            empresa=empresa, estado=Gasto.Estado.EMITIDO, fecha_vencimiento__isnull=False
        )
        .annotate(
            pagado_calc=Coalesce(Subquery(pagado, output_field=_DINERO), CERO, output_field=_DINERO)
        )
        .filter(pagado_calc__lt=F("total"))
    )
    if hasta is not None:
        consulta = consulta.filter(fecha_vencimiento__lte=hasta)
    return consulta


def recurrentes_por_registrar(empresa: Empresa, hoy: date) -> list[GastoRecurrente]:
    """Gastos recurrentes activos a los que ya les toca (o les falta poco, según su aviso)."""
    return [
        r
        for r in GastoRecurrente.objects.filter(
            empresa=empresa, estado=GastoRecurrente.Estado.ACTIVO
        ).select_related("categoria")
        if r.proxima_fecha <= hoy + timedelta(days=r.avisar_dias)
    ]
