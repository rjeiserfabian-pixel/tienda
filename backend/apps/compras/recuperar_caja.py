"""Pone en el libro de caja y bancos los pagos de compras hechos antes de que existiera el libro.

Es idempotente: un pago que ya tiene su movimiento no se vuelve a registrar. Se ejecuta con
``sync_permisos`` (y se puede repetir sin riesgo). Las compras y pagos anulados no generan nada.
"""

import logging

from apps.caja import servicios as caja
from apps.caja.models import MovimientoCaja, Origen
from apps.core.tenant import contexto_tenant
from apps.organizacion.models import Empresa

from .models import Compra, PagoCompra

logger = logging.getLogger(__name__)


def crear_movimientos_de_pagos(organizacion_id: int) -> int:
    """Crea el egreso de cada pago vigente que aún no lo tiene. Devuelve cuántos creó."""
    empresas = list(Empresa.objects.sin_ambito().filter(organizacion_id=organizacion_id))
    creados = 0
    with contexto_tenant(organizacion_id, [e.pk for e in empresas]):
        pagos = (
            PagoCompra.objects.sin_ambito()
            .filter(
                empresa__organizacion_id=organizacion_id,
                anulado=False,
                compra__estado=Compra.Estado.EMITIDO,
            )
            .select_related("empresa", "cuenta", "compra", "compra__proveedor")
            .order_by("id")
        )
        hechos = set(
            MovimientoCaja.objects.sin_ambito()
            .filter(empresa__organizacion_id=organizacion_id, origen_tipo=Origen.PAGO_COMPRA)
            .values_list("origen_id", flat=True)
        )
        for pago in pagos:
            if pago.pk in hechos:
                continue
            compra = pago.compra
            etiqueta = "Flete de la" if pago.tipo == PagoCompra.Tipo.FLETE else "Pago de la"
            caja.registrar_pago_de_compra(
                empresa=pago.empresa,
                cuenta=pago.cuenta,
                monto=pago.monto_en_cuenta,
                fecha=pago.fecha,
                referencia=pago.referencia,
                glosa=(
                    f"{etiqueta} compra N° {compra.numero:06d} · {compra.comprobante} "
                    f"· {compra.proveedor.nombre}"
                ),
                pago_id=pago.pk,
                medio_pago=pago.medio_pago,
            )
            creados += 1
    if creados:
        logger.info("movimientos_de_pagos_recuperados", extra={"organizacion_id": organizacion_id})
    return creados
