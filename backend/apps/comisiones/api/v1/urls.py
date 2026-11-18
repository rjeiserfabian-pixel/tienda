from django.urls import path

from . import escalas, liquidaciones, views

app_name = "comisiones"

urlpatterns = [
    path("escalas/", escalas.EscalasView.as_view(), name="escalas"),
    path("escalas/<int:pk>/", escalas.EscalaView.as_view(), name="escala"),
    path("metas/", escalas.MetasView.as_view(), name="metas"),
    path("metas/<int:pk>/", escalas.MetaView.as_view(), name="meta"),
    path("avance/", escalas.AvanceView.as_view(), name="avance"),
    path("liquidaciones/", liquidaciones.LiquidacionesView.as_view(), name="liquidaciones"),
    path("liquidaciones/<int:pk>/", liquidaciones.LiquidacionView.as_view(), name="liquidacion"),
    path(
        "liquidaciones/lineas/<int:pk>/planilla/",
        liquidaciones.LineaPlanillaView.as_view(),
        name="linea-planilla",
    ),
    path(
        "liquidaciones/lineas/<int:pk>/pagada/",
        liquidaciones.LineaPagadaView.as_view(),
        name="linea-pagada",
    ),
    path("mias/", liquidaciones.MisComisionesView.as_view(), name="mias"),
    path("reglas/", views.ReglasView.as_view(), name="reglas"),
    path("reglas/opciones/", views.OpcionesView.as_view(), name="opciones"),
    path("reglas/simular/", views.SimularView.as_view(), name="simular"),
    path("reglas/<int:pk>/", views.ReglaView.as_view(), name="regla"),
]
