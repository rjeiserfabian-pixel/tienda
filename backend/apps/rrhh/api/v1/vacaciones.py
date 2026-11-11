"""API de las vacaciones de los trabajadores (por empresa).

* ``RRHH.VACACIONES.VER``: saldos de días y vacaciones registradas.
* ``RRHH.VACACIONES.REGISTRAR``: registrar las vacaciones que toma un trabajador.
* ``RRHH.VACACIONES.ANULAR``: anularlas (los días vuelven al saldo).
"""

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import EstadoRegistro, Personal
from apps.rrhh import vacaciones as servicio
from apps.rrhh.api.v1.trabajadores import _entero, _PorEmpresa
from apps.rrhh.models import VacacionPersonal
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

TAG = ["rrhh"]
VER = "RRHH.VACACIONES.VER"
REGISTRAR = "RRHH.VACACIONES.REGISTRAR"
ANULAR = "RRHH.VACACIONES.ANULAR"


class VacacionEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    personal = serializers.IntegerField(min_value=1)
    desde = serializers.DateField()
    hasta = serializers.DateField()
    observacion = serializers.CharField(max_length=150, required=False, allow_blank=True)
    marcar_asistencia = serializers.BooleanField(required=False, default=True)


class AnulacionEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


def _json(v: VacacionPersonal) -> dict:
    return {
        "id": v.pk,
        "personal": v.personal_id,
        "personal_nombre": v.personal.nombre_completo,
        "desde": v.desde,
        "hasta": v.hasta,
        "dias": v.dias,
        "marco_asistencia": v.marco_asistencia,
        "observacion": v.observacion,
        "estado": v.estado,
        "estado_nombre": v.get_estado_display(),
        "anulado_en": v.anulado_en,
        "motivo_anulacion": v.motivo_anulacion,
    }


class VacacionViewSet(
    _PorEmpresa,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Vacaciones registradas de una empresa (``?empresa=ID``).

    Filtros: ``personal``, ``estado``. Los saldos de días van en ``/saldos/``.
    """

    modelo = VacacionPersonal
    _modelo_de_pk = VacacionPersonal
    campo_propio = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "saldos": VER,
        "create": REGISTRAR,
        "anular": ANULAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            return super().empresas_de_la_operacion(request)
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("personal")
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (personal := _entero(params, "personal")) is not None:
            queryset = queryset.filter(personal_id=personal)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("-desde", "-id")

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("personal", int),
            OpenApiParameter("estado", str),
        ],
        responses={200: dict},
    )
    def list(self, request, *args, **kwargs):
        pagina = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response([_json(v) for v in pagina])

    def retrieve(self, request, *args, **kwargs):
        return Response(_json(self.get_object()))

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True), OpenApiParameter("q", str)],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"])
    def saldos(self, request):
        """Días ganados, tomados y saldo de cada trabajador con contrato."""
        empresa_id = _entero(request.query_params, "empresa")
        personal = Personal.objects.filter(
            empresa_id=empresa_id, estado=EstadoRegistro.ACTIVO, contratos__isnull=False
        ).distinct()
        if q := " ".join((request.query_params.get("q") or "").split()):
            personal = personal.filter(Q(nombres__icontains=q) | Q(apellidos__icontains=q))
        pagina = self.paginate_queryset(personal.order_by("apellidos", "nombres", "id"))
        saldos = servicio.saldos_de([p.pk for p in pagina])
        filas = []
        for p in pagina:
            s = saldos.get(p.pk)
            if s is None:
                continue
            filas.append(
                {
                    "personal": p.pk,
                    "nombre_completo": p.nombre_completo,
                    "inicio_servicio": s["inicio_servicio"],
                    "meses_servicio": s["meses_servicio"],
                    "dias_anuales": s["dias_anuales"],
                    "ganados": str(s["ganados"]),
                    "tomados": s["tomados"],
                    "saldo": str(s["saldo"]),
                }
            )
        return self.get_paginated_response(filas)

    @extend_schema(tags=TAG, request=VacacionEntrada, responses={201: dict})
    def create(self, request, *args, **kwargs):
        entrada = VacacionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        v = entrada.validated_data
        personal = Personal.objects.filter(pk=v["personal"], empresa_id=v["empresa"]).first()
        if personal is None:
            raise ValidationError({"personal": "El trabajador no es de esta empresa."})
        vacacion = servicio.registrar(
            personal=personal,
            desde=v["desde"],
            hasta=v["hasta"],
            observacion=v.get("observacion", ""),
            marcar_asistencia=v["marcar_asistencia"],
        )
        nueva = self.get_queryset().get(pk=vacacion.pk)
        return Response(_json(nueva), status=201)

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: dict})
    @action(detail=True, methods=["post"])
    def anular(self, request, pk=None):
        vacacion = self.get_object()
        entrada = AnulacionEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicio.anular(vacacion, motivo=entrada.validated_data["motivo"])
        return Response(_json(self.get_queryset().get(pk=vacacion.pk)))
