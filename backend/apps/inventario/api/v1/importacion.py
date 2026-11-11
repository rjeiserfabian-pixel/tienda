from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle, ImportacionThrottle
from apps.inventario import importacion
from apps.mantenimiento.importacion import ErrorImportacion
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["inventario"]
SALDO_INICIAL = "INVENTARIO.SALDO_INICIAL.CARGAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ImportacionEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    modo = serializers.ChoiceField(choices=["validar", "importar"], default="validar")
    archivo = serializers.FileField()


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


class _SaldoInicialBase(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = SALDO_INICIAL
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]


class SaldoInicialImportarView(_SaldoInicialBase):
    """Carga el saldo inicial de una empresa desde un Excel o CSV, en dos pasos.

    ``modo=validar`` informa sin guardar nada; ``modo=importar`` crea los movimientos de las filas
    válidas. Multipart con ``empresa``, ``fecha`` (AAAA-MM-DD), ``modo`` y ``archivo``.
    """

    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ApiAutenticadaThrottle, ImportacionThrottle]

    @extend_schema(
        tags=TAG, request={"multipart/form-data": ImportacionEntrada}, responses={200: dict}
    )
    def post(self, request):
        datos = ImportacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        try:
            if v["modo"] == "validar":
                informe, creados = importacion.validar(empresa, v["fecha"], v["archivo"]), 0
            else:
                informe = importacion.importar(empresa, v["fecha"], v["archivo"])
                creados = informe.validas
        except ErrorImportacion as error:
            raise ValidationError({"archivo": str(error)}) from None
        return Response({**informe.como_dict(), "modo": v["modo"], "creados": creados})


class SaldoInicialPlantillaView(_SaldoInicialBase):
    """Plantilla de Excel con los productos del catálogo ya listados (``?empresa=ID``)."""

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={(200, XLSX): bytes},
    )
    def get(self, request):
        empresa = _empresa_activa(empresa_declarada(request, self))
        respuesta = HttpResponse(importacion.plantilla_xlsx(empresa), content_type=XLSX)
        respuesta["Content-Disposition"] = 'attachment; filename="plantilla_saldo_inicial.xlsx"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta
