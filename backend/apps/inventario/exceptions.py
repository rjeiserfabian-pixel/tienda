from apps.core.exceptions import ErrorDominio


class StockInsuficiente(ErrorDominio):
    status_code = 409
    codigo = "stock_insuficiente"
    mensaje = "No hay stock suficiente para esta salida."


class PeriodoCerrado(ErrorDominio):
    status_code = 409
    codigo = "periodo_cerrado"
    mensaje = "El periodo está cerrado: ya no admite movimientos."


class PeriodoInvalido(ErrorDominio):
    status_code = 400
    codigo = "periodo_invalido"
    mensaje = "El periodo no es válido. Use el formato AAAAMM."


class CierreFueraDeOrden(ErrorDominio):
    status_code = 409
    codigo = "cierre_fuera_de_orden"
    mensaje = "Los periodos se cierran en orden, del más antiguo al más reciente."


class TipoCambioNoDisponible(ErrorDominio):
    status_code = 400
    codigo = "tipo_cambio_no_disponible"
    mensaje = "No hay tipo de cambio para esa fecha. Regístrelo e intente de nuevo."


class ComprobanteDuplicado(ErrorDominio):
    status_code = 409
    codigo = "comprobante_duplicado"
    mensaje = "Ya existe un movimiento con ese comprobante."


class MovimientoInvalido(ErrorDominio):
    status_code = 400
    codigo = "movimiento_invalido"
    mensaje = "El movimiento no es válido."


class ProductoNoInventariable(ErrorDominio):
    status_code = 400
    codigo = "producto_no_inventariable"
    mensaje = "El producto no lleva control de stock."


class AnulacionNoPermitida(ErrorDominio):
    status_code = 409
    codigo = "anulacion_no_permitida"
    mensaje = "El movimiento no se puede anular."


class ReporteInvalido(ErrorDominio):
    status_code = 400
    codigo = "reporte_invalido"
    mensaje = "Los datos del reporte no son válidos."


class ReporteDemasiadoGrande(ErrorDominio):
    status_code = 400
    codigo = "reporte_demasiado_grande"
    mensaje = "El reporte tiene demasiadas filas. Reduzca el rango de fechas o elija un almacén."


class TomaEstadoInvalido(ErrorDominio):
    status_code = 409
    codigo = "toma_estado_invalido"
    mensaje = "La toma de inventario no está en un estado que permita esta operación."


class TomaInvalida(ErrorDominio):
    status_code = 400
    codigo = "toma_invalida"
    mensaje = "Los datos de la toma de inventario no son válidos."


class TomaVigenteExistente(ErrorDominio):
    status_code = 409
    codigo = "toma_vigente_existente"
    mensaje = "Ese almacén ya tiene una toma de inventario en curso."


class ConteoInvalido(ErrorDominio):
    status_code = 400
    codigo = "conteo_invalido"
    mensaje = "El conteo no es válido."


class ConteoRequiereConfirmacion(ErrorDominio):
    status_code = 409
    codigo = "conteo_requiere_confirmacion"
    mensaje = "Confirme el conteo: se contó 0 de un producto con stock importante."


class TomaIncompleta(ErrorDominio):
    status_code = 409
    codigo = "toma_incompleta"
    mensaje = "La toma todavía tiene pendientes y no se puede cerrar."


class AjusteImposible(ErrorDominio):
    status_code = 409
    codigo = "ajuste_imposible"
    mensaje = "No se puede generar el ajuste de la toma de inventario."
