from django.contrib import admin

from .models import ConfiguracionEmpresa, Empresa, Organizacion, Sucursal


class _SoloLecturaSinAmbito(admin.ModelAdmin):
    """Consulta del admin de plataforma, sin filtro de ámbito y de solo lectura.

    Las altas y cambios se hacen por servicios/API (Fase 4), que validan el
    ámbito; el admin de Django no conoce el contexto de tenant.
    """

    def get_queryset(self, request):
        gestor = self.model._default_manager
        qs = gestor.sin_ambito() if hasattr(gestor, "sin_ambito") else gestor.all()
        ordenamiento = self.get_ordering(request)
        return qs.order_by(*ordenamiento) if ordenamiento else qs

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organizacion)
class OrganizacionAdmin(_SoloLecturaSinAmbito):
    list_display = ("nombre", "estado", "creado_en")
    list_filter = ("estado",)
    search_fields = ("nombre",)


@admin.register(Empresa)
class EmpresaAdmin(_SoloLecturaSinAmbito):
    list_display = ("razon_social", "ruc", "organizacion", "estado")
    list_filter = ("estado",)
    search_fields = ("razon_social", "ruc")


@admin.register(Sucursal)
class SucursalAdmin(_SoloLecturaSinAmbito):
    list_display = ("nombre", "codigo", "empresa", "estado")
    list_filter = ("estado",)


@admin.register(ConfiguracionEmpresa)
class ConfiguracionEmpresaAdmin(_SoloLecturaSinAmbito):
    # Nunca se muestran las credenciales SUNAT, ni siquiera cifradas.
    exclude = ("sunat_usuario_sol", "sunat_clave_sol")
    list_display = ("empresa", "modo_sunat", "regimen_igv", "moneda")
