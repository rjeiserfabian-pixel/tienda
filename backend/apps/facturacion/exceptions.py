from apps.core.exceptions import ErrorDominio


class FacturacionNoActiva(ErrorDominio):
    status_code = 409
    codigo = "facturacion_no_activa"
    mensaje = "La facturación electrónica no está activa en esta empresa."


class ConfiguracionIncompleta(ErrorDominio):
    status_code = 409
    codigo = "configuracion_incompleta"
    mensaje = "Falta completar la configuración de la facturación electrónica."


class DocumentoNoEnviable(ErrorDominio):
    status_code = 409
    codigo = "documento_no_enviable"
    mensaje = "Este documento no se puede enviar a SUNAT."


class EnvioEnCurso(ErrorDominio):
    status_code = 409
    codigo = "envio_en_curso"
    mensaje = "Este documento ya se está enviando. Espere unos segundos."


class YaEnviado(ErrorDominio):
    status_code = 409
    codigo = "ya_enviado"
    mensaje = "Este documento ya se envió a SUNAT."


class ErrorConexionSunat(ErrorDominio):
    """No se pudo hablar con la API de facturación (caída, tiempo agotado, dirección mala)."""

    status_code = 502
    codigo = "sin_conexion_api"
    mensaje = "No se pudo conectar con la API de facturación."
