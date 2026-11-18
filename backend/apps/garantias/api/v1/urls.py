from django.urls import path

from . import avisos, reclamos, views

app_name = "garantias"

urlpatterns = [
    path("", views.GarantiaListView.as_view(), name="lista"),
    path("reclamos/", reclamos.ReclamoListaView.as_view(), name="reclamos"),
    path("reclamos/<int:pk>/", reclamos.ReclamoDetalleView.as_view(), name="reclamo"),
    path("reclamos/<int:pk>/servicio/", reclamos.VincularServicioView.as_view(), name="r-servicio"),
    path(
        "reclamos/<int:pk>/proveedor/", reclamos.EnviarProveedorView.as_view(), name="r-proveedor"
    ),
    path(
        "reclamos/<int:pk>/respuesta-proveedor/",
        reclamos.RespuestaProveedorView.as_view(),
        name="r-respuesta",
    ),
    path("reclamos/<int:pk>/resolver/", reclamos.ResolverView.as_view(), name="r-resolver"),
    path("configuracion/", avisos.ConfiguracionView.as_view(), name="configuracion"),
    path("reportes/", avisos.ReporteView.as_view(), name="reportes"),
    path("publico/buscar/", views.BuscarPublicaView.as_view(), name="publico-buscar"),
    path("publico/baja/", avisos.BajaPublicaView.as_view(), name="publico-baja"),
    path("publico/<str:token>/", views.EstadoPublicoView.as_view(), name="publico"),
    path("<int:pk>/certificado/", views.CertificadoView.as_view(), name="certificado"),
    path("<int:pk>/", views.GarantiaDetalleView.as_view(), name="detalle"),
]
