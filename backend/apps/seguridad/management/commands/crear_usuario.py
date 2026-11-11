from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.core.exceptions import ErrorDominio
from apps.organizacion.models import Organizacion
from apps.seguridad.models import Rol
from apps.seguridad.services.roles import asignar_rol_de_sistema
from apps.seguridad.services.usuarios import crear_usuario

from ._credenciales import leer_password


class Command(BaseCommand):
    help = "Crea un usuario de una organización con acceso a empresas. Contraseña oculta."

    def add_arguments(self, parser):
        parser.add_argument("--organizacion-id", type=int, required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--nombres", default="")
        parser.add_argument("--apellidos", default="")
        parser.add_argument("--cargo", default="")
        parser.add_argument(
            "--empresa-id", type=int, action="append", default=[], help="Repetible."
        )
        parser.add_argument("--debe-cambiar-password", action="store_true")
        parser.add_argument(
            "--rol",
            action="append",
            default=[],
            help="Código de rol plantilla (repetible). Ej. ADMIN.",
        )

    def handle(self, *args, **options):
        organizacion = Organizacion.objects.filter(pk=options["organizacion_id"]).first()
        if organizacion is None:
            raise CommandError("La organización indicada no existe.")
        for codigo in options["rol"]:
            if (
                not Rol.objects.sin_ambito()
                .filter(organizacion=organizacion, codigo=codigo)
                .exists()
            ):
                raise CommandError(
                    f"El rol '{codigo}' no existe. ¿Ejecutó 'manage.py sync_permisos'?"
                )
        password = leer_password()
        try:
            with transaction.atomic():  # usuario y roles: todo o nada
                usuario = crear_usuario(
                    organizacion=organizacion,
                    username=options["username"],
                    email=options["email"],
                    password=password,
                    nombres=options["nombres"],
                    apellidos=options["apellidos"],
                    empresa_ids=options["empresa_id"],
                    cargo=options["cargo"],
                    debe_cambiar_password=options["debe_cambiar_password"],
                )
                for codigo in options["rol"]:
                    asignar_rol_de_sistema(usuario, codigo)
        except ValidationError as exc:
            detalle = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
            raise CommandError(f"Datos inválidos: {detalle}") from exc
        except ErrorDominio as exc:
            raise CommandError(exc.mensaje) from exc
        except IntegrityError as exc:
            raise CommandError("Ya existe un usuario con ese nombre o correo.") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Usuario '{usuario}' creado con {len(options['empresa_id'])} acceso(s) a empresa."
            )
        )
