"""API de la toma de inventario físico (``/api/v1/inventario/tomas/``).

La empresa va en ``?empresa=ID`` al listar y al crear; en el resto sale de la propia toma.
En un conteo a ciegas, quien no tiene ``INVENTARIO.TOMAS.APROBAR`` nunca recibe el stock del
sistema, las diferencias ni los importes (ni en el detalle ni en el avance).
"""

import json
from decimal import Decimal

from django.db.models import Q
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.auditoria.servicios import registrar
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle, ImportacionThrottle
from apps.inventario import importacion_toma, tomas
from apps.inventario.exceptions import TomaEstadoInvalido
from apps.inventario.models import (
    AlcanceToma,
    DetalleToma,
    EstadoFisico,
    EstadoToma,
    ResultadoToma,
    TomaInventario,
    TurnoToma,
)
from apps.inventario.reportes import toma as informe_toma
from apps.mantenimiento.importacion import ErrorImportacion
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import AnulacionEntrada
from .views import TAG, _empresa_activa, _entero, _plano

VER = "INVENTARIO.TOMAS.VER"
GESTIONAR = "INVENTARIO.TOMAS.GESTIONAR"
CONTAR = "INVENTARIO.TOMAS.CONTAR"
APROBAR = "INVENTARIO.TOMAS.APROBAR"
EXPORTAR = "INVENTARIO.EXPORTAR"

# Campos del detalle que revelan lo que dice el sistema: se ocultan en un conteo a ciegas.
_CAMPOS_DEL_SISTEMA = (
    "stock_sistema",
    "costo_unitario",
    "diferencia",
    "importe_diferencia",
    "resultado",
    "movimientos_posteriores",
    "diferencia_ajuste",
    "importe_ajuste",
)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class TomaCrearEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    almacen = serializers.IntegerField(min_value=1)
    alcance = serializers.ChoiceField(choices=AlcanceToma.choices, default=AlcanceToma.TODO)
    categorias = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=200
    )
    excluir_productos = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=5000
    )
    conteo_ciego = serializers.BooleanField(default=True)
    responsable = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    umbral_monto = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), default=Decimal("500")
    )
    umbral_porcentaje = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        default=Decimal("10"),
    )


class ConteoEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"))
    estado_fisico = serializers.ChoiceField(
        choices=EstadoFisico.choices, default=EstadoFisico.BUENO
    )
    nota = serializers.CharField(max_length=250, required=False, allow_blank=True)
    turno = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    confirmar_cero = serializers.BooleanField(default=False)


class NotaEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    nota = serializers.CharField(max_length=250)


class SeriesAjusteEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    series = serializers.ListField(
        child=serializers.CharField(max_length=40), min_length=1, max_length=2000
    )


class AprobarEntrada(serializers.Serializer):
    fecha = serializers.DateField(required=False)
    nota = serializers.CharField(max_length=250, required=False, allow_blank=True)
    # Series de los productos que las llevan: las que salen (faltante) o entran (sobrante).
    series = SeriesAjusteEntrada(many=True, required=False)


class ImportarEntrada(serializers.Serializer):
    archivo = serializers.FileField()
    accion = serializers.ChoiceField(choices=["revisar", "importar"], default="revisar")
    modo = serializers.ChoiceField(choices=list(importacion_toma.MODOS), default="automatico")
    importar_ceros = serializers.BooleanField(default=False)


class CierreEntrada(serializers.Serializer):
    confirmar_pendientes = serializers.BooleanField(default=False)


class TurnoEntrada(serializers.Serializer):
    fecha = serializers.DateField()
    turno = serializers.ChoiceField(choices=TurnoToma.Turno.choices)
    hora_inicio = serializers.TimeField()
    equipo = serializers.CharField(max_length=200, required=False, allow_blank=True)


class TurnoFinEntrada(serializers.Serializer):
    hora_fin = serializers.TimeField()


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class TomaSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    categorias = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    productos_excluidos = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    movimientos = serializers.SerializerMethodField()

    class Meta:
        model = TomaInventario
        fields = (
            "id",
            "empresa",
            "almacen",
            "almacen_nombre",
            "numero",
            "estado",
            "estado_nombre",
            "alcance",
            "categorias",
            "productos_excluidos",
            "conteo_ciego",
            "responsable",
            "observacion",
            "umbral_monto",
            "umbral_porcentaje",
            "fecha_corte",
            "abierta_en",
            "cerrada_en",
            "aprobada_en",
            "fecha_ajuste",
            "nota_aprobacion",
            "movimientos",
            "anulada_en",
            "motivo_anulacion",
            "creado_en",
        )
        read_only_fields = fields

    def get_movimientos(self, toma) -> list[dict]:
        """Los ajustes que generó la aprobación (solo cuando se pide la ficha de una toma)."""
        if not self.context.get("con_movimientos"):
            return []
        return [
            {"id": m.pk, "numero": m.numero, "tipo": m.tipo, "estado": m.estado}
            for m in tomas.movimientos_de_ajuste(toma)
        ]


