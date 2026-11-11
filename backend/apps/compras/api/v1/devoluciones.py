"""API de devoluciones a proveedores y del saldo a favor que dejan.

* ``/compras/devoluciones/``: listar, ver, registrar (idempotente) y anular devoluciones.
* ``/compras/creditos/``: saldos a favor con un proveedor; usarlos para pagar compras a crédito
  (idempotente) y deshacer ese uso.
* ``/compras/{id}/por-devolver/`` (en ``views.py``): qué se puede devolver de una compra.

Los montos viajan siempre como texto con dos decimales.
"""

import json
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.compras.creditos import aplicar_credito, deshacer_aplicacion
from apps.compras.devoluciones import (
    LineaDevuelta,
    anular_devolucion,
    previsualizar_devolucion,
    registrar_devolucion,
)
from apps.compras.models import (
    AplicacionCredito,
    AplicacionDevolucion,
    Compra,
    CreditoProveedor,
    DevolucionCompra,
    LineaDevolucionCompra,
    ReembolsoCompra,
)
from apps.compras.servicios import PagoEntrada
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.inventario.models import SerieProducto
from apps.mantenimiento.models import CuentaFinanciera, MedioPago, TipoComprobante
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada

from .serializers import AnulacionCompraEntrada, PagoCompraEntrada
from .views import _entero, _fecha, _plano, _uno

TAG = ["compras"]
VER = "COMPRAS.VER"
DEVOLVER = "COMPRAS.DEVOLVER"
ANULAR_DEVOLUCION = "COMPRAS.DEVOLUCION_ANULAR"
USAR_CREDITO = "COMPRAS.CREDITO_USAR"

DINERO = {"max_digits": 16, "decimal_places": 2}
CERO = Decimal("0")
TOPE_AJUSTE = Decimal("0.10")


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class LineaDevolucionCompraEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1, help_text="Línea de la compra a devolver.")
    cantidad = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal("0.001"), max_value=Decimal("99999999")
    )
    series = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, max_length=2000
    )


class DevolucionEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    compra = serializers.IntegerField(min_value=1)
    # La nota de crédito que emitió el proveedor.
    comprobante_serie = serializers.CharField(max_length=10, required=False, allow_blank=True)
    comprobante_numero = serializers.CharField(max_length=20)
    fecha_emision = serializers.DateField()
    razon = serializers.CharField(max_length=250)
    ajuste_redondeo = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=-TOPE_AJUSTE,
        max_value=TOPE_AJUSTE,
        required=False,
        default=CERO,
    )
    lineas = serializers.ListField(
        child=LineaDevolucionCompraEntrada(), min_length=1, max_length=200
    )
    # Dinero que el proveedor devuelve; lo que no se reembolse queda como saldo a favor.
    reembolsos = serializers.ListField(
        child=PagoCompraEntrada(), required=False, max_length=10, default=list
    )


class CalcularDevolucionEntrada(serializers.Serializer):
    """Lo mínimo para calcular una devolución antes de registrarla."""

    empresa = serializers.IntegerField(min_value=1)
    compra = serializers.IntegerField(min_value=1)
    ajuste_redondeo = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=-TOPE_AJUSTE,
        max_value=TOPE_AJUSTE,
        required=False,
        default=CERO,
    )
    lineas = serializers.ListField(
        child=LineaDevolucionCompraEntrada(), min_length=1, max_length=200
    )


class AplicarCreditoEntrada(serializers.Serializer):
    compra = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    fecha = serializers.DateField(required=False, allow_null=True)
    cuotas = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=60
    )


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class LineaDevolucionSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    unidad = serializers.CharField(source="linea_compra.unidad", read_only=True)
    series = serializers.SerializerMethodField()

    class Meta:
        model = LineaDevolucionCompra
        fields = [
            "id",
            "linea_compra",
            "orden",
            "producto",
            "producto_nombre",
            "unidad",
            "cantidad",
            "cantidad_base",
            "valor_venta",
            "impuesto",
            "total",
            "costo_soles",
            "series",
        ]
        read_only_fields = fields

    def get_series(self, linea) -> list[str]:
        return self.context.get("series", {}).get(linea.orden - 1, [])


