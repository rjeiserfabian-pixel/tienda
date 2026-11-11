from django.urls import path

from . import views

app_name = "auditoria"

urlpatterns = [
    path("eventos/", views.EventoListView.as_view(), name="eventos"),
]
