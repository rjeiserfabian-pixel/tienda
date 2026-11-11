"""Antigüedad del stock: configuración por empresa y aviso en la pantalla de venta."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.throttles import ApiAutenticadaThrottle, MostradorThrottle
from apps.inventario import antiguedad
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Estado
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["inventario"]
MAX_ITEMS = 50


class ConfiguracionEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    dias = serializers.IntegerField(min_value=1, max_value=3650)


class ConfiguracionAntiguedadView(APIView):
    """Cuántos días tiene que llevar guardado el stock para considerarlo antiguo."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [ApiAutenticadaThrottle]
    requiere_empresa = True
    permisos_por_accion = {"get": "INVENTARIO.VER", "patch": "INVENTARIO.CONFIGURAR"}

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa_id = empresa_declarada(request, self)
        if not Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).exists():
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return Response(
            {"empresa": empresa_id, "dias": antiguedad.dias_para_considerar_antiguo(empresa_id)}
        )

    @extend_schema(tags=TAG, request=ConfiguracionEntrada)
    @transaction.atomic
    def patch(self, request):
        entrada = ConfiguracionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        empresa = Empresa.objects.filter(
            pk=entrada.validated_data["empresa"], estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        fila, _ = (
            ConfiguracionEmpresa.objects.sin_ambito()
            .select_for_update()
            .get_or_create(empresa=empresa)
        )
        antes = fila.dias_stock_antiguo
        fila.dias_stock_antiguo = entrada.validated_data["dias"]
        fila.save()
        registrar(
            "inventario.antiguedad_configurada",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen="Días para considerar antiguo el stock cambiados",
            detalle={"antes": antes, "dias": fila.dias_stock_antiguo},
        )
        from django.core.cache import cache

        cache.delete(f"inventario:antiguo:{empresa.pk}")
        return Response({"empresa": empresa.pk, "dias": fila.dias_stock_antiguo})


class AvisoDeVentaView(APIView):
    """Para el carrito del mostrador: qué productos tienen unidades antiguas en el almacén.

    ``?items=empresa:almacen:producto,…`` (hasta 50). Solo devuelve los que pasan el umbral y nunca
    costos: es una nota para que el vendedor despache primero lo más antiguo.
    """

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    throttle_classes = [MostradorThrottle]
    permiso_requerido = "VENTAS.VENDER"

    def _items(self, request) -> list[tuple[int, int, int]]:
        crudo = request.query_params.get("items", "")
        items: list[tuple[int, int, int]] = []
        for parte in [p for p in crudo.split(",") if p.strip()]:
            try:
                empresa, almacen, producto = (int(x) for x in parte.split(":"))
            except ValueError:
                raise ValidationError({"items": "Use empresa:almacén:producto."}) from None
            if min(empresa, almacen, producto) < 1:
                raise ValidationError({"items": "Los códigos deben ser positivos."})
            items.append((empresa, almacen, producto))
        if len(items) > MAX_ITEMS:
            raise ValidationError({"items": f"Hasta {MAX_ITEMS} productos por consulta."})
        return list(dict.fromkeys(items))

    def empresas_de_la_operacion(self, request):
        return sorted({e for e, _, _ in self._items(request)})

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("items", str, description="empresa:almacen:producto,…")],
        responses={200: dict},
    )
    def get(self, request):
        items = self._items(request)
        avisos = antiguedad.aviso_de_venta(items) if items else []
        respuesta = Response(
            [{**a, "unidades_antiguas": str(a["unidades_antiguas"])} for a in avisos]
        )
        respuesta["Cache-Control"] = "private, max-age=30"
        return respuesta
