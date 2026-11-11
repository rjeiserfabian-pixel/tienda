"""La deuda entre empresas de los pedidos mixtos de la tienda: su estado y cómo se revierte.

Cuando un pedido pagado con Culqi incluye productos de las dos empresas, todo el dinero entra a la
cuenta de la empresa que cobra y la parte de la otra queda como ``DeudaCobroTienda``. Esa deuda
también está en la libreta de «Liquidación entre empresas» (``ventas.DeudaInterna``, origen
COBRO_TIENDA) y se salda allí, compensada con lo demás que se deban.

ASIENTO al liquidar (ver ``ventas.liquidacion_interna``), con ``A`` = la empresa que cobró y ``B`` =
la otra, para ``x`` = lo que le tocaba a B:

1. B «Culqi (cobrado por otra empresa)» → A «Culqi (tienda virtual)»: ``x`` (reconocimiento: el
   dinero de B está de verdad en la cuenta de Culqi de A). La cuenta puente de B queda en cero.
2. A (cuenta elegida, por defecto su Culqi) → B (banco elegido): lo NETO de lo que se deben.
   Resultado: A conserva solo lo suyo, B recibe ``x`` en su banco y no queda saldo virtual.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.ventas import liquidacion_interna
from apps.ventas.models import DeudaInterna, MotivoDeuda, OrigenDeuda

from .models import DeudaCobroTienda, PedidoTienda

logger = logging.getLogger(__name__)

PENDIENTE = "PENDIENTE"
LIQUIDADA = "LIQUIDADA"
ANULADA = "ANULADA"  # se revirtió antes de liquidarse: nunca se pagó
REVERSA_PENDIENTE = "REVERSA_PENDIENTE"  # ya se había liquidado: la otra empresa debe devolver
REVERSA_LIQUIDADA = "REVERSA_LIQUIDADA"
ESTADOS = {
    PENDIENTE: "Por liquidar",
    LIQUIDADA: "Liquidada",
    ANULADA: "Anulada antes de liquidar",
    REVERSA_PENDIENTE: "Devolución por liquidar",
    REVERSA_LIQUIDADA: "Devolución liquidada",
}


def _partidas(deuda: DeudaCobroTienda):
    return DeudaInterna.objects.sin_ambito(incluir_eliminados=True).filter(
        origen=OrigenDeuda.COBRO_TIENDA, origen_id=deuda.pk
    )


def estado_de(deuda: DeudaCobroTienda) -> dict:
    """Cómo va esa deuda en la libreta: por liquidar, liquidada (con su número) o revertida."""
    partidas = list(_partidas(deuda).select_related("liquidacion"))
    venta = next((p for p in partidas if p.motivo == MotivoDeuda.VENTA), None)
    reversa = next(
        (p for p in partidas if p.motivo == MotivoDeuda.ANULACION and p.eliminado_en is None), None
    )
    liquidacion = None
    if reversa is not None:
        estado = REVERSA_LIQUIDADA if reversa.liquidacion_id else REVERSA_PENDIENTE
        liquidacion = reversa.liquidacion
    elif deuda.revertida_en is not None:
        estado = ANULADA
    elif venta is not None and venta.liquidacion_id:
        estado, liquidacion = LIQUIDADA, venta.liquidacion
    else:
        estado = PENDIENTE
    return {
        "estado": estado,
        "estado_texto": ESTADOS[estado],
        "liquidacion_id": liquidacion.pk if liquidacion else None,
        "liquidacion_numero": liquidacion.numero if liquidacion else None,
    }


@transaction.atomic
def revertir_deuda_de_pedido(pedido: PedidoTienda, *, motivo: str = "") -> list[dict]:
    """Deshace la deuda entre empresas de un pedido anulado o reembolsado. Es idempotente.

    * Si todavía no se liquidó: la partida se anula (nunca hubo nada que pagar).
    * Si ya se liquidó: se agrega una partida contraria («la otra empresa devuelve») que se
      compensa en la siguiente liquidación; lo ya pagado no se toca.

    Esto NO anula la venta ni devuelve dinero al cliente (eso es del reembolso): solo ajusta lo
    que se deben las empresas. Devuelve un resumen por deuda.
    """
    resumen = []
    deudas = (
        DeudaCobroTienda.objects.sin_ambito()
        .select_for_update()
        .filter(pedido=pedido, revertida_en__isnull=True)
        .select_related("deudora", "acreedora")
    )
    for deuda in deudas:
        partida = (
            _partidas(deuda)
            .select_for_update(of=("self",))
            .filter(motivo=MotivoDeuda.VENTA, eliminado_en__isnull=True)
            .first()
        )
        if partida is None or partida.liquidacion_id is None:
            if partida is not None:
                partida.delete()  # borrado lógico: queda el rastro
            accion = ANULADA
        else:
            liquidacion_interna.partida_de_cobro_web(
                cobro_id=deuda.pk,
                pedido=pedido.numero,
                cobra=deuda.deudora,
                otra=deuda.acreedora,
                monto=deuda.monto,
                motivo=MotivoDeuda.ANULACION,
            )
            accion = REVERSA_PENDIENTE
        deuda.revertida_en = timezone.now()
        deuda.save(update_fields=["revertida_en", "actualizado_en"])
        registrar(
            "tienda.deuda_entre_empresas_revertida",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=f"Pedido {pedido.numero}: deuda entre empresas revertida ({accion})",
            detalle={"monto": deuda.monto, "motivo": (motivo or "")[:200]},
        )
        resumen.append({"deuda": deuda.pk, "monto": deuda.monto, "resultado": accion})
    return resumen
