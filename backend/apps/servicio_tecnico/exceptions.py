from apps.core.exceptions import ErrorDominio


class OrdenInvalida(ErrorDominio):
    status_code = 400
    codigo = "orden_servicio_invalida"
    mensaje = "Los datos de la orden de servicio no son válidos."


class TransicionInvalida(ErrorDominio):
    status_code = 409
    codigo = "transicion_estado_invalida"
    mensaje = "La orden no puede pasar a ese estado."


class MotivoRequerido(ErrorDominio):
    status_code = 400
    codigo = "motivo_requerido"
    mensaje = "Indique el motivo del cambio de estado."


class DiagnosticoIncompleto(ErrorDominio):
    status_code = 400
    codigo = "diagnostico_incompleto"
    mensaje = "Falta completar el diagnóstico."


class PresupuestoInvalido(ErrorDominio):
    status_code = 400
    codigo = "presupuesto_invalido"
    mensaje = "Los datos del presupuesto no son válidos."


class PresupuestoRequerido(ErrorDominio):
    status_code = 400
    codigo = "presupuesto_requerido"
    mensaje = "Arme el presupuesto antes de continuar."


class RepuestosPendientes(ErrorDominio):
    status_code = 409
    codigo = "repuestos_pendientes"
    mensaje = "Faltan repuestos por reservar."


class AbandonoNoPermitido(ErrorDominio):
    status_code = 409
    codigo = "abandono_no_permitido"
    mensaje = "Todavía no se puede dar por abandonado."
