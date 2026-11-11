"""API de la asistencia diaria (por empresa).

* ``RRHH.ASISTENCIA.VER``: ver la grilla del mes.
* ``RRHH.ASISTENCIA.CARGAR``: marcar días, rangos y completar el mes.
No muestra sueldos ni cuentas: solo marcas y totales de días.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle
from apps.organizacion.models import Empresa, Estado
from apps.rrhh import asistencia
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["rrhh"]
VER = "RRHH.ASISTENCIA.VER"
CARGAR = "RRHH.ASISTENCIA.CARGAR"


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


def _entero(valor, nombre: str) -> int:
    if valor in (None, "") or not str(valor).isdigit():
        raise ValidationError({nombre: "Debe ser un número entero."})
    return int(valor)


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]


class DiaEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    personal = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    tipo = serializers.IntegerField(min_value=1, allow_null=True)  # null = borrar la marca
    horas_extra = serializers.DecimalField(
        max_digits=4, decimal_places=2, min_value=0, max_value=12, required=False, default=0
    )
    observacion = serializers.CharField(max_length=100, required=False, allow_blank=True)


class RangoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    personal = serializers.IntegerField(min_value=1)
    desde = serializers.DateField()
    hasta = serializers.DateField()
    tipo = serializers.IntegerField(min_value=1)
    sobrescribir = serializers.BooleanField(required=False, default=False)


class CompletarEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    anio = serializers.IntegerField()
    mes = serializers.IntegerField()
    descanso = serializers.ChoiceField(choices=list(asistencia.DESCANSOS))
    personal = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, allow_empty=False
    )


class GrillaView(_Base):
    """La asistencia de un mes: trabajadores × días con totales."""

    permisos_por_accion = {"get": VER}

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("anio", int, required=True),
            OpenApiParameter("mes", int, required=True),
            OpenApiParameter("q", str),
        ],
        responses={200: dict},
    )
    def get(self, request):
        empresa = _empresa_activa(empresa_declarada(request, self))
        params = request.query_params
        return Response(
            asistencia.grilla(
                empresa,
                _entero(params.get("anio"), "anio"),
                _entero(params.get("mes"), "mes"),
                q=params.get("q", ""),
            )
        )


class DiaView(_Base):
    permisos_por_accion = {"post": CARGAR}

    @extend_schema(tags=TAG, request=DiaEntrada, responses={200: dict})
    def post(self, request):
        entrada = DiaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        empresa = _empresa_activa(v["empresa"])
        personal = asistencia._trabajador(empresa.pk, v["personal"])
        marca = asistencia.marcar_dia(
            personal,
            v["fecha"],
            tipo_id=v["tipo"],
            horas_extra=v["horas_extra"],
            observacion=v.get("observacion", ""),
        )
        return Response({"marcada": marca is not None})


class RangoView(_Base):
    permisos_por_accion = {"post": CARGAR}

    @extend_schema(tags=TAG, request=RangoEntrada, responses={200: dict})
    def post(self, request):
        entrada = RangoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        empresa = _empresa_activa(v["empresa"])
        personal = asistencia._trabajador(empresa.pk, v["personal"])
        marcados = asistencia.marcar_rango(
            personal, v["desde"], v["hasta"], tipo_id=v["tipo"], sobrescribir=v["sobrescribir"]
        )
        return Response({"marcados": marcados})


class CompletarView(_Base):
    permisos_por_accion = {"post": CARGAR}

    @extend_schema(tags=TAG, request=CompletarEntrada, responses={200: dict})
    def post(self, request):
        entrada = CompletarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        empresa = _empresa_activa(v["empresa"])
        return Response(
            asistencia.completar_mes(
                empresa, v["anio"], v["mes"], descanso=v["descanso"], personal_ids=v.get("personal")
            )
        )
