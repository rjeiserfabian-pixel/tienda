from django.urls import path
from rest_framework.routers import SimpleRouter

from . import antiguedad, consulta_precios, importacion, reportes, tomas, views

app_name = "inventario"

router = SimpleRouter()
router.register("movimientos", views.MovimientoViewSet, basename="movimiento")
router.register("stock", views.StockViewSet, basename="stock")
router.register("kardex", views.KardexViewSet, basename="kardex")
router.register("series", views.SerieViewSet, basename="serie")
router.register("ubicaciones", views.UbicacionProductoViewSet, basename="ubicacion-producto")
router.register("periodos", views.PeriodoViewSet, basename="periodo")
router.register("tomas", tomas.TomaViewSet, basename="toma")

urlpatterns = [
    path(
        "saldo-inicial/importar/",
        importacion.SaldoInicialImportarView.as_view(),
        name="saldo-inicial-importar",
    ),
    path(
        "saldo-inicial/plantilla/",
        importacion.SaldoInicialPlantillaView.as_view(),
        name="saldo-inicial-plantilla",
    ),
    path(
        "antiguedad/configuracion/",
        antiguedad.ConfiguracionAntiguedadView.as_view(),
        name="antiguedad-configuracion",
    ),
    path("antiguedad/venta/", antiguedad.AvisoDeVentaView.as_view(), name="antiguedad-venta"),
    path(
        "consulta-precios/", consulta_precios.ConsultaPreciosView.as_view(), name="consulta-precios"
    ),
    path(
        "reportes/<str:tipo>/vista/",
        reportes.VistaPreviaReporteView.as_view(),
        name="reporte-vista",
    ),
    path("reportes/<str:tipo>/", reportes.ReporteView.as_view(), name="reporte"),
    path(
        "stock/disponibilidad/<int:producto_id>/",
        views.DisponibilidadView.as_view(),
        name="disponibilidad",
    ),
    *router.urls,
]
