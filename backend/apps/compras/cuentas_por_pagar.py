"""Cuentas por pagar: pagar las cuotas de las compras a crédito y revertir un pago.

Un pago se aplica a las cuotas más antiguas primero, o a una cuota elegida. Puede cubrir varias
cuotas y quedan guardadas sus aplicaciones, así anularlo devuelve a cada cuota exactamente lo que
recibió. El pago se hace desde una caja o cuenta de la empresa, en la moneda de la compra. El
movimiento del dinero en esa caja lo llevará el módulo de Caja y bancos.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.inventario import periodos

from .exceptions import CompraInvalida, CompraNoAnulable
from .models import AplicacionPago, Compra, CuotaCompra, FormaPago, PagoCompra
from .servicios import PagoEntrada, _detalle_cambio, _validar_pago

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


def _cuotas_bloqueadas(compra: Compra) -> list[CuotaCompra]:
    """Las cuotas de la compra, bloqueadas y en orden: dos pagos a la vez no se pisan."""
    return list(CuotaCompra.objects.select_for_update().filter(compra=compra).order_by("numero"))


def saldo_de(compra: Compra) -> Decimal:
    """Lo que falta pagar de una compra a crédito."""
    return sum((c.monto - c.pagado for c in CuotaCompra.objects.filter(compra=compra)), ZERO)


def repartir(cuotas: list[CuotaCompra], monto: Decimal, cuota_ids: list[int] | None) -> list[tuple]:
    """``[(cuota, monto)]``: a las cuotas elegidas, o a las pendientes de la más antigua a la nueva.

    Con cuotas elegidas solo se paga entre ellas (por ejemplo la 1 y la 3), también en orden.
    """
    candidatas = cuotas
    if cuota_ids:
        elegidas = set(cuota_ids)
        candidatas = [c for c in cuotas if c.pk in elegidas]
        if len(candidatas) != len(elegidas):
            raise CompraInvalida("Una cuota no pertenece a la compra.")
        disponible = sum((c.monto - c.pagado for c in candidatas), ZERO)
        if monto > disponible:
            texto = (
                f"La cuota {candidatas[0].numero} solo tiene pendiente {disponible}."
                if len(candidatas) == 1
                else f"Las cuotas elegidas solo tienen pendiente {disponible}."
            )
            raise CompraInvalida(texto)
    restante = monto
    aplicado = []
    for cuota in candidatas:
        pendiente = cuota.monto - cuota.pagado
        if pendiente <= 0 or restante <= 0:
            continue
        parte = min(pendiente, restante)
        aplicado.append((cuota, parte))
        restante -= parte
    return aplicado


@transaction.atomic
def registrar_pagos(
    compra: Compra,
    *,
    pagos: list[PagoEntrada],
    cuota_ids: list[int] | None = None,
) -> list[PagoCompra]:
    """Paga una compra a crédito con uno o varios medios a la vez (efectivo y Yape, por ejemplo).

    Cada medio queda como un pago propio, con su caja o cuenta y su número de operación. Entre
    todos se aplican a las cuotas más antiguas primero (o solo a las elegidas). Todo o nada: si
    uno no es válido, no se registra ninguno. Entre todos no pueden pasar de lo que se debe.
    """
    if not pagos:
        raise CompraInvalida("Indique al menos un pago.")
    periodos.exigir_empresa(compra.empresa)
    actual = Compra.objects.select_for_update().get(pk=compra.pk)
    if actual.estado != Compra.Estado.EMITIDO:
        raise CompraInvalida("La compra está anulada: no se puede pagar.")
    if actual.forma_pago != FormaPago.CREDITO:
        raise CompraInvalida("La compra fue al contado: ya está pagada.")
    hoy = timezone.localdate()
    validados = []
    for i, pago in enumerate(pagos, start=1):
        etiqueta = "Pago" if len(pagos) == 1 else f"Pago {i}"
        validado = _validar_pago(compra.empresa, pago, actual.moneda, hoy, etiqueta)
        if validado.fecha < actual.fecha_emision:
            raise CompraInvalida("El pago no puede ser anterior a la emisión de la compra.")
        validados.append(validado)
    cuotas = _cuotas_bloqueadas(actual)
    pendiente = sum((c.monto - c.pagado for c in cuotas), ZERO)
    if pendiente <= 0:
        raise CompraInvalida("La compra ya está pagada por completo.")
    a_pagar = sum((v.monto for v in validados), ZERO)
    if a_pagar > pendiente:
        raise CompraInvalida(f"Los pagos suman más de lo que se debe ({pendiente}).")

    creados = []
    for validado in validados:
        aplicado = repartir(cuotas, validado.monto, cuota_ids)
        nuevo = PagoCompra.objects.create(
            empresa=actual.empresa,
            compra=actual,
            tipo=PagoCompra.Tipo.COMPRA,
            medio_pago=validado.medio_pago,
            cuenta=validado.cuenta,
            fecha=validado.fecha,
            monto=validado.monto,
            referencia=validado.referencia,
            tipo_cambio=validado.tipo_cambio,
            monto_cuenta=validado.monto_cuenta,
        )
        for cuota, parte in aplicado:
            cuota.pagado += parte
            cuota.save(update_fields=["pagado"])
        caja.registrar_pago_de_compra(
            empresa=actual.empresa,
            cuenta=validado.cuenta,
            monto=nuevo.monto_en_cuenta,
            fecha=validado.fecha,
            referencia=validado.referencia,
            glosa=(
                f"Pago de cuotas {', '.join(str(c.numero) for c, _ in aplicado)} de la compra "
                f"N° {actual.numero:06d} · {actual.comprobante} · {actual.proveedor.nombre}"
                f"{_detalle_cambio(nuevo, actual.moneda)}"
            ),
            pago_id=nuevo.pk,
            medio_pago=nuevo.medio_pago,
            aporte_socio=validado.aporte_socio,
        )
        AplicacionPago.objects.bulk_create(
            [
                AplicacionPago(empresa=actual.empresa, pago=nuevo, cuota=c, monto=m)
                for c, m in aplicado
            ]
        )
        pendiente -= validado.monto
        registrar(
            "compras.pago_registrado",
            recurso_tipo="compra",
            recurso_id=actual.pk,
            empresa_id=actual.empresa_id,
            resumen=f"Pago de {validado.monto} a la compra N° {actual.numero:06d}",
            detalle={
                "pago": nuevo.pk,
                "monto": validado.monto,
                "cuenta": validado.cuenta.pk,
                "medio_pago": validado.medio_pago.pk,
                "cuotas": [c.numero for c, _ in aplicado],
                "saldo": pendiente,
            },
        )
        logger.info("pago_compra_registrado", extra={"compra_id": actual.pk, "pago_id": nuevo.pk})
        creados.append(nuevo)
    return creados


def registrar_pago(
    compra: Compra,
    *,
    pago: PagoEntrada,
    cuota_id: int | None = None,
) -> PagoCompra:
    """Paga una compra a crédito con un solo medio (ver ``registrar_pagos``)."""
    return registrar_pagos(compra, pagos=[pago], cuota_ids=[cuota_id] if cuota_id else None)[0]


@transaction.atomic
def anular_pago(pago: PagoCompra, *, motivo: str) -> PagoCompra:
    """Revierte un pago a crédito: cada cuota recupera lo que había recibido de él."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise MotivoObligatorio()
    periodos.exigir_empresa(pago.empresa)
    compra = Compra.objects.select_for_update().get(pk=pago.compra_id)
    actual = PagoCompra.objects.select_for_update().get(pk=pago.pk)
    if actual.anulado:
        raise DocumentoYaAnulado()
    if compra.estado != Compra.Estado.EMITIDO:
        raise CompraNoAnulable("La compra está anulada: sus pagos ya quedaron anulados con ella.")
    aplicaciones = list(AplicacionPago.objects.filter(pago=actual).select_related("cuota"))
    if not aplicaciones:
        raise CompraNoAnulable(
            "Este pago se hizo al registrar la compra: para deshacerlo, anula la compra."
        )
    cuotas = {c.pk: c for c in _cuotas_bloqueadas(compra)}
    for aplicacion in aplicaciones:
        cuota = cuotas[aplicacion.cuota_id]
        cuota.pagado -= aplicacion.monto
        cuota.save(update_fields=["pagado"])
    caja.anular_por_origen(Origen.PAGO_COMPRA, actual.pk, motivo=f"Pago anulado: {motivo}")
    actual.anulado = True
    actual.anulado_en = timezone.now()
    actual.motivo_anulacion = motivo[:250]
    actual.save(update_fields=["anulado", "anulado_en", "motivo_anulacion"])
    registrar(
        "compras.pago_anulado",
        recurso_tipo="compra",
        recurso_id=compra.pk,
        empresa_id=compra.empresa_id,
        resumen=f"Pago de {actual.monto} de la compra N° {compra.numero:06d} anulado",
        detalle={"pago": actual.pk, "monto": actual.monto, "motivo": motivo[:200]},
    )
    return actual
