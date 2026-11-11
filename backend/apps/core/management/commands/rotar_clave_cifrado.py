from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.crypto import CampoCifrado, version_actual


class Command(BaseCommand):
    help = (
        "Re-cifra todos los campos CampoCifrado con la clave actual "
        "(CIFRADO_CLAVE_ACTUAL). Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument("--lote", type=int, default=500, help="Filas por transacción.")
        parser.add_argument("--simular", action="store_true", help="Solo cuenta, no escribe.")

    def handle(self, *args, **options):
        lote, simular = options["lote"], options["simular"]
        total = 0
        for modelo in apps.get_models():
            campos = [f.name for f in modelo._meta.concrete_fields if isinstance(f, CampoCifrado)]
            if not campos:
                continue
            # _base_manager: sin filtros de ámbito ni de borrado lógico.
            cantidad = self._rotar(modelo, campos, lote, simular)
            total += cantidad
            self.stdout.write(f"{modelo._meta.label}: {cantidad} fila(s)")
        accion = "A re-cifrar" if simular else "Re-cifradas"
        self.stdout.write(
            self.style.SUCCESS(
                f"{accion}: {total} fila(s) con la clave versión {version_actual()}."
            )
        )

    @staticmethod
    def _rotar(modelo, campos, lote, simular) -> int:
        pks = list(modelo._base_manager.order_by("pk").values_list("pk", flat=True))
        if simular:
            return len(pks)
        for inicio in range(0, len(pks), lote):
            with transaction.atomic():
                for obj in modelo._base_manager.select_for_update().filter(
                    pk__in=pks[inicio : inicio + lote]
                ):
                    # Los valores ya vienen descifrados; update() los cifra con la clave actual.
                    modelo._base_manager.filter(pk=obj.pk).update(
                        **{campo: getattr(obj, campo) for campo in campos}
                    )
        return len(pks)
