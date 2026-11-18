"""Avance del mes de un vendedor: cuánto lleva vendido, en qué tramo está y qué metas cumplió.

«Lo vendido» es la venta neta del mes: lo facturado en el mes (sin IGV, en soles) menos lo
devuelto con notas de crédito, contando solo comprobantes vigentes. Sirve para elegir el tramo de
la escala y para las metas con bono.

Dos acciones se hacen UNA VEZ AL CERRAR el mes (la entrega 5): aplicar la escala (que reescribe el
porcentaje de las líneas generales de ese mes) y otorgar los bonos. Ambas son idempotentes.
"""

from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum

from apps.auditoria.servicios import registrar
from apps.ventas.models import ComprobanteVenta, LineaNotaCredito, NotaCredito

from . import calculo, periodos
from .models import BonoGanado, ComisionComprobante, EscalaComision, MetaBono
from .servicios import ReglaInvalida

CERO = Decimal("0")


def rango_del_mes(año: int, mes: int) -> tuple[date, date]:
    return date(año, mes, 1), date(año, mes, monthrange(año, mes)[1])


def periodo_de(año: int, mes: int) -> str:
    return f"{año:04d}-{mes:02d}"


def _planes(organizacion_id: int, vendedor_id, año: int, mes: int):
    inicio, fin = rango_del_mes(año, mes)
    return (
        ComisionComprobante.objects.sin_ambito()
        .select_related("comprobante__venta")
        .filter(
            empresa__organizacion_id=organizacion_id,
            vendedor_id=vendedor_id,
            fecha_venta__gte=inicio,
            fecha_venta__lte=fin,
            comprobante__estado=ComprobanteVenta.Estado.EMITIDO,
        )
    )


def ventas_netas_del_mes(organizacion_id: int, vendedor_id, año: int, mes: int) -> Decimal:
    """Lo que vendió el vendedor en el mes, sin IGV y en soles, menos lo devuelto."""
    planes = list(_planes(organizacion_id, vendedor_id, año, mes))
    if not planes:
        return CERO
    devuelto = {
        f["nota__comprobante_id"]: f["v"]
        for f in LineaNotaCredito.objects.sin_ambito()
        .filter(
            nota__estado=NotaCredito.Estado.EMITIDO,
            nota__comprobante_id__in=[p.comprobante_id for p in planes],
        )
        .values("nota__comprobante_id")
        .annotate(v=Sum("valor_venta"))
    }
    total = CERO
    for plan in planes:
        en_soles = (devuelto.get(plan.comprobante_id) or CERO) * plan.comprobante.venta.tipo_cambio
        total += plan.base_neta - en_soles
    return max(total, CERO).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- qué escala y qué metas le tocan ----------------------------------------------------------
def _vigentes(modelo, organizacion_id: int, vendedor_id, fecha: date):
    return (
        modelo.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, activa=True)
        .filter(Q(vigente_desde__isnull=True) | Q(vigente_desde__lte=fecha))
        .filter(Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha))
        .filter(Q(vendedor_id__isnull=True) | Q(vendedor_id=vendedor_id))
    )


def escala_de(organizacion_id: int, vendedor_id, fecha: date) -> EscalaComision | None:
    """La escala que rige para el vendedor ese día: la suya si la tiene y si no, la general."""
    escalas = list(_vigentes(EscalaComision, organizacion_id, vendedor_id, fecha))
    if not escalas:
        return None
    return min(escalas, key=lambda e: (e.vendedor_id is None, -e.pk))


def tramos_de(escala: EscalaComision) -> list:
    return list(escala.tramos.order_by("desde"))


def tramo_de(escala: EscalaComision, ventas: Decimal):
    """El tramo alcanzado: el más alto cuyo «desde» no supera lo vendido."""
    alcanzado = None
    for tramo in tramos_de(escala):
        if tramo.desde <= ventas:
            alcanzado = tramo
    return alcanzado


def metas_de(organizacion_id: int, vendedor_id, fecha: date) -> list[MetaBono]:
    return list(_vigentes(MetaBono, organizacion_id, vendedor_id, fecha).order_by("meta", "id"))


