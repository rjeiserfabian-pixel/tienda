from apps.core.exceptions import ErrorDominio


class VentaInvalida(ErrorDominio):
    status_code = 400
    codigo = "venta_invalida"
    mensaje = "Los datos de la venta no son válidos."


class PrecioBajoElMinimo(ErrorDominio):
    status_code = 409
    codigo = "precio_bajo_el_minimo"
    mensaje = "El precio está por debajo del mínimo permitido."


class VentaNoAnulable(ErrorDominio):
    status_code = 409
    codigo = "venta_no_anulable"
    mensaje = "Este comprobante no se puede anular."


class CuentaDeCobroNoConfigurada(ErrorDominio):
    status_code = 409
    codigo = "cuenta_de_cobro_no_configurada"
    mensaje = "No se sabe en qué caja o cuenta entra este cobro."


class LiquidacionInternaPendiente(ErrorDominio):
    status_code = 409
    codigo = "liquidacion_interna_pendiente"
    mensaje = "Hay ventas internas por liquidar entre las empresas."


class LimiteDeCreditoExcedido(ErrorDominio):
    status_code = 409
    codigo = "limite_de_credito_excedido"
    mensaje = "La venta pasa el límite de crédito del cliente."
