import json
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.caja import adjuntos as revision
from apps.compras.servicios import PagoEntrada
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle
from apps.gastos import adjuntos, servicios
from apps.gastos.models import AdjuntoGasto, FormaPago, Gasto, GastoRecurrente, PagoGasto
from apps.gastos.servicios import RepartoEntrada
from apps.mantenimiento import fiscal
from apps.mantenimiento.models import (
    AfectacionIGV,
    CategoriaGasto,
    CuentaFinanciera,
    MedioPago,
    Proveedor,
    TipoComprobante,
)
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Estado, Sucursal
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import (
    AdjuntoGastoEntrada,
    AdjuntoGastoSerializer,
    AnulacionEntrada,
    GastoDetalleSerializer,
    GastoEntrada,
    GastoSerializer,
    PagarEntrada,
)

TAG = ["gastos"]
VER = "GASTOS.VER"
REGISTRAR = "GASTOS.REGISTRAR"
ANULAR = "GASTOS.ANULAR"
PAGAR = "GASTOS.PAGAR"
ASIGNAR = "GASTOS.ASIGNAR_EMPRESA"
EXCEDER = "GASTOS.SIN_COMPROBANTE_EXCEDER"
CERO = Decimal("0")


def _entero(params, nombre: str) -> int | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    if not str(valor).isdigit():
        raise ValidationError({nombre: "Debe ser un número entero."})
    return int(valor)


def _fecha(params, nombre: str):
    from datetime import date

    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nombre: "Use el formato AAAA-MM-DD."}) from None


def _uno(modelo, pk, campo: str, mensaje: str, **filtros):
    if pk is None:
        return None
    objeto = modelo.objects.filter(pk=pk, **filtros).first()
    if objeto is None:
        raise ValidationError({campo: mensaje})
    return objeto


def _pagos_de(pagos, empresa: Empresa) -> list[PagoEntrada]:
    """Los pagos que llegan como números (ids) pasan a objetos de la organización y la empresa."""
    org = empresa.organizacion_id
    return [
        PagoEntrada(
            medio_pago=_uno(
                MedioPago,
                p["medio_pago"],
                "pagos",
                "Hay métodos de pago que no existen.",
                organizacion_id=org,
            ),
            cuenta=_uno(
                CuentaFinanciera,
                p["cuenta"],
                "pagos",
                "Hay cajas o cuentas que no existen.",
                empresa=empresa,
            ),
            monto=p["monto"],
            fecha=p.get("fecha"),
            referencia=p.get("referencia", ""),
            tipo_cambio=p.get("tipo_cambio"),
            aporte_socio=bool(p.get("aporte_socio", False)),
        )
        for p in pagos
    ]


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


