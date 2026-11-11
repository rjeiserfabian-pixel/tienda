from apps.core.exceptions import ErrorDominio


class UltimaEmpresaActiva(ErrorDominio):
    status_code = 409
    codigo = "ultima_empresa_activa"
    mensaje = "La organización debe conservar al menos una empresa activa."


class UltimaSucursalActiva(ErrorDominio):
    status_code = 409
    codigo = "ultima_sucursal_activa"
    mensaje = "La empresa debe conservar al menos una sucursal activa."


class RucBloqueado(ErrorDominio):
    status_code = 409
    codigo = "ruc_bloqueado"
    mensaje = "El RUC ya no se puede cambiar: la empresa tiene documentos emitidos."


class LogoInvalido(ErrorDominio):
    status_code = 400
    codigo = "logo_invalido"
    mensaje = "El logo no es válido."
