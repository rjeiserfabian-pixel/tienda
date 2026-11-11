"""Manejador uniforme de errores para DRF.

Formato de error para el cliente::

    {"error": {"codigo": "...", "mensaje": "...", "detalle": ..., "request_id": "..."}}

Los detalles internos (trazas, SQL, rutas) nunca llegan al cliente: se registran
en el log con el ``request_id`` para poder rastrearlos.
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import ErrorDominio
from .logging import obtener_request_id

logger = logging.getLogger(__name__)


def _respuesta_error(status: int, codigo: str, mensaje: str, detalle=None) -> Response:
    cuerpo = {"codigo": codigo, "mensaje": mensaje, "request_id": obtener_request_id()}
    if detalle is not None:
        cuerpo["detalle"] = detalle
    return Response({"error": cuerpo}, status=status)


def manejador_excepciones(exc, context):
    """Convierte cualquier excepción en una respuesta de error uniforme."""
    if isinstance(exc, ErrorDominio):
        respuesta = _respuesta_error(exc.status_code, exc.codigo, exc.mensaje, exc.detalle)
        for cabecera, valor in exc.cabeceras.items():
            respuesta[cabecera] = valor
        return respuesta

    if isinstance(exc, DjangoValidationError):
        detalle = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
        return _respuesta_error(400, "validacion", "Los datos enviados no son válidos.", detalle)

    if isinstance(exc, Http404):
        return _respuesta_error(404, "no_encontrado", "El recurso solicitado no existe.")

    if isinstance(exc, DjangoPermissionDenied):
        return _respuesta_error(403, "permiso_denegado", "No tiene permiso para esta operación.")

    respuesta = drf_exception_handler(exc, context)
    if respuesta is not None:
        mensaje = "No se pudo procesar la solicitud."
        codigo = getattr(getattr(exc, "detail", None), "code", None) or "error"
        if isinstance(exc, drf_exceptions.ValidationError):
            mensaje = "Los datos enviados no son válidos."
            codigo = "validacion"
        elif isinstance(exc, drf_exceptions.Throttled):
            mensaje = "Demasiadas solicitudes. Intente nuevamente en unos instantes."
        elif isinstance(exc, drf_exceptions.APIException) and not isinstance(
            exc.detail, (list, dict)
        ):
            mensaje = str(exc.detail)
        detalle = respuesta.data if isinstance(exc, drf_exceptions.ValidationError) else None
        nueva = _respuesta_error(respuesta.status_code, str(codigo), mensaje, detalle)
        for cabecera, valor in respuesta.items():
            if cabecera.lower() in {"retry-after", "www-authenticate"}:
                nueva[cabecera] = valor
        return nueva

    # Error no controlado: se registra con contexto y se responde de forma genérica.
    view = context.get("view")
    logger.exception(
        "Error no controlado", extra={"vista": view.__class__.__name__ if view else None}
    )
    return _respuesta_error(500, "error_interno", "Ocurrió un error interno. Intente más tarde.")
