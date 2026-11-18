"""Favoritos del cliente y «avísame cuando llegue».

* Favoritos: el corazón de la tienda. Solo con cuenta; hasta 200 productos por cliente. Un producto
  que deja de publicarse sigue guardado pero no se muestra.
* Avísame cuando llegue: solo se puede pedir de un producto que hoy está agotado. Cuando vuelve a
  haber stock se le escribe UNA vez por correo (lo pidió él mismo, no es publicidad). Un pedido
  de aviso que nunca se cumple vence a los 90 días.
"""

import contextlib
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import catalogo
from .exceptions import PedidoInvalido, PedidoNoEncontrado
from .models import AvisoDisponibilidad, ConfiguracionTienda, CuentaCliente, Favorito

logger = logging.getLogger(__name__)

MAX_FAVORITOS = 200
VIGENCIA_AVISO = timedelta(days=90)
TANDA_PRODUCTOS = 200


def _producto(ctx, producto_id: int):
    producto = catalogo.productos_publicos(ctx).filter(pk=producto_id).first()
    if producto is None:
        raise PedidoNoEncontrado("No encontramos ese producto.")
    return producto


# ---------------------------------------------------------------------------
# Favoritos
# ---------------------------------------------------------------------------
def ids(cuenta: CuentaCliente) -> list[int]:
    return list(
        Favorito.objects.sin_ambito()
        .filter(organizacion_id=cuenta.organizacion_id, cuenta=cuenta)
        .values_list("producto_id", flat=True)
    )


def agregar(cuenta: CuentaCliente, ctx, producto_id: int) -> list[int]:
    _producto(ctx, producto_id)
    actuales = Favorito.objects.sin_ambito().filter(
        organizacion_id=cuenta.organizacion_id, cuenta=cuenta
    )
    if actuales.filter(producto_id=producto_id).exists():
        return ids(cuenta)
    if actuales.count() >= MAX_FAVORITOS:
        raise PedidoInvalido(f"Puedes guardar hasta {MAX_FAVORITOS} favoritos.")
    with contextlib.suppress(IntegrityError), transaction.atomic():  # dos clics a la vez
        Favorito.objects.sin_ambito().create(
            organizacion_id=cuenta.organizacion_id, cuenta=cuenta, producto_id=producto_id
        )
    return ids(cuenta)


def quitar(cuenta: CuentaCliente, producto_id: int) -> list[int]:
    for fila in Favorito.objects.sin_ambito().filter(
        organizacion_id=cuenta.organizacion_id, cuenta=cuenta, producto_id=producto_id
    ):
        fila.delete()
    return ids(cuenta)


def listar(cuenta: CuentaCliente, ctx) -> list[dict]:
    """Los favoritos como tarjetas (solo los que siguen publicados), del más nuevo al más viejo."""
    orden = ids(cuenta)
    productos = {p.pk: p for p in catalogo.productos_publicos(ctx).filter(pk__in=orden)}
    return catalogo.tarjetas([productos[i] for i in orden if i in productos], ctx)


# ---------------------------------------------------------------------------
# Avísame cuando llegue
# ---------------------------------------------------------------------------
def _pendientes(cuenta: CuentaCliente):
    return AvisoDisponibilidad.objects.sin_ambito().filter(
        organizacion_id=cuenta.organizacion_id, cuenta=cuenta, avisado_en__isnull=True
    )


def avisos_pedidos(cuenta: CuentaCliente) -> list[int]:
    return list(_pendientes(cuenta).values_list("producto_id", flat=True))


def pedir_aviso(cuenta: CuentaCliente, ctx, producto_id: int) -> list[int]:
    producto = _producto(ctx, producto_id)
    if catalogo._disponibilidad(producto, ctx)["disponibilidad"] != "agotado":
        raise PedidoInvalido("Este producto ya está disponible: puedes comprarlo ahora.")
    if not _pendientes(cuenta).filter(producto_id=producto_id).exists():
        with contextlib.suppress(IntegrityError), transaction.atomic():
            AvisoDisponibilidad.objects.sin_ambito().create(
                organizacion_id=cuenta.organizacion_id, cuenta=cuenta, producto_id=producto_id
            )
    return avisos_pedidos(cuenta)


def cancelar_aviso(cuenta: CuentaCliente, producto_id: int) -> list[int]:
    for fila in _pendientes(cuenta).filter(producto_id=producto_id):
        fila.delete()
    return avisos_pedidos(cuenta)


def _correo(cuenta: CuentaCliente, producto, nombre_tienda: str) -> None:
    base = settings.TIENDA_URL.rstrip("/")
    cuerpo = (
        f"Hola {cuenta.nombres},\n\n"
        f"¡Buenas noticias! «{producto.nombre}» ya está disponible otra vez en {nombre_tienda}.\n"
        "Te escribimos porque nos pediste que te avisáramos. Como la cantidad es limitada, "
        "te recomendamos asegurarlo pronto:\n\n"
        f"{base}/producto/{producto.slug}\n\n"
        "Este aviso se manda una sola vez."
    )
    send_mail(f"Ya llegó: {producto.nombre}", cuerpo, None, [cuenta.correo], fail_silently=False)


def avisar_disponibles() -> int:
    """Escribe a quienes pidieron aviso de un producto que ya tiene stock. Devuelve cuántos."""
    ahora = timezone.now()
    AvisoDisponibilidad.objects.sin_ambito().filter(
        avisado_en__isnull=True, creado_en__lt=ahora - VIGENCIA_AVISO
    ).update(eliminado_en=ahora)
    ctx = catalogo.contexto()
    if ctx is None:
        return 0
    pendientes = list(
        AvisoDisponibilidad.objects.sin_ambito()
        .filter(organizacion_id=ctx.organizacion_id, avisado_en__isnull=True)
        .select_related("cuenta")
        .order_by("id")[: TANDA_PRODUCTOS * 5]
    )
    if not pendientes:
        return 0
    productos = {
        p.pk: p
        for p in catalogo.productos_publicos(ctx).filter(pk__in={a.producto_id for a in pendientes})
    }
    nombre_tienda = (
        ConfiguracionTienda.objects.sin_ambito()
        .filter(organizacion_id=ctx.organizacion_id)
        .values_list("nombre", flat=True)
        .first()
        or "la tienda"
    )
    enviados = 0
    for aviso in pendientes:
        producto = productos.get(aviso.producto_id)
        cuenta = aviso.cuenta
        if producto is None or not (cuenta.activa and cuenta.verificada):
            continue
        if catalogo._disponibilidad(producto, ctx)["disponibilidad"] == "agotado":
            continue
        if producto.precio_web is None:  # sin precio web no se puede comprar: no se avisa
            continue
        try:
            _correo(cuenta, producto, nombre_tienda)
        except Exception:  # noqa: BLE001 - un correo caído no frena a los demás; se reintenta
            logger.exception("tienda_aviso_stock_fallo", extra={"aviso_id": aviso.pk})
            continue
        aviso.avisado_en = timezone.now()
        aviso.save(update_fields=["avisado_en", "actualizado_en"])
        enviados += 1
    return enviados
