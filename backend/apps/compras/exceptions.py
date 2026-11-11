from apps.core.exceptions import ErrorDominio


class CompraInvalida(ErrorDominio):
    status_code = 400
    codigo = "compra_invalida"
    mensaje = "Los datos de la compra no son válidos."


class CompraNoAnulable(ErrorDominio):
    status_code = 409
    codigo = "compra_no_anulable"
    mensaje = "Esta compra no se puede anular."


class DevolucionInvalida(ErrorDominio):
    status_code = 400
    codigo = "devolucion_invalida"
    mensaje = "Los datos de la devolución no son válidos."


class DevolucionNoAnulable(ErrorDominio):
    status_code = 409
    codigo = "devolucion_no_anulable"
    mensaje = "Esta devolución no se puede anular."


class CreditoInvalido(ErrorDominio):
    status_code = 400
    codigo = "credito_invalido"
    mensaje = "El saldo a favor no se puede aplicar así."


class OrdenCompraInvalida(ErrorDominio):
    status_code = 400
    codigo = "orden_compra_invalida"
    mensaje = "Los datos de la orden de compra no son válidos."


class OrdenCompraNoModificable(ErrorDominio):
    status_code = 409
    codigo = "orden_compra_no_modificable"
    mensaje = "La orden de compra no se puede modificar en su estado actual."


class CotizacionInvalida(ErrorDominio):
    status_code = 400
    codigo = "cotizacion_invalida"
    mensaje = "Los datos de la cotización no son válidos."


class CotizacionNoModificable(ErrorDominio):
    status_code = 409
    codigo = "cotizacion_no_modificable"
    mensaje = "La cotización no se puede modificar en su estado actual."


class AnticipoInvalido(ErrorDominio):
    status_code = 400
    codigo = "anticipo_invalido"
    mensaje = "Los datos del anticipo no son válidos."
