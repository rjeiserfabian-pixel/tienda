from django.db import migrations, models
from django.utils.text import slugify


def generar_direcciones(apps, schema_editor):
    """Da una dirección web a las familias, categorías y marcas que ya existen."""
    for nombre_modelo in ("Familia", "Categoria", "Marca"):
        modelo = apps.get_model("mantenimiento", nombre_modelo)
        usados: dict[int, set[str]] = {}
        # Incluye los eliminados lógicos: así ninguna dirección se repite jamás.
        for fila in modelo._base_manager.order_by("id").iterator():
            ocupados = usados.setdefault(fila.organizacion_id, set())
            base = (slugify(fila.nombre) or "sin-nombre")[:100].strip("-") or "sin-nombre"
            slug, n = base, 2
            while slug in ocupados:
                slug = f"{base}-{n}"
                n += 1
            ocupados.add(slug)
            modelo._base_manager.filter(pk=fila.pk).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [
        ("mantenimiento", "0036_tienda_especificaciones"),
        ("organizacion", "0010_ordenes_de_compra"),
    ]

    operations = [
        migrations.AddField(
            model_name="categoria",
            name="slug",
            field=models.SlugField(blank=True, editable=False, max_length=120),
        ),
        migrations.AddField(
            model_name="familia",
            name="slug",
            field=models.SlugField(blank=True, editable=False, max_length=120),
        ),
        migrations.AddField(
            model_name="marca",
            name="slug",
            field=models.SlugField(blank=True, editable=False, max_length=120),
        ),
        migrations.RunPython(generar_direcciones, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="categoria",
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(("slug", ""), _negated=True), ("eliminado_en__isnull", True)),
                fields=("organizacion", "slug"),
                name="uq_categoria_slug_vigente",
            ),
        ),
        migrations.AddConstraint(
            model_name="familia",
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(("slug", ""), _negated=True), ("eliminado_en__isnull", True)),
                fields=("organizacion", "slug"),
                name="uq_familia_slug_vigente",
            ),
        ),
        migrations.AddConstraint(
            model_name="marca",
            constraint=models.UniqueConstraint(
                condition=models.Q(models.Q(("slug", ""), _negated=True), ("eliminado_en__isnull", True)),
                fields=("organizacion", "slug"),
                name="uq_marca_slug_vigente",
            ),
        ),
    ]
