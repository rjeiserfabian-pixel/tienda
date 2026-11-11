from apps.core.exceptions import ErrorDominio


class GastoInvalido(ErrorDominio):
    status_code = 400
    codigo = "gasto_invalido"
    mensaje = "Los datos del gasto no son válidos."


class GastoNoModificable(ErrorDominio):
    status_code = 409
    codigo = "gasto_no_modificable"
    mensaje = "Este gasto no admite esa operación."
