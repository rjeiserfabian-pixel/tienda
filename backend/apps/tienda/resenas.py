"""Reseñas de productos: solo de clientes que ya recibieron el producto.

Reglas (decididas con el negocio):

* Solo opina quien tiene un pedido ENTREGADO que incluye ese producto: son opiniones de compra
  verificada. Una reseña por cliente y producto (puede editarla o borrarla).
* Se publican solas. El dueño puede OCULTARLAS (con un motivo interno) y RESPONDER en público;
  lo oculto nunca cuenta en el promedio ni se muestra.
* No se aceptan enlaces en el texto (evita publicidad y estafas). Nada de esto toca el precio ni
  el stock.
* Opcional: un correo pidiendo la reseña unos días después de entregar, solo a clientes que
  aceptaron recibir comunicaciones y con su enlace de baja.
"""

import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Exists, OuterRef, Q, Subquery
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Producto

from . import carrito_abandonado, catalogo
from .exceptions import PedidoInvalido, PedidoNoEncontrado
from .models import (
    AvisoPedido,
    ConfiguracionResenas,
    CuentaCliente,
    HistorialPedido,
    LineaPedido,
    PedidoTienda,
    ResenaProducto,
)

logger = logging.getLogger(__name__)

Estado = ResenaProducto.Estado

TAM_PAGINA = 10
MAX_PAGINA = 30
MAX_TITULO = 80
MAX_COMENTARIO = 1000
MAX_RESPUESTA = 600
MAX_MOTIVO = 200
VENTANA_PEDIR = timedelta(days=14)  # pasado este tiempo ya no se le pide
TANDA = 100

_ENLACE = re.compile(r"(https?:|www\.|\b[\w-]+\.(com|pe|net|org|io|me|shop|store)\b)", re.I)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ResenaNoPermitida(PedidoInvalido):
    """El cliente no puede opinar de este producto (todavía no lo recibió)."""

    codigo = "resena_no_permitida"


def configuracion(organizacion_id: int) -> ConfiguracionResenas | None:
    return ConfiguracionResenas.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()


def _limpio(texto: str | None, maximo: int, campo: str) -> str:
    texto = _CONTROL.sub("", texto or "")
    texto = "\n".join(" ".join(linea.split()) for linea in texto.strip().splitlines())
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    if len(texto) > maximo:
        raise PedidoInvalido(f"{campo} admite hasta {maximo} caracteres.")
    if _ENLACE.search(texto):
        raise PedidoInvalido(f"{campo} no puede llevar enlaces ni direcciones web.")
    return texto


# ---------------------------------------------------------------------------
# Lo público
# ---------------------------------------------------------------------------
def producto_publico(ctx, slug: str) -> Producto:
    producto = catalogo.productos_publicos(ctx).filter(slug=slug).first()
    if producto is None:
        raise PedidoNoEncontrado("No encontramos ese producto.")
    return producto


def _publicas(producto_id: int):
    return ResenaProducto.objects.sin_ambito().filter(
        producto_id=producto_id, estado=Estado.PUBLICADA
    )


def _autor(cuenta: CuentaCliente) -> str:
    nombre = (cuenta.nombres or "").split(" ")[0].title()[:20]
    inicial = (cuenta.apellidos or "").strip()[:1].upper()
    return f"{nombre} {inicial}.".strip() if inicial else (nombre or "Cliente")


def resumen(producto_id: int) -> dict:
    """Promedio, total y cuántas hay de cada puntaje (solo las publicadas)."""
    filas = dict(_publicas(producto_id).values_list("estrellas").annotate(n=Count("id")).order_by())
    total = sum(filas.values())
    promedio = _publicas(producto_id).aggregate(p=Avg("estrellas"))["p"] if total else None
    return {
        "total": total,
        "promedio": round(float(promedio), 1) if promedio is not None else None,
        "distribucion": {str(e): filas.get(e, 0) for e in (5, 4, 3, 2, 1)},
    }


