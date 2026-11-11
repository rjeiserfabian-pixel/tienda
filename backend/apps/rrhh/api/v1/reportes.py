"""API de los reportes de RR.HH. (por empresa).

* ``RRHH.REPORTES.VER``: ver el reporte en pantalla (incluye sueldos).
* ``RRHH.REPORTES.EXPORTAR``: descargarlo en Excel; queda en la auditoría.
"""

import logging

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle
from apps.organizacion.models import Empresa, Estado
from apps.rrhh import reportes
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

logger = logging.getLogger(__name__)

TAG = ["rrhh"]
VER = "RRHH.REPORTES.VER"
EXPORTAR = "RRHH.REPORTES.EXPORTAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ParametrosReporte(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    periodo = serializers.CharField(max_length=7, required=False)
    anio = serializers.IntegerField(min_value=2000, max_value=2100, required=False)


_PARAMETROS = [
    OpenApiParameter("empresa", int, required=True),
    OpenApiParameter("periodo", str, description="AAAA-MM (planilla y PLAME)"),
    OpenApiParameter("anio", int, description="Año (resumen anual)"),
]


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _armar(request, tipo: str):
        if tipo not in reportes.TIPOS:
            raise ValidationError({"tipo": "Elija un reporte de la lista."})
        parametros = ParametrosReporte(data=request.query_params)
        parametros.is_valid(raise_exception=True)
        p = parametros.validated_data
        empresa = Empresa.objects.filter(pk=p["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        reporte = reportes.armar(tipo, empresa, periodo=p.get("periodo"), anio=p.get("anio"))
        return empresa, reporte


class ReporteVistaView(_Base):
    """El reporte en pantalla (las primeras filas de cada tabla y sus totales)."""

    permisos_por_accion = {"get": VER}
    throttle_classes = [ApiAutenticadaThrottle]

    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request, tipo):
        _, reporte = self._armar(request, tipo)
        respuesta = Response(reportes.vista(reporte))
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class ReporteExcelView(_Base):
    """Descarga el reporte en Excel. Queda en la auditoría (sin los datos)."""

    permisos_por_accion = {"get": EXPORTAR}
    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request, tipo):
        empresa, reporte = self._armar(request, tipo)
        contenido = reportes.libro_excel(empresa, reporte)
        registrar(
            "rrhh.reporte_exportado",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Reporte de RR.HH. exportado: {reporte.titulo.lower()}",
            detalle={"reporte": tipo, "filas": sum(len(t.filas) for t in reporte.tablas)},
        )
        logger.info("reporte_rrhh_exportado", extra={"empresa_id": empresa.pk, "reporte": tipo})
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{reporte.archivo}"'
        respuesta["Cache-Control"] = "no-store"
        return respuesta
