"""Carga los catálogos fiscales de SUNAT en las organizaciones que ya existen.

También conserva el porcentaje de IGV que tenía la configuración de cada empresa: pasa a ser la
tasa de la organización (antes de que ``igv_porcentaje`` se elimine de la configuración).
"""

from datetime import date
from decimal import Decimal

from django.db import migrations

from apps.mantenimiento import fiscal_datos


def sembrar(apps, schema_editor):
    Organizacion = apps.get_model("organizacion", "Organizacion")
    Configuracion = apps.get_model("organizacion", "ConfiguracionEmpresa")
    Tipo = apps.get_model("mantenimiento", "TipoComprobante")
    Afectacion = apps.get_model("mantenimiento", "AfectacionIGV")
    Tasa = apps.get_model("mantenimiento", "TasaImpuesto")

    for org in Organizacion.objects.all():
        for (
            codigo,
            nombre,
            abrev,
            electronico,
            compras,
            ventas,
            igv,
            serie,
        ) in fiscal_datos.TIPOS_COMPROBANTE:
            Tipo.objects.get_or_create(
                organizacion_id=org.pk,
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "abreviatura": abrev,
                    "es_electronico": electronico,
                    "aplica_compras": compras,
                    "aplica_ventas": ventas,
                    "lleva_igv": igv,
                    "patron_serie": serie,
                },
            )
        for (
            codigo,
            nombre,
            grupo,
            impuesto,
            gratuita,
            compras,
            ventas,
        ) in fiscal_datos.AFECTACIONES_IGV:
            Afectacion.objects.get_or_create(
                organizacion_id=org.pk,
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "grupo": grupo,
                    "impuesto": impuesto,
                    "gratuita": gratuita,
                    "aplica_compras": compras,
                    "aplica_ventas": ventas,
                },
            )
        # La tasa vigente hasta hoy: la que ya usaban las empresas de la organización.
        previa = (
            Configuracion.objects.filter(empresa__organizacion_id=org.pk)
            .values_list("igv_porcentaje", flat=True)
            .first()
        )
        Tasa.objects.get_or_create(
            organizacion_id=org.pk,
            impuesto="IGV",
            vigente_desde=date(2011, 3, 1),
            defaults={"porcentaje": previa if previa is not None else Decimal("18.00")},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("mantenimiento", "0014_fiscal"),
    ]

    operations = [
        # No se deshace: los catálogos son datos de la organización y se pueden conservar.
        migrations.RunPython(sembrar, migrations.RunPython.noop),
    ]
