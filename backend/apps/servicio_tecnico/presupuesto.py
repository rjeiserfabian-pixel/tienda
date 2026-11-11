"""El presupuesto de una orden: se arma como una proforma de Ventas y el cliente lo aprueba.

Reutiliza lo que Ventas ya sabe: precios por lista, IGV según el cliente, el mínimo de venta, la
empresa que surte cada producto, la vigencia y la impresión. Cada cambio crea una versión nueva y
anula la anterior; al aprobarse se reservan los repuestos y el presupuesto deja de editarse.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto
from apps.mantenimiento.models import TipoProducto
from apps.ventas import proformas
from apps.ventas.models import Proforma
from apps.ventas.servicios import LineaEntrada

from . import repuestos, servicios
from .exceptions import OrdenInvalida, PresupuestoInvalido, TransicionInvalida
from .models import (
    EstadoOrden,
    MedioAviso,
    OrdenServicio,
    PresupuestoOrden,
    RepuestoOrden,
)

logger = logging.getLogger(__name__)

# Mientras el cliente no lo apruebe, el presupuesto se puede rehacer.
ESTADOS_EDITABLES = frozenset(
    {
        EstadoOrden.RECIBIDO,
        EstadoOrden.PENDIENTE_DIAGNOSTICO,
        EstadoOrden.EN_DIAGNOSTICO,
        EstadoOrden.DIAGNOSTICADO,
        EstadoOrden.PENDIENTE_APROBACION,
    }
)
MAXIMO_LINEAS = 60
VALIDEZ_POR_DEFECTO = 15


@dataclass(frozen=True, slots=True)
class LineaPresupuesto:
    """Un producto o servicio del presupuesto y la empresa que lo surte (o lo factura)."""

    producto: object
    cantidad: Decimal
    empresa: object
    precio_unitario: Decimal | None = None  # sin IGV; vacío = el de la lista principal


def vigente_de(orden: OrdenServicio) -> PresupuestoOrden | None:
    return (
        PresupuestoOrden.objects.filter(orden=orden, vigente=True)
        .select_related("proforma")
        .first()
    )


def lleva_stock(producto) -> bool:
    return producto.tipo == TipoProducto.BIEN and producto.controla_stock


def _validar_lineas(orden: OrdenServicio, lineas: list[LineaPresupuesto]) -> None:
    if not lineas:
        raise PresupuestoInvalido("Agregue al menos un servicio o repuesto.")
    if len(lineas) > MAXIMO_LINEAS:
        raise PresupuestoInvalido(f"Un presupuesto admite hasta {MAXIMO_LINEAS} líneas.")
    for ln in lineas:
        if not lleva_stock(ln.producto) and ln.empresa.pk != orden.empresa_id:
            raise PresupuestoInvalido(
                f"«{ln.producto.nombre}» es un servicio: lo factura la empresa de la orden."
            )
        if lleva_stock(ln.producto) and ln.producto.lleva_serie:
            raise PresupuestoInvalido(
                f"{ln.producto.nombre} lleva número de serie: por ahora no se puede usar "
                "como repuesto de un servicio."
            )


@transaction.atomic
def armar_presupuesto(
    orden: OrdenServicio,
    lineas: list[LineaPresupuesto],
    *,
    vendedor_nombre: str,
    vendedor_id=None,
    validez_dias: int = VALIDEZ_POR_DEFECTO,
    condiciones: str = "",
    puede_otra_empresa: bool = False,
    puede_bajo_minimo: bool = False,
) -> PresupuestoOrden:
    """Crea la versión nueva del presupuesto (y anula la anterior, si la había)."""
    actual = (
        OrdenServicio.objects.select_for_update(of=("self",))
        .select_related("empresa", "cliente", "sucursal", "equipo__tipo")
        .get(pk=orden.pk)
    )
    if actual.estado not in ESTADOS_EDITABLES:
        raise OrdenInvalida("El presupuesto ya fue aprobado o la orden está avanzada: no se edita.")
    _validar_lineas(actual, lineas)

    anterior = vigente_de(actual)
    if anterior is not None and anterior.aprobado:
        raise OrdenInvalida("El presupuesto ya fue aprobado: no se puede modificar.")

    nota = f"Orden de servicio {actual.codigo}. {' '.join((condiciones or '').split())}".strip()
    proforma = proformas.crear_proforma(
        empresa=actual.empresa,
        lineas=[
            LineaEntrada(
                producto=ln.producto,
                cantidad=ln.cantidad,
                empresa=ln.empresa,
                precio_unitario=ln.precio_unitario,
            )
            for ln in lineas
        ],
        vendedor_nombre=vendedor_nombre,
        vendedor_id=vendedor_id,
        cliente=actual.cliente,
        atencion=f"{actual.codigo} · {actual.equipo}"[:120],
        sucursal=actual.sucursal,
        validez_dias=validez_dias,
        condiciones=nota[:500],
        puede_vender_stock_otra_empresa=puede_otra_empresa,
        puede_vender_bajo_minimo=puede_bajo_minimo,
    )

    version = 1
    if anterior is not None:
        version = anterior.version + 1
        proformas.anular_proforma(
            anterior.proforma, motivo=f"Reemplazado por la versión {version} del presupuesto"
        )
        anterior.vigente = False
        anterior.save(update_fields=["vigente"])
    else:
        mayor = PresupuestoOrden.objects.filter(orden=actual).aggregate(m=Max("version"))["m"]
        version = (mayor or 0) + 1

    presupuesto = PresupuestoOrden.objects.create(
        empresa_id=actual.empresa_id, orden=actual, proforma=proforma, version=version
    )
    RepuestoOrden.objects.bulk_create(
        [
            RepuestoOrden(
                empresa_id=linea.empresa_id,
                presupuesto=presupuesto,
                linea=linea,
                producto=linea.producto,
                cantidad=linea.cantidad,
            )
            for linea in proforma.lineas.select_related("producto").order_by("orden")
            if lleva_stock(linea.producto)
        ]
    )
    registrar(
        "servicio_tecnico.presupuesto_armado",
        recurso_tipo="orden_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo}: presupuesto v{version} por {proforma.moneda} {proforma.total}",
        detalle={"proforma": proforma.pk, "lineas": len(lineas)},
    )
    return presupuesto


def _vigente_aprobable(orden: OrdenServicio) -> PresupuestoOrden:
    presupuesto = vigente_de(orden)
    if presupuesto is None:
        raise PresupuestoInvalido("La orden no tiene un presupuesto vigente.")
    proforma: Proforma = presupuesto.proforma
    if proforma.estado != Proforma.Estado.EMITIDO:
        raise PresupuestoInvalido("El presupuesto está anulado: arme uno nuevo.")
    if proforma.valida_hasta < timezone.localdate():
        raise PresupuestoInvalido("El presupuesto venció: arme uno nuevo con precios al día.")
    return presupuesto


@transaction.atomic
def aprobar_presupuesto(
    orden: OrdenServicio, *, medio: str, nota: str
) -> tuple[PresupuestoOrden, repuestos.ResultadoReserva]:
    """Registra la aprobación del cliente, pasa la orden a «Aprobado» y reserva los repuestos."""
    actual = OrdenServicio.objects.select_for_update(of=("self",)).get(pk=orden.pk)
    aprobable = (
        EstadoOrden.PENDIENTE_APROBACION,
        *((EstadoOrden.DIAGNOSTICADO,) if actual.es_garantia else ()),
    )
    if actual.estado not in aprobable:
        raise TransicionInvalida("Solo se aprueba un presupuesto que está pendiente de aprobación.")
    if medio not in MedioAviso.values:
        raise OrdenInvalida("Indique cómo respondió el cliente.")
    nota = " ".join((nota or "").split())[:500]
    if len(nota) < 3:
        raise OrdenInvalida("Anote cómo aprobó el cliente (por ejemplo: «Aprobó por WhatsApp»).")
    presupuesto = _vigente_aprobable(actual)

    contexto = obtener_contexto()
    presupuesto.aprobado_en = timezone.now()
    presupuesto.aprobado_por_id = contexto.usuario_id if contexto else None
    presupuesto.aprobacion_medio = medio
    presupuesto.aprobacion_nota = nota
    presupuesto.save(
        update_fields=["aprobado_en", "aprobado_por_id", "aprobacion_medio", "aprobacion_nota"]
    )
    motivo = f"Aprobó el presupuesto v{presupuesto.version} ({MedioAviso(medio).label}): {nota}"
    servicios.cambiar_estado(actual, EstadoOrden.APROBADO, motivo=motivo, via_aprobacion=True)
    reserva = repuestos.reservar_pendientes(actual)
    registrar(
        "servicio_tecnico.presupuesto_aprobado",
        recurso_tipo="orden_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo}: presupuesto v{presupuesto.version} aprobado",
        detalle={"medio": medio, "total": str(presupuesto.proforma.total)},
    )
    orden.estado = actual.estado
    return presupuesto, reserva
