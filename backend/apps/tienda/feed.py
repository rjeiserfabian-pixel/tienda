"""Feed de productos para Google Merchant Center (aparecer en Google Shopping y en «Comprar»).

Es un RSS 2.0 con el espacio de nombres ``g:`` de Google. Solo salen productos con precio y foto;
el precio es el que ve el público (con IGV si la tienda lo muestra así) y la disponibilidad nunca
revela el stock exacto. Lo pide Google cada cierto tiempo, así que se guarda un rato en caché.
"""

from xml.sax.saxutils import escape

from django.conf import settings

from . import catalogo
from .models import ConfiguracionTienda

LIMITE = 5000
MAX_TITULO = 150
MAX_DESCRIPCION = 4900


def _texto(valor, maximo: int) -> str:
    limpio = " ".join(str(valor or "").split())
    return escape(limpio[:maximo])


def _etiqueta(nombre: str, valor: str) -> str:
    return f"<{nombre}>{valor}</{nombre}>"


def construir(ctx) -> str:
    """El XML completo del feed."""
    base = settings.TIENDA_URL.rstrip("/")
    config = (
        ConfiguracionTienda.objects.sin_ambito().filter(organizacion_id=ctx.organizacion_id).first()
    )
    tienda = _texto(config.nombre if config else "Tienda", 100)
    productos = list(catalogo.productos_publicos(ctx).order_by("id")[:LIMITE])
    items = []
    for p in productos:
        precios = catalogo._precios(p, ctx)
        if precios["consultar_precio"] or not p.foto_principal_id:
            continue
        disponibilidad = catalogo._disponibilidad(p, ctx)["disponibilidad"]
        enlace = f"{base}/producto/{p.slug}"
        foto = f"{base}{catalogo.url_foto(p.foto_principal_id, 'grande').rstrip('/')}"
        filas = [
            _etiqueta("g:id", _texto(p.codigo or p.pk, 50)),
            _etiqueta("g:title", _texto(p.nombre, MAX_TITULO)),
            _etiqueta(
                "g:description",
                _texto(p.descripcion_web or p.descripcion or p.nombre, MAX_DESCRIPCION),
            ),
            _etiqueta("g:link", escape(enlace)),
            _etiqueta("g:image_link", escape(foto)),
            _etiqueta(
                "g:availability", "out_of_stock" if disponibilidad == "agotado" else "in_stock"
            ),
            _etiqueta("g:condition", "new"),
            _etiqueta(
                "g:price", f"{precios['precio_normal_mostrar'] or precios['precio_mostrar']} PEN"
            ),
        ]
        if precios["precio_normal_mostrar"]:  # en oferta: el precio de venta es el rebajado
            filas.append(_etiqueta("g:sale_price", f"{precios['precio_mostrar']} PEN"))
        if p.marca:
            filas.append(_etiqueta("g:brand", _texto(p.marca.nombre, 70)))
        mpn = p.codigo_fabricante or ""
        if mpn:
            filas.append(_etiqueta("g:mpn", _texto(mpn, 70)))
        else:
            filas.append(_etiqueta("g:identifier_exists", "no"))
        filas.append(_etiqueta("g:product_type", _texto(p.categoria.nombre, 150)))
        items.append("<item>" + "".join(filas) + "</item>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>'
        f"<title>{tienda}</title><link>{escape(base)}</link>"
        f"<description>Productos de {tienda}</description>" + "".join(items) + "</channel></rss>"
    )
