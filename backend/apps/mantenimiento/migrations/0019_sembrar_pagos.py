"""Carga los métodos de pago y periodicidades iniciales en las organizaciones que ya existen."""

from django.db import migrations

from apps.mantenimiento import pagos_datos


def sembrar(apps, schema_editor):
    Organizacion = apps.get_model("organizacion", "Organizacion")
    Medio = apps.get_model("mantenimiento", "MedioPago")
    Periodicidad = apps.get_model("mantenimiento", "Periodicidad")

    for org in Organizacion.objects.all():
        for nombre, tipo, referencia in pagos_datos.MEDIOS_DE_PAGO:
            if not Medio.objects.filter(organizacion_id=org.pk, nombre__iexact=nombre).exists():
                Medio.objects.create(
                    organizacion_id=org.pk,
                    nombre=nombre,
                    tipo=tipo,
                    requiere_referencia=referencia,
                )
        for nombre, unidad, cantidad in pagos_datos.PERIODICIDADES:
            if not Periodicidad.objects.filter(
                organizacion_id=org.pk, nombre__iexact=nombre
            ).exists():
                Periodicidad.objects.create(
                    organizacion_id=org.pk, nombre=nombre, unidad=unidad, cantidad=cantidad
                )


class Migration(migrations.Migration):
    dependencies = [
        ("mantenimiento", "0018_medios_pago_periodicidades"),
    ]

    operations = [
        # No se deshace: son datos de la organización y se pueden conservar.
        migrations.RunPython(sembrar, migrations.RunPython.noop),
    ]
