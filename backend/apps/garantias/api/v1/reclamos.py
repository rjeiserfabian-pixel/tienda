"""API de reclamos de garantía: lista, ficha y las acciones de cada paso."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import PaginaEstandar
from apps.garantias import reclamos
from apps.garantias.models import Garantia, ReclamoGarantia
from apps.seguridad.mixins import filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada

VER = "VENTAS.VER"
RECLAMAR = "VENTAS.GARANTIA_RECLAMAR"
RESOLVER = "VENTAS.GARANTIA_RESOLVER"
TAG = ["garantias"]


class ReclamoSerializer(serializers.ModelSerializer):
    numero_completo = serializers.CharField(read_only=True)
    producto_nombre = serializers.CharField(source="garantia.producto.nombre", read_only=True)
    numero_serie = serializers.CharField(source="garantia.numero_serie", read_only=True)
    cliente_nombre = serializers.CharField(source="garantia.cliente_nombre", read_only=True)
    cliente_documento = serializers.CharField(source="garantia.cliente_documento", read_only=True)
    comprobante_numero = serializers.CharField(
        source="garantia.comprobante.numero_completo", read_only=True
    )
    garantia_vence_el = serializers.DateField(source="garantia.vence_el", read_only=True)
    empresa_nombre = serializers.CharField(source="empresa.razon_social", read_only=True)
    orden_servicio_codigo = serializers.SerializerMethodField()
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True, default="")
    garantia_nueva_serie = serializers.CharField(
        source="garantia_nueva.numero_serie", read_only=True, default=""
    )
    garantia_nueva_vence_el = serializers.DateField(
        source="garantia_nueva.vence_el", read_only=True, default=None
    )
    estado_texto = serializers.CharField(source="get_estado_display", read_only=True)
    resolucion_texto = serializers.CharField(source="get_resolucion_display", read_only=True)

    class Meta:
        model = ReclamoGarantia
        fields = [
            "id",
            "empresa",
            "empresa_nombre",
            "numero",
            "numero_completo",
            "fecha",
            "garantia",
            "producto_nombre",
            "numero_serie",
            "cliente_nombre",
            "cliente_documento",
            "comprobante_numero",
            "garantia_vence_el",
            "cantidad",
            "descripcion",
            "estado",
            "estado_texto",
            "orden_servicio",
            "orden_servicio_codigo",
            "proveedor",
            "proveedor_nombre",
            "rma_numero",
            "enviado_proveedor_el",
            "respuesta_proveedor",
            "respondido_proveedor_el",
            "resolucion",
            "resolucion_texto",
            "resolucion_detalle",
            "resuelto_el",
            "garantia_nueva",
            "garantia_nueva_serie",
            "garantia_nueva_vence_el",
        ]
        read_only_fields = fields

    def get_orden_servicio_codigo(self, obj) -> str:
        return obj.orden_servicio.codigo if obj.orden_servicio_id else ""


def _consulta():
    return ReclamoGarantia.objects.select_related(
        "garantia__producto",
        "garantia__comprobante",
        "empresa",
        "orden_servicio",
        "proveedor",
        "garantia_nueva",
    )


class ReclamoListaView(generics.ListAPIView):
    """Lista los reclamos (``estado``, ``q``) y abre uno nuevo."""

    serializer_class = ReclamoSerializer
    pagination_class = PaginaEstandar
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"get": VER, "post": RECLAMAR}

    def empresas_de_la_operacion(self, request):
        if request.method != "POST":
            return [empresa_declarada(request, self)]
        garantia = (
            Garantia.objects.filter(pk=_entero(request.data.get("garantia"), "garantia"))
            .values_list("empresa_id", flat=True)
            .first()
        )
        if garantia is None:
            raise ValidationError({"garantia": "La garantía no existe."})
        return [garantia]

    def get_queryset(self):
        qs = filtrar_por_alcance(
            _consulta(), self.request.user, VER, campo_empresa="empresa_id", campo_propio=None
        )
        p = self.request.query_params
        if p.get("empresa", "").isdigit():
            qs = qs.filter(empresa_id=int(p["empresa"]))
        estado = (p.get("estado") or "").upper()
        if estado == "ABIERTOS":
            qs = qs.filter(estado__in=["ABIERTO", "EN_SERVICIO", "EN_PROVEEDOR"])
        elif estado:
            qs = qs.filter(estado=estado)
        if p.get("garantia", "").isdigit():
            qs = qs.filter(garantia_id=int(p["garantia"]))
        texto = " ".join((p.get("q") or "").split())[:60]
        if texto:
            from django.db.models import Q

            qs = qs.filter(
                Q(garantia__numero_serie__icontains=texto)
                | Q(garantia__cliente_nombre__icontains=texto)
                | Q(garantia__cliente_documento__icontains=texto)
                | Q(garantia__producto__nombre__icontains=texto)
                | Q(rma_numero__icontains=texto)
            )
        return qs

    @extend_schema(
        parameters=[OpenApiParameter("estado", str, description="ABIERTOS o un estado")], tags=TAG
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=None, tags=TAG)
    def post(self, request, *args, **kwargs):
        reclamo = reclamos.abrir(
            garantia_id=_entero(request.data.get("garantia"), "garantia"),
            descripcion=request.data.get("descripcion", ""),
            cantidad=request.data.get("cantidad"),
        )
        return Response(ReclamoSerializer(_consulta().get(pk=reclamo.pk)).data, status=201)


def _entero(valor, campo: str) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ValidationError({campo: "Indique un número válido."}) from None


def _fecha(valor, campo: str):
    if valor in (None, ""):
        return None
    from django.utils.dateparse import parse_date

    fecha = parse_date(str(valor))
    if fecha is None:
        raise ValidationError({campo: "Use el formato AAAA-MM-DD."})
    return fecha


class ReclamoDetalleView(generics.RetrieveAPIView):
    serializer_class = ReclamoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER

    def get_queryset(self):
        return filtrar_por_alcance(
            _consulta(), self.request.user, VER, campo_empresa="empresa_id", campo_propio=None
        )

    @extend_schema(tags=TAG)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class _AccionBase(APIView):
    """Una acción sobre un reclamo. La empresa sale del propio reclamo, no del cliente."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = RECLAMAR

    def empresas_de_la_operacion(self, request):
        empresa = (
            ReclamoGarantia.objects.filter(pk=self.kwargs["pk"])
            .values_list("empresa_id", flat=True)
            .first()
        )
        if empresa is None:
            raise NotFound()
        return [empresa]

    def ejecutar(self, request, pk: int):  # pragma: no cover - lo define cada acción
        raise NotImplementedError

    @extend_schema(request=None, responses=ReclamoSerializer, tags=TAG)
    def post(self, request, pk: int):
        self.ejecutar(request, pk)
        return Response(ReclamoSerializer(_consulta().get(pk=pk)).data)


