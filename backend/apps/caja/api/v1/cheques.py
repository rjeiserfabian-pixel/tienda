"""API de cheques recibidos y girados: registrar, depositar, cobrar, rechazar y anular."""

import json
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.caja import cheques as servicio
from apps.caja.models import Cheque
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.models import Cliente, CuentaFinanciera, EstadoRegistro, Proveedor
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada

from .conciliacion import _textos
from .views import TAG, _entero, _fecha

VER = "CAJA.CHEQUES.VER"
GESTIONAR = "CAJA.CHEQUES.GESTIONAR"


class ChequeSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    moneda_nombre = serializers.CharField(source="get_moneda_display", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", default="", read_only=True)
    cartera_nombre = serializers.CharField(
        source="cuenta_cartera.nombre", default="", read_only=True
    )
    vence = serializers.DateField(read_only=True)

    class Meta:
        model = Cheque
        fields = [
            "id",
            "empresa",
            "tipo",
            "tipo_nombre",
            "estado",
            "estado_nombre",
            "numero",
            "banco",
            "importe",
            "moneda",
            "moneda_nombre",
            "fecha_emision",
            "fecha_pago",
            "vence",
            "tercero",
            "cliente",
            "proveedor",
            "cuenta",
            "cuenta_nombre",
            "cuenta_cartera",
            "cartera_nombre",
            "glosa",
            "depositado_en",
            "cobrado_en",
            "motivo",
        ]
        read_only_fields = fields


class ChequeEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    tipo = serializers.ChoiceField(choices=Cheque.Tipo.choices)
    numero = serializers.CharField(max_length=30)
    banco = serializers.CharField(max_length=60)
    importe = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal("0.01"))
    moneda = serializers.ChoiceField(choices=Cheque.Moneda.choices, default=Cheque.Moneda.PEN)
    fecha_emision = serializers.DateField()
    fecha_pago = serializers.DateField(required=False, allow_null=True)
    tercero = serializers.CharField(max_length=150, required=False, allow_blank=True)
    cliente = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    proveedor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cuenta = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cuenta_cartera = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    glosa = serializers.CharField(max_length=250, required=False, allow_blank=True)


class DepositoEntrada(serializers.Serializer):
    cuenta = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField(required=False, allow_null=True)


class CobroEntrada(serializers.Serializer):
    cuenta = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cuenta_cartera = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    fecha = serializers.DateField(required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)


class RechazoEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)
    comision = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=Decimal("0"), default=Decimal("0")
    )
    fecha = serializers.DateField(required=False, allow_null=True)


class MotivoEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


def _uno(modelo, pk, campo: str, empresa: Empresa | None = None):
    """El registro pedido, o un error de campo claro (las cuentas, de la empresa)."""
    if pk is None:
        return None
    filtros = {"pk": pk}
    if empresa is not None:
        filtros["empresa"] = empresa
    objeto = modelo.objects.filter(**filtros).first()
    if objeto is None:
        raise ValidationError({campo: "No existe."})
    return objeto


class ChequeViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Cheques de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``tipo``, ``estado``, ``vencidos=1`` (recibidos pendientes que ya pasaron su plazo),
    ``desde`` y ``hasta`` (fecha de emisión) y ``q`` (número, banco o quién lo giró).
    """

    modelo = Cheque
    serializer_class = ChequeSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": GESTIONAR,
        "depositar": GESTIONAR,
        "cobrar": GESTIONAR,
        "rechazar": GESTIONAR,
        "anular": GESTIONAR,
        "deshacer_cobro": GESTIONAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                Cheque.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_throttles(self):
        return [ApiAutenticadaThrottle()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Cheque.objects.none()
        codigo = codigo_requerido(self, self.request)
        queryset = Cheque.objects.select_related("cuenta", "cuenta_cartera")
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if valor := params.get("tipo"):
            queryset = queryset.filter(tipo=valor)
        if valor := params.get("estado"):
            queryset = queryset.filter(estado=valor)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha_emision__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha_emision__lte=hasta)
        if q := (params.get("q") or "").strip():
            queryset = queryset.filter(
                Q(numero__icontains=q) | Q(banco__icontains=q) | Q(tercero__icontains=q)
            )
        if params.get("vencidos") in ("1", "true", "True"):
            # el plazo es de 30 días desde la fecha de pago (o de emisión)
            hoy = self._hoy()
            candidatos = queryset.filter(
                tipo=Cheque.Tipo.RECIBIDO,
                estado__in=(Cheque.Estado.EN_CARTERA, Cheque.Estado.DEPOSITADO),
            ).values_list("pk", "fecha_emision", "fecha_pago")
            ids = [
                pk
                for pk, emision, pago in candidatos
                if (pago or emision) + timedelta(days=30) < hoy
            ]
            queryset = queryset.filter(pk__in=ids)
        return queryset.order_by("-fecha_emision", "-id")

    @staticmethod
    def _hoy():
        from django.utils import timezone

        return timezone.localdate()

    def _recargar(self, pk: int) -> dict:
        cheque = Cheque.objects.select_related("cuenta", "cuenta_cartera").get(pk=pk)
        return _textos(ChequeSerializer(cheque).data)

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
        request=ChequeEntrada,
        responses={201: ChequeSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no duplica el cheque.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = ChequeEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        argumentos = {
            "empresa": empresa,
            "tipo": v["tipo"],
            "numero": v["numero"],
            "banco": v["banco"],
            "importe": v["importe"],
            "moneda": v["moneda"],
            "fecha_emision": v["fecha_emision"],
            "fecha_pago": v.get("fecha_pago"),
            "tercero": v.get("tercero", ""),
            "cliente": _uno(Cliente, v.get("cliente"), "cliente"),
            "proveedor": _uno(Proveedor, v.get("proveedor"), "proveedor"),
            "cuenta": _uno(CuentaFinanciera, v.get("cuenta"), "cuenta", empresa),
            "cuenta_cartera": _uno(
                CuentaFinanciera, v.get("cuenta_cartera"), "cuenta_cartera", empresa
            ),
            "glosa": v.get("glosa", ""),
        }

        def operacion():
            with transaction.atomic():
                cheque = servicio.registrar_cheque(**argumentos)
            return 201, _textos(self._recargar(cheque.pk))

        return self._idempotente(request, operacion)

    def retrieve(self, request, *args, **kwargs):
        return Response(_textos(ChequeSerializer(self.get_object()).data))

    def list(self, request, *args, **kwargs):
        pagina = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(_textos(ChequeSerializer(pagina, many=True).data))

    @extend_schema(tags=TAG, request=DepositoEntrada, responses={200: ChequeSerializer})
    @action(detail=True, methods=["post"], url_path="depositar")
    def depositar(self, request, pk=None):
        """Marca que el cheque recibido se llevó al banco."""
        cheque = self.get_object()
        datos = DepositoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        cuenta = _uno(CuentaFinanciera, v["cuenta"], "cuenta", cheque.empresa)
        servicio.depositar(cheque, cuenta=cuenta, fecha=v.get("fecha"))
        return Response(self._recargar(cheque.pk))

    @extend_schema(tags=TAG, request=CobroEntrada, responses={200: ChequeSerializer})
    @action(detail=True, methods=["post"], url_path="cobrar")
    def cobrar(self, request, pk=None):
        """El banco pagó el cheque. En uno recibido, el importe pasa de la cuenta de cheques al
        banco; en uno girado solo cambia su estado."""
        cheque = self.get_object()
        datos = CobroEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        servicio.cobrar(
            cheque,
            fecha=v.get("fecha"),
            cuenta=_uno(CuentaFinanciera, v.get("cuenta"), "cuenta", cheque.empresa),
            cuenta_cartera=_uno(
                CuentaFinanciera, v.get("cuenta_cartera"), "cuenta_cartera", cheque.empresa
            ),
            referencia=v.get("referencia", ""),
        )
        return Response(self._recargar(cheque.pk))

    @extend_schema(tags=TAG, request=RechazoEntrada, responses={200: ChequeSerializer})
    @action(detail=True, methods=["post"], url_path="rechazar")
    def rechazar(self, request, pk=None):
        """El banco no pagó el cheque; opcionalmente se anota la comisión que cobró."""
        cheque = self.get_object()
        datos = RechazoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        servicio.rechazar(cheque, motivo=v["motivo"], comision=v["comision"], fecha=v.get("fecha"))
        return Response(self._recargar(cheque.pk))

    @extend_schema(tags=TAG, request=MotivoEntrada, responses={200: ChequeSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula un cheque que aún no se depositó ni se cobró."""
        cheque = self.get_object()
        datos = MotivoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.anular(cheque, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(cheque.pk))

    @extend_schema(tags=TAG, request=MotivoEntrada, responses={200: ChequeSerializer})
    @action(detail=True, methods=["post"], url_path="deshacer-cobro")
    def deshacer_cobro(self, request, pk=None):
        """Corrige un cobro marcado por error."""
        cheque = self.get_object()
        datos = MotivoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.deshacer_cobro(cheque, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(cheque.pk))


class CuentasDeChequesView(APIView):
    """La cuenta donde se anota lo cobrado con cheque (la de «Cuentas de cobro» de Ventas)."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        from apps.mantenimiento.models import MedioPago
        from apps.ventas.models import CuentaDeCobro  # ventas depende de caja: se importa aquí

        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        ids = (
            CuentaDeCobro.objects.sin_ambito()
            .filter(empresa=empresa, medio_pago__tipo=MedioPago.Tipo.CHEQUE)
            .values_list("cuenta_id", flat=True)
        )
        cuentas = CuentaFinanciera.objects.filter(
            pk__in=list(ids), empresa=empresa, estado=EstadoRegistro.ACTIVO
        ).order_by("nombre")
        return Response(
            [{"id": c.pk, "nombre": c.nombre, "moneda": c.moneda, "tipo": c.tipo} for c in cuentas]
        )
