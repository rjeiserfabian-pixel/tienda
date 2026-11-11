"""Entregar el equipo: cobrar el presupuesto aprobado y cerrar la orden, todo en un solo paso.

El cobro es una venta de Ventas armada con las líneas del presupuesto: un comprobante por cada
empresa que participó (la de la orden factura el servicio y lo que ella surtió; la otra, lo suyo).
Los repuestos ya salieron del almacén cuando empezó el trabajo, así que la venta no vuelve a
descontarlos: solo los cobra y toma el costo real con que salieron.
"""

import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import TipoProducto
from apps.ventas.models import Venta
from apps.ventas.servicios import CobroEntrada, LineaEntrada, registrar_venta

from . import adelantos, servicios
from . import presupuesto as presupuestos
from .exceptions import OrdenInvalida, RepuestosPendientes, TransicionInvalida
from .models import (
    ComisionTecnico,
    EstadoOrden,
    EstadoRepuesto,
    HistorialEstado,
    OrdenServicio,
    PresupuestoOrden,
    RepuestoOrden,
)

logger = logging.getLogger(__name__)

MOTIVO_MINIMO = 5


def _llego_de_terminado(orden: OrdenServicio) -> bool:
    """¿Está listo porque se terminó el servicio? (y no porque se devuelve sin reparar)."""
    ultimo = (
        HistorialEstado.objects.filter(orden=orden, estado_nuevo=EstadoOrden.LISTO_ENTREGA)
        .order_by("-id")
        .first()
    )
    return ultimo is not None and ultimo.estado_anterior == EstadoOrden.TERMINADO


def a_cobrar(orden: OrdenServicio) -> PresupuestoOrden | None:
    """El presupuesto que se cobra al entregar, o ``None`` si esta entrega no cobra nada."""
    if orden.es_garantia:
        return None  # un reingreso por garantía no se cobra
    vigente = presupuestos.vigente_de(orden)
    if (
        vigente is None
        or not vigente.aprobado
        or vigente.venta_id is not None
        or vigente.proforma.total <= 0
        or not _llego_de_terminado(orden)
    ):
        return None
    return vigente


def _lineas_de_cobro(vigente: PresupuestoOrden) -> list[LineaEntrada]:
    repuestos = {r.linea_id: r for r in vigente.repuestos.all()}
    lineas = []
    for ln in vigente.proforma.lineas.select_related("producto", "afectacion", "empresa").order_by(
        "orden"
    ):
        r: RepuestoOrden | None = repuestos.get(ln.pk)
        if r is not None and r.estado != EstadoRepuesto.CONSUMIDO:
            raise RepuestosPendientes(
                f"El repuesto «{ln.producto.nombre}» todavía no se usó en el trabajo: "
                "no se puede cobrar."
            )
        lineas.append(
            LineaEntrada(
                producto=ln.producto,
                cantidad=ln.cantidad,
                empresa=ln.empresa,
                # El precio que el cliente aprobó, sin IGV, tal como se presupuestó.
                precio_unitario=ln.precio_unitario,
                afectacion=ln.afectacion.codigo,
                stock_ya_descontado=r is not None,
                costo_total=r.costo_total if r is not None else None,
            )
        )
    return lineas


def _quien_recoge(orden: OrdenServicio, nombre: str, documento: str, es_titular: bool):
    """Quién se lleva el equipo. El titular puede ir sin datos (son los del cliente)."""
    nombre = " ".join((nombre or "").split())[:120]
    documento = "".join((documento or "").split()).upper()[:20]
    if es_titular:
        return (
            nombre or orden.cliente.nombre[:120],
            documento or orden.cliente.numero_documento,
            True,
        )
    if len(nombre) < 3:
        raise OrdenInvalida("Indique el nombre de quien recoge el equipo.")
    if len(documento) < 6:
        raise OrdenInvalida("Indique el documento de quien recoge el equipo (no es el titular).")
    return (nombre, documento, False)


