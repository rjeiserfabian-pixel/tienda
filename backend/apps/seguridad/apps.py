from django.apps import AppConfig


class SeguridadConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.seguridad"
    label = "seguridad"
    verbose_name = "Seguridad"

    def ready(self):
        from . import signals  # noqa: F401  (registra los receptores)
