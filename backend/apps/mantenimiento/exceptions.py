from apps.core.exceptions import ErrorDominio


class ConsultaNoConfigurada(ErrorDominio):
    status_code = 503
    codigo = "consulta_no_configurada"
    mensaje = "La consulta de DNI y RUC no está configurada. Avise al administrador del sistema."


class DocumentoNoEncontrado(ErrorDominio):
    status_code = 404
    codigo = "documento_no_encontrado"
    mensaje = "No se encontraron datos para ese número."


class ServicioConsultaNoDisponible(ErrorDominio):
    status_code = 502
    codigo = "servicio_consulta_no_disponible"
    mensaje = "El servicio de consulta no está disponible ahora. Intenta de nuevo en unos minutos."


class UsuarioYaVinculado(ErrorDominio):
    status_code = 409
    codigo = "usuario_ya_vinculado"
    mensaje = "Ese usuario ya está vinculado a otro trabajador."


class FamiliaConCategorias(ErrorDominio):
    status_code = 409
    codigo = "familia_con_categorias"
    mensaje = "La familia tiene categorías. Elimínalas o muévelas a otra familia primero."


class CentroConHijos(ErrorDominio):
    status_code = 409
    codigo = "centro_con_hijos"
    mensaje = "El centro de costo tiene centros dentro. Elimínalos o muévelos primero."


class TipoCambioOficial(ErrorDominio):
    status_code = 409
    codigo = "tipo_cambio_oficial"
    mensaje = "Los tipos de cambio de SUNAT y SBS no se modifican: son el dato oficial."


class CuotaAgotada(ErrorDominio):
    status_code = 429
    codigo = "cuota_agotada"
    mensaje = (
        "Se agotó la cuota mensual de consultas al servicio externo. "
        "Puedes seguir registrando los datos a mano; se renueva el próximo mes."
    )


class RegistroEnUso(ErrorDominio):
    status_code = 409
    codigo = "registro_en_uso"
    mensaje = "Está en uso por productos. Desactívalo en lugar de eliminarlo."


class ImagenInvalida(ErrorDominio):
    status_code = 400
    codigo = "imagen_invalida"
    mensaje = "La imagen no es válida."


class TasaNoVigente(ErrorDominio):
    status_code = 422
    codigo = "tasa_no_vigente"
    mensaje = "No hay una tasa de impuesto vigente para esa fecha. Cárgala en Tasas de impuesto."


class AfectacionNoDisponible(ErrorDominio):
    status_code = 422
    codigo = "afectacion_no_disponible"
    mensaje = "La afectación del IGV que corresponde no está activa. Actívala en IGV."


class SerieNoDisponible(ErrorDominio):
    status_code = 404
    codigo = "serie_no_disponible"
    mensaje = "La serie no existe en esta empresa."


class SerieInactiva(ErrorDominio):
    status_code = 409
    codigo = "serie_inactiva"
    mensaje = "La serie está desactivada. Actívala o elige otra para emitir."


class SerieAgotada(ErrorDominio):
    status_code = 409
    codigo = "serie_agotada"
    mensaje = "La serie llegó a su último número (99 999 999). Crea una serie nueva."


class CorrelativoNoPuedeBajar(ErrorDominio):
    status_code = 409
    codigo = "correlativo_no_puede_bajar"
    mensaje = (
        "Esta serie ya emitió comprobantes: su numeración no puede bajar, solo subir "
        "(un número repetido invalida el comprobante ante SUNAT)."
    )
