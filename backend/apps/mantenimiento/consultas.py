"""Consulta de DNI (RENIEC) y RUC (SUNAT) a través de Decolecta.

* El token vive solo en el entorno (``DECOLECTA_TOKEN``): nunca en el código ni en los logs.
* Se valida el formato ANTES de llamar, para no gastar cuota con números imposibles.
* Toda llamada lleva timeout; los fallos del proveedor se traducen a errores controlados que no
  revelan detalles internos.
* El resultado se guarda unas horas en caché: repetir una consulta no consume cuota.
"""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from . import cuota
from .exceptions import ConsultaNoConfigurada, DocumentoNoEncontrado, ServicioConsultaNoDisponible
from .validators import validar_documento

logger = logging.getLogger(__name__)

TTL_CACHE_SEGUNDOS = 6 * 60 * 60
RUTAS = {"DNI": "/v1/reniec/dni", "RUC": "/v1/sunat/ruc"}


def _pedir(tipo: str, numero: str) -> dict:
    token = settings.DECOLECTA_TOKEN
    if not token:
        raise ConsultaNoConfigurada()
    cuota.exigir_disponible()
    try:
        respuesta = requests.get(
            f"{settings.DECOLECTA_URL.rstrip('/')}{RUTAS[tipo]}",
            params={"numero": numero},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=settings.DECOLECTA_TIMEOUT,
        )
    except requests.RequestException:
        logger.warning("consulta_documento_sin_respuesta", extra={"tipo": tipo})
        raise ServicioConsultaNoDisponible() from None
    cuota.registrar_uso()  # la consulta llegó al proveedor: gasta cuota aunque no encuentre nada
    if respuesta.status_code in (400, 404, 422):
        raise DocumentoNoEncontrado()
    if respuesta.status_code in (401, 403):
        logger.error("consulta_documento_token_rechazado", extra={"estado": respuesta.status_code})
        raise ServicioConsultaNoDisponible()
    if respuesta.status_code != 200:
        logger.warning(
            "consulta_documento_error", extra={"tipo": tipo, "estado": respuesta.status_code}
        )
        raise ServicioConsultaNoDisponible()
    try:
        datos = respuesta.json()
    except ValueError:
        raise ServicioConsultaNoDisponible() from None
    if not isinstance(datos, dict) or not datos:
        raise DocumentoNoEncontrado()
    return datos


def _texto(datos: dict, clave: str) -> str:
    return str(datos.get(clave) or "").strip()


def _normalizar_dni(numero: str, datos: dict) -> dict:
    nombres = _texto(datos, "first_name")
    apellidos = " ".join(
        parte
        for parte in (_texto(datos, "first_last_name"), _texto(datos, "second_last_name"))
        if parte
    )
    if not (nombres or apellidos):
        raise DocumentoNoEncontrado()
    return {
        "numero": numero,
        "nombres": nombres,
        "apellidos": apellidos,
        "nombre_completo": _texto(datos, "full_name") or f"{apellidos} {nombres}".strip(),
    }


def _normalizar_ruc(numero: str, datos: dict) -> dict:
    razon_social = _texto(datos, "razon_social")
    if not razon_social:
        raise DocumentoNoEncontrado()
    zona = " - ".join(
        p
        for p in (
            _texto(datos, "distrito"),
            _texto(datos, "provincia"),
            _texto(datos, "departamento"),
        )
        if p
    )
    direccion = _texto(datos, "direccion")
    estado, condicion = _texto(datos, "estado"), _texto(datos, "condicion")
    return {
        "numero": numero,
        "razon_social": razon_social,
        "direccion": ", ".join(p for p in (direccion, zona) if p),
        "estado": estado,
        "condicion": condicion,
        "es_activo": estado.upper() == "ACTIVO" and condicion.upper() == "HABIDO",
    }


def consultar(tipo: str, numero: str) -> dict:
    """Datos públicos de un DNI o RUC. ``tipo`` es ``DNI`` o ``RUC``."""
    tipo = tipo.upper()
    validar_documento(tipo, numero)  # ValidationError → 400, sin gastar cuota
    clave = f"consulta:{tipo}:{numero}"
    guardado = cache.get(clave)
    if guardado is not None:
        return guardado
    datos = _pedir(tipo, numero)
    resultado = (_normalizar_dni if tipo == "DNI" else _normalizar_ruc)(numero, datos)
    cache.set(clave, resultado, TTL_CACHE_SEGUNDOS)
    return resultado
