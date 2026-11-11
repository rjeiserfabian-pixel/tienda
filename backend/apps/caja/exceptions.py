from apps.core.exceptions import ErrorDominio


class MovimientoInvalido(ErrorDominio):
    status_code = 400
    codigo = "movimiento_caja_invalido"
    mensaje = "Los datos del movimiento no son válidos."


class MovimientoNoAnulable(ErrorDominio):
    status_code = 409
    codigo = "movimiento_caja_no_anulable"
    mensaje = "Este movimiento no se puede anular."


class SesionRequerida(ErrorDominio):
    status_code = 409
    codigo = "sesion_caja_requerida"
    mensaje = "Abra la sesión de la caja para mover efectivo."


class SaldoInsuficiente(ErrorDominio):
    status_code = 409
    codigo = "saldo_insuficiente"
    mensaje = "La caja o cuenta no tiene saldo para esta salida."


class SesionInvalida(ErrorDominio):
    status_code = 409
    codigo = "sesion_caja_invalida"
    mensaje = "La operación no se puede hacer con esta sesión de caja."


class ConciliacionInvalida(ErrorDominio):
    status_code = 409
    codigo = "conciliacion_invalida"
    mensaje = "La operación no se puede hacer con este estado de cuenta."


class AdjuntoInvalido(ErrorDominio):
    status_code = 400
    codigo = "adjunto_caja_invalido"
    mensaje = "El archivo no se puede adjuntar."


class RendicionInvalida(ErrorDominio):
    status_code = 409
    codigo = "rendicion_caja_invalida"
    mensaje = "La rendición de la caja chica no se puede hacer."


class ChequeInvalido(ErrorDominio):
    status_code = 400
    codigo = "cheque_invalido"
    mensaje = "Los datos del cheque no son válidos."


class ChequeNoModificable(ErrorDominio):
    status_code = 409
    codigo = "cheque_no_modificable"
    mensaje = "El cheque no se puede cambiar en su estado actual."
