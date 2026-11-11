"""Cuentas de cobro: en qué caja o cuenta entra cada método de pago de una empresa y tienda."""

from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.auditoria.servicios import registrar
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro, MedioPago
from apps.organizacion.models import Sucursal
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.ventas.models import CuentaDeCobro

from .views import TAG, VER, _empresa_activa, _entero, _uno

GESTIONAR = "VENTAS.CUENTAS_COBRO"


class CuentaDeCobroSerializer(serializers.ModelSerializer):
    medio_pago_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    medio_pago_tipo = serializers.CharField(source="medio_pago.tipo", read_only=True)
    sucursal_nombre = serializers.CharField(source="sucursal.nombre", default="", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    cuenta_tipo = serializers.CharField(source="cuenta.tipo", read_only=True)
    moneda = serializers.CharField(source="cuenta.moneda", read_only=True)

    class Meta:
        model = CuentaDeCobro
        fields = [
            "id",
            "empresa",
            "medio_pago",
            "medio_pago_nombre",
            "medio_pago_tipo",
            "sucursal",
            "sucursal_nombre",
            "cuenta",
            "cuenta_nombre",
            "cuenta_tipo",
            "moneda",
        ]
        read_only_fields = fields


class CuentaDeCobroEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    medio_pago = serializers.IntegerField(min_value=1)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cuenta = serializers.IntegerField(min_value=1)


class CuentaDeCobroViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Cuentas de cobro de una empresa (``?empresa=ID`` obligatorio en el listado)."""

    modelo = CuentaDeCobro
    serializer_class = CuentaDeCobroSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    pagination_class = PaginaEstandar
    permisos_por_accion = {"list": VER, "create": GESTIONAR, "destroy": GESTIONAR}

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                CuentaDeCobro.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                from django.http import Http404

                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("medio_pago", "sucursal", "cuenta")
        if self.action == "list":
            queryset = queryset.filter(empresa_id=_entero(self.request.query_params, "empresa"))
        return queryset.order_by("medio_pago__nombre", "sucursal__nombre", "id")

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(tags=TAG, request=CuentaDeCobroEntrada, responses={201: CuentaDeCobroSerializer})
    def create(self, request, *args, **kwargs):
        datos = CuentaDeCobroEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        medio = _uno(
            MedioPago,
            v["medio_pago"],
            "medio_pago",
            "Elija un método de pago.",
            organizacion_id=empresa.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
        )
        sucursal = _uno(
            Sucursal,
            v.get("sucursal"),
            "sucursal",
            "Elija una tienda de la empresa.",
            empresa=empresa,
        )
        cuenta = _uno(
            CuentaFinanciera,
            v["cuenta"],
            "cuenta",
            "Elija una caja o cuenta de la empresa.",
            empresa=empresa,
            estado=EstadoRegistro.ACTIVO,
        )
        if medio.tipo == MedioPago.Tipo.EFECTIVO and cuenta.tipo != CuentaFinanciera.Tipo.CAJA:
            raise ValidationError({"cuenta": "El efectivo entra a una caja de efectivo."})
        if medio.tipo != MedioPago.Tipo.EFECTIVO and cuenta.tipo == CuentaFinanciera.Tipo.CAJA:
            raise ValidationError({"cuenta": "Este método entra a una cuenta, no a una caja."})
        try:
            with transaction.atomic():
                fila = CuentaDeCobro.objects.create(
                    empresa=empresa, medio_pago=medio, sucursal=sucursal, cuenta=cuenta
                )
        except IntegrityError:
            raise ValidationError(
                {"medio_pago": "Ese método ya tiene una cuenta para esa tienda: elimínala primero."}
            ) from None
        registrar(
            "ventas.cuenta_de_cobro_creada",
            recurso_tipo="cuenta_de_cobro",
            recurso_id=fila.pk,
            empresa_id=empresa.pk,
            resumen=f"{medio.nombre} entra a «{cuenta.nombre}»"
            + (f" en {sucursal.nombre}" if sucursal else ""),
        )
        return Response(CuentaDeCobroSerializer(fila).data, status=201)

    @extend_schema(tags=TAG, responses={204: None})
    def destroy(self, request, *args, **kwargs):
        fila = self.get_object()
        registrar(
            "ventas.cuenta_de_cobro_eliminada",
            recurso_tipo="cuenta_de_cobro",
            recurso_id=fila.pk,
            empresa_id=fila.empresa_id,
            resumen=f"Se quitó que {fila.medio_pago.nombre} entre a «{fila.cuenta.nombre}»",
        )
        fila.delete()
        return Response(status=204)
