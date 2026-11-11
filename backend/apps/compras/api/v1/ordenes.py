"""API de órdenes de compra.

* ``/compras/ordenes/``: listar, ver, crear (idempotente), editar, emitir (idempotente), aprobar,
  rechazar, reabrir, anular y cerrar órdenes; ``calcular`` (vista previa) y ``configuracion``
  (monto desde el que piden aprobación y tolerancia al recibir).
* ``/compras/ordenes/{id}/por-recibir/``: lo que falta recibir, para precargar «Registrar compra».

Recibir la mercadería es registrar una compra con ``orden`` (ver ``views.py``). Los montos viajan
siempre como texto con dos decimales.
"""

import json
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.auditoria.servicios import registrar
from apps.compras import ordenes as servicio
from apps.compras.models import FormaPago, LineaOrdenCompra, Moneda, OrdenCompra
from apps.compras.recepcion import RECIBE
from apps.compras.reposicion import HASTA_POR_DEFECTO, reposicion_sugerida
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    PresentacionProducto,
    Producto,
    Proveedor,
)
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import AnulacionCompraEntrada
from .views import _entero, _fecha, _plano, _uno

TAG = ["compras"]
VER = "ORDENES_COMPRA.VER"
CREAR = "ORDENES_COMPRA.CREAR"
EDITAR = "ORDENES_COMPRA.EDITAR"
APROBAR = "ORDENES_COMPRA.APROBAR"
ANULAR = "ORDENES_COMPRA.ANULAR"
CERRAR = "ORDENES_COMPRA.CERRAR"
RECIBIR = "COMPRAS.CREAR"  # recibir mercadería es registrar una compra

DINERO = {"max_digits": 16, "decimal_places": 2}
CERO = Decimal("0")


def _dinero(valor) -> str:
    return f"{valor:.2f}"


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class LineaOrdenEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    presentacion = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    precio_unitario = serializers.DecimalField(
        max_digits=16, decimal_places=6, min_value=Decimal("0")
    )
    # Código SUNAT de la afectación (10, 20, 30…). Vacío = la que propone el sistema.
    afectacion = serializers.CharField(max_length=2, required=False, allow_blank=True)


class _CuerpoOrden(serializers.Serializer):
    proveedor = serializers.IntegerField(min_value=1)
    almacen = serializers.IntegerField(min_value=1)
    fecha_emision = serializers.DateField()
    fecha_entrega = serializers.DateField(required=False, allow_null=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )
    precios_incluyen_igv = serializers.BooleanField(default=False)
    forma_pago = serializers.ChoiceField(choices=FormaPago.choices, default=FormaPago.CONTADO)
    plazo_dias = serializers.IntegerField(min_value=0, max_value=365, default=0)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    lineas = serializers.ListField(child=LineaOrdenEntrada(), min_length=1, max_length=200)


class OrdenEntrada(_CuerpoOrden):
    empresa = serializers.IntegerField(min_value=1)


class EdicionOrdenEntrada(_CuerpoOrden):
    """Editar una orden en borrador: lo mismo que crearla, sin cambiar de empresa."""


class ConfiguracionOrdenEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    monto_aprobacion = serializers.DecimalField(
        min_value=Decimal("0"), required=False, allow_null=True, **DINERO
    )
    tolerancia = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
    )


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class LineaOrdenSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    pendiente = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    maximo_recibible = serializers.SerializerMethodField()

    class Meta:
        model = LineaOrdenCompra
        fields = [
            "id",
            "orden_linea",
            "producto",
            "producto_codigo",
            "producto_nombre",
            "presentacion",
            "unidad",
            "factor",
            "cantidad",
            "cantidad_base",
            "cantidad_recibida",
            "pendiente",
            "maximo_recibible",
            "afectacion_codigo",
            "tasa",
            "precio_unitario",
            "valor_venta",
            "impuesto",
            "total",
        ]
        read_only_fields = fields

    def get_maximo_recibible(self, linea) -> str:
        tolerancia = self.context.get("tolerancia", CERO)
        tope = (linea.cantidad * (Decimal(1) + tolerancia / Decimal(100))).quantize(
            Decimal("0.001")
        )
        return f"{max(tope - linea.cantidad_recibida, CERO):.3f}"


