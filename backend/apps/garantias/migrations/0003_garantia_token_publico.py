import secrets

from django.db import migrations, models

import apps.garantias.models


def dar_token(apps, schema_editor):
    """Cada garantía que ya existe recibe su propio código (un default fijo se repetiría)."""
    Garantia = apps.get_model("garantias", "Garantia")
    usados: set[str] = set()
    for garantia in Garantia.objects.filter(token_publico__isnull=True).iterator():
        token = secrets.token_urlsafe(12)
        while token in usados:
            token = secrets.token_urlsafe(12)
        usados.add(token)
        Garantia.objects.filter(pk=garantia.pk).update(token_publico=token)


class Migration(migrations.Migration):
    dependencies = [
        ("garantias", "0002_alter_garantia_estado_reclamogarantia"),
    ]

    operations = [
        migrations.AddField(
            model_name="garantia",
            name="token_publico",
            field=models.CharField(max_length=20, null=True),
        ),
        migrations.RunPython(dar_token, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="garantia",
            name="token_publico",
            field=models.CharField(
                default=apps.garantias.models.token_publico, max_length=20, unique=True
            ),
        ),
    ]
