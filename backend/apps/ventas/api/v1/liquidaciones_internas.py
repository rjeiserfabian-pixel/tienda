"""Liquidación interna: lo que se deben las dos empresas por sus ventas internas.

Lo pendiente por local, cómo liquidarlo (una transferencia entre las cajas de las dos empresas),
el historial y cómo anular. El permiso se exige en las DOS empresas: se mueve dinero de una a otra.
"""

import json

from django.db.models import Q
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditoria.servicios import registrar
from apps.caja.reportes import nombre_archivo
from apps.caja.servicios import saldo_de
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor
from apps.ventas import liquidacion_interna, reportes_internas
from apps.ventas.cuentas_web import LOCAL_WEB
from apps.ventas.models import LiquidacionInterna

from .serializers import AnulacionVentaEntrada
from .views import TAG, _empresa_activa, _entero, _nombre_empresa, _uno

PERMISO = "VENTAS.LIQUIDAR_INTERNA"
MONEDA = "PEN"


class PartidaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    fecha = serializers.DateField()
    motivo = serializers.CharField()
    motivo_nombre = serializers.CharField(source="get_motivo_display")
    deudora = serializers.SerializerMethodField()
    acreedora = serializers.SerializerMethodField()
    monto = serializers.DecimalField(max_digits=16, decimal_places=2)
    origen = serializers.CharField()
    origen_nombre = serializers.CharField(source="get_origen_display")
    # Una venta interna lleva su número y su venta; un cobro de la tienda, el número del pedido.
    venta_interna = serializers.SerializerMethodField()
    venta = serializers.SerializerMethodField()
    referencia = serializers.SerializerMethodField()

    def get_venta_interna(self, partida) -> int | None:
        return partida.venta_interna.numero if partida.venta_interna_id else None

    def get_venta(self, partida) -> int | None:
        return partida.venta_interna.venta_id if partida.venta_interna_id else None

    def get_referencia(self, partida) -> str:
        """«Venta interna N° 000012» o «Pedido T-000123»: lo que se muestra como origen."""
        if partida.venta_interna_id:
            return f"Venta interna N° {partida.venta_interna.numero:06d}"
        return partida.referencia

    def get_deudora(self, partida) -> str:
        return _nombre_empresa(partida.empresa)

    def get_acreedora(self, partida) -> str:
        return _nombre_empresa(partida.acreedora)


class LiquidacionInternaSerializer(serializers.ModelSerializer):
    paga = serializers.SerializerMethodField()
    recibe = serializers.SerializerMethodField()
    desde = serializers.SerializerMethodField()
    hacia = serializers.SerializerMethodField()
    cantidad_partidas = serializers.SerializerMethodField()

    class Meta:
        model = LiquidacionInterna
        fields = [
            "id",
            "numero",
            "fecha",
            "empresa",
            "paga",
            "empresa_destino",
            "recibe",
            "local",
            "monto",
            "desde",
            "hacia",
            "referencia",
            "observacion",
            "cantidad_partidas",
            "estado",
            "motivo_anulacion",
            "creado_en",
        ]
        read_only_fields = fields

    def get_paga(self, liquidacion) -> str:
        return _nombre_empresa(liquidacion.empresa)

    def get_recibe(self, liquidacion) -> str:
        return _nombre_empresa(liquidacion.empresa_destino)

    def get_desde(self, liquidacion) -> str:
        t = liquidacion.transferencia
        return t.cuenta_origen.nombre if t else ""

    def get_hacia(self, liquidacion) -> str:
        t = liquidacion.transferencia
        return t.cuenta_destino.nombre if t else ""

    def get_cantidad_partidas(self, liquidacion) -> int:
        return len(liquidacion.partidas.all())


class LiquidacionInternaDetalleSerializer(LiquidacionInternaSerializer):
    partidas = PartidaSerializer(many=True, read_only=True)

    class Meta(LiquidacionInternaSerializer.Meta):
        fields = [*LiquidacionInternaSerializer.Meta.fields, "partidas"]
        read_only_fields = fields


