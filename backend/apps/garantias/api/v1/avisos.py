"""API de los avisos de garantía por vencer, la baja del correo y los reportes."""

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiPublicaThrottle
from apps.garantias import avisos, reportes
from apps.garantias.models import AvisoGarantia, ConfiguracionGarantias, EstadoAviso
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

VER = "VENTAS.VER"
RESOLVER = "VENTAS.GARANTIA_RESOLVER"
VER_UTILIDAD = "VENTAS.VER_UTILIDAD"
TAG = ["garantias"]


class ConfiguracionEntrada(serializers.Serializer):
    avisos_activos = serializers.BooleanField(required=False)
    dias_antes = serializers.IntegerField(required=False, min_value=1, max_value=90)


def _resumen_de_avisos(organizacion_id: int) -> dict:
    cuentas = {
        f["estado"]: f["n"]
        for f in AvisoGarantia.objects.filter(empresa__organizacion_id=organizacion_id)
        .values("estado")
        .annotate(n=Count("id"))
    }
    return {e.value: cuentas.get(e.value, 0) for e in EstadoAviso}


class ConfiguracionView(APIView):
    """Si se avisa por correo que una garantía vence pronto, y con cuántos días de anticipación."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "patch": RESOLVER}

    def _organizacion(self, request) -> int:
        if request.user.organizacion_id is None:
            raise ValidationError("No hay una organización activa.")
        return request.user.organizacion_id

    def _datos(self, organizacion_id: int) -> dict:
        return {
            **avisos.datos_de_configuracion(organizacion_id),
            "avisos": _resumen_de_avisos(organizacion_id),
        }

    @extend_schema(tags=TAG)
    def get(self, request):
        return Response(self._datos(self._organizacion(request)))

    @extend_schema(tags=TAG, request=ConfiguracionEntrada)
    def patch(self, request):
        organizacion_id = self._organizacion(request)
        entrada = ConfiguracionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        antes = avisos.datos_de_configuracion(organizacion_id)
        config, _ = ConfiguracionGarantias.objects.get_or_create(
            organizacion_id=organizacion_id, defaults=entrada.validated_data
        )
        for campo, valor in entrada.validated_data.items():
            setattr(config, campo, valor)
        config.save()
        despues = avisos.datos_de_configuracion(organizacion_id)
        if antes != despues:
            registrar(
                "garantias.avisos_configurados",
                recurso_tipo="configuracion_garantias",
                recurso_id=config.pk,
                resumen="Avisos de garantía por vencer: configuración modificada",
                detalle={"antes": antes, "despues": despues},
            )
        return Response(self._datos(organizacion_id))


class BajaEntrada(serializers.Serializer):
    token = serializers.CharField(max_length=600)


class BajaPublicaView(APIView):
    """El enlace «darme de baja» del correo: un clic y no se le escribe más."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ApiPublicaThrottle]

    @extend_schema(tags=TAG, auth=[], request=BajaEntrada, responses={200: dict})
    def post(self, request):
        entrada = BajaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        avisos.dar_de_baja(entrada.validated_data["token"])
        respuesta = Response({"ok": True})
        respuesta["Cache-Control"] = "no-store"
        return respuesta


def _fecha(valor, campo: str):
    if valor in (None, ""):
        return None
    fecha = parse_date(str(valor))
    if fecha is None:
        raise ValidationError({campo: "Use el formato AAAA-MM-DD."})
    return fecha


class ReporteView(APIView):
    """Resumen de garantías de una empresa: situación, falla por marca, reclamos y cambios."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("desde", str, description="AAAA-MM-DD (por defecto, hace 90 días)"),
            OpenApiParameter("hasta", str, description="AAAA-MM-DD (por defecto, hoy)"),
        ],
    )
    def get(self, request):
        empresa_id = empresa_declarada(request, self)
        hoy = timezone.localdate()
        hasta = _fecha(request.query_params.get("hasta"), "hasta") or hoy
        desde = _fecha(request.query_params.get("desde"), "desde") or hasta - timedelta(days=90)
        if desde > hasta:
            raise ValidationError({"desde": "No puede ser posterior a «hasta»."})
        if (hasta - desde).days > 366:
            raise ValidationError({"desde": "El periodo no puede pasar de un año."})
        # El costo de los cambios solo lo ve quien puede ver costos y utilidad de las ventas.
        ver_costos = motor.alcance_de(request.user, VER_UTILIDAD, empresa_id) is not None
        return Response(reportes.resumen(empresa_id, desde, hasta, ver_costos=ver_costos, hoy=hoy))
