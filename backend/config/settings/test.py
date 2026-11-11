"""Pruebas automáticas (pytest)."""

from cryptography.fernet import Fernet

from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS, REST_FRAMEWORK

SECRET_KEY = "clave-solo-para-pruebas-de-al-menos-32-bytes"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
USAR_REDIS = False
INSTALLED_APPS = [*INSTALLED_APPS, "apps.core.tests.app_prueba"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # rápido, solo tests
CELERY_TASK_ALWAYS_EAGER = True
LOG_JSON = False
DOCS_API_HABILITADA = True
COOKIE_REFRESH_SECURE = False
TIENDA_COOKIE_SECURE = False
# Las pruebas nunca avisan a una tienda real (aunque el .env de desarrollo tenga la dirección).
TIENDA_RENOVAR_URL = ""
TIENDA_RENOVAR_TOKEN = ""

CIFRADO_CLAVES = {"1": Fernet.generate_key().decode(), "2": Fernet.generate_key().decode()}
CIFRADO_CLAVE_ACTUAL = "1"

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        "login": "1000/min",
        "usuario": "1000/min",
        "mostrador": "1000/min",
        "anon": "1000/min",
        "consultas": "1000/min",
        "importaciones": "1000/hour",
        "exportaciones": "1000/hour",
        "tienda": "1000/min",
        "tienda_fotos": "1000/min",
        "tienda_cuenta": "1000/min",
        "tienda_webhook": "1000/min",
    },
}

# La mayoría de las pruebas pagan sin haber cargado saldo; las del bloqueo lo activan a propósito
# (apps/caja/tests/test_saldo_insuficiente.py).
CAJA_BLOQUEA_SALDO_NEGATIVO = False
