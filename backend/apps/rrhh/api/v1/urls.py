from django.urls import path
from rest_framework.routers import SimpleRouter

from . import (
    adelantos,
    asistencia,
    autoservicio,
    cts,
    planilla,
    reportes,
    trabajadores,
    vacaciones,
    views,
)

app_name = "rrhh"

router = SimpleRouter()
router.register("trabajadores", trabajadores.TrabajadorViewSet, basename="trabajador")
router.register("adelantos", adelantos.AdelantoViewSet, basename="adelanto")
router.register("vacaciones", vacaciones.VacacionViewSet, basename="vacacion")
router.register("cts", cts.CtsViewSet, basename="cts")
router.register("planillas", planilla.PlanillaViewSet, basename="planilla")
router.register("contratos", trabajadores.ContratoViewSet, basename="contrato")
router.register("regimenes", views.RegimenViewSet, basename="regimen")
router.register("parametros", views.ParametroViewSet, basename="parametro")
router.register("tasas-afp", views.TasaAfpViewSet, basename="tasa-afp")
router.register("tramos-renta5", views.TramoRenta5ViewSet, basename="tramo-renta5")
router.register("tipos-asistencia", views.TipoAsistenciaViewSet, basename="tipo-asistencia")
router.register("feriados", views.FeriadoViewSet, basename="feriado")
router.register("conceptos", views.ConceptoViewSet, basename="concepto")

urlpatterns = [
    path("mi/resumen/", autoservicio.MiResumenView.as_view(), name="mi-resumen"),
    path("mi/boletas/<int:planilla_id>/", autoservicio.MiBoletaView.as_view(), name="mi-boleta"),
    path("reportes/<str:tipo>/excel/", reportes.ReporteExcelView.as_view(), name="reporte-excel"),
    path("reportes/<str:tipo>/", reportes.ReporteVistaView.as_view(), name="reporte-vista"),
    path("asistencia/", asistencia.GrillaView.as_view(), name="asistencia"),
    path("asistencia/dia/", asistencia.DiaView.as_view(), name="asistencia-dia"),
    path("asistencia/rango/", asistencia.RangoView.as_view(), name="asistencia-rango"),
    path("asistencia/completar/", asistencia.CompletarView.as_view(), name="asistencia-completar"),
    *router.urls,
]
