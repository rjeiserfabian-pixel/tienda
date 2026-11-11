from apps.core.exceptions import ErrorDominio


class SesionNoValida(ErrorDominio):
    status_code = 401
    codigo = "sesion_no_valida"
    mensaje = "Ingresa a tu cuenta para continuar."


class CredencialesInvalidas(ErrorDominio):
    status_code = 401
    codigo = "credenciales_invalidas"
    mensaje = "Correo o contraseña incorrectos."


class CuentaBloqueada(ErrorDominio):
    status_code = 429
    codigo = "cuenta_bloqueada"
    mensaje = "Demasiados intentos. Espera unos minutos e inténtalo de nuevo."


class EnlaceInvalido(ErrorDominio):
    status_code = 400
    codigo = "enlace_invalido"
    mensaje = "El enlace no es válido o ya venció. Pide uno nuevo."


class DatosInvalidos(ErrorDominio):
    status_code = 400
    codigo = "datos_invalidos"
    mensaje = "Revisa los datos ingresados."


class SolicitudNoPermitida(ErrorDominio):
    status_code = 403
    codigo = "solicitud_no_permitida"
    mensaje = "Solicitud no permitida."


class PedidoInvalido(ErrorDominio):
    status_code = 400
    codigo = "pedido_invalido"
    mensaje = "No pudimos armar tu pedido. Revisa los datos."


class CorreoSinConfirmar(ErrorDominio):
    status_code = 403
    codigo = "correo_sin_confirmar"
    mensaje = "Confirma tu correo antes de comprar. Te enviamos un enlace al registrarte."


class PedidoNoEncontrado(ErrorDominio):
    status_code = 404
    codigo = "pedido_no_encontrado"
    mensaje = "No encontramos ese pedido."


class PedidoNoCancelable(ErrorDominio):
    status_code = 409
    codigo = "pedido_no_cancelable"
    mensaje = "Este pedido ya no se puede cancelar."


class PagoNoDisponible(ErrorDominio):
    status_code = 503
    codigo = "pago_no_disponible"
    mensaje = "El pago en línea no está disponible por el momento. Escríbenos y te ayudamos."


class PagoRechazado(ErrorDominio):
    status_code = 402
    codigo = "pago_rechazado"
    mensaje = "Tu banco no aprobó el pago. Prueba con otra tarjeta o medio."


class PagoEnProceso(ErrorDominio):
    status_code = 409
    codigo = "pago_en_proceso"
    mensaje = "Tu pago se está procesando. Espera unos segundos y revisa tu pedido."


class PedidoVencido(ErrorDominio):
    status_code = 409
    codigo = "pedido_vencido"
    mensaje = "Este pedido venció. Vuelve a armar tu carrito."


class TransicionInvalida(ErrorDominio):
    status_code = 409
    codigo = "transicion_invalida"
    mensaje = "Ese cambio de estado no es posible."


class ReembolsoNoPermitido(ErrorDominio):
    status_code = 409
    codigo = "reembolso_no_permitido"
    mensaje = "Este pedido no se puede reembolsar."
