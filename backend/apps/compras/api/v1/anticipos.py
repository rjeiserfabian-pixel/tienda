"""API de anticipos a proveedores: adelantar dinero, ver su saldo, devolverlo y anularlo.

El saldo a favor que deja cada anticipo se usa desde «Saldos a favor» (``/compras/creditos/``),
igual que el de las devoluciones. Los montos viajan como texto con dos decimales.
"""

import json
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.compras import anticipos as servicio
from apps.compras.models import AnticipoProveedor, Moneda, OrdenCompra
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import CuentaFinanciera, MedioPago, Proveedor
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada

from .serializers import AnulacionCompraEntrada
from .views import _entero, _fecha, _plano, _uno

TAG = ["compras"]
VER = "COMPRAS.VER"
ANTICIPAR = "COMPRAS.ANTICIPAR"
ANULAR = "COMPRAS.ANULAR"
DINERO = {"max_digits": 16, "decimal_places": 2}


def _dinero(valor) -> str:
    return f"{valor:.2f}"


class AnticipoSerializer(serializers.ModelSerializer):
    codigo = serializers.CharField(read_only=True)
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    medio_nombre = serializers.CharField(source="medio_pago.nombre", default="", read_only=True)
    orden_codigo = serializers.SerializerMethodField()
    credito = serializers.SerializerMethodField()
    disponible = serializers.SerializerMethodField()
    devuelto = serializers.SerializerMethodField()
    aplicado = serializers.SerializerMethodField()

    class Meta:
        model = AnticipoProveedor
        fields = [
            "id",
            "numero",
            "codigo",
            "empresa",
            "fecha",
            "proveedor",
            "proveedor_nombre",
            "moneda",
            "monto",
            "cuenta",
            "cuenta_nombre",
            "medio_pago",
            "medio_nombre",
            "referencia",
            "glosa",
            "orden",
            "orden_codigo",
            "estado",
            "motivo_anulacion",
            "credito",
            "disponible",
            "devuelto",
            "aplicado",
        ]
        read_only_fields = fields

    def _c(self, a):
        return getattr(a, "credito", None)

    def get_orden_codigo(self, a) -> str | None:
        return a.orden.codigo if a.orden_id else None

    def get_credito(self, a) -> int | None:
        c = self._c(a)
        return c.pk if c else None

    def get_disponible(self, a) -> str:
        c = self._c(a)
        return _dinero(c.disponible if c else Decimal("0"))

    def get_devuelto(self, a) -> str:
        return _dinero(servicio.devuelto(a))

    def get_aplicado(self, a) -> str:
        """Lo que ya se descontó de compras: lo usado menos lo que el proveedor devolvió."""
        c = self._c(a)
        return _dinero(max((c.usado if c else Decimal("0")) - servicio.devuelto(a), Decimal("0")))


class AnticipoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    proveedor = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    cuenta = serializers.IntegerField(min_value=1)
    moneda = serializers.ChoiceField(choices=Moneda.choices, default=Moneda.PEN)
    fecha = serializers.DateField(required=False, allow_null=True)
    medio_pago = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    glosa = serializers.CharField(max_length=250, required=False, allow_blank=True)
    orden = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class DevolucionAnticipoEntrada(serializers.Serializer):
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    cuenta = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField(required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    medio_pago = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class AnticipoViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Anticipos a proveedores de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``proveedor``, ``orden``, ``estado``, ``desde``, ``hasta`` (fecha) y ``q`` (número o
    referencia).
    """

    modelo = AnticipoProveedor
    serializer_class = AnticipoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": ANTICIPAR,
        "devolver": ANTICIPAR,
        "anular": ANULAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                AnticipoProveedor.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_throttles(self):
        return [ApiAutenticadaThrottle()]

    def _base(self):
        return AnticipoProveedor.objects.select_related(
            "proveedor", "cuenta", "medio_pago", "orden", "credito"
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnticipoProveedor.objects.none()
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(self._base(), self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        if (proveedor := _entero(params, "proveedor")) is not None:
            queryset = queryset.filter(proveedor_id=proveedor)
        if (orden := _entero(params, "orden")) is not None:
            queryset = queryset.filter(orden_id=orden)
        if valor := params.get("estado"):
            queryset = queryset.filter(estado=valor)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            condicion = Q(referencia__icontains=q) | Q(proveedor__nombre__icontains=q)
            digitos = q.upper().removeprefix("ANT-").lstrip("0")
            if digitos.isdigit() and len(digitos) <= 9:
                condicion |= Q(numero=int(digitos))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    def _recargar(self, pk: int) -> dict:
        return _plano(AnticipoSerializer(self._base().get(pk=pk)).data)

    def _idempotente(self, request, operacion):
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()
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
        tags=TAG,
        request=AnticipoEntrada,
        responses={201: AnticipoSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no adelanta el dinero otra vez.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = AnticipoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        argumentos = {
            "empresa": empresa,
            "proveedor": _uno(Proveedor, v["proveedor"], "proveedor", "No existe."),
            "monto": v["monto"],
            "cuenta": _uno(
                CuentaFinanciera,
                v["cuenta"],
                "cuenta",
                "Elija una cuenta de la empresa.",
                empresa=empresa,
            ),  # fmt: skip
            "moneda": v["moneda"],
            "fecha": v.get("fecha"),
            "medio_pago": (
                _uno(MedioPago, v["medio_pago"], "medio_pago", "No existe.")
                if v.get("medio_pago")
                else None
            ),
            "referencia": v.get("referencia", ""),
            "glosa": v.get("glosa", ""),
            "orden": (
                _uno(OrdenCompra, v["orden"], "orden", "No existe.", empresa=empresa)
                if v.get("orden")
                else None
            ),
        }

        def operacion():
            with transaction.atomic():
                anticipo = servicio.registrar_anticipo(**argumentos)
            return 201, self._recargar(anticipo.pk)

        return self._idempotente(request, operacion)

    @extend_schema(
        tags=TAG,
        request=DevolucionAnticipoEntrada,
        responses={200: AnticipoSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no registra la devolución "
                "dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="devolver")
    def devolver(self, request, pk=None):
        """El proveedor devuelve (todo o parte de) el dinero: entra a una caja y baja el saldo."""
        anticipo = self.get_object()
        datos = DevolucionAnticipoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        cuenta = _uno(
            CuentaFinanciera, v["cuenta"], "cuenta", "Elija una cuenta de la empresa.",
            empresa=anticipo.empresa,
        )  # fmt: skip
        medio = (
            _uno(MedioPago, v["medio_pago"], "medio_pago", "No existe.")
            if v.get("medio_pago")
            else None
        )

        def operacion():
            with transaction.atomic():
                servicio.devolver_anticipo(
                    anticipo,
                    monto=v["monto"],
                    cuenta=cuenta,
                    fecha=v.get("fecha"),
                    referencia=v.get("referencia", ""),
                    medio_pago=medio,
                )
            return 200, self._recargar(anticipo.pk)

        return self._idempotente(request, operacion)

    @extend_schema(tags=TAG, request=AnulacionCompraEntrada, responses={200: AnticipoSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula el anticipo si su saldo está intacto: el dinero vuelve a la caja."""
        anticipo = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.anular_anticipo(anticipo, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(anticipo.pk))
