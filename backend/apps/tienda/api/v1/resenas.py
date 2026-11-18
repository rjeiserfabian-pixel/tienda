"""API de reseñas: lectura pública, la reseña propia del cliente y la gestión desde el panel."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import resenas
from apps.tienda.models import ConfiguracionResenas

from .compra import _Compra
from .publica import _Publica

TAG = ["tienda"]
GESTIONAR = "TIENDA.OFERTAS.GESTIONAR"


# ---------------------------------------------------------------------------
# Público
# ---------------------------------------------------------------------------
class ResenasPublicasView(_Publica):
    """Las reseñas publicadas de un producto, con su promedio."""

    ttl = 30

    @extend_schema(
        tags=TAG,
        auth=[],
        responses={200: dict},
        parameters=[
            OpenApiParameter("orden", str, description="recientes, mejores o peores."),
            OpenApiParameter("page", int),
        ],
    )
    def get(self, request, slug: str):
        ctx = self.contexto()

        def construir():
            producto = resenas.producto_publico(ctx, slug)
            return resenas.listar(producto.pk, request.query_params)

        return self.responder(request, construir)


# ---------------------------------------------------------------------------
# El cliente
# ---------------------------------------------------------------------------
class ResenaEntrada(serializers.Serializer):
    estrellas = serializers.IntegerField(min_value=1, max_value=5)
    titulo = serializers.CharField(max_length=resenas.MAX_TITULO, required=False, allow_blank=True)
    comentario = serializers.CharField(
        max_length=resenas.MAX_COMENTARIO, required=False, allow_blank=True
    )


class MiResenaView(_Compra):
    """La reseña del cliente de un producto: ver si puede opinar, guardarla o borrarla."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, slug: str):
        cuenta, _ = self.sesion(request)
        producto = resenas.producto_publico(self.contexto(), slug)
        return Response(resenas.estado_del_cliente(cuenta, producto.pk))

    @extend_schema(tags=TAG, request=ResenaEntrada, responses={200: dict})
    def put(self, request, slug: str):
        cuenta, _ = self.sesion(request)
        entrada = ResenaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        producto = resenas.producto_publico(self.contexto(), slug)
        resenas.guardar(
            cuenta,
            producto.pk,
            estrellas=d["estrellas"],
            titulo=d.get("titulo", ""),
            comentario=d.get("comentario", ""),
        )
        return Response(resenas.estado_del_cliente(cuenta, producto.pk))

    @extend_schema(tags=TAG, responses={200: dict})
    def delete(self, request, slug: str):
        cuenta, _ = self.sesion(request)
        producto = resenas.producto_publico(self.contexto(), slug)
        resenas.borrar_mia(cuenta, producto.pk)
        return Response(resenas.estado_del_cliente(cuenta, producto.pk))


# ---------------------------------------------------------------------------
# El panel
# ---------------------------------------------------------------------------
class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = {"get": GESTIONAR, "post": GESTIONAR, "patch": GESTIONAR}

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class ResenasAdminView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(resenas.listar_admin(request.user.organizacion_id, request.query_params))


class OcultarEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=resenas.MAX_MOTIVO, required=False, allow_blank=True)


class OcultarResenaView(_Admin):
    @extend_schema(tags=TAG, request=OcultarEntrada, responses={200: dict})
    def post(self, request, pk: int):
        entrada = OcultarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        return Response(
            resenas.ocultar(
                request.user.organizacion_id,
                pk,
                usuario=request.user,
                motivo=entrada.validated_data.get("motivo", ""),
            )
        )


class MostrarResenaView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request, pk: int):
        return Response(resenas.mostrar(request.user.organizacion_id, pk, usuario=request.user))


class RespuestaEntrada(serializers.Serializer):
    texto = serializers.CharField(
        max_length=resenas.MAX_RESPUESTA, required=False, allow_blank=True
    )


class ResponderResenaView(_Admin):
    @extend_schema(tags=TAG, request=RespuestaEntrada, responses={200: dict})
    def post(self, request, pk: int):
        entrada = RespuestaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        return Response(
            resenas.responder(
                request.user.organizacion_id,
                pk,
                usuario=request.user,
                texto=entrada.validated_data.get("texto", ""),
            )
        )


class ConfiguracionEntrada(serializers.Serializer):
    pedir_activo = serializers.BooleanField(required=False)
    pedir_dias = serializers.IntegerField(min_value=1, max_value=30, required=False)


def _config_de(organizacion_id: int) -> ConfiguracionResenas:
    existente = resenas.configuracion(organizacion_id)
    if existente is not None:
        return existente
    return ConfiguracionResenas.objects.sin_ambito().create(organizacion_id=organizacion_id)


class ConfiguracionResenasView(_Admin):
    """Si se pide la reseña por correo y a los cuántos días de entregar."""

    @staticmethod
    def _salida(c: ConfiguracionResenas) -> dict:
        return {"pedir_activo": c.pedir_activo, "pedir_dias": c.pedir_dias}

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(self._salida(_config_de(request.user.organizacion_id)))

    @extend_schema(tags=TAG, request=ConfiguracionEntrada, responses={200: dict})
    @transaction.atomic
    def patch(self, request):
        entrada = ConfiguracionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        config = _config_de(request.user.organizacion_id)
        for campo, valor in entrada.validated_data.items():
            setattr(config, campo, valor)
        config.save()
        return Response(self._salida(config))
