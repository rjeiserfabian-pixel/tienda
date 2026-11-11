"""API de proformas: cotizar un carrito, consultarlo, imprimirlo y venderlo después."""

import json
from collections import defaultdict
from decimal import Decimal

from django.db.models import Exists, OuterRef, Prefetch, Q
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import Cliente
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.ventas import catalogo, proformas
from apps.ventas.models import FormaPago, LineaProforma, Moneda, Proforma, Venta

from .serializers import AnulacionVentaEntrada, LineaEntradaSerializer
from .views import (
    TAG,
    VENDER,
    VER,
    _carrito_de,
    _empresas_del_carrito,
    _empresas_que_venden,
    _entero,
    _fecha,
    _nombre_empresa,
    _nombre_usuario,
)


class ProformaEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    cliente = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cliente_nombre = serializers.CharField(max_length=250, required=False, allow_blank=True)
    cliente_documento = serializers.CharField(max_length=20, required=False, allow_blank=True)
    cliente_contacto = serializers.CharField(max_length=120, required=False, allow_blank=True)
    cliente_direccion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    fecha_entrega = serializers.DateField(required=False, allow_null=True)
    atencion = serializers.CharField(max_length=120, required=False, allow_blank=True)
    lugar_entrega = serializers.CharField(max_length=250, required=False, allow_blank=True)
    serie = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    forma_pago = serializers.ChoiceField(choices=FormaPago.choices, required=False)
    moneda = serializers.ChoiceField(choices=Moneda.choices, required=False)
    tipo_cambio = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )
    lista = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    validez_dias = serializers.IntegerField(min_value=1, max_value=90, required=False)
    condiciones = serializers.CharField(max_length=500, required=False, allow_blank=True)
    lineas = LineaEntradaSerializer(many=True, allow_empty=False, max_length=100)


class LineaProformaSerializer(serializers.ModelSerializer):
    unidad = serializers.CharField(source="producto.unidad.abreviatura", read_only=True)
    codigo = serializers.CharField(source="producto.codigo", read_only=True)
    afectacion_nombre = serializers.CharField(source="afectacion.nombre", read_only=True)
    empresa_nombre = serializers.SerializerMethodField()

    class Meta:
        model = LineaProforma
        fields = [
            "id",
            "producto",
            "codigo",
            "descripcion",
            "unidad",
            "empresa",
            "empresa_nombre",
            "cantidad",
            "afectacion_nombre",
            "tasa_igv",
            "precio_lista",
            "precio_unitario",
            "valor_venta",
            "igv",
            "total",
        ]
        read_only_fields = fields

    def get_empresa_nombre(self, linea) -> str:
        return _nombre_empresa(linea.empresa)


class ProformaSerializer(serializers.ModelSerializer):
    estado_proforma = serializers.SerializerMethodField()
    numero_completo = serializers.CharField(read_only=True)

    class Meta:
        model = Proforma
        fields = [
            "id",
            "numero",
            "serie",
            "numero_completo",
            "forma_pago",
            "fecha",
            "valida_hasta",
            "cliente",
            "cliente_nombre",
            "cliente_documento",
            "vendedor_nombre",
            "moneda",
            "total",
            "estado",
            "estado_proforma",
        ]
        read_only_fields = fields

    def get_estado_proforma(self, proforma) -> str:
        return proformas.estado_de(
            proforma, self.context["hoy"], vendida=bool(getattr(proforma, "vendida", False))
        )


