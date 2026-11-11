from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.organizacion.services.creacion import crear_organizacion_con_empresa


class Command(BaseCommand):
    help = "Crea una organización con su primera empresa, sucursal principal y configuración."

    def add_arguments(self, parser):
        parser.add_argument("--nombre", required=True, help="Nombre de la organización.")
        parser.add_argument("--razon-social", required=True)
        parser.add_argument("--ruc", required=True, help="RUC de 11 dígitos.")
        parser.add_argument("--nombre-comercial", default="")
        parser.add_argument("--codigo-sucursal", default="001")

    def handle(self, *args, **options):
        try:
            creada = crear_organizacion_con_empresa(
                nombre_organizacion=options["nombre"],
                razon_social=options["razon_social"],
                ruc=options["ruc"],
                nombre_comercial=options["nombre_comercial"],
                codigo_sucursal=options["codigo_sucursal"],
            )
        except ValidationError as exc:
            detalle = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
            raise CommandError(f"Datos inválidos: {detalle}") from exc
        except IntegrityError as exc:
            raise CommandError(
                "Ya existe una organización con ese nombre o una empresa con ese RUC."
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Organización '{creada.organizacion}' (id={creada.organizacion.pk}) creada con "
                f"la empresa {creada.empresa} y la sucursal {creada.sucursal}."
            )
        )
