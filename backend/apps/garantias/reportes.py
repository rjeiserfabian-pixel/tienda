"""Reportes de garantías de UNA empresa: cómo están, qué falla más y cuánto cuestan los cambios."""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from apps.inventario.models import LineaMovimiento

from .models import EstadoGarantia, EstadoReclamo, Garantia, ReclamoGarantia, Resolucion

POR_VENCER_DIAS = 30
TOP_PRODUCTOS = 10
SIN_MARCA = "Sin marca"


def _tasa(reclamadas: Decimal, vendidas: Decimal) -> float | None:
    """Qué porcentaje de lo vendido volvió con reclamo (``None`` si no se vendió nada)."""
    if not vendidas:
        return None
    return round(float(reclamadas) / float(vendidas) * 100, 1)


def _entero(valor) -> int:
    return int(valor or 0)


def situacion_actual(empresa_id: int, hoy: date) -> dict:
    """Cuántas garantías hay en cada situación, hoy."""
    base = Garantia.objects.filter(empresa_id=empresa_id)
    limite = hoy + timedelta(days=POR_VENCER_DIAS)
    activas = Q(estado=EstadoGarantia.ACTIVA)
    return base.aggregate(
        vigentes=Count("id", filter=activas & Q(vence_el__gt=limite)),
        por_vencer=Count("id", filter=activas & Q(vence_el__gte=hoy, vence_el__lte=limite)),
        vencidas=Count("id", filter=activas & Q(vence_el__lt=hoy)),
        anuladas=Count("id", filter=Q(estado=EstadoGarantia.ANULADA)),
        reemplazadas=Count("id", filter=Q(estado=EstadoGarantia.REEMPLAZADA)),
    )


def resumen(
    empresa_id: int, desde: date, hasta: date, *, ver_costos: bool, hoy: date | None = None
) -> dict:
    hoy = hoy or timezone.localdate()
    vendidas = Garantia.objects.filter(
        empresa_id=empresa_id, fecha_inicio__gte=desde, fecha_inicio__lte=hasta, reemplaza_a=None
    )
    reclamos = ReclamoGarantia.objects.filter(
        empresa_id=empresa_id, fecha__gte=desde, fecha__lte=hasta
    )

    # --- falla por marca y por producto (lo vendido contra lo reclamado en el mismo periodo) ---
    ventas_por_marca = {
        (f["producto__marca__nombre"] or SIN_MARCA): f["unidades"]
        for f in vendidas.values("producto__marca__nombre").annotate(unidades=Sum("cantidad"))
    }
    reclamos_por_marca = {
        (f["garantia__producto__marca__nombre"] or SIN_MARCA): f
        for f in reclamos.values("garantia__producto__marca__nombre").annotate(
            casos=Count("id"), unidades=Sum("cantidad")
        )
    }
    por_marca = []
    for marca in sorted(set(ventas_por_marca) | set(reclamos_por_marca)):
        unidades_vendidas = ventas_por_marca.get(marca) or Decimal("0")
        fila = reclamos_por_marca.get(marca)
        unidades_reclamadas = (fila["unidades"] if fila else None) or Decimal("0")
        por_marca.append(
            {
                "marca": marca,
                "vendidas": _entero(unidades_vendidas),
                "reclamos": fila["casos"] if fila else 0,
                "reclamadas": _entero(unidades_reclamadas),
                "tasa": _tasa(unidades_reclamadas, unidades_vendidas),
            }
        )
    por_marca.sort(key=lambda f: (-f["reclamos"], f["marca"]))

    ventas_por_producto = {
        f["producto"]: f["unidades"]
        for f in vendidas.values("producto").annotate(unidades=Sum("cantidad"))
    }
    por_producto = []
    for f in (
        reclamos.values("garantia__producto", "garantia__producto__nombre")
        .annotate(casos=Count("id"), unidades=Sum("cantidad"))
        .order_by("-casos", "garantia__producto__nombre")[:TOP_PRODUCTOS]
    ):
        vendidas_producto = ventas_por_producto.get(f["garantia__producto"]) or Decimal("0")
        por_producto.append(
            {
                "producto": f["garantia__producto__nombre"],
                "reclamos": f["casos"],
                "reclamadas": _entero(f["unidades"]),
                "vendidas": _entero(vendidas_producto),
                "tasa": _tasa(f["unidades"] or Decimal("0"), vendidas_producto),
            }
        )

    # --- cómo se atienden los reclamos ---
    por_estado = {r["estado"]: r["n"] for r in reclamos.values("estado").annotate(n=Count("id"))}
    cerrados = reclamos.filter(estado__in=[EstadoReclamo.RESUELTO, EstadoReclamo.RECHAZADO])
    promedio = cerrados.aggregate(
        dias=Avg(F("resuelto_el") - F("fecha")),
    )["dias"]
    por_resolucion = {
        r["resolucion"]: r["n"]
        for r in reclamos.exclude(resolucion="").values("resolucion").annotate(n=Count("id"))
    }

    # --- lo que se envió a proveedores (RMA) ---
    proveedores = [
        {
            "proveedor": f["proveedor__nombre"],
            "enviados": f["enviados"],
            "con_respuesta": f["con_respuesta"],
        }
        for f in reclamos.filter(proveedor__isnull=False)
        .values("proveedor__nombre")
        .annotate(
            enviados=Count("id"),
            con_respuesta=Count("id", filter=Q(respondido_proveedor_el__isnull=False)),
        )
        .order_by("-enviados", "proveedor__nombre")
    ]

    # --- cuánto costaron los cambios (solo para quien puede ver costos) ---
    cambios = reclamos.filter(resolucion=Resolucion.CAMBIADO)
    costo_cambios = None
    if ver_costos:
        costo_cambios = str(
            LineaMovimiento.objects.filter(
                movimiento_id__in=cambios.exclude(movimiento=None).values("movimiento_id")
            ).aggregate(
                total=Sum(ExpressionWrapper(F("costo_total"), output_field=DecimalField()))
            )["total"]
            or Decimal("0.00")
        )

    return {
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "situacion": situacion_actual(empresa_id, hoy),
        "vendidas": _entero(vendidas.aggregate(n=Sum("cantidad"))["n"]),
        "reclamos": {
            "total": reclamos.count(),
            "abiertos": reclamos.exclude(
                estado__in=[EstadoReclamo.RESUELTO, EstadoReclamo.RECHAZADO]
            ).count(),
            "por_estado": por_estado,
            "por_resolucion": por_resolucion,
            "dias_promedio": round(promedio.total_seconds() / 86400, 1)
            if promedio is not None
            else None,
        },
        "por_marca": por_marca,
        "por_producto": por_producto,
        "proveedores": proveedores,
        "cambios": {"cantidad": cambios.count(), "costo": costo_cambios},
    }
