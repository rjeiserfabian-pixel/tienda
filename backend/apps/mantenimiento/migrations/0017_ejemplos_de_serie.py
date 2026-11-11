"""Completa el ejemplo de serie de los tipos de comprobante que ya existían."""

from django.db import migrations

from apps.mantenimiento import fiscal_datos


def completar(apps, schema_editor):
    Tipo = apps.get_model("mantenimiento", "TipoComprobante")
    for codigo, ejemplo in fiscal_datos.EJEMPLOS_SERIE.items():
        # Solo donde está vacío: lo que el administrador ya escribió no se pisa.
        Tipo.objects.filter(codigo=codigo, ejemplo_serie="").update(ejemplo_serie=ejemplo)


class Migration(migrations.Migration):
    dependencies = [
        ("mantenimiento", "0016_series_comprobante"),
    ]

    operations = [
        migrations.RunPython(completar, migrations.RunPython.noop),
    ]
