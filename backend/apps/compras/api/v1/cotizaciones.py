"""API de cotizaciones de compra.

* ``/compras/cotizaciones/``: listar, ver (con el comparativo), crear (idempotente), editar, sumar o
  quitar proveedores, registrar la respuesta de un proveedor a mano o desde un Excel, marcar que un
  proveedor no cotiza, adjudicar (crea las órdenes de compra) y anular.
* ``/compras/cotizaciones/{id}/plantilla/``: el Excel que se le entrega al proveedor.

Los importes viajan como texto (sin notación científica); las cantidades con tres decimales.
"""

import json
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.caja.reportes import nombre_archivo
from apps.compras import cotizaciones as servicio
from apps.compras import importacion_cotizacion as importacion
from apps.compras.models import (
    FormaPago,
    LineaSolicitudCotizacion,
    Moneda,
    RespuestaCotizacion,
    SolicitudCotizacion,
)
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle, ImportacionThrottle
from apps.mantenimiento.importacion import ErrorImportacion
from apps.mantenimiento.models import Almacen, PresentacionProducto, Producto, Proveedor
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import AnulacionCompraEntrada
from .views import _entero, _fecha, _plano, _uno

TAG = ["compras"]
VER = "COTIZACIONES_COMPRA.VER"
CREAR = "COTIZACIONES_COMPRA.CREAR"
ADJUDICAR = "COTIZACIONES_COMPRA.ADJUDICAR"
CREAR_ORDEN = "ORDENES_COMPRA.CREAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _json(valor):
    """Decimales como texto plano, fechas ISO; el resto igual. Sirve para dicts y listas."""
    if isinstance(valor, Decimal):
        return format(valor, "f")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json(v) for v in valor]
    return valor


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class LineaPedidaEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    presentacion = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class _CuerpoSolicitud(serializers.Serializer):
    almacen = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    fecha_limite = serializers.DateField(required=False, allow_null=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, default=Moneda.PEN)
    precios_incluyen_igv = serializers.BooleanField(default=False)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    proveedores = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=15
    )
    lineas = serializers.ListField(child=LineaPedidaEntrada(), min_length=1, max_length=200)


class SolicitudEntrada(_CuerpoSolicitud):
    empresa = serializers.IntegerField(min_value=1)


class ProveedorEntrada(serializers.Serializer):
    proveedor = serializers.IntegerField(min_value=1)


class RespuestaRefEntrada(serializers.Serializer):
    respuesta = serializers.IntegerField(min_value=1)


class PrecioEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    precio_unitario = serializers.DecimalField(
        max_digits=16, decimal_places=6, min_value=Decimal("0"), required=False, allow_null=True
    )
    cantidad_ofrecida = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        allow_null=True,
    )
    observacion = serializers.CharField(max_length=120, required=False, allow_blank=True)


class RespuestaEntrada(RespuestaRefEntrada):
    forma_pago = serializers.ChoiceField(choices=FormaPago.choices, default=FormaPago.CONTADO)
    plazo_dias = serializers.IntegerField(min_value=0, max_value=365, default=0)
    plazo_entrega_dias = serializers.IntegerField(min_value=0, max_value=365, default=0)
    validez_hasta = serializers.DateField(required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    precios = serializers.ListField(child=PrecioEntrada(), min_length=1, max_length=200)


class DeclinarEntrada(RespuestaRefEntrada):
    motivo = serializers.CharField(max_length=250, required=False, allow_blank=True)


class AsignacionEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    respuesta = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        allow_null=True,
    )


class AdjudicarEntrada(serializers.Serializer):
    asignaciones = serializers.ListField(child=AsignacionEntrada(), min_length=1, max_length=200)


class ImportarEntrada(RespuestaRefEntrada):
    archivo = serializers.FileField()
    accion = serializers.ChoiceField(choices=["revisar", "aplicar"], default="revisar")


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
def _cabecera(s: SolicitudCotizacion, **extra) -> dict:
    return {
        "id": s.pk,
        "numero": s.numero,
        "codigo": s.codigo,
        "empresa": s.empresa_id,
        "estado": s.estado,
        "estado_nombre": s.get_estado_display(),
        "fecha": s.fecha,
        "fecha_limite": s.fecha_limite,
        "almacen": s.almacen_id,
        "almacen_nombre": s.almacen.nombre,
        "moneda": s.moneda,
        "precios_incluyen_igv": s.precios_incluyen_igv,
        "observacion": s.observacion,
        "adjudicada_en": s.adjudicada_en,
        "anulada_en": s.anulada_en,
        "motivo_anulacion": s.motivo_anulacion,
        **extra,
    }


