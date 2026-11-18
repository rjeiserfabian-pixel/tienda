"""Pedidos con adelanto que el cliente no recogió a tiempo.

Cada hora se revisan los pedidos con adelanto cuyo plazo venció (y que siguen sin entregarse):

* Se suelta el stock apartado.
* Se aplica lo ACORDADO con el cliente al pagar (copiado en el pedido): devolver el adelanto
  menos la comisión de la pasarela, o retener una parte (o todo) como penalidad.
* Lo que se devuelve sale por Culqi con el mismo cuidado que cualquier reembolso (ver
  ``reembolsos``: primero lo interno, después el dinero, con reintentos y sin duplicar).
* Se avisa al cliente. También se le recuerda, un día antes, que su plazo está por vencer.

Lo que se retiene no se mueve: el dinero ya está en la cuenta donde entró. Cómo se registra ese
ingreso (penalidad o comisión recuperada) es una decisión contable que se acuerda con el contador.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar

from . import adelantos, avisos, catalogo, pedidos, reembolsos
from .models import AvisoPedido, HistorialPedido, PedidoTienda

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado
PENDIENTES = (Estado.ADELANTO_PAGADO, Estado.EN_PREPARACION, Estado.LISTO_PARA_RECOJO)
HORAS_RECORDATORIO = 24
TANDA = 100


def _pendientes():
    return PedidoTienda.objects.sin_ambito().filter(
        pago_modo=PedidoTienda.PagoModo.ADELANTO, estado__in=PENDIENTES, venta__isnull=True
    )


def resolver(pedido_id: int) -> str:
    """Resuelve un pedido vencido. Devuelve qué pasó: ``devuelto``, ``retenido`` u ``omitido``."""
    with transaction.atomic():
        pedido = PedidoTienda.objects.sin_ambito().select_for_update().get(pk=pedido_id)
        ahora = timezone.now()
        if (
            pedido.pago_modo != PedidoTienda.PagoModo.ADELANTO
            or pedido.estado not in PENDIENTES
            or pedido.venta_id is not None
            or pedido.adelanto_vence_en is None
            or pedido.adelanto_vence_en > ahora
        ):
            return "omitido"
        devolver, retener = adelantos.liquidar_no_recogido(pedido)
        pedido.adelanto_retenido = retener
        pedidos.liberar_reservas(pedido)  # el producto vuelve a estar disponible
        if devolver <= 0:
            pedido.estado = Estado.NO_RECOGIDO
            pedido.adelanto_devuelto = 0
        pedido.save()
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=pedido.estado,
            texto=(
                f"No recogió a tiempo: se devuelve S/ {devolver:,.2f} del adelanto "
                f"y se retiene S/ {retener:,.2f} (según lo acordado)."
            )[:500],
        )
        registrar(
            "tienda.adelanto_vencido",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=(
                f"Pedido {pedido.numero}: no se recogió (devolver {devolver}, retener {retener})"
            ),
            detalle={"politica": pedido.adelanto_politica},
        )
        transaction.on_commit(catalogo.invalidar)
    if devolver > 0:
        # Fuera de toda transacción: el dinero va por Culqi y puede reintentarse.
        reembolsos.devolver_adelanto_no_recogido(pedido.pk, devolver)
    avisos.encolar(pedido.pk, "PEDIDO_NO_RECOGIDO")
    return "devuelto" if devolver > 0 else "retenido"


def vencer_adelantos() -> int:
    """Resuelve los pedidos con adelanto cuyo plazo ya venció. Devuelve cuántos resolvió."""
    ahora = timezone.now()
    ids = list(
        _pendientes()
        .filter(adelanto_vence_en__lte=ahora)
        .order_by("adelanto_vence_en")
        .values_list("pk", flat=True)[:TANDA]
    )
    resueltos = 0
    for pk in ids:
        try:
            resueltos += resolver(pk) != "omitido"
        except Exception:  # noqa: BLE001 - uno no puede frenar a los demás; se reintenta en una hora
            logger.exception("tienda_adelanto_no_resuelto", extra={"pedido_id": pk})
    return resueltos


def recordar_adelantos() -> int:
    """Avisa, una sola vez, a quien le queda un día o menos para recoger su pedido."""
    ahora = timezone.now()
    ya_avisados = AvisoPedido.objects.sin_ambito().filter(evento="PEDIDO_RECORDATORIO")
    ids = list(
        _pendientes()
        .filter(
            adelanto_vence_en__gt=ahora,
            adelanto_vence_en__lte=ahora + timedelta(hours=HORAS_RECORDATORIO),
        )
        .exclude(pk__in=ya_avisados.values("pedido_id"))
        .values_list("pk", flat=True)[:TANDA]
    )
    for pk in ids:
        avisos.encolar(pk, "PEDIDO_RECORDATORIO")
    return len(ids)