def _detalle(pk: int) -> dict:
    """La liquidación con sus partidas, lista para responder (se lee de nuevo, ya guardada)."""
    liquidacion = (
        LiquidacionInterna.objects.select_related(
            "empresa",
            "empresa_destino",
            "transferencia__cuenta_origen",
            "transferencia__cuenta_destino",
        )
        .prefetch_related("partidas__empresa", "partidas__acreedora", "partidas__venta_interna")
        .get(pk=pk)
    )
    return json.loads(
        json.dumps(LiquidacionInternaDetalleSerializer(liquidacion).data, default=str)
    )


class LiquidarEntrada(serializers.Serializer):
    pagadora = serializers.IntegerField(min_value=1)
    receptora = serializers.IntegerField(min_value=1)
    local = serializers.CharField(max_length=60, allow_blank=True)
    cuenta_origen = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cuenta_destino = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)


def _cuenta(cuenta: CuentaFinanciera | None) -> dict | None:
    if cuenta is None:
        return None
    return {"id": cuenta.pk, "nombre": cuenta.nombre, "tipo": cuenta.tipo}


def _cuentas_de(empresa: Empresa) -> list[dict]:
    """Las cajas y cuentas en soles entre las que se puede elegir, con su saldo."""
    return [
        {**_cuenta(c), "saldo": f"{saldo_de(c):.2f}"}
        for c in CuentaFinanciera.objects.sin_ambito()
        .filter(empresa=empresa, moneda=MONEDA, estado=EstadoRegistro.ACTIVO)
        .exclude(rol_caja=CuentaFinanciera.RolCaja.CAJA_CHICA)
        .order_by("tipo", "nombre")
    ]


def pendiente_a_dict(p: liquidacion_interna.Pendiente) -> dict:
    """Un pendiente listo para la pantalla, con las cuentas propuestas y las elegibles."""
    es_web = p.local == LOCAL_WEB
    if es_web:
        origen, destino, motivo = liquidacion_interna.cuentas_sugeridas_web(p.pagadora, p.receptora)
    else:
        origen, destino, motivo = liquidacion_interna.cuentas_sugeridas(
            p.pagadora, p.receptora, p.sucursal
        )
    return {
        "local": p.local,
        "origen": "COBRO_TIENDA" if es_web else "VENTA_INTERNA",
        "origen_nombre": "Cobros de la tienda virtual" if es_web else "",
        "pagadora": p.pagadora.pk,
        "pagadora_nombre": _nombre_empresa(p.pagadora),
        "receptora": p.receptora.pk,
        "receptora_nombre": _nombre_empresa(p.receptora),
        "monto": f"{p.monto:.2f}",
        "debe_pagadora": f"{p.debe_pagadora:.2f}",
        "debe_receptora": f"{p.debe_receptora:.2f}",
        "cuenta_origen": _cuenta(origen),
        "cuenta_destino": _cuenta(destino),
        "motivo_cuentas": motivo,
        "cuentas_pagadora": _cuentas_de(p.pagadora),
        "cuentas_receptora": _cuentas_de(p.receptora),
        "partidas": PartidaSerializer(p.partidas, many=True).data,
    }


class LiquidacionInternaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Liquidaciones internas de una empresa (``?empresa=ID`` obligatorio en el listado)."""

    modelo = LiquidacionInterna
    serializer_class = LiquidacionInternaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": PERMISO,
        "retrieve": PERMISO,
        "pendientes": PERMISO,
        "create": PERMISO,
        "anular": PERMISO,
        "excel": PERMISO,
    }

    def get_serializer_class(self):
        if self.action == "retrieve":
            return LiquidacionInternaDetalleSerializer
        return LiquidacionInternaSerializer

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            ids = (
                LiquidacionInterna.objects.sin_ambito()
                .filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", "empresa_destino_id")
                .first()
            )
            if ids is None:
                raise Http404
            return list(ids)
        if self.action == "create":
            datos = request.data if hasattr(request.data, "get") else {}
            ids = [empresa_declarada(request, self)]
            for campo in ("pagadora", "receptora"):
                if str(datos.get(campo)).isdigit():
                    ids.append(int(datos[campo]))
            return list(dict.fromkeys(ids))
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related(
                "empresa",
                "empresa_destino",
                "transferencia__cuenta_origen",
                "transferencia__cuenta_destino",
            )
            .prefetch_related("partidas")
        )
        if self.action in ("retrieve", "excel"):
            queryset = queryset.prefetch_related(
                "partidas__empresa", "partidas__acreedora", "partidas__venta_interna"
            )
        if self.action == "list":
            empresa = _entero(self.request.query_params, "empresa")
            queryset = queryset.filter(Q(empresa_id=empresa) | Q(empresa_destino_id=empresa))
        return queryset.order_by("-fecha", "-id")

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    @action(detail=False, methods=["get"], url_path="pendientes")
    def pendientes(self, request):
        """Lo que falta liquidar, por local: solo donde la persona puede operar las dos empresas."""
        empresa = _empresa_activa(empresa_declarada(request, self))
        visibles = {
            e
            for e in motor.empresas_ids_de(request.user)
            if motor.tiene_permiso(request.user, PERMISO, e)
        }
        grupos = liquidacion_interna.pendientes(empresa.organizacion_id, empresa_ids=visibles)
        respuesta = Response([pendiente_a_dict(p) for p in grupos])
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    @extend_schema(
        tags=TAG,
        request=LiquidarEntrada,
        responses={201: LiquidacionInternaDetalleSerializer},
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = LiquidarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        mostrador = _empresa_activa(empresa_declarada(request, self))
        org = mostrador.organizacion_id
        pagadora = _uno(
            Empresa, v["pagadora"], "pagadora", "Elija la empresa que paga.", organizacion_id=org
        )
        receptora = _uno(
            Empresa,
            v["receptora"],
            "receptora",
            "Elija la empresa que recibe.",
            organizacion_id=org,
        )
        activa = {"estado": EstadoRegistro.ACTIVO}
        origen = _uno(
            CuentaFinanciera,
            v.get("cuenta_origen"),
            "cuenta_origen",
            "Elija una cuenta de la empresa que paga.",
            empresa=pagadora,
            **activa,
        )
        destino = _uno(
            CuentaFinanciera,
            v.get("cuenta_destino"),
            "cuenta_destino",
            "Elija una cuenta de la empresa que recibe.",
            empresa=receptora,
            **activa,
        )
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            liquidacion = liquidacion_interna.liquidar(
                pagadora=pagadora,
                receptora=receptora,
                local=v["local"],
                cuenta_origen=origen,
                cuenta_destino=destino,
                referencia=v.get("referencia", ""),
                observacion=v.get("observacion", ""),
            )
            return 201, _detalle(liquidacion.pk)

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

    @extend_schema(tags=TAG, responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path="excel")
    def excel(self, request, pk=None):
        """El informe de la liquidación: cada partida que se saldó y lo que quedó a pagar."""
        liquidacion = self.get_object()
        contenido = reportes_internas.liquidacion_excel(liquidacion)
        nombre = nombre_archivo(
            f"liquidacion-interna-{liquidacion.numero:06d}",
            liquidacion.empresa,
            f"{liquidacion.fecha:%Y%m%d}",
        )
        registrar(
            "ventas.liquidacion_interna_exportada",
            recurso_tipo="liquidacion_interna",
            recurso_id=liquidacion.pk,
            empresa_id=liquidacion.empresa_id,
            resumen=f"Informe de la liquidación interna N° {liquidacion.numero:06d} exportado",
            detalle={"archivo": nombre},
        )
        respuesta = HttpResponse(
            contenido,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta

    @extend_schema(
        tags=TAG,
        request=AnulacionVentaEntrada,
        responses={200: LiquidacionInternaDetalleSerializer},
    )
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Deshace la liquidación: la transferencia se anula y las partidas quedan pendientes."""
        liquidacion = self.get_object()
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        liquidacion_interna.anular_liquidacion(liquidacion, motivo=datos.validated_data["motivo"])
        return Response(_detalle(liquidacion.pk))
