"""Salud, formato uniforme de errores, request_id y documentación OpenAPI."""

import pytest
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.exceptions import ContextoTenantNoDefinido
from apps.core.manejador_errores import manejador_excepciones

pytestmark = pytest.mark.django_db


def test_salud_responde_ok_sin_autenticacion(client):
    respuesta = client.get("/api/v1/salud/")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok", "base_datos": True, "cache": True}


def test_request_id_se_genera_y_se_respeta(client):
    generado = client.get("/api/v1/salud/")
    assert len(generado["X-Request-ID"]) == 32

    propio = client.get("/api/v1/salud/", HTTP_X_REQUEST_ID="mi-trazo-123456")
    assert propio["X-Request-ID"] == "mi-trazo-123456"

    malicioso = client.get("/api/v1/salud/", HTTP_X_REQUEST_ID="a b\r\nSet-Cookie: x")
    assert malicioso["X-Request-ID"] != "a b\r\nSet-Cookie: x"


def test_openapi_esta_disponible(client):
    respuesta = client.get("/api/v1/schema/")
    assert respuesta.status_code == 200
    assert b"/api/v1/salud/" in respuesta.content


def _contexto():
    return {"view": APIView()}


def test_error_de_dominio_tiene_formato_uniforme():
    respuesta = manejador_excepciones(ContextoTenantNoDefinido(), _contexto())
    assert respuesta.status_code == 403
    cuerpo = respuesta.data["error"]
    assert cuerpo["codigo"] == "contexto_tenant_no_definido"
    assert {"codigo", "mensaje", "request_id"} <= cuerpo.keys()


def test_error_de_validacion_incluye_detalle():
    respuesta = manejador_excepciones(ValidationError({"ruc": ["inválido"]}), _contexto())
    assert respuesta.status_code == 400
    assert respuesta.data["error"]["codigo"] == "validacion"
    assert respuesta.data["error"]["detalle"] == {"ruc": ["inválido"]}


def test_throttle_conserva_retry_after():
    respuesta = manejador_excepciones(Throttled(wait=30), _contexto())
    assert respuesta.status_code == 429
    assert respuesta["Retry-After"] == "30"


def test_error_inesperado_no_filtra_detalles_internos(caplog):
    respuesta = manejador_excepciones(RuntimeError("password=secreta SELECT * FROM x"), _contexto())
    assert respuesta.status_code == 500
    assert "secreta" not in str(respuesta.data)
    assert any("Error no controlado" in r.message for r in caplog.records)


def test_ruta_protegida_exige_autenticacion(client):
    # Cualquier endpoint que no sea público debe responder 401 sin token.
    from rest_framework.permissions import IsAuthenticated

    class Protegida(APIView):
        permission_classes = [IsAuthenticated]

        def get(self, request):  # pragma: no cover - no debe alcanzarse
            raise AssertionError

    request = APIRequestFactory().get("/")
    assert Protegida.as_view()(request).status_code == 401
