"""Traslado entre empresas: pasar mercadería de una empresa a la otra sin vender a nadie.

Es la misma operación de fondo que la venta interna (sale al costo promedio de la empresa que
entrega y entra por ese valor a la que recibe, sin margen, y las series viajan), pero sin una venta
al cliente de por medio. Queda como una ``VentaInterna`` SIN venta: así comparte la deuda interna
(la que recibe le debe el costo a la que entregó) y se liquida junto con las ventas internas al
cerrar la caja.

Puede llevar guía de remisión si la mercadería viaja a otro local (ver ``guias``); en el mismo local
no hace falta.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto_requerido
from apps.inventario import periodos
from apps.inventario.models import OrigenMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_traslado_entre_empresas
from apps.mantenimiento.models import Almacen, EstadoRegistro, Producto, TipoProducto

from . import liquidacion_interna
from .exceptions import VentaInvalida
from .models import CERO, DocumentoInterno, LineaVentaInterna, VentaInterna
from .ventas_internas import _bloquear, _nombre, _siguiente_numero, anular

MAX_LINEAS = 200


@dataclass(frozen=True, slots=True)
class LineaTraslado:
    producto: Producto
    cantidad: Decimal
    series: tuple[str, ...] = ()


def _exigir_almacen(almacen: Almacen, rol: str) -> None:
    if almacen.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida(f"El almacén {rol} ({almacen.nombre}) no está activo.")


@transaction.atomic
def registrar_traslado(
    *,
    origen: Almacen,
    destino: Almacen,
    fecha: date,
    lineas: list[LineaTraslado],
    observacion: str = "",
    documento: str = DocumentoInterno.INTERNO,
) -> VentaInterna:
    """Pasa la mercadería de ``origen`` a ``destino`` (de empresas distintas) y anota la deuda."""
    if not lineas:
        raise VentaInvalida("Agregue al menos un producto al traslado.")
    if len(lineas) > MAX_LINEAS:
        raise VentaInvalida(f"Un traslado admite hasta {MAX_LINEAS} productos.")
    if documento != DocumentoInterno.INTERNO:
        raise VentaInvalida("Por ahora el traslado se respalda con un documento interno.")
    entrega, recibe = origen.empresa, destino.empresa
    if entrega.pk == recibe.pk:
        raise VentaInvalida("Para mover mercadería dentro de la misma empresa use «Traspasar».")
    contexto = obtener_contexto_requerido()
    for empresa in (entrega, recibe):
        if not contexto.empresa_habilitada(empresa.pk):
            raise VentaInvalida(f"No tiene acceso a {_nombre(empresa)}.")
        periodos.exigir_empresa(empresa)
    _exigir_almacen(origen, "de salida")
    _exigir_almacen(destino, "de llegada")
    vistos: set[int] = set()
    for ln in lineas:
        nombre = " ".join(str(ln.producto.nombre).split())
        if ln.producto.tipo != TipoProducto.BIEN or not ln.producto.controla_stock:
            raise VentaInvalida(f"{nombre}: solo se trasladan productos con control de stock.")
        if ln.producto.pk in vistos:
            raise VentaInvalida(f"{nombre}: está repetido; sume sus cantidades en una sola línea.")
        vistos.add(ln.producto.pk)
        if ln.cantidad <= 0:
            raise VentaInvalida(f"{nombre}: la cantidad debe ser mayor que cero.")
    nota = " ".join((observacion or "").split())[:200]
    codigo = uuid.uuid4()
    salida, entrada = registrar_traslado_entre_empresas(
        origen=origen,
        destino=destino,
        fecha=fecha,
        lineas=[LineaNueva(ln.producto, ln.cantidad, series=tuple(ln.series)) for ln in lineas],
        codigo=codigo,
        observacion=nota,
        motivo=OrigenMovimiento.TRASLADO_EMPRESAS,
    )
    valores = list(salida.lineas.order_by("orden", "id"))
    for ln, valor in zip(lineas, valores, strict=True):
        if valor.costo_total <= 0:
            raise VentaInvalida(
                f"{ln.producto.nombre}: no tiene costo en {_nombre(entrega)}; el traslado "
                "saldría en cero. Registre su compra o ajuste el costo primero."
            )
    total = sum((v.costo_total for v in valores), CERO)
    interna = VentaInterna.objects.create(
        empresa=entrega,
        empresa_destino=recibe,
        codigo=codigo,
        numero=_siguiente_numero(entrega),
        fecha=fecha,
        venta=None,
        sucursal=origen.sucursal,
        observacion=nota,
        documento=documento,
        total_costo=total,
    )
    LineaVentaInterna.objects.bulk_create(
        [
            LineaVentaInterna(
                empresa=entrega,
                venta_interna=interna,
                orden=orden,
                producto=ln.producto,
                descripcion=" ".join(str(ln.producto.nombre).split())[:250],
                cantidad=ln.cantidad,
                costo_unitario=valor.costo_unitario,
                costo_total=valor.costo_total,
                series=list(ln.series),
                almacen_origen=origen,
                almacen_destino=destino,
                movimiento_salida=salida,
                movimiento_entrada=entrada,
            )
            for orden, (ln, valor) in enumerate(zip(lineas, valores, strict=True))
        ]
    )
    liquidacion_interna.partida_de_venta(interna)
    registrar(
        "ventas.traslado_empresas_registrado",
        recurso_tipo="venta_interna",
        recurso_id=interna.pk,
        empresa_id=entrega.pk,
        resumen=(
            f"Traslado N° {interna.numero:06d}: {_nombre(entrega)} → {_nombre(recibe)}, "
            f"costo S/ {total}"
        ),
        detalle={"lineas": len(lineas), "movimiento": salida.pk},
    )
    return interna


def guia_vigente(interna: VentaInterna):
    """La guía de remisión vigente de este traslado, si ya se emitió una."""
    from .models import GuiaRemision

    salida = interna.lineas.values_list("movimiento_salida_id", flat=True).first()
    if salida is None:
        return None
    return GuiaRemision.objects.filter(
        movimiento_salida_id=salida, estado=GuiaRemision.Estado.EMITIDO
    ).first()


@transaction.atomic
def anular_traslado(interna: VentaInterna, *, motivo: str) -> VentaInterna:
    """Deshace el traslado: la mercadería vuelve a la empresa que la entregó y la deuda se compensa."""
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 3:
        raise VentaInvalida("Indique el motivo de la anulación.")
    if interna.venta_id is not None:
        raise VentaInvalida("Esta operación es parte de una venta: se anula desde la venta.")
    if interna.estado != VentaInterna.Estado.EMITIDO:
        raise VentaInvalida("El traslado ya está anulado.")
    _bloquear({interna.empresa, interna.empresa_destino}, VentaInvalida, "anularlo")
    interna = VentaInterna.objects.select_for_update(of=("self",)).get(pk=interna.pk)
    if interna.estado != VentaInterna.Estado.EMITIDO:
        raise VentaInvalida("El traslado ya está anulado.")
    guia = guia_vigente(interna)
    if guia is not None:
        raise VentaInvalida(
            f"El traslado tiene vigente la guía de remisión {guia.numero_completo}: anúlela primero."
        )
    anular(interna, motivo=motivo)
    return interna