# --- el avance --------------------------------------------------------------------------------
def avance(organizacion_id: int, vendedor_id, año: int, mes: int) -> dict:
    inicio, fin = rango_del_mes(año, mes)
    ventas = ventas_netas_del_mes(organizacion_id, vendedor_id, año, mes)
    escala = escala_de(organizacion_id, vendedor_id, fin)
    datos_escala = None
    if escala is not None:
        tramos = tramos_de(escala)
        actual = tramo_de(escala, ventas)
        siguiente = next((t for t in tramos if t.desde > ventas), None)
        datos_escala = {
            "nombre": escala.nombre,
            "porcentaje": str(actual.porcentaje) if actual else None,
            "siguiente": (
                {
                    "desde": str(siguiente.desde),
                    "porcentaje": str(siguiente.porcentaje),
                    "falta": str(siguiente.desde - ventas),
                }
                if siguiente
                else None
            ),
        }
    otorgados = {
        b.meta_id: b
        for b in BonoGanado.objects.sin_ambito().filter(
            organizacion_id=organizacion_id,
            vendedor_id=vendedor_id,
            periodo=periodo_de(año, mes),
        )
    }
    metas = [
        {
            "id": m.pk,
            "nombre": m.nombre,
            "meta": str(m.meta),
            "bono": str(m.bono),
            "cumplida": ventas >= m.meta,
            "falta": str(max(m.meta - ventas, CERO)),
            "otorgado": m.pk in otorgados,
        }
        for m in metas_de(organizacion_id, vendedor_id, fin)
    ]
    return {
        "periodo": periodo_de(año, mes),
        "desde": inicio.isoformat(),
        "hasta": fin.isoformat(),
        "ventas": str(ventas),
        "escala": datos_escala,
        "metas": metas,
    }


# --- al cerrar el mes -------------------------------------------------------------------------
@transaction.atomic
def aplicar_escala_del_mes(
    organizacion_id: int, vendedor_id, año: int, mes: int, *, fecha: date | None = None
) -> int:
    """Fija el porcentaje de la escala en las líneas generales del mes.

    Devuelve cuántos comprobantes cambió. ``fecha`` es el día al que se anotan los ajustes (por
    defecto, el último día del mes).
    """
    _, fin = rango_del_mes(año, mes)
    fecha = fecha or fin
    if periodos.mes_cerrado(organizacion_id, año, mes):
        raise ReglaInvalida("Ese mes ya está cerrado: la escala ya no se cambia.")
    ventas = ventas_netas_del_mes(organizacion_id, vendedor_id, año, mes)
    escala = escala_de(organizacion_id, vendedor_id, fin)
    tramo = tramo_de(escala, ventas) if escala else None
    porcentaje = tramo.porcentaje if tramo else None
    tocados = 0
    for plan in _planes(organizacion_id, vendedor_id, año, mes).select_for_update(of=("self",)):
        if calculo.aplicar_porcentaje_de_escala(plan, porcentaje):
            calculo.recalcular(plan.comprobante, hoy=fecha)
            tocados += 1
    if tocados:
        registrar(
            "comisiones.escala_aplicada",
            recurso_tipo="vendedor",
            recurso_id=str(vendedor_id),
            organizacion_id=organizacion_id,
            resumen=(
                f"Escala del mes {periodo_de(año, mes)} aplicada: {porcentaje or 'sin escala'} %"
            ),
            detalle={"ventas": str(ventas), "porcentaje": str(porcentaje), "comprobantes": tocados},
        )
    return tocados


@transaction.atomic
def otorgar_bonos_del_mes(
    organizacion_id: int, vendedor_id, año: int, mes: int, *, fecha: date | None = None
) -> list[BonoGanado]:
    """Otorga los bonos de las metas cumplidas (uno por meta y mes). Devuelve los nuevos."""
    _, fin = rango_del_mes(año, mes)
    if periodos.mes_cerrado(organizacion_id, año, mes):
        raise ReglaInvalida("Ese mes ya está cerrado: los bonos ya no se otorgan.")
    ventas = ventas_netas_del_mes(organizacion_id, vendedor_id, año, mes)
    nuevos = []
    for meta in metas_de(organizacion_id, vendedor_id, fin):
        if ventas < meta.meta:
            continue
        bono, creado = BonoGanado.objects.sin_ambito().get_or_create(
            organizacion_id=organizacion_id,
            vendedor_id=vendedor_id,
            periodo=periodo_de(año, mes),
            meta=meta,
            defaults={
                "nombre": meta.nombre,
                "ventas_mes": ventas,
                "monto": meta.bono,
                "fecha": fecha or fin,
            },
        )
        if creado:
            nuevos.append(bono)
            registrar(
                "comisiones.bono_otorgado",
                recurso_tipo="bono_ganado",
                recurso_id=bono.pk,
                organizacion_id=organizacion_id,
                resumen=(
                    f"Bono «{meta.nombre}» de {meta.bono} por vender {ventas} en {bono.periodo}"
                ),
                detalle={"vendedor": str(vendedor_id), "ventas": str(ventas)},
            )
    return nuevos
