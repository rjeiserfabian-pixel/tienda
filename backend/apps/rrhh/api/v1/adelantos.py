"""API de adelantos de sueldo y préstamos a los trabajadores (por empresa).

* ``RRHH.ADELANTOS.VER``: listado y ficha.  * ``RRHH.ADELANTOS.REGISTRAR``: entregar uno nuevo
  (sale dinero de una caja).  * ``RRHH.ADELANTOS.ANULAR``: deshacerlo.
"""

import json

from django.db.models import Q, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro, MedioPago, Personal
from apps.organizacion.models import Empresa, Estado
from apps.rrhh import adelantos
from apps.rrhh.api.v1.trabajadores import _entero, _PorEmpresa
from apps.rrhh.models import AdelantoPersonal, EstadoAdelanto, EstadoCuota, TipoAdelanto
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["rrhh"]
VER = "RRHH.ADELANTOS.VER"
REGISTRAR = "RRHH.ADELANTOS.REGISTRAR"
ANULAR = "RRHH.ADELANTOS.ANULAR"


class AdelantoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    personal = serializers.IntegerField(min_value=1)
    tipo = serializers.ChoiceField(choices=TipoAdelanto.choices)
    fecha = serializers.DateField()
    monto = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    num_cuotas = serializers.IntegerField(min_value=1, max_value=36, required=False, default=1)
    primer_periodo = serializers.DateField(required=False, allow_null=True)
    cuenta = serializers.IntegerField(min_value=1)
    medio_pago = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    motivo = serializers.CharField(max_length=150, required=False, allow_blank=True)


class AnulacionEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


def _json(adelanto: AdelantoPersonal, *, detalle: bool = False) -> dict:
    datos = {
        "id": adelanto.pk,
        "numero": adelanto.numero,
        "personal": adelanto.personal_id,
        "personal_nombre": adelanto.personal.nombre_completo,
        "tipo": adelanto.tipo,
        "tipo_nombre": adelanto.get_tipo_display(),
        "fecha": adelanto.fecha,
        "monto": adelanto.monto,
        "num_cuotas": adelanto.num_cuotas,
        "primer_periodo": adelanto.primer_periodo,
        "estado": adelanto.estado,
        "cuenta_nombre": adelanto.cuenta.nombre,
        "saldo_pendiente": adelantos.saldo_pendiente(adelanto),
    }
    if detalle:
        datos |= {
            "referencia": adelanto.referencia,
            "motivo": adelanto.motivo,
            "medio_pago_nombre": adelanto.medio_pago.nombre if adelanto.medio_pago else "",
            "anulado_en": adelanto.anulado_en,
            "motivo_anulacion": adelanto.motivo_anulacion,
            "cuotas": [
                {
                    "numero": c.numero,
                    "periodo": c.periodo,
                    "monto": c.monto,
                    "estado": c.estado,
                    "estado_nombre": c.get_estado_display(),
                }
                for c in adelanto.cuotas.all()
            ],
        }
    return datos


