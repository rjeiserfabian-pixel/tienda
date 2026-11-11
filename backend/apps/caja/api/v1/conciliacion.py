"""API de la conciliación bancaria: importar el extracto, emparejarlo con el libro y cerrarlo."""

from decimal import Decimal

from django.db.models import Count, Q
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.caja import conciliacion
from apps.caja.models import EstadoCuenta, LineaEstadoCuenta, MovimientoCaja
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.mantenimiento.importacion import ErrorImportacion
from apps.mantenimiento.models import ConceptoCaja, CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada

from .serializers import MovimientoSerializer
from .views import TAG, _entero, _fecha

VER = "CAJA.CONCILIACION.VER"
GESTIONAR = "CAJA.CONCILIACION.GESTIONAR"
CERRAR = "CAJA.CONCILIACION.CERRAR"


class LineaSerializer(serializers.ModelSerializer):
    union_nombre = serializers.CharField(source="get_union_display", read_only=True)
    movimiento_numero = serializers.IntegerField(
        source="movimiento.numero", default=None, read_only=True
    )
    movimiento_concepto = serializers.CharField(
        source="movimiento.concepto.nombre", default=None, read_only=True
    )

    class Meta:
        model = LineaEstadoCuenta
        fields = [
            "id",
            "orden",
            "fecha",
            "descripcion",
            "referencia",
            "monto",
            "saldo",
            "movimiento",
            "movimiento_numero",
            "movimiento_concepto",
            "union",
            "union_nombre",
            "conciliada_en",
            "conciliada_por_nombre",
        ]
        read_only_fields = fields


class EstadoCuentaSerializer(serializers.ModelSerializer):
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    moneda = serializers.CharField(source="cuenta.moneda", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    lineas_total = serializers.SerializerMethodField()
    lineas_pendientes = serializers.SerializerMethodField()
    resumen = serializers.SerializerMethodField()

    class Meta:
        model = EstadoCuenta
        fields = [
            "id",
            "numero",
            "empresa",
            "cuenta",
            "cuenta_nombre",
            "moneda",
            "desde",
            "hasta",
            "saldo_inicial_banco",
            "saldo_final_banco",
            "archivo_nombre",
            "estado",
            "estado_nombre",
            "importado_por_nombre",
            "cerrado_en",
            "cerrado_por_nombre",
            "nota_cierre",
            "reaperturas",
            "creado_en",
            "lineas_total",
            "lineas_pendientes",
            "resumen",
        ]
        read_only_fields = fields

    def get_lineas_total(self, e) -> int:
        return e.total if hasattr(e, "total") else e.lineas.count()

    def get_lineas_pendientes(self, e) -> int:
        if hasattr(e, "pendientes"):
            return e.pendientes
        return e.lineas.filter(movimiento__isnull=True).count()

    def get_resumen(self, e):
        return _textos(conciliacion.resumen(e)) if self.context.get("con_resumen") else None


class _ArchivoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    archivo = serializers.FileField(max_length=200, allow_empty_file=False)


class ImportarEntrada(_ArchivoEntrada):
    saldo_inicial = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, allow_null=True
    )
    saldo_final = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, allow_null=True
    )


class ConciliarEntrada(serializers.Serializer):
    movimiento = serializers.IntegerField(min_value=1)


class RegistrarEntrada(serializers.Serializer):
    concepto = serializers.IntegerField(min_value=1)
    glosa = serializers.CharField(max_length=250, required=False, allow_blank=True)


class CerrarEntrada(serializers.Serializer):
    nota = serializers.CharField(max_length=250, required=False, allow_blank=True)


class ReabrirEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