class AplicacionDevolucionSerializer(serializers.ModelSerializer):
    cuota_numero = serializers.IntegerField(source="cuota.numero", read_only=True)

    class Meta:
        model = AplicacionDevolucion
        fields = ["id", "cuota", "cuota_numero", "monto"]
        read_only_fields = fields


class ReembolsoCompraSerializer(serializers.ModelSerializer):
    medio_pago_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    moneda_cuenta = serializers.CharField(source="cuenta.moneda", read_only=True)

    class Meta:
        model = ReembolsoCompra
        fields = [
            "id",
            "medio_pago",
            "medio_pago_nombre",
            "cuenta",
            "cuenta_nombre",
            "moneda_cuenta",
            "fecha",
            "monto",
            "referencia",
            "tipo_cambio",
            "monto_cuenta",
            "anulado",
        ]
        read_only_fields = fields


class AplicacionCreditoSerializer(serializers.ModelSerializer):
    compra_numero = serializers.IntegerField(source="compra.numero", read_only=True)
    compra_comprobante = serializers.CharField(source="compra.comprobante", read_only=True)
    cuotas = serializers.SerializerMethodField()

    class Meta:
        model = AplicacionCredito
        fields = [
            "id",
            "compra",
            "compra_numero",
            "compra_comprobante",
            "fecha",
            "monto",
            "cuotas",
            "anulada",
            "anulada_en",
            "motivo_anulacion",
        ]
        read_only_fields = fields

    def get_cuotas(self, aplicacion) -> list[dict]:
        return [
            {"cuota": d.cuota_id, "numero": d.cuota.numero, "monto": f"{d.monto:.2f}"}
            for d in aplicacion.detalles.all()
        ]


class CreditoSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    disponible = serializers.DecimalField(read_only=True, **DINERO)
    devolucion_numero = serializers.IntegerField(
        source="devolucion.numero", default=None, read_only=True
    )
    devolucion_comprobante = serializers.CharField(
        source="devolucion.comprobante", default="", read_only=True
    )
    anticipo_numero = serializers.IntegerField(
        source="anticipo.numero", default=None, read_only=True
    )
    anticipo_codigo = serializers.CharField(source="anticipo.codigo", default="", read_only=True)
    origen = serializers.SerializerMethodField()
    fecha = serializers.DateField(source="fecha_origen", read_only=True)
    aplicaciones = AplicacionCreditoSerializer(many=True, read_only=True)

    class Meta:
        model = CreditoProveedor
        fields = [
            "id",
            "empresa",
            "proveedor",
            "proveedor_nombre",
            "moneda",
            "monto",
            "usado",
            "disponible",
            "anulado",
            "devolucion",
            "devolucion_numero",
            "devolucion_comprobante",
            "anticipo",
            "anticipo_numero",
            "anticipo_codigo",
            "origen",
            "fecha",
            "aplicaciones",
        ]
        read_only_fields = fields

    def get_origen(self, credito) -> str:
        return "ANTICIPO" if credito.anticipo_id else "DEVOLUCION"


class CreditoResumenSerializer(serializers.ModelSerializer):
    disponible = serializers.DecimalField(read_only=True, **DINERO)

    class Meta:
        model = CreditoProveedor
        fields = ["id", "moneda", "monto", "usado", "disponible", "anulado"]
        read_only_fields = fields


class DevolucionListaSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    compra_numero = serializers.IntegerField(source="compra.numero", read_only=True)
    compra_comprobante = serializers.CharField(source="compra.comprobante", read_only=True)
    comprobante = serializers.CharField(read_only=True)
    motivo_nombre = serializers.CharField(source="get_motivo_display", read_only=True)

    class Meta:
        model = DevolucionCompra
        fields = [
            "id",
            "numero",
            "empresa",
            "compra",
            "compra_numero",
            "compra_comprobante",
            "proveedor",
            "proveedor_nombre",
            "comprobante",
            "fecha_emision",
            "motivo",
            "motivo_nombre",
            "moneda",
            "total",
            "aplicado_a_deuda",
            "reembolsado",
            "saldo_a_favor",
            "estado",
        ]
        read_only_fields = fields


