from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ventas', '0010_proforma_forma_pago'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notacredito',
            name='motivo',
            field=models.CharField(choices=[('01', 'Anulación de la operación'), ('06', 'Devolución total'), ('07', 'Devolución por ítem')], max_length=2),
        ),
    ]
