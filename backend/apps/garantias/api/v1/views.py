"""Consulta de garantías: por serie o IMEI, comprobante, cliente (nombre o documento) o producto."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiPublicaThrottle, GarantiaConsultaThrottle
from apps.garantias import publico
from apps.garantias.models import EstadoGarantia, Garantia
from apps.inventario.models import SerieProducto
from apps.seguridad.mixins import filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC

PERMISO = "VENTAS.VER"
TAG = ["garantias"]
POR_VENCER_DIAS = 30


class GarantiaSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    comprobante_numero = serializers.CharField(source="comprobante.numero_completo", read_only=True)
    empresa_nombre = serializers.CharField(source="empresa.razon_social", read_only=True)
    vigente = serializers.SerializerMethodField()
    dias_restantes = serializers.SerializerMethodField()
    situacion = serializers.SerializerMethodField()

    class Meta:
        model = Garantia
        fields = [
            "id",
            "empresa",
            "empresa_nombre",
            "producto",
            "producto_nombre",
            "numero_serie",
            "cantidad",
            "cliente_nombre",
            "cliente_documento",
            "comprobante",
            "comprobante_numero",
            "fecha_inicio",
            "meses",
            "vence_el",
            "estado",
            "vigente",
            "dias_restantes",
            "situacion",
            "motivo_anulacion",
        ]
        read_only_fields = fields

    def get_vigente(self, obj) -> bool:
        return obj.vigente()

    def get_dias_restantes(self, obj) -> int:
        return obj.dias_restantes()

    def get_situacion(self, obj) -> str:
        """ANULADA, REEMPLAZADA, VENCIDA, POR_VENCER (30 días o menos) o VIGENTE."""
        return publico.situacion_de(obj)


class _Base:
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = PERMISO

    def get_queryset(self):
        base = Garantia.objects.select_related("producto", "comprobante", "empresa")
        return filtrar_por_alcance(
            base, self.request.user, PERMISO, campo_empresa="empresa_id", campo_propio=None
        )


class GarantiaListView(_Base, generics.ListAPIView):
    """Lista y busca garantías.

    Filtros: ``q`` (serie o IMEI, número de comprobante, nombre o documento del cliente,
    producto), ``situacion`` (VIGENTE, POR_VENCER, VENCIDA, ANULADA), ``empresa``.
    """

    serializer_class = GarantiaSerializer
    pagination_class = PaginaEstandar

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        hoy = timezone.localdate()
        if p.get("empresa", "").isdigit():
            qs = qs.filter(empresa_id=int(p["empresa"]))
        texto = " ".join((p.get("q") or "").split())[:60]
        if texto:
            qs = qs.filter(
                Q(numero_serie__icontains=texto)
                | Q(cliente_documento__icontains=texto)
                | Q(cliente_nombre__icontains=texto)
                | Q(producto__nombre__icontains=texto)
                | Q(comprobante__serie__icontains=texto)
                | Q(comprobante__serie=texto.split("-")[0], comprobante__numero=_numero(texto))
            )
        situacion = (p.get("situacion") or "").upper()
        activa = Q(estado=EstadoGarantia.ACTIVA)
        if situacion in ("ANULADA", "REEMPLAZADA"):
            qs = qs.filter(estado=situacion)
        elif situacion == "VENCIDA":
            qs = qs.filter(activa, vence_el__lt=hoy)
        elif situacion == "POR_VENCER":
            qs = qs.filter(
                activa, vence_el__gte=hoy, vence_el__lte=hoy + timedelta(days=POR_VENCER_DIAS)
            )
        elif situacion == "VIGENTE":
            qs = qs.filter(activa, vence_el__gte=hoy)
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Serie/IMEI, comprobante, cliente o producto"),
            OpenApiParameter("situacion", str, description="VIGENTE, POR_VENCER, VENCIDA, ANULADA"),
        ],
        tags=TAG,
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


def _numero(texto: str) -> int:
    """El correlativo de «F001-00000012» (o -1 si no tiene forma de comprobante)."""
    cola = texto.rsplit("-", 1)[-1] if "-" in texto else ""
    return int(cola) if cola.isdigit() else -1


class GarantiaDetalleView(_Base, generics.RetrieveAPIView):
    """Una garantía con la historia de su unidad (entradas y salidas del almacén)."""

    serializer_class = GarantiaSerializer

    @extend_schema(tags=TAG)
    def get(self, request, *args, **kwargs):
        garantia = self.get_object()
        datos = self.get_serializer(garantia).data
        datos["historial"] = _historial(garantia)
        datos["reclamos"] = [
            {
                "id": r.pk,
                "numero_completo": r.numero_completo,
                "fecha": r.fecha.isoformat(),
                "estado": r.estado,
                "estado_texto": r.get_estado_display(),
                "descripcion": r.descripcion,
            }
            for r in garantia.reclamos.order_by("-id")
        ]
        return Response(datos)


def _historial(garantia: Garantia) -> list[dict]:
    """Cuándo entró la unidad, de qué almacén salió y cuándo se vendió, en orden."""
    eventos: list[dict] = []
    if garantia.numero_serie:
        series = SerieProducto.objects.select_related(
            "almacen", "entrada__movimiento", "salida__movimiento"
        ).filter(producto_id=garantia.producto_id, numero=garantia.numero_serie)
        for s in series:
            eventos.append(
                {
                    "fecha": s.entrada.fecha.isoformat(),
                    "evento": f"Entró al almacén {s.almacen.nombre}",
                    "origen": s.entrada.movimiento.origen,
                }
            )
            if s.salida is not None:
                eventos.append(
                    {
                        "fecha": s.salida.fecha.isoformat(),
                        "evento": f"Salió del almacén {s.almacen.nombre}",
                        "origen": s.salida.movimiento.origen,
                    }
                )
    eventos.append(
        {
            "fecha": garantia.fecha_inicio.isoformat(),
            "evento": f"Vendido en {garantia.comprobante.numero_completo}",
            "origen": "VENTA",
        }
    )
    if garantia.reemplaza_a_id:
        eventos.append(
            {
                "fecha": garantia.fecha_inicio.isoformat(),
                "evento": "Entregada como cambio por garantía (conserva el plazo que quedaba)",
                "origen": "CAMBIO",
            }
        )
    if garantia.estado == EstadoGarantia.ANULADA and garantia.anulada_en:
        eventos.append(
            {
                "fecha": timezone.localtime(garantia.anulada_en).date().isoformat(),
                "evento": f"Garantía anulada: {garantia.motivo_anulacion}",
                "origen": "ANULACION",
            }
        )
    return sorted(eventos, key=lambda e: e["fecha"])


class CertificadoView(_Base, generics.RetrieveAPIView):
    """Lo que lleva el certificado de garantía impreso: emisor, producto, cliente y condiciones."""

    serializer_class = GarantiaSerializer

    @extend_schema(tags=TAG)
    def get(self, request, *args, **kwargs):
        g = self.get_object()
        e = g.empresa
        datos = dict(self.get_serializer(g).data)
        datos.update(
            {
                "emisor": {
                    "empresa": e.pk,
                    "tiene_logo": bool(e.logo),
                    "nombre": e.nombre_comercial or e.razon_social,
                    "ruc": e.ruc,
                    "direccion": e.direccion_fiscal,
                    "telefono": e.telefono,
                    "correo": e.correo,
                },
                "condiciones": list(publico.CONDICIONES),
                "url_publica": publico.url_publica(g),
            }
        )
        return Response(datos)


class _PublicaBase(APIView):
    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    @staticmethod
    def sin_cache(respuesta):
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Robots-Tag"] = "noindex, nofollow"
        return respuesta


class EstadoPublicoView(_PublicaBase):
    """La garantía para su cliente. Sin sesión: el enlace secreto es la llave."""

    throttle_classes = [ApiPublicaThrottle]

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request, token: str):
        garantia = publico.garantia_por_token(token)
        if garantia is None:
            raise NotFound("No encontramos esa garantía. Revisa el enlace o el código QR.")
        return self.sin_cache(Response(publico.estado_publico(garantia)))


class BuscarPublicaEntrada(serializers.Serializer):
    serie = serializers.CharField(max_length=40)
    documento = serializers.CharField(max_length=20)


class BuscarPublicaView(_PublicaBase):
    """Encuentra el código de una garantía con la serie (o IMEI) y el documento de quien compró."""

    throttle_classes = [GarantiaConsultaThrottle]

    @extend_schema(tags=TAG, auth=[], request=BuscarPublicaEntrada, responses={200: dict})
    def post(self, request):
        datos = BuscarPublicaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        token = publico.token_por_serie_y_documento(
            datos.validated_data["serie"], datos.validated_data["documento"]
        )
        if token is None:  # el mismo mensaje para «no existe» y «el documento no coincide»
            raise NotFound("No encontramos una garantía con esos datos.")
        return self.sin_cache(Response({"token": token}))
