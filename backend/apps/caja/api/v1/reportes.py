"""API de los reportes de caja y bancos: se ven en pantalla y se descargan en Excel o TXT."""

import logging

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.caja import ple, reportes
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

from .conciliacion import _textos
from .views import TAG

logger = logging.getLogger(__name__)

VER = "CAJA.REPORTES.VER"
EXPORTAR = "CAJA.REPORTES.EXPORTAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class Parametros(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField(required=False)
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)
    anio = serializers.IntegerField(required=False, min_value=2000, max_value=2100)
    mes = serializers.IntegerField(required=False, min_value=1, max_value=12)
    agrupar = serializers.ChoiceField(choices=["mes", "dia"], required=False, default="mes")
    meses = serializers.IntegerField(required=False, min_value=1, max_value=12, default=3)
    formato = serializers.ChoiceField(choices=["1.1", "1.2"], required=False)


_PARAMETROS = [OpenApiParameter("empresa", int, required=True)]


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @staticmethod
    def _parametros(request):
        p = Parametros(data=request.query_params)
        p.is_valid(raise_exception=True)
        empresa = Empresa.objects.filter(
            pk=p.validated_data["empresa"], estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return empresa, p.validated_data

    @staticmethod
    def _vista(datos) -> Response:
        respuesta = Response(_textos(datos))
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    @staticmethod
    def _archivo(
        contenido, nombre: str, tipo: str, *, accion: str, empresa, detalle
    ) -> HttpResponse:
        registrar(
            f"caja.{accion}",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Reporte de caja exportado: {nombre}",
            detalle=detalle,
        )
        logger.info("reporte_caja_exportado", extra={"empresa_id": empresa.pk, "reporte": accion})
        respuesta = HttpResponse(contenido, content_type=tipo)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class _Exportacion(_Base):
    permiso_requerido = EXPORTAR
    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]


def _fecha_o_hoy(p) -> object:
    return p.get("fecha") or timezone.localdate()


def _periodo(p) -> tuple[int, int]:
    hoy = timezone.localdate()
    return p.get("anio") or hoy.year, p.get("mes") or hoy.month


# -- saldos a una fecha ---------------------------------------------------------
class SaldosFechaView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, p = self._parametros(request)
        return self._vista(reportes.saldos_a_fecha(empresa, _fecha_o_hoy(p)))


class SaldosFechaExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, p = self._parametros(request)
        fecha = _fecha_o_hoy(p)
        contenido = reportes.saldos_excel(empresa, reportes.saldos_a_fecha(empresa, fecha))
        nombre = reportes.nombre_archivo("saldos-caja", empresa, f"{fecha:%Y%m%d}")
        return self._archivo(
            contenido,
            nombre,
            XLSX,
            accion="saldos_exportados",
            empresa=empresa,
            detalle={"fecha": fecha},
        )


# -- libro caja y bancos --------------------------------------------------------
class LibroView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, p = self._parametros(request)
        anio, mes = _periodo(p)
        return self._vista(reportes.libro(empresa, anio, mes))


class LibroExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, p = self._parametros(request)
        anio, mes = _periodo(p)
        datos = reportes.libro(empresa, anio, mes)
        nombre = reportes.nombre_archivo("libro-caja-bancos", empresa, f"{anio}{mes:02d}")
        return self._archivo(
            reportes.libro_excel(empresa, datos), nombre, XLSX,
            accion="libro_exportado", empresa=empresa, detalle={"anio": anio, "mes": mes},
        )  # fmt: skip


class LibroPleView(_Exportacion):
    """Borrador del archivo TXT del PLE (formato 1.1 o 1.2). Debe validarlo el contador."""

    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={(200, "text/plain"): bytes})
    def get(self, request):
        empresa, p = self._parametros(request)
        if not p.get("formato"):
            raise ValidationError({"formato": "Elija el formato 1.1 (efectivo) o 1.2 (bancos)."})
        anio, mes = _periodo(p)
        archivo = ple.generar(empresa, reportes.libro(empresa, anio, mes), p["formato"])
        respuesta = self._archivo(
            archivo["contenido"].encode("utf-8"), archivo["nombre"], "text/plain; charset=utf-8",
            accion="libro_ple_exportado", empresa=empresa,
            detalle={
                "anio": anio,
                "mes": mes,
                "formato": p["formato"],
                "lineas": archivo["lineas"],
            },
        )  # fmt: skip
        if archivo["avisos"]:
            respuesta["X-Avisos"] = (
                " | ".join(archivo["avisos"]).encode("ascii", "ignore").decode()[:500]
            )
        return respuesta


# -- flujo de caja --------------------------------------------------------------
class FlujoView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, p = self._parametros(request)
        return self._vista(
            reportes.flujo_real(empresa, p.get("desde"), p.get("hasta"), p["agrupar"])
        )


class FlujoExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, p = self._parametros(request)
        datos = reportes.flujo_real(empresa, p.get("desde"), p.get("hasta"), p["agrupar"])
        nombre = reportes.nombre_archivo(
            "flujo-caja", empresa, f"{datos['desde']:%Y%m%d}_{datos['hasta']:%Y%m%d}"
        )
        return self._archivo(
            reportes.flujo_excel(empresa, datos), nombre, XLSX,
            accion="flujo_exportado", empresa=empresa,
            detalle={"desde": datos["desde"], "hasta": datos["hasta"]},
        )  # fmt: skip


class ProyeccionView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, p = self._parametros(request)
        return self._vista(reportes.flujo_proyectado(empresa, timezone.localdate(), p["meses"]))


# -- por método de pago ---------------------------------------------------------
class MediosView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, p = self._parametros(request)
        return self._vista(reportes.por_medio(empresa, p.get("desde"), p.get("hasta")))


class MediosExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, p = self._parametros(request)
        datos = reportes.por_medio(empresa, p.get("desde"), p.get("hasta"))
        nombre = reportes.nombre_archivo(
            "caja-por-metodo", empresa, f"{datos['desde']:%Y%m%d}_{datos['hasta']:%Y%m%d}"
        )
        return self._archivo(
            reportes.medios_excel(empresa, datos),
            nombre,
            XLSX,
            accion="medios_exportados",
            empresa=empresa,
            detalle={"desde": datos["desde"], "hasta": datos["hasta"]},
        )


# -- por concepto ---------------------------------------------------------------
class ConceptosView(_Base):
    @extend_schema(tags=TAG, parameters=_PARAMETROS, responses={200: dict})
    def get(self, request):
        empresa, p = self._parametros(request)
        return self._vista(reportes.por_concepto(empresa, p.get("desde"), p.get("hasta")))


class ConceptosExcelView(_Exportacion):
    @extend_schema(
        tags=TAG, parameters=_PARAMETROS, responses={(200, "application/octet-stream"): bytes}
    )
    def get(self, request):
        empresa, p = self._parametros(request)
        datos = reportes.por_concepto(empresa, p.get("desde"), p.get("hasta"))
        nombre = reportes.nombre_archivo(
            "caja-por-concepto", empresa, f"{datos['desde']:%Y%m%d}_{datos['hasta']:%Y%m%d}"
        )
        return self._archivo(
            reportes.conceptos_excel(empresa, datos), nombre, XLSX,
            accion="conceptos_exportados", empresa=empresa,
            detalle={"desde": datos["desde"], "hasta": datos["hasta"]},
        )  # fmt: skip
