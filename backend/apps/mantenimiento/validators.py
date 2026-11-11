import re

from django.core.exceptions import ValidationError

from apps.organizacion.validators import ruc_es_valido

_ALFANUMERICO = re.compile(r"^[A-Z0-9]+$")


def normalizar_documento(numero: str) -> str:
    """Sin espacios ni guiones y en mayúsculas: así se compara y se garantiza que sea único."""
    return re.sub(r"[\s-]", "", (numero or "")).upper()


def validar_documento(tipo: str, numero: str) -> None:
    """Reglas de formato por tipo. (La consulta a RENIEC/SUNAT es un paso aparte.)"""
    if not numero:
        raise ValidationError({"numero_documento": "Ingrese el número de documento."})
    mensaje = None
    if tipo == "DNI":
        if not (numero.isdigit() and len(numero) == 8):
            mensaje = "El DNI debe tener 8 dígitos."
    elif tipo == "RUC":
        if not ruc_es_valido(numero):
            mensaje = "El RUC no es válido."
    elif tipo == "CE":
        if not (_ALFANUMERICO.match(numero) and 9 <= len(numero) <= 12):
            mensaje = "El carné de extranjería debe tener entre 9 y 12 letras o números."
    elif tipo == "PASAPORTE":
        if not (_ALFANUMERICO.match(numero) and 6 <= len(numero) <= 12):
            mensaje = "El pasaporte debe tener entre 6 y 12 letras o números."
    elif not (_ALFANUMERICO.match(numero) and 3 <= len(numero) <= 20):
        mensaje = "El documento debe tener entre 3 y 20 letras o números."
    if mensaje:
        raise ValidationError({"numero_documento": mensaje})
