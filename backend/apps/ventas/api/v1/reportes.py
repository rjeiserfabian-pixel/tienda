"""API de los reportes de ventas: se ven en pantalla y se descargan en Excel.

El costo y la utilidad solo salen para quien tiene VENTAS.VER_UTILIDAD en la empresa.
"""

import logging
from datetime import date

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.caja.api.v1.conciliacion import _textos  # noqa: I001
from apps.caja.reportes import nombre_archivo
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor
from apps.ventas import reportes, reportes_internas

from .views import TAG

logger = logging.getLogger(__name__)

VER = "VENTAS.VER"
EXPORTAR = "VENTAS.EXPORTAR"
UTILIDAD = "VENTAS.VER_UTILIDAD"
CONSOLIDADO = "REPORTES.CONSOLIDADO.VER"
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
    # Lo propio de cada reporte: el nombre en la ruta, la función y su Excel.
    nombre = ""
    calcular = None
    excel = None
    utilidad = True  # si el reporte admite costo y utilidad

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    def _parametros(self, request) -> tuple[Empresa, date | None, date | None, dict]:
        p = Parametros(data=request.query_params)
        p.is_valid(raise_exception=True)
        empresa = Empresa.objects.filter(
            pk=p.validated_data["empresa"], estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        extra = (
            {"con_utilidad": motor.tiene_permiso(request.user, UTILIDAD, empresa.pk)}
            if self.utilidad
            else {}
        )
        return empresa, p.validated_data.get("desde"), p.validated_data.get("hasta"), extra


class _Vista(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, desde, hasta, extra = self._parametros(request)
        respuesta = Response(_textos(type(self).calcular(empresa, desde, hasta, **extra)))
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class _Exportacion(_Base):
    permiso_requerido = EXPORTAR
    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, desde, hasta, extra = self._parametros(request)
        if self.nombre in ("registro", "ventas-internas"):
            extra["limite"] = None  # el Excel trae todo
        datos = type(self).calcular(empresa, desde, hasta, **extra)
        contenido = type(self).excel(empresa, datos)
        nombre = nombre_archivo(
            f"ventas-{self.nombre}", empresa, f"{datos['desde']:%Y%m%d}_{datos['hasta']:%Y%m%d}"
        )
        registrar(
            f"ventas.reporte_{self.nombre.replace('-', '_')}_exportado",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Reporte de ventas exportado: {nombre}",
            detalle={"desde": str(datos["desde"]), "hasta": str(datos["hasta"])},
        )
        logger.info(
            "reporte_ventas_exportado", extra={"empresa_id": empresa.pk, "reporte": self.nombre}
        )
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


def _par(nombre: str, calcular, excel, *, utilidad: bool = True):
    """Una vista de pantalla y una de Excel para un mismo reporte."""
    comunes = {
        "nombre": nombre,
        "calcular": staticmethod(calcular),
        "excel": staticmethod(excel),
        "utilidad": utilidad,
    }
    vista = type(f"Reporte_{nombre}", (_Vista,), comunes)
    descarga = type(f"ReporteExcel_{nombre}", (_Exportacion,), comunes)
    return vista, descarga


ResumenView, ResumenExcelView = _par("resumen", reportes.resumen, reportes.resumen_excel)
VendedoresView, VendedoresExcelView = _par(
    "vendedores", reportes.por_vendedor, reportes.vendedores_excel
)
ProductosView, ProductosExcelView = _par(
    "productos", reportes.por_producto, reportes.productos_excel
)
ClientesView, ClientesExcelView = _par("clientes", reportes.por_cliente, reportes.clientes_excel)
MetodosView, MetodosExcelView = _par(
    "metodos", reportes.por_metodo, reportes.metodos_excel, utilidad=False
)
RegistroView, RegistroExcelView = _par("registro", reportes.registro, reportes.registro_excel)
VentasInternasView, VentasInternasExcelView = _par(
    "ventas-internas", reportes_internas.ventas_internas, reportes_internas.ventas_internas_excel
)
_ConsolidadoVista, _ConsolidadoDescarga = _par(
    "consolidado", reportes_internas.consolidado, reportes_internas.consolidado_excel
)


class _TodasLasEmpresas:
    """El consolidado junta a TODAS las empresas: se exige el permiso en cada una de ellas."""

    def _ids(self, request) -> list[int]:
        declarada = empresa_declarada(request, self)
        organizacion = (
            Empresa.objects.filter(pk=declarada).values_list("organizacion_id", flat=True).first()
        )
        return list(
            Empresa.objects.filter(organizacion_id=organizacion, estado=Estado.ACTIVO).values_list(
                "pk", flat=True
            )
        )

    def empresas_de_la_operacion(self, request):
        return self._ids(request)

    def _parametros(self, request):
        empresa, desde, hasta, extra = super()._parametros(request)
        ids = self._ids(request)
        if not all(motor.tiene_permiso(request.user, CONSOLIDADO, e) for e in ids):
            raise PermissionDenied("No tiene permiso para ver el consolidado de las empresas.")
        extra["con_utilidad"] = all(motor.tiene_permiso(request.user, UTILIDAD, e) for e in ids)
        return empresa, desde, hasta, extra


class ConsolidadoView(_TodasLasEmpresas, _ConsolidadoVista):
    pass


class ConsolidadoExcelView(_TodasLasEmpresas, _ConsolidadoDescarga):
    pass
