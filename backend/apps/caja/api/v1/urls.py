from django.urls import path
from rest_framework.routers import SimpleRouter

from . import cheques, conciliacion, extras, reportes, sesiones, views

app_name = "caja"

router = SimpleRouter()
router.register("movimientos", views.MovimientoCajaViewSet, basename="movimiento-caja")
router.register("transferencias", views.TransferenciaViewSet, basename="transferencia")
router.register("adjuntos", extras.AdjuntoViewSet, basename="adjunto-caja")
router.register("rendiciones", extras.RendicionViewSet, basename="rendicion-caja")
router.register("sesiones", sesiones.SesionCajaViewSet, basename="sesion-caja")
router.register("cheques", cheques.ChequeViewSet, basename="cheque")
router.register("extractos", conciliacion.EstadoCuentaViewSet, basename="extracto")
router.register("lineas-extracto", conciliacion.LineaEstadoCuentaViewSet, basename="linea-extracto")

urlpatterns = [
    path("saldos/", views.SaldosView.as_view(), name="saldos"),
    path("alertas/", extras.AlertasView.as_view(), name="alertas"),
    path("cheques/cuentas/", cheques.CuentasDeChequesView.as_view(), name="cheques-cuentas"),
    path("caja-chica/", extras.CajaChicaView.as_view(), name="caja-chica"),
    path("caja-chica/gastos/", extras.GastosPorRendirView.as_view(), name="caja-chica-gastos"),
    path(
        "reportes/bancarizacion/", extras.BancarizacionView.as_view(), name="reporte-bancarizacion"
    ),
    path("reportes/saldos/", reportes.SaldosFechaView.as_view(), name="reporte-saldos"),
    path("reportes/saldos/excel/", reportes.SaldosFechaExcelView.as_view()),
    path("reportes/libro/", reportes.LibroView.as_view(), name="reporte-libro"),
    path("reportes/libro/excel/", reportes.LibroExcelView.as_view()),
    path("reportes/libro/ple/", reportes.LibroPleView.as_view()),
    path("reportes/flujo/", reportes.FlujoView.as_view(), name="reporte-flujo"),
    path("reportes/flujo/excel/", reportes.FlujoExcelView.as_view()),
    path("reportes/proyeccion/", reportes.ProyeccionView.as_view(), name="reporte-proyeccion"),
    path("reportes/medios/", reportes.MediosView.as_view(), name="reporte-medios"),
    path("reportes/medios/excel/", reportes.MediosExcelView.as_view()),
    path("reportes/conceptos/", reportes.ConceptosView.as_view(), name="reporte-conceptos"),
    path("reportes/conceptos/excel/", reportes.ConceptosExcelView.as_view()),
    *router.urls,
]
