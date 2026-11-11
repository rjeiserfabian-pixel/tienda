"""Panel: ofertas de productos y banners del inicio de la tienda."""

import logging
from decimal import Decimal
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import EstadoRegistro, PrecioProducto, Producto
from apps.seguridad.permissions import PermisoRBAC
from apps.seguridad.services import permisos_engine
from apps.tienda import banners, catalogo, ofertas
from apps.tienda.exceptions import DatosInvalidos
from apps.tienda.models import BannerTienda, OfertaProducto

logger = logging.getLogger(__name__)

TAG = ["tienda"]
GESTIONAR = "TIENDA.OFERTAS.GESTIONAR"
UTILIDAD = "VENTAS.VER_UTILIDAD"
TAM_PAGINA = 25


class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = dict.fromkeys(("get", "post", "patch", "delete"), GESTIONAR)

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización, no de una empresa

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def contexto(self, request) -> SimpleNamespace:
        """Lo que hace falta de la tienda de la organización (aunque esté cerrada): su lista."""
        from apps.tienda.api.v1.admin import _lista_efectiva
        from apps.tienda.models import ConfiguracionTienda

        config = ConfiguracionTienda.objects.filter(
            organizacion_id=request.user.organizacion_id
        ).first()
        lista = _lista_efectiva(config) if config is not None else None
        if lista is None:
            raise DatosInvalidos("La tienda no tiene una lista de precios para mostrar.")
        return SimpleNamespace(organizacion_id=request.user.organizacion_id, lista_id=lista.pk)

    def ve_costos(self, request) -> bool:
        return UTILIDAD in permisos_engine.codigos_en_alguna_empresa(request.user)


# ---------------------------------------------------------------------------
# Ofertas
# ---------------------------------------------------------------------------
class OfertaEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1, required=False)
    precio_oferta = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False
    )
    desde = serializers.DateTimeField(required=False)
    hasta = serializers.DateTimeField(required=False)
    etiqueta = serializers.CharField(max_length=30, required=False, allow_blank=True)
    activa = serializers.BooleanField(required=False)


def _d2(valor: Decimal) -> str:
    return format(valor.quantize(Decimal("0.01")), "f")


def _salida_oferta(o: OfertaProducto, normal: Decimal | None, costo: Decimal, ver_costos: bool):
    ahora = timezone.now()
    ahorro = None
    if normal and normal > 0:
        ahorro = int(((1 - o.precio_oferta / normal) * 100).quantize(Decimal("1")))
    salida = {
        "id": o.pk,
        "producto": {
            "id": o.producto_id,
            "codigo": o.producto.codigo,
            "nombre": o.producto.nombre,
        },
        "precio_normal": None if normal is None else _d2(normal),
        "precio_oferta": _d2(o.precio_oferta),
        "ahorro_pct": ahorro,
        "desde": o.desde.isoformat(),
        "hasta": o.hasta.isoformat(),
        "etiqueta": o.etiqueta,
        "activa": o.activa,
        "estado": ofertas.estado_de(o, ahora),
    }
    if ver_costos and o.precio_oferta > 0:
        # Solo quien ve costos y utilidad: cuánto queda de ganancia sobre el precio de oferta.
        salida["margen_pct"] = int(
            (((o.precio_oferta - costo) / o.precio_oferta) * 100).quantize(Decimal("1"))
        )
    return salida


def _normales(ctx, producto_ids: list[int]) -> dict[int, Decimal]:
    filas = PrecioProducto.objects.sin_ambito().filter(
        producto_id__in=producto_ids, lista_id=ctx.lista_id
    )
    return {f.producto_id: f.precio for f in filas}


class OfertasView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        ctx = self.contexto(request)
        qs = (
            OfertaProducto.objects.sin_ambito()
            .filter(organizacion_id=request.user.organizacion_id)
            .select_related("producto")
        )
        ahora = timezone.now()
        estado = request.query_params.get("estado", "")
        if estado == ofertas.VIGENTE:
            qs = qs.filter(activa=True, desde__lte=ahora, hasta__gt=ahora)
        elif estado == ofertas.PROGRAMADA:
            qs = qs.filter(activa=True, desde__gt=ahora)
        elif estado == ofertas.VENCIDA:
            qs = qs.filter(activa=True, hasta__lte=ahora)
        elif estado == ofertas.PAUSADA:
            qs = qs.filter(activa=False)
        if texto := (request.query_params.get("q") or "").strip()[:80]:
            qs = qs.filter(
                Q(producto__nombre__icontains=texto) | Q(producto__codigo__icontains=texto)
            )
        total = qs.count()
        try:
            pagina = max(int(request.query_params.get("page", 1)), 1)
        except ValueError:
            pagina = 1
        filas = list(qs.order_by("-desde", "-id")[(pagina - 1) * TAM_PAGINA : pagina * TAM_PAGINA])
        normales = _normales(ctx, [o.producto_id for o in filas])
        ver = self.ve_costos(request)
        return Response(
            {
                "count": total,
                "page": pagina,
                "page_size": TAM_PAGINA,
                "ver_margen": ver,
                "results": [
                    _salida_oferta(o, normales.get(o.producto_id), o.producto.costo, ver)
                    for o in filas
                ],
            }
        )

    @extend_schema(tags=TAG, request=OfertaEntrada, responses={201: dict})
    def post(self, request):
        ctx = self.contexto(request)
        entrada = OfertaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        for campo in ("producto", "precio_oferta", "desde", "hasta"):
            if campo not in d:
                raise DatosInvalidos("Completa el producto, el precio y las fechas de la oferta.")
        producto = _producto_de(request, d["producto"])
        ver = self.ve_costos(request)
        oferta = ofertas.guardar(
            ctx,
            oferta=None,
            producto=producto,
            precio=d["precio_oferta"],
            desde=d["desde"],
            hasta=d["hasta"],
            etiqueta=d.get("etiqueta", ""),
            activa=d.get("activa", True),
            ver_costos=ver,
        )
        return Response(
            _salida_oferta(oferta, ofertas.precio_normal(ctx, producto), producto.costo, ver),
            status=201,
        )


