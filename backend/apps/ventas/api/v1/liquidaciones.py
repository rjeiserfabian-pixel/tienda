"""Liquidación de tarjetas: lo pendiente en cada POS, el historial y cómo liquidar o anular."""

import json
from decimal import Decimal

from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.ventas import liquidaciones
from apps.ventas.models import LiquidacionTarjeta

from .serializers import AnulacionVentaEntrada
from .views import TAG, _empresa_activa, _entero, _uno

PERMISO = "VENTAS.LIQUIDAR_TARJETA"
DINERO = {"max_digits": 16, "decimal_places": 2}


class LiquidacionSerializer(serializers.ModelSerializer):
    cuenta_pos_nombre = serializers.CharField(source="cuenta_pos.nombre", read_only=True)
    cuenta_destino_nombre = serializers.CharField(source="cuenta_destino.nombre", read_only=True)
    moneda = serializers.CharField(source="cuenta_pos.moneda", read_only=True)

    class Meta:
        model = LiquidacionTarjeta
        fields = [
            "id",
            "numero",
            "fecha",
            "cuenta_pos",
            "cuenta_pos_nombre",
            "cuenta_destino",
            "cuenta_destino_nombre",
            "moneda",
            "bruto",
            "comision",
            "neto",
            "referencia",
            "observacion",
            "estado",
            "motivo_anulacion",
            "creado_en",
        ]
        read_only_fields = fields


class LiquidarEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    cuenta_pos = serializers.IntegerField(min_value=1)
    cuenta_destino = serializers.IntegerField(min_value=1)
    bruto = serializers.DecimalField(**DINERO)
    comision = serializers.DecimalField(required=False, **DINERO)
    fecha = serializers.DateField(required=False)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)


class LiquidacionViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Liquidaciones de tarjeta de una empresa (``?empresa=ID`` obligatorio)."""

    modelo = LiquidacionTarjeta
    serializer_class = LiquidacionSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": PERMISO,
        "pendientes": PERMISO,
        "create": PERMISO,
        "anular": PERMISO,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                LiquidacionTarjeta.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("cuenta_pos", "cuenta_destino")
        if self.action == "list":
            queryset = queryset.filter(empresa_id=_entero(self.request.query_params, "empresa"))
        return queryset.order_by("-fecha", "-id")

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    @action(detail=False, methods=["get"], url_path="pendientes")
    def pendientes(self, request):
        """Cada cuenta de POS con lo que falta liquidar."""
        empresa = _empresa_activa(empresa_declarada(request, self))
        filas = liquidaciones.pendientes(empresa)
        respuesta = Response([{**f, "saldo": f"{f['saldo']:.2f}"} for f in filas])
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    @extend_schema(
        tags=TAG,
        request=LiquidarEntrada,
        responses={201: LiquidacionSerializer},
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = LiquidarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        activa = {"estado": EstadoRegistro.ACTIVO}
        pos = _uno(
            CuentaFinanciera,
            v["cuenta_pos"],
            "cuenta_pos",
            "Elija la cuenta del POS.",
            empresa=empresa,
            **activa,
        )
        destino = _uno(
            CuentaFinanciera,
            v["cuenta_destino"],
            "cuenta_destino",
            "Elija el banco donde se depositó.",
            empresa=empresa,
            **activa,
        )
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            liquidacion = liquidaciones.liquidar_tarjeta(
                empresa=empresa,
                cuenta_pos=pos,
                cuenta_destino=destino,
                bruto=v["bruto"],
                comision=v.get("comision", Decimal("0")),
                fecha=v.get("fecha"),
                referencia=v.get("referencia", ""),
                observacion=v.get("observacion", ""),
            )
            nueva = LiquidacionTarjeta.objects.select_related("cuenta_pos", "cuenta_destino").get(
                pk=liquidacion.pk
            )
            return 201, json.loads(json.dumps(LiquidacionSerializer(nueva).data, default=str))

        codigo, contenido, repetida = ejecutar_idempotente(
            clave=clave,
            metodo=request.method,
            ruta=request.path,
            cuerpo=cuerpo,
            operacion=operacion,
        )
        respuesta = Response(contenido, status=codigo)
        if repetida:
            respuesta["Idempotency-Replayed"] = "true"
        return respuesta

    @extend_schema(tags=TAG, request=AnulacionVentaEntrada, responses={200: LiquidacionSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Deshace la liquidación: el dinero y la comisión vuelven a la cuenta del POS."""
        liquidacion = self.get_object()
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        liquidaciones.anular_liquidacion(liquidacion, motivo=datos.validated_data["motivo"])
        recargada = self.get_queryset().get(pk=liquidacion.pk)
        return Response(LiquidacionSerializer(recargada).data)
