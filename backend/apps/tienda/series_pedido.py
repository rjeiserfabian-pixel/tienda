"""Series (número de serie o IMEI) de los pedidos de la tienda.

El cliente compra el MODELO. Al pagar se asigna sola la serie más antigua disponible del almacén
que surte (primero en entrar, primero en salir) y esa es la que sale en el comprobante. Mientras
el pedido se prepara (PAGADO o EN_PREPARACION) el almacén puede cambiar la serie si la unidad que
tomó es otra.

DECISIÓN sobre el comprobante: el comprobante ya emitido NO se edita (su detalle conserva la serie
asignada al pagar). El cambio corrige el INVENTARIO de series (la unidad que realmente salió queda
como «ya salió» y la otra vuelve al stock) y se anota en el pedido como «serie entregada»,
distinta de la «serie del comprobante». Todo cambio queda en ``CambioSerie`` y en la auditoría.
"""

import logging

from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.inventario import series as inv_series
from apps.inventario.exceptions import MovimientoInvalido
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import LineaVenta

from . import reservas
from .exceptions import PedidoInvalido
from .models import CambioSerie, HistorialPedido, LineaPedido, PedidoTienda

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado
# Hasta el despacho se puede cambiar la serie; después ya salió con el cliente.
ESTADOS_EDITABLES = (Estado.PAGADO, Estado.EN_PREPARACION)
# El cliente ve su serie solo cuando el equipo ya va hacia él.
ESTADOS_VISIBLES = (Estado.ENVIADO, Estado.LISTO_PARA_RECOJO, Estado.ENTREGADO)
MAX_MOTIVO = 200


def disponibles(almacen_ids, producto_id: int) -> int:
    """Series EN STOCK de un producto en los almacenes de la tienda, menos lo apartado."""
    ids = list(almacen_ids)
    en_stock = sum(inv_series.en_stock_por_almacen([producto_id], ids).values())
    apartado = sum(reservas.apartado(ids, [producto_id]).values())
    return max(0, int(en_stock - apartado))


def lleva_serie(linea: LineaPedido) -> bool:
    return not linea.es_envio and bool(getattr(linea.producto, "lleva_serie", False))


def entregadas(linea: LineaPedido) -> list[str]:
    """Las series que se entregan: las que cambió el almacén o, si no, las asignadas al pagar."""
    return list(linea.series_fisicas or linea.series_asignadas or [])


# ---------------------------------------------------------------------------
# Al pagar
# ---------------------------------------------------------------------------
def asignar(lineas: list[LineaPedido]) -> dict[int, list[str]]:
    """La serie más antigua disponible para cada línea que la lleva: ``{línea: [números]}``.

    Se llama DENTRO de la transacción del pago: bloquea las unidades para que dos pagos a la vez no
    tomen la misma. Si falta alguna serie lanza ``VentaInvalida`` (el pedido queda «cobrado, falta
    el comprobante» y el reintento vuelve a asignar).
    """
    asignadas: dict[int, list[str]] = {}
    for ln in lineas:
        if not lleva_serie(ln):
            continue
        if ln.cantidad != ln.cantidad.to_integral_value():
            raise VentaInvalida(
                f"{ln.descripcion}: la cantidad de un producto con serie es entera."
            )
        pedidas = int(ln.cantidad)
        elegidas = inv_series.mas_antiguas(
            ln.producto_id, ln.empresa_id, ln.almacen_id, pedidas, bloquear=True
        )
        if len(elegidas) < pedidas:
            raise VentaInvalida(
                f"{ln.descripcion}: no hay {pedidas} serie(s) disponibles en el almacén "
                f"«{ln.almacen.nombre}» (hay {len(elegidas)}). Revisa el stock de series."
            )
        asignadas[ln.pk] = [s.numero for s in elegidas]
    return asignadas


def guardar(lineas: list[LineaPedido], asignadas: dict[int, list[str]]) -> None:
    """Deja anotadas en el pedido las series que salieron en el comprobante."""
    for ln in lineas:
        numeros = asignadas.get(ln.pk)
        if numeros:
            ln.series_asignadas = numeros
            ln.series_fisicas = []
            ln.save(update_fields=["series_asignadas", "series_fisicas", "actualizado_en"])


# ---------------------------------------------------------------------------
# Cambiar la serie al preparar el pedido
# ---------------------------------------------------------------------------
def _quien(usuario) -> dict:
    nombre = (usuario.get_full_name() or usuario.get_username())[:150]
    return {"usuario_id": usuario.pk, "usuario_nombre": nombre}


@transaction.atomic
def cambiar(
    organizacion_id: int,
    numero: str,
    linea_id: int,
    *,
    anterior: str,
    nueva: str,
    motivo: str,
    usuario,
) -> PedidoTienda:
    """Cambia una de las series de una línea por la unidad que realmente se tomó."""
    motivo = " ".join((motivo or "").split())
    if len(motivo) < 3:
        raise PedidoInvalido("Escribe por qué cambias la serie.")
    if len(motivo) > MAX_MOTIVO:
        raise PedidoInvalido(f"El motivo admite hasta {MAX_MOTIVO} caracteres.")
    pedido = (
        PedidoTienda.objects.sin_ambito()
        .select_for_update()
        .filter(organizacion_id=organizacion_id, numero=numero)
        .first()
    )
    if pedido is None:
        raise PedidoInvalido("No encontramos ese pedido.")
    if pedido.estado not in ESTADOS_EDITABLES or pedido.venta_id is None:
        raise PedidoInvalido(
            "Solo se puede cambiar la serie mientras el pedido está pagado o en preparación."
        )
    linea = (
        LineaPedido.objects.sin_ambito()
        .select_for_update(of=("self",))
        .select_related("producto", "almacen")
        .filter(pk=linea_id, pedido=pedido)
        .first()
    )
    if linea is None or not lleva_serie(linea):
        raise PedidoInvalido("Esa línea no lleva número de serie.")
    anterior = " ".join((anterior or "").split()).upper()
    nueva = " ".join((nueva or "").split()).upper()
    actuales = entregadas(linea)
    if anterior not in actuales:
        raise PedidoInvalido(
            f"La serie {anterior or '—'} no es una de las entregadas en esta línea."
        )
    if nueva in actuales:
        raise PedidoInvalido(f"La serie {nueva} ya está en esta línea.")
    # La salida del Kardex con que se vendió esa línea (para saber qué unidades salieron).
    venta_linea = next(
        (
            lv
            for lv in LineaVenta.objects.sin_ambito().filter(
                venta_id=pedido.venta_id, producto_id=linea.producto_id, empresa_id=linea.empresa_id
            )
            if lv.movimiento_id is not None
        ),
        None,
    )
    if venta_linea is None:
        raise PedidoInvalido("No encontramos la salida de stock de esta línea.")
    try:
        inv_series.intercambiar_series_de_salida(
            producto_id=linea.producto_id,
            empresa_id=linea.empresa_id,
            almacen_id=linea.almacen_id,
            movimiento_id=venta_linea.movimiento_id,
            anterior=anterior,
            nueva=nueva,
        )
    except MovimientoInvalido as error:
        raise PedidoInvalido(str(error)) from None
    linea.series_fisicas = [nueva if s == anterior else s for s in actuales]
    linea.save(update_fields=["series_fisicas", "actualizado_en"])
    CambioSerie.objects.sin_ambito().create(
        organizacion_id=organizacion_id,
        pedido=pedido,
        linea=linea,
        serie_anterior=anterior,
        serie_nueva=nueva,
        motivo=motivo,
        usuario_id=usuario.pk,
    )
    HistorialPedido.objects.create(
        pedido=pedido,
        tipo=HistorialPedido.Tipo.NOTA,
        texto=f"Serie cambiada: {anterior} → {nueva} ({motivo})"[:500],
        **_quien(usuario),
    )
    registrar(
        "tienda.serie_cambiada",
        recurso_tipo="pedido_tienda",
        recurso_id=pedido.pk,
        organizacion_id=organizacion_id,
        resumen=f"Pedido {pedido.numero}: serie {anterior} cambiada por {nueva}"[:250],
        detalle={"linea": linea.pk, "anterior": anterior, "nueva": nueva, "motivo": motivo},
    )
    return pedido


@transaction.atomic
def deshacer_cambios(pedido: PedidoTienda) -> int:
    """Devuelve el inventario de series al estado del comprobante (antes de anular o devolver).

    Si el almacén cambió una serie, la unidad física quedó «ya salió» y la del comprobante volvió
    al stock. Para anular o devolver el comprobante hay que dejar «ya salió» la serie del
    comprobante (es la que él conoce): se invierte el cambio. Las dos unidades terminan en stock,
    que es lo real (ninguna salió, o la entregada vuelve). Devuelve cuántas se invirtieron.
    """
    invertidas = 0
    lineas = (
        LineaPedido.objects.sin_ambito()
        .select_for_update(of=("self",))
        .filter(pedido=pedido)
        .select_related("producto")
    )
    for linea in lineas:
        if not lleva_serie(linea) or not linea.series_fisicas:
            continue
        if list(linea.series_fisicas) == list(linea.series_asignadas):
            continue
        venta_linea = next(
            (
                lv
                for lv in LineaVenta.objects.sin_ambito().filter(
                    venta_id=pedido.venta_id,
                    producto_id=linea.producto_id,
                    empresa_id=linea.empresa_id,
                )
                if lv.movimiento_id is not None
            ),
            None,
        )
        if venta_linea is None:
            raise VentaInvalida("No encontramos la salida de stock de una línea con serie.")
        for fisica, asignada in zip(linea.series_fisicas, linea.series_asignadas, strict=True):
            if fisica == asignada:
                continue
            try:
                inv_series.intercambiar_series_de_salida(
                    producto_id=linea.producto_id,
                    empresa_id=linea.empresa_id,
                    almacen_id=linea.almacen_id,
                    movimiento_id=venta_linea.movimiento_id,
                    anterior=fisica,
                    nueva=asignada,
                )
            except MovimientoInvalido as error:
                raise VentaInvalida(str(error)) from None
            invertidas += 1
        linea.series_fisicas = []
        linea.save(update_fields=["series_fisicas", "actualizado_en"])
    return invertidas


# ---------------------------------------------------------------------------
# Salidas (panel y cliente)
# ---------------------------------------------------------------------------
def series_para_panel(linea: LineaPedido) -> dict | None:
    """Las dos listas, para que el almacén vea qué salió en el comprobante y qué se entrega."""
    if not linea.series_asignadas:
        return None
    return {
        "comprobante": list(linea.series_asignadas),
        "entregadas": entregadas(linea),
        "cambiada": bool(linea.series_fisicas)
        and list(linea.series_fisicas) != list(linea.series_asignadas),
    }


def series_para_cliente(pedido: PedidoTienda, linea: LineaPedido) -> list[str] | None:
    """La serie que ve el cliente: solo cuando el equipo ya va hacia él; antes puede cambiar."""
    if pedido.estado not in ESTADOS_VISIBLES or not linea.series_asignadas:
        return None
    return entregadas(linea)
