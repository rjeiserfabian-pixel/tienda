"""Panel: pedidos de la tienda (ver, avanzar de estado, notas y reintentar el comprobante)."""

from decimal import Decimal

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.throttles import ApiAutenticadaThrottle
from apps.seguridad.permissions import PermisoRBAC
from apps.tienda import gestion, reembolsos, series_pedido

TAG = ["tienda"]
VER = "TIENDA.PEDIDOS.VER"
GESTIONAR = "TIENDA.PEDIDOS.GESTIONAR"
REEMBOLSAR = "TIENDA.PEDIDOS.REEMBOLSAR"


class _Admin(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    permisos_por_accion = {"get": VER, "post": GESTIONAR}

    def empresas_de_la_operacion(self, request):
        return [None]  # el pedido es de la organización, no de una empresa

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response

    def organizacion(self, request) -> int:
        return request.user.organizacion_id


class PedidosView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(gestion.listar(self.organizacion(request), request.query_params))


class ResumenView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        return Response(gestion.resumen(self.organizacion(request)))


class PedidoView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, numero: str):
        return Response(gestion.detalle(gestion.pedido_de(self.organizacion(request), numero)))


class EstadoEntrada(serializers.Serializer):
    estado = serializers.CharField(max_length=24)
    nota = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    seguimiento = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )


class EstadoView(_Admin):
    @extend_schema(tags=TAG, request=EstadoEntrada, responses={200: dict})
    def post(self, request, numero: str):
        entrada = EstadoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        pedido = gestion.cambiar_estado(
            self.organizacion(request),
            numero,
            datos["estado"],
            nota=datos["nota"],
            seguimiento=datos["seguimiento"],
            usuario=request.user,
        )
        return Response(gestion.detalle(gestion.pedido_de(pedido.organizacion_id, numero)))


class NotaEntrada(serializers.Serializer):
    texto = serializers.CharField(max_length=500)


class NotaView(_Admin):
    @extend_schema(tags=TAG, request=NotaEntrada, responses={200: dict})
    def post(self, request, numero: str):
        entrada = NotaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        gestion.agregar_nota(
            self.organizacion(request),
            numero,
            entrada.validated_data["texto"],
            usuario=request.user,
        )
        return Response(gestion.detalle(gestion.pedido_de(self.organizacion(request), numero)))


class ReintentarComprobanteView(_Admin):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request, numero: str):
        gestion.reintentar_comprobante(self.organizacion(request), numero, usuario=request.user)
        return Response(gestion.detalle(gestion.pedido_de(self.organizacion(request), numero)))


class SerieEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    anterior = serializers.CharField(max_length=40)
    nueva = serializers.CharField(max_length=40)
    motivo = serializers.CharField(max_length=200)


class CambiarSerieView(_Admin):
    """El almacén tomó otra unidad: cambia la serie entregada (hasta el despacho)."""

    @extend_schema(tags=TAG, request=SerieEntrada, responses={200: dict})
    def post(self, request, numero: str):
        entrada = SerieEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        series_pedido.cambiar(
            self.organizacion(request),
            numero,
            d["linea"],
            anterior=d["anterior"],
            nueva=d["nueva"],
            motivo=d["motivo"],
            usuario=request.user,
        )
        return Response(gestion.detalle(gestion.pedido_de(self.organizacion(request), numero)))


class ReembolsoLineaEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class ReembolsoEntrada(serializers.Serializer):
    motivo_tipo = serializers.ChoiceField(choices=reembolsos.ReembolsoPedido.Motivo.choices)
    motivo = serializers.CharField(max_length=250)
    reingresa_stock = serializers.BooleanField(required=False, default=True)
    # Solo para devolver en parte un pedido ya entregado; sin él se devuelve todo.
    lineas = ReembolsoLineaEntrada(many=True, required=False, allow_null=True, max_length=50)


class _Reembolsar(_Admin):
    """Dinero real: exige su propio permiso crítico (distinto de gestionar pedidos)."""

    permisos_por_accion = {"get": REEMBOLSAR, "post": REEMBOLSAR}


class ReembolsoPlanView(_Reembolsar):
    """Qué pasaría exactamente si se reembolsa (no cambia nada)."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, numero: str):
        return Response(reembolsos.plan(self.organizacion(request), numero))


class ReembolsoView(_Reembolsar):
    @extend_schema(tags=TAG, request=ReembolsoEntrada, responses={200: dict})
    def post(self, request, numero: str):
        entrada = ReembolsoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        lineas = d.get("lineas")
        reembolsos.reembolsar(
            self.organizacion(request),
            numero,
            motivo_tipo=d["motivo_tipo"],
            motivo=d["motivo"],
            usuario=request.user,
            lineas=[{"linea": x["linea"], "cantidad": x["cantidad"]} for x in lineas]
            if lineas
            else None,
            reingresa_stock=d["reingresa_stock"],
        )
        return Response(gestion.detalle(gestion.pedido_de(self.organizacion(request), numero)))


class ReembolsoReintentarView(_Reembolsar):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request, numero: str):
        reembolsos.reintentar(self.organizacion(request), numero, usuario=request.user)
        return Response(gestion.detalle(gestion.pedido_de(self.organizacion(request), numero)))