class ConfiguracionView(APIView):
    """Datos que la pantalla de gastos necesita: tasa del IGV, tope sin comprobante y permisos."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER
    requiere_empresa = True
    throttle_classes = [ApiAutenticadaThrottle]

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(tags=TAG, parameters=[OpenApiParameter("empresa", int, required=True)])
    def get(self, request):
        empresa = _empresa_activa(empresa_declarada(request, self))
        configuracion = ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=empresa).first()
        tope = configuracion.gasto_sin_comprobante_maximo if configuracion else Decimal("100.00")
        igv = fiscal.tasa_vigente(empresa.organizacion_id, AfectacionIGV.Impuesto.IGV)
        respuesta = Response(
            {
                "igv_porcentaje": f"{igv:.2f}",
                "tope_sin_comprobante": f"{tope:.2f}",
                "puede_exceder_tope": motor.tiene_permiso(request.user, EXCEDER, empresa.pk),
                "puede_repartir": motor.tiene_permiso(request.user, ASIGNAR, empresa.pk),
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class GastoViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Gastos de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``desde``, ``hasta``, ``categoria``, ``proveedor``, ``con_comprobante`` (1 o 0),
    ``estado``, ``forma_pago``, ``pago`` (``pendiente``, ``pagado`` o ``vencido``) y ``q``.
    """

    modelo = Gasto
    serializer_class = GastoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": REGISTRAR,
        "anular": ANULAR,
        "pagar": PAGAR,
        "anular_pago": ANULAR,
    }

    def get_serializer_class(self):
        return GastoDetalleSerializer if self.action == "retrieve" else GastoSerializer

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                Gasto.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        pagado = (
            PagoGasto.objects.filter(gasto=OuterRef("pk"), anulado=False)
            .order_by()
            .values("gasto")
            .annotate(s=Sum("monto"))
            .values("s")
        )
        queryset = (
            Gasto.objects.select_related(
                "empresa", "categoria", "tipo_comprobante", "proveedor", "sucursal", "recurrente"
            )
            .prefetch_related("repartos", "adjuntos")
            .annotate(
                pagado_calc=Coalesce(
                    Subquery(pagado, output_field=DecimalField(max_digits=16, decimal_places=2)),
                    CERO,
                    output_field=DecimalField(max_digits=16, decimal_places=2),
                )
            )
        )
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        if (categoria := _entero(params, "categoria")) is not None:
            queryset = queryset.filter(categoria_id=categoria)
        if (proveedor := _entero(params, "proveedor")) is not None:
            queryset = queryset.filter(proveedor_id=proveedor)
        if (con := params.get("con_comprobante")) in ("0", "1"):
            queryset = queryset.filter(con_comprobante=con == "1")
        for campo in ("estado", "forma_pago"):
            if valor := params.get(campo):
                queryset = queryset.filter(**{campo: valor})
        pago = params.get("pago")
        hoy = timezone.localdate()
        if pago == "pagado":
            queryset = queryset.filter(estado=Gasto.Estado.EMITIDO, pagado_calc__gte=F("total"))
        elif pago == "pendiente":
            queryset = queryset.filter(estado=Gasto.Estado.EMITIDO, pagado_calc__lt=F("total"))
        elif pago == "vencido":
            queryset = queryset.filter(
                estado=Gasto.Estado.EMITIDO,
                pagado_calc__lt=F("total"),
                fecha_vencimiento__lt=hoy,
            )
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(descripcion__icontains=q)
                | Q(gastado_por__icontains=q)
                | Q(comprobante_numero__icontains=q)
                | Q(proveedor__nombre__icontains=q)
                | Q(categoria__nombre__icontains=q)
            )
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    @extend_schema(
        tags=TAG,
        request=GastoEntrada,
        responses={201: GastoDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no registra dos veces.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        datos = GastoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        org = empresa.organizacion_id
        categoria = _uno(
            CategoriaGasto, v["categoria"], "categoria", "Elija una categoría.", organizacion_id=org
        )
        tipo = _uno(
            TipoComprobante,
            v.get("tipo_comprobante"),
            "tipo_comprobante",
            "Elija un tipo de comprobante.",
            organizacion_id=org,
        )
        proveedor = _uno(
            Proveedor, v.get("proveedor"), "proveedor", "Elija un proveedor.", organizacion_id=org
        )
        sucursal = _uno(
            Sucursal, v.get("sucursal"), "sucursal", "Elija una sucursal.", empresa=empresa
        )
        pagos = _pagos_de(v.get("pagos", []), empresa)
        reparto = []
        for r in v.get("reparto", []):
            destino = _uno(
                Empresa,
                r["empresa"],
                "reparto",
                "Hay empresas que no existen.",
                organizacion_id=org,
            )
            reparto.append(RepartoEntrada(destino, r["porcentaje"]))
        if reparto and not motor.tiene_permiso(request.user, ASIGNAR, empresa.pk):
            raise PermissionDenied("No tiene permiso para repartir un gasto entre empresas.")
        puede_exceder = motor.tiene_permiso(request.user, EXCEDER, empresa.pk)
        recurrente = _uno(
            GastoRecurrente,
            v.get("recurrente"),
            "recurrente",
            "Elija un gasto recurrente de esta empresa.",
            empresa=empresa,
        )

        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            gasto = servicios.registrar_gasto(
                empresa=empresa,
                categoria=categoria,
                fecha=v["fecha"],
                descripcion=v["descripcion"],
                con_comprobante=v["con_comprobante"],
                tipo_comprobante=tipo,
                comprobante_serie=v.get("comprobante_serie", ""),
                comprobante_numero=v.get("comprobante_numero", ""),
                proveedor=proveedor,
                base_gravada=v.get("base_gravada", CERO),
                igv=v.get("igv", CERO),
                no_gravado=v.get("no_gravado", CERO),
                gastado_por=v.get("gastado_por", ""),
                sucursal=sucursal,
                observacion=v.get("observacion", ""),
                moneda=v.get("moneda", "PEN"),
                tipo_cambio=v.get("tipo_cambio"),
                forma_pago=v.get("forma_pago", FormaPago.CONTADO),
                fecha_vencimiento=v.get("fecha_vencimiento"),
                pagos=pagos,
                reparto=reparto,
                puede_exceder_tope=puede_exceder,
                recurrente=recurrente,
            )
            nuevo = self.get_queryset().get(pk=gasto.pk)
            return 201, json.loads(json.dumps(GastoDetalleSerializer(nuevo).data, default=str))

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
        tags=TAG,
        request=PagarEntrada,
        responses={200: GastoDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no paga dos veces.",
            )
        ],
    )
    @action(detail=True, methods=["post"], url_path="pagar")
    def pagar(self, request, pk=None):
        """Paga todo o parte de lo que falta de un gasto, con uno o varios métodos."""
        gasto = self.get_object()
        datos = PagarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        pagos = _pagos_de(datos.validated_data["pagos"], gasto.empresa)
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            servicios.pagar_gasto(gasto, pagos)
            nuevo = self.get_queryset().get(pk=gasto.pk)
            return 200, json.loads(json.dumps(GastoDetalleSerializer(nuevo).data, default=str))

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

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: GastoDetalleSerializer})
    @action(detail=True, methods=["post"], url_path=r"pagos/(?P<pago_id>\d+)/anular")
    def anular_pago(self, request, pk=None, pago_id=None):
        """Anula un pago de un gasto por pagar: el dinero vuelve a su caja y la deuda reaparece."""
        gasto = self.get_object()
        pago = PagoGasto.objects.filter(gasto=gasto, pk=pago_id).first()
        if pago is None:
            raise Http404
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicios.anular_pago(pago, motivo=datos.validated_data["motivo"])
        return Response(GastoDetalleSerializer(self.get_queryset().get(pk=gasto.pk)).data)

    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: GastoDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula el gasto: el dinero de sus pagos vuelve a las cajas de donde salió."""
        gasto = self.get_object()
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        servicios.anular_gasto(gasto, motivo=datos.validated_data["motivo"])
        return Response(GastoDetalleSerializer(self.get_queryset().get(pk=gasto.pk)).data)


class AdjuntoGastoViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Comprobantes de los gastos. Listado: ``?gasto=ID``. Subir: ``POST`` con el archivo."""

    modelo = AdjuntoGasto
    serializer_class = AdjuntoGastoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "delete", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "archivo": VER,
        "create": REGISTRAR,
        "destroy": REGISTRAR,
    }

    def get_throttles(self):
        return [ApiAutenticadaThrottle()] if self.action == "create" else super().get_throttles()

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                AdjuntoGasto.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
        else:
            gasto = _entero(request.query_params, "gasto")
            if gasto is None and hasattr(request.data, "get"):
                gasto = _entero(request.data, "gasto")
            empresa_id = Gasto.objects.filter(pk=gasto).values_list("empresa_id", flat=True).first()
        if empresa_id is None:
            raise Http404
        return [empresa_id]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = filtrar_por_alcance(AdjuntoGasto.objects.all(), self.request.user, codigo)
        if self.action == "list":
            queryset = queryset.filter(gasto_id=_entero(self.request.query_params, "gasto"))
        return queryset.order_by("id")

    @extend_schema(tags=TAG, request=AdjuntoGastoEntrada, responses={201: AdjuntoGastoSerializer})
    def create(self, request, *args, **kwargs):
        datos = AdjuntoGastoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        gasto = (
            filtrar_por_alcance(Gasto.objects.select_related("empresa"), request.user, REGISTRAR)
            .filter(pk=datos.validated_data["gasto"])
            .first()
        )
        if gasto is None:
            raise Http404
        adjunto = adjuntos.agregar(gasto, datos.validated_data["archivo"], request.user)
        return Response(AdjuntoGastoSerializer(adjunto).data, status=201)

    @extend_schema(tags=TAG, responses={204: None})
    def destroy(self, request, *args, **kwargs):
        adjuntos.eliminar(self.get_object(), request.user)
        return Response(status=204)

    @extend_schema(tags=TAG, responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path="archivo")
    def archivo(self, request, pk=None):
        """El comprobante: solo con sesión y permiso. Las fotos se ven; el PDF se descarga."""
        adjunto = self.get_object()
        try:
            abierto = adjunto.archivo.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404 from None
        respuesta = FileResponse(abierto, content_type=adjunto.tipo_contenido)
        es_pdf = adjunto.tipo_contenido == revision.PDF
        respuesta["Content-Disposition"] = (
            f"{'attachment' if es_pdf else 'inline'}; "
            f'filename="gasto-{adjunto.gasto_id}-{adjunto.pk}.{"pdf" if es_pdf else "webp"}"'
        )
        respuesta["Cache-Control"] = "private, max-age=3600"
        respuesta["X-Content-Type-Options"] = "nosniff"
        respuesta["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return respuesta
