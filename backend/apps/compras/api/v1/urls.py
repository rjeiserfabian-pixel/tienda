from django.urls import path
from rest_framework.routers import SimpleRouter

from . import anticipos, cotizaciones, devoluciones, ordenes, reportes, views, xml

app_name = "compras"

router = SimpleRouter()
router.register("ordenes", ordenes.OrdenCompraViewSet, basename="orden")
router.register("cotizaciones", cotizaciones.SolicitudCotizacionViewSet, basename="cotizacion")
router.register("devoluciones", devoluciones.DevolucionCompraViewSet, basename="devolucion")
router.register("anticipos", anticipos.AnticipoViewSet, basename="anticipo")
router.register("creditos", devoluciones.CreditoProveedorViewSet, basename="credito")
router.register("", views.CompraViewSet, basename="compra")

urlpatterns = [
    path(
        "reportes/registro-compras/vista/",
        reportes.RegistroComprasVistaView.as_view(),
        name="registro-compras-vista",
    ),
    path(
        "reportes/registro-compras/",
        reportes.RegistroComprasExcelView.as_view(),
        name="registro-compras",
    ),
    path(
        "reportes/devoluciones/vista/",
        reportes.DevolucionesVistaView.as_view(),
        name="devoluciones-reporte-vista",
    ),
    path(
        "reportes/devoluciones/",
        reportes.DevolucionesExcelView.as_view(),
        name="devoluciones-reporte",
    ),
    path(
        "reportes/ordenes/vista/",
        reportes.OrdenesVistaView.as_view(),
        name="ordenes-reporte-vista",
    ),
    path("reportes/ordenes/", reportes.OrdenesExcelView.as_view(), name="ordenes-reporte"),
    path("xml/leer/", xml.LeerXmlView.as_view(), name="xml-leer"),
    *router.urls,
]
