from django.urls import path
from rest_framework.routers import SimpleRouter

from . import catalogos, ordenes, presupuesto, publico, reportes

app_name = "servicio_tecnico"

router = SimpleRouter()
router.register("tipos-equipo", catalogos.TipoEquipoViewSet, basename="tipo-equipo")
router.register("accesorios", catalogos.AccesorioEquipoViewSet, basename="accesorio-equipo")
router.register("revisiones", catalogos.ItemChecklistViewSet, basename="item-checklist")
router.register("tipos-servicio", catalogos.TipoServicioViewSet, basename="tipo-servicio")

router.register("equipos", ordenes.EquipoViewSet, basename="equipo")
router.register("ordenes", ordenes.OrdenServicioViewSet, basename="orden-servicio")

urlpatterns = [
    path("configuracion/", ordenes.ConfiguracionView.as_view(), name="configuracion"),
    path("catalogo/", presupuesto.CatalogoView.as_view(), name="catalogo-presupuesto"),
    path("publico/<str:token>/", publico.EstadoPublicoView.as_view(), name="estado-publico"),
    path(
        "avisos/configuracion/",
        publico.ConfiguracionAvisosView.as_view(),
        name="avisos-configuracion",
    ),
    path("tablero/", reportes.TableroView.as_view(), name="tablero"),
    path("reportes/resumen/", reportes.ResumenReporteView.as_view(), name="reporte-resumen"),
    path("reportes/utilidad/", reportes.UtilidadReporteView.as_view(), name="reporte-utilidad"),
    path("comisiones/", reportes.ComisionesView.as_view(), name="comisiones"),
    path(
        "comisiones/<int:personal_id>/",
        reportes.ComisionDetalleView.as_view(),
        name="comision-detalle",
    ),
    *router.urls,
]