class DevolucionDetalleSerializer(DevolucionListaSerializer):
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    tipo_comprobante_codigo = serializers.CharField(
        source="tipo_comprobante.codigo", read_only=True
    )
    lineas = LineaDevolucionSerializer(many=True, read_only=True)
    aplicaciones = AplicacionDevolucionSerializer(many=True, read_only=True)
    reembolsos = ReembolsoCompraSerializer(many=True, read_only=True)
    credito = serializers.SerializerMethodField()

    class Meta(DevolucionListaSerializer.Meta):
        fields = [
            *DevolucionListaSerializer.Meta.fields,
            "almacen_nombre",
            "tipo_comprobante_codigo",
            "comprobante_serie",
            "comprobante_numero",
            "razon",
            "tipo_cambio",
            "op_gravada",
            "igv",
            "op_ivap",
            "ivap",
            "op_exonerada",
            "op_inafecta",
            "ajuste_redondeo",
            "costo_soles",
            "anulado_en",
            "motivo_anulacion",
            "lineas",
            "aplicaciones",
            "reembolsos",
            "credito",
        ]
        read_only_fields = fields

    def get_credito(self, devolucion) -> dict | None:
        credito = getattr(devolucion, "credito", None)
        return CreditoResumenSerializer(credito).data if credito is not None else None


def _series_devueltas(devolucion: DevolucionCompra) -> dict[int, list[str]]:
    """Por posición de línea del movimiento (desde 0), las series que salieron."""
    filas = SerieProducto.objects.filter(
        salida__movimiento_id=devolucion.movimiento_id
    ).values_list("salida__orden", "numero")
    series: dict[int, list[str]] = {}
    for orden, numero in sorted(filas):
        series.setdefault(orden, []).append(numero)
    return series


