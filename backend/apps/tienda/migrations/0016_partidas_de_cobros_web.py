"""Pasa a la libreta de «Liquidación entre empresas» las deudas por cobros web que ya existían.

Cada ``DeudaCobroTienda`` vigente (no eliminada ni revertida) que todavía no tenga su partida en
``ventas.DeudaInterna`` recibe una. Es seguro repetirla: no duplica nada.
"""

from django.db import migrations

LOCAL_WEB = "TIENDA_WEB"


def crear_partidas(apps, schema_editor):
    Deuda = apps.get_model("tienda", "DeudaCobroTienda")
    Partida = apps.get_model("ventas", "DeudaInterna")
    for deuda in Deuda.objects.filter(eliminado_en__isnull=True, revertida_en__isnull=True):
        ya = Partida.objects.filter(
            origen="COBRO_TIENDA", origen_id=deuda.pk, motivo="VENTA", eliminado_en__isnull=True
        ).exists()
        if ya:
            continue
        Partida.objects.create(
            empresa_id=deuda.deudora_id,
            acreedora_id=deuda.acreedora_id,
            origen="COBRO_TIENDA",
            origen_id=deuda.pk,
            referencia=f"Pedido {deuda.pedido.numero}"[:60],
            motivo="VENTA",
            fecha=deuda.creado_en.date(),
            monto=deuda.monto,
            local=LOCAL_WEB,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tienda", "0015_deuda_cobro_revertida"),
        ("ventas", "0020_deuda_interna_origen_tienda"),
    ]

    operations = [migrations.RunPython(crear_partidas, migrations.RunPython.noop)]
