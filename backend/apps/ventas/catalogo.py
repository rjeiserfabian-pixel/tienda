"""Productos para la pantalla de venta: fichas con foto, precios por lista y stock por empresa.

Es una vista pensada para vender: NUNCA devuelve costos ni utilidad. Sin texto de búsqueda lista
el catálogo por páginas (con filtro de categoría); con texto busca por nombre, código, código de
barras o código del fabricante, y un código exacto devuelve solo ese producto.
"""

from collections import defaultdict

from django.db.models import Prefetch

from apps.inventario import consulta_precios
from apps.inventario.models import SaldoStock
from apps.mantenimiento.models import EstadoRegistro, PrecioProducto, Producto, TipoProducto
from apps.organizacion.models import Empresa

TAMANO_PAGINA = 24


def _base():
    return (
        Producto.objects.filter(estado=EstadoRegistro.ACTIVO)
        .select_related("categoria", "marca", "unidad")
        .prefetch_related(
            "fotos",
            Prefetch(
                "precios",
                queryset=PrecioProducto.objects.select_related("lista").order_by(
                    "lista__orden", "lista_id"
                ),
            ),
        )
    )


def _stock(productos: list[Producto], empresas: list[Empresa]) -> dict[int, list[dict]]:
    """Existencias vendibles por producto, empresa y almacén (las empresas ya vienen filtradas)."""
    ids = [p.pk for p in productos if p.controla_stock and p.tipo == TipoProducto.BIEN]
    por_producto: dict[int, list[dict]] = defaultdict(list)
    if not ids or not empresas:
        return por_producto
    filas = (
        SaldoStock.objects.sin_ambito()
        .filter(
            producto_id__in=ids,
            empresa_id__in=[e.pk for e in empresas],
            almacen__permite_venta=True,
            almacen__estado=EstadoRegistro.ACTIVO,
            cantidad__gt=0,
        )
        .select_related("almacen")
        .order_by("almacen__codigo", "almacen_id")
    )
    for fila in filas:
        por_producto[fila.producto_id].append(
            {
                "empresa": fila.empresa_id,
                "almacen": fila.almacen_id,
                "almacen_nombre": fila.almacen.nombre,
                "cantidad": str(fila.cantidad),
            }
        )
    return por_producto


def _ficha(p: Producto, stock: dict[int, list[dict]]) -> dict:
    fotos = list(p.fotos.all())
    return {
        "id": p.pk,
        "codigo": p.codigo,
        "nombre": p.nombre,
        "marca": p.marca.nombre if p.marca else None,
        "categoria": p.categoria.nombre,
        "categoria_id": p.categoria_id,
        "unidad": p.unidad.abreviatura,
        "codigo_barras": p.codigo_barras_efectivo,
        "tipo": p.tipo,
        "lleva_serie": p.lleva_serie,
        "controla_stock": p.controla_stock and p.tipo == TipoProducto.BIEN,
        "foto_principal": fotos[0].pk if fotos else None,
        "precios": [
            {"lista": pr.lista_id, "precio": str(pr.precio)}
            for pr in p.precios.all()
            if pr.lista.estado == EstadoRegistro.ACTIVO
        ],
        "stock": stock.get(p.pk, []),
    }


def fichas_de(producto_ids: list[int], empresas: list[Empresa]) -> dict[int, dict]:
    """Las fichas de venta (precios y stock) de unos productos concretos, por id."""
    productos = list(_base().filter(pk__in=producto_ids))
    stock = _stock(productos, empresas)
    return {p.pk: _ficha(p, stock) for p in productos}


def buscar(empresas: list[Empresa], *, q: str = "", categoria: int | None = None, pagina: int = 1):
    """``(fichas, exacto, hay_mas)`` de los productos que se pueden vender desde ``empresas``."""
    q = " ".join((q or "").split())
    if len(q) >= consulta_precios.MIN_LETRAS:
        productos, exacto, _ = consulta_precios.buscar(q)
        if categoria:
            productos = [p for p in productos if p.categoria_id == categoria]
        hay_mas = False
    else:
        consulta = _base().order_by("nombre", "id")
        if categoria:
            consulta = consulta.filter(categoria_id=categoria)
        desde = (max(pagina, 1) - 1) * TAMANO_PAGINA
        productos = list(consulta[desde : desde + TAMANO_PAGINA + 1])
        hay_mas = len(productos) > TAMANO_PAGINA
        productos = productos[:TAMANO_PAGINA]
        exacto = False
    stock = _stock(productos, empresas)
    return [_ficha(p, stock) for p in productos], exacto, hay_mas