# ---------------------------------------------------------------------------
# Devoluciones
# ---------------------------------------------------------------------------
class DevolucionCompraViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Devoluciones de mercadería a proveedores (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``compra``, ``proveedor``, ``estado``, ``desde``, ``hasta`` (AAAA-MM-DD) y ``q``
    (nota de crédito, número interno, motivo o proveedor).
    """

    modelo = DevolucionCompra
    serializer_class = DevolucionListaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": DEVOLVER,
        "calcular": DEVOLVER,
        "anular": ANULAR_DEVOLUCION,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                DevolucionCompra.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_class(self):
        if self.action in ("retrieve", "anular", "create"):
            return DevolucionDetalleSerializer
        return DevolucionListaSerializer

    def _base(self):
        return DevolucionCompra.objects.select_related(
            "proveedor", "compra", "almacen", "tipo_comprobante"
        )

    def _con_detalle(self, queryset):
        return queryset.prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaDevolucionCompra.objects.select_related(
                    "producto", "linea_compra"
                ).order_by("orden"),
            ),
            Prefetch(
                "aplicaciones",
                queryset=AplicacionDevolucion.objects.select_related("cuota").order_by(
                    "cuota__numero"
                ),
            ),
            Prefetch(
                "reembolsos",
                queryset=ReembolsoCompra.objects.select_related("medio_pago", "cuenta").order_by(
                    "id"
                ),
            ),
            "credito",
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # al generar la documentación
            return DevolucionCompra.objects.none()
        codigo = codigo_requerido(self, self.request)
        queryset = self._base()
        if self.action in ("retrieve", "anular"):
            queryset = self._con_detalle(queryset)
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        if valor := params.get("estado"):
            queryset = queryset.filter(estado=valor)
        for campo in ("compra", "proveedor"):
            if (valor := _entero(params, campo)) is not None:
                queryset = queryset.filter(**{f"{campo}_id": valor})
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha_emision__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha_emision__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(comprobante_numero__icontains=q)
                | Q(comprobante_serie__icontains=q)
                | Q(razon__icontains=q)
                | Q(proveedor__nombre__icontains=q)
            )
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha_emision", "-id")

    def _contexto_detalle(self, devolucion: DevolucionCompra) -> dict:
        return {"series": _series_devueltas(devolucion)}

    def retrieve(self, request, *args, **kwargs):
        devolucion = self.get_object()
        datos = DevolucionDetalleSerializer(devolucion, context=self._contexto_detalle(devolucion))
        return Response(datos.data)

    def _recargar(self, pk: int) -> dict:
        devolucion = self._con_detalle(self._base()).get(pk=pk)
        return _plano(
            DevolucionDetalleSerializer(devolucion, context=self._contexto_detalle(devolucion)).data
        )

    @extend_schema(
        tags=TAG,
        request=DevolucionEntrada,
        responses={201: DevolucionDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento (8 a 128 caracteres). Un reintento con la "
                "misma clave devuelve el mismo resultado sin devolver de nuevo.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = DevolucionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        compra = Compra.objects.filter(pk=v["compra"], empresa=empresa).first()
        if compra is None:
            raise ValidationError({"compra": "La compra no existe en esta empresa."})
        nota = TipoComprobante.objects.filter(
            organizacion_id=empresa.organizacion_id, codigo="07"
        ).first()
        if nota is None:
            raise ValidationError({"detail": "Falta el tipo de comprobante 07 (nota de crédito)."})
        reembolsos = [
            PagoEntrada(
                medio_pago=_uno(
                    MedioPago, r["medio_pago"], "reembolsos", "Hay métodos de pago que no existen."
                ),
                cuenta=_uno(
                    CuentaFinanciera,
                    r["cuenta"],
                    "reembolsos",
                    "Hay cajas o cuentas que no existen.",
                    empresa=empresa,
                ),  # fmt: skip
                monto=r["monto"],
                fecha=r.get("fecha"),
                referencia=r.get("referencia", ""),
                tipo_cambio=r.get("tipo_cambio"),
                aporte_socio=bool(r.get("aporte_socio", False)),
            )
            for r in v["reembolsos"]
        ]
        lineas = [
            LineaDevuelta(ln["linea"], ln["cantidad"], tuple(ln.get("series", ())))
            for ln in v["lineas"]
        ]
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            with transaction.atomic():
                devolucion = registrar_devolucion(
                    empresa=empresa,
                    compra=compra,
                    tipo_comprobante=nota,
                    comprobante_serie=v.get("comprobante_serie", ""),
                    comprobante_numero=v["comprobante_numero"],
                    fecha_emision=v["fecha_emision"],
                    razon=v["razon"],
                    lineas=lineas,
                    ajuste_redondeo=v["ajuste_redondeo"],
                    reembolsos=reembolsos,
                )
            return 201, self._recargar(devolucion.pk)

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

    @extend_schema(tags=TAG, request=CalcularDevolucionEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="calcular")
    def calcular(self, request):
        """Vista previa: importes, IGV y a dónde iría el dinero, sin registrar nada."""
        datos = CalcularDevolucionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        compra = Compra.objects.filter(pk=v["compra"], empresa_id=v["empresa"]).first()
        if compra is None:
            raise ValidationError({"compra": "La compra no existe en esta empresa."})
        previa = previsualizar_devolucion(
            compra,
            [LineaDevuelta(ln["linea"], ln["cantidad"]) for ln in v["lineas"]],
            v["ajuste_redondeo"],
        )
        r = previa["resultado"]

        def dinero(valor) -> str:
            return f"{valor:.2f}"

        return Response(
            {
                "moneda": compra.moneda,
                "motivo": previa["motivo"],
                "op_gravada": dinero(r.op_gravada),
                "igv": dinero(r.igv),
                "op_ivap": dinero(r.op_ivap),
                "ivap": dinero(r.ivap),
                "op_exonerada": dinero(r.op_exonerada),
                "op_inafecta": dinero(r.op_inafecta),
                "ajuste_redondeo": dinero(r.ajuste_redondeo),
                "total": dinero(r.total),
                "costo_soles": dinero(r.costo_soles),
                "aplicado_a_deuda": dinero(previa["aplicado_a_deuda"]),
                "por_recuperar": dinero(previa["por_recuperar"]),
                "lineas": [
                    {
                        "linea": pk,
                        "cantidad_base": f"{ln.cantidad_base:f}",
                        "valor_venta": dinero(ln.valor_venta),
                        "impuesto": dinero(ln.impuesto),
                        "total": dinero(ln.total),
                        "costo_soles": dinero(ln.costo_soles),
                    }
                    for pk, ln in zip(previa["elegidas"], r.lineas, strict=True)
                ],
            }
        )

    @extend_schema(
        tags=TAG, request=AnulacionCompraEntrada, responses={200: DevolucionDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula la devolución: la mercadería vuelve al almacén y se deshace el dinero."""
        devolucion = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        anular_devolucion(devolucion, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(devolucion.pk))


# ---------------------------------------------------------------------------
# Saldo a favor con proveedores
# ---------------------------------------------------------------------------
class CreditoProveedorViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Saldos a favor con proveedores (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``proveedor``, ``moneda`` y ``disponibles=1`` (solo los que aún tienen saldo).
    """

    modelo = CreditoProveedor
    serializer_class = CreditoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "aplicar": USAR_CREDITO,
        "deshacer": USAR_CREDITO,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                CreditoProveedor.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def _base(self):
        return CreditoProveedor.objects.select_related(
            "proveedor", "devolucion", "anticipo"
        ).prefetch_related(
            Prefetch(
                "aplicaciones",
                queryset=AplicacionCredito.objects.select_related("compra")
                .prefetch_related("detalles__cuota")
                .order_by("-fecha", "-id"),
            )
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # al generar la documentación
            return CreditoProveedor.objects.none()
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(self._base(), self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        if (proveedor := _entero(params, "proveedor")) is not None:
            queryset = queryset.filter(proveedor_id=proveedor)
        if moneda := params.get("moneda"):
            queryset = queryset.filter(moneda=moneda)
        if params.get("disponibles") in ("1", "true", "True"):
            queryset = queryset.filter(anulado=False, usado__lt=F("monto"))
        return queryset.order_by("-id")

    def _recargar(self, pk: int) -> dict:
        return _plano(CreditoSerializer(self._base().get(pk=pk)).data)

    @extend_schema(
        tags=TAG,
        request=AplicarCreditoEntrada,
        responses={201: CreditoSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no aplica el saldo dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="aplicar")
    def aplicar(self, request, pk=None):
        """Paga cuotas de una compra a crédito del mismo proveedor con este saldo a favor."""
        credito = self.get_object()
        datos = AplicarCreditoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        compra = Compra.objects.filter(pk=v["compra"], empresa_id=credito.empresa_id).first()
        if compra is None:
            raise ValidationError({"compra": "La compra no existe en esta empresa."})
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            aplicar_credito(
                credito,
                compra,
                monto=v["monto"],
                cuota_ids=v.get("cuotas"),
                fecha=v.get("fecha"),
            )
            return 201, self._recargar(credito.pk)

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

    @extend_schema(tags=TAG, request=AnulacionCompraEntrada, responses={200: CreditoSerializer})
    @action(detail=True, methods=["post"], url_path=r"aplicaciones/(?P<aplicacion_id>\d+)/deshacer")
    def deshacer(self, request, pk=None, aplicacion_id=None):
        """Deshace un uso del saldo a favor: la compra vuelve a deber esas cuotas."""
        credito = self.get_object()
        aplicacion = AplicacionCredito.objects.filter(pk=aplicacion_id, credito=credito).first()
        if aplicacion is None:
            raise Http404
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        deshacer_aplicacion(aplicacion, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(credito.pk))