ORDENES = {
    "recientes": ("-id",),
    "mejores": ("-estrellas", "-id"),
    "peores": ("estrellas", "-id"),
}


def listar(producto_id: int, params) -> dict:
    try:
        pagina = max(int(params.get("page", 1)), 1)
        tam = min(max(int(params.get("page_size", TAM_PAGINA)), 1), MAX_PAGINA)
    except ValueError:
        pagina, tam = 1, TAM_PAGINA
    orden = ORDENES.get(params.get("orden", "recientes"), ORDENES["recientes"])
    qs = _publicas(producto_id).select_related("cuenta").order_by(*orden)
    total = qs.count()
    filas = qs[(pagina - 1) * tam : pagina * tam]
    return {
        "resumen": resumen(producto_id),
        "count": total,
        "page": pagina,
        "paginas": max((total + tam - 1) // tam, 1),
        "results": [
            {
                "id": r.pk,
                "autor": _autor(r.cuenta),
                "estrellas": r.estrellas,
                "titulo": r.titulo,
                "comentario": r.comentario,
                "fecha": r.creado_en.isoformat(),
                "respuesta": r.respuesta,
                "respuesta_en": r.respuesta_en.isoformat() if r.respuesta_en else None,
                "verificada": True,
            }
            for r in filas
        ],
    }


# ---------------------------------------------------------------------------
# El cliente
# ---------------------------------------------------------------------------
def _pedido_que_da_derecho(cuenta: CuentaCliente, producto_id: int) -> PedidoTienda | None:
    return (
        PedidoTienda.objects.sin_ambito()
        .filter(
            organizacion_id=cuenta.organizacion_id,
            cuenta=cuenta,
            estado=PedidoTienda.Estado.ENTREGADO,
            lineas__producto_id=producto_id,
            lineas__es_envio=False,
        )
        .order_by("-id")
        .first()
    )


def _mia(cuenta: CuentaCliente, producto_id: int) -> ResenaProducto | None:
    return (
        ResenaProducto.objects.sin_ambito()
        .filter(organizacion_id=cuenta.organizacion_id, cuenta=cuenta, producto_id=producto_id)
        .first()
    )


def _salida_mia(r: ResenaProducto) -> dict:
    return {
        "id": r.pk,
        "estrellas": r.estrellas,
        "titulo": r.titulo,
        "comentario": r.comentario,
        "estado": r.estado,
        "visible": r.estado == Estado.PUBLICADA,
        "respuesta": r.respuesta if r.estado == Estado.PUBLICADA else "",
        "fecha": r.creado_en.isoformat(),
    }


def estado_del_cliente(cuenta: CuentaCliente, producto_id: int) -> dict:
    """¿Puede opinar este cliente? ¿Ya lo hizo? (para mostrar el formulario)."""
    mia = _mia(cuenta, producto_id)
    puede = _pedido_que_da_derecho(cuenta, producto_id) is not None
    return {
        "puede": puede,
        "mia": _salida_mia(mia) if mia else None,
        "motivo": ""
        if puede
        else "Podrás opinar cuando recibas este producto en un pedido de la tienda.",
    }


def guardar(
    cuenta: CuentaCliente, producto_id: int, *, estrellas, titulo: str = "", comentario: str = ""
) -> ResenaProducto:
    """Crea la reseña del cliente o actualiza la que ya tenía."""
    if not isinstance(estrellas, int) or isinstance(estrellas, bool) or not 1 <= estrellas <= 5:
        raise PedidoInvalido("Elige de 1 a 5 estrellas.")
    titulo = _limpio(titulo, MAX_TITULO, "El título")
    comentario = _limpio(comentario, MAX_COMENTARIO, "El comentario")
    with transaction.atomic():
        # Se bloquea la cuenta: sus reseñas se guardan de a una.
        CuentaCliente.objects.sin_ambito().select_for_update().get(pk=cuenta.pk)
        pedido = _pedido_que_da_derecho(cuenta, producto_id)
        if pedido is None:
            raise ResenaNoPermitida("Solo puedes opinar de productos que ya recibiste.")
        existente = _mia(cuenta, producto_id)
        try:
            if existente is None:
                resena = ResenaProducto.objects.sin_ambito().create(
                    organizacion_id=cuenta.organizacion_id,
                    producto_id=producto_id,
                    cuenta=cuenta,
                    pedido=pedido,
                    estrellas=estrellas,
                    titulo=titulo,
                    comentario=comentario,
                )
            else:
                existente.estrellas, existente.titulo, existente.comentario = (
                    estrellas,
                    titulo,
                    comentario,
                )
                existente.editada_en = timezone.now()
                existente.save()  # si el dueño la ocultó, sigue oculta
                resena = existente
        except IntegrityError:
            raise PedidoInvalido("Ya enviaste tu opinión de este producto.") from None
        registrar(
            "tienda.resena_guardada",
            recurso_tipo="resena_producto",
            recurso_id=resena.pk,
            organizacion_id=cuenta.organizacion_id,
            resumen=f"Reseña de {estrellas} estrellas del producto {producto_id}",
        )
    return resena


def borrar_mia(cuenta: CuentaCliente, producto_id: int) -> None:
    resena = _mia(cuenta, producto_id)
    if resena is None:
        raise PedidoNoEncontrado("No tienes una reseña de este producto.")
    resena.delete()  # borrado lógico: el cliente puede volver a opinar
    registrar(
        "tienda.resena_borrada",
        recurso_tipo="resena_producto",
        recurso_id=resena.pk,
        organizacion_id=cuenta.organizacion_id,
        resumen=f"El cliente borró su reseña del producto {producto_id}",
    )


# ---------------------------------------------------------------------------
# El panel
# ---------------------------------------------------------------------------
def _fila_admin(r: ResenaProducto) -> dict:
    return {
        "id": r.pk,
        "producto": r.producto.nombre,
        "producto_slug": r.producto.slug,
        "cliente": f"{r.cuenta.nombres} {r.cuenta.apellidos}".strip(),
        "pedido": r.pedido.numero,
        "estrellas": r.estrellas,
        "titulo": r.titulo,
        "comentario": r.comentario,
        "estado": r.estado,
        "estado_texto": r.get_estado_display(),
        "oculta_motivo": r.oculta_motivo,
        "respuesta": r.respuesta,
        "respuesta_en": r.respuesta_en.isoformat() if r.respuesta_en else None,
        "respuesta_por": r.respuesta_por,
        "fecha": r.creado_en.isoformat(),
        "editada_en": r.editada_en.isoformat() if r.editada_en else None,
    }


def listar_admin(organizacion_id: int, params) -> dict:
    try:
        pagina = max(int(params.get("page", 1)), 1)
    except ValueError:
        pagina = 1
    tam = 25
    qs = (
        ResenaProducto.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .select_related("producto", "cuenta", "pedido")
    )
    estado = params.get("estado", "")
    if estado in Estado.values:
        qs = qs.filter(estado=estado)
    elif estado == "sin_respuesta":
        qs = qs.filter(respuesta="", estado=Estado.PUBLICADA)
    estrellas = params.get("estrellas", "")
    if estrellas.isdigit() and 1 <= int(estrellas) <= 5:
        qs = qs.filter(estrellas=int(estrellas))
    texto = (params.get("q") or "").strip()[:80]
    if texto:
        qs = qs.filter(
            Q(producto__nombre__icontains=texto)
            | Q(comentario__icontains=texto)
            | Q(titulo__icontains=texto)
            | Q(cuenta__nombres__icontains=texto)
        )
    total = qs.count()
    filas = qs.order_by("-id")[(pagina - 1) * tam : pagina * tam]
    base = ResenaProducto.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    publicadas = base.filter(estado=Estado.PUBLICADA)
    promedio = publicadas.aggregate(p=Avg("estrellas"))["p"]
    return {
        "count": total,
        "page": pagina,
        "tamano": tam,
        "results": [_fila_admin(r) for r in filas],
        "resumen": {
            "total": base.count(),
            "publicadas": publicadas.count(),
            "ocultas": base.filter(estado=Estado.OCULTA).count(),
            "sin_respuesta": publicadas.filter(respuesta="").count(),
            "promedio": round(float(promedio), 1) if promedio is not None else None,
        },
    }


def _de_la_organizacion(organizacion_id: int, resena_id: int) -> ResenaProducto:
    resena = (
        ResenaProducto.objects.sin_ambito()
        .select_related("producto", "cuenta", "pedido")
        .filter(organizacion_id=organizacion_id, pk=resena_id)
        .first()
    )
    if resena is None:
        raise PedidoNoEncontrado("No encontramos esa reseña.")
    return resena


def _quien(usuario) -> str:
    return (usuario.get_full_name() or usuario.get_username())[:150]


def ocultar(organizacion_id: int, resena_id: int, *, usuario, motivo: str = "") -> dict:
    motivo = _limpio(motivo, MAX_MOTIVO, "El motivo")
    resena = _de_la_organizacion(organizacion_id, resena_id)
    resena.estado = Estado.OCULTA
    resena.oculta_motivo = motivo
    resena.save()
    registrar(
        "tienda.resena_oculta",
        recurso_tipo="resena_producto",
        recurso_id=resena.pk,
        organizacion_id=organizacion_id,
        resumen=f"Reseña {resena.pk} oculta por {_quien(usuario)}",
        detalle={"motivo": motivo},
    )
    catalogo.invalidar()
    return _fila_admin(resena)


def mostrar(organizacion_id: int, resena_id: int, *, usuario) -> dict:
    resena = _de_la_organizacion(organizacion_id, resena_id)
    resena.estado = Estado.PUBLICADA
    resena.oculta_motivo = ""
    resena.save()
    registrar(
        "tienda.resena_publicada",
        recurso_tipo="resena_producto",
        recurso_id=resena.pk,
        organizacion_id=organizacion_id,
        resumen=f"Reseña {resena.pk} publicada de nuevo por {_quien(usuario)}",
    )
    catalogo.invalidar()
    return _fila_admin(resena)


def responder(organizacion_id: int, resena_id: int, *, usuario, texto: str) -> dict:
    """Respuesta pública del negocio; un texto vacío la quita."""
    texto = _limpio(texto, MAX_RESPUESTA, "La respuesta")
    resena = _de_la_organizacion(organizacion_id, resena_id)
    resena.respuesta = texto
    resena.respuesta_en = timezone.now() if texto else None
    resena.respuesta_por = _quien(usuario) if texto else ""
    resena.save()
    registrar(
        "tienda.resena_respondida",
        recurso_tipo="resena_producto",
        recurso_id=resena.pk,
        organizacion_id=organizacion_id,
        resumen=f"Reseña {resena.pk} respondida por {_quien(usuario)}",
    )
    catalogo.invalidar()
    return _fila_admin(resena)


# ---------------------------------------------------------------------------
# Pedir la reseña por correo
# ---------------------------------------------------------------------------
def pendientes_de_resena(pedido: PedidoTienda) -> list[Producto]:
    """Productos del pedido que el cliente aún no reseñó (y que siguen publicados)."""
    ya = ResenaProducto.objects.sin_ambito().filter(
        cuenta_id=pedido.cuenta_id, producto_id=OuterRef("producto_id")
    )
    productos = (
        LineaPedido.objects.sin_ambito()
        .filter(pedido=pedido, es_envio=False)
        .annotate(reseñado=Exists(ya))
        .filter(reseñado=False)
        .select_related("producto")
        .order_by("id")
    )
    vistos: dict[int, Producto] = {}
    for linea in productos:
        vistos.setdefault(linea.producto_id, linea.producto)
    return [p for p in vistos.values() if p.slug]


def texto_del_correo(pedido: PedidoTienda) -> tuple[str, str] | None:
    pendientes = pendientes_de_resena(pedido)
    if not pendientes:
        return None
    base = settings.TIENDA_URL.rstrip("/")
    nombre = pedido.cuenta.nombres
    lista = "\n".join(f"  - {p.nombre}: {base}/producto/{p.slug}#resenas" for p in pendientes[:6])
    cuerpo = (
        f"Hola {nombre},\n\n"
        f"Esperamos que estés disfrutando lo que compraste en tu pedido {pedido.numero}. "
        "¿Nos cuentas qué te pareció? Tu opinión ayuda a otros clientes y a nosotros a mejorar:\n\n"
        f"{lista}\n\n"
        "Recibes este correo porque aceptaste recibir comunicaciones. Si ya no quieres recibirlas, "
        f"puedes darte de baja aquí: {base}/cuenta/baja?t="
        f"{carrito_abandonado.token_de_baja(pedido.cuenta)}"
    )
    return f"¿Qué tal tu compra {pedido.numero}? Cuéntanos tu opinión", cuerpo


def candidatos(config: ConfiguracionResenas, ahora=None) -> list[int]:
    """Pedidos entregados hace ``pedir_dias`` (máx. 14 más) a los que aún no se les pidió."""
    ahora = ahora or timezone.now()
    entregado = Subquery(
        HistorialPedido.objects.filter(pedido=OuterRef("pk"), estado=PedidoTienda.Estado.ENTREGADO)
        .order_by("-creado_en")
        .values("creado_en")[:1]
    )
    pedido_ya = AvisoPedido.objects.sin_ambito().filter(
        pedido=OuterRef("pk"), evento="PEDIDO_RESENA", canal=AvisoPedido.Canal.CORREO
    )
    return list(
        PedidoTienda.objects.sin_ambito()
        .filter(
            organizacion_id=config.organizacion_id,
            estado=PedidoTienda.Estado.ENTREGADO,
            cuenta__activa=True,
            cuenta__acepta_ofertas=True,
            cuenta__correo_verificado_en__isnull=False,
        )
        .annotate(entregado_en=entregado, ya_pedido=Exists(pedido_ya))
        .filter(
            ya_pedido=False,
            entregado_en__lte=ahora - timedelta(days=config.pedir_dias),
            entregado_en__gte=ahora - timedelta(days=config.pedir_dias) - VENTANA_PEDIR,
        )
        .values_list("pk", flat=True)[:TANDA]
    )


def pedir_resenas() -> int:
    """Pide la reseña de lo entregado a quienes toca. Devuelve cuántos correos encoló."""
    from . import avisos

    enviados = 0
    ahora = timezone.now()
    for config in ConfiguracionResenas.objects.sin_ambito().filter(pedir_activo=True):
        for pedido_id in candidatos(config, ahora):
            try:
                pedido = (
                    PedidoTienda.objects.sin_ambito().select_related("cuenta").get(pk=pedido_id)
                )
                if not pendientes_de_resena(pedido):
                    # Ya opinó de todo: se anota para no volver a revisarlo.
                    avisos.anotar_correo(
                        pedido, "PEDIDO_RESENA", enviado=False, detalle="Ya opinó de todo."
                    )
                    continue
                avisos.encolar(pedido.pk, "PEDIDO_RESENA")
                enviados += 1
            except Exception:  # noqa: BLE001 - un pedido con problema no frena a los demás
                logger.exception("tienda_pedir_resena_fallo", extra={"pedido_id": pedido_id})
    return enviados
