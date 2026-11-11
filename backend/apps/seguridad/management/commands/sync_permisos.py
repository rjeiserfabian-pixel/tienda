from django.core.management.base import BaseCommand

from apps.compras.recuperar_caja import crear_movimientos_de_pagos
from apps.mantenimiento.categorias_gasto import sembrar_categorias_gasto
from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja
from apps.mantenimiento.fiscal import sembrar_catalogos_fiscales
from apps.mantenimiento.pagos import sembrar_catalogos_pago
from apps.organizacion.models import Organizacion
from apps.rrhh.catalogos import sembrar_catalogos_rrhh
from apps.seguridad.services.catalogo import sembrar_roles_plantilla, sincronizar_catalogo
from apps.servicio_tecnico.catalogos import sembrar_catalogos_servicio


class Command(BaseCommand):
    help = (
        "Sincroniza el catálogo de permisos y el menú con la base (idempotente) y siembra los "
        "roles plantilla que falten en cada organización. Ejecutar en cada despliegue."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--solo-catalogo", action="store_true", help="No toca los roles de las organizaciones."
        )

    def handle(self, *args, **options):
        r = sincronizar_catalogo()
        self.stdout.write(
            f"Permisos: {r.permisos_creados} creados, {r.permisos_actualizados} actualizados, "
            f"{r.permisos_desactivados} desactivados. Módulos de menú: {r.modulos}."
        )
        if options["solo_catalogo"]:
            return
        for organizacion in Organizacion.objects.all():
            estado = sembrar_roles_plantilla(organizacion)
            resumen = ", ".join(f"{c}={e}" for c, e in estado.items())
            self.stdout.write(f"Organización '{organizacion}': {resumen}")
            nuevos = sembrar_catalogos_fiscales(organizacion.pk)
            self.stdout.write(f"  Catálogos fiscales nuevos: {nuevos}")
            pagos = sembrar_catalogos_pago(organizacion.pk)
            self.stdout.write(f"  Métodos de pago y periodicidades nuevos: {pagos}")
            conceptos = sembrar_conceptos_caja(organizacion.pk)
            self.stdout.write(f"  Conceptos de caja nuevos: {conceptos}")
            categorias = sembrar_categorias_gasto(organizacion.pk)
            self.stdout.write(f"  Categorías de gasto nuevas: {categorias}")
            servicio = sembrar_catalogos_servicio(organizacion.pk)
            self.stdout.write(f"  Catálogos de servicio técnico nuevos: {servicio}")
            rrhh = sembrar_catalogos_rrhh(organizacion.pk)
            self.stdout.write(f"  Catálogos de recursos humanos nuevos: {rrhh}")
            recuperados = crear_movimientos_de_pagos(organizacion.pk)
            self.stdout.write(f"  Pagos de compras pasados al libro de caja: {recuperados}")
        self.stdout.write(self.style.SUCCESS("Catálogo sincronizado."))
