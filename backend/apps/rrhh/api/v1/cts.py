"""API del cálculo y depósito de la CTS (por empresa).

* ``RRHH.CTS.VER``: ver los cálculos y lo que le toca a cada trabajador.
* ``RRHH.CTS.CALCULAR``: calcular, recalcular y descartar un cálculo en revisión.
* ``RRHH.CTS.DEPOSITAR``: registrar el depósito (sale dinero de una caja) y anularlo.
"""

import json

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro, MedioPago
from apps.organizacion.models import Empresa, Estado
from apps.rrhh import cts as servicio
from apps.rrhh.api.v1.trabajadores import _entero, _PorEmpresa
from apps.rrhh.models import DepositoCts, DepositoCtsTrabajador, PeriodoCts
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["rrhh"]
VER = "RRHH.CTS.VER"
CALCULAR = "RRHH.CTS.CALCULAR"
DEPOSITAR = "RRHH.CTS.DEPOSITAR"


class CalculoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    anio = serializers.IntegerField(min_value=2000, max_value=2100)
    periodo = serializers.ChoiceField(choices=PeriodoCts.choices)


class DepositoEntrada(serializers.Serializer):
    fecha = serializers.DateField()
    cuenta = serializers.IntegerField(min_value=1)
    medio_pago = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    total = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )


class AnulacionEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


def _cabecera(d: DepositoCts) -> dict:
    inicio, fin = servicio.rango_del_periodo(d.anio, d.periodo)
    return {
        "id": d.pk,
        "empresa": d.empresa_id,
        "anio": d.anio,
        "periodo": d.periodo,
        "periodo_nombre": d.get_periodo_display(),
        "desde": inicio,
        "hasta": fin,
        "estado": d.estado,
        "estado_nombre": d.get_estado_display(),
        "num_trabajadores": d.num_trabajadores,
        "total": str(d.total),
        "num_errores": d.num_errores,
        "num_avisos": d.num_avisos,
        "calculado_en": d.calculado_en,
        "fecha_deposito": d.fecha_deposito,
        "referencia": d.referencia,
        "puede_depositar": (d.estado == "CALCULADO" and d.num_errores == 0 and d.total > 0),
    }


def _fila(f: DepositoCtsTrabajador) -> dict:
    return {
        "id": f.pk,
        "personal": f.personal_id,
        "nombre_completo": f.personal.nombre_completo,
        "regimen_nombre": f.regimen_nombre,
        "meses": f.meses,
        "dias": f.dias,
        "dias_falta": f.dias_falta,
        "sueldo": str(f.sueldo),
        "asignacion_familiar": str(f.asignacion_familiar),
        "sexto_gratificacion": str(f.sexto_gratificacion),
        "remuneracion_computable": str(f.remuneracion_computable),
        "monto": str(f.monto),
        "avisos": f.avisos,
    }


class CtsViewSet(
    _PorEmpresa,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Cálculos de CTS de una empresa (``?empresa=ID``). Filtros: ``anio``, ``estado``."""

    modelo = DepositoCts
    _modelo_de_pk = DepositoCts
    campo_propio = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "delete", "head", "options"]
    lookup_value_regex = r"\d+"
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": CALCULAR,
        "recalcular": CALCULAR,
        "destroy": CALCULAR,
        "opciones_pago": DEPOSITAR,
        "depositar": DEPOSITAR,
        "anular_deposito": DEPOSITAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            return super().empresas_de_la_operacion(request)
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("empresa")
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (anio := _entero(params, "anio")) is not None:
            queryset = queryset.filter(anio=anio)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("-anio", "-periodo")

    def _detalle(self, d: DepositoCts) -> dict:
        filas = (
            DepositoCtsTrabajador.objects.filter(deposito=d)
            .select_related("personal")
            .order_by("personal__apellidos", "personal__nombres", "id")
        )
        return {**_cabecera(d), "trabajadores": [_fila(f) for f in filas]}

    def _respuesta(self, d: DepositoCts) -> Response:
        return Response(self._detalle(self.get_queryset().get(pk=d.pk)))

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("anio", int),
            OpenApiParameter("estado", str),
        ],
        responses={200: dict},
    )
    def list(self, request, *args, **kwargs):
        pagina = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response([_cabecera(d) for d in pagina])

    def retrieve(self, request, *args, **kwargs):
        return Response(self._detalle(self.get_object()))

    @extend_schema(tags=TAG, request=CalculoEntrada, responses={201: dict})
    def create(self, request, *args, **kwargs):
        entrada = CalculoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        deposito = servicio.crear_calculo(empresa=empresa, anio=v["anio"], periodo=v["periodo"])
        return Response(
            self._detalle(self.get_queryset().get(pk=deposito.pk)), status=status.HTTP_201_CREATED
        )

    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def recalcular(self, request, pk=None):
        deposito = self.get_object()
        servicio.recalcular(deposito)
        return self._respuesta(deposito)

    @extend_schema(tags=TAG, responses={204: None})
    def destroy(self, request, *args, **kwargs):
        servicio.descartar(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="opciones-pago")
    def opciones_pago(self, request, pk=None):
        """Cajas o cuentas en soles y métodos de pago para el depósito."""
        deposito = self.get_object()
        cuentas = CuentaFinanciera.objects.filter(
            empresa_id=deposito.empresa_id,
            estado=EstadoRegistro.ACTIVO,
            moneda=CuentaFinanciera.Moneda.PEN,
        ).order_by("nombre")
        medios = MedioPago.objects.filter(
            organizacion_id=deposito.empresa.organizacion_id, estado=EstadoRegistro.ACTIVO
        ).order_by("nombre")
        return Response(
            {
                "cuentas": [{"id": c.pk, "nombre": c.nombre, "tipo": c.tipo} for c in cuentas],
                "medios_pago": [{"id": m.pk, "nombre": m.nombre} for m in medios],
            }
        )

    @extend_schema(
        tags=TAG,
        request=DepositoEntrada,
        responses={200: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no deposita dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"])
    def depositar(self, request, pk=None):
        deposito = self.get_object()
        entrada = DepositoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        cuenta = CuentaFinanciera.objects.filter(
            pk=v["cuenta"], empresa_id=deposito.empresa_id
        ).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja o cuenta de la lista."})
        medio = None
        if v.get("medio_pago"):
            medio = MedioPago.objects.filter(
                pk=v["medio_pago"], organizacion_id=deposito.empresa.organizacion_id
            ).first()
            if medio is None:
                raise ValidationError({"medio_pago": "Elija un método de pago de la lista."})
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            servicio.depositar(
                deposito,
                fecha=v["fecha"],
                cuenta=cuenta,
                medio_pago=medio,
                referencia=v.get("referencia", ""),
                total_visto=v.get("total"),
            )
            nuevo = self.get_queryset().get(pk=deposito.pk)
            return 200, json.loads(json.dumps(self._detalle(nuevo), default=str))

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

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="anular-deposito")
    def anular_deposito(self, request, pk=None):
        deposito = self.get_object()
        entrada = AnulacionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicio.anular_deposito(deposito, motivo=entrada.validated_data["motivo"])
        return self._respuesta(deposito)