def _producto_de(request, producto_id: int) -> Producto:
    producto = (
        Producto.objects.sin_ambito()
        .filter(
            pk=producto_id,
            organizacion_id=request.user.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            publicado_web=True,
        )
        .first()
    )
    if producto is None:
        raise DatosInvalidos("Elige un producto publicado en la tienda.")
    return producto


class OfertaView(_Admin):
    def _oferta(self, request, pk: int) -> OfertaProducto:
        oferta = (
            OfertaProducto.objects.sin_ambito()
            .select_related("producto")
            .filter(pk=pk, organizacion_id=request.user.organizacion_id)
            .first()
        )
        if oferta is None:
            raise NotFound("No existe esa oferta.")
        return oferta

    @extend_schema(tags=TAG, request=OfertaEntrada, responses={200: dict})
    def patch(self, request, pk: int):
        ctx = self.contexto(request)
        oferta = self._oferta(request, pk)
        entrada = OfertaEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        ver = self.ve_costos(request)
        producto = oferta.producto
        if "producto" in d and d["producto"] != oferta.producto_id:
            producto = _producto_de(request, d["producto"])
        oferta = ofertas.guardar(
            ctx,
            oferta=oferta,
            producto=producto,
            precio=d.get("precio_oferta", oferta.precio_oferta),
            desde=d.get("desde", oferta.desde),
            hasta=d.get("hasta", oferta.hasta),
            etiqueta=d.get("etiqueta", oferta.etiqueta),
            activa=d.get("activa", oferta.activa),
            ver_costos=ver,
        )
        return Response(
            _salida_oferta(oferta, ofertas.precio_normal(ctx, producto), producto.costo, ver)
        )

    @extend_schema(tags=TAG, responses={204: None})
    @transaction.atomic
    def delete(self, request, pk: int):
        oferta = self._oferta(request, pk)
        oferta.delete()  # borrado lógico
        registrar(
            "tienda.oferta_eliminada",
            recurso_tipo="oferta_producto",
            recurso_id=oferta.pk,
            resumen=f"Oferta de «{oferta.producto.nombre}» eliminada",
        )
        transaction.on_commit(catalogo.invalidar)
        return Response(status=204)


class ProductosParaOfertaView(_Admin):
    """Buscador de productos publicados para elegir uno al crear la oferta."""

    @extend_schema(tags=TAG, responses={200: list})
    def get(self, request):
        ctx = self.contexto(request)
        qs = Producto.objects.sin_ambito().filter(
            organizacion_id=request.user.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            publicado_web=True,
        )
        if texto := (request.query_params.get("q") or "").strip()[:80]:
            qs = qs.filter(Q(nombre__icontains=texto) | Q(codigo__icontains=texto))
        filas = list(qs.order_by("nombre")[:20])
        normales = _normales(ctx, [p.pk for p in filas])
        return Response(
            [
                {
                    "id": p.pk,
                    "codigo": p.codigo,
                    "nombre": p.nombre,
                    "precio_normal": None if normales.get(p.pk) is None else _d2(normales[p.pk]),
                }
                for p in filas
            ]
        )


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------
class BannerEntrada(serializers.Serializer):
    titulo = serializers.CharField(max_length=100, required=False)
    subtitulo = serializers.CharField(max_length=160, required=False, allow_blank=True)
    boton_texto = serializers.CharField(max_length=30, required=False, allow_blank=True)
    enlace = serializers.CharField(max_length=300, required=False, allow_blank=True)
    alt = serializers.CharField(max_length=150, required=False)
    orden = serializers.IntegerField(min_value=0, max_value=1000, required=False)
    desde = serializers.DateTimeField(required=False, allow_null=True)
    hasta = serializers.DateTimeField(required=False, allow_null=True)
    activo = serializers.BooleanField(required=False, default=True)
    quitar_imagen_movil = serializers.BooleanField(required=False)

    def validate_enlace(self, valor):
        return banners.validar_enlace(valor)


