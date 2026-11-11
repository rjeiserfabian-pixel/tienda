from django.urls import path

from .views import SaludView

app_name = "core"

urlpatterns = [
    path("salud/", SaludView.as_view(), name="salud"),
]
