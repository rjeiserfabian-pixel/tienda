import django.db.models.deletion
from django.db import migrations, models


def completar_pagos_de_compras(apps, schema_editor):
    """Los egresos que ya existían por pagos de compras toman el método con que se pagó."""
    Movimiento = apps.get_model("caja", "MovimientoCaja")
    Pago = apps.get_model("compras", "PagoCompra")
    metodos = dict(Pago.objects.values_list("pk", "medio_pago_id"))
    pendientes = Movimiento.objects.filter(origen_tipo="PAGO_COMPRA", medio_pago__isnull=True)
    for movimiento in pendientes.iterator():
        medio = metodos.get(movimiento.origen_id)
        if medio:
            Movimiento.objects.filter(pk=movimiento.pk).update(medio_pago_id=medio)


class Migration(migrations.Migration):
    dependencies = [
        ("caja", "0005_adjuntos_y_caja_chica"),
        ("compras", "0004_pago_en_otra_moneda"),
        ("mantenimiento", "0026_saldo_minimo_y_caja_chica"),
    ]

    operations = [
        migrations.AddField(
            model_name="movimientocaja",
            name="medio_pago",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="mantenimiento.mediopago",
            ),
        ),
        migrations.RunPython(completar_pagos_de_compras, migrations.RunPython.noop),
    ]