def _textos(valor):
    """Importes como texto de dos decimales (los Decimal viajan como texto, no como flotante)."""
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    if isinstance(valor, dict):
        return {k: _textos(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_textos(v) for v in valor]
    return valor


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


def _cuenta_de(empresa: Empresa, cuenta_id: int) -> CuentaFinanciera:
    cuenta = CuentaFinanciera.objects.filter(empresa=empresa, pk=cuenta_id).first()
    if cuenta is None:
        raise ValidationError({"cuenta": "Elija una cuenta de la empresa."})
    return cuenta


class EstadoCuentaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Estados de cuenta importados (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``cuenta``, ``estado``, ``desde`` y ``hasta``. Importar: ``POST`` con el archivo.
    """

    modelo = EstadoCuenta
    serializer_class = EstadoCuentaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "lineas": VER,
        "create": GESTIONAR,
        "previsualizar": GESTIONAR,
        "automatica": GESTIONAR,
        "descartar": GESTIONAR,
        "cerrar": CERRAR,
        "reabrir": CERRAR,
    }

    def get_throttles(self):
        if self.action in ("create", "previsualizar"):
            return [ApiAutenticadaThrottle()]
        return super().get_throttles()

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                EstadoCuenta.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["con_resumen"] = self.action == "retrieve"
        return contexto

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = EstadoCuenta.objects.select_related("cuenta").annotate(
            total=Count("lineas"), pendientes=Count("lineas", filter=Q(lineas__movimiento=None))
        )
        if self.action != "list":
            return filtrar_por_alcance(queryset, self.request.user, codigo)
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (cuenta := _entero(params, "cuenta")) is not None:
            queryset = queryset.filter(cuenta_id=cuenta)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(hasta__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(desde__lte=hasta)
        return queryset.order_by("-hasta", "-id")

    # -- importar -----------------------------------------------------------------
    @extend_schema(tags=TAG, request=_ArchivoEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="previsualizar")
    def previsualizar(self, request):
        """Lee el extracto y dice qué se importaría, sin guardar nada."""
        datos = _ArchivoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        try:
            return Response(
                _textos(
                    conciliacion.previsualizar(
                        empresa=empresa,
                        cuenta=_cuenta_de(empresa, v["cuenta"]),
                        archivo=v["archivo"],
                    )
                )
            )
        except ErrorImportacion as e:
            raise ValidationError({"archivo": str(e)}) from None

    @extend_schema(tags=TAG, request=ImportarEntrada, responses={201: EstadoCuentaSerializer})
    def create(self, request, *args, **kwargs):
        datos = ImportarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        try:
            estado = conciliacion.importar(
                empresa=empresa,
                cuenta=_cuenta_de(empresa, v["cuenta"]),
                archivo=v["archivo"],
                usuario=request.user,
                saldo_inicial=v.get("saldo_inicial"),
                saldo_final=v.get("saldo_final"),
            )
        except ErrorImportacion as e:
            raise ValidationError({"archivo": str(e)}) from None
        estado = self.get_queryset().get(pk=estado.pk)
        return Response(EstadoCuentaSerializer(estado).data, status=201)

    # -- las líneas del extracto --------------------------------------------------
    @extend_schema(tags=TAG, responses={200: LineaSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="lineas")
    def lineas(self, request, pk=None):
        """Líneas del extracto. Filtros: ``estado`` (pendiente o conciliada) y ``q``."""
        estado = self.get_object()
        queryset = estado.lineas.select_related("movimiento__concepto")
        filtro = request.query_params.get("estado")
        if filtro == "pendiente":
            queryset = queryset.filter(movimiento__isnull=True)
        elif filtro == "conciliada":
            queryset = queryset.filter(movimiento__isnull=False)
        q = (request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(Q(descripcion__icontains=q) | Q(referencia__icontains=q))
        pagina = self.paginate_queryset(queryset.order_by("fecha", "orden"))
        return self.get_paginated_response(LineaSerializer(pagina, many=True).data)

    # -- conciliar ----------------------------------------------------------------
    @extend_schema(tags=TAG, request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="automatica")
    def automatica(self, request, pk=None):
        """Une las líneas que tienen un solo movimiento posible."""
        estado = self.get_object()
        unidas = conciliacion.conciliar_automaticamente(estado, request.user)
        return Response({"unidas": unidas})

    @extend_schema(tags=TAG, request=CerrarEntrada, responses={200: EstadoCuentaSerializer})
    @action(detail=True, methods=["post"], url_path="cerrar")
    def cerrar(self, request, pk=None):
        datos = CerrarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        estado = conciliacion.cerrar(
            self.get_object(), usuario=request.user, nota=datos.validated_data.get("nota", "")
        )
        return Response(
            EstadoCuentaSerializer(
                self.get_queryset().get(pk=estado.pk), context={"con_resumen": True}
            ).data
        )

    @extend_schema(tags=TAG, request=ReabrirEntrada, responses={200: EstadoCuentaSerializer})
    @action(detail=True, methods=["post"], url_path="reabrir")
    def reabrir(self, request, pk=None):
        datos = ReabrirEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        estado = conciliacion.reabrir(
            self.get_object(), motivo=datos.validated_data["motivo"], usuario=request.user
        )
        return Response(
            EstadoCuentaSerializer(
                self.get_queryset().get(pk=estado.pk), context={"con_resumen": True}
            ).data
        )

    @extend_schema(tags=TAG, request=None, responses={204: None})
    @action(detail=True, methods=["post"], url_path="descartar")
    def descartar(self, request, pk=None):
        """Quita un extracto importado por error (sin líneas conciliadas)."""
        conciliacion.descartar(self.get_object(), request.user)
        return Response(status=204)


class LineaEstadoCuentaViewSet(ScopedQuerysetMixin, viewsets.GenericViewSet):
    """Acciones sobre una línea del extracto: ver candidatos, unir, registrar y deshacer."""

    modelo = LineaEstadoCuenta
    serializer_class = LineaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    parser_classes = [JSONParser]
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "candidatos": GESTIONAR,
        "conciliar": GESTIONAR,
        "registrar": GESTIONAR,
        "deshacer": GESTIONAR,
    }

    def empresas_de_la_operacion(self, request):
        empresa_id = (
            LineaEstadoCuenta.objects.filter(pk=self.kwargs.get("pk"))
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        return filtrar_por_alcance(
            LineaEstadoCuenta.objects.select_related("estado_cuenta", "cuenta", "movimiento"),
            self.request.user,
            codigo,
        )

    @extend_schema(tags=TAG, responses={200: MovimientoSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="candidatos")
    def candidatos(self, request, pk=None):
        """Movimientos del libro que podrían ser esta línea (``?dias=`` de margen, hasta 31)."""
        linea = self.get_object()
        dias = _entero(request.query_params, "dias")
        lista = conciliacion.candidatos(linea, 5 if dias is None else dias)
        return Response(MovimientoSerializer(lista, many=True).data)

    @extend_schema(tags=TAG, request=ConciliarEntrada, responses={200: LineaSerializer})
    @action(detail=True, methods=["post"], url_path="conciliar")
    def conciliar(self, request, pk=None):
        linea = self.get_object()
        datos = ConciliarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        movimiento = MovimientoCaja.objects.filter(
            pk=datos.validated_data["movimiento"], empresa_id=linea.empresa_id
        ).first()
        if movimiento is None:
            raise ValidationError({"movimiento": "Elija un movimiento de la cuenta."})
        return Response(
            LineaSerializer(conciliacion.conciliar(linea, movimiento, request.user)).data
        )

    @extend_schema(tags=TAG, request=RegistrarEntrada, responses={200: LineaSerializer})
    @action(detail=True, methods=["post"], url_path="registrar")
    def registrar(self, request, pk=None):
        """Anota en el libro lo que el banco cobró o abonó y queda conciliado."""
        linea = self.get_object()
        datos = RegistrarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        concepto = ConceptoCaja.objects.filter(
            pk=datos.validated_data["concepto"],
            organizacion_id=linea.empresa.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            automatico=False,
        ).first()
        if concepto is None:
            raise ValidationError({"concepto": "Elija un concepto activo."})
        hecha = conciliacion.registrar_partida(
            linea,
            concepto=concepto,
            usuario=request.user,
            glosa=datos.validated_data.get("glosa", ""),
        )
        return Response(LineaSerializer(hecha).data)

    @extend_schema(tags=TAG, request=None, responses={200: LineaSerializer})
    @action(detail=True, methods=["post"], url_path="deshacer")
    def deshacer(self, request, pk=None):
        return Response(
            LineaSerializer(conciliacion.desconciliar(self.get_object(), request.user)).data
        )
