"""API de las notas de crédito: ver lo que falta devolver, calcular, emitir y consultar."""

import json
import logging
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Prefetch, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, mixins, permissions, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.caja.reportes import nombre_archivo
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.core.throttles import ApiAutenticadaThrottle, ExportacionThrottle, MostradorThrottle
from apps.mantenimiento.models import MedioPago
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.ventas import notas_credito, reportes, servicios, ventas_internas
from apps.ventas.models import (
    CERO,
    MOTIVOS_TOTALES,
    ComprobanteVenta,
    CuotaVenta,
    LineaNotaCredito,
    LineaVenta,
    LineaVentaInterna,
    MotivoNota,
    NotaCredito,
    ReembolsoNota,
    VentaInterna,
)

from .serializers import CobroEntradaSerializer
from .views import TAG, VER, _entero, _fecha, _nombre_empresa, _nombre_usuario

EMITIR = "VENTAS.NOTA_CREDITO"
EXPORTAR = "VENTAS.EXPORTAR"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAXIMO_EXCEL = 20_000  # filas que admite un Excel: más se piden por rangos de fechas

logger = logging.getLogger(__name__)


def _dinero(valor: Decimal) -> str:
    return f"{valor:.2f}"


class LineaDevueltaEntrada(serializers.Serializer):
    linea = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    series = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, max_length=500
    )


class ReembolsoEntrada(CobroEntradaSerializer):
    """Un reembolso es un cobro al revés: método, monto y número de operación."""


class NotaCreditoEntrada(serializers.Serializer):
    motivo = serializers.ChoiceField(choices=MotivoNota.choices)
    descripcion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    # La serie de la nota, si la empresa tiene varias que sirven para el comprobante.
    serie_nota = serializers.IntegerField(min_value=1, required=False)
    reingresa_stock = serializers.BooleanField(required=False)
    lineas = LineaDevueltaEntrada(many=True, required=False, max_length=100)
    reembolsos = ReembolsoEntrada(many=True, required=False, max_length=10)


class LineaNotaSerializer(serializers.ModelSerializer):
    descripcion = serializers.CharField(source="linea_venta.descripcion", read_only=True)
    unidad = serializers.CharField(source="linea_venta.producto.unidad.abreviatura", read_only=True)
    precio_unitario = serializers.DecimalField(
        source="linea_venta.precio_unitario", max_digits=16, decimal_places=6, read_only=True
    )

    class Meta:
        model = LineaNotaCredito
        fields = [
            "id",
            "descripcion",
            "unidad",
            "cantidad",
            "precio_unitario",
            "valor_venta",
            "igv",
            "total",
            "series",
        ]
        read_only_fields = fields


class ReembolsoSerializer(serializers.ModelSerializer):
    medio_pago_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)

    class Meta:
        model = ReembolsoNota
        fields = ["id", "medio_pago_nombre", "cuenta_nombre", "monto", "referencia"]
        read_only_fields = fields


class NotaCreditoSerializer(serializers.ModelSerializer):
    numero_completo = serializers.CharField(read_only=True)
    comprobante_numero = serializers.CharField(source="comprobante.numero_completo", read_only=True)
    comprobante_tipo = serializers.CharField(
        source="comprobante.tipo_comprobante.nombre", read_only=True
    )
    comprobante_fecha = serializers.DateField(source="comprobante.fecha", read_only=True)
    cliente_nombre = serializers.CharField(source="venta.cliente_nombre", read_only=True)
    cliente_documento = serializers.CharField(source="venta.cliente_documento", read_only=True)
    cliente_tipo_documento = serializers.CharField(
        source="venta.cliente_tipo_documento", read_only=True
    )
    moneda = serializers.CharField(source="venta.moneda", read_only=True)
    motivo_nombre = serializers.CharField(source="get_motivo_display", read_only=True)
    usuario = serializers.CharField(source="emitida_por_nombre", read_only=True)
    # Lo que la nota descontó de la deuda del cliente y lo que todavía debe de ese comprobante.
    asociado = serializers.DecimalField(
        source="a_cuotas", max_digits=16, decimal_places=2, read_only=True
    )
    pendiente = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = NotaCredito
        fields = [
            "id",
            "empresa",
            "venta",
            "comprobante",
            "comprobante_numero",
            "comprobante_tipo",
            "comprobante_fecha",
            "numero_completo",
            "fecha",
            "usuario",
            "cliente_nombre",
            "cliente_documento",
            "cliente_tipo_documento",
            "moneda",
            "motivo",
            "motivo_nombre",
            "total",
            "a_cuotas",
            "asociado",
            "pendiente",
            "reembolsado",
            "estado",
        ]
        read_only_fields = fields


