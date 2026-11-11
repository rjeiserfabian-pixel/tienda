import logging

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class SaludView(APIView):
    """Verificación de vida para balanceador/monitoreo. No expone detalles internos."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={200: dict, 503: dict}, auth=[])
    def get(self, request):
        estado = {"base_datos": self._base_datos(), "cache": self._cache()}
        correcto = all(estado.values())
        return Response(
            {"estado": "ok" if correcto else "degradado", **estado},
            status=200 if correcto else 503,
        )

    @staticmethod
    def _base_datos() -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 - cualquier fallo de conexión es "no disponible"
            logger.exception("Falla de base de datos en /salud")
            return False

    @staticmethod
    def _cache() -> bool:
        try:
            cache.set("salud", "ok", 10)
            return cache.get("salud") == "ok"
        except Exception:  # noqa: BLE001
            logger.exception("Falla de caché en /salud")
            return False
