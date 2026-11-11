import logging

from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle
from apps.inventario.reportes.generar import REPORTES, generar
from apps.inventario.reportes.vista import previsualizar
from apps.mantenimiento.models import Almacen, Producto
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

from .serializers import ParametrosReporte

logger = logging.getLogger(__name__)

EXPORTAR = "INVENTARIO.EXPORTAR"


class _BaseReporte(APIView):
    """Lo común de la descarga y la vista previa: permiso, empresa y lectura de parámetros."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = EXPORTAR
    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _resolver(request, tipo: str):
        """Valida el tipo y los parámetros; devuelve ``(p, empresa, almacen, producto)``."""
        if tipo not in REPORTES:
            raise Http404
        parametros = ParametrosReporte(data=request.query_params)
        parametros.is_valid(raise_exception=True)
        p = parametros.validated_data

        empresa = Empresa.objects.filter(pk=p["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        almacen = None
        if "almacen" in p:
            almacen = (
                Almacen.objects.select_related("sucursal")
                .filter(pk=p["almacen"], empresa=empresa)
                .first()
            )
            if almacen is None:
                raise ValidationError({"almacen": "Elija un almacén de la empresa."})
        producto = None
        if "producto" in p:
            producto = Producto.objects.select_related("unidad").filter(pk=p["producto"]).first()
            if producto is None:
                raise ValidationError({"producto": "No existe."})
        return p, empresa, almacen, producto


class VistaPreviaReporteView(_BaseReporte):
    """Los datos del reporte para verlos en pantalla antes de descargar (primeras 200 filas).

    Acepta los mismos parámetros que la descarga. No genera archivo ni deja auditoría de
    exportación: es una consulta.
    """

    throttle_classes = [ApiAutenticadaThrottle]

    @extend_schema(
        tags=["inventario"],
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("almacen", int),
            OpenApiParameter("producto", int),
            OpenApiParameter("desde", str, description="AAAA-MM-DD"),
            OpenApiParameter("hasta", str, description="AAAA-MM-DD"),
            OpenApiParameter("fecha", str, description="AAAA-MM-DD (solo para saldos)"),
            OpenApiParameter("categoria", int, description="Solo antigüedad"),
            OpenApiParameter("marca", int, description="Solo antigüedad"),
            OpenApiParameter("solo_antiguo", bool, description="Solo antigüedad"),
        ],
        responses={200: dict},
    )
    def get(self, request, tipo: str):
        p, empresa, almacen, producto = self._resolver(request, tipo)
        datos = previsualizar(
            tipo,
            empresa=empresa,
            almacen=almacen,
            producto=producto,
            desde=p.get("desde"),
            hasta=p.get("hasta"),
            fecha=p.get("fecha"),
            categoria=p.get("categoria"),
            marca=p.get("marca"),
            solo_antiguo=p.get("solo_antiguo", False),
        )
        respuesta = Response(datos)
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class ReporteView(_BaseReporte):
    """Descarga un libro o reporte de inventario de una empresa (``?empresa=ID`` obligatorio).

    ``tipo``: ``kardex-fisico`` (Formato 12.1), ``kardex-valorizado`` (13.1), ``saldos``,
    ``costo-venta``, ``movimientos`` (Excel con las hojas Dcab y Ddet) y ``antiguedad``
    (solo Excel; filtros ``categoria``, ``marca`` y ``solo_antiguo``). ``formato``: ``xlsx``
    (por defecto) o ``pdf``. El archivo se genera al momento y no se guarda en el servidor.
    """

    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    @extend_schema(
        tags=["inventario"],
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("formato", str, enum=["xlsx", "pdf"]),
            OpenApiParameter("almacen", int),
            OpenApiParameter("producto", int),
            OpenApiParameter("desde", str, description="AAAA-MM-DD"),
            OpenApiParameter("hasta", str, description="AAAA-MM-DD"),
            OpenApiParameter("fecha", str, description="AAAA-MM-DD (solo para saldos)"),
        ],
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request, tipo: str):
        p, empresa, almacen, producto = self._resolver(request, tipo)

        resultado = generar(
            tipo,
            p["formato"],
            empresa=empresa,
            almacen=almacen,
            producto=producto,
            desde=p.get("desde"),
            hasta=p.get("hasta"),
            fecha=p.get("fecha"),
            categoria=p.get("categoria"),
            marca=p.get("marca"),
            solo_antiguo=p.get("solo_antiguo", False),
        )
        registrar(
            "inventario.reporte_exportado",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"{resultado.titulo} exportado ({p['formato']})",
            detalle={
                "reporte": tipo,
                "formato": p["formato"],
                "almacen": almacen.pk if almacen else None,
                "producto": producto.pk if producto else None,
                "desde": p.get("desde"),
                "hasta": p.get("hasta"),
                "fecha": p.get("fecha"),
                "categoria": p.get("categoria"),
                "marca": p.get("marca"),
                "solo_antiguo": p.get("solo_antiguo", False),
                "filas": resultado.filas,
            },
        )
        logger.info(
            "reporte_inventario_exportado",
            extra={"empresa_id": empresa.pk, "reporte": tipo, "filas": resultado.filas},
        )
        respuesta = HttpResponse(resultado.contenido, content_type=resultado.mime)
        respuesta["Content-Disposition"] = f'attachment; filename="{resultado.nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta
