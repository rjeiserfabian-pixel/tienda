import re
import uuid

from . import contexto_peticion
from .logging import establecer_request_id, restablecer_request_id
from .tenant import limpiar_contexto
from .utils.red import ip_cliente

_REQUEST_ID_VALIDO = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Asigna un ``request_id`` a cada petición (acepta ``X-Request-ID`` válido)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        entrante = request.headers.get("X-Request-ID", "")
        request_id = entrante if _REQUEST_ID_VALIDO.match(entrante) else uuid.uuid4().hex
        request.request_id = request_id
        token = establecer_request_id(request_id)
        try:
            respuesta = self.get_response(request)
        finally:
            restablecer_request_id(token)
        respuesta["X-Request-ID"] = request_id
        return respuesta


class LimpiarContextoTenantMiddleware:
    """Garantiza que el contexto de tenant nunca se filtre entre peticiones.

    La autenticación (Fase 2) lo establece una vez identificado el usuario; aquí
    solo se asegura un inicio y un final limpios.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limpiar_contexto()
        try:
            return self.get_response(request)
        finally:
            limpiar_contexto()


class ContextoPeticionMiddleware:
    """Expone IP (respetando ``NUM_PROXIES``) y user-agent a servicios y auditoría."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tokens = contexto_peticion.establecer(
            ip_cliente(request), request.headers.get("User-Agent", "")[:300]
        )
        try:
            return self.get_response(request)
        finally:
            contexto_peticion.restablecer(tokens)


class CabecerasApiMiddleware:
    """Cabeceras de seguridad para las respuestas de la API (JSON, nunca HTML).

    La política es la más estricta posible: una respuesta de la API no carga recursos ni
    se incrusta. La documentación Swagger (solo si está habilitada) queda fuera.
    """

    RUTAS_EXCLUIDAS = ("/api/v1/docs/", "/api/v1/schema/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        respuesta = self.get_response(request)
        ruta = request.path
        if ruta.startswith("/api/") and not ruta.startswith(self.RUTAS_EXCLUIDAS):
            respuesta.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
            respuesta.setdefault("Cache-Control", "no-store")  # nada sensible queda en cachés
            respuesta.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
            respuesta.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return respuesta
