"""Excepciones de dominio (sin dependencias de DRF, para evitar imports circulares).

El manejador que las convierte en respuestas HTTP está en ``manejador_errores``.
"""


class ErrorDominio(Exception):
    """Error de regla de negocio con código estable y estado HTTP asociado."""

    status_code = 400
    codigo = "error_dominio"
    mensaje = "No se pudo completar la operación."

    def __init__(self, mensaje: str | None = None, *, detalle=None, cabeceras=None):
        self.mensaje = mensaje or self.mensaje
        self.detalle = detalle
        self.cabeceras = cabeceras or {}  # p. ej. {"Retry-After": "60"}
        super().__init__(self.mensaje)


class ContextoTenantNoDefinido(ErrorDominio):
    status_code = 403
    codigo = "contexto_tenant_no_definido"
    mensaje = "No hay organización activa para esta operación."


class EmpresaNoHabilitada(ErrorDominio):
    status_code = 403
    codigo = "empresa_no_habilitada"
    mensaje = "No tiene acceso a la empresa indicada."


class ViolacionAmbito(ErrorDominio):
    status_code = 403
    codigo = "violacion_ambito"
    mensaje = "El registro no pertenece al ámbito activo."


class DocumentoInmutableError(ErrorDominio):
    status_code = 409
    codigo = "documento_inmutable"
    mensaje = "El documento emitido no se puede modificar ni eliminar; debe anularse."


class DocumentoYaAnulado(ErrorDominio):
    status_code = 409
    codigo = "documento_ya_anulado"
    mensaje = "El documento ya se encuentra anulado."


class MotivoObligatorio(ErrorDominio):
    status_code = 400
    codigo = "motivo_obligatorio"
    mensaje = "Debe indicar el motivo de la anulación."


class ClaveIdempotenciaRequerida(ErrorDominio):
    status_code = 400
    codigo = "idempotency_key_requerida"
    mensaje = "Falta una cabecera Idempotency-Key válida."


class ClaveIdempotenciaReutilizada(ErrorDominio):
    status_code = 422
    codigo = "idempotency_key_reutilizada"
    mensaje = "La Idempotency-Key ya se usó con una petición distinta."


class OperacionEnCurso(ErrorDominio):
    status_code = 409
    codigo = "operacion_en_curso"
    mensaje = "Una petición idéntica todavía se está procesando."
