"""API de la compra en la tienda: carrito y resumen con la entrega elegida.

El carrito sirve también sin cuenta (el navegador manda ids y cantidades y el servidor responde con
precios y disponibilidad vigentes). Quien tiene cuenta puede guardarlo para verlo en otro equipo.
Nada se guarda en caché: cada respuesta depende del stock y del cliente.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response

from apps.tienda import carrito, catalogo, cuentas, pedidos
from apps.tienda.exceptions import DatosInvalidos, PedidoInvalido
from apps.tienda.models import DireccionCuenta

from .cuenta import COOKIE, TAG, _Base


class LineaEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.IntegerField(min_value=1, max_value=carrito.MAX_CANTIDAD)


class CarritoEntrada(serializers.Serializer):
    lineas = LineaEntrada(many=True, allow_empty=True, max_length=carrito.MAX_LINEAS * 2)


class _Compra(_Base):
    def contexto(self) -> catalogo.Contexto:
        self.organizacion_id()  # 503 si la tienda está cerrada
        return catalogo.contexto()

    def sesion_opcional(self, request):
        """La cuenta si hay sesión válida; si no, ``None`` (también compran los invitados)."""
        encontrada = cuentas.cuenta_de_sesion(request.COOKIES.get(COOKIE, ""))
        if encontrada is None or encontrada[0].organizacion_id != self.organizacion_id():
            return None
        return encontrada[0]


class CalcularView(_Compra):
    @extend_schema(tags=TAG, request=CarritoEntrada, responses={200: dict})
    def post(self, request):
        entrada = CarritoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        lineas = carrito.normalizar(entrada.validated_data["lineas"])
        return Response(carrito.calcular(self.contexto(), lineas))


class CarritoGuardadoView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        cuenta, _ = self.sesion(request)
        lineas = carrito.normalizar(carrito.guardado(cuenta))
        return Response(carrito.calcular(self.contexto(), lineas))

    @extend_schema(tags=TAG, request=CarritoEntrada, responses={200: dict})
    def put(self, request):
        cuenta, _ = self.sesion(request)
        entrada = CarritoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        lineas = carrito.normalizar(entrada.validated_data["lineas"])
        carrito.guardar(cuenta, lineas)
        return Response(carrito.calcular(self.contexto(), lineas))


class CotizarEntrada(CarritoEntrada):
    modalidad = serializers.ChoiceField(choices=["ENVIO", "RECOJO"], required=False)
    ubigeo = serializers.RegexField(r"^\d{6}$", required=False)
    direccion = serializers.IntegerField(min_value=1, required=False)
    punto = serializers.IntegerField(min_value=1, required=False)
    comprobante = serializers.DictField(required=False)


class CotizarView(_Compra):
    @extend_schema(tags=TAG, request=CotizarEntrada, responses={200: dict})
    def post(self, request):
        entrada = CotizarEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        ubigeo = datos.get("ubigeo", "")
        cuenta = self.sesion_opcional(request)
        if datos.get("direccion"):
            if cuenta is None:
                raise DatosInvalidos("Ingresa a tu cuenta para usar una dirección guardada.")
            direccion = (
                DireccionCuenta.objects.sin_ambito()
                .filter(pk=datos["direccion"], cuenta=cuenta)
                .first()
            )
            if direccion is None:
                raise DatosInvalidos("No encontramos esa dirección.")
            ubigeo = direccion.ubigeo
        resumen = carrito.resumen_de_compra(
            self.contexto(),
            carrito.normalizar(datos["lineas"]),
            modalidad=datos.get("modalidad"),
            ubigeo=ubigeo,
            punto_id=datos.get("punto"),
        )
        resumen["totales"], resumen["totales_error"] = None, None
        if datos.get("modalidad") and resumen["entrega"]["valida"] and resumen["puede_comprar"]:
            from .pedidos import datos_de

            try:
                resumen["totales"] = pedidos.totales_exactos(
                    self.contexto(),
                    carrito.normalizar(datos["lineas"]),
                    modalidad=datos["modalidad"],
                    ubigeo=ubigeo,
                    punto_id=datos.get("punto"),
                    comprobante=datos_de(datos.get("comprobante", {})),
                )
            except PedidoInvalido as error:
                resumen["totales_error"] = error.mensaje
        resumen["cuenta"] = {
            "autenticada": cuenta is not None,
            "correo_verificado": bool(cuenta and cuenta.verificada),
        }
        return Response(resumen)
