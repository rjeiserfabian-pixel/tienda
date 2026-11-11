from django.core.exceptions import ValidationError

_PESOS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
_PREFIJOS_VALIDOS = ("10", "15", "16", "17", "20")


def ruc_es_valido(ruc: str) -> bool:
    """RUC peruano: 11 dígitos, prefijo válido y dígito verificador (módulo 11)."""
    if len(ruc) != 11 or not ruc.isdigit() or ruc[:2] not in _PREFIJOS_VALIDOS:
        return False
    suma = sum(int(d) * p for d, p in zip(ruc[:10], _PESOS, strict=True))
    verificador = (11 - suma % 11) % 10
    return verificador == int(ruc[10])


def validar_ruc(valor: str) -> None:
    if not ruc_es_valido(valor):
        raise ValidationError("El RUC no es válido.", code="ruc_invalido")
