"""API del traslado entre empresas: pasar mercadería de una empresa a la otra sin vender.

Se registra desde una pantalla propia en Almacén. El permiso se exige en las DOS empresas: se mueve
mercadería (y se anota una deuda) de una a otra. Se liquida junto con las ventas internas.
"""

import json
from decimal import Decimal

from django.db.models import Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import Almacen, Producto
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.ventas import traslados_empresas
from apps.ventas.models import VentaInterna

from .serializers import AnulacionVentaEntrada
from .views import TAG, _entero, _nombre_empresa

VER = "INVENTARIO.VER"
REGISTRAR = "INVENTARIO.TRASLADO_EMPRESAS.REGISTRAR"


class LineaTrasladoEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    series = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, max_length=2000
    )


class TrasladoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    almacen_origen = serializers.IntegerField(min_value=1)
    almacen_destino = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    observacion = serializers.CharField(max_length=200, required=False, allow_blank=True)
    lineas = serializers.ListField(child=LineaTrasladoEntrada(), min_length=1, max_length=200)


class LineaTrasladoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    producto = serializers.IntegerField(source="producto_id")
    descripcion = serializers.CharField()
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3)
    costo_unitario = serializers.DecimalField(max_digits=16, decimal_places=6)
    costo_total = serializers.DecimalField(max_digits=16, decimal_places=2)
    series = serializers.ListField(child=serializers.CharField())


class TrasladoSerializer(serializers.ModelSerializer):
    entrega = serializers.SerializerMethodField()
    recibe = serializers.SerializerMethodField()
    almacen_origen = serializers.SerializerMethodField()
    almacen_destino = serializers.SerializerMethodField()
    cantidad_lineas = serializers.SerializerMethodField()
    movimiento = serializers.SerializerMethodField()
    guia = serializers.SerializerMethodField()
    liquidado = serializers.SerializerMethodField()

    class Meta:
        model = VentaInterna
        fields = [
            "id",
            "numero",
            "fecha",
            "empresa",
            "entrega",
            "empresa_destino",
            "recibe",
            "almacen_origen",
            "almacen_destino",
            "total_costo",
            "observacion",
            "cantidad_lineas",
            "movimiento",
            "guia",
            "liquidado",
            "estado",
            "motivo_anulacion",
            "creado_en",
        ]
        read_only_fields = fields

    def get_entrega(self, i) -> str:
        return _nombre_empresa(i.empresa)

    def get_recibe(self, i) -> str:
        return _nombre_empresa(i.empresa_destino)

    def _primera(self, i):
        lineas = list(i.lineas.all())
        return lineas[0] if lineas else None

    def get_almacen_origen(self, i) -> str:
        ln = self._primera(i)
        return ln.almacen_origen.nombre if ln and ln.almacen_origen else ""

    def get_almacen_destino(self, i) -> str:
        ln = self._primera(i)
        return ln.almacen_destino.nombre if ln and ln.almacen_destino else ""

    def get_cantidad_lineas(self, i) -> int:
        return len(i.lineas.all())

    def get_movimiento(self, i) -> int | None:
        """El id de la salida en el Kardex: con él se pide la guía de remisión."""
        ln = self._primera(i)
        return ln.movimiento_salida_id if ln else None

    def get_guia(self, i) -> dict | None:
        if i.estado != VentaInterna.Estado.EMITIDO:
            return None
        guia = traslados_empresas.guia_vigente(i)
        return {"id": guia.pk, "numero_completo": guia.numero_completo} if guia else None

    def get_liquidado(self, i) -> bool:
        partidas = list(i.partidas.all())
        return bool(partidas) and all(p.liquidacion_id for p in partidas)


class TrasladoDetalleSerializer(TrasladoSerializer):
    lineas = LineaTrasladoSerializer(many=True, read_only=True)

    class Meta(TrasladoSerializer.Meta):
        fields = [*TrasladoSerializer.Meta.fields, "lineas"]
        read_only_fields = fields


def _leer(pk: int) -> dict:
    interna = (
        VentaInterna.objects.select_related("empresa", "empresa_destino")
        .prefetch_related("lineas__almacen_origen", "lineas__almacen_destino", "partidas")
        .get(pk=pk)
    )
    return json.loads(json.dumps(TrasladoDetalleSerializer(interna).data, default=str))


class TrasladoEmpresasViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Traslados de mercadería entre empresas (``?empresa=ID`` obligatorio en el listado)."""

    modelo = VentaInterna
    serializer_class = TrasladoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": REGISTRAR,
        "anular": REGISTRAR,
    }

    def get_serializer_class(self):
        return TrasladoDetalleSerializer if self.action == "retrieve" else TrasladoSerializer

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            ids = (
                VentaInterna.objects.sin_ambito()
                .filter(pk=self.kwargs["pk"], venta__isnull=True)
                .values_list("empresa_id", "empresa_destino_id")
                .first()
            )
            if ids is None:
                raise Http404
            return list(ids)
        if self.action == "create":
            datos = request.data if hasattr(request.data, "get") else {}
            ids = []
            for campo in ("almacen_origen", "almacen_destino"):
                if str(datos.get(campo)).isdigit():
                    empresa = (
                        Almacen.objects.sin_ambito()
                        .filter(pk=int(datos[campo]))
                        .values_list("empresa_id", flat=True)
                        .first()
                    )
                    if empresa is not None:
                        ids.append(empresa)
            return list(dict.fromkeys(ids)) or [empresa_declarada(request, self)]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(venta__isnull=True)
            .select_related("empresa", "empresa_destino")
            .prefetch_related("lineas__almacen_origen", "lineas__almacen_destino", "partidas")
        )
        if self.action == "list":
            empresa = _entero(self.request.query_params, "empresa")
            queryset = queryset.filter(Q(empresa_id=empresa) | Q(empresa_destino_id=empresa))
        return queryset.order_by("-fecha", "-id")

    @extend_schema(
        tags=TAG,
        request=TrasladoEntrada,
        responses={201: TrasladoDetalleSerializer},
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = TrasladoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        almacenes = {
            campo: Almacen.objects.select_related("empresa", "sucursal").filter(pk=v[campo]).first()
            for campo in ("almacen_origen", "almacen_destino")
        }
        for campo, almacen in almacenes.items():
            if almacen is None:
                raise ValidationError({campo: "Elija un almacén."})
        pedidos = {ln["producto"] for ln in v["lineas"]}
        productos = {p.pk: p for p in Producto.objects.filter(pk__in=pedidos)}
        if set(productos) != pedidos:
            raise ValidationError({"lineas": "Hay productos que no existen."})
        lineas = [
            traslados_empresas.LineaTraslado(
                productos[ln["producto"]], ln["cantidad"], tuple(ln.get("series", ()))
            )
            for ln in v["lineas"]
        ]
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            interna = traslados_empresas.registrar_traslado(
                origen=almacenes["almacen_origen"],
                destino=almacenes["almacen_destino"],
                fecha=v["fecha"],
                lineas=lineas,
                observacion=v.get("observacion", ""),
            )
            return 201, _leer(interna.pk)

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

    @extend_schema(
        tags=TAG, request=AnulacionVentaEntrada, responses={200: TrasladoDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        interna = self.get_object()
        traslados_empresas.anular_traslado(interna, motivo=datos.validated_data["motivo"])
        return Response(_leer(interna.pk))