def _congelar_comision(orden: OrdenServicio, vigente: PresupuestoOrden) -> None:
    """Anota la comisión del técnico sobre la mano de obra que se acaba de cobrar."""
    if orden.tecnico_id is None:
        return
    base = sum(
        (
            ln.valor_venta
            for ln in vigente.proforma.lineas.select_related("producto")
            if ln.producto.tipo == TipoProducto.SERVICIO
        ),
        Decimal("0"),
    )
    fila = ComisionTecnico.objects.filter(personal_id=orden.tecnico_id).first()
    porcentaje = fila.porcentaje if fila else Decimal("0")
    orden.comision_base = base
    orden.comision_porcentaje = porcentaje
    orden.comision_monto = (base * porcentaje / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    orden.save(update_fields=["comision_base", "comision_porcentaje", "comision_monto"])


def dias_de_garantia(orden: OrdenServicio) -> int:
    """Los días de garantía del servicio, si el trabajo se hizo (no si se devuelve sin reparar)."""
    if orden.es_garantia or orden.tipo_servicio_id is None or not _llego_de_terminado(orden):
        return 0
    return orden.tipo_servicio.garantia_dias


@transaction.atomic
def entregar_equipo(
    orden: OrdenServicio,
    *,
    tipo_comprobante: str = "",
    cobros: list[CobroEntrada] | None = None,
    vendedor_nombre: str,
    vendedor_id=None,
    series: dict[int, int] | None = None,
    sin_cobro: bool = False,
    motivo_sin_cobro: str = "",
    fecha: date | None = None,
    recoge_nombre: str = "",
    recoge_documento: str = "",
    recoge_es_titular: bool = True,
) -> tuple[OrdenServicio, Venta | None]:
    """Cobra lo presupuestado (si corresponde) y deja la orden «Entregado / Cerrado».

    Anota quién se lleva el equipo (el titular u otra persona con su documento) y deja corriendo
    la garantía del servicio.
    """
    actual = (
        OrdenServicio.objects.select_for_update(of=("self",))
        .select_related("empresa", "cliente", "sucursal", "tipo_servicio")
        .get(pk=orden.pk)
    )
    if actual.estado != EstadoOrden.LISTO_ENTREGA:
        raise TransicionInvalida("Solo se entrega un equipo que está listo para entrega.")
    quien = _quien_recoge(actual, recoge_nombre, recoge_documento, recoge_es_titular)
    pendiente = a_cobrar(actual)
    if pendiente is None or sin_cobro:
        adelantos.exigir_sin_pendientes(actual)  # lo que dejó el cliente no se queda sin devolver
    venta = None
    detalle = "Equipo entregado al cliente."
    if pendiente is not None and sin_cobro:
        motivo = " ".join((motivo_sin_cobro or "").split())[:500]
        if len(motivo) < MOTIVO_MINIMO:
            raise OrdenInvalida("Explique por qué se entrega sin cobrar (garantía, cortesía…).")
        pendiente.entregado_sin_cobro = motivo
        pendiente.save(update_fields=["entregado_sin_cobro"])
        detalle = f"Equipo entregado sin cobrar: {motivo}"
        registrar(
            "servicio_tecnico.entregado_sin_cobro",
            recurso_tipo="orden_servicio",
            recurso_id=actual.pk,
            empresa_id=actual.empresa_id,
            resumen=f"{actual.codigo}: entregado sin cobrar",
            detalle={"motivo": motivo, "total": str(pendiente.proforma.total)},
        )
    elif pendiente is not None:
        if not tipo_comprobante:
            raise OrdenInvalida("Elija el tipo de comprobante con que se cobra.")
        proforma = pendiente.proforma
        lineas_cobro = _lineas_de_cobro(pendiente)
        hay_ajenas = any(ln.empresa.pk != actual.empresa_id for ln in lineas_cobro)
        venta = registrar_venta(
            empresa=actual.empresa,
            fecha=fecha or timezone.localdate(),
            tipo_comprobante=tipo_comprobante,
            lineas=lineas_cobro,
            cobros_entrada=list(cobros or []),
            vendedor_nombre=vendedor_nombre,
            vendedor_id=vendedor_id,
            cliente=actual.cliente,
            moneda=proforma.moneda,
            sucursal=actual.sucursal,
            observacion=f"Orden de servicio {actual.codigo}",
            series=series,
            # El precio y las empresas ya se autorizaron al presupuestar: aquí solo se cobra.
            puede_vender_bajo_minimo=True,
            puede_vender_stock_otra_empresa=True,
            proforma=proforma,
            cobros_previos=adelantos.cobros_previos(actual),
            # Cobra siempre la empresa dueña de la orden. Lo que surtió la otra empresa ya salió de
            # su stock al usarse: Technology le debe su costo (deuda interna, se liquida al cerrar caja).
            facturar_por=actual.empresa if hay_ajenas else None,
            puede_venta_interna=hay_ajenas,
        )
        adelantos.aplicar(actual, venta)
        pendiente.venta = venta
        pendiente.save(update_fields=["venta"])
        _congelar_comision(actual, pendiente)
        numeros = ", ".join(c.numero_completo for c in venta.comprobantes.order_by("id"))
        detalle = f"Equipo entregado y cobrado. Comprobantes: {numeros}."
        registrar(
            "servicio_tecnico.cobrado",
            recurso_tipo="orden_servicio",
            recurso_id=actual.pk,
            empresa_id=actual.empresa_id,
            resumen=f"{actual.codigo}: cobrado con {numeros}",
            detalle={"venta": venta.pk, "total": str(venta.total)},
        )
    elif sin_cobro:
        raise OrdenInvalida("Esta entrega no cobra nada: no hace falta «entregar sin cobrar».")

    dias = dias_de_garantia(actual)
    hoy = fecha or timezone.localdate()
    actual.recogio_nombre, actual.recogio_documento, actual.recogio_es_titular = quien
    actual.garantia_dias = dias
    actual.garantia_hasta = hoy + timedelta(days=dias) if dias else None
    actual.save(
        update_fields=[
            "recogio_nombre",
            "recogio_documento",
            "recogio_es_titular",
            "garantia_dias",
            "garantia_hasta",
        ]
    )
    detalle = f"{detalle} Recogió {quien[0]}{'' if quien[2] else f' (DNI {quien[1]})'}."
    if dias:
        detalle += f" Garantía de {dias} días."
    servicios.cambiar_estado(actual, EstadoOrden.ENTREGADO, motivo=detalle, via_entrega=True)
    orden.estado = actual.estado
    orden.fecha_entrega = actual.fecha_entrega
    return actual, venta
