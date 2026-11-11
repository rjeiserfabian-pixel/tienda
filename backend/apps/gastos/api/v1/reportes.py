"""API de los reportes de gastos: se ven en pantalla y se descargan en Excel."""

import logging
from datetime import date

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.caja.api.v1.conciliacion import _textos  # noqa: I001
from apps.caja.reportes import nombre_archivo
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle
from apps.gastos import reportes
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

from .views import TAG

logger = logging.getLogger(__name__)

VER = "GASTOS.VER"
EXPORTAR = "GASTOS.EXPORTAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PARAMETROS = [
    OpenApiParameter("empresa", int, required=True),
    OpenApiParameter("desde", str, required=True, description="AAAA-MM-DD"),
    OpenApiParameter("hasta", str, required=True, description="AAAA-MM-DD"),
]


class Parametros(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _parametros(request) -> tuple[Empresa, date | None, date | None]:
        p = Parametros(data=request.query_params)
        p.is_valid(raise_exception=True)
        empresa = Empresa.objects.filter(
            pk=p.validated_data["empresa"], estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return empresa, p.validated_data.get("desde"), p.validated_data.get("hasta")

    @staticmethod
    def _vista(datos) -> Response:
        respuesta = Response(_textos(datos))
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class _Exportacion(_Base):
    permiso_requerido = EXPORTAR
    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @staticmethod
    def _archivo(contenido: bytes, nombre: str, accion: str, empresa: Empresa, datos: dict):
        registrar(
            f"gastos.{accion}",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Reporte de gastos exportado: {nombre}",
            detalle={"desde": datos["desde"], "hasta": datos["hasta"]},
        )
        logger.info("reporte_gastos_exportado", extra={"empresa_id": empresa.pk, "reporte": accion})
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


def _sufijo(datos: dict) -> str:
    return f"{datos['desde']:%Y%m%d}_{datos['hasta']:%Y%m%d}"


class ResumenView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta = self._parametros(request)
        return self._vista(reportes.resumen(empresa, desde, hasta))


class ResumenExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, desde, hasta = self._parametros(request)
        datos = reportes.resumen(empresa, desde, hasta)
        nombre = nombre_archivo("gastos-por-categoria", empresa, _sufijo(datos))
        return self._archivo(
            reportes.resumen_excel(empresa, datos), nombre, "resumen_exportado", empresa, datos
        )


class ProveedoresView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta = self._parametros(request)
        return self._vista(reportes.por_proveedor(empresa, desde, hasta))


class ProveedoresExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, desde, hasta = self._parametros(request)
        datos = reportes.por_proveedor(empresa, desde, hasta)
        nombre = nombre_archivo("gastos-por-proveedor", empresa, _sufijo(datos))
        return self._archivo(
            reportes.proveedores_excel(empresa, datos),
            nombre,
            "proveedores_exportado",
            empresa,
            datos,
        )


class SinComprobanteView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta = self._parametros(request)
        return self._vista(reportes.sin_comprobante(empresa, desde, hasta))


class SinComprobanteExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, desde, hasta = self._parametros(request)
        datos = reportes.sin_comprobante(empresa, desde, hasta)
        nombre = nombre_archivo("gastos-sin-comprobante", empresa, _sufijo(datos))
        return self._archivo(
            reportes.sin_comprobante_excel(empresa, datos),
            nombre,
            "sin_comprobante_exportado",
            empresa,
            datos,
        )
