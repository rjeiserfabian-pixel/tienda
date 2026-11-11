"""Ofertas de la tienda: estado, validación del precio y consultas para el panel.

Una oferta es un precio especial SOLO web (sin IGV, como las listas) con fecha de inicio y de fin.
Reglas que se cuidan al crearla o editarla:

* El precio de oferta debe ser MENOR que el precio normal de la lista de la tienda.
* No puede bajar del precio mínimo que el sistema permite vender (el que ya usa Ventas: listas de
  descuento y técnica, o el costo). Así el motor de Ventas nunca rechaza el pedido por precio.
* Un producto no puede tener dos ofertas activas que se pisen en el tiempo.
* ``hasta`` es posterior a ``desde``.

Lo que se muestra al público (precio tachado, % de descuento, cuenta regresiva) sale de
``catalogo._precios``; el precio de oferta nunca revela el costo ni el mínimo.
"""

import logging
from datetime import datetime
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import ListaPrecio, PrecioProducto, Producto
from apps.ventas import precios

from . import catalogo
from .exceptions import DatosInvalidos
from .models import OfertaProducto

logger = logging.getLogger(__name__)

PROGRAMADA, VIGENTE, VENCIDA, PAUSADA = "PROGRAMADA", "VIGENTE", "VENCIDA", "PAUSADA"
CLAVE_FIRMA = "tienda:ofertas:firma"


def estado_de(oferta: OfertaProducto, ahora: datetime | None = None) -> str:
    ahora = ahora or timezone.now()
    if not oferta.activa:
        return PAUSADA
    if ahora < oferta.desde:
        return PROGRAMADA
    if ahora >= oferta.hasta:
        return VENCIDA
    return VIGENTE


def vigentes(organizacion_id: int, ahora: datetime | None = None):
    ahora = ahora or timezone.now()
    return OfertaProducto.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, activa=True, desde__lte=ahora, hasta__gt=ahora
    )


def _lista_de_la_tienda(ctx) -> ListaPrecio:
    lista = (
        ListaPrecio.objects.sin_ambito().filter(pk=ctx.lista_id).first() if ctx.lista_id else None
    )
    if lista is None:
        raise DatosInvalidos("La tienda no tiene una lista de precios para mostrar.")
    return lista


def precio_normal(ctx, producto: Producto) -> Decimal | None:
    fila = (
        PrecioProducto.objects.sin_ambito()
        .filter(producto=producto, lista_id=ctx.lista_id)
        .values_list("precio", flat=True)
        .first()
    )
    return fila


def minimo_permitido(ctx, producto: Producto, normal: Decimal) -> tuple[Decimal, Decimal]:
    """``(mínimo, costo)`` en soles sin IGV: lo más bajo que el sistema deja vender el producto."""
    listas = precios.cargar_listas(ctx.organizacion_id)
    por_lista = precios.precios_de([producto.pk]).get(producto.pk, {})
    minimo, _oculto = precios.minimo_del_producto(
        listas, por_lista, precio_lista=normal, costo=producto.costo
    )
    return minimo, producto.costo


def validar_precio(ctx, producto: Producto, precio: Decimal, *, ver_costos: bool) -> None:
    """Lanza ``DatosInvalidos`` si el precio de oferta no se puede aplicar."""
    _lista_de_la_tienda(ctx)
    normal = precio_normal(ctx, producto)
    if normal is None or normal <= 0:
        raise DatosInvalidos("Este producto no tiene precio en la lista de la tienda.")
    if precio >= normal:
        raise DatosInvalidos(
            f"El precio de oferta debe ser menor que el precio normal (S/ {normal:,.2f} sin IGV)."
        )
    minimo, costo = minimo_permitido(ctx, producto, normal)
    estado = precios.evaluar_precio(precio, minimo=minimo, absoluto=min(normal, costo))
    if estado == precios.OK:
        return
    # El monto mínimo solo se dice a quien puede ver costos y utilidad.
    if estado == precios.BAJO_COSTO:
        cuanto = f" (costo S/ {costo:,.2f})" if ver_costos else ""
        raise DatosInvalidos(f"El precio de oferta no puede estar por debajo del costo{cuanto}.")
    cuanto = f" (S/ {minimo:,.2f})" if ver_costos else ""
    raise DatosInvalidos(
        f"El precio de oferta está por debajo del mínimo permitido{cuanto}. "
        "Súbelo o ajusta las listas de precios en Mantenimiento."
    )


@transaction.atomic
def guardar(
    ctx,
    *,
    oferta: OfertaProducto | None,
    producto: Producto,
    precio: Decimal,
    desde: datetime,
    hasta: datetime,
    etiqueta: str,
    activa: bool,
    ver_costos: bool,
) -> OfertaProducto:
    """Crea o edita una oferta con todas las validaciones."""
    if hasta <= desde:
        raise DatosInvalidos("La oferta debe terminar después de empezar.")
    if precio <= 0:
        raise DatosInvalidos("El precio de oferta debe ser mayor que cero.")
    # Se bloquea el producto para que dos ofertas a la vez no se pisen.
    Producto.objects.sin_ambito().select_for_update().get(pk=producto.pk)
    validar_precio(ctx, producto, precio, ver_costos=ver_costos)
    if activa:
        cruzadas = OfertaProducto.objects.sin_ambito().filter(
            producto=producto, activa=True, desde__lt=hasta, hasta__gt=desde
        )
        if oferta is not None:
            cruzadas = cruzadas.exclude(pk=oferta.pk)
        if cruzadas.exists():
            raise DatosInvalidos("Este producto ya tiene otra oferta en esas fechas.")
    if oferta is None:
        oferta = OfertaProducto(organizacion_id=ctx.organizacion_id, producto=producto)
    oferta.precio_oferta = precio
    oferta.desde, oferta.hasta = desde, hasta
    oferta.etiqueta = " ".join((etiqueta or "").split())
    oferta.activa = activa
    oferta.save()
    registrar(
        "tienda.oferta_guardada",
        recurso_tipo="oferta_producto",
        recurso_id=oferta.pk,
        resumen=f"Oferta de «{producto.nombre}» guardada",
        detalle={"precio": str(precio), "desde": desde.isoformat(), "hasta": hasta.isoformat()},
    )
    transaction.on_commit(catalogo.invalidar)
    return oferta


def firma_de_vigentes(organizacion_id: int) -> str:
    """Huella de qué ofertas están vigentes ahora: cambia cuando una empieza o termina."""
    ids = sorted(vigentes(organizacion_id).values_list("pk", flat=True))
    return ",".join(str(i) for i in ids)


def revisar_cambios() -> bool:
    """Tarea periódica: si una oferta empezó o terminó, renueva lo guardado de la tienda."""
    organizaciones = set(
        OfertaProducto.objects.sin_ambito().values_list("organizacion_id", flat=True)
    )
    cambio = False
    for org in organizaciones:
        clave = f"{CLAVE_FIRMA}:{org}"
        firma = firma_de_vigentes(org)
        anterior = cache.get(clave)
        cache.set(clave, firma, None)
        if anterior is not None and anterior != firma:
            cambio = True
    if cambio:
        catalogo.invalidar()
        logger.info("tienda_ofertas_cambiaron")
    return cambio
