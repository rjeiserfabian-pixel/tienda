"""Rutas raíz: solo incluye los urls de cada app (prefijo /api/v1/)."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.throttles import ApiPublicaThrottle

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/seguridad/", include("apps.seguridad.api.v1.urls")),
    path("api/v1/organizacion/", include("apps.organizacion.api.v1.urls")),
    path("api/v1/auditoria/", include("apps.auditoria.api.v1.urls")),
    path("api/v1/mantenimiento/", include("apps.mantenimiento.api.v1.urls")),
    path("api/v1/inventario/", include("apps.inventario.api.v1.urls")),
    path("api/v1/compras/", include("apps.compras.api.v1.urls")),
    path("api/v1/caja/", include("apps.caja.api.v1.urls")),
    path("api/v1/gastos/", include("apps.gastos.api.v1.urls")),
    path("api/v1/ventas/", include("apps.ventas.api.v1.urls")),
    path("api/v1/servicio-tecnico/", include("apps.servicio_tecnico.api.v1.urls")),
    path("api/v1/facturacion/", include("apps.facturacion.api.v1.urls")),
    path("api/v1/rrhh/", include("apps.rrhh.api.v1.urls")),
    path("api/v1/panel/", include("apps.panel.api.v1.urls")),
    path("api/v1/tienda/", include("apps.tienda.api.v1.urls")),
]

if settings.DOCS_API_HABILITADA:
    urlpatterns += [
        path(
            "api/v1/schema/",
            SpectacularAPIView.as_view(
                authentication_classes=[],
                permission_classes=[],
                throttle_classes=[ApiPublicaThrottle],
            ),
            name="schema",
        ),
        path(
            "api/v1/docs/",
            SpectacularSwaggerView.as_view(
                url_name="schema", authentication_classes=[], permission_classes=[]
            ),
            name="docs",
        ),
    ]
