"""API de las guías de remisión: qué falta enviar, emitir, consultar, anular y exportar."""

import json
import logging
from decimal import Decimal

from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.caja.reportes import nombre_archivo
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle, MostradorThrottle
from apps.mantenimiento.api.v1.campos import CampoUbigeo
from apps.mantenimiento.models import (
    Almacen,
    Cliente,
    Conductor,
    EmpresaTransporte,
    Ubigeo,
    Vehiculo,
)
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.ventas import guias, reportes
from apps.ventas.models import (
    ComprobanteVenta,
    GuiaRemision,
    LineaGuia,
    LineaVenta,
    ModalidadTransporte,
    MotivoTraslado,
)

from .notas_credito import ComprobanteDevolvibleSerializer, _por_cliente, _por_numero
from .serializers import AnulacionVentaEntrada
from .views import TAG, VER, _entero, _fecha, _nombre_empresa, _nombre_usuario

EMITIR = "VENTAS.GUIA_REMISION"
EXPORTAR = "VENTAS.EXPORTAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAXIMO_EXCEL = 20_000  # filas que admite un Excel: más se piden por rangos de fechas

logger = logging.getLogger(__name__)


class LineaEnvioEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    peso_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False
    )


class GuiaEntrada(serializers.Serializer):
    lineas = LineaEnvioEntrada(many=True, allow_empty=False, max_length=100)
    fecha_traslado = serializers.DateField()
    motivo = serializers.ChoiceField(choices=MotivoTraslado.choices, required=False)
    modalidad = serializers.ChoiceField(choices=ModalidadTransporte.choices)
    # La serie de la guía, si la empresa tiene varias.
    serie_guia = serializers.IntegerField(min_value=1, required=False)
    # Otro cliente registrado como destinatario (por defecto, el de la venta).
    destinatario = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    punto_partida = serializers.CharField(max_length=250)
    ubigeo_partida = CampoUbigeo()
    punto_llegada = serializers.CharField(max_length=250)
    ubigeo_llegada = CampoUbigeo()
    almacen_origen = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    traslado_m1_l = serializers.BooleanField(required=False)
    # Quién lo lleva: lo elegido de las listas de Mantenimiento, o escrito a mano.
    transportista = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    transportista_nombre = serializers.CharField(max_length=250, required=False, allow_blank=True)
    transportista_documento = serializers.CharField(max_length=20, required=False, allow_blank=True)
    conductor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    conductor_nombre = serializers.CharField(max_length=150, required=False, allow_blank=True)
    conductor_licencia = serializers.CharField(max_length=20, required=False, allow_blank=True)
    vehiculo = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    placa = serializers.CharField(max_length=10, required=False, allow_blank=True)
    vehiculos_secundarios = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=10
    )
    peso_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False
    )
    bultos = serializers.IntegerField(min_value=1, max_value=100_000, required=False)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)


class LineaGuiaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineaGuia
        fields = ["id", "descripcion", "unidad", "cantidad", "peso_kg"]
        read_only_fields = fields


class GuiaSerializer(serializers.ModelSerializer):
    numero_completo = serializers.CharField(read_only=True)
    # La guía de un traspaso no tiene comprobante: en su lugar trae el traspaso del que sale.
    comprobante_numero = serializers.CharField(
        source="comprobante.numero_completo", default="", read_only=True
    )
    comprobante_tipo = serializers.CharField(
        source="comprobante.tipo_comprobante.nombre", default="", read_only=True
    )
    comprobante_fecha = serializers.DateField(
        source="comprobante.fecha", default=None, read_only=True
    )
    traspaso = serializers.IntegerField(source="movimiento_salida_id", default=None, read_only=True)
    traspaso_numero = serializers.IntegerField(
        source="movimiento_salida.numero", default=None, read_only=True
    )
    motivo_nombre = serializers.CharField(source="get_motivo_display", read_only=True)
    modalidad_nombre = serializers.CharField(source="get_modalidad_display", read_only=True)
    usuario = serializers.CharField(source="emitida_por_nombre", read_only=True)

    class Meta:
        model = GuiaRemision
        fields = [
            "id",
            "empresa",
            "comprobante",
            "comprobante_numero",
            "comprobante_tipo",
            "comprobante_fecha",
            "traspaso",
            "traspaso_numero",
            "numero_completo",
            "fecha_emision",
            "fecha_traslado",
            "usuario",
            "destinatario_nombre",
            "destinatario_tipo_documento",
            "destinatario_documento",
            "punto_llegada",
            "motivo",
            "motivo_nombre",
            "modalidad",
            "modalidad_nombre",
            "transportista_nombre",
            "placa",
            "conductor_nombre",
            "bultos",
            "peso_kg",
            "estado",
        ]
        read_only_fields = fields


