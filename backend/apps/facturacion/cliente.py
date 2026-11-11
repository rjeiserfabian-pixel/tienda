"""La llamada HTTP a la API de facturación.

Reglas: tiempo máximo explícito, sin seguir redirecciones, y NUNCA se escribe en el log lo que se
envía (lleva las claves SOL) ni lo que se recibe: solo el código HTTP y el tipo de documento.
"""

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from django.conf import settings

from .exceptions import ConfiguracionIncompleta, ErrorConexionSunat

logger = logging.getLogger(__name__)

TIEMPO_CONEXION = 5  # segundos para abrir la conexión


@dataclass(frozen=True, slots=True)
class RespuestaApi:
    codigo_http: int
    datos: dict | None  # el contenido de «data» cuando la respuesta es JSON; si no, None


def _base() -> str:
    return settings.SUNAT_API_URL.rstrip("/") + "/"


def direccion_de(tipo_documento: str) -> str:
    """La dirección completa donde se envía ese tipo de documento."""
    archivo = settings.SUNAT_ENDPOINTS.get(tipo_documento, "")
    if not archivo:
        raise ConfiguracionIncompleta(
            "Falta configurar en el servidor la dirección de la API para este tipo de documento "
            "(guía de remisión: variable SUNAT_ENDPOINT_GUIA)."
        )
    return urljoin(_base(), archivo)


def enviar(tipo_documento: str, payload: dict) -> RespuestaApi:
    """Envía el JSON a la API y devuelve su respuesta sin interpretarla."""
    url = direccion_de(tipo_documento)
    try:
        respuesta = requests.post(
            url,
            json=payload,
            timeout=(TIEMPO_CONEXION, settings.SUNAT_API_TIMEOUT),
            allow_redirects=False,
        )
    except requests.Timeout:
        raise ErrorConexionSunat("La API de facturación tardó demasiado en responder.") from None
    except requests.RequestException:
        raise ErrorConexionSunat() from None
    try:
        cuerpo = respuesta.json()
    except ValueError:
        cuerpo = None
    datos = cuerpo.get("data") if isinstance(cuerpo, dict) else None
    logger.info(
        "api_facturacion_respuesta",
        extra={"tipo_documento": tipo_documento, "http": respuesta.status_code},
    )
    return RespuestaApi(respuesta.status_code, datos if isinstance(datos, dict) else None)


def alcanzable() -> bool:
    """¿Responde algo la dirección de la API? (cualquier respuesta HTTP cuenta; no envía nada)."""
    try:
        requests.get(_base(), timeout=(TIEMPO_CONEXION, TIEMPO_CONEXION), allow_redirects=False)
    except requests.RequestException:
        return False
    return True