def _salida_banner(b: BannerTienda) -> dict:
    ahora = timezone.now()
    if not b.activo:
        estado = "PAUSADO"
    elif b.desde and ahora < b.desde:
        estado = "PROGRAMADO"
    elif b.hasta and ahora >= b.hasta:
        estado = "VENCIDO"
    elif not b.imagen_escritorio:
        estado = "SIN_IMAGEN"
    else:
        estado = "VIGENTE"
    return {
        "id": b.pk,
        "titulo": b.titulo,
        "subtitulo": b.subtitulo,
        "boton_texto": b.boton_texto,
        "enlace": b.enlace,
        "alt": b.alt,
        "orden": b.orden,
        "desde": b.desde.isoformat() if b.desde else None,
        "hasta": b.hasta.isoformat() if b.hasta else None,
        "activo": b.activo,
        "estado": estado,
        "tiene_escritorio": bool(b.imagen_escritorio),
        "tiene_movil": bool(b.imagen_movil),
        "version": b.version,
    }


def _banners_de(request):
    return BannerTienda.objects.sin_ambito().filter(organizacion_id=request.user.organizacion_id)


class BannersView(_Admin):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(tags=TAG, responses={200: list})
    def get(self, request):
        return Response([_salida_banner(b) for b in _banners_de(request).order_by("orden", "id")])

    @extend_schema(tags=TAG, request=BannerEntrada, responses={201: dict})
    @transaction.atomic
    def post(self, request):
        entrada = BannerEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        if not d.get("titulo") or not d.get("alt"):
            raise DatosInvalidos("Escribe el título y el texto alternativo de la imagen.")
        if _banners_de(request).count() >= 30:
            raise DatosInvalidos("Llegaste al máximo de 30 banners. Elimina alguno antiguo.")
        escritorio = request.FILES.get("imagen_escritorio")
        if escritorio is None:
            raise DatosInvalidos("Sube la imagen del banner para computadora.")
        d.pop("quitar_imagen_movil", None)
        banner = BannerTienda(organizacion_id=request.user.organizacion_id, **d)
        try:
            banners.poner_imagen(banner, "escritorio", escritorio)
            if movil := request.FILES.get("imagen_movil"):
                banners.poner_imagen(banner, "movil", movil)
        except Exception:
            # Si algo falla, no dejar archivos sueltos de lo que ya se alcanzó a guardar.
            banners._borrar(banner.imagen_escritorio)
            banners._borrar(banner.imagen_movil)
            raise
        banners.auditar("tienda.banner_creado", banner, f"Banner «{banner.titulo}» creado")
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida_banner(banner), status=201)


class BannerView(_Admin):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def _banner(self, request, pk: int) -> BannerTienda:
        banner = _banners_de(request).filter(pk=pk).first()
        if banner is None:
            raise NotFound("No existe ese banner.")
        return banner

    @extend_schema(tags=TAG, request=BannerEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request, pk: int):
        banner = self._banner(request, pk)
        entrada = BannerEntrada(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        d = dict(entrada.validated_data)
        quitar_movil = d.pop("quitar_imagen_movil", False)
        for campo, valor in d.items():
            setattr(banner, campo, " ".join(valor.split()) if isinstance(valor, str) else valor)
        if not banner.titulo or not banner.alt:
            raise DatosInvalidos("El título y el texto alternativo no pueden quedar vacíos.")
        banner.save()
        if escritorio := request.FILES.get("imagen_escritorio"):
            banners.poner_imagen(banner, "escritorio", escritorio)
        if movil := request.FILES.get("imagen_movil"):
            banners.poner_imagen(banner, "movil", movil)
        elif quitar_movil:
            banners.quitar_imagen(banner, "movil")
        banners.auditar("tienda.banner_editado", banner, f"Banner «{banner.titulo}» editado")
        transaction.on_commit(catalogo.invalidar)
        return Response(_salida_banner(banner))

    @extend_schema(tags=TAG, responses={204: None})
    @transaction.atomic
    def delete(self, request, pk: int):
        banner = self._banner(request, pk)
        banner.delete()  # borrado lógico (los archivos se conservan para la auditoría)
        banners.auditar("tienda.banner_eliminado", banner, f"Banner «{banner.titulo}» eliminado")
        transaction.on_commit(catalogo.invalidar)
        return Response(status=204)


class BannerVistaPreviaView(_Admin):
    """La imagen del banner para el panel (con sesión): sirve aunque la tienda esté cerrada."""

    @extend_schema(tags=TAG, responses={(200, "image/webp"): bytes})
    def get(self, request, pk: int, tam: str):
        if tam not in banners.TAMANOS:
            raise Http404
        banner = _banners_de(request).filter(pk=pk).first()
        campo = None
        if banner is not None:
            campo = banner.imagen_escritorio if tam == "escritorio" else banner.imagen_movil
        if not campo:
            raise Http404
        try:
            archivo = campo.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type="image/webp")
        respuesta["Cache-Control"] = "private, no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta
