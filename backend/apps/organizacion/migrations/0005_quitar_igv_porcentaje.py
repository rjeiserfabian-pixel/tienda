from django.db import migrations


class Migration(migrations.Migration):
    """El porcentaje del IGV pasa a las tasas de impuesto (con vigencia), que ya se cargaron."""

    dependencies = [
        ("organizacion", "0004_regimen_igv"),
        ("mantenimiento", "0015_sembrar_catalogos_fiscales"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="configuracionempresa",
            name="igv_porcentaje",
        ),
    ]