class ProformaDetalleSerializer(ProformaSerializer):
    lineas = LineaProformaSerializer(many=True, read_only=True)
    lista_nombre = serializers.CharField(source="lista.nombre", default="", read_only=True)
    emisor = serializers.SerializerMethodField()
    por_empresa = serializers.SerializerMethodField()

    class Meta(ProformaSerializer.Meta):
        fields = [
            *ProformaSerializer.Meta.fields,
            "cliente_contacto",
            "cliente_direccion",
            "fecha_entrega",
            "atencion",
            "lugar_entrega",
            "tipo_cambio",
            "condiciones",
            "lista_nombre",
            "motivo_anulacion",
            "lineas",
            "emisor",
            "por_empresa",
        ]
        read_only_fields = fields

    def get_emisor(self, proforma) -> dict:
        e = proforma.empresa
        return {
            "empresa": e.pk,
            "tiene_logo": bool(e.logo),
            "nombre": _nombre_empresa(e),
            "ruc": e.ruc,
            "direccion": e.direccion_fiscal,
            "telefono": e.telefono,
            "correo": e.correo,
        }

    def get_por_empresa(self, proforma) -> list[dict]:
        """Lo que cobraría cada empresa: su valor de venta, su IGV y su total."""
        sumas: dict[int, dict] = defaultdict(
            lambda: {"valor_venta": Decimal("0"), "igv": Decimal("0"), "total": Decimal("0")}
        )
        nombres: dict[int, str] = {}
        for ln in proforma.lineas.all():
            s = sumas[ln.empresa_id]
            s["valor_venta"] += ln.valor_venta
            s["igv"] += ln.igv
            s["total"] += ln.total
            nombres[ln.empresa_id] = _nombre_empresa(ln.empresa)
        return [
            {"empresa": e, "nombre": nombres[e], **{k: f"{v:.2f}" for k, v in s.items()}}
            for e, s in sumas.items()
        ]


class ProformaViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Proformas del mostrador de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``estado`` (``vigente``, ``vencida``, ``vendida`` o ``anulada``), ``desde``, ``hasta``
    y ``q`` (cliente, documento o número).
    """

    modelo = Proforma
    serializer_class = ProformaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": VENDER,
        "anular": VENDER,
        "para_vender": VENDER,
    }

    def get_serializer_class(self):
        return ProformaDetalleSerializer if self.action == "retrieve" else ProformaSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "hoy": timezone.localdate()}

    def empresas_de_la_operacion(self, request):
        if self.action == "create":
            return _empresas_del_carrito(request, self)
        if "pk" in self.kwargs:
            empresa_id = (
                Proforma.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    @staticmethod
    def _consulta(detalle: bool):
        vendida = Exists(
            Venta.objects.sin_ambito().filter(proforma=OuterRef("pk"), estado=Venta.Estado.EMITIDO)
        )
        queryset = Proforma.objects.select_related("lista", "empresa").annotate(vendida=vendida)
        if detalle:
            queryset = queryset.prefetch_related(
                Prefetch(
                    "lineas",
                    queryset=LineaProforma.objects.select_related(
                        "producto__unidad", "afectacion", "empresa"
                    ).order_by("orden"),
                )
            )
        return queryset

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(
            self._consulta(detalle=self.action in ("retrieve", "para_vender")),
            self.request.user,
            codigo,
        )
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        hoy = timezone.localdate()
        estado = params.get("estado")
        if estado == "anulada":
            queryset = queryset.filter(estado=Proforma.Estado.ANULADO)
        elif estado == "vendida":
            queryset = queryset.filter(estado=Proforma.Estado.EMITIDO, vendida=True)
        elif estado == "vigente":
            queryset = queryset.filter(
                estado=Proforma.Estado.EMITIDO, vendida=False, valida_hasta__gte=hoy
            )
        elif estado == "vencida":
            queryset = queryset.filter(
                estado=Proforma.Estado.EMITIDO, vendida=False, valida_hasta__lt=hoy
            )
        q = (params.get("q") or "").strip()
        if q:
            condicion = Q(cliente_nombre__icontains=q) | Q(cliente_documento__icontains=q)
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    @extend_schema(tags=TAG, request=ProformaEntrada, responses={201: ProformaDetalleSerializer})
    def create(self, request, *args, **kwargs):
        datos = ProformaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        argumentos = _carrito_de(request, {**v, "tipo_comprobante": "NV"})
        proforma = proformas.crear_proforma(
            empresa=argumentos["empresa"],
            lineas=argumentos["lineas"],
            vendedor_id=request.user.pk,
            vendedor_nombre=_nombre_usuario(request.user),
            cliente=argumentos["cliente"],
            cliente_nombre=v.get("cliente_nombre", ""),
            cliente_documento=v.get("cliente_documento", ""),
            cliente_contacto=v.get("cliente_contacto", ""),
            cliente_direccion=v.get("cliente_direccion", ""),
            fecha_entrega=v.get("fecha_entrega"),
            atencion=v.get("atencion", ""),
            lugar_entrega=v.get("lugar_entrega", ""),
            serie=v.get("serie"),
            forma_pago=argumentos["forma_pago"],
            puede_credito=argumentos["puede_credito"],
            moneda=argumentos["moneda"],
            tipo_cambio=argumentos["tipo_cambio"],
            lista=argumentos["lista"],
            sucursal=argumentos["sucursal"],
            validez_dias=v.get("validez_dias", 7),
            condiciones=v.get("condiciones", ""),
            puede_descontar=argumentos["puede_descontar"],
            puede_precio_tecnico=argumentos["puede_precio_tecnico"],
            puede_vender_bajo_minimo=argumentos["puede_vender_bajo_minimo"],
            puede_vender_stock_otra_empresa=argumentos["puede_vender_stock_otra_empresa"],
        )
        return Response(self._detalle(proforma.pk), status=201)

    def _detalle(self, pk: int) -> dict:
        proforma = self._consulta(detalle=True).get(pk=pk)
        return json.loads(
            json.dumps(
                ProformaDetalleSerializer(proforma, context=self.get_serializer_context()).data,
                default=str,
            )
        )

    @extend_schema(
        tags=TAG, request=AnulacionVentaEntrada, responses={200: ProformaDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        proforma = self.get_object()
        datos = AnulacionVentaEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        proformas.anular_proforma(proforma, motivo=datos.validated_data["motivo"])
        return Response(self._detalle(proforma.pk))

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="para-vender")
    def para_vender(self, request, pk=None):
        """Las líneas de la proforma listas para cargarse al punto de venta, con su stock actual."""
        proforma = self.get_object()
        if proformas.estado_de(proforma, vendida=bool(proforma.vendida)) in (
            proformas.ANULADA,
            proformas.VENDIDA,
        ):
            return Response(
                {
                    "error": {
                        "codigo": "proforma_no_disponible",
                        "mensaje": "La proforma ya no está disponible.",
                    }
                },
                status=409,
            )
        empresas = _empresas_que_venden(request.user, proforma.empresa.organizacion_id)
        fichas = catalogo.fichas_de([ln.producto_id for ln in proforma.lineas.all()], empresas)
        cliente = None
        if proforma.cliente_id:
            c = Cliente.objects.filter(pk=proforma.cliente_id).first()
            if c:
                cliente = {
                    "id": c.pk,
                    "nombre": c.nombre,
                    "tipo_documento": c.tipo_documento,
                    "numero_documento": c.numero_documento,
                }
        respuesta = Response(
            {
                "id": proforma.pk,
                "numero": proforma.numero,
                "numero_completo": proforma.numero_completo,
                "forma_pago": proforma.forma_pago,
                "empresa": proforma.empresa_id,
                "moneda": proforma.moneda,
                "valida_hasta": proforma.valida_hasta,
                "vencida": proforma.valida_hasta < timezone.localdate(),
                "cliente": cliente,
                "cliente_nombre": proforma.cliente_nombre,
                "lineas": [
                    {
                        "ficha": fichas.get(ln.producto_id),
                        "cantidad": str(ln.cantidad),
                        "empresa": ln.empresa_id,
                        "precio_unitario": str(ln.precio_unitario),
                        "precio_lista": str(ln.precio_lista),
                    }
                    for ln in proforma.lineas.all()
                ],
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta
