from django.urls import path

from . import views

app_name = "facturacion"

urlpatterns = [
    path("configuracion/", views.ConfiguracionView.as_view(), name="configuracion"),
    path("configuracion/probar/", views.ProbarView.as_view(), name="probar"),
    path("documentos/", views.DocumentosView.as_view(), name="documentos"),
    path("vista-previa/", views.VistaPreviaView.as_view(), name="vista-previa"),
    path("enviar/", views.EnviarView.as_view(), name="enviar"),
]