class NotaCreditoDetalleSerializer(NotaCreditoSerializer):
    lineas = LineaNotaSerializer(many=True, read_only=True)
    reembolsos = ReembolsoSerializer(many=True, read_only=True)
    emisor = serializers.SerializerMethodField()

    class Meta(NotaCreditoSerializer.Meta):
        fields = [
            *NotaCreditoSerializer.Meta.fields,
            "descripcion",
            "reingresa_stock",
            "emitida_por_nombre",
            "op_gravada",
            "op_exonerada",
            "op_inafecta",
            "igv",
            "lineas",
            "reembolsos",
            "emisor",
        ]
        read_only_fields = fields

    def get_emisor(self, nota) -> dict:
        e = nota.empresa
        return {
            "empresa": e.pk,
            "tiene_logo": bool(e.logo),
            "nombre": _nombre_empresa(e),
            "ruc": e.ruc,
            "direccion": e.direccion_fiscal,
        }


def _con_pendiente(queryset):
    """Agrega ``pendiente``: lo que el cliente aún debe del comprobante (0 si fue al contado)."""
    importe = DecimalField(max_digits=16, decimal_places=2)
    debe = (
        CuotaVenta.objects.sin_ambito()
        .filter(comprobante=OuterRef("comprobante_id"))
        .values("comprobante")
        .annotate(total=Sum(F("monto") - F("pagado"), output_field=importe))
        .values("total")
    )
    return queryset.annotate(
        pendiente=Coalesce(Subquery(debe, output_field=importe), Value(CERO, output_field=importe))
    )


def _por_cliente(q: str) -> Q:
    return Q(venta__cliente_nombre__icontains=q) | Q(venta__cliente_documento__icontains=q)


def _por_numero(q: str, prefijo: str = "") -> Q:
    """Serie o número de un documento; también «F001-1724» (serie y número juntos)."""
    condicion = Q(**{f"{prefijo}serie__icontains": q})
    if q.isdigit() and len(q) <= 8:
        condicion |= Q(**{f"{prefijo}numero": int(q)})
    serie, separador, numero = (parte.strip() for parte in q.partition("-"))
    if separador and serie and numero.isdigit() and len(numero) <= 8:
        condicion |= Q(**{f"{prefijo}serie__iexact": serie, f"{prefijo}numero": int(numero)})
    return condicion


def _busca_nota(q: str) -> Q:
    """El cliente, el número de la nota o el del comprobante que modifica."""
    return _por_cliente(q) | _por_numero(q) | _por_numero(q, "comprobante__")


class NotaCreditoViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Notas de crédito de una empresa (``?empresa=ID`` obligatorio en el listado)."""

    modelo = NotaCredito
    serializer_class = NotaCreditoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {"list": VER, "retrieve": VER}

    def get_serializer_class(self):
        return NotaCreditoDetalleSerializer if self.action == "retrieve" else NotaCreditoSerializer

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                NotaCredito.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = _con_pendiente(
            NotaCredito.objects.select_related("venta", "comprobante__tipo_comprobante", "empresa")
        )
        if self.action == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "lineas",
                    queryset=LineaNotaCredito.objects.select_related(
                        "linea_venta__producto__unidad"
                    ).order_by("orden"),
                ),
                Prefetch(
                    "reembolsos",
                    queryset=ReembolsoNota.objects.select_related("medio_pago", "cuenta"),
                ),
            )
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        return _filtrar_listado(queryset, self.request.query_params)


def _filtrar_listado(queryset, params):
    """Los filtros del listado de notas (empresa, fechas y texto); los usa también el Excel."""
    queryset = queryset.filter(empresa_id=_entero(params, "empresa"))
    if (desde := _fecha(params, "desde")) is not None:
        queryset = queryset.filter(fecha__gte=desde)
    if (hasta := _fecha(params, "hasta")) is not None:
        queryset = queryset.filter(fecha__lte=hasta)
    if q := (params.get("q") or "").strip()[:60]:
        queryset = queryset.filter(_busca_nota(q))
    return queryset.order_by("-fecha", "-id")


class NotasExcelView(APIView):
    """El listado de notas de crédito (con los mismos filtros de la pantalla) en Excel."""

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
        notas = _filtrar_listado(
            filtrar_por_alcance(
                _con_pendiente(
                    NotaCredito.objects.select_related(
                        "venta", "comprobante__tipo_comprobante", "empresa"
                    )
                ),
                request.user,
                EXPORTAR,
            ),
            params,
        )[: MAXIMO_EXCEL + 1]
        filas = [
            {
                "fecha": n.fecha,
                "numero": n.numero_completo,
                "usuario": n.emitida_por_nombre,
                "cliente": n.venta.cliente_nombre,
                "documento": n.venta.cliente_documento,
                "comprobante": n.comprobante.numero_completo,
                "fecha_comprobante": n.comprobante.fecha,
                "motivo": n.get_motivo_display(),
                "moneda": n.venta.moneda,
                "total": n.total,
                "asociado": n.a_cuotas,
                "pendiente": n.pendiente,
                "reembolsado": n.reembolsado,
            }
            for n in notas
        ]
        if len(filas) > MAXIMO_EXCEL:
            raise ValidationError(
                {"desde": f"Hay más de {MAXIMO_EXCEL} notas: acote las fechas para exportarlas."}
            )
        contenido = reportes.notas_credito_excel(
            empresa, filas, _fecha(params, "desde"), _fecha(params, "hasta")
        )
        nombre = nombre_archivo("ventas-notas-credito", empresa, f"{timezone.localdate():%Y%m%d}")
        registrar(
            "ventas.notas_credito_exportadas",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Notas de crédito exportadas: {nombre}",
            detalle={"filas": len(filas)},
        )
        logger.info(
            "notas_credito_exportadas", extra={"empresa_id": empresa.pk, "filas": len(filas)}
        )
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        respuesta["Cache-Control"] = "no-store"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta


class _DeComprobante(APIView):
    """Base de lo que se hace sobre un comprobante: se exige el permiso en SU empresa."""

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
                    "venta__cliente", "empresa", "tipo_comprobante"
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


def _devueltas(
    comprobante: ComprobanteVenta, v: dict, *, calcular: bool
) -> list[notas_credito.LineaDevuelta]:
    """Las líneas que llegan como números pasan a líneas reales del comprobante.

    En los motivos totales (01 y 06) el servicio calcula lo que se devuelve con el comprobante
    bloqueado al emitir; ``calcular`` lo pide antes, para la vista previa.
    """
    if v["motivo"] in MOTIVOS_TOTALES:
        if not calcular:
            return []
        return notas_credito.devueltas_de_motivo(comprobante, v["motivo"])
    por_id = {
        ln.pk: ln
        for ln in LineaVenta.objects.select_related("afectacion", "producto", "almacen").filter(
            comprobante=comprobante
        )
    }
    devueltas = []
    for d in v.get("lineas", []):
        if d["linea"] not in por_id:
            raise ValidationError({"lineas": "Hay líneas que no son de este comprobante."})
        devueltas.append(
            notas_credito.LineaDevuelta(
                por_id[d["linea"]], d["cantidad"], tuple(d.get("series", ()))
            )
        )
    return devueltas


class PendienteView(_DeComprobante):
    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, comprobante_id: int):
        """Todo lo que la pantalla de la nota necesita saber de un comprobante.

        Sus datos y los del cliente, cada línea con lo que todavía se puede devolver, lo que el
        cliente pagó por cada método (para prellenar el reembolso), las series posibles de la nota
        y si la anulación de la operación todavía es posible.
        """
        comprobante = self.comprobante()
        venta = comprobante.venta
        filas = notas_credito.pendiente_de_devolver(comprobante)
        saldo = Decimal("0")
        if venta.forma_pago == "CREDITO":
            from apps.ventas import cuentas_por_cobrar

            saldo = cuentas_por_cobrar.saldo_de(comprobante)
        anulado = comprobante.estado == ComprobanteVenta.Estado.ANULADO
        vuelve_a = {
            li.linea_venta_id: _nombre_empresa(li.empresa)
            for li in LineaVentaInterna.objects.sin_ambito()
            .filter(
                linea_venta__comprobante=comprobante,
                venta_interna__estado=VentaInterna.Estado.EMITIDO,
            )
            .select_related("empresa")
        }
        sin_devoluciones = all(f["devuelto"] <= 0 for f in filas)
        con_pendiente = any(f["disponible"] > 0 for f in filas)
        respuesta = Response(
            {
                "comprobante": comprobante.pk,
                "empresa": comprobante.empresa_id,
                "venta": venta.pk,
                "numero_completo": comprobante.numero_completo,
                "tipo_codigo": comprobante.tipo_comprobante.codigo,
                "tipo_nombre": comprobante.tipo_comprobante.nombre,
                "fecha": comprobante.fecha.isoformat(),
                "total": _dinero(comprobante.total),
                "cliente_nombre": venta.cliente_nombre,
                "cliente_tipo_documento": venta.cliente_tipo_documento,
                "cliente_documento": venta.cliente_documento,
                "cliente_direccion": venta.cliente.direccion if venta.cliente_id else "",
                "moneda": venta.moneda,
                "a_credito": venta.forma_pago == "CREDITO",
                "saldo_por_cobrar": _dinero(saldo),
                "anulado": anulado,
                "se_puede_devolver": not anulado and con_pendiente,
                "motivos": [
                    {
                        "codigo": m.value,
                        "nombre": m.label,
                        "total": m in MOTIVOS_TOTALES,
                        "disponible": m != MotivoNota.ANULACION or sin_devoluciones,
                    }
                    for m in MotivoNota
                ],
                **notas_credito.series_para_elegir(comprobante),
                "cobrado": [
                    {
                        "medio_pago": m["medio_pago"],
                        "nombre": m["nombre"],
                        "tipo": m["tipo"],
                        "requiere_referencia": m["requiere_referencia"],
                        "pagado": _dinero(m["pagado"]),
                        "devuelto": _dinero(m["devuelto"]),
                        "disponible": _dinero(m["disponible"]),
                    }
                    for m in notas_credito.reembolsable_por_metodo(comprobante)
                ],
                "lineas": [
                    {
                        "id": f["linea"].pk,
                        "descripcion": f["linea"].descripcion,
                        "unidad": f["linea"].producto.unidad.abreviatura,
                        "tipo_igv": f["linea"].afectacion.nombre,
                        "cantidad": str(f["linea"].cantidad),
                        "devuelto": str(f["devuelto"]),
                        "disponible": str(f["disponible"]),
                        "precio_unitario": str(f["linea"].precio_unitario),
                        "total": str(f["linea"].total),
                        "lleva_serie": bool(f["linea"].series),
                        "series": f["series"],
                        # Si vino de la otra empresa (venta interna), a quién vuelve al devolverla.
                        "vuelve_a": vuelve_a.get(f["linea"].pk, ""),
                    }
                    for f in filas
                ],
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class PrevisualizarView(_DeComprobante):
    @extend_schema(tags=TAG, request=NotaCreditoEntrada, responses={200: dict})
    def post(self, request, comprobante_id: int):
        """Calcula la nota sin emitirla: sus importes y a dónde va lo devuelto."""
        comprobante = self.comprobante()
        datos = NotaCreditoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        calculo = notas_credito.calcular_nota(
            comprobante, _devueltas(comprobante, v, calcular=True)
        )
        sugerido, sin_asignar = notas_credito.sugerir_reembolso(comprobante, calculo.a_reembolsar)
        respuesta = Response(
            {
                "total": str(calculo.total),
                "igv": str(calculo.igv),
                "op_gravada": str(calculo.op_gravada),
                "op_exonerada": str(calculo.op_exonerada),
                "op_inafecta": str(calculo.op_inafecta),
                "a_cuotas": str(calculo.a_cuotas),
                "a_reembolsar": str(calculo.a_reembolsar),
                # Cómo devolver el dinero por los mismos métodos con que pagó el cliente; lo que
                # no cabe en lo que pagó (sin_asignar) lo elige la persona.
                "reembolso_sugerido": [{**s, "monto": _dinero(s["monto"])} for s in sugerido],
                "reembolso_sin_asignar": _dinero(sin_asignar),
                "lineas": [
                    {
                        "linea": d.linea.pk,
                        "cantidad": str(d.cantidad),
                        "valor_venta": str(d.valor),
                        "igv": str(d.igv),
                        "total": str(d.total),
                    }
                    for d in calculo.lineas
                ],
            }
        )
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class EmitirView(_DeComprobante):
    def empresas_de_la_operacion(self, request):
        """Además de la del comprobante: las que entregaron mercadería de lo que se devuelve.

        Si el stock devuelto vuelve a la empresa que lo entregó (venta interna), quien emite la
        nota necesita el permiso también en ella.
        """
        empresas = super().empresas_de_la_operacion(request)
        datos = request.data if hasattr(request.data, "get") else {}
        if datos.get("reingresa_stock", True) in (False, "false", "False", 0, "0"):
            return empresas
        if datos.get("motivo") in MOTIVOS_TOTALES:
            lineas = None
        else:
            crudas = datos.get("lineas")
            lineas = [
                int(x["linea"])
                for x in (crudas if isinstance(crudas, list) else [])
                if isinstance(x, dict) and str(x.get("linea")).isdigit()
            ]
        entregaron = ventas_internas.empresas_que_entregaron_en(
            self.kwargs["comprobante_id"], lineas
        )
        return list(dict.fromkeys([*empresas, *entregaron]))

    @extend_schema(
        tags=TAG,
        request=NotaCreditoEntrada,
        responses={201: NotaCreditoDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento: un reintento no devuelve dos veces.",
            )
        ],
    )
    def post(self, request, comprobante_id: int):
        comprobante = self.comprobante()
        datos = NotaCreditoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        devueltas = _devueltas(comprobante, v, calcular=False)
        medios = {
            m.pk: m
            for m in MedioPago.objects.filter(
                pk__in={r["medio_pago"] for r in v.get("reembolsos", [])},
                organizacion_id=comprobante.empresa.organizacion_id,
            )
        }
        reembolsos = []
        for r in v.get("reembolsos", []):
            if r["medio_pago"] not in medios:
                raise ValidationError({"reembolsos": "Hay métodos de pago que no existen."})
            reembolsos.append(
                servicios.CobroEntrada(
                    medio_pago=medios[r["medio_pago"]],
                    monto=r["monto"],
                    referencia=r.get("referencia", ""),
                    recibido=r.get("recibido"),
                )
            )
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            nota = notas_credito.crear_nota_credito(
                comprobante,
                motivo=v["motivo"],
                devueltas=devueltas,
                reembolsos=reembolsos,
                reingresa_stock=v.get("reingresa_stock", True),
                descripcion=v.get("descripcion", ""),
                serie_id=v.get("serie_nota"),
                usuario_id=request.user.pk,
                usuario_nombre=_nombre_usuario(request.user),
            )
            nueva = _detalle(nota.pk)
            return 201, json.loads(
                json.dumps(NotaCreditoDetalleSerializer(nueva).data, default=str)
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


class ComprobanteDevolvibleSerializer(serializers.ModelSerializer):
    """Un comprobante que se puede buscar para hacerle una nota de crédito."""

    numero_completo = serializers.CharField(read_only=True)
    tipo_codigo = serializers.CharField(source="tipo_comprobante.codigo", read_only=True)
    tipo_nombre = serializers.CharField(source="tipo_comprobante.nombre", read_only=True)
    venta_numero = serializers.IntegerField(source="venta.numero", read_only=True)
    cliente_nombre = serializers.CharField(source="venta.cliente_nombre", read_only=True)
    cliente_tipo_documento = serializers.CharField(
        source="venta.cliente_tipo_documento", read_only=True
    )
    cliente_documento = serializers.CharField(source="venta.cliente_documento", read_only=True)
    moneda = serializers.CharField(source="venta.moneda", read_only=True)
    forma_pago = serializers.CharField(source="venta.forma_pago", read_only=True)

    class Meta:
        model = ComprobanteVenta
        fields = [
            "id",
            "empresa",
            "venta",
            "venta_numero",
            "numero_completo",
            "tipo_codigo",
            "tipo_nombre",
            "fecha",
            "cliente_nombre",
            "cliente_tipo_documento",
            "cliente_documento",
            "moneda",
            "forma_pago",
            "total",
        ]
        read_only_fields = fields


class DevolviblesView(generics.ListAPIView):
    """Buscar el comprobante de una empresa al que se le hará una nota de crédito.

    Solo trae comprobantes emitidos a los que todavía les queda algo por devolver. Filtros:
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
        return notas_credito.con_algo_por_devolver(queryset).order_by("-fecha", "-id")


def _detalle(pk: int) -> NotaCredito:
    return (
        _con_pendiente(
            NotaCredito.objects.select_related("venta", "comprobante__tipo_comprobante", "empresa")
        )
        .prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaNotaCredito.objects.select_related(
                    "linea_venta__producto__unidad"
                ).order_by("orden"),
            ),
            Prefetch(
                "reembolsos", queryset=ReembolsoNota.objects.select_related("medio_pago", "cuenta")
            ),
        )
        .get(pk=pk)
    )