class AdelantoViewSet(
    _PorEmpresa,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Adelantos y préstamos de una empresa (``?empresa=ID``).

    Filtros: ``q`` (trabajador), ``tipo``, ``estado``, ``personal``, ``con_saldo=1``,
    ``desde`` y ``hasta`` (fecha de entrega).
    """

    modelo = AdelantoPersonal
    _modelo_de_pk = AdelantoPersonal
    campo_propio = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "opciones": REGISTRAR,
        "create": REGISTRAR,
        "anular": ANULAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            return super().empresas_de_la_operacion(request)
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("personal", "cuenta", "medio_pago")
            .prefetch_related("cuotas")
        )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if tipo := params.get("tipo"):
            queryset = queryset.filter(tipo=tipo)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if (personal := _entero(params, "personal")) is not None:
            queryset = queryset.filter(personal_id=personal)
        if desde := params.get("desde"):
            queryset = queryset.filter(fecha__gte=desde)
        if hasta := params.get("hasta"):
            queryset = queryset.filter(fecha__lte=hasta)
        if params.get("con_saldo") == "1":
            queryset = queryset.filter(
                estado=EstadoAdelanto.VIGENTE, cuotas__estado=EstadoCuota.PENDIENTE
            ).distinct()
        if q := " ".join((params.get("q") or "").split()):
            condicion = Q(personal__nombres__icontains=q) | Q(personal__apellidos__icontains=q)
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("q", str),
            OpenApiParameter("tipo", str),
            OpenApiParameter("estado", str),
            OpenApiParameter("personal", int),
            OpenApiParameter("con_saldo", str),
            OpenApiParameter("desde", str),
            OpenApiParameter("hasta", str),
        ],
        responses={200: dict},
    )
    def list(self, request, *args, **kwargs):
        pagina = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        respuesta = self.get_paginated_response([_json(a) for a in pagina])
        # Lo que falta descontar en total (de todo el filtro, no solo de la página).
        pendiente = (
            self.filter_queryset(self.get_queryset())
            .filter(estado=EstadoAdelanto.VIGENTE, cuotas__estado=EstadoCuota.PENDIENTE)
            .aggregate(t=Sum("cuotas__monto"))["t"]
        )
        respuesta.data["pendiente_total"] = pendiente or 0
        return respuesta

    def retrieve(self, request, *args, **kwargs):
        return Response(_json(self.get_object(), detalle=True))

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    @action(detail=False, methods=["get"])
    def opciones(self, request):
        """Cajas/cuentas en soles, métodos de pago y trabajadores con contrato vigente."""
        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        cuentas = CuentaFinanciera.objects.filter(
            empresa=empresa, estado=EstadoRegistro.ACTIVO, moneda=CuentaFinanciera.Moneda.PEN
        ).order_by("nombre")
        medios = MedioPago.objects.filter(
            organizacion_id=empresa.organizacion_id, estado=EstadoRegistro.ACTIVO
        ).order_by("nombre")
        personal = (
            Personal.objects.filter(
                empresa=empresa,
                estado=EstadoRegistro.ACTIVO,
                contratos__estado="VIGENTE",
            )
            .distinct()
            .order_by("apellidos", "nombres")
        )
        return Response(
            {
                "cuentas": [{"id": c.pk, "nombre": c.nombre, "tipo": c.tipo} for c in cuentas],
                "medios_pago": [{"id": m.pk, "nombre": m.nombre} for m in medios],
                "trabajadores": [
                    {"id": p.pk, "nombre_completo": p.nombre_completo} for p in personal
                ],
            }
        )

    @extend_schema(
        tags=TAG,
        request=AdelantoEntrada,
        responses={201: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no entrega el dinero dos veces.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        entrada = AdelantoEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        personal = Personal.objects.filter(pk=v["personal"], empresa=empresa).first()
        if personal is None:
            raise ValidationError({"personal": "El trabajador no es de esta empresa."})
        cuenta = CuentaFinanciera.objects.filter(pk=v["cuenta"], empresa=empresa).first()
        if cuenta is None:
            raise ValidationError({"cuenta": "Elija una caja o cuenta de la lista."})
        medio = None
        if v.get("medio_pago"):
            medio = MedioPago.objects.filter(
                pk=v["medio_pago"], organizacion_id=empresa.organizacion_id
            ).first()
            if medio is None:
                raise ValidationError({"medio_pago": "Elija un método de pago de la lista."})

        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            adelanto = adelantos.crear_adelanto(
                empresa=empresa,
                personal=personal,
                tipo=v["tipo"],
                fecha=v["fecha"],
                monto=v["monto"],
                num_cuotas=v["num_cuotas"],
                primer_periodo=v.get("primer_periodo"),
                cuenta=cuenta,
                medio_pago=medio,
                referencia=v.get("referencia", ""),
                motivo=v.get("motivo", ""),
            )
            nuevo = self.get_queryset().get(pk=adelanto.pk)
            return 201, json.loads(json.dumps(_json(nuevo, detalle=True), default=str))

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
    @action(detail=True, methods=["post"])
    def anular(self, request, pk=None):
        adelanto = self.get_object()
        entrada = AnulacionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        adelantos.anular_adelanto(adelanto, motivo=entrada.validated_data["motivo"])
        return Response(_json(self.get_queryset().get(pk=adelanto.pk), detalle=True))
