from apps.core.exceptions import ErrorDominio


class ReclamoInvalido(ErrorDominio):
    status_code = 400
    codigo = "reclamo_garantia_invalido"
    mensaje = "El reclamo de garantía no es válido."


class ReclamoNoPermitido(ErrorDominio):
    status_code = 409
    codigo = "reclamo_garantia_no_permitido"
    mensaje = "Esta acción no corresponde al estado del reclamo."
