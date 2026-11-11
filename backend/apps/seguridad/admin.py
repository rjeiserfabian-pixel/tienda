from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Sesion, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "email", "organizacion", "is_active", "es_admin_plataforma")
    list_filter = ("is_active", "es_admin_plataforma")
    fieldsets = (
        *UserAdmin.fieldsets,
        ("Sistema", {"fields": ("organizacion", "es_admin_plataforma", "debe_cambiar_password")}),
    )


@admin.register(Sesion)
class SesionAdmin(admin.ModelAdmin):
    """Solo consulta: las sesiones se crean y revocan por la API."""

    list_display = ("usuario", "plataforma", "ip", "ultimo_uso", "revocada", "motivo_revocacion")
    list_filter = ("plataforma", "revocada")
    exclude = ("jti_actual", "jti_anterior", "push_token")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
