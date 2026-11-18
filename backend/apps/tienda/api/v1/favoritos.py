"""API del cliente: favoritos y «avísame cuando llegue» (con sesión de la tienda)."""

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.tienda import favoritos

from .compra import _Compra
from .cuenta import TAG


class FavoritosView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request):
        """Los ids (para pintar los corazones) y, con ``?productos=1``, las tarjetas."""
        cuenta, _ = self.sesion(request)
        salida = {"ids": favoritos.ids(cuenta), "avisos": favoritos.avisos_pedidos(cuenta)}
        if request.query_params.get("productos") == "1":
            salida["productos"] = favoritos.listar(cuenta, self.contexto())
        return Response(salida)


class FavoritoView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def put(self, request, producto_id: int):
        cuenta, _ = self.sesion(request)
        return Response({"ids": favoritos.agregar(cuenta, self.contexto(), producto_id)})

    @extend_schema(tags=TAG, responses={200: dict})
    def delete(self, request, producto_id: int):
        cuenta, _ = self.sesion(request)
        return Response({"ids": favoritos.quitar(cuenta, producto_id)})


class AvisoStockView(_Compra):
    @extend_schema(tags=TAG, responses={200: dict})
    def put(self, request, producto_id: int):
        cuenta, _ = self.sesion(request)
        return Response({"avisos": favoritos.pedir_aviso(cuenta, self.contexto(), producto_id)})

    @extend_schema(tags=TAG, responses={200: dict})
    def delete(self, request, producto_id: int):
        cuenta, _ = self.sesion(request)
        return Response({"avisos": favoritos.cancelar_aviso(cuenta, producto_id)})