class DetalleTomaSerializer(serializers.ModelSerializer):
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    codigo_barras = serializers.CharField(source="producto.codigo_barras", read_only=True)
    categoria_nombre = serializers.CharField(source="producto.categoria.nombre", read_only=True)
    unidad = serializers.CharField(source="producto.unidad.abreviatura", read_only=True)
    admite_decimales = serializers.SerializerMethodField()

    class Meta:
        model = DetalleToma
        fields = (
            "id",
            "producto",
            "producto_codigo",
            "producto_nombre",
            "codigo_barras",
            "categoria_nombre",
            "unidad",
            "admite_decimales",
            "stock_sistema",
            "costo_unitario",
            "cantidad_contada",
            "diferencia",
            "importe_diferencia",
            "resultado",
            "movimientos_posteriores",
            "diferencia_ajuste",
            "importe_ajuste",
            "estado_fisico",
            "nota",
            "numero_conteos",
            "requiere_reconteo",
            "contado_en",
        )
        read_only_fields = fields

    def get_admite_decimales(self, detalle) -> bool:
        return tomas.unidad_fraccionable(detalle.producto) and not detalle.producto.lleva_serie

    def to_representation(self, detalle):
        datos = super().to_representation(detalle)
        if not self.context.get("ver_sistema", False):
            for campo in _CAMPOS_DEL_SISTEMA:
                datos.pop(campo, None)
        return datos


