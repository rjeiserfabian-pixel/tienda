"""API PÚBLICA de la tienda virtual: solo lectura, sin sesión.

Lo que responde es lo mismo para todos, así que se guarda en caché un minuto (y se avisa a los
navegadores y CDN que pueden hacer lo mismo). Cuando el catálogo cambia se invalida solo.
No devuelve nunca costos, utilidades, stock exacto ni datos internos. Los límites de uso por IP
(``THROTTLE_TIENDA``) protegen contra abusos; la caché hace que casi todas las visitas no toquen la
base de datos.
"""

import hashlib
import logging

from django.core.cache import cache
from django.http import FileResponse, Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import ErrorDominio
from apps.core.throttles import TiendaFotosThrottle, TiendaThrottle
from apps.tienda import banners, catalogo, servicios
from apps.tienda.models import ConfiguracionTienda

logger = logging.getLogger(__name__)

TAG = ["tienda"]
TTL_LISTADO = 60
TTL_MENU = 300
TTL_FICHA = 60
TTL_SUGERENCIAS = 30
FORMATOS_FOTO = {"mini": "miniatura", "grande": "imagen"}


class TiendaNoDisponible(ErrorDominio):
    status_code = 503
    codigo = "tienda_no_disponible"
    mensaje = "La tienda no está disponible por el momento."


