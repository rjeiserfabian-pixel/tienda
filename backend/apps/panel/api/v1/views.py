"""API del panel de Inicio: un solo pedido trae todos los bloques que la persona puede ver."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.caja.api.v1.conciliacion import _textos
from apps.core.throttles import ApiAutenticadaThrottle
from apps.organizacion.models import Empresa, Estado
from apps.panel import resumen
from apps.seguridad.permissions import _entero
from apps.seguridad.services import permisos_engine as motor


class InicioView(APIView):
    """Resumen de la empresa activa (``?empresa=ID``). Cada bloque exige su propio permiso."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ApiAutenticadaThrottle]

    @extend_schema(
        tags=["panel"],
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={200: dict},
    )
    def get(self, request):
        empresa_id = _entero(request.query_params.get("empresa"), "empresa")
        if empresa_id is None:
            raise ValidationError({"empresa": "Debe indicar la empresa."})
        empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
        # Sin acceso a esa empresa se responde igual que si no existiera.
        if empresa is None or not motor.permisos_de(request.user, empresa.pk).acceso:
            raise PermissionDenied("No tiene acceso a esa empresa.")
        respuesta = Response(_textos(resumen.resumen_inicio(request.user, empresa)))
        respuesta["Cache-Control"] = "no-store"
        return respuesta
