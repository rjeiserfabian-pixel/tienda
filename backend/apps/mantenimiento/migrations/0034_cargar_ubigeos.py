import csv
from pathlib import Path

from django.db import migrations

from apps.mantenimiento.ubigeos import texto_de_busqueda

ARCHIVO = Path(__file__).resolve().parent.parent / "datos" / "ubigeos_inei.csv"


def cargar(apps, schema_editor):
    """Carga la lista de ubigeos del INEI; lo que ya existe no se toca (se puede repetir)."""
    Ubigeo = apps.get_model("mantenimiento", "Ubigeo")
    existentes = set(Ubigeo.objects.values_list("codigo", flat=True))
    with ARCHIVO.open(encoding="utf-8", newline="") as f:
        nuevos = [
            Ubigeo(
                codigo=fila["codigo"],
                departamento=fila["departamento"],
                provincia=fila["provincia"],
                distrito=fila["distrito"],
                busqueda=texto_de_busqueda(
                    fila["codigo"], fila["departamento"], fila["provincia"], fila["distrito"]
                ),
            )
            for fila in csv.DictReader(f)
            if fila["codigo"] not in existentes
        ]
    Ubigeo.objects.bulk_create(nuevos, batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("mantenimiento", "0033_ubigeo_y_transporte"),
    ]

    operations = [
        migrations.RunPython(cargar, migrations.RunPython.noop),
    ]
