"""Recibir mercadería contra una orden de compra.

Una recepción es una compra normal que dice a qué orden corresponde. Aquí se decide si la compra
puede recibirse contra esa orden, a qué línea de la orden va cada línea de la compra, cuánto más se
puede recibir y qué precios difieren de lo pactado. Al registrar la compra suben las cantidades
recibidas de la orden y su estado cambia solo; al anular la compra se revierte todo.

Este módulo no importa ``servicios.py`` (es ``servicios.py`` quien lo usa), para no cruzar imports.
Las reglas:

* Solo se recibe una orden EMITIDA o RECIBIDA EN PARTE, del mismo proveedor, empresa y moneda.
* Cada línea de la compra corresponde a una línea de la orden (la que se indique o la del mismo
  producto y presentación). No se reciben productos que no estén en la orden.
* No se recibe más de lo pedido, salvo la tolerancia que fije la empresa.
* El precio del comprobante manda: si difiere del pactado solo se avisa.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.organizacion.models import ConfiguracionEmpresa, Empresa

from .exceptions import CompraInvalida
from .models import Compra, LineaCompra, LineaOrdenCompra, OrdenCompra

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CIEN = Decimal("100")
TRES = Decimal("0.001")
Estado = OrdenCompra.Estado
# Estados en los que la mercadería puede estar llegando.
EN_RECEPCION = (Estado.EMITIDA, Estado.PARCIAL, Estado.RECIBIDA)
# Estados que aceptan una recepción nueva.
RECIBE = (Estado.EMITIDA, Estado.PARCIAL)

_NO_RECIBE = {
    Estado.BORRADOR: "todavía está en borrador: emítela primero",
    Estado.PENDIENTE: "está por aprobar",
    Estado.RECIBIDA: "ya se recibió por completo",
    Estado.CERRADA: "está cerrada",
    Estado.ANULADA: "está anulada",
}


# ---------------------------------------------------------------------------
# Configuración y estado
# ---------------------------------------------------------------------------
def configuracion_de(empresa: Empresa) -> ConfiguracionEmpresa | None:
    return ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=empresa).first()


def tolerancia_de_recepcion(empresa: Empresa) -> Decimal:
    """Qué porcentaje más de lo pedido se puede recibir (0 = nada más)."""
    config = configuracion_de(empresa)
    return config.orden_compra_tolerancia if config else ZERO


def auditar_orden(accion: str, orden: OrdenCompra, resumen: str, **detalle) -> None:
    registrar(
        accion,
        recurso_tipo="orden_compra",
        recurso_id=orden.pk,
        empresa_id=orden.empresa_id,
        resumen=f"Orden de compra {orden.codigo} {resumen}",
        detalle={"estado": orden.estado, "total": orden.total, **detalle},
    )


def recalcular_estado(orden: OrdenCompra) -> OrdenCompra:
    """Pone la orden en Emitida, Recibida en parte o Recibida según lo que ya llegó.

    No toca borrador, por aprobar, cerrada ni anulada. Debe llamarse con la orden ya bloqueada,
    dentro de una transacción.
    """
    if orden.estado not in EN_RECEPCION:
        return orden
    lineas = list(LineaOrdenCompra.objects.filter(orden=orden))
    if all(ln.cantidad_recibida >= ln.cantidad for ln in lineas):
        nuevo = Estado.RECIBIDA
    elif any(ln.cantidad_recibida > 0 for ln in lineas):
        nuevo = Estado.PARCIAL
    else:
        nuevo = Estado.EMITIDA
    if nuevo != orden.estado:
        orden.estado = nuevo
        orden.save(update_fields=["estado"])
        auditar_orden(
            "compras.orden_estado_recepcion", orden, f"pasó a «{orden.get_estado_display()}»"
        )
    return orden


def _maximo_recibible(linea: LineaOrdenCompra, tolerancia: Decimal) -> Decimal:
    tope = (linea.cantidad * (Decimal(1) + tolerancia / CIEN)).quantize(TRES)
    return max(tope - linea.cantidad_recibida, ZERO)


def pendiente_de_recibir(orden: OrdenCompra) -> list[dict]:
    """Por línea: lo pedido, lo recibido, lo que falta y lo máximo que aún se puede recibir.

    El máximo suma la tolerancia de la empresa a lo pedido (0 % = nada más que lo pedido).
    """
    tolerancia = tolerancia_de_recepcion(orden.empresa)
    return [
        {
            "linea": ln.pk,
            "producto": ln.producto_id,
            "unidad": ln.unidad,
            "pedido": ln.cantidad,
            "recibido": ln.cantidad_recibida,
            "pendiente": ln.pendiente,
            "maximo_recibible": _maximo_recibible(ln, tolerancia),
        }
        for ln in LineaOrdenCompra.objects.filter(orden=orden).select_related("producto")
    ]


def tiene_recepciones(orden: OrdenCompra) -> bool:
    """Si ya llegó algo de la orden: hay lo recibido en sus líneas o una compra vigente enlazada."""
    return (
        LineaOrdenCompra.objects.filter(orden=orden, cantidad_recibida__gt=0).exists()
        or Compra.objects.filter(orden=orden, estado=Compra.Estado.EMITIDO).exists()
    )


# ---------------------------------------------------------------------------
# Antes de registrar la compra
# ---------------------------------------------------------------------------
def vincular_lineas(
    orden: OrdenCompra,
    *,
    empresa: Empresa,
    proveedor,
    moneda: str,
    fecha_emision,
    entradas: Sequence,
) -> list[LineaOrdenCompra]:
    """Valida que la compra pueda recibirse contra la orden y devuelve, por cada línea de la
    compra (en el mismo orden), la línea de la orden a la que corresponde.

    ``entradas`` son las ``LineaEntrada`` de la compra (producto, presentación, cantidad y,
    opcionalmente, ``linea_orden`` con el id de la línea de la orden).
    """
    if orden.empresa_id != empresa.pk:
        raise CompraInvalida("La orden de compra no pertenece a la empresa.")
    if orden.proveedor_id != proveedor.pk:
        raise CompraInvalida(f"La orden {orden.codigo} es de otro proveedor.")
    if orden.estado not in RECIBE:
        razon = _NO_RECIBE.get(orden.estado, "no admite recepciones")
        raise CompraInvalida(f"La orden {orden.codigo} {razon}.")
    if orden.moneda != moneda:
        raise CompraInvalida(f"La orden {orden.codigo} está en otra moneda que la compra.")
    if fecha_emision < orden.fecha_emision:
        raise CompraInvalida("La compra no puede ser anterior a la orden de compra.")

    lineas = {ln.pk: ln for ln in LineaOrdenCompra.objects.filter(orden=orden)}
    por_producto = {(ln.producto_id, ln.presentacion_id): ln for ln in lineas.values()}
    elegidas: list[LineaOrdenCompra] = []
    for entrada in entradas:
        clave = (entrada.producto.pk, entrada.presentacion.pk if entrada.presentacion else None)
        indicada = getattr(entrada, "linea_orden", None)
        if indicada is not None:
            linea = lineas.get(indicada)
            if linea is None:
                raise CompraInvalida(f"Una línea no pertenece a la orden {orden.codigo}.")
            if (linea.producto_id, linea.presentacion_id) != clave:
                raise CompraInvalida(
                    f"{entrada.producto.nombre}: no coincide con la línea de la orden "
                    "(distinto producto o presentación)."
                )
        else:
            linea = por_producto.get(clave)
            if linea is None:
                hay_otra = any(k[0] == clave[0] for k in por_producto)
                raise CompraInvalida(
                    f"{entrada.producto.nombre}: "
                    + (
                        "la orden lo pide en otra presentación."
                        if hay_otra
                        else f"no está en la orden {orden.codigo}."
                    )
                )
        elegidas.append(linea)

    # Lo que llegaría en total por cada línea de la orden, con lo ya recibido y la tolerancia.
    tolerancia = tolerancia_de_recepcion(empresa)
    llegaria: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for entrada, linea in zip(entradas, elegidas, strict=True):
        llegaria[linea.pk] += entrada.cantidad
    for pk, cantidad in llegaria.items():
        linea = lineas[pk]
        maximo = _maximo_recibible(linea, tolerancia)
        if cantidad > maximo:
            nombre = linea.producto.nombre
            raise CompraInvalida(
                f"{nombre}: se pidieron {linea.cantidad:f}, ya llegaron "
                f"{linea.cantidad_recibida:f} y como máximo se pueden recibir {maximo:f} más."
            )
    return elegidas


def _neto(precio: Decimal, tasa: Decimal, incluye_igv: bool) -> Decimal:
    return precio / (Decimal(1) + tasa / CIEN) if incluye_igv else precio


def avisos_de_precio(
    orden: OrdenCompra,
    vinculos: Sequence[LineaOrdenCompra],
    entradas: Sequence,
    tasas: Sequence[Decimal],
    precios_incluyen_igv: bool,
) -> list[dict]:
    """Líneas cuyo precio sin IGV difiere del pactado en la orden (el del comprobante manda).

    Los dos precios se llevan a «sin IGV» antes de compararlos, para no avisar cuando solo cambia
    la forma de escribirlos (uno con IGV y el otro sin).
    """
    avisos = []
    for entrada, linea, tasa in zip(entradas, vinculos, tasas, strict=True):
        facturado = _neto(entrada.precio_unitario, tasa, precios_incluyen_igv)
        pactado = _neto(linea.precio_unitario, linea.tasa, orden.precios_incluyen_igv)
        diferencia = (facturado - pactado).quantize(Decimal("0.0001"))
        if diferencia == 0:
            continue
        porcentaje = (diferencia / pactado * CIEN).quantize(Decimal("0.01")) if pactado else None
        avisos.append(
            {
                "linea_orden": linea.pk,
                "producto": entrada.producto.pk,
                "producto_nombre": entrada.producto.nombre,
                "precio_pactado": linea.precio_unitario,
                "precio_facturado": entrada.precio_unitario,
                "diferencia": diferencia,  # sin IGV, por unidad
                "porcentaje": porcentaje,
            }
        )
    return avisos


# ---------------------------------------------------------------------------
# Al registrar y al anular la compra
# ---------------------------------------------------------------------------
@transaction.atomic
def aplicar_recepcion(
    orden: OrdenCompra, vinculos: Sequence[LineaOrdenCompra], entradas: Sequence
) -> None:
    """Suma lo recibido a las líneas de la orden y recalcula su estado (orden ya bloqueada)."""
    llegado: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for entrada, linea in zip(entradas, vinculos, strict=True):
        llegado[linea.pk] += entrada.cantidad
    for linea in LineaOrdenCompra.objects.select_for_update().filter(pk__in=llegado).order_by("pk"):
        linea.cantidad_recibida += llegado[linea.pk]
        linea.save(update_fields=["cantidad_recibida"])
    recalcular_estado(orden)


@transaction.atomic
def revertir_recepcion(compra: Compra) -> None:
    """Deshace lo que una compra anulada había sumado a la orden."""
    orden = OrdenCompra.objects.select_for_update().get(pk=compra.orden_id)
    devuelto: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for linea in LineaCompra.objects.filter(compra=compra, linea_orden__isnull=False):
        devuelto[linea.linea_orden_id] += linea.cantidad
    for linea in (
        LineaOrdenCompra.objects.select_for_update().filter(pk__in=devuelto).order_by("pk")
    ):
        linea.cantidad_recibida = max(linea.cantidad_recibida - devuelto[linea.pk], ZERO)
        linea.save(update_fields=["cantidad_recibida"])
    recalcular_estado(orden)
