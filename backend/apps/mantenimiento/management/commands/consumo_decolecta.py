from django.core.management.base import BaseCommand

from apps.mantenimiento import cuota


class Command(BaseCommand):
    help = (
        "Muestra las consultas a Decolecta de este mes. Con --fijar N se calibra con la cifra "
        "oficial de https://decolecta.com/profile."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fijar", type=int, metavar="N", help="Consultas ya gastadas este mes."
        )

    def handle(self, *args, **opciones):
        if opciones["fijar"] is not None:
            cuota.fijar(opciones["fijar"])
        e = cuota.estado()
        self.stdout.write(
            f"{e['mes']}: {e['usadas']} de {e['limite']} consultas ({e['restantes']} restantes)."
        )
