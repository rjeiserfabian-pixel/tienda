from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.seguridad.services.usuarios import crear_admin_plataforma

from ._credenciales import leer_password


class Command(BaseCommand):
    help = "Crea un administrador de plataforma (sin organización). La contraseña se pide oculta."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        try:
            usuario = crear_admin_plataforma(
                username=options["username"],
                email=options["email"],
                password=leer_password(),
            )
        except ValidationError as exc:
            detalle = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
            raise CommandError(f"Datos inválidos: {detalle}") from exc
        except IntegrityError as exc:
            raise CommandError("Ya existe un usuario con ese nombre o correo.") from exc
        self.stdout.write(self.style.SUCCESS(f"Administrador de plataforma '{usuario}' creado."))
