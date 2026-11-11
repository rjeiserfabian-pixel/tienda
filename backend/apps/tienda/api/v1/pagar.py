"""API del pago: cobrar un pedido con Culqi y recibir los avisos (webhook) de Culqi."""

import json
import logging

from django.http import JsonResponse
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import TiendaWebhookThrottle
from apps.tienda import catalogo, culqi, pagar, pedidos

from .compra import _Compra
from .cuenta import TAG

logger = logging.getLogger(__name__)

MAX_CUERPO_WEBHOOK = 20_000  # bytes: un aviso de Culqi pesa unos pocos KB


class PagarEntrada(serializers.Serializer):
    token = serializers.CharField(max_length=80)


class PagarView(_Compra):
    """Cobra el pedido. El monto es siempre el total guardado del pedido: el navegador solo manda
    el token que Culqi le dio (la tarjeta nunca pasa por este servidor)."""

    @extend_schema(tags=TAG, request=PagarEntrada, responses={200: dict})
    def post(self, request, numero: str):
        cuenta, _ = self.sesion(request)
        entrada = PagarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        self.contexto()  # 503 si la tienda está cerrada
        pedido = pagar.pagar(cuenta, numero, entrada.validated_data["token"])
        return Response(pedidos.pedido_salida(pedido))


def _id_de_cargo(evento) -> str:
    """El id del cargo que menciona el aviso (``data`` puede venir como objeto o como texto)."""
    if not isinstance(evento, dict):
        return ""
    datos = evento.get("data")
    if isinstance(datos, str):
        try:
            datos = json.loads(datos)
        except ValueError:
            return ""
    if isinstance(datos, dict):
        candidato = datos.get("id") or (
            datos.get("object") if isinstance(datos.get("object"), str) else ""
        )
    else:
        candidato = ""
    candidato = str(candidato)
    return candidato if candidato.startswith("chr_") else ""


class WebhookView(APIView):
    """Aviso de Culqi. No se confía en su contenido: solo se toma el id del cargo y se consulta a
    Culqi. Responde 200 salvo que Culqi no pueda confirmarse (entonces 503 para que reintente)."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TiendaWebhookThrottle]

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def post(self, request):
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_CUERPO_WEBHOOK:
            return JsonResponse({"ok": False}, status=413)
        ctx = catalogo.contexto()
        if ctx is None:
            return JsonResponse({"ok": True, "resultado": "tienda_cerrada"})
        cargo_id = _id_de_cargo(request.data if isinstance(request.data, dict) else None)
        if not cargo_id:
            return JsonResponse({"ok": True, "resultado": "ignorado"})
        try:
            resultado = pagar.reconciliar_cargo(ctx.organizacion_id, cargo_id)
        except culqi.ErrorCulqi:
            logger.warning("tienda_webhook_sin_confirmar")
            return JsonResponse({"ok": False}, status=503)
        logger.info("tienda_webhook", extra={"resultado": resultado})
        return JsonResponse({"ok": True, "resultado": resultado})
