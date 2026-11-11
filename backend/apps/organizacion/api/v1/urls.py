from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

app_name = "organizacion"

router = SimpleRouter()
router.register("empresas", views.EmpresaViewSet, basename="empresa")
router.register("sucursales", views.SucursalViewSet, basename="sucursal")

urlpatterns = [
    path("", views.OrganizacionView.as_view(), name="organizacion"),
    *router.urls,
]
