import logging

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.compras import reportes, reportes_ordenes
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

logger = logging.getLogger(__name__)

EXPORTAR = "COMPRAS.EXPORTAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ParametrosRegistro(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)
    incluir_gastos = serializers.BooleanField(required=False, default=True)
    incluir_devoluciones = serializers.BooleanField(required=False, default=True)


class _BaseRegistro(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = EXPORTAR
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _resolver(request):
        parametros = ParametrosRegistro(data=request.query_params)
        parametros.is_valid(raise_exception=True)
        p = parametros.validated_data
        empresa = Empresa.objects.filter(pk=p["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        desde, hasta = reportes.validar_rango(p.get("desde"), p.get("hasta"))
        return empresa, desde, hasta, p["incluir_gastos"], p["incluir_devoluciones"]


_PARAMETROS = [
    OpenApiParameter("empresa", int, required=True),
    OpenApiParameter("desde", str, required=True, description="AAAA-MM-DD"),
    OpenApiParameter("hasta", str, required=True, description="AAAA-MM-DD"),
]


class RegistroComprasVistaView(_BaseRegistro):
    """Las primeras filas del registro de compras y sus totales, para ver antes de descargar."""

    throttle_classes = [ApiAutenticadaThrottle]

    @extend_schema(tags=["compras"], parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta, gastos, devoluciones = self._resolver(request)
        respuesta = Response(
            reportes.vista_previa(
                reportes.registro_de_compras(empresa, desde, hasta, gastos, devoluciones)
            )
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class RegistroComprasExcelView(_BaseRegistro):
    """Descarga el registro de compras de la empresa en Excel. Queda en la auditoría."""

    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @extend_schema(
        tags=["compras"],
        parameters=_PARAMETROS,
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request):
        empresa, desde, hasta, gastos, devoluciones = self._resolver(request)
        registro = reportes.registro_de_compras(empresa, desde, hasta, gastos, devoluciones)
        contenido = reportes.libro_excel(empresa, registro, desde, hasta)
        registrar(
            "compras.registro_exportado",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen="Registro de compras exportado",
            detalle={"desde": desde, "hasta": hasta, "filas": len(registro.filas)},
        )
        logger.info(
            "registro_compras_exportado",
            extra={"empresa_id": empresa.pk, "filas": len(registro.filas)},
        )
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = (
            f'attachment; filename="{reportes.nombre_archivo(empresa, desde, hasta)}"'
        )
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class ParametrosDevoluciones(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)


class _BaseDevoluciones(_BaseRegistro):
    @staticmethod
    def _resolver(request):
        parametros = ParametrosDevoluciones(data=request.query_params)
        parametros.is_valid(raise_exception=True)
        p = parametros.validated_data
        empresa = Empresa.objects.filter(pk=p["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        desde, hasta = reportes.validar_rango(p.get("desde"), p.get("hasta"))
        return empresa, desde, hasta


class DevolucionesVistaView(_BaseDevoluciones):
    """Resumen por proveedor y primeras filas de las devoluciones, para ver antes de descargar."""

    throttle_classes = [ApiAutenticadaThrottle]

    @extend_schema(tags=["compras"], parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta = self._resolver(request)
        respuesta = Response(
            reportes.vista_devoluciones(reportes.devoluciones_por_proveedor(empresa, desde, hasta))
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class DevolucionesExcelView(_BaseDevoluciones):
    """Descarga las devoluciones a proveedores en Excel (resumen y detalle). Queda en auditoría."""

    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @extend_schema(
        tags=["compras"],
        parameters=_PARAMETROS,
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request):
        empresa, desde, hasta = self._resolver(request)
        reporte = reportes.devoluciones_por_proveedor(empresa, desde, hasta)
        contenido = reportes.libro_devoluciones(empresa, reporte, desde, hasta)
        registrar(
            "compras.devoluciones_exportadas",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen="Devoluciones a proveedores exportadas",
            detalle={"desde": desde, "hasta": hasta, "filas": len(reporte.detalle)},
        )
        logger.info(
            "devoluciones_compras_exportadas",
            extra={"empresa_id": empresa.pk, "filas": len(reporte.detalle)},
        )
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = (
            f'attachment; filename="{reportes.nombre_archivo_devoluciones(empresa, desde, hasta)}"'
        )
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class OrdenesVistaView(_BaseDevoluciones):
    """Pendientes de recibir, cumplimiento por proveedor y diferencias de precio de las órdenes."""

    throttle_classes = [ApiAutenticadaThrottle]

    @extend_schema(tags=["compras"], parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta = self._resolver(request)
        respuesta = Response(
            reportes_ordenes.vista_ordenes(
                reportes_ordenes.reporte_de_ordenes(empresa, desde, hasta)
            )
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class OrdenesExcelView(_BaseDevoluciones):
    """Descarga los reportes de órdenes de compra en Excel (tres hojas). Queda en auditoría."""

    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @extend_schema(
        tags=["compras"],
        parameters=_PARAMETROS,
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request):
        empresa, desde, hasta = self._resolver(request)
        reporte = reportes_ordenes.reporte_de_ordenes(empresa, desde, hasta)
        contenido = reportes_ordenes.libro_ordenes(empresa, reporte, desde, hasta)
        registrar(
            "compras.ordenes_exportadas",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen="Reportes de órdenes de compra exportados",
            detalle={
                "desde": desde,
                "hasta": hasta,
                "pendientes": len(reporte.pendientes),
                "proveedores": len(reporte.cumplimiento),
                "diferencias": len(reporte.diferencias),
            },
        )
        logger.info(
            "ordenes_compra_exportadas",
            extra={"empresa_id": empresa.pk, "pendientes": len(reporte.pendientes)},
        )
        respuesta = HttpResponse(contenido, content_type=XLSX)
        nombre = reportes_ordenes.nombre_archivo_ordenes(empresa, desde, hasta)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta
