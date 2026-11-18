"""API del Libro de Reclamaciones, las páginas legales y las métricas de la tienda."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import cuentas, metricas, paginas, reclamos

from .cuenta import COOKIE, TAG, _Base
from .publica import _Publica

CONFIGURAR = "TIENDA.CONFIGURAR"
GESTIONAR_RECLAMOS = "TIENDA.PEDIDOS.GESTIONAR"
VER_METRICAS = "TIENDA.PEDIDOS.VER"


# ---------------------------------------------------------------------------
# Público: Libro de Reclamaciones y páginas legales
# ---------------------------------------------------------------------------
class LibroView(_Publica):
    """Los proveedores a quienes se puede reclamar y el plazo de respuesta."""

    ttl = 300

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request):
        ctx = self.contexto()
        return self.responder(request, lambda: reclamos.datos_del_libro(ctx.organizacion_id))


class ReclamoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    tipo = serializers.ChoiceField(choices=["RECLAMO", "QUEJA"])
    nombre = serializers.CharField(max_length=150)
    documento_tipo = serializers.ChoiceField(choices=["DNI", "RUC", "CE", "PASAPORTE"])
    documento_numero = serializers.CharField(max_length=20)
    domicilio = serializers.CharField(max_length=250)
    telefono = serializers.CharField(max_length=30, required=False, allow_blank=True)
    correo = serializers.CharField(max_length=150)
    menor_de_edad = serializers.BooleanField(required=False, default=False)
    apoderado = serializers.CharField(max_length=150, required=False, allow_blank=True)
    bien_tipo = serializers.ChoiceField(choices=["PRODUCTO", "SERVICIO"])
    monto = serializers.CharField(max_length=14, required=False, allow_blank=True, allow_null=True)
    bien_descripcion = serializers.CharField(max_length=300)
    pedido_numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    detalle = serializers.CharField(max_length=2000)
    pedido_consumidor = serializers.CharField(max_length=1000)


class RegistrarReclamoView(_Base):
    """Registra una hoja de reclamación. No exige cuenta (es un derecho del consumidor)."""

    @extend_schema(tags=TAG, request=ReclamoEntrada, responses={201: dict})
    def post(self, request):
        entrada = ReclamoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        encontrada = cuentas.cuenta_de_sesion(request.COOKIES.get(COOKIE, ""))
        cuenta = encontrada[0] if encontrada else None
        organizacion_id = self.organizacion_id()
        if cuenta is not None and cuenta.organizacion_id != organizacion_id:
            cuenta = None
        r = reclamos.crear(organizacion_id, dict(entrada.validated_data), cuenta=cuenta)
        return Response(
            {
                "numero": r.numero,
                "tipo": r.tipo,
                "fecha": r.creado_en.isoformat(),
                "vence_en": r.vence_en.isoformat(),
                "correo": r.correo,
            },
            status=201,
        )


class PaginaView(_Publica):
    ttl = 300

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request, slug: str):
        ctx = self.contexto()
        return self.responder(request, lambda: paginas.leer(ctx.organizacion_id, slug))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [None]  # es de la organización

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class _AdminReclamos(_Admin):
    permisos_por_accion = {"get": GESTIONAR_RECLAMOS, "post": GESTIONAR_RECLAMOS}


class ReclamosAdminView(_AdminReclamos):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(reclamos.listar(request.user.organizacion_id, request.query_params))


class ReclamoAdminView(_AdminReclamos):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, pk: int):
        return Response(reclamos.detalle(request.user.organizacion_id, pk))


class RespuestaEntrada(serializers.Serializer):
    texto = serializers.CharField(max_length=reclamos.MAX_RESPUESTA)


class ResponderReclamoView(_AdminReclamos):
    @extend_schema(tags=TAG, request=RespuestaEntrada, responses={200: dict})
    def post(self, request, pk: int):
        entrada = RespuestaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        return Response(
            reclamos.responder(
                request.user.organizacion_id,
                pk,
                usuario=request.user,
                texto=entrada.validated_data["texto"],
            )
        )


class ReenviarRespuestaView(_AdminReclamos):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request, pk: int):
        return Response(reclamos.reenviar_respuesta(request.user.organizacion_id, pk))


class _AdminPaginas(_Admin):
    permisos_por_accion = {"get": CONFIGURAR, "put": CONFIGURAR}


class PaginasAdminView(_AdminPaginas):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response({"paginas": paginas.listar_admin(request.user.organizacion_id)})


class PaginaEntrada(serializers.Serializer):
    contenido = serializers.CharField(
        max_length=paginas.MAX_CONTENIDO + 2000, allow_blank=True, trim_whitespace=False
    )
    publicada = serializers.BooleanField()


class PaginaAdminView(_AdminPaginas):
    @extend_schema(tags=TAG, request=PaginaEntrada, responses={200: dict})
    def put(self, request, slug: str):
        entrada = PaginaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        return Response(
            paginas.guardar(
                request.user.organizacion_id,
                slug,
                contenido=d["contenido"],
                publicada=d["publicada"],
            )
        )


class MetricasView(_Admin):
    permisos_por_accion = {"get": VER_METRICAS}

    @extend_schema(
        tags=TAG,
        responses={200: dict},
        parameters=[OpenApiParameter("dias", int, description="7, 30 o 90.")],
    )
    def get(self, request):
        try:
            dias = int(request.query_params.get("dias", 30))
        except ValueError:
            dias = 30
        return Response(metricas.resumen(request.user.organizacion_id, dias))
