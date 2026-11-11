"""Usar el saldo a favor de un proveedor para pagar compras a crédito.

El saldo nace de una devolución ya pagada (ver ``devoluciones.py``). Se aplica a las cuotas de una
compra a crédito del MISMO proveedor, de la MISMA empresa y en la MISMA moneda, de la cuota más
antigua a la más nueva (o solo a las elegidas), igual que un pago. No mueve dinero en las cajas:
la cuota queda pagada con el crédito. Se puede deshacer; el saldo vuelve a estar disponible.

Orden de bloqueos, siempre el mismo: compra, crédito, cuotas.
"""

import logging
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.inventario import periodos

from .cuentas_por_pagar import _cuotas_bloqueadas, repartir
from .exceptions import CreditoInvalido
from .models import (
    AplicacionCredito,
    Compra,
    CreditoProveedor,
    DetalleAplicacionCredito,
    FormaPago,
)

logger = logging.getLogger(__name__)

CERO = Decimal("0")
CENTIMO = Decimal("0.01")
MAX_MONTO = Decimal("9999999999999.99")


def creditos_disponibles(proveedor_id: int, moneda: str) -> list[CreditoProveedor]:
    """Los saldos a favor vigentes de un proveedor en una moneda, los más antiguos primero."""
    creditos = CreditoProveedor.objects.filter(
        proveedor_id=proveedor_id, moneda=moneda, anulado=False
    ).order_by("id")
    return [c for c in creditos if c.disponible > 0]


def saldo_a_favor_total(proveedor_id: int, moneda: str) -> Decimal:
    return sum((c.disponible for c in creditos_disponibles(proveedor_id, moneda)), CERO)


@transaction.atomic
def aplicar_credito(
    credito: CreditoProveedor,
    compra: Compra,
    *,
    monto: Decimal,
    cuota_ids: Sequence[int] | None = None,
    fecha: date | None = None,
) -> AplicacionCredito:
    """Paga cuotas de ``compra`` con el saldo a favor ``credito``. Todo o nada."""
    periodos.exigir_empresa(compra.empresa)
    # Siempre en este orden: compra, crédito, cuotas.
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    credito = CreditoProveedor.objects.select_for_update().get(pk=credito.pk)
    if credito.empresa_id != compra.empresa_id:
        raise CreditoInvalido("El saldo a favor es de otra empresa.")
    if credito.anulado:
        raise CreditoInvalido("Este saldo a favor está anulado.")
    if credito.proveedor_id != compra.proveedor_id:
        raise CreditoInvalido("El saldo a favor es de otro proveedor.")
    if credito.moneda != compra.moneda:
        raise CreditoInvalido("El saldo a favor y la compra están en monedas distintas.")
    if compra.estado != Compra.Estado.EMITIDO:
        raise CreditoInvalido("La compra está anulada: no se puede pagar.")
    if compra.forma_pago != FormaPago.CREDITO:
        raise CreditoInvalido("La compra fue al contado: ya está pagada.")
    if (
        not isinstance(monto, Decimal)
        or not monto.is_finite()
        or monto != monto.quantize(CENTIMO)
        or monto > MAX_MONTO
    ):
        raise CreditoInvalido("El monto admite hasta 2 decimales.")
    if monto <= 0:
        raise CreditoInvalido("El monto debe ser mayor que cero.")
    if monto > credito.disponible:
        raise CreditoInvalido(f"El saldo a favor solo tiene disponible {credito.disponible}.")
    hoy = timezone.localdate()
    fecha = fecha or hoy
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise CreditoInvalido("La fecha no es válida.")
    if fecha > hoy:
        raise CreditoInvalido("La fecha no puede ser futura.")
    if fecha < compra.fecha_emision:
        raise CreditoInvalido("La fecha no puede ser anterior a la emisión de la compra.")
    if fecha < credito.fecha_origen:
        raise CreditoInvalido("La fecha no puede ser anterior al documento que originó el saldo.")

    cuotas = _cuotas_bloqueadas(compra)
    pendiente = sum((c.monto - c.pagado for c in cuotas), CERO)
    if pendiente <= 0:
        raise CreditoInvalido("La compra ya está pagada por completo.")
    if monto > pendiente:
        raise CreditoInvalido(f"El monto pasa de lo que se debe ({pendiente}).")
    reparto = repartir(cuotas, monto, list(cuota_ids) if cuota_ids else None)

    aplicacion = AplicacionCredito.objects.create(
        empresa=compra.empresa, credito=credito, compra=compra, fecha=fecha, monto=monto
    )
    for cuota, parte in reparto:
        cuota.pagado += parte
        cuota.save(update_fields=["pagado"])
    DetalleAplicacionCredito.objects.bulk_create(
        [
            DetalleAplicacionCredito(
                empresa=compra.empresa, aplicacion=aplicacion, cuota=c, monto=m
            )
            for c, m in reparto
        ]
    )
    credito.usado += monto
    credito.save(update_fields=["usado"])
    registrar(
        "compras.credito_aplicado",
        recurso_tipo="compra",
        recurso_id=compra.pk,
        empresa_id=compra.empresa_id,
        resumen=f"Saldo a favor de {monto} aplicado a la compra N° {compra.numero:06d}",
        detalle={
            "credito": credito.pk,
            "devolucion": credito.devolucion_id,
            "anticipo": credito.anticipo_id,
            "aplicacion": aplicacion.pk,
            "monto": monto,
            "cuotas": [c.numero for c, _ in reparto],
            "saldo": pendiente - monto,
            "disponible": credito.disponible,
        },
    )
    logger.info("credito_aplicado", extra={"compra_id": compra.pk, "credito_id": credito.pk})
    return aplicacion


@transaction.atomic
def deshacer_aplicacion(aplicacion: AplicacionCredito, *, motivo: str) -> AplicacionCredito:
    """Deshace el uso del saldo a favor: las cuotas vuelven a deberse y el saldo se recupera."""
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise MotivoObligatorio()
    periodos.exigir_empresa(aplicacion.empresa)
    compra = Compra.objects.select_for_update().get(pk=aplicacion.compra_id)
    credito = CreditoProveedor.objects.select_for_update().get(pk=aplicacion.credito_id)
    actual = AplicacionCredito.objects.select_for_update().get(pk=aplicacion.pk)
    if actual.anulada:
        raise DocumentoYaAnulado()
    cuotas = {c.pk: c for c in _cuotas_bloqueadas(compra)}
    for detalle in DetalleAplicacionCredito.objects.filter(aplicacion=actual):
        cuota = cuotas[detalle.cuota_id]
        cuota.pagado -= detalle.monto
        cuota.save(update_fields=["pagado"])
    credito.usado -= actual.monto
    credito.save(update_fields=["usado"])
    aplicacion.anulada = actual.anulada = True
    aplicacion.anulada_en = timezone.now()
    aplicacion.motivo_anulacion = motivo[:250]
    aplicacion.save(update_fields=["anulada", "anulada_en", "motivo_anulacion"])
    registrar(
        "compras.credito_aplicacion_deshecha",
        recurso_tipo="compra",
        recurso_id=compra.pk,
        empresa_id=compra.empresa_id,
        resumen=f"Uso de saldo a favor deshecho en la compra N° {compra.numero:06d}",
        detalle={
            "credito": credito.pk,
            "aplicacion": aplicacion.pk,
            "monto": actual.monto,
            "motivo": motivo[:200],
        },
    )
    return aplicacion
