"""API de los extras de caja: avisos, bancarización, vouchers y caja chica."""

from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.caja import adjuntos, alertas, bancarizacion, caja_chica
from apps.caja.models import AdjuntoMovimiento, MovimientoCaja, RendicionCaja
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import CuentaFinanciera
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada

from .conciliacion import _textos
from .serializers import AnulacionEntrada, MovimientoSerializer
from .views import TAG, _entero, _fecha

VER = "CAJA.MOVIMIENTOS.VER"
CREAR = "CAJA.MOVIMIENTOS.CREAR"
ANULAR = "CAJA.MOVIMIENTOS.ANULAR"
REPORTES = "CAJA.REPORTES.VER"
CHICA_VER = "CAJA.CAJA_CHICA.VER"
CHICA_RENDIR = "CAJA.CAJA_CHICA.RENDIR"
MAX_FILAS_BANCARIZACION = 500


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


class _ConEmpresa(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    def empresa(self, request) -> Empresa:
        return _empresa_activa(empresa_declarada(request, self))

    @staticmethod
    def respuesta(datos) -> Response:
        r = Response(_textos(datos))
        r["Cache-Control"] = "no-store"
        return r


# -- avisos -------------------------------------------------------------------
class AlertasView(_ConEmpresa):
    """Lo que conviene mirar hoy: saldos bajos, sesiones largas, extractos sin cerrar…"""

    permiso_requerido = VER

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        return self.respuesta(alertas.alertas(self.empresa(request)))


# -- bancarización ---------------------------------------------------------------
class BancarizacionView(_ConEmpresa):
    """Pagos y cobros en efectivo que llegan al límite de bancarización, en un rango de fechas."""

    permiso_requerido = REPORTES

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = self.empresa(request)
        hoy = timezone.localdate()
        desde = _fecha(request.query_params, "desde") or hoy.replace(day=1)
        hasta = _fecha(request.query_params, "hasta") or hoy
        if desde > hasta:
            raise ValidationError({"desde": "«Desde» no puede ser posterior a «Hasta»."})
        if (hasta - desde).days > 732:
            raise ValidationError({"desde": "El rango no puede pasar de dos años."})
        consulta = bancarizacion.sin_bancarizar(empresa, desde, hasta)
        total = consulta.count()
        filas = MovimientoSerializer(consulta[:MAX_FILAS_BANCARIZACION], many=True).data
        return self.respuesta(
            {
                "desde": desde,
                "hasta": hasta,
                "total": total,
                "truncado": total > MAX_FILAS_BANCARIZACION,
                "umbrales": bancarizacion.UMBRALES,
                "filas": filas,
            }
        )


# -- vouchers ------------------------------------------------------------------
class AdjuntoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdjuntoMovimiento
        fields = [
            "id",
            "movimiento",
            "tipo_contenido",
            "nombre_original",
            "tamano",
            "subido_por_nombre",
            "creado_en",
        ]
        read_only_fields = fields


class AdjuntoEntrada(serializers.Serializer):
    movimiento = serializers.IntegerField(min_value=1)
    archivo = serializers.FileField(max_length=200, allow_empty_file=False)


class AdjuntoViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Vouchers de los movimientos. Listado: ``?movimiento=ID``. Subir: ``POST`` con el archivo."""

    modelo = AdjuntoMovimiento
    serializer_class = AdjuntoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "delete", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "archivo": VER,
        "create": CREAR,
        "destroy": CREAR,
    }

    def get_throttles(self):
        return [ApiAutenticadaThrottle()] if self.action == "create" else super().get_throttles()

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                AdjuntoMovimiento.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
        else:
            movimiento = _entero(request.query_params, "movimiento")
            if movimiento is None and hasattr(request.data, "get"):
                movimiento = _entero(request.data, "movimiento")
            empresa_id = (
                MovimientoCaja.objects.filter(pk=movimiento)
                .values_list("empresa_id", flat=True)
                .first()
            )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(AdjuntoMovimiento.objects.all(), self.request.user, codigo)
        if self.action == "list":
            queryset = queryset.filter(
                movimiento_id=_entero(self.request.query_params, "movimiento")
            )
        return queryset.order_by("id")

    @extend_schema(tags=TAG, request=AdjuntoEntrada, responses={201: AdjuntoSerializer})
    def create(self, request, *args, **kwargs):
        datos = AdjuntoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        movimiento = (
            filtrar_por_alcance(
                MovimientoCaja.objects.select_related("empresa"), request.user, CREAR
            )
            .filter(pk=datos.validated_data["movimiento"])
            .first()
        )
        if movimiento is None:
            raise Http404
        adjunto = adjuntos.agregar(movimiento, datos.validated_data["archivo"], request.user)
        return Response(AdjuntoSerializer(adjunto).data, status=201)

    @extend_schema(tags=TAG, responses={204: None})
    def destroy(self, request, *args, **kwargs):
        adjuntos.eliminar(self.get_object(), request.user)
        return Response(status=204)

    @extend_schema(tags=TAG, responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path="archivo")
    def archivo(self, request, pk=None):
        """El voucher: solo con sesión y permiso. Las fotos se ven; el PDF siempre se descarga."""
        adjunto = self.get_object()
        try:
            abierto = adjunto.archivo.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404 from None
        respuesta = FileResponse(abierto, content_type=adjunto.tipo_contenido)
        extension = "pdf" if adjunto.tipo_contenido == adjuntos.PDF else "webp"
        disposicion = "attachment" if extension == "pdf" else "inline"
        respuesta["Content-Disposition"] = (
            f'{disposicion}; filename="voucher-{adjunto.movimiento_id}-{adjunto.pk}.{extension}"'
        )
        respuesta["Cache-Control"] = "private, max-age=3600"
        respuesta["X-Content-Type-Options"] = "nosniff"
        respuesta["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return respuesta


# -- caja chica ------------------------------------------------------------------
class CajaChicaView(_ConEmpresa):
    """Las cajas chicas de la empresa: su fondo fijo, lo que tienen y lo que falta rendir."""

    permiso_requerido = CHICA_VER

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        filas = caja_chica.resumen(self.empresa(request))
        return self.respuesta(
            [
                {
                    "cuenta": f["cuenta"].pk,
                    "nombre": f["cuenta"].nombre,
                    "moneda": f["cuenta"].moneda,
                    "sucursal_nombre": f["cuenta"].sucursal.nombre if f["cuenta"].sucursal else "",
                    "fondo": f["fondo"],
                    "saldo": f["saldo"],
                    "faltante": f["faltante"],
                    "por_rendir_cantidad": f["por_rendir_cantidad"],
                    "por_rendir_total": f["por_rendir_total"],
                }
                for f in filas
            ]
        )


class GastosPorRendirView(_ConEmpresa):
    """Los gastos de una caja chica que todavía no se rinden (``?cuenta=ID``)."""

    permiso_requerido = CHICA_VER

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = self.empresa(request)
        cuenta = CuentaFinanciera.objects.filter(
            empresa=empresa, pk=_entero(request.query_params, "cuenta")
        ).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja chica de la empresa."})
        gastos = caja_chica.gastos_por_rendir(cuenta).prefetch_related("adjuntos")
        return self.respuesta(MovimientoSerializer(gastos, many=True).data)


class RendicionSerializer(serializers.ModelSerializer):
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    origen_nombre = serializers.CharField(source="cuenta_origen.nombre", read_only=True)
    moneda = serializers.CharField(source="cuenta.moneda", read_only=True)

    class Meta:
        model = RendicionCaja
        fields = [
            "id",
            "numero",
            "empresa",
            "cuenta",
            "cuenta_nombre",
            "cuenta_origen",
            "origen_nombre",
            "moneda",
            "desde",
            "hasta",
            "total",
            "cantidad",
            "glosa",
            "rendida_por_nombre",
            "estado",
            "motivo_anulacion",
            "creado_en",
        ]
        read_only_fields = fields


class RendirEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    cuenta_origen = serializers.IntegerField(min_value=1)
    movimientos = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
        max_length=500,
    )
    glosa = serializers.CharField(max_length=250, required=False, allow_blank=True)


class RendicionViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Rendiciones de caja chica (``?empresa=ID``; filtros ``cuenta`` y ``estado``)."""

    modelo = RendicionCaja
    serializer_class = RendicionSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": CHICA_VER,
        "retrieve": CHICA_VER,
        "create": CHICA_RENDIR,
        "anular": ANULAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                RendicionCaja.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = RendicionCaja.objects.select_related("cuenta", "cuenta_origen")
        if self.action != "list":
            return filtrar_por_alcance(queryset, self.request.user, codigo)
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (cuenta := _entero(params, "cuenta")) is not None:
            queryset = queryset.filter(cuenta_id=cuenta)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("-id")

    @extend_schema(tags=TAG, request=RendirEntrada, responses={201: RendicionSerializer})
    def create(self, request, *args, **kwargs):
        datos = RendirEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        cuentas = CuentaFinanciera.objects.filter(empresa=empresa)
        cuenta = cuentas.filter(pk=v["cuenta"]).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja chica de la empresa."})
        origen = cuentas.filter(pk=v["cuenta_origen"]).first()
        if origen is None:
            raise ValidationError({"cuenta_origen": "Elija la caja que repone el fondo."})
        rendicion = caja_chica.rendir(
            empresa=empresa,
            cuenta=cuenta,
            cuenta_origen=origen,
            movimientos_ids=v.get("movimientos"),
            usuario=request.user,
            glosa=v.get("glosa", ""),
        )
        return Response(RendicionSerializer(rendicion).data, status=201)

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: RendicionSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        rendicion = caja_chica.anular(self.get_object(), motivo=datos.validated_data["motivo"])
        return Response(RendicionSerializer(rendicion).data)