class OrdenListaSerializer(serializers.ModelSerializer):
    codigo = serializers.CharField(read_only=True)
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    atrasada = serializers.SerializerMethodField()

    class Meta:
        model = OrdenCompra
        fields = [
            "id",
            "numero",
            "codigo",
            "empresa",
            "estado",
            "estado_nombre",
            "proveedor",
            "proveedor_nombre",
            "almacen",
            "almacen_nombre",
            "fecha_emision",
            "fecha_entrega",
            "atrasada",
            "moneda",
            "total",
            "forma_pago",
            "plazo_dias",
        ]
        read_only_fields = fields

    def get_atrasada(self, orden) -> bool:
        """Emitida o recibida en parte y con la fecha de entrega ya vencida."""
        return bool(
            orden.estado in RECIBE
            and orden.fecha_entrega
            and orden.fecha_entrega < timezone.localdate()
        )


class OrdenDetalleSerializer(OrdenListaSerializer):
    lineas = LineaOrdenSerializer(many=True, read_only=True)
    compras = serializers.SerializerMethodField()
    requiere_aprobacion = serializers.SerializerMethodField()
    monto_aprobacion = serializers.SerializerMethodField()
    tolerancia = serializers.SerializerMethodField()
    emisor = serializers.SerializerMethodField()
    proveedor_datos = serializers.SerializerMethodField()
    anticipos = serializers.SerializerMethodField()

    class Meta(OrdenListaSerializer.Meta):
        fields = [
            *OrdenListaSerializer.Meta.fields,
            "emisor",
            "proveedor_datos",
            "anticipos",
            "tipo_cambio",
            "precios_incluyen_igv",
            "observacion",
            "op_gravada",
            "igv",
            "op_ivap",
            "ivap",
            "op_exonerada",
            "op_inafecta",
            "total_soles",
            "requiere_aprobacion",
            "monto_aprobacion",
            "tolerancia",
            "emitida_en",
            "aprobada_en",
            "motivo_rechazo",
            "cerrada_en",
            "motivo_cierre",
            "anulada_en",
            "motivo_anulacion",
            "lineas",
            "compras",
        ]
        read_only_fields = fields

    def get_emisor(self, orden) -> dict:
        """La empresa que pide, para la hoja impresa."""
        e = orden.empresa
        return {
            "nombre": e.razon_social,
            "nombre_comercial": e.nombre_comercial,
            "ruc": e.ruc,
            "direccion": e.direccion_fiscal,
            "telefono": e.telefono,
        }

    def get_anticipos(self, orden) -> list[dict]:
        """Lo que se adelantó al proveedor por esta orden (los anulados no suman)."""
        return [
            {
                "id": a.pk,
                "codigo": a.codigo,
                "fecha": a.fecha.isoformat(),
                "monto": _dinero(a.monto),
                "estado": a.estado,
            }
            for a in orden.anticipos.order_by("id")
        ]

    def get_proveedor_datos(self, orden) -> dict:
        p = orden.proveedor
        return {
            "tipo_documento": p.tipo_documento,
            "numero_documento": p.numero_documento,
            "direccion": p.direccion,
            "telefono": p.telefono,
            "correo": p.correo,
            "contacto": p.contacto,
            "ciudad": p.ciudad,
        }

    def get_compras(self, orden) -> list[dict]:
        """Las compras con que se recibió esta orden."""
        return [
            {
                "id": c.pk,
                "numero": c.numero,
                "comprobante": c.comprobante,
                "fecha_emision": c.fecha_emision.isoformat(),
                "total": _dinero(c.total),
                "estado": c.estado,
            }
            for c in orden.compras.all().order_by("fecha_emision", "id")
        ]

    def get_requiere_aprobacion(self, orden) -> bool:
        return servicio.requiere_aprobacion(orden)

    def get_monto_aprobacion(self, orden) -> str | None:
        monto = servicio.monto_de_aprobacion(orden.empresa)
        return None if monto is None else _dinero(monto)

    def get_tolerancia(self, orden) -> str:
        return f"{servicio.tolerancia_de_recepcion(orden.empresa):.2f}"