def _detalle(s: SolicitudCotizacion) -> dict:
    """La solicitud completa con su comparativo."""
    lineas = LineaSolicitudCotizacion.objects.filter(solicitud=s).select_related("producto")
    respuestas = RespuestaCotizacion.objects.filter(solicitud=s).select_related("proveedor")
    return _json(
        _cabecera(
            s,
            lineas=[
                {
                    "id": ln.pk,
                    "posicion": ln.posicion,
                    "producto": ln.producto_id,
                    "producto_codigo": ln.producto.codigo,
                    "producto_nombre": ln.producto.nombre,
                    "presentacion": ln.presentacion_id,
                    "unidad": ln.unidad,
                    "cantidad": ln.cantidad,
                }
                for ln in lineas.order_by("posicion")
            ],
            proveedores=[
                {
                    "respuesta": r.pk,
                    "proveedor": r.proveedor_id,
                    "nombre": r.proveedor.nombre,
                    "telefono": r.proveedor.telefono,
                    "correo": r.proveedor.correo,
                    "estado": r.estado,
                    "orden": r.orden_id,
                    "orden_codigo": r.orden.codigo if r.orden_id else None,
                }
                for r in respuestas.order_by("id")
            ],
            comparativo=servicio.comparativo(s),
            emisor={"nombre": s.empresa.razon_social, "ruc": s.empresa.ruc},
        )
    )


