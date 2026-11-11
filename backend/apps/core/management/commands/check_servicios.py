from django.conf import settings
from django.core.cache import caches
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verifica la conexión a PostgreSQL, a la caché y (si está activo) a Redis."

    def handle(self, *args, **options):
        fallos = []

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0].split(",")[0]
            self.stdout.write(self.style.SUCCESS(f"PostgreSQL OK: {version}"))
        except Exception as exc:  # noqa: BLE001 - se reporta, no se oculta
            fallos.append("PostgreSQL")
            self.stderr.write(self.style.ERROR(f"PostgreSQL FALLÓ: {exc}"))

        for alias in ("default", "throttle"):
            try:
                caches[alias].set("check_servicios", "ok", 5)
                if caches[alias].get("check_servicios") != "ok":
                    raise RuntimeError("lectura distinta a la escritura")
                motor = "Redis" if settings.USAR_REDIS else "memoria local"
                self.stdout.write(self.style.SUCCESS(f"Caché '{alias}' OK ({motor})"))
            except Exception as exc:  # noqa: BLE001
                fallos.append(f"caché {alias}")
                self.stderr.write(self.style.ERROR(f"Caché '{alias}' FALLÓ: {exc}"))

        if not settings.USAR_REDIS:
            self.stdout.write(
                self.style.WARNING("USAR_REDIS=False: caché local y Celery en el mismo proceso.")
            )

        if fallos:
            raise CommandError("Servicios con fallas: " + ", ".join(fallos))
