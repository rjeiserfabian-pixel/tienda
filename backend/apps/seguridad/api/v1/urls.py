from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views, views_gestion

app_name = "seguridad"

router = SimpleRouter()
router.register("usuarios", views_gestion.UsuarioViewSet, basename="usuario")
router.register("roles", views_gestion.RolViewSet, basename="rol")

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="refresh"),
    path("auth/mfa/verificar/", views.MfaVerificarLoginView.as_view(), name="mfa-verificar"),
    path("auth/recuperar/", views.RecuperarSolicitudView.as_view(), name="recuperar"),
    path(
        "auth/recuperar/confirmar/",
        views.RecuperarConfirmarView.as_view(),
        name="recuperar-confirmar",
    ),
    path("mfa/", views.MfaEstadoView.as_view(), name="mfa-estado"),
    path("mfa/configurar/", views.MfaConfigurarView.as_view(), name="mfa-configurar"),
    path("mfa/confirmar/", views.MfaConfirmarView.as_view(), name="mfa-confirmar"),
    path("mfa/desactivar/", views.MfaDesactivarView.as_view(), name="mfa-desactivar"),
    path("mfa/codigos-recuperacion/", views.MfaCodigosView.as_view(), name="mfa-codigos"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/logout-global/", views.LogoutGlobalView.as_view(), name="logout-global"),
    path("auth/cambiar-password/", views.CambiarPasswordView.as_view(), name="cambiar-password"),
    path("me/", views.MiPerfilView.as_view(), name="me"),
    path("permisos/catalogo/", views.CatalogoPermisosView.as_view(), name="permisos-catalogo"),
    path("permisos/mios/", views.MisPermisosView.as_view(), name="permisos-mios"),
    path("menu/", views.MenuView.as_view(), name="menu"),
    path("sesiones/", views.SesionListView.as_view(), name="sesiones"),
    path(
        "sesiones/otras/", views.SesionesOtrasRevocarView.as_view(), name="sesiones-otras-revocar"
    ),
    path("sesiones/<uuid:sesion_id>/", views.SesionRevocarView.as_view(), name="sesion-revocar"),
    *router.urls,
]
