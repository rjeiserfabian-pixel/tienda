"""Lectura segura de la contraseña para los comandos (nunca como argumento visible)."""

import os
from getpass import getpass

from django.core.management.base import CommandError


def leer_password(variable_entorno: str = "USUARIO_PASSWORD") -> str:
    """Toma la contraseña de una variable de entorno (automatización) o la pide oculta."""
    password = os.environ.get(variable_entorno)
    if password:
        return password
    password = getpass("Contraseña: ")
    if password != getpass("Repetir contraseña: "):
        raise CommandError("Las contraseñas no coinciden.")
    return password
