from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventario import consulta_precios
from apps.seguridad.permissions import PermisoRBAC

VER_PRODUCTOS = "MANTENIMIENTO.PRODUCTOS.VER"


class ConsultaPreciosView(APIView):
    """Consulta rápida para el vendedor: ``?q=`` nombre, código o código de barras.

    Devuelve hasta 10 productos activos con sus precios por lista, el stock por almacén de las
    empresas que la persona puede ver y la ubicación. No incluye costos. Si ``q`` coincide
    exactamente con un código (por ejemplo, un escáner), devuelve solo ese producto.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER_PRODUCTOS

    def empresas_de_la_operacion(self, request):
        return [None]  # el catálogo es de la organización; el stock se filtra por permisos

    @extend_schema(
        tags=["inventario"],
        parameters=[OpenApiParameter("q", str, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        datos = consulta_precios.consultar(request.user, request.query_params.get("q", ""))
        respuesta = Response(datos)
        respuesta["Cache-Control"] = "no-store"
        return respuesta