# ---------------------------------------------------------------------------
# Vista
# ---------------------------------------------------------------------------
class OrdenCompraViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Órdenes de compra de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``proveedor``, ``estado``, ``desde``, ``hasta`` (fecha de emisión, AAAA-MM-DD),
    ``pendientes=1`` (emitidas o recibidas en parte), ``atrasadas=1`` (con la entrega vencida) y
    ``q`` (número, proveedor u observación).
    """

    modelo = OrdenCompra
    serializer_class = OrdenListaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "patch", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": CREAR,
        "calcular": CREAR,
        "editar": EDITAR,
        "emitir": EDITAR,
        "reabrir": EDITAR,
        "aprobar": APROBAR,
        "rechazar": APROBAR,
        "anular": ANULAR,
        "cerrar": CERRAR,
        "configuracion": APROBAR,
        "por_recibir": RECIBIR,
        "reposicion": CREAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                OrdenCompra.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_class(self):
        if self.action == "list":
            return OrdenListaSerializer
        return OrdenDetalleSerializer

    def _base(self):
        return OrdenCompra.objects.select_related("proveedor", "almacen", "empresa")

    def _con_detalle(self, queryset):
        return queryset.prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaOrdenCompra.objects.select_related("producto").order_by(
                    "orden_linea"
                ),
            ),
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # al generar la documentación
            return OrdenCompra.objects.none()
        codigo = codigo_requerido(self, self.request)
        queryset = self._base()
        if self.action != "list":
            queryset = self._con_detalle(queryset)
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        if valor := params.get("estado"):
            queryset = queryset.filter(estado=valor)
        if (proveedor := _entero(params, "proveedor")) is not None:
            queryset = queryset.filter(proveedor_id=proveedor)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha_emision__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha_emision__lte=hasta)
        if params.get("pendientes") in ("1", "true", "True"):
            queryset = queryset.filter(estado__in=RECIBE)
        if params.get("atrasadas") in ("1", "true", "True"):
            queryset = queryset.filter(estado__in=RECIBE, fecha_entrega__lt=timezone.localdate())
        q = (params.get("q") or "").strip()
        if q:
            condicion = Q(proveedor__nombre__icontains=q) | Q(observacion__icontains=q)
            digitos = q.upper().removeprefix("OC-").lstrip("0")
            if digitos.isdigit() and len(digitos) <= 9:
                condicion |= Q(numero=int(digitos))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha_emision", "-id")

    # -- armar los argumentos del servicio a partir de lo que llega ------------------------------
    @staticmethod
    def _lineas(lineas: list[dict], org: int) -> list[servicio.LineaOrden]:
        productos = {
            p.pk: p for p in Producto.objects.filter(pk__in={ln["producto"] for ln in lineas})
        }
        pedidas = {ln["presentacion"] for ln in lineas if ln.get("presentacion")}
        presentaciones = {
            p.pk: p
            for p in PresentacionProducto.objects.select_related("unidad").filter(pk__in=pedidas)
        }
        codigos = {ln["afectacion"] for ln in lineas if ln.get("afectacion")}
        afectaciones = {
            a.codigo: a
            for a in AfectacionIGV.objects.filter(organizacion_id=org, codigo__in=codigos)
        }
        resultado = []
        for ln in lineas:
            producto = productos.get(ln["producto"])
            if producto is None:
                raise ValidationError({"lineas": "Hay productos que no existen."})
            if ln.get("presentacion") and ln["presentacion"] not in presentaciones:
                raise ValidationError({"lineas": "Hay presentaciones que no existen."})
            if ln.get("afectacion") and ln["afectacion"] not in afectaciones:
                raise ValidationError({"lineas": "Hay afectaciones del IGV que no existen."})
            resultado.append(
                servicio.LineaOrden(
                    producto=producto,
                    cantidad=ln["cantidad"],
                    precio_unitario=ln["precio_unitario"],
                    presentacion=presentaciones.get(ln.get("presentacion")),
                    afectacion=afectaciones.get(ln.get("afectacion")),
                )
            )
        return resultado

    def _argumentos(self, validados: dict, empresa: Empresa) -> dict:
        proveedor = _uno(Proveedor, validados["proveedor"], "proveedor", "No existe.")
        almacen = _uno(
            Almacen, validados["almacen"], "almacen", "Elija un almacén de la empresa.",
            empresa=empresa,
        )  # fmt: skip
        return {
            "proveedor": proveedor,
            "almacen": almacen,
            "fecha_emision": validados["fecha_emision"],
            "fecha_entrega": validados.get("fecha_entrega"),
            "moneda": validados["moneda"],
            "tipo_cambio": validados.get("tipo_cambio"),
            "precios_incluyen_igv": validados["precios_incluyen_igv"],
            "forma_pago": validados["forma_pago"],
            "plazo_dias": validados["plazo_dias"],
            "observacion": validados.get("observacion", ""),
            "lineas": self._lineas(validados["lineas"], empresa.organizacion_id),
        }

    def _empresa_y_argumentos(self, request):
        datos = OrdenEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        validados = datos.validated_data
        empresa = Empresa.objects.filter(pk=validados["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return empresa, self._argumentos(validados, empresa)

    def _recargar(self, pk: int) -> dict:
        orden = self._con_detalle(self._base()).get(pk=pk)
        contexto = {"tolerancia": servicio.tolerancia_de_recepcion(orden.empresa)}
        return _plano(OrdenDetalleSerializer(orden, context=contexto).data)

    def retrieve(self, request, *args, **kwargs):
        orden = self.get_object()
        contexto = {"tolerancia": servicio.tolerancia_de_recepcion(orden.empresa)}
        return Response(OrdenDetalleSerializer(orden, context=contexto).data)

    def _idempotente(self, request, operacion, estado=200):
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

    # -- crear, editar y vista previa -------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=OrdenEntrada,
        responses={201: OrdenDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento (8 a 128 caracteres). Un reintento con la "
                "misma clave devuelve el mismo resultado sin crear otra orden.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        empresa, argumentos = self._empresa_y_argumentos(request)

        def operacion():
            with transaction.atomic():
                orden = servicio.crear_orden(empresa=empresa, **argumentos)
            return 201, self._recargar(orden.pk)

        return self._idempotente(request, operacion)

    @extend_schema(tags=TAG, request=EdicionOrdenEntrada, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="editar")
    def editar(self, request, pk=None):
        """Cambia una orden en borrador (cabecera y líneas)."""
        orden = self.get_object()
        datos = EdicionOrdenEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        argumentos = self._argumentos(datos.validated_data, orden.empresa)
        servicio.editar_orden(orden, **argumentos)
        return Response(self._recargar(orden.pk))

    @extend_schema(tags=TAG, request=OrdenEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="calcular")
    def calcular(self, request):
        """Calcula totales e IGV por línea sin guardar nada, y dice si pediría aprobación."""
        empresa, argumentos = self._empresa_y_argumentos(request)
        p = servicio.preparar_orden(empresa=empresa, **argumentos)
        r = p.resultado
        umbral = servicio.monto_de_aprobacion(empresa)
        return Response(
            {
                "moneda": p.moneda,
                "tipo_cambio": f"{p.tipo_cambio:.4f}",
                "op_gravada": _dinero(r.op_gravada),
                "igv": _dinero(r.igv),
                "op_ivap": _dinero(r.op_ivap),
                "ivap": _dinero(r.ivap),
                "op_exonerada": _dinero(r.op_exonerada),
                "op_inafecta": _dinero(r.op_inafecta),
                "total": _dinero(r.total),
                "total_soles": _dinero(p.total_soles),
                "requiere_aprobacion": umbral is not None and p.total_soles > umbral,
                "monto_aprobacion": None if umbral is None else _dinero(umbral),
                "lineas": [
                    {
                        "afectacion_codigo": afectacion.codigo,
                        "afectacion_nombre": afectacion.nombre,
                        "tasa": f"{tasa:.2f}",
                        "cantidad_base": f"{base:.3f}",
                        "valor_venta": _dinero(linea.valor_venta),
                        "impuesto": _dinero(linea.impuesto),
                        "total": _dinero(linea.total),
                    }
                    for (afectacion, tasa), base, linea in zip(
                        p.afectaciones, p.cantidades_base, r.lineas, strict=True
                    )
                ],
            }
        )

    # -- estados --------------------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=None,
        responses={200: OrdenDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no emite la orden dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="emitir")
    def emitir(self, request, pk=None):
        """Emite la orden. Si su monto pide aprobación y quien emite no puede darla, queda por
        aprobar."""
        orden = self.get_object()
        puede_aprobar = motor.tiene_permiso(request.user, APROBAR, orden.empresa_id)

        def operacion():
            servicio.emitir_orden(orden, puede_aprobar=puede_aprobar)
            return 200, self._recargar(orden.pk)

        return self._idempotente(request, operacion)

    @extend_schema(tags=TAG, request=None, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="aprobar")
    def aprobar(self, request, pk=None):
        """Aprueba una orden que estaba por aprobar: queda emitida."""
        orden = self.get_object()
        servicio.aprobar_orden(orden)
        return Response(self._recargar(orden.pk))

    @extend_schema(
        tags=TAG, request=AnulacionCompraEntrada, responses={200: OrdenDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="rechazar")
    def rechazar(self, request, pk=None):
        """No aprueba la orden: vuelve a borrador con el motivo."""
        orden = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.rechazar_orden(orden, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(orden.pk))

    @extend_schema(tags=TAG, request=None, responses={200: OrdenDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="reabrir")
    def reabrir(self, request, pk=None):
        """Devuelve a borrador una orden por aprobar o emitida que todavía no recibió nada."""
        orden = self.get_object()
        servicio.reabrir_orden(orden)
        return Response(self._recargar(orden.pk))

    @extend_schema(
        tags=TAG, request=AnulacionCompraEntrada, responses={200: OrdenDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula una orden que no recibió nada."""
        orden = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.anular_orden(orden, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(orden.pk))

    @extend_schema(
        tags=TAG, request=AnulacionCompraEntrada, responses={200: OrdenDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="cerrar")
    def cerrar(self, request, pk=None):
        """Da por terminada una orden recibida en parte (el proveedor no entregará el resto)."""
        orden = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio.cerrar_orden(orden, motivo=datos.validated_data["motivo"])
        return Response(self._recargar(orden.pk))

    # -- recibir ---------------------------------------------------------------------------
    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="por-recibir")
    def por_recibir(self, request, pk=None):
        """Lo que falta recibir de la orden, para precargar «Registrar compra»."""
        orden = self.get_object()
        tolerancia = servicio.tolerancia_de_recepcion(orden.empresa)
        por_linea = {f["linea"]: f for f in servicio.pendiente_de_recibir(orden)}
        lineas = []
        for ln in orden.lineas.all():
            fila = por_linea[ln.pk]
            lineas.append(
                {
                    "linea": ln.pk,
                    "producto": ln.producto_id,
                    "producto_codigo": ln.producto.codigo,
                    "producto_nombre": ln.producto.nombre,
                    "presentacion": ln.presentacion_id,
                    "unidad": ln.unidad,
                    "lleva_serie": ln.producto.lleva_serie,
                    "pedido": f"{ln.cantidad:.3f}",
                    "recibido": f"{ln.cantidad_recibida:.3f}",
                    "pendiente": f"{fila['pendiente']:.3f}",
                    "maximo_recibible": f"{fila['maximo_recibible']:.3f}",
                    "precio_unitario": f"{ln.precio_unitario:f}",
                    "afectacion_codigo": ln.afectacion_codigo,
                    "tasa": f"{ln.tasa:.2f}",
                }
            )
        return Response(
            {
                "orden": orden.pk,
                "codigo": orden.codigo,
                "estado": orden.estado,
                "puede_recibir": orden.estado in RECIBE,
                "empresa": orden.empresa_id,
                "proveedor": orden.proveedor_id,
                "proveedor_nombre": orden.proveedor.nombre,
                "almacen": orden.almacen_id,
                "moneda": orden.moneda,
                "tipo_cambio": f"{orden.tipo_cambio:.4f}",
                "precios_incluyen_igv": orden.precios_incluyen_igv,
                "forma_pago": orden.forma_pago,
                "plazo_dias": orden.plazo_dias,
                "fecha_entrega": orden.fecha_entrega,
                "tolerancia": f"{tolerancia:.2f}",
                "lineas": lineas,
            }
        )

    # -- reposición sugerida ---------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        parameters=[
            OpenApiParameter("empresa", int, required=True),
            OpenApiParameter("almacen", int, required=True),
            OpenApiParameter(
                "hasta", float, description="Veces el stock mínimo (1 a 10; por defecto 2)."
            ),
        ],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"], url_path="reposicion")
    def reposicion(self, request):
        """Productos bajo su stock mínimo, agrupados por el proveedor de su última compra."""
        params = request.query_params
        empresa = Empresa.objects.filter(
            pk=empresa_declarada(request, self), estado=Estado.ACTIVO
        ).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        almacen = _uno(
            Almacen, _entero(params, "almacen"), "almacen", "Elija un almacén de la empresa.",
            empresa=empresa,
        )  # fmt: skip
        try:
            hasta = Decimal(params.get("hasta") or HASTA_POR_DEFECTO)
        except ArithmeticError:
            raise ValidationError({"hasta": "Indique un número."}) from None
        r = reposicion_sugerida(empresa, almacen, hasta)

        def cantidad(valor) -> str:
            return f"{valor:.3f}"

        return Response(
            {
                "almacen": almacen.pk,
                "almacen_nombre": almacen.nombre,
                "hasta": f"{r['hasta']:f}",
                "total_productos": r["total_productos"],
                "grupos": [
                    {
                        "proveedor": (
                            {
                                "id": g["proveedor"].pk,
                                "nombre": g["proveedor"].nombre,
                                "tipo_documento": g["proveedor"].tipo_documento,
                                "numero_documento": g["proveedor"].numero_documento,
                            }
                            if g["proveedor"]
                            else None
                        ),
                        "productos": [
                            {
                                "producto": p["producto"].pk,
                                "codigo": p["producto"].codigo,
                                "nombre": p["producto"].nombre,
                                "unidad": p["producto"].unidad.abreviatura,
                                "stock": cantidad(p["stock"]),
                                "minimo": cantidad(p["minimo"]),
                                "en_camino": cantidad(p["en_camino"]),
                                "sugerido": cantidad(p["sugerido"]),
                                "precio_estimado": f"{p['precio_estimado']:f}",
                                "ultima_compra": p["ultima_compra"],
                            }
                            for p in g["productos"]
                        ],
                    }
                    for g in r["grupos"]
                ],
            }
        )

    # -- configuración de la empresa ---------------------------------------------------------
    @extend_schema(tags=TAG, request=ConfiguracionOrdenEntrada, responses={200: dict})
    @action(detail=False, methods=["get", "patch"], url_path="configuracion")
    def configuracion(self, request):
        """Desde qué monto una orden pide aprobación y cuánto más se puede recibir.

        ``GET ?empresa=ID`` lo lee; ``PATCH`` lo cambia (``monto_aprobacion`` vacío = nunca pide
        aprobación; ``tolerancia`` en %).
        """
        if request.method == "GET":
            empresa = Empresa.objects.filter(
                pk=empresa_declarada(request, self), estado=Estado.ACTIVO
            ).first()
            if empresa is None:
                raise ValidationError({"empresa": "Elija una empresa activa."})
        else:
            datos = ConfiguracionOrdenEntrada(data=request.data)
            datos.is_valid(raise_exception=True)
            v = datos.validated_data
            empresa = Empresa.objects.filter(pk=v["empresa"], estado=Estado.ACTIVO).first()
            if empresa is None:
                raise ValidationError({"empresa": "Elija una empresa activa."})
            with transaction.atomic():
                fila, _ = (
                    ConfiguracionEmpresa.objects.sin_ambito()
                    .select_for_update()
                    .get_or_create(empresa=empresa)
                )
                antes = (fila.orden_compra_monto_aprobacion, fila.orden_compra_tolerancia)
                if "monto_aprobacion" in v:
                    fila.orden_compra_monto_aprobacion = v["monto_aprobacion"]
                if "tolerancia" in v:
                    fila.orden_compra_tolerancia = v["tolerancia"]
                fila.save()
                registrar(
                    "compras.orden_configuracion",
                    recurso_tipo="empresa",
                    recurso_id=empresa.pk,
                    empresa_id=empresa.pk,
                    resumen="Configuración de órdenes de compra cambiada",
                    detalle={
                        "monto_aprobacion_antes": antes[0],
                        "monto_aprobacion": fila.orden_compra_monto_aprobacion,
                        "tolerancia_antes": antes[1],
                        "tolerancia": fila.orden_compra_tolerancia,
                    },
                )
        monto = servicio.monto_de_aprobacion(empresa)
        return Response(
            {
                "empresa": empresa.pk,
                "monto_aprobacion": None if monto is None else _dinero(monto),
                "tolerancia": f"{servicio.tolerancia_de_recepcion(empresa):.2f}",
            }
        )
