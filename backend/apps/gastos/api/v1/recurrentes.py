"""API de los gastos recurrentes: plantillas de lo que se paga cada cierto tiempo."""

from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.pagination import PaginaEstandar
from apps.gastos import recurrentes
from apps.gastos.models import GastoRecurrente, Moneda
from apps.mantenimiento.models import CategoriaGasto, Periodicidad, Proveedor, TipoComprobante
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada

from .views import TAG, _entero

VER = "GASTOS.VER"
REGISTRAR = "GASTOS.REGISTRAR"
DINERO = {"max_digits": 16, "decimal_places": 2}


class RecurrenteEntrada(serializers.Serializer):
    """Para crear van todos los datos obligatorios; al editar, solo los que cambian."""

    empresa = serializers.IntegerField(min_value=1, required=False)
    nombre = serializers.CharField(max_length=80, required=False)
    categoria = serializers.IntegerField(min_value=1, required=False)
    descripcion = serializers.CharField(max_length=250, required=False)
    con_comprobante = serializers.BooleanField(required=False)
    tipo_comprobante = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    proveedor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, required=False)
    importe_estimado = serializers.DecimalField(required=False, allow_null=True, **DINERO)
    periodicidad = serializers.IntegerField(min_value=1, required=False)
    proxima_fecha = serializers.DateField(required=False)
    avisar_dias = serializers.IntegerField(min_value=0, max_value=30, required=False)
    estado = serializers.ChoiceField(choices=GastoRecurrente.Estado.choices, required=False)


class RecurrenteSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    tipo_comprobante_nombre = serializers.CharField(
        source="tipo_comprobante.nombre", default="", read_only=True
    )
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", default="", read_only=True)
    proveedor_documento = serializers.CharField(
        source="proveedor.numero_documento", default="", read_only=True
    )
    proveedor_tipo_documento = serializers.CharField(
        source="proveedor.tipo_documento", default="", read_only=True
    )
    periodicidad_nombre = serializers.CharField(source="periodicidad.nombre", read_only=True)
    periodicidad_descripcion = serializers.CharField(
        source="periodicidad.descripcion", read_only=True
    )
    dias_para_toca = serializers.SerializerMethodField()
    aviso = serializers.SerializerMethodField()

    class Meta:
        model = GastoRecurrente
        fields = [
            "id",
            "empresa",
            "nombre",
            "categoria",
            "categoria_nombre",
            "descripcion",
            "con_comprobante",
            "tipo_comprobante",
            "tipo_comprobante_nombre",
            "proveedor",
            "proveedor_nombre",
            "proveedor_documento",
            "proveedor_tipo_documento",
            "moneda",
            "importe_estimado",
            "periodicidad",
            "periodicidad_nombre",
            "periodicidad_descripcion",
            "proxima_fecha",
            "avisar_dias",
            "ultima_registrada",
            "estado",
            "dias_para_toca",
            "aviso",
            "creado_en",
        ]
        read_only_fields = fields

    def get_dias_para_toca(self, r) -> int:
        return (r.proxima_fecha - timezone.localdate()).days

    def get_aviso(self, r) -> str:
        """VENCIDO (ya pasó), HOY, PROXIMO (dentro de su aviso), AL_DIA o INACTIVO."""
        if r.estado != GastoRecurrente.Estado.ACTIVO:
            return "INACTIVO"
        dias = (r.proxima_fecha - timezone.localdate()).days
        if dias < 0:
            return "VENCIDO"
        if dias == 0:
            return "HOY"
        return "PROXIMO" if dias <= r.avisar_dias else "AL_DIA"


def _uno(modelo, pk, campo: str, mensaje: str, **filtros):
    if pk is None:
        return None
    objeto = modelo.objects.filter(pk=pk, **filtros).first()
    if objeto is None:
        raise ValidationError({campo: mensaje})
    return objeto


class RecurrenteViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Gastos recurrentes (``?empresa=ID`` obligatorio en el listado; ``?pendientes=1``)."""

    modelo = GastoRecurrente
    serializer_class = RecurrenteSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": REGISTRAR,
        "partial_update": REGISTRAR,
        "destroy": REGISTRAR,
        "omitir": REGISTRAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                GastoRecurrente.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(
            GastoRecurrente.objects.select_related(
                "categoria", "tipo_comprobante", "proveedor", "periodicidad"
            ),
            self.request.user,
            codigo,
        )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("proxima_fecha", "nombre")

    def list(self, request, *args, **kwargs):
        if request.query_params.get("pendientes") in ("1", "true"):
            hoy = timezone.localdate()
            lista = [
                r
                for r in self.get_queryset().filter(estado=GastoRecurrente.Estado.ACTIVO)
                if (r.proxima_fecha - hoy).days <= r.avisar_dias
            ]
            pagina = self.paginate_queryset(lista)
            return self.get_paginated_response(RecurrenteSerializer(pagina, many=True).data)
        return super().list(request, *args, **kwargs)

    @staticmethod
    def _objetos(v: dict, empresa: Empresa) -> dict:
        """Los ids que llegan se vuelven objetos de la organización; solo se tocan los enviados."""
        org = empresa.organizacion_id
        datos = {k: v[k] for k in v if k not in ("empresa", "estado")}
        if "categoria" in datos:
            datos["categoria"] = _uno(
                CategoriaGasto, datos["categoria"], "categoria", "Elija una categoría.",
                organizacion_id=org,
            )  # fmt: skip
        if "periodicidad" in datos:
            datos["periodicidad"] = _uno(
                Periodicidad, datos["periodicidad"], "periodicidad", "Elija cada cuánto se repite.",
                organizacion_id=org,
            )  # fmt: skip
        if "tipo_comprobante" in datos:
            datos["tipo_comprobante"] = _uno(
                TipoComprobante, datos["tipo_comprobante"], "tipo_comprobante",
                "Elija un tipo de comprobante.", organizacion_id=org,
            )  # fmt: skip
        if "proveedor" in datos:
            datos["proveedor"] = _uno(
                Proveedor, datos["proveedor"], "proveedor", "Elija un proveedor.",
                organizacion_id=org,
            )  # fmt: skip
        return datos

    @extend_schema(tags=TAG, request=RecurrenteEntrada, responses={201: RecurrenteSerializer})
    def create(self, request, *args, **kwargs):
        datos = RecurrenteEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = Empresa.objects.filter(pk=v.get("empresa"), estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        faltan = [
            c
            for c in ("nombre", "categoria", "descripcion", "periodicidad", "proxima_fecha")
            if c not in v
        ]
        if faltan:
            raise ValidationError(dict.fromkeys(faltan, "Este dato es obligatorio."))
        completos = {
            "con_comprobante": True,
            "tipo_comprobante": None,
            "proveedor": None,
            "moneda": Moneda.PEN,
            "importe_estimado": None,
            "avisar_dias": 5,
            **self._objetos(v, empresa),
        }
        r = recurrentes.guardar(empresa, completos)
        return Response(RecurrenteSerializer(self.get_queryset().get(pk=r.pk)).data, status=201)

    @extend_schema(tags=TAG, request=RecurrenteEntrada, responses={200: RecurrenteSerializer})
    def partial_update(self, request, *args, **kwargs):
        instancia = self.get_object()
        datos = RecurrenteEntrada(data=request.data, partial=True)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        r = recurrentes.guardar(
            instancia.empresa, self._objetos(v, instancia.empresa), instancia=instancia
        )
        if "estado" in v and v["estado"] != r.estado:
            r = recurrentes.cambiar_estado(r, v["estado"])
        return Response(RecurrenteSerializer(self.get_queryset().get(pk=r.pk)).data)

    @extend_schema(tags=TAG, responses={204: None})
    def destroy(self, request, *args, **kwargs):
        """Quita la plantilla (sus gastos ya registrados se quedan)."""
        instancia = self.get_object()
        instancia.delete()  # borrado lógico
        return Response(status=204)

    @extend_schema(tags=TAG, request=None, responses={200: RecurrenteSerializer})
    @action(detail=True, methods=["post"], url_path="omitir")
    def omitir(self, request, pk=None):
        """Salta el ciclo que tocaba (ese mes no hubo gasto) sin registrar nada."""
        r = recurrentes.omitir(self.get_object())
        return Response(RecurrenteSerializer(self.get_queryset().get(pk=r.pk)).data)
