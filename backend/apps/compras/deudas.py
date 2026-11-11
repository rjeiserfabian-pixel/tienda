"""Lo que se debe a cada proveedor: sus compras a crédito pendientes sumadas por moneda.

Un proveedor puede tener deudas en soles y en dólares: nunca se suman entre sí. Cada fila trae lo
adeudado por moneda y los datos para ordenar por urgencia: primero quien tiene cuotas vencidas
(la más atrasada arriba) y después quien vence antes.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Min, Q, QuerySet, Sum

from apps.mantenimiento.models import Proveedor

from .models import CuotaCompra

CERO = Decimal("0")
DIAS_PROXIMOS = 7


def deudas_por_proveedor(
    compras: QuerySet,
    *,
    hoy: date,
    q: str = "",
    vencimiento: str = "",
    vence_hasta: date | None = None,
) -> list[dict]:
    """Una fila por proveedor con deuda, ya ordenada. ``compras`` son las compras visibles."""
    pendiente = ExpressionWrapper(
        F("monto") - F("pagado"), output_field=DecimalField(max_digits=16, decimal_places=2)
    )
    cuotas = CuotaCompra.objects.filter(compra__in=compras, pagado__lt=F("monto"))
    if q:
        cuotas = cuotas.filter(
            Q(compra__proveedor__nombre__icontains=q)
            | Q(compra__proveedor__nombre_comercial__icontains=q)
            | Q(compra__proveedor__numero_documento__icontains=q)
        )
    filas = cuotas.values("compra__proveedor_id", "compra__moneda").annotate(
        saldo=Sum(pendiente),
        vencido=Sum(pendiente, filter=Q(fecha_vencimiento__lt=hoy)),
        por_vencer=Sum(
            pendiente,
            filter=Q(
                fecha_vencimiento__gte=hoy,
                fecha_vencimiento__lte=hoy + timedelta(days=DIAS_PROXIMOS),
            ),
        ),
        facturas=Count("compra", distinct=True),
        proximo=Min("fecha_vencimiento"),
        mas_atrasada=Min("fecha_vencimiento", filter=Q(fecha_vencimiento__lt=hoy)),
    )

    por_proveedor: dict[int, dict] = {}
    for f in filas:
        d = por_proveedor.setdefault(
            f["compra__proveedor_id"],
            {"montos": [], "facturas": 0, "proximo": None, "mas_atrasada": None},
        )
        d["montos"].append(
            {
                "moneda": f["compra__moneda"],
                "saldo": f["saldo"] or CERO,
                "vencido": f["vencido"] or CERO,
                "por_vencer_7_dias": f["por_vencer"] or CERO,
                "facturas": f["facturas"],
            }
        )
        # Las facturas de un proveedor en dos monedas son distintas: se suman.
        d["facturas"] += f["facturas"]
        d["proximo"] = min(filter(None, [d["proximo"], f["proximo"]]))
        if f["mas_atrasada"]:
            d["mas_atrasada"] = min(filter(None, [d["mas_atrasada"], f["mas_atrasada"]]))

    proveedores = {p.pk: p for p in Proveedor.objects.filter(pk__in=por_proveedor)}
    resultado = []
    for proveedor_id, d in por_proveedor.items():
        proveedor = proveedores.get(proveedor_id)
        if proveedor is None:
            continue
        con_vencido = d["mas_atrasada"] is not None
        if vencimiento == "vencidas" and not con_vencido:
            continue
        if vencimiento == "por_vencer" and con_vencido:
            continue
        if vence_hasta is not None and d["proximo"] > vence_hasta:
            continue
        resultado.append(
            {
                "proveedor": proveedor.pk,
                "proveedor_nombre": proveedor.nombre,
                "tipo_documento": proveedor.tipo_documento,
                "numero_documento": proveedor.numero_documento,
                "ciudad": proveedor.ciudad,
                "facturas": d["facturas"],
                "proximo_vencimiento": d["proximo"],
                "dias_atraso": (hoy - d["mas_atrasada"]).days if con_vencido else 0,
                "montos": sorted(d["montos"], key=lambda m: m["moneda"]),
            }
        )
    # Primero quien está más atrasado; después, quien vence antes; por último, por nombre.
    resultado.sort(
        key=lambda r: (
            0 if r["dias_atraso"] > 0 else 1,
            -r["dias_atraso"],
            r["proximo_vencimiento"],
            r["proveedor_nombre"].lower(),
        )
    )
    return resultado
