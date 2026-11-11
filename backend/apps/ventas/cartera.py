"""Lo que los clientes deben: sus ventas a crédito pendientes sumadas por moneda.

Un cliente puede tener deudas en soles y en dólares: nunca se suman entre sí. Cada fila trae lo
adeudado por moneda y los datos para ordenar por urgencia: primero quien tiene cuotas vencidas
(la más atrasada arriba) y después quien vence antes. Cada empresa ve lo suyo: se trabaja con los
comprobantes de la empresa que se consulta.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Min,
    Prefetch,
    Q,
    QuerySet,
    Sum,
)

from apps.mantenimiento.models import Cliente

from .models import ComprobanteVenta, CuotaVenta, FormaPago

CERO = Decimal("0")
DIAS_PROXIMOS = 7
_PENDIENTE = ExpressionWrapper(
    F("monto") - F("pagado"), output_field=DecimalField(max_digits=16, decimal_places=2)
)


def comprobantes_a_credito(empresa_id: int) -> QuerySet:
    """Los comprobantes vigentes de una empresa que se vendieron a crédito."""
    return ComprobanteVenta.objects.filter(
        empresa_id=empresa_id,
        estado=ComprobanteVenta.Estado.EMITIDO,
        venta__forma_pago=FormaPago.CREDITO,
    )


def _cuotas_pendientes(comprobantes: QuerySet) -> QuerySet:
    return CuotaVenta.objects.filter(comprobante__in=comprobantes, pagado__lt=F("monto"))


def deudas_por_cliente(
    comprobantes: QuerySet,
    *,
    hoy: date,
    q: str = "",
    vencimiento: str = "",
    vence_hasta: date | None = None,
) -> list[dict]:
    """Una fila por cliente con deuda, ya ordenada. ``comprobantes`` son los visibles."""
    cuotas = _cuotas_pendientes(comprobantes)
    if q:
        cuotas = cuotas.filter(
            Q(comprobante__venta__cliente_nombre__icontains=q)
            | Q(comprobante__venta__cliente_documento__icontains=q)
        )
    filas = cuotas.values("comprobante__venta__cliente_id", "comprobante__venta__moneda").annotate(
        saldo=Sum(_PENDIENTE),
        vencido=Sum(_PENDIENTE, filter=Q(fecha_vencimiento__lt=hoy)),
        por_vencer=Sum(
            _PENDIENTE,
            filter=Q(
                fecha_vencimiento__gte=hoy,
                fecha_vencimiento__lte=hoy + timedelta(days=DIAS_PROXIMOS),
            ),
        ),
        comprobantes=Count("comprobante", distinct=True),
        proximo=Min("fecha_vencimiento"),
        mas_atrasada=Min("fecha_vencimiento", filter=Q(fecha_vencimiento__lt=hoy)),
    )

    por_cliente: dict[int, dict] = {}
    for f in filas:
        d = por_cliente.setdefault(
            f["comprobante__venta__cliente_id"],
            {"montos": [], "comprobantes": 0, "proximo": None, "mas_atrasada": None},
        )
        d["montos"].append(
            {
                "moneda": f["comprobante__venta__moneda"],
                "saldo": f["saldo"] or CERO,
                "vencido": f["vencido"] or CERO,
                "por_vencer_7_dias": f["por_vencer"] or CERO,
                "comprobantes": f["comprobantes"],
            }
        )
        d["comprobantes"] += f["comprobantes"]
        d["proximo"] = min(filter(None, [d["proximo"], f["proximo"]]))
        if f["mas_atrasada"]:
            d["mas_atrasada"] = min(filter(None, [d["mas_atrasada"], f["mas_atrasada"]]))

    clientes = {c.pk: c for c in Cliente.objects.filter(pk__in=por_cliente)}
    resultado = []
    for cliente_id, d in por_cliente.items():
        cliente = clientes.get(cliente_id)
        if cliente is None:
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
                "cliente": cliente.pk,
                "cliente_nombre": cliente.nombre,
                "tipo_documento": cliente.tipo_documento,
                "numero_documento": cliente.numero_documento,
                "telefono": cliente.telefono,
                "comprobantes": d["comprobantes"],
                "proximo_vencimiento": d["proximo"],
                "dias_atraso": (hoy - d["mas_atrasada"]).days if con_vencido else 0,
                "montos": sorted(d["montos"], key=lambda m: m["moneda"]),
            }
        )
    resultado.sort(
        key=lambda r: (
            0 if r["dias_atraso"] > 0 else 1,
            -r["dias_atraso"],
            r["proximo_vencimiento"],
            r["cliente_nombre"].lower(),
        )
    )
    return resultado


def resumen(comprobantes: QuerySet, *, hoy: date) -> list[dict]:
    """Totales de lo que se debe, por moneda: todo, lo vencido y lo que vence en 7 días."""
    filas = (
        _cuotas_pendientes(comprobantes)
        .values("comprobante__venta__moneda")
        .annotate(
            saldo=Sum(_PENDIENTE),
            vencido=Sum(_PENDIENTE, filter=Q(fecha_vencimiento__lt=hoy)),
            por_vencer=Sum(
                _PENDIENTE,
                filter=Q(
                    fecha_vencimiento__gte=hoy,
                    fecha_vencimiento__lte=hoy + timedelta(days=DIAS_PROXIMOS),
                ),
            ),
            comprobantes=Count("comprobante", distinct=True),
            clientes=Count("comprobante__venta__cliente", distinct=True),
        )
        .order_by("comprobante__venta__moneda")
    )
    return [
        {
            "moneda": f["comprobante__venta__moneda"],
            "saldo": f["saldo"] or CERO,
            "vencido": f["vencido"] or CERO,
            "por_vencer_7_dias": f["por_vencer"] or CERO,
            "comprobantes": f["comprobantes"],
            "clientes": f["clientes"],
        }
        for f in filas
    ]


def _filas_de(consulta: QuerySet, *, hoy: date) -> list[dict]:
    """Cada comprobante de ``consulta`` que todavía tiene cuotas por cobrar, con su detalle."""
    consulta = consulta.select_related("venta", "empresa", "tipo_comprobante").prefetch_related(
        Prefetch("cuotas", queryset=CuotaVenta.objects.order_by("numero"))
    )
    resultado = []
    for c in consulta:
        cuotas = list(c.cuotas.all())
        pendientes = [q for q in cuotas if q.pagado < q.monto]
        if not pendientes:
            continue
        vencidas = [q for q in pendientes if q.fecha_vencimiento < hoy]
        resultado.append(
            {
                "comprobante": c,
                "cuotas": cuotas,
                "saldo": sum((q.monto - q.pagado for q in pendientes), CERO),
                "vencido": sum((q.monto - q.pagado for q in vencidas), CERO),
                "proximo": min(q.fecha_vencimiento for q in pendientes),
                "dias_atraso": (hoy - min(q.fecha_vencimiento for q in vencidas)).days
                if vencidas
                else 0,
            }
        )
    resultado.sort(key=lambda r: (-r["dias_atraso"], r["proximo"], r["comprobante"].pk))
    return resultado


def comprobantes_del_cliente(comprobantes: QuerySet, cliente_id: int, *, hoy: date) -> list[dict]:
    """Los comprobantes con deuda de un cliente, con sus cuotas, el más urgente primero."""
    return _filas_de(comprobantes.filter(venta__cliente_id=cliente_id), hoy=hoy)


def comprobantes_con_deuda(
    comprobantes: QuerySet,
    *,
    hoy: date,
    q: str = "",
    vencimiento: str = "",
    vence_hasta: date | None = None,
) -> list[dict]:
    """Todos los comprobantes con deuda (la vista «por comprobante»), el más urgente primero."""
    if q:
        condicion = (
            Q(venta__cliente_nombre__icontains=q)
            | Q(venta__cliente_documento__icontains=q)
            | Q(serie__icontains=q)
        )
        if q.isdigit() and len(q) <= 9:
            condicion |= Q(numero=int(q))
        comprobantes = comprobantes.filter(condicion)
    filas = _filas_de(comprobantes, hoy=hoy)
    if vencimiento == "vencidas":
        filas = [f for f in filas if f["dias_atraso"] > 0]
    elif vencimiento == "por_vencer":
        filas = [f for f in filas if f["dias_atraso"] == 0]
    if vence_hasta is not None:
        filas = [f for f in filas if f["proximo"] <= vence_hasta]
    return filas