# ---------------------------------------------------------------------------
class SolicitudCotizacionViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Cotizaciones de compra de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``estado``, ``proveedor``, ``desde``, ``hasta`` (fecha, AAAA-MM-DD) y ``q`` (número u
    observación).
    """

    modelo = SolicitudCotizacion
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "plantilla": VER,
        "create": CREAR,
        "editar": CREAR,
        "agregar_proveedor": CREAR,
        "quitar_proveedor": CREAR,
        "respuesta": CREAR,
        "declinar": CREAR,
        "importar": CREAR,
        "anular": CREAR,
        "adjudicar": ADJUDICAR,
    }
    serializer_class = serializers.Serializer  # la salida se arma a mano

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                SolicitudCotizacion.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_throttles(self):
        if getattr(self, "action", None) == "importar":
            return [ApiAutenticadaThrottle(), ImportacionThrottle()]
        return [ApiAutenticadaThrottle()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SolicitudCotizacion.objects.none()
        codigo = codigo_requerido(self, self.request)
        queryset = SolicitudCotizacion.objects.select_related("almacen", "empresa")
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        if valor := params.get("estado"):
            queryset = queryset.filter(estado=valor)
        if (proveedor := _entero(params, "proveedor")) is not None:
            queryset = queryset.filter(respuestas__proveedor_id=proveedor)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            condicion = Q(observacion__icontains=q)
            digitos = q.upper().removeprefix("COT-").lstrip("0")
            if digitos.isdigit() and len(digitos) <= 9:
                condicion |= Q(numero=int(digitos))
            queryset = queryset.filter(condicion)
        return queryset.distinct().order_by("-fecha", "-id")

    # -- lectura ---------------------------------------------------------------------------
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().annotate(
            n_lineas=Count("lineas", distinct=True),
            n_proveedores=Count("respuestas", distinct=True),
            n_respondidas=Count(
                "respuestas",
                filter=Q(respuestas__estado=RespuestaCotizacion.Estado.RESPONDIDA),
                distinct=True,
            ),
        )
        pagina = self.paginate_queryset(queryset)
        filas = [
            _json(
                _cabecera(
                    s,
                    lineas=s.n_lineas,
                    proveedores=s.n_proveedores,
                    respondidas=s.n_respondidas,
                )
            )
            for s in pagina
        ]
        return self.get_paginated_response(filas)

    def retrieve(self, request, *args, **kwargs):
        return Response(_detalle(self.get_object()))

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("respuesta", int, required=True)],
        responses={(200, XLSX): bytes},
    )
    @action(detail=True, methods=["get"], url_path="plantilla")
    def plantilla(self, request, pk=None):
        """El Excel con los productos pedidos, listo para que el proveedor ponga sus precios."""
        s = self.get_object()
        respuesta = self._respuesta(s, _entero(request.query_params, "respuesta"))
        contenido = importacion.plantilla(respuesta)
        nombre = nombre_archivo(f"cotizacion-{s.numero}", s.empresa, f"p{respuesta.proveedor_id}")
        r = HttpResponse(contenido, content_type=XLSX)
        r["Content-Disposition"] = f'attachment; filename="{nombre}"'
        r["Cache-Control"] = "no-store"
        r["X-Content-Type-Options"] = "nosniff"
        return r

    # -- armado de argumentos --------------------------------------------------------------
    @staticmethod
    def _respuesta(s: SolicitudCotizacion, respuesta_id) -> RespuestaCotizacion:
        fila = (
            RespuestaCotizacion.objects.select_related("proveedor", "solicitud")
            .filter(pk=respuesta_id, solicitud=s)
            .first()
        )
        if fila is None:
            raise ValidationError({"respuesta": "Ese proveedor no está en esta cotización."})
        return fila

    @staticmethod
    def _argumentos(validados: dict, empresa: Empresa) -> dict:
        almacen = _uno(
            Almacen, validados["almacen"], "almacen", "Elija un almacén de la empresa.",
            empresa=empresa,
        )  # fmt: skip
        ids = validados.get("proveedores", [])
        proveedores = {p.pk: p for p in Proveedor.objects.filter(pk__in=ids)}
        if len(proveedores) != len(set(ids)):
            raise ValidationError({"proveedores": "Hay proveedores que no existen."})
        lineas = validados["lineas"]
        productos = {
            p.pk: p for p in Producto.objects.filter(pk__in={ln["producto"] for ln in lineas})
        }
        pedidas = {ln["presentacion"] for ln in lineas if ln.get("presentacion")}
        presentaciones = {
            p.pk: p
            for p in PresentacionProducto.objects.select_related("unidad").filter(pk__in=pedidas)
        }
        armadas = []
        for ln in lineas:
            producto = productos.get(ln["producto"])
            if producto is None:
                raise ValidationError({"lineas": "Hay productos que no existen."})
            if ln.get("presentacion") and ln["presentacion"] not in presentaciones:
                raise ValidationError({"lineas": "Hay presentaciones que no existen."})
            armadas.append(
                servicio.LineaPedida(
                    producto=producto,
                    cantidad=ln["cantidad"],
                    presentacion=presentaciones.get(ln.get("presentacion")),
                )
            )
        return {
            "almacen": almacen,
            "fecha": validados["fecha"],
            "fecha_limite": validados.get("fecha_limite"),
            "moneda": validados["moneda"],
            "precios_incluyen_igv": validados["precios_incluyen_igv"],
            "observacion": validados.get("observacion", ""),
            "proveedores": [proveedores[i] for i in ids],
            "lineas": armadas,
        }

    def _recargar(self, pk: int) -> dict:
        return _detalle(SolicitudCotizacion.objects.select_related("almacen", "empresa").get(pk=pk))

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

    # -- crear y editar ----------------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=SolicitudEntrada,
        responses={201: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no crea otra cotización.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = SolicitudEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        validados = datos.validated_data
        empresa = Empresa.objects.filter(pk=validados["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        argumentos = self._argumentos(validados, empresa)

        def operacion():
            with transaction.atomic():
                s = servicio.crear_solicitud(empresa=empresa, **argumentos)
            return 201, _plano(self._recargar(s.pk))

        return self._idempotente(request, operacion)

    @extend_schema(tags=TAG, request=_CuerpoSolicitud, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="editar")
    def editar(self, request, pk=None):
        """Cambia una cotización en borrador (sin respuestas con precios)."""
        s = self.get_object()
        datos = _CuerpoSolicitud(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.editar_solicitud(s, **self._argumentos(datos.validated_data, s.empresa))
        return Response(self._recargar(s.pk))

    # -- proveedores y respuestas ----------------------------------------------------------
    @extend_schema(tags=TAG, request=ProveedorEntrada, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="proveedores")
    def agregar_proveedor(self, request, pk=None):
        """Suma un proveedor a una cotización que todavía no se adjudicó."""
        s = self.get_object()
        datos = ProveedorEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        proveedor = _uno(Proveedor, datos.validated_data["proveedor"], "proveedor", "No existe.")
        servicio.agregar_proveedor(s, proveedor)
        return Response(self._recargar(s.pk))

    @extend_schema(tags=TAG, request=RespuestaRefEntrada, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="quitar-proveedor")
    def quitar_proveedor(self, request, pk=None):
        """Saca a un proveedor que todavía no respondió."""
        s = self.get_object()
        datos = RespuestaRefEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.quitar_proveedor(self._respuesta(s, datos.validated_data["respuesta"]))
        return Response(self._recargar(s.pk))

    @extend_schema(tags=TAG, request=RespuestaEntrada, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="respuesta")
    def respuesta(self, request, pk=None):
        """Registra a mano lo que contestó un proveedor (se puede corregir después)."""
        s = self.get_object()
        datos = RespuestaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        servicio.registrar_respuesta(
            self._respuesta(s, v["respuesta"]),
            precios=[
                servicio.PrecioDado(
                    p["linea"],
                    p.get("precio_unitario"),
                    p.get("cantidad_ofrecida"),
                    p.get("observacion", ""),
                )
                for p in v["precios"]
            ],
            forma_pago=v["forma_pago"],
            plazo_dias=v["plazo_dias"],
            plazo_entrega_dias=v["plazo_entrega_dias"],
            validez_hasta=v.get("validez_hasta"),
            observacion=v.get("observacion", ""),
        )
        return Response(self._recargar(s.pk))

    @extend_schema(tags=TAG, request=DeclinarEntrada, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="declinar")
    def declinar(self, request, pk=None):
        """El proveedor avisó que no cotiza: queda fuera de la comparación."""
        s = self.get_object()
        datos = DeclinarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.declinar_respuesta(
            self._respuesta(s, datos.validated_data["respuesta"]),
            motivo=datos.validated_data.get("motivo", ""),
        )
        return Response(self._recargar(s.pk))

    @extend_schema(
        tags=TAG, request={"multipart/form-data": ImportarEntrada}, responses={200: dict}
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="importar",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def importar(self, request, pk=None):
        """Trae la respuesta de un proveedor desde el Excel, en dos pasos: ``accion=revisar``
        informa sin guardar nada y ``accion=aplicar`` la guarda (todo o nada)."""
        s = self.get_object()
        datos = ImportarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        respuesta = self._respuesta(s, v["respuesta"])
        try:
            if v["accion"] == "revisar":
                informe = importacion.revisar(respuesta, v["archivo"])
            else:
                informe = importacion.aplicar(respuesta, v["archivo"])
        except ErrorImportacion as error:
            raise ValidationError({"archivo": str(error)}) from None
        cuerpo = {"accion": v["accion"], "informe": informe.como_dict()}
        if v["accion"] == "aplicar":
            cuerpo["cotizacion"] = self._recargar(s.pk)
        return Response(_json(cuerpo))

    # -- adjudicar y anular ---------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=AdjudicarEntrada,
        responses={200: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no crea las órdenes dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="adjudicar")
    def adjudicar(self, request, pk=None):
        """Elige el ganador de cada producto y crea una orden de compra en borrador por proveedor.

        Exige además poder crear órdenes de compra, porque eso es lo que se genera."""
        s = self.get_object()
        motor.exigir_permiso(request.user, CREAR_ORDEN, s.empresa_id)
        datos = AdjudicarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        asignaciones = [
            servicio.Asignacion(a["linea"], a["respuesta"], a.get("cantidad"))
            for a in datos.validated_data["asignaciones"]
        ]

        def operacion():
            with transaction.atomic():
                servicio.adjudicar(s, asignaciones=asignaciones)
            return 200, _plano(self._recargar(s.pk))

        return self._idempotente(request, operacion)

    @extend_schema(tags=TAG, request=AnulacionCompraEntrada, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula una cotización que todavía no se adjudicó."""
        s = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.anular_solicitud(s, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(s.pk))
