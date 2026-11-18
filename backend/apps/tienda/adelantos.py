"""Pago con adelanto: el cliente paga una parte ahora y el resto al recoger en tienda.

Reglas (decididas con el negocio):

* Solo para pedidos que se RECOGEN en tienda, y solo si TODOS los productos son de la empresa que
  cobra con Culqi (así el dinero del adelanto es de esa empresa y se descuenta de su comprobante).
* El porcentaje, el monto mínimo del pedido y los días para recoger los define el negocio.
* Lo acordado se COPIA al pedido al crearlo: si el negocio cambia su configuración después, los
  pedidos ya hechos conservan las condiciones con que el cliente los aceptó.
* Mientras el pedido espera su saldo, el stock sigue apartado.
* Si el cliente no recoge a tiempo, el negocio decide (una sola política): devolver el adelanto
  menos la comisión de la pasarela, o retenerlo como penalidad (todo o una parte).
* El adelanto entra a la cuenta de cobro como un ingreso («adelanto de la tienda») y NO se emite un
  comprobante por él: el comprobante sale por el total al entregar y descuenta lo ya pagado.
"""

import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import ConfiguracionPago, PedidoTienda

logger = logging.getLogger(__name__)

CERO = Decimal("0")
CENTIMO = Decimal("0.01")
MINIMO_ADELANTO = Decimal("1.00")  # no tiene sentido cobrar menos (la pasarela se lo come)


def _q(valor: Decimal) -> Decimal:
    return valor.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _pct(valor: Decimal) -> str:
    """Un porcentaje legible: 30 → «30», 3.5 → «3.5»."""
    texto = format(Decimal(valor).normalize(), "f")
    return texto.rstrip("0").rstrip(".") if "." in texto else texto


def configuracion(organizacion_id: int) -> ConfiguracionPago | None:
    return ConfiguracionPago.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()


def condiciones(
    *,
    dias: int,
    politica: str,
    penalidad_pct: Decimal,
    comision_pct: Decimal,
    comision_fija: Decimal,
) -> str:
    """Lo que el cliente acepta, en palabras claras (se muestra antes de pagar)."""
    plazo = f"Si no recoges tu pedido en {dias} {'día' if dias == 1 else 'días'}"
    if politica == ConfiguracionPago.SiNoRecoge.PENALIDAD:
        if penalidad_pct >= 100:
            return f"{plazo}, pierdes tu adelanto."
        return (
            f"{plazo}, retenemos el {_pct(penalidad_pct)} % de tu adelanto "
            "y te devolvemos el resto."
        )
    comision = f"{_pct(comision_pct)} %" + (
        f" + S/ {comision_fija:,.2f}" if comision_fija > 0 else ""
    )
    return (
        f"{plazo}, te devolvemos tu adelanto menos la comisión del procesador de pagos "
        f"({comision})."
    )


def _motivo(texto: str) -> dict:
    return {"disponible": False, "motivo": texto}


def evaluar(config: ConfiguracionPago | None, *, calculo) -> dict | None:
    """¿Se puede ofrecer el adelanto a este pedido? Devuelve ``None`` si el negocio no lo usa
    (o el pedido no se recoge: ahí ni se menciona) o un diccionario con la oferta o el motivo."""
    if config is None or not config.adelanto_activo:
        return None
    if calculo.modalidad != "RECOJO":
        return None
    if not (config.culqi_activo and config.empresa_cobra_id):
        return None
    total = calculo.total
    if total < config.adelanto_minimo:
        return _motivo(
            f"El pago con adelanto es para pedidos desde S/ {config.adelanto_minimo:,.2f}."
        )
    empresas = {ln["empresa"].pk for ln in calculo.lineas if not ln["es_envio"]}
    if empresas != {config.empresa_cobra_id}:
        return _motivo("Este pedido tiene productos de otra empresa: se paga completo.")
    monto = _q(total * config.adelanto_pct / Decimal(100))
    if monto < MINIMO_ADELANTO or monto >= total:
        return _motivo("El adelanto de este pedido no es válido: se paga completo.")
    return {
        "disponible": True,
        "motivo": "",
        "porcentaje": _pct(config.adelanto_pct),
        "monto": format(monto, "f"),
        "saldo": format(total - monto, "f"),
        "dias": config.adelanto_dias,
        "condiciones": condiciones(
            dias=config.adelanto_dias,
            politica=config.adelanto_si_no_recoge,
            penalidad_pct=config.adelanto_penalidad_pct,
            comision_pct=config.comision_pasarela_pct,
            comision_fija=config.comision_pasarela_fija,
        ),
    }


def campos_del_pedido(config: ConfiguracionPago, monto: Decimal) -> dict:
    """Lo acordado, para copiarlo al pedido al crearlo."""
    return {
        "pago_modo": PedidoTienda.PagoModo.ADELANTO,
        "adelanto_pct": config.adelanto_pct,
        "adelanto_monto": monto,
        "adelanto_dias": config.adelanto_dias,
        "adelanto_politica": config.adelanto_si_no_recoge,
        "adelanto_penalidad_pct": config.adelanto_penalidad_pct,
        "adelanto_comision_pct": config.comision_pasarela_pct,
        "adelanto_comision_fija": config.comision_pasarela_fija,
    }


def vencimiento(pedido: PedidoTienda, desde=None):
    """Hasta cuándo puede recoger: ``días`` completos desde que pagó el adelanto."""
    return (desde or timezone.now()) + timedelta(days=pedido.adelanto_dias)


def texto_condiciones(pedido: PedidoTienda) -> str:
    return condiciones(
        dias=pedido.adelanto_dias,
        politica=pedido.adelanto_politica,
        penalidad_pct=pedido.adelanto_penalidad_pct,
        comision_pct=pedido.adelanto_comision_pct,
        comision_fija=pedido.adelanto_comision_fija,
    )


def liquidar_no_recogido(pedido: PedidoTienda) -> tuple[Decimal, Decimal]:
    """``(a devolver, a retener)`` del adelanto de un pedido no recogido, según lo acordado."""
    adelanto = pedido.adelanto_monto
    if pedido.adelanto_politica == ConfiguracionPago.SiNoRecoge.PENALIDAD:
        retener = _q(adelanto * pedido.adelanto_penalidad_pct / Decimal(100))
    else:
        comision = _q(adelanto * pedido.adelanto_comision_pct / Decimal(100))
        retener = min(comision + pedido.adelanto_comision_fija, adelanto)
    retener = min(max(retener, CERO), adelanto)
    return adelanto - retener, retener
