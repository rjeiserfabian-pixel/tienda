"""Cuánto gana un vendedor por cada comprobante, y cómo se va ganando.

Cómo funciona (las reglas aprobadas por el dueño):

* Al VENDER se fija, línea por línea, qué porcentaje corresponde (según las reglas de ese día) y
  cuánto sería la comisión total del comprobante sobre su venta neta (sin IGV, en soles).
* La comisión se GANA AL COBRAR: lo ganado es la comisión total por la fracción ya cobrada. Al
  contado se gana todo al instante; a crédito, a medida que se cobran las cuotas.
* Una nota de crédito baja la comisión de lo devuelto y una anulación la quita toda.
* No ganan comisión: las ventas sin vendedor (la tienda web) ni las de Servicio Técnico (el
  técnico tiene su propia comisión).

Para no equivocarse con tantos casos, después de CADA hecho (venta, abono, abono anulado, nota de
crédito, anulación) se recalcula cuánto debería llevar ganado el comprobante y se anota la
DIFERENCIA como un movimiento. Así el resultado depende solo del estado actual y se corrige solo.
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.servicio_tecnico.models import PresupuestoOrden
from apps.ventas.models import (
    AbonoVenta,
    CobroVenta,
    ComprobanteVenta,
    LineaNotaCredito,
    LineaVenta,
    NotaCredito,
    ReembolsoNota,
    Venta,
)

from . import periodos, servicios
from .models import Alcance, ComisionComprobante, MovimientoComision

logger = logging.getLogger(__name__)

CERO = Decimal("0")
CENTAVO = Decimal("0.01")


def _dos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _suma(consulta, campo: str) -> Decimal:
    return consulta.aggregate(t=Sum(campo))["t"] or CERO


def gana_comision(venta: Venta) -> bool:
    """¿Esta venta puede pagar comisión? No la tienda web (sin vendedor) ni Servicio Técnico."""
    if venta.vendedor_id is None:
        return False
    if venta.proforma_id is None:
        return True
    de_servicio = PresupuestoOrden.objects.sin_ambito().filter(proforma_id=venta.proforma_id)
    return not de_servicio.exists()


# --- al vender -------------------------------------------------------------------------
def _crear_plan(venta: Venta, comprobante: ComprobanteVenta) -> ComisionComprobante:
    """Fija el porcentaje de cada línea con las reglas de HOY (la fecha de la venta)."""
    organizacion_id = comprobante.empresa.organizacion_id
    lineas = (
        LineaVenta.objects.sin_ambito()
        .select_related("producto")
        .filter(comprobante=comprobante)
        .order_by("orden", "id")
    )
    detalle, base, total = [], CERO, CERO
    for ln in lineas:
        neta = _dos(ln.valor_venta * venta.tipo_cambio)  # en soles
        resultado = servicios.porcentaje_para(
            organizacion_id,
            vendedor_id=venta.vendedor_id,
            producto=ln.producto,
            fecha=venta.fecha,
        )
        comision = _dos(neta * resultado.porcentaje / 100)
        detalle.append(
            {
                "linea": ln.pk,
                "producto": ln.producto.nombre,
                "neta": str(neta),
                "porcentaje": str(resultado.porcentaje),
                "comision": str(comision),
                "regla": resultado.texto,
                # Sin regla de producto, marca o categoría: la escala mensual puede mover su %.
                "general": resultado.regla is None or resultado.regla.alcance == Alcance.GENERAL,
            }
        )
        base += neta
        total += comision
    return ComisionComprobante.objects.sin_ambito().create(
        empresa=comprobante.empresa,
        comprobante=comprobante,
        vendedor_id=venta.vendedor_id,
        vendedor_nombre=venta.vendedor_nombre,
        fecha_venta=venta.fecha,
        base_neta=base,
        comision_total=total,
        detalle=detalle,
    )


def alta_de_venta(venta: Venta, comprobantes: list[ComprobanteVenta]) -> int:
    """Recién hecha la venta: fija su comisión y anota lo ya cobrado. Devuelve cuántos planes."""
    if not gana_comision(venta):
        return 0
    for comprobante in comprobantes:
        _crear_plan(venta, comprobante)
        recalcular(comprobante, hoy=venta.fecha)
    return len(comprobantes)


# --- lo que debería llevar ganado ---------------------------------------------------------
def _objetivo(plan: ComisionComprobante, comprobante: ComprobanteVenta, tipo_cambio: Decimal):
    """Lo que el comprobante debería llevar ganado AHORA, según su estado actual."""
    if comprobante.estado != ComprobanteVenta.Estado.EMITIDO:
        return CERO
    notas = NotaCredito.objects.sin_ambito().filter(
        comprobante=comprobante, estado=NotaCredito.Estado.EMITIDO
    )
    devuelto = {
        f["linea_venta_id"]: f["v"]
        for f in LineaNotaCredito.objects.sin_ambito()
        .filter(nota__in=notas)
        .values("linea_venta_id")
        .annotate(v=Sum("valor_venta"))
    }
    # Comisión que queda después de lo devuelto (cada línea con SU porcentaje de la venta).
    restante = CERO
    for fila in plan.detalle:
        neta = Decimal(fila["neta"]) - _dos((devuelto.get(fila["linea"]) or CERO) * tipo_cambio)
        porcentaje = Decimal(fila.get("porcentaje_aplicado", fila["porcentaje"]))
        restante += max(neta, CERO) * porcentaje / 100
    por_cobrar = comprobante.total - _suma(notas, "total")
    if por_cobrar <= CERO or restante <= CERO:
        return CERO
    cobrado = (
        _suma(CobroVenta.objects.sin_ambito().filter(comprobante=comprobante), "monto")
        + _suma(
            AbonoVenta.objects.sin_ambito().filter(comprobante=comprobante, anulado=False),
            "monto",
        )
        - _suma(ReembolsoNota.objects.sin_ambito().filter(nota__in=notas), "monto")
    )
    fraccion = min(max(cobrado / por_cobrar, CERO), Decimal("1"))
    return _dos(restante * fraccion)


def aplicar_porcentaje_de_escala(plan: ComisionComprobante, porcentaje: Decimal | None) -> bool:
    """Fija (o quita, con ``None``) el porcentaje de la escala en las líneas «generales» del plan.

    Las líneas con regla de producto, marca o categoría no se tocan. Devuelve si algo cambió; quien
    llama debe recalcular el comprobante para anotar la diferencia.
    """
    cambio = False
    total = CERO
    for fila in plan.detalle:
        if fila.get("general"):
            actual = fila.get("porcentaje_aplicado")
            if porcentaje is None:
                if actual is not None:
                    del fila["porcentaje_aplicado"]
                    cambio = True
            elif actual != str(porcentaje):
                fila["porcentaje_aplicado"] = str(porcentaje)
                cambio = True
            efectivo = Decimal(fila.get("porcentaje_aplicado", fila["porcentaje"]))
            fila["comision"] = str(_dos(Decimal(fila["neta"]) * efectivo / 100))
        total += Decimal(fila["comision"])
    if cambio:
        plan.detalle = list(plan.detalle)
        plan.comision_total = total
        plan.escala_pct = porcentaje
        plan.save(update_fields=["detalle", "comision_total", "escala_pct", "actualizado_en"])
    return cambio


@transaction.atomic
def recalcular(comprobante: ComprobanteVenta, *, hoy: date | None = None) -> Decimal:
    """Pone al día lo ganado por el comprobante. Devuelve lo que se anotó (+ sube, − baja)."""
    plan = (
        ComisionComprobante.objects.sin_ambito()
        .select_for_update(of=("self",))
        .select_related("comprobante__venta")
        .filter(comprobante_id=comprobante.pk)
        .first()
    )
    if plan is None:
        return CERO
    comprobante = ComprobanteVenta.objects.sin_ambito().get(pk=comprobante.pk)
    objetivo = _objetivo(plan, comprobante, plan.comprobante.venta.tipo_cambio)
    actual = _suma(MovimientoComision.objects.sin_ambito().filter(plan=plan), "monto")
    diferencia = objetivo - actual
    if diferencia == CERO:
        return CERO
    if comprobante.estado != ComprobanteVenta.Estado.EMITIDO:
        motivo = MovimientoComision.Motivo.ANULACION
        texto = f"Se anuló {comprobante.numero_completo}"
    elif diferencia > CERO:
        motivo = MovimientoComision.Motivo.COBRO
        texto = f"Cobro de {comprobante.numero_completo}"
    else:
        motivo = MovimientoComision.Motivo.AJUSTE
        texto = f"Ajuste de {comprobante.numero_completo} (devolución o abono anulado)"
    MovimientoComision.objects.sin_ambito().create(
        empresa=plan.empresa,
        plan=plan,
        vendedor_id=plan.vendedor_id,
        fecha=periodos.fecha_abierta(plan.empresa.organizacion_id, hoy or timezone.localdate()),
        monto=diferencia,
        motivo=motivo,
        detalle=texto[:250],
    )
    return diferencia


def ganado_por(comprobante: ComprobanteVenta) -> Decimal:
    """Lo que el comprobante lleva ganado hasta hoy."""
    return _suma(
        MovimientoComision.objects.sin_ambito().filter(plan__comprobante_id=comprobante.pk),
        "monto",
    )


# --- lo que llama Ventas ------------------------------------------------------------------
# Un fallo al calcular una comisión NO debe impedir una venta, un cobro o una devolución: se anota
# en el registro del servidor y se corrige solo en el siguiente hecho del comprobante (el cálculo
# parte siempre del estado actual). Va en su propio «savepoint» para no dañar la operación.
def alta_segura(venta: Venta, comprobantes: list[ComprobanteVenta]) -> None:
    try:
        with transaction.atomic():
            alta_de_venta(venta, comprobantes)
    except Exception:  # noqa: BLE001
        logger.exception("comision_alta_fallida", extra={"venta": venta.pk})


def recalcular_seguro(comprobante: ComprobanteVenta) -> None:
    try:
        with transaction.atomic():
            recalcular(comprobante)
    except Exception:  # noqa: BLE001
        logger.exception("comision_recalculo_fallido", extra={"comprobante": comprobante.pk})