class TurnoSerializer(serializers.ModelSerializer):
    turno_nombre = serializers.CharField(source="get_turno_display", read_only=True)

    class Meta:
        model = TurnoToma
        fields = ("id", "fecha", "turno", "turno_nombre", "hora_inicio", "hora_fin", "equipo")
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Vista
# ---------------------------------------------------------------------------
class TomaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Tomas de inventario físico de una empresa (``?empresa=ID`` obligatorio al listar).

    Filtros del listado: ``almacen``, ``estado``. Acciones: ``abrir``, ``reconteo``, ``cerrar``,
    ``anular``, ``contar``, ``detalle``, ``avance``, ``turnos``.
    """

    modelo = TomaInventario
    serializer_class = TomaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "detalle": VER,
        "avance": VER,
        "turnos": VER,
        "create": GESTIONAR,
        "abrir": GESTIONAR,
        "reconteo": GESTIONAR,
        "cerrar": GESTIONAR,
        "anular": GESTIONAR,
        "ajustes": APROBAR,
        "aprobar": APROBAR,
        "reporte": APROBAR,
        "importar": GESTIONAR,
        "contar": CONTAR,
        "nota": CONTAR,
        "registrar_turno": CONTAR,
        "finalizar_turno": CONTAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                TomaInventario.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset().select_related("almacen")
        if self.action in ("retrieve", "list"):
            queryset = queryset.prefetch_related("categorias", "productos_excluidos")
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa_id := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa_id)
        if (almacen := _entero(params, "almacen")) is not None:
            queryset = queryset.filter(almacen_id=almacen)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("-numero")

    # -- utilidades -----------------------------------------------------------------
    def _ve_sistema(self, toma: TomaInventario) -> bool:
        """El conteo a ciegas oculta el stock del sistema salvo a quien aprueba."""
        if not toma.conteo_ciego:
            return True
        return motor.tiene_permiso(self.request.user, APROBAR, toma.empresa_id)

    def _responder(self, toma_id: int, codigo: int = 200) -> Response:
        toma = (
            self.get_queryset()
            .prefetch_related("categorias", "productos_excluidos")
            .get(pk=toma_id)
        )
        contexto = {"con_movimientos": True}
        return Response(TomaSerializer(toma, context=contexto).data, status=codigo)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "con_movimientos": self.action == "retrieve"}

    # -- crear ----------------------------------------------------------------------
    @extend_schema(tags=TAG, request=TomaCrearEntrada, responses={201: TomaSerializer})
    def create(self, request, *args, **kwargs):
        datos = TomaCrearEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        toma = tomas.crear_toma(
            empresa=_empresa_activa(v["empresa"]),
            almacen_id=v["almacen"],
            alcance=v["alcance"],
            categorias_ids=v.get("categorias", []),
            excluidos_ids=v.get("excluir_productos", []),
            conteo_ciego=v["conteo_ciego"],
            responsable_id=v.get("responsable"),
            observacion=v.get("observacion", ""),
            umbral_monto=v["umbral_monto"],
            umbral_porcentaje=v["umbral_porcentaje"],
        )
        return self._responder(toma.pk, 201)

    # -- cambios de estado -------------------------------------------------------------
    @extend_schema(tags=TAG, request=None, responses={200: TomaSerializer})
    @action(detail=True, methods=["post"], url_path="abrir")
    def abrir(self, request, pk=None):
        """Congela el stock y el costo de cada producto y abre el conteo."""
        self.get_object()
        tomas.abrir_toma(int(pk))
        return self._responder(int(pk))

    @extend_schema(tags=TAG, request=None, responses={200: TomaSerializer})
    @action(detail=True, methods=["post"], url_path="reconteo")
    def reconteo(self, request, pk=None):
        """Pasa a reconteo: solo se vuelven a contar los productos con diferencia importante."""
        self.get_object()
        tomas.iniciar_reconteo(int(pk))
        return self._responder(int(pk))

    @extend_schema(tags=TAG, request=CierreEntrada, responses={200: TomaSerializer})
    @action(detail=True, methods=["post"], url_path="cerrar")
    def cerrar(self, request, pk=None):
        self.get_object()
        datos = CierreEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        tomas.cerrar_toma(
            int(pk), confirmar_pendientes=datos.validated_data["confirmar_pendientes"]
        )
        return self._responder(int(pk))

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: TomaSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        toma = self.get_object()
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        if toma.estado == EstadoToma.APROBADA:  # deshacer un ajuste ya hecho exige aprobar
            motor.exigir_permiso(request.user, APROBAR, toma.empresa_id)
        tomas.anular_toma(int(pk), motivo=datos.validated_data["motivo"])
        return self._responder(int(pk))

    @extend_schema(tags=TAG, request=AprobarEntrada, responses={200: TomaSerializer})
    @action(detail=True, methods=["post"], url_path="aprobar")
    def aprobar(self, request, pk=None):
        """Aprueba la toma cerrada y genera el ajuste en el Kardex (operación 28)."""
        self.get_object()
        datos = AprobarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        series = {}
        for item in v.get("series", []):
            if item["producto"] in series:
                raise ValidationError({"series": "Un producto se repite en las series."})
            series[item["producto"]] = tuple(item["series"])
        tomas.aprobar_toma(int(pk), fecha=v.get("fecha"), nota=v.get("nota", ""), series=series)
        return self._responder(int(pk))

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("formato", str, enum=["xlsx", "pdf"])],
        responses={(200, "application/octet-stream"): bytes},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="reporte",
        throttle_classes=[ApiAutenticadaThrottle, ExportacionThrottle],
    )
    def reporte(self, request, pk=None):
        """Informe de la toma (Excel o PDF) con el stock del sistema y las diferencias al costo.

        Lo pide quien puede aprobar y exportar: revela lo que el conteo a ciegas oculta.
        """
        toma = self.get_object()
        motor.exigir_permiso(request.user, EXPORTAR, toma.empresa_id)
        formato = request.query_params.get("formato", "xlsx")
        if formato not in ("xlsx", "pdf"):
            raise ValidationError({"formato": "Use xlsx o pdf."})
        if toma.estado == EstadoToma.BORRADOR:
            raise TomaEstadoInvalido("La toma todavía no se abrió: no hay nada que informar.")
        resultado = informe_toma.generar(toma, formato)
        registrar(
            "inventario.toma_exportada",
            recurso_tipo="toma_inventario",
            recurso_id=toma.pk,
            empresa_id=toma.empresa_id,
            resumen=f"Informe de la toma N° {toma.numero:06d} exportado ({formato})",
            detalle={"formato": formato, "filas": resultado.filas},
        )
        respuesta = HttpResponse(resultado.contenido, content_type=resultado.mime)
        respuesta["Content-Disposition"] = f'attachment; filename="{resultado.nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="ajustes")
    def ajustes(self, request, pk=None):
        """Vista previa del ajuste: qué se va a entrar y sacar del Kardex (solo quien aprueba)."""
        toma = self.get_object()
        if toma.estado not in (EstadoToma.CERRADA, EstadoToma.APROBADA):
            raise TomaEstadoInvalido("El ajuste se revisa cuando la toma está cerrada.")
        calculados = tomas.calcular_ajustes(toma)
        con_ajuste = [a for a in calculados if a.diferencia != 0]
        resumen = tomas.resumen_ajustes(calculados)  # siempre sobre todo, filtre o no la lista
        if request.query_params.get("lleva_serie") == "1":
            con_ajuste = [a for a in con_ajuste if a.detalle.producto.lleva_serie]
        pagina = self.paginate_queryset(con_ajuste)
        filas = [
            {
                "producto": a.detalle.producto_id,
                "producto_codigo": a.detalle.producto.codigo,
                "producto_nombre": a.detalle.producto.nombre,
                "lleva_serie": a.detalle.producto.lleva_serie,
                "stock_sistema": a.detalle.stock_sistema,
                "movimientos_posteriores": a.movimientos_posteriores,
                "cantidad_contada": a.detalle.cantidad_contada,
                "tipo": a.tipo,
                "cantidad": a.cantidad,
                "costo_unitario": a.detalle.costo_unitario,
                "importe_estimado": a.importe_estimado,
            }
            for a in pagina
        ]
        respuesta = self.get_paginated_response(_como_texto(filas))
        respuesta.data["resumen"] = _como_texto(resumen)
        return respuesta

    # -- conteo ---------------------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=ConteoEntrada,
        responses={200: DetalleTomaSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento (8 a 128 caracteres): un reintento no "
                "registra el conteo dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="contar")
    def contar(self, request, pk=None):
        """Registra el conteo (o reconteo) de un producto de la toma."""
        toma = self.get_object()
        datos = ConteoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        clave = clave_desde_request(request)
        ver_sistema = self._ve_sistema(toma)

        def operacion():
            detalle = tomas.registrar_conteo(
                toma_id=toma.pk,
                producto_id=v["producto"],
                cantidad=v["cantidad"],
                estado_fisico=v["estado_fisico"],
                nota=v.get("nota", ""),
                turno_id=v.get("turno"),
                confirmar_cero=v["confirmar_cero"],
            )
            detalle = DetalleToma.objects.select_related(
                "producto__unidad", "producto__categoria"
            ).get(pk=detalle.pk)
            return 200, _plano(
                DetalleTomaSerializer(detalle, context={"ver_sistema": ver_sistema}).data
            )

        cuerpo = _cuerpo_estable(request.data)
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
        tags=TAG, request={"multipart/form-data": ImportarEntrada}, responses={200: dict}
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="importar",
        parser_classes=[MultiPartParser, FormParser],
        throttle_classes=[ApiAutenticadaThrottle, ImportacionThrottle],
    )
    def importar(self, request, pk=None):
        """Trae los conteos de un Excel, en dos pasos: ``accion=revisar`` informa sin guardar nada;
        ``accion=importar`` guarda los conteos válidos (todos o ninguno).
        """
        self.get_object()
        datos = ImportarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        opciones = {"modo": v["modo"], "importar_ceros": v["importar_ceros"]}
        try:
            if v["accion"] == "revisar":
                informe = importacion_toma.revisar(int(pk), v["archivo"], **opciones)
            else:
                informe = importacion_toma.importar(int(pk), v["archivo"], **opciones)
        except ErrorImportacion as error:
            raise ValidationError({"archivo": str(error)}) from None
        importados = len(informe.items) if v["accion"] == "importar" else 0
        return Response({**informe.como_dict(), "accion": v["accion"], "importados": importados})

    @extend_schema(tags=TAG, request=NotaEntrada, responses={200: DetalleTomaSerializer})
    @action(detail=True, methods=["post"], url_path="nota")
    def nota(self, request, pk=None):
        """Pone la nota de un producto ya contado (por ejemplo, tras un reconteo)."""
        toma = self.get_object()
        datos = NotaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        detalle = tomas.registrar_nota(
            toma_id=toma.pk,
            producto_id=datos.validated_data["producto"],
            nota=datos.validated_data["nota"],
        )
        detalle = DetalleToma.objects.select_related("producto__unidad", "producto__categoria").get(
            pk=detalle.pk
        )
        contexto = {"ver_sistema": self._ve_sistema(toma)}
        return Response(DetalleTomaSerializer(detalle, context=contexto).data)

    @extend_schema(
        tags=TAG,
        responses={200: DetalleTomaSerializer(many=True)},
        parameters=[
            OpenApiParameter("categoria", int, description="Solo esa categoría."),
            OpenApiParameter("estado", str, description="contado | pendiente."),
            OpenApiParameter("reconteo", int, description="1 = solo los que faltan recontar."),
            OpenApiParameter(
                "sin_nota", int, description="1 = con diferencia importante y sin nota."
            ),
            OpenApiParameter("resultado", str, description="CONFORME, FALTANTE, SOBRANTE."),
            OpenApiParameter("q", str, description="Nombre, código o código de barras."),
        ],
    )
    @action(detail=True, methods=["get"], url_path="detalle")
    def detalle(self, request, pk=None):
        """Hoja de conteo: los productos de la toma, paginados y filtrables."""
        toma = self.get_object()
        ver_sistema = self._ve_sistema(toma)
        params = request.query_params
        queryset = DetalleToma.objects.filter(toma=toma).select_related(
            "producto__unidad", "producto__categoria"
        )
        if (categoria := _entero(params, "categoria")) is not None:
            queryset = queryset.filter(producto__categoria_id=categoria)
        if (estado := params.get("estado")) == "contado":
            queryset = queryset.filter(cantidad_contada__isnull=False)
        elif estado == "pendiente":
            queryset = queryset.filter(cantidad_contada__isnull=True)
        elif estado:
            raise ValidationError({"estado": "Use «contado» o «pendiente»."})
        if params.get("reconteo") == "1":
            queryset = queryset.filter(requiere_reconteo=True)
        if params.get("sin_nota") == "1":
            queryset = queryset.filter(pk__in=tomas.sin_nota(toma).values("pk"))
        if resultado := params.get("resultado"):
            if not ver_sistema:
                raise ValidationError({"resultado": "No está disponible en un conteo a ciegas."})
            if resultado not in ResultadoToma.values:
                raise ValidationError({"resultado": "El resultado no es válido."})
            queryset = queryset.filter(resultado=resultado)
        if q := (params.get("q") or "").strip():
            queryset = queryset.filter(
                Q(producto__nombre__icontains=q)
                | Q(producto__codigo__icontains=q)
                | Q(producto__codigo_barras__icontains=q)
                | Q(producto__codigo_fabricante__icontains=q)
            )
        queryset = queryset.order_by("producto__categoria__nombre", "producto__nombre", "id")
        pagina = self.paginate_queryset(queryset)
        serializer = DetalleTomaSerializer(pagina, many=True, context={"ver_sistema": ver_sistema})
        return self.get_paginated_response(serializer.data)

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="avance")
    def avance(self, request, pk=None):
        """Contados, por contar y porcentaje; el resultado solo si se puede ver el sistema."""
        toma = self.get_object()
        datos = tomas.avance(toma)
        if not self._ve_sistema(toma):
            datos.pop("resultado")
        return Response(_como_texto(datos))

    # -- turnos ---------------------------------------------------------------------------
    @extend_schema(tags=TAG, responses={200: TurnoSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="turnos", pagination_class=None)
    def turnos(self, request, pk=None):
        toma = self.get_object()
        turnos = TurnoToma.objects.filter(toma=toma).order_by("fecha", "hora_inicio", "id")[:200]
        return Response(TurnoSerializer(turnos, many=True).data)

    @extend_schema(tags=TAG, request=TurnoEntrada, responses={201: TurnoSerializer})
    @action(detail=True, methods=["post"], url_path="turnos/nuevo")
    def registrar_turno(self, request, pk=None):
        self.get_object()
        datos = TurnoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        turno = tomas.crear_turno(
            toma_id=int(pk),
            fecha=v["fecha"],
            turno=v["turno"],
            hora_inicio=v["hora_inicio"],
            equipo=v.get("equipo", ""),
        )
        return Response(TurnoSerializer(turno).data, status=201)

    @extend_schema(tags=TAG, request=TurnoFinEntrada, responses={200: TurnoSerializer})
    @action(
        detail=True,
        methods=["post"],
        url_path=r"turnos/(?P<turno_id>\d+)/finalizar",
    )
    def finalizar_turno(self, request, pk=None, turno_id=None):
        self.get_object()
        datos = TurnoFinEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        turno = tomas.finalizar_turno(
            toma_id=int(pk), turno_id=int(turno_id), hora_fin=datos.validated_data["hora_fin"]
        )
        return Response(TurnoSerializer(turno).data)


def _como_texto(valor):
    """Los decimales viajan como texto (sin perder precisión), igual que en los serializers."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, dict):
        return {clave: _como_texto(dato) for clave, dato in valor.items()}
    if isinstance(valor, list):
        return [_como_texto(dato) for dato in valor]
    return valor


def _cuerpo_estable(datos) -> bytes:
    """Huella estable del cuerpo (el cuerpo crudo ya lo consumió el parser de DRF)."""
    return json.dumps(datos, sort_keys=True, default=str).encode()