class GuiaDetalleSerializer(GuiaSerializer):
    lineas = LineaGuiaSerializer(many=True, read_only=True)
    emisor = serializers.SerializerMethodField()
    venta = serializers.IntegerField(source="comprobante.venta_id", default=None, read_only=True)
    almacen_origen_nombre = serializers.CharField(
        source="almacen_origen.nombre", default="", read_only=True
    )
    ubigeo_partida_nombre = serializers.SerializerMethodField()
    ubigeo_llegada_nombre = serializers.SerializerMethodField()

    class Meta(GuiaSerializer.Meta):
        fields = [
            *GuiaSerializer.Meta.fields,
            "venta",
            "destinatario",
            "punto_partida",
            "ubigeo_partida",
            "ubigeo_partida_nombre",
            "ubigeo_llegada",
            "ubigeo_llegada_nombre",
            "almacen_origen",
            "almacen_origen_nombre",
            "traslado_m1_l",
            "transportista",
            "transportista_documento",
            "transportista_mtc",
            "transportista_certificado",
            "conductor",
            "conductor_documento",
            "conductor_licencia",
            "vehiculo",
            "vehiculo_descripcion",
            "placas_secundarias",
            "observacion",
            "emitida_por_nombre",
            "motivo_anulacion",
            "lineas",
            "emisor",
        ]
        read_only_fields = fields

    def _nombre_de(self, codigo: str) -> str:
        if not codigo:
            return ""
        ubigeo = Ubigeo.objects.filter(codigo=codigo).first()
        return ubigeo.nombre_completo if ubigeo else ""

    def get_ubigeo_partida_nombre(self, guia) -> str:
        return self._nombre_de(guia.ubigeo_partida)

    def get_ubigeo_llegada_nombre(self, guia) -> str:
        return self._nombre_de(guia.ubigeo_llegada)

    def get_emisor(self, guia) -> dict:
        e = guia.empresa
        return {
            "empresa": e.pk,
            "tiene_logo": bool(e.logo),
            "nombre": _nombre_empresa(e),
            "ruc": e.ruc,
            "direccion": e.direccion_fiscal,
        }


def _detalle(pk: int) -> GuiaRemision:
    return (
        GuiaRemision.objects.select_related(
            "comprobante__tipo_comprobante", "movimiento_salida", "empresa", "almacen_origen"
        )
        .prefetch_related(Prefetch("lineas", queryset=LineaGuia.objects.order_by("orden")))
        .get(pk=pk)
    )


def _filtrar_guias(queryset, params):
    """Los filtros del listado de guías (empresa, fechas, estado y texto); los usa el Excel."""
    queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
    if (desde := _fecha(params, "desde")) is not None:
        queryset = queryset.filter(fecha_emision__gte=desde)
    if (hasta := _fecha(params, "hasta")) is not None:
        queryset = queryset.filter(fecha_emision__lte=hasta)
    if estado := params.get("estado"):
        queryset = queryset.filter(estado=estado)
    if q := (params.get("q") or "").strip()[:60]:
        queryset = queryset.filter(
            Q(destinatario_nombre__icontains=q)
            | Q(destinatario_documento__icontains=q)
            | Q(placa__icontains=q)
            | _por_numero(q)
            | _por_numero(q, "comprobante__")
        )
    return queryset.order_by("-fecha_emision", "-id")


class GuiaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Guías de remisión de una empresa (``?empresa=ID`` obligatorio en el listado)."""

    modelo = GuiaRemision
    serializer_class = GuiaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {"list": VER, "retrieve": VER, "anular": EMITIR}

    def get_serializer_class(self):
        return GuiaDetalleSerializer if self.action == "retrieve" else GuiaSerializer

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                GuiaRemision.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = GuiaRemision.objects.select_related(
            "comprobante__tipo_comprobante", "movimiento_salida", "empresa", "almacen_origen"
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch("lineas", queryset=LineaGuia.objects.order_by("orden"))
            )
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        return _filtrar_guias(queryset, self.request.query_params)

    @extend_schema(tags=TAG, request=AnulacionVentaEntrada, responses={200: GuiaDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        guia = self.get_object()
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        guias.anular_guia(guia, motivo=datos.validated_data["motivo"])
        return Response(GuiaDetalleSerializer(_detalle(guia.pk)).data)


class GuiasExcelView(APIView):
    """El listado de guías de remisión (con los mismos filtros de la pantalla) en Excel."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = EXPORTAR
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle, ExportacionThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("desde", str, description="AAAA-MM-DD"),
            OpenApiParameter("hasta", str, description="AAAA-MM-DD"),
            OpenApiParameter("estado", str),
            OpenApiParameter("q", str),
        ],
        responses={(200, "application/octet-stream"): bytes},
    )
    def get(self, request):
        params = request.query_params
        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        guias_filtradas = _filtrar_guias(
            filtrar_por_alcance(
                GuiaRemision.objects.select_related("comprobante", "movimiento_salida", "empresa"),
                request.user,
                EXPORTAR,
            ),
            params,
        )[: MAXIMO_EXCEL + 1]
        filas = [
            {
                "fecha": g.fecha_emision,
                "numero": g.numero_completo,
                "usuario": g.emitida_por_nombre,
                "destinatario": g.destinatario_nombre,
                "documento": g.destinatario_documento,
                "comprobante": g.comprobante.numero_completo
                if g.comprobante_id
                else f"Traspaso N° {g.movimiento_salida.numero:06d}",
                "motivo": g.get_motivo_display(),
                "traslado": g.fecha_traslado,
                "transporte": "Público"
                if g.modalidad == ModalidadTransporte.PUBLICO
                else "Privado",
                "transportista": g.transportista_nombre,
                "conductor": g.conductor_nombre,
                "placa": g.placa,
                "partida": g.punto_partida,
                "llegada": g.punto_llegada,
                "bultos": g.bultos,
                "peso": g.peso_kg,
                "estado": "Anulada" if g.estado == GuiaRemision.Estado.ANULADO else "Vigente",
            }
            for g in guias_filtradas
        ]
        if len(filas) > MAXIMO_EXCEL:
            raise ValidationError(
                {"desde": f"Hay más de {MAXIMO_EXCEL} guías: acote las fechas para exportarlas."}
            )
        contenido = reportes.guias_excel(
            empresa, filas, _fecha(params, "desde"), _fecha(params, "hasta")
        )
        nombre = nombre_archivo("ventas-guias-remision", empresa, f"{timezone.localdate():%Y%m%d}")
        registrar(
            "ventas.guias_exportadas",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Guías de remisión exportadas: {nombre}",
            detalle={"filas": len(filas)},
        )
        logger.info("guias_exportadas", extra={"empresa_id": empresa.pk, "filas": len(filas)})
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class _DeComprobante(APIView):
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = EMITIR
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        empresa_id = (
            ComprobanteVenta.objects.filter(pk=self.kwargs["comprobante_id"])
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    def comprobante(self) -> ComprobanteVenta:
        c = (
            filtrar_por_alcance(
                ComprobanteVenta.objects.select_related(
                    "venta", "empresa", "venta__cliente", "venta__sucursal", "tipo_comprobante"
                ),
                self.request.user,
                EMITIR,
            )
            .filter(pk=self.kwargs["comprobante_id"])
            .first()
        )
        if c is None:
            raise Http404
        return c


class EnviablesView(generics.ListAPIView):
    """Buscar el comprobante de una empresa al que se le hará una guía de remisión.

    Solo trae comprobantes emitidos a los que todavía les queda algo por enviar. Filtros:
    ``empresa`` (obligatorio), ``q`` (cliente, documento, serie o número; también «F001-1724»),
    ``desde`` y ``hasta`` (fecha del comprobante).
    """

    serializer_class = ComprobanteDevolvibleSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = EMITIR
    pagination_class = PaginaEstandar
    requiere_empresa = True
    throttle_classes = [MostradorThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ComprobanteVenta.objects.none()
        params = self.request.query_params
        queryset = filtrar_por_alcance(
            ComprobanteVenta.objects.select_related("venta", "tipo_comprobante"),
            self.request.user,
            EMITIR,
        ).filter(
            empresa_id=empresa_declarada(self.request, self),
            estado=ComprobanteVenta.Estado.EMITIDO,
        )
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        if q := (params.get("q") or "").strip()[:60]:
            queryset = queryset.filter(_por_cliente(q) | _por_numero(q))
        return guias.con_algo_por_enviar(queryset).order_by("-fecha", "-id")


def _ubigeo(codigo: str) -> dict:
    if not codigo:
        return {"codigo": "", "nombre": ""}
    ubigeo = Ubigeo.objects.filter(codigo=codigo).first()
    return {"codigo": codigo, "nombre": ubigeo.nombre_completo if ubigeo else ""}


def _partida(c: ComprobanteVenta, almacen) -> tuple[str, str]:
    """Desde dónde sale lo que viaja: el almacén, si no la tienda y si no la dirección fiscal."""
    sucursal = c.venta.sucursal
    direccion = next(
        (o.direccion for o in (almacen, sucursal) if o is not None and o.direccion),
        c.empresa.direccion_fiscal,
    )
    ubigeo = next((o.ubigeo for o in (almacen, sucursal) if o is not None and o.ubigeo), "")
    return direccion, ubigeo


class PendienteView(_DeComprobante):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, comprobante_id: int):
        """Lo que falta enviar del comprobante y los datos que la guía propone.

        Trae al remitente, al destinatario (el cliente de la venta), los puntos de partida y de
        llegada con su ubigeo, el almacén de origen, las series posibles y cada línea con lo
        que le falta enviar.
        """
        c = self.comprobante()
        venta, empresa = c.venta, c.empresa
        cliente = venta.cliente
        pendientes = guias.pendiente_de_enviar(c)
        almacen = guias.almacen_de_origen([p["linea"] for p in pendientes])
        partida, ubigeo_partida = _partida(c, almacen)
        llegada = cliente.direccion if cliente else ""
        ubigeo_llegada = cliente.ubigeo if cliente else ""
        anulado = c.estado == ComprobanteVenta.Estado.ANULADO
        respuesta = Response(
            {
                "comprobante": c.pk,
                "empresa": empresa.pk,
                "venta": venta.pk,
                "numero_completo": c.numero_completo,
                "tipo_codigo": c.tipo_comprobante.codigo,
                "tipo_nombre": c.tipo_comprobante.nombre,
                "fecha": c.fecha.isoformat(),
                "anulado": anulado,
                "se_puede_enviar": not anulado and any(p["pendiente"] > 0 for p in pendientes),
                "remitente": {"nombre": empresa.razon_social, "ruc": empresa.ruc},
                "destinatario": venta.cliente_nombre,
                "destinatario_datos": {
                    "cliente": cliente.pk if cliente else None,
                    "nombre": venta.cliente_nombre,
                    "tipo_documento": venta.cliente_tipo_documento,
                    "documento": venta.cliente_documento,
                },
                "punto_partida": partida,
                "ubigeo_partida": _ubigeo(ubigeo_partida),
                "punto_llegada": llegada,
                "ubigeo_llegada": _ubigeo(ubigeo_llegada),
                "almacen_origen": {"id": almacen.pk, "nombre": almacen.nombre} if almacen else None,
                **guias.series_para_elegir(empresa, venta.sucursal),
                "lineas": [
                    {
                        "id": p["linea"].pk,
                        "codigo": p["linea"].producto.codigo,
                        "descripcion": p["linea"].descripcion,
                        "unidad": p["linea"].producto.unidad.abreviatura,
                        "cantidad": str(p["linea"].cantidad),
                        "enviado": str(p["enviado"]),
                        "pendiente": str(p["pendiente"]),
                    }
                    for p in pendientes
                ],
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


def _del_catalogo(modelo, pk, organizacion_id: int, campo: str):
    """El registro de un catálogo (de la organización) que se eligió por su id."""
    if pk is None:
        return None
    objeto = modelo.objects.filter(pk=pk, organizacion_id=organizacion_id).first()
    if objeto is None:
        raise ValidationError({campo: "No existe."})
    return objeto


def _transporte_elegido(v: dict, organizacion_id: int) -> tuple[dict, list[Vehiculo]]:
    """Lo que se eligió de las listas de transporte: empresa, conductor, vehículo y secundarios."""
    ids_secundarios = v.get("vehiculos_secundarios", [])
    secundarios = list(
        Vehiculo.objects.filter(pk__in=ids_secundarios, organizacion_id=organizacion_id)
    )
    if len(secundarios) != len(set(ids_secundarios)):
        raise ValidationError({"vehiculos_secundarios": "Hay vehículos que no existen."})
    elegido = {
        "transportista": _del_catalogo(
            EmpresaTransporte, v.get("transportista"), organizacion_id, "transportista"
        ),
        "conductor": _del_catalogo(Conductor, v.get("conductor"), organizacion_id, "conductor"),
        "vehiculo": _del_catalogo(Vehiculo, v.get("vehiculo"), organizacion_id, "vehiculo"),
    }
    return elegido, secundarios


class EmitirView(_DeComprobante):
    @extend_schema(
        tags=TAG,
        request=GuiaEntrada,
        responses={201: GuiaDetalleSerializer},
        parameters=[
            OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
        ],
    )
    def post(self, request, comprobante_id: int):
        comprobante = self.comprobante()
        datos = GuiaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        organizacion = comprobante.empresa.organizacion_id
        por_id = {
            ln.pk: ln
            for ln in LineaVenta.objects.select_related("producto__unidad", "almacen").filter(
                comprobante=comprobante
            )
        }
        lineas = []
        for d in v["lineas"]:
            if d["linea"] not in por_id:
                raise ValidationError({"lineas": "Hay líneas que no son de este comprobante."})
            lineas.append((por_id[d["linea"]], d["cantidad"], d.get("peso_kg", Decimal("0"))))
        transporte, secundarios = _transporte_elegido(v, organizacion)
        almacen = None
        if v.get("almacen_origen"):
            almacen = Almacen.objects.filter(
                pk=v["almacen_origen"], empresa=comprobante.empresa
            ).first()
            if almacen is None:
                raise ValidationError({"almacen_origen": "No existe."})
        catalogos = {
            "destinatario": _del_catalogo(
                Cliente, v.get("destinatario"), organizacion, "destinatario"
            ),
            **transporte,
        }
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            guia = guias.crear_guia(
                comprobante,
                lineas=lineas,
                punto_partida=v["punto_partida"],
                punto_llegada=v["punto_llegada"],
                fecha_traslado=v["fecha_traslado"],
                modalidad=v["modalidad"],
                motivo=v.get("motivo", MotivoTraslado.VENTA),
                serie_id=v.get("serie_guia"),
                ubigeo_partida=v.get("ubigeo_partida", ""),
                ubigeo_llegada=v.get("ubigeo_llegada", ""),
                almacen_origen=almacen,
                traslado_m1_l=v.get("traslado_m1_l", False),
                transportista_nombre=v.get("transportista_nombre", ""),
                transportista_documento=v.get("transportista_documento", ""),
                placa=v.get("placa", ""),
                conductor_nombre=v.get("conductor_nombre", ""),
                conductor_licencia=v.get("conductor_licencia", ""),
                vehiculos_secundarios=secundarios,
                peso_kg=v.get("peso_kg"),
                bultos=v.get("bultos", 1),
                observacion=v.get("observacion", ""),
                usuario_nombre=_nombre_usuario(request.user),
                **catalogos,
            )
            return 201, json.loads(
                json.dumps(GuiaDetalleSerializer(_detalle(guia.pk)).data, default=str)
            )

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