class VincularServicioView(_AccionBase):
    def ejecutar(self, request, pk):
        reclamos.vincular_servicio(pk, _entero(request.data.get("orden"), "orden"))


class EnviarProveedorView(_AccionBase):
    def ejecutar(self, request, pk):
        reclamos.enviar_a_proveedor(
            pk,
            proveedor_id=_entero(request.data.get("proveedor"), "proveedor"),
            rma_numero=request.data.get("rma_numero", ""),
            fecha=_fecha(request.data.get("fecha"), "fecha"),
        )


class RespuestaProveedorView(_AccionBase):
    def ejecutar(self, request, pk):
        reclamos.respuesta_del_proveedor(
            pk,
            texto=request.data.get("texto", ""),
            fecha=_fecha(request.data.get("fecha"), "fecha"),
        )


class ResolverView(_AccionBase):
    permiso_requerido = RESOLVER

    def ejecutar(self, request, pk):
        datos = request.data
        cambio = None
        if datos.get("almacen") not in (None, ""):
            series = datos.get("series") or []
            if not isinstance(series, list) or len(series) > 100:
                raise ValidationError({"series": "Envíe la lista de series."})
            cambio = reclamos.Cambio(
                almacen_id=_entero(datos.get("almacen"), "almacen"),
                series=tuple(str(s) for s in series),
            )
        reclamos.resolver(
            pk,
            resolucion=str(datos.get("resolucion", "")),
            detalle=datos.get("detalle", ""),
            cambio=cambio,
        )
