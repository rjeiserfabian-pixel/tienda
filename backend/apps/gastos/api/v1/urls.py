from django.urls import path
from rest_framework.routers import SimpleRouter

from . import recurrentes, reportes, views

app_name = "gastos"

router = SimpleRouter()
router.register("adjuntos", views.AdjuntoGastoViewSet, basename="adjunto-gasto")
router.register("recurrentes", recurrentes.RecurrenteViewSet, basename="gasto-recurrente")
router.register("", views.GastoViewSet, basename="gasto")

urlpatterns = [
    path("configuracion/", views.ConfiguracionView.as_view(), name="configuracion"),
    path("reportes/resumen/", reportes.ResumenView.as_view(), name="reporte-resumen"),
    path("reportes/resumen/excel/", reportes.ResumenExcelView.as_view()),
    path("reportes/proveedores/", reportes.ProveedoresView.as_view(), name="reporte-proveedores"),
    path("reportes/proveedores/excel/", reportes.ProveedoresExcelView.as_view()),
    path("reportes/sin-comprobante/", reportes.SinComprobanteView.as_view(), name="reporte-sin"),
    path("reportes/sin-comprobante/excel/", reportes.SinComprobanteExcelView.as_view()),
    *router.urls,
]
