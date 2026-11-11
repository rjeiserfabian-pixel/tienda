"""Cifrado simétrico con claves versionadas (rotación sin perder datos).

El valor guardado tiene la forma ``"<version>:<token fernet>"``. Cualquier clave
registrada en ``CIFRADO_CLAVES`` descifra; solo ``CIFRADO_CLAVE_ACTUAL`` cifra.
Para rotar: agregar la clave nueva, cambiar ``CIFRADO_CLAVE_ACTUAL`` y ejecutar
``manage.py rotar_clave_cifrado``.
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

_SEPARADOR = ":"


class ErrorDescifrado(Exception):
    """El dato no se pudo descifrar (clave desconocida o dato corrupto)."""


def _fernet(version: str) -> Fernet:
    try:
        return Fernet(settings.CIFRADO_CLAVES[version].encode())
    except KeyError:
        raise ImproperlyConfigured(
            f"No existe la clave de cifrado versión '{version}' en CIFRADO_CLAVES."
        ) from None
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"La clave de cifrado versión '{version}' no es válida."
        ) from exc


def version_actual() -> str:
    return str(settings.CIFRADO_CLAVE_ACTUAL)


def cifrar(texto: str) -> str:
    version = version_actual()
    token = _fernet(version).encrypt(texto.encode()).decode()
    return f"{version}{_SEPARADOR}{token}"


def descifrar(valor: str) -> str:
    version, separador, token = valor.partition(_SEPARADOR)
    if not separador:
        raise ErrorDescifrado("El dato no tiene el formato cifrado esperado.")
    try:
        return _fernet(version).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ErrorDescifrado("No se pudo descifrar el dato.") from exc


def version_de(valor: str) -> str:
    return valor.partition(_SEPARADOR)[0]


class CampoCifrado(models.TextField):
    """Campo que cifra al guardar y descifra al leer. No admite búsquedas por valor."""

    description = "Texto cifrado con clave versionada"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return cifrar(str(value))

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        return descifrar(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        # get_prep_value ya cifra; evita cifrar dos veces.
        return value if prepared else self.get_prep_value(value)
