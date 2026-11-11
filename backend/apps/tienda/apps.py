from django.apps import AppConfig


class TiendaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tienda"
    label = "tienda"
    verbose_name = "Tienda virtual"

    def ready(self):
        from . import signals

        signals.conectar()
