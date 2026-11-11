"""API pública del estado de una orden y configuración de los avisos por WhatsApp."""

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle, ApiPublicaThrottle
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.servicio_tecnico import proveedores, publico
from apps.servicio_tecnico.models import ConfiguracionAvisos, EventoAviso
from apps.servicio_tecnico.notificaciones import CAMPO_DE_CONFIGURACION

TAG = ["servicio-tecnico"]
AVISOS = "SERVICIOS.AVISOS.GESTIONAR"


class EstadoPublicoView(APIView):
    """El estado de una orden para su cliente. Sin sesión: el enlace secreto es la llave.

    Un enlace que no existe responde siempre lo mismo (404), tenga el formato que tenga, y el
    número de consultas por IP está limitado. La respuesta no se guarda en cachés ni en buscadores.
    """

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ApiPublicaThrottle]

    @extend_schema(tags=TAG, auth=[], responses={200: dict})
    def get(self, request, token: str):
        orden = publico.orden_por_token(token)
        if orden is None:
            raise NotFound("No encontramos esa orden. Revisa el enlace o el código QR.")
        respuesta = Response(publico.estado_publico(orden))
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Robots-Tag"] = "noindex, nofollow"
        return respuesta


class ConfiguracionAvisosEntrada(serializers.Serializer):
    whatsapp_activo = serializers.BooleanField(required=False)
    aviso_recibido = serializers.BooleanField(required=False)
    aviso_presupuesto = serializers.BooleanField(required=False)
    aviso_listo = serializers.BooleanField(required=False)
    aviso_entregado = serializers.BooleanField(required=False)


def _estado_del_proveedor() -> dict:
    """Si el servidor puede mandar WhatsApp y qué le falta, evento por evento."""
    proveedor = proveedores.obtener()
    return {
        "nombre": proveedor.nombre,
        "configurado": proveedor.configurado(),
        "faltantes": {e: proveedor.falta(e) for e in EventoAviso.values if proveedor.falta(e)},
        "url_publica": settings.SERVICIO_TECNICO_URL_PUBLICA,
    }


def _datos(config: ConfiguracionAvisos | None) -> dict:
    por_defecto = ConfiguracionAvisos()
    c = config or por_defecto
    return {
        campo: getattr(c, campo) for campo in ("whatsapp_activo", *CAMPO_DE_CONFIGURACION.values())
    }


class ConfiguracionAvisosView(APIView):
    """Qué avisos automáticos manda cada empresa. Apagados hasta que alguien los enciende."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = AVISOS
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    def _empresa(self, request) -> Empresa:
        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise NotFound("Elija una empresa activa.")
        return empresa

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = self._empresa(request)
        config = ConfiguracionAvisos.objects.filter(empresa=empresa).first()
        return Response({"configuracion": _datos(config), "proveedor": _estado_del_proveedor()})

    @extend_schema(
        tags=TAG,
        request=ConfiguracionAvisosEntrada,
        parameters=[OpenApiParameter("empresa", int, required=True)],
    )
    def put(self, request):
        empresa = self._empresa(request)
        datos = ConfiguracionAvisosEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        config, _ = ConfiguracionAvisos.objects.get_or_create(
            empresa=empresa, defaults=datos.validated_data
        )
        antes = _datos(config)
        for campo, valor in datos.validated_data.items():
            setattr(config, campo, valor)
        config.save()
        despues = _datos(config)
        if antes != despues:
            registrar(
                "servicio_tecnico.avisos_configurados",
                recurso_tipo="configuracion_avisos",
                recurso_id=config.pk,
                empresa_id=empresa.pk,
                resumen="Configuración de los avisos por WhatsApp modificada",
                detalle={"antes": antes, "despues": despues},
            )
        return Response({"configuracion": despues, "proveedor": _estado_del_proveedor()})
