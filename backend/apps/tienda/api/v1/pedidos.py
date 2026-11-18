"""API de pedidos del cliente de la tienda (con sesión; cada cliente ve solo los suyos)."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.tienda import carrito, cupones, garantias_cliente, pedidos, transferencias
from apps.tienda.exceptions import CuponInvalido
from apps.tienda.pedidos import DatosComprobante

from .compra import CarritoEntrada, _Compra
from .cuenta import TAG

TAM_PAGINA = 10
MAX_PAGINA = 30


class ComprobanteEntrada(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=["03", "01"], default="03")
    documento_tipo = serializers.ChoiceField(
        choices=["DNI", "RUC", "CE", "PASAPORTE"], required=False, allow_blank=True, default=""
    )
    documento_numero = serializers.CharField(
        max_length=20, required=False, allow_blank=True, default=""
    )
    nombre = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    direccion_fiscal = serializers.CharField(
        max_length=250, required=False, allow_blank=True, default=""
    )


def datos_de(d: dict) -> DatosComprobante:
    """El comprobante pedido; sin datos, una boleta sin documento."""
    return DatosComprobante(
        d.get("tipo", "03"),
        d.get("documento_tipo", ""),
        d.get("documento_numero", ""),
        d.get("nombre", ""),
        d.get("direccion_fiscal", ""),
    )


class PedidoEntrada(CarritoEntrada):
    modalidad = serializers.ChoiceField(choices=["ENVIO", "RECOJO"])
    direccion = serializers.IntegerField(min_value=1, required=False)
    punto = serializers.IntegerField(min_value=1, required=False)
    comprobante = ComprobanteEntrada(required=False)
    clave_idempotencia = serializers.UUIDField()
    cupon = serializers.CharField(max_length=40, required=False, allow_blank=True)
    pago = serializers.ChoiceField(choices=["COMPLETO", "ADELANTO"], required=False)
    metodo = serializers.ChoiceField(choices=["CULQI", "TRANSFERENCIA"], required=False)
    cuenta_transferencia = serializers.IntegerField(min_value=1, required=False)


class GarantiasView(_Compra):
    """«Mis garantías»: la garantía de cada producto que el cliente ya recibió o va a recibir."""

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        cuenta, _ = self.sesion(request)
        return Response({"results": garantias_cliente.de_cuenta(cuenta)})


class PedidosView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        cuenta, _ = self.sesion(request)
        try:
            pagina = max(int(request.query_params.get("page", 1)), 1)
            tam = min(max(int(request.query_params.get("page_size", TAM_PAGINA)), 1), MAX_PAGINA)
        except ValueError:
            pagina, tam = 1, TAM_PAGINA
        consulta = pedidos._pedidos(cuenta.organizacion_id).filter(cuenta=cuenta).order_by("-id")
        total = consulta.count()
        filas = consulta[(pagina - 1) * tam : pagina * tam]
        return Response(
            {
                "count": total,
                "page": pagina,
                "paginas": max((total + tam - 1) // tam, 1),
                "results": [pedidos.pedido_salida(p, detalle=False) for p in filas],
            }
        )

    @extend_schema(tags=TAG, request=PedidoEntrada, responses={201: dict, 200: dict})
    def post(self, request):
        cuenta, _ = self.sesion(request)
        entrada = PedidoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        codigo = (datos.get("cupon") or "").strip()
        if codigo:
            cupones.exigir_sin_bloqueo(cuenta.pk)  # demasiados intentos fallidos: 429
        try:
            pedido, creado = pedidos.crear_pedido(
                cuenta,
                self.contexto(),
                carrito.normalizar(datos["lineas"]),
                modalidad=datos["modalidad"],
                direccion_id=datos.get("direccion"),
                punto_id=datos.get("punto"),
                comprobante=datos_de(datos.get("comprobante", {})),
                clave=datos["clave_idempotencia"],
                cupon=codigo,
                pago=datos.get("pago", "COMPLETO"),
                metodo=datos.get("metodo", "CULQI"),
                cuenta_transferencia_id=datos.get("cuenta_transferencia"),
            )
        except CuponInvalido:
            cupones.anotar_fallo(cuenta.pk)
            raise
        return Response(pedidos.pedido_salida(pedido), status=201 if creado else 200)


class PedidoView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, numero: str):
        cuenta, _ = self.sesion(request)
        return Response(pedidos.pedido_salida(pedidos.pedido_de(cuenta, numero)))


class VoucherEntrada(serializers.Serializer):
    imagen = serializers.ImageField(allow_empty_file=False)
    operacion = serializers.CharField(max_length=40, required=False, allow_blank=True)


class VoucherView(_Compra):
    """El cliente sube la foto de su comprobante de transferencia."""

    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(tags=TAG, request=VoucherEntrada, responses={200: dict})
    def post(self, request, numero: str):
        cuenta, _ = self.sesion(request)
        entrada = VoucherEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        pedido = transferencias.subir_voucher(cuenta, numero, d["imagen"], d.get("operacion", ""))
        return Response(pedidos.pedido_salida(pedido))


class CancelarPedidoView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def post(self, request, numero: str):
        cuenta, _ = self.sesion(request)
        return Response(pedidos.pedido_salida(pedidos.cancelar(cuenta, numero)))
