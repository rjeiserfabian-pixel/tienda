from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views, whatsapp

app_name = "organizacion"

router = SimpleRouter()
router.register("empresas", views.EmpresaViewSet, basename="empresa")
router.register("sucursales", views.SucursalViewSet, basename="sucursal")

urlpatterns = [
    path("", views.OrganizacionView.as_view(), name="organizacion"),
    path("whatsapp/", whatsapp.WhatsAppView.as_view(), name="whatsapp"),
    path("whatsapp/probar/", whatsapp.ProbarWhatsAppView.as_view(), name="whatsapp-probar"),
    *router.urls,
]