class _Publica(APIView):
    """Base: sin autenticación, solo lectura, con límite por IP."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TiendaThrottle]
    ttl = TTL_LISTADO

    def contexto(self) -> catalogo.Contexto:
        ctx = catalogo.contexto()
        if ctx is None:
            raise TiendaNoDisponible()
        return ctx

    def clave(self, request) -> str:
        # La versión sube cuando cambia el catálogo; la dirección completa distingue cada consulta.
        crudo = f"{catalogo.version()}|{request.path}|{request.META.get('QUERY_STRING', '')}"
        return "tienda:r:" + hashlib.sha256(crudo.encode()).hexdigest()

    def responder(self, request, construir):
        clave = self.clave(request)
        datos = cache.get(clave)
        if datos is None:
            datos = construir()
            cache.set(clave, datos, self.ttl)
        respuesta = Response(datos)
        respuesta["Cache-Control"] = (
            f"public, max-age={min(self.ttl, 30)}, s-maxage={self.ttl}, stale-while-revalidate=300"
        )
        return respuesta


class MenuView(_Publica):
    ttl = TTL_MENU

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        """Familias con sus categorías, y marcas: solo donde hay productos publicados."""
        ctx = self.contexto()
        return self.responder(request, lambda: catalogo.menu(ctx))


class InicioView(_Publica):
    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        """Destacados y novedades para la portada."""
        ctx = self.contexto()
        return self.responder(request, lambda: catalogo.inicio(ctx))


class ProductosView(_Publica):
    @extend_schema(
        tags=TAG,
        auth=[],
        responses={200: dict},
        parameters=[
            OpenApiParameter("categoria", str, description="Dirección web de la categoría."),
            OpenApiParameter("familia", str, description="Dirección web de la familia."),
            OpenApiParameter(
                "marca", str, description="Una o varias marcas (repetir el parámetro)."
            ),
            OpenApiParameter("q", str, description="Texto a buscar."),
            OpenApiParameter("precio_min", str),
            OpenApiParameter("precio_max", str),
            OpenApiParameter("disponible", str, description="1 = solo con stock."),
            OpenApiParameter("nuevo", str, description="1 = solo novedades."),
            OpenApiParameter("destacado", str, description="1 = solo destacados."),
            OpenApiParameter(
                "orden", str, description="relevancia, precio_asc, precio_desc, nuevos o nombre."
            ),
            OpenApiParameter(
                "esp.<clave>", str, description="Filtro por una especificación (repetible)."
            ),
            OpenApiParameter("facetas", str, description="1 = incluir los filtros disponibles."),
            OpenApiParameter("page", int),
            OpenApiParameter("page_size", int, description="Hasta 48."),
        ],
    )
    def get(self, request):
        """Listado con filtros, orden y paginación."""
        ctx = self.contexto()
        return self.responder(request, lambda: catalogo.listar(ctx, request.query_params))


class ProductoView(_Publica):
    ttl = TTL_FICHA

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request, slug: str):
        """La ficha completa de un producto."""
        ctx = self.contexto()
        return self.responder(request, lambda: catalogo.detalle(ctx, slug))


class SugerenciasView(_Publica):
    ttl = TTL_SUGERENCIAS

    @extend_schema(
        tags=TAG, auth=[], responses={200: dict}, parameters=[OpenApiParameter("q", str)]
    )
    def get(self, request):
        """Ayuda mientras se escribe en el buscador."""
        ctx = self.contexto()
        texto = request.query_params.get("q", "")
        return self.responder(request, lambda: catalogo.sugerencias(ctx, texto))


class CompararView(_Publica):
    ttl = TTL_FICHA

    @extend_schema(
        tags=TAG,
        auth=[],
        responses={200: dict},
        parameters=[OpenApiParameter("ids", str, description="Ids separados por coma (hasta 4).")],
    )
    def get(self, request):
        """Hasta 4 productos lado a lado con una tabla de especificaciones unificada."""
        crudo = request.query_params.get("ids", "")[:80]
        ids: list[int] = []
        for trozo in crudo.split(","):
            trozo = trozo.strip()
            if trozo.isdigit() and 0 < int(trozo) < 2**31 and int(trozo) not in ids:
                ids.append(int(trozo))
        if not ids:
            raise ValidationError({"ids": "Indica los productos a comparar."})
        if len(ids) > catalogo.MAX_COMPARAR:
            raise ValidationError(
                {"ids": f"Puedes comparar hasta {catalogo.MAX_COMPARAR} productos."}
            )
        ctx = self.contexto()
        return self.responder(request, lambda: catalogo.comparar(ctx, ids))


class MapaDelSitioView(_Publica):
    ttl = TTL_MENU

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        """Direcciones públicas para los buscadores (sitemap)."""
        ctx = self.contexto()
        return self.responder(request, lambda: catalogo.mapa_del_sitio(ctx))


class FotoView(_Publica):
    """Una foto de un producto publicado. El archivo nunca cambia (una foto nueva es otra fila),
    por eso los navegadores y CDN la pueden guardar un año."""

    throttle_classes = [TiendaFotosThrottle]

    @extend_schema(tags=TAG, auth=[], responses={(200, "image/webp"): bytes})
    def get(self, request, foto_id: int, tam: str):
        if tam not in FORMATOS_FOTO:
            raise Http404
        ctx = self.contexto()
        foto = catalogo.foto_publica(ctx, foto_id)
        if foto is None:
            raise Http404
        campo = getattr(foto, FORMATOS_FOTO[tam])
        try:
            archivo = campo.open("rb")
        except (FileNotFoundError, ValueError):
            logger.warning("tienda_foto_sin_archivo", extra={"foto_id": foto_id})
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type="image/webp")
        respuesta["Cache-Control"] = "public, max-age=31536000, immutable"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class ConfiguracionPublicaView(_Publica):
    ttl = TTL_MENU

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        """Marca, contacto y textos de la tienda (los edita el negocio desde el panel)."""
        ctx = self.contexto()

        def construir():
            config = ConfiguracionTienda.objects.sin_ambito().get(
                organizacion_id=ctx.organizacion_id
            )
            return servicios.datos_publicos(config)

        return self.responder(request, construir)


class LogoView(_Publica):
    """El logo de la tienda. La dirección lleva su «versión»: un logo nuevo es otra dirección,
    por eso se puede guardar un año."""

    throttle_classes = [TiendaFotosThrottle]

    @extend_schema(tags=TAG, auth=[], responses={(200, "image/png"): bytes})
    def get(self, request, version: str):
        ctx = self.contexto()
        config = (
            ConfiguracionTienda.objects.sin_ambito()
            .filter(organizacion_id=ctx.organizacion_id)
            .first()
        )
        if config is None or not config.logo or config.logo_version != version:
            raise Http404
        try:
            archivo = config.logo.open("rb")
        except (FileNotFoundError, ValueError):
            logger.warning("tienda_logo_sin_archivo")
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type=servicios.tipo_de_logo(config))
        respuesta["Cache-Control"] = "public, max-age=31536000, immutable"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class UbigeosView(_Publica):
    """Lugares para elegir la dirección de entrega (departamentos y provincias; con
    ``?provincia=1501``, los distritos). Son datos fijos: se guardan un día."""

    ttl = 24 * 3600

    @extend_schema(tags=TAG, auth=[], responses={200: list})
    def get(self, request):
        from .envios import datos_de_ubigeos

        provincia = request.query_params.get("provincia", "")
        self.contexto()
        return self.responder(request, lambda: datos_de_ubigeos(provincia))


class OfertasView(_Publica):
    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        """Productos con oferta vigente, de mayor a menor descuento (con filtros y paginación)."""
        ctx = self.contexto()

        def construir():
            params = request.query_params.copy()
            params["oferta"] = "1"
            if not params.get("orden"):
                params["orden"] = "descuento"
            return catalogo.listar(ctx, params)

        return self.responder(request, construir)


class BannersView(_Publica):
    ttl = 60

    @extend_schema(tags=TAG, auth=[], responses={200: list})
    def get(self, request):
        """Banners del inicio vigentes (máximo 8)."""
        ctx = self.contexto()
        return self.responder(
            request,
            lambda: [banners.datos_publicos(b) for b in banners.vigentes(ctx.organizacion_id)],
        )


class BannerImagenView(_Publica):
    """Imagen de un banner. La dirección lleva su «versión»: una imagen nueva es otra dirección,
    por eso se puede guardar un año."""

    throttle_classes = [TiendaFotosThrottle]

    @extend_schema(tags=TAG, auth=[], responses={(200, "image/webp"): bytes})
    def get(self, request, banner_id: int, tam: str, version: str):
        if tam not in banners.TAMANOS:
            raise Http404
        ctx = self.contexto()
        banner = next(
            (b for b in banners.vigentes(ctx.organizacion_id) if b.pk == int(banner_id)), None
        )
        campo = None
        if banner is not None and banner.version == version:
            campo = banner.imagen_escritorio if tam == "escritorio" else banner.imagen_movil
        if not campo:
            raise Http404
        try:
            archivo = campo.open("rb")
        except (FileNotFoundError, ValueError):
            logger.warning("tienda_banner_sin_archivo", extra={"banner_id": banner_id})
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type="image/webp")
        respuesta["Cache-Control"] = "public, max-age=31536000, immutable"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class HoraView(APIView):
    """La hora del servidor, SIN caché: la cuenta regresiva de las ofertas corrige con ella el
    reloj del navegador del cliente (que puede estar adelantado o atrasado)."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TiendaThrottle]

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        from django.utils import timezone

        respuesta = Response({"ahora": timezone.now().isoformat()})
        respuesta["Cache-Control"] = "no-store"
        return respuesta
