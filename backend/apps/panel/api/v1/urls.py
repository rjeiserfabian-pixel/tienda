from django.urls import path

from . import views

app_name = "panel"

urlpatterns = [
    path("inicio/", views.InicioView.as_view(), name="inicio"),
]
