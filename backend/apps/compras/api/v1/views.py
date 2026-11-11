import json
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Min, Prefetch, Q, Sum
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from apps.compras.cuentas_por_pagar import anular_pago, registrar_pagos
from apps.compras.deudas import deudas_por_proveedor
from apps.compras.devoluciones import (
    deuda_pendiente,
    pendiente_de_devolver,
    series_disponibles,
)
from apps.compras.models import (
    AplicacionPago,
    Compra,
    CuotaCompra,
    LineaCompra,
    OrdenCompra,
    PagoCompra,
)
from apps.compras.servicios import (
    CuotasEntrada,
    FleteEntrada,
    LineaEntrada,
    PagoEntrada,
    anular_compra,
    preparar_compra,
    registrar_compra,
)
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    CuentaFinanciera,
    MedioPago,
    Periodicidad,
    PresentacionProducto,
    Producto,
    Proveedor,
    TipoComprobante,
    Ubicacion,
)
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import (
    AnulacionCompraEntrada,
    CompraDetalleSerializer,
    CompraEntrada,
    CompraListaSerializer,
    PagarEntrada,
    PorPagarSerializer,
)

TAG = ["compras"]
VER = "COMPRAS.VER"
CREAR = "COMPRAS.CREAR"
ANULAR = "COMPRAS.ANULAR"
PAGAR = "COMPRAS.PAGAR"
DEVOLVER = "COMPRAS.DEVOLVER"
ASIGNAR_UBICACION = "INVENTARIO.UBICACIONES.ASIGNAR"


def _entero(params, nombre: str) -> int | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    if not str(valor).isdigit():
        raise ValidationError({nombre: "Debe ser un número entero."})
    return int(valor)


def _fecha(params, nombre: str) -> date | None:
    valor = params.get(nombre)
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nombre: "Use el formato AAAA-MM-DD."}) from None


def _plano(datos):
    """Datos de una respuesta como JSON simple, para guardarlos en la idempotencia."""
    return json.loads(JSONRenderer().render(datos))


def _dinero(valor) -> str:
    """Importe como texto con 2 decimales (igual que los demás importes de la API)."""
    return f"{valor:.2f}"


def _busqueda_comprobante(q: str) -> Q:
    """Busca un comprobante por serie, número, serie y número juntos («F001-2») o N° interno."""
    condicion = Q(comprobante_numero__icontains=q) | Q(comprobante_serie__icontains=q)
    if "-" in q:
        serie, _, numero = (parte.strip() for parte in q.partition("-"))
        condicion |= Q(
            comprobante_serie__icontains=serie,
            comprobante_numero__icontains=numero.lstrip("0") or numero,
        )
    if q.isdigit() and len(q) <= 9:
        condicion |= Q(numero=int(q))
    return condicion


def _uno(modelo, pk, campo: str, mensaje: str, **filtros):
    """El registro ``pk`` del ámbito activo, o un error de campo claro."""
    objeto = modelo.objects.filter(pk=pk, **filtros).first()
    if objeto is None:
        raise ValidationError({campo: mensaje})
    return objeto


class CompraViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Compras de una empresa (``?empresa=ID`` obligatorio en el listado).

    Filtros: ``proveedor``, ``almacen``, ``estado``, ``forma_pago``, ``desde``, ``hasta``
    (fechas AAAA-MM-DD) y ``q`` (comprobante, número interno o proveedor).
    """

    modelo = Compra
    serializer_class = CompraListaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": CREAR,
        "calcular": CREAR,
        "anular": ANULAR,
        "por_pagar": VER,
        "resumen_por_pagar": VER,
        "por_pagar_proveedores": VER,
        "pagar": PAGAR,
        "anular_pago": ANULAR,
        "por_devolver": DEVOLVER,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                Compra.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_class(self):
        if self.action in ("retrieve", "anular"):
            return CompraDetalleSerializer
        return CompraListaSerializer

    def _base(self):
        return Compra.objects.select_related("proveedor", "almacen", "tipo_comprobante", "orden")

    def _con_detalle(self, queryset):
        return queryset.prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaCompra.objects.select_related("producto").order_by("orden"),
            ),
            Prefetch(
                "pagos",
                queryset=PagoCompra.objects.select_related("medio_pago", "cuenta")
                .prefetch_related(
                    Prefetch(
                        "aplicaciones",
                        queryset=AplicacionPago.objects.select_related("cuota").order_by(
                            "cuota__numero"
                        ),
                    )
                )
                .order_by("id"),
            ),
            Prefetch("cuotas", queryset=CuotaCompra.objects.order_by("numero")),
        )

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = self._base()
        if self.action in ("retrieve", "anular", "pagar", "anular_pago", "por_devolver"):
            queryset = self._con_detalle(queryset)
        elif self.action == "list":
            queryset = queryset.annotate(cantidad_lineas=Count("lineas"))
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        if (empresa := _entero(params, "empresa")) is not None:
            queryset = queryset.filter(empresa_id=empresa)
        for campo in ("estado", "forma_pago"):
            if valor := params.get(campo):
                queryset = queryset.filter(**{campo: valor})
        for campo in ("proveedor", "almacen"):
            if (valor := _entero(params, campo)) is not None:
                queryset = queryset.filter(**{f"{campo}_id": valor})
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha_emision__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha_emision__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                _busqueda_comprobante(q)
                | Q(proveedor__nombre__icontains=q)
                | Q(nro_guia__icontains=q)
            )
        return queryset.order_by("-fecha_emision", "-id")

    # -- armar los argumentos del servicio a partir de lo que llega ---------------
    def _argumentos(self, validados: dict, empresa: Empresa) -> dict:
        org = empresa.organizacion_id
        proveedor = _uno(Proveedor, validados["proveedor"], "proveedor", "No existe.")
        almacen = _uno(
            Almacen, validados["almacen"], "almacen", "Elija un almacén de la empresa.",
            empresa=empresa,
        )  # fmt: skip
        tipo = TipoComprobante.objects.filter(
            organizacion_id=org, codigo=validados["tipo_comprobante"]
        ).first()
        if tipo is None:
            raise ValidationError({"tipo_comprobante": "El tipo de comprobante no existe."})
        orden = None
        if validados.get("orden"):
            orden = OrdenCompra.objects.filter(pk=validados["orden"], empresa=empresa).first()
            if orden is None:
                raise ValidationError({"orden": "La orden de compra no existe en esta empresa."})
        return {
            "empresa": empresa,
            "proveedor": proveedor,
            "almacen": almacen,
            "tipo_comprobante": tipo,
            "comprobante_serie": validados.get("comprobante_serie", ""),
            "comprobante_numero": validados["comprobante_numero"],
            "fecha_emision": validados["fecha_emision"],
            "nro_guia": validados.get("nro_guia", ""),
            "observacion": validados.get("observacion", ""),
            "moneda": validados["moneda"],
            "tipo_cambio": validados.get("tipo_cambio"),
            "precios_incluyen_igv": validados["precios_incluyen_igv"],
            "ajuste_redondeo": validados["ajuste_redondeo"],
            "forma_pago": validados["forma_pago"],
            "lineas": self._lineas(validados["lineas"], org),
            "pagos": self._pagos(validados.get("pagos", ()), empresa),
            "cuotas": self._cuotas(validados.get("cuotas"), org),
            "flete": self._flete(validados.get("flete"), empresa),
            "orden": orden,
        }

    @staticmethod
    def _lineas(lineas: list[dict], org: int) -> list[LineaEntrada]:
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
            series = ln.get("series", ())
            resultado.append(
                LineaEntrada(
                    producto=producto,
                    cantidad=ln["cantidad"],
                    precio_unitario=ln["precio_unitario"],
                    presentacion=presentaciones.get(ln.get("presentacion")),
                    afectacion=afectaciones.get(ln.get("afectacion")),
                    series=tuple(s["numero"] for s in series),
                    datos_series=tuple(s["otros_datos"] for s in series)
                    if any(s["otros_datos"] for s in series)
                    else (),
                    ubicacion_id=ln.get("ubicacion"),
                    lote=ln.get("lote", ""),
                    linea_orden=ln.get("linea_orden"),
                )
            )
        return resultado

    @staticmethod
    def _pagos(pagos, empresa: Empresa) -> list[PagoEntrada]:
        return [
            PagoEntrada(
                medio_pago=_uno(
                    MedioPago, p["medio_pago"], "pagos", "Hay métodos de pago que no existen."
                ),
                cuenta=_uno(
                    CuentaFinanciera,
                    p["cuenta"],
                    "pagos",
                    "Hay cajas o cuentas que no existen.",
                    empresa=empresa,
                ),  # fmt: skip
                monto=p["monto"],
                fecha=p.get("fecha"),
                referencia=p.get("referencia", ""),
                tipo_cambio=p.get("tipo_cambio"),
                aporte_socio=bool(p.get("aporte_socio", False)),
            )
            for p in pagos
        ]

    @staticmethod
    def _cuotas(cuotas, org: int) -> CuotasEntrada | None:
        if not cuotas:
            return None
        periodicidad = _uno(
            Periodicidad, cuotas["periodicidad"], "cuotas", "No existe esa periodicidad."
        )
        return CuotasEntrada(cuotas["cantidad"], cuotas["primera_fecha"], periodicidad)

    def _flete(self, flete, empresa: Empresa) -> FleteEntrada | None:
        if not flete:
            return None
        return FleteEntrada(
            monto=flete["monto"],
            al_costo=flete["al_costo"],
            comprobante_tipo=flete.get("comprobante_tipo", ""),
            comprobante_serie=flete.get("comprobante_serie", ""),
            comprobante_numero=flete.get("comprobante_numero", ""),
            pagos=tuple(self._pagos(flete.get("pagos", ()), empresa)),
        )

    def _empresa_y_argumentos(self, request):
        datos = CompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        validados = datos.validated_data
        empresa = Empresa.objects.filter(pk=validados["empresa"], estado=Estado.ACTIVO).first()
        if empresa is None:
            raise ValidationError({"empresa": "Elija una empresa activa."})
        return validados, empresa, self._argumentos(validados, empresa)

    def _recargar(self, pk: int) -> Compra:
        return self._con_detalle(self._base()).get(pk=pk)

    # -- registrar ----------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=CompraEntrada,
        responses={201: CompraDetalleSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento (8 a 128 caracteres). Un reintento con la "
                "misma clave devuelve el mismo resultado sin registrar de nuevo.",
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        validados, empresa, argumentos = self._empresa_y_argumentos(request)
        if any(ln.ubicacion_id for ln in argumentos["lineas"]):
            motor.exigir_permiso(request.user, ASIGNAR_UBICACION, empresa.pk)
            self._validar_ubicaciones(argumentos, empresa)
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            with transaction.atomic():
                compra = registrar_compra(**argumentos)
            return 201, _plano(CompraDetalleSerializer(self._recargar(compra.pk)).data)

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

    @staticmethod
    def _validar_ubicaciones(argumentos: dict, empresa: Empresa) -> None:
        pedidas = {ln.ubicacion_id for ln in argumentos["lineas"] if ln.ubicacion_id}
        validas = set(
            Ubicacion.objects.filter(
                pk__in=pedidas, almacen=argumentos["almacen"], empresa=empresa
            ).values_list("pk", flat=True)
        )
        if validas != pedidas:
            raise ValidationError({"lineas": "Elija una ubicación activa de ese almacén."})

    # -- vista previa: totales y cuotas sin guardar nada -------------------------------
    @extend_schema(tags=TAG, request=CompraEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="calcular")
    def calcular(self, request):
        """Calcula totales, costo por línea y cuotas sin registrar nada."""
        _, _, argumentos = self._empresa_y_argumentos(request)
        p = preparar_compra(**argumentos, completa=False)
        r = p.resultado
        return Response(
            {
                "moneda": p.moneda,
                "tipo_cambio": f"{p.tipo_cambio:.4f}",
                "igv_al_costo": p.igv_al_costo,
                "op_gravada": _dinero(r.op_gravada),
                "igv": _dinero(r.igv),
                "op_ivap": _dinero(r.op_ivap),
                "ivap": _dinero(r.ivap),
                "op_exonerada": _dinero(r.op_exonerada),
                "op_inafecta": _dinero(r.op_inafecta),
                "ajuste_redondeo": _dinero(r.ajuste_redondeo),
                "total": _dinero(r.total),
                "orden": p.orden.pk if p.orden else None,
                "avisos_precio": [
                    {
                        "linea_orden": a["linea_orden"],
                        "producto": a["producto"],
                        "producto_nombre": a["producto_nombre"],
                        "precio_pactado": f"{a['precio_pactado']:f}",
                        "precio_facturado": f"{a['precio_facturado']:f}",
                        "diferencia": f"{a['diferencia']:f}",
                        "porcentaje": None if a["porcentaje"] is None else f"{a['porcentaje']:f}",
                    }
                    for a in p.avisos_precio
                ],
                "lineas": [
                    {
                        "afectacion_codigo": afectacion.codigo,
                        "afectacion_nombre": afectacion.nombre,
                        "tasa": f"{tasa:.2f}",
                        "cantidad_base": f"{base:.3f}",
                        "valor_venta": _dinero(linea.valor_venta),
                        "impuesto": _dinero(linea.impuesto),
                        "total": _dinero(linea.total),
                        "costo_soles": _dinero(linea.costo_soles),
                        "flete_asignado": _dinero(linea.flete_asignado),
                    }
                    for (afectacion, tasa), base, linea in zip(
                        p.afectaciones, p.cantidades_base, r.lineas, strict=True
                    )
                ],
                "cuotas": [
                    {
                        "numero": c.numero,
                        "fecha_vencimiento": c.fecha.isoformat(),
                        "monto": _dinero(c.monto),
                    }
                    for c in p.cuotas
                ],
            }
        )

    # -- anular -------------------------------------------------------------------
    @extend_schema(
        tags=TAG, request=AnulacionCompraEntrada, responses={200: CompraDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula la compra y devuelve su entrada al inventario."""
        compra = self.get_object()
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        anular_compra(compra, motivo=datos.validated_data["motivo"])
        return Response(CompraDetalleSerializer(self._recargar(compra.pk)).data)

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=True, methods=["get"], url_path="por-devolver")
    def por_devolver(self, request, pk=None):
        """Lo que todavía se puede devolver de cada línea de la compra, y su deuda pendiente."""
        compra = self.get_object()
        lineas = {ln.pk: ln for ln in compra.lineas.all()}
        filas = []
        for fila in pendiente_de_devolver(compra):
            filas.append(
                {
                    **fila,
                    "comprado": f"{fila['comprado']:f}",
                    "devuelto": f"{fila['devuelto']:f}",
                    "pendiente": f"{fila['pendiente']:f}",
                    "series_disponibles": (
                        series_disponibles(compra, lineas[fila["linea"]])
                        if fila["lleva_serie"]
                        else []
                    ),
                }
            )
        return Response(
            {
                "compra": compra.pk,
                "estado": compra.estado,
                "moneda": compra.moneda,
                "forma_pago": compra.forma_pago,
                "deuda_pendiente": _dinero(deuda_pendiente(compra)),
                "lineas": filas,
            }
        )

    # -- cuentas por pagar ------------------------------------------------------------
    def _por_pagar_base(self):
        """Compras a crédito vigentes con lo que se debe, lo vencido y el próximo vencimiento."""
        hoy = timezone.localdate()
        pendiente = ExpressionWrapper(
            F("cuotas__monto") - F("cuotas__pagado"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
        queryset = filtrar_por_alcance(
            self._base().filter(estado=Compra.Estado.EMITIDO, forma_pago="CREDITO"),
            self.request.user,
            VER,
        )
        return queryset.annotate(
            pagado=Sum("cuotas__pagado"),
            saldo=Sum(pendiente),
            saldo_vencido=Sum(pendiente, filter=Q(cuotas__fecha_vencimiento__lt=hoy)),
            proximo_vencimiento=Min(
                "cuotas__fecha_vencimiento", filter=Q(cuotas__pagado__lt=F("cuotas__monto"))
            ),
        ).filter(saldo__gt=0)

    @extend_schema(tags=TAG, responses={200: PorPagarSerializer(many=True)})
    @action(detail=False, methods=["get"], url_path="por-pagar")
    def por_pagar(self, request):
        """Compras a crédito con deuda (``?empresa=ID`` obligatorio).

        Filtros: ``proveedor``, ``vencimiento`` (``vencidas`` o ``por_vencer``), ``vence_hasta``
        (fecha AAAA-MM-DD), ``q`` (comprobante o proveedor). Las más urgentes primero.
        """
        params = request.query_params
        queryset = self._por_pagar_base().filter(empresa_id=_entero(params, "empresa"))
        if (proveedor := _entero(params, "proveedor")) is not None:
            queryset = queryset.filter(proveedor_id=proveedor)
        estado = params.get("vencimiento")
        if estado == "vencidas":
            queryset = queryset.filter(saldo_vencido__gt=0)
        elif estado == "por_vencer":
            queryset = queryset.filter(Q(saldo_vencido__isnull=True) | Q(saldo_vencido=0))
        if (hasta := _fecha(params, "vence_hasta")) is not None:
            queryset = queryset.filter(proximo_vencimiento__lte=hasta)
        q = (params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(_busqueda_comprobante(q) | Q(proveedor__nombre__icontains=q))
        queryset = queryset.order_by("proximo_vencimiento", "id")
        contexto = {**self.get_serializer_context(), "hoy": timezone.localdate()}
        pagina = self.paginate_queryset(queryset)
        return self.get_paginated_response(
            PorPagarSerializer(pagina, many=True, context=contexto).data
        )

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=False, methods=["get"], url_path="por-pagar/proveedores")
    def por_pagar_proveedores(self, request):
        """Lo que se debe a cada proveedor, sumado por moneda (``?empresa=ID`` obligatorio).

        Filtros: ``q`` (nombre o documento), ``vencimiento`` (``vencidas`` o ``por_vencer``),
        ``vence_hasta``. Primero el más atrasado. Las facturas de uno se piden con
        ``/compras/por-pagar/?proveedor=ID``.
        """
        params = request.query_params
        compras = filtrar_por_alcance(
            Compra.objects.filter(
                empresa_id=_entero(params, "empresa"),
                estado=Compra.Estado.EMITIDO,
                forma_pago="CREDITO",
            ),
            request.user,
            VER,
        )
        filas = deudas_por_proveedor(
            compras,
            hoy=timezone.localdate(),
            q=(params.get("q") or "").strip(),
            vencimiento=params.get("vencimiento", ""),
            vence_hasta=_fecha(params, "vence_hasta"),
        )

        def dinero(valor) -> str:
            return f"{valor:.2f}"

        pagina = self.paginate_queryset(filas)
        return self.get_paginated_response(
            [
                {
                    **f,
                    "proximo_vencimiento": f["proximo_vencimiento"].isoformat(),
                    "montos": [
                        {
                            **m,
                            "saldo": dinero(m["saldo"]),
                            "vencido": dinero(m["vencido"]),
                            "por_vencer_7_dias": dinero(m["por_vencer_7_dias"]),
                        }
                        for m in f["montos"]
                    ],
                }
                for f in pagina
            ]
        )

    @extend_schema(tags=TAG, responses={200: dict})
    @action(detail=False, methods=["get"], url_path="por-pagar/resumen")
    def resumen_por_pagar(self, request):
        """Totales de lo que se debe, por moneda: todo, lo vencido y lo que vence en 7 días."""
        hoy = timezone.localdate()
        pendiente = ExpressionWrapper(
            F("monto") - F("pagado"), output_field=DecimalField(max_digits=16, decimal_places=2)
        )
        visibles = filtrar_por_alcance(Compra.objects.all(), request.user, VER)
        filas = (
            CuotaCompra.objects.filter(
                compra__in=visibles.filter(
                    empresa_id=_entero(request.query_params, "empresa"),
                    estado=Compra.Estado.EMITIDO,
                    forma_pago="CREDITO",
                ),
                pagado__lt=F("monto"),
            )
            .values("compra__moneda")
            .annotate(
                saldo=Sum(pendiente),
                vencido=Sum(pendiente, filter=Q(fecha_vencimiento__lt=hoy)),
                por_vencer=Sum(
                    pendiente,
                    filter=Q(
                        fecha_vencimiento__gte=hoy, fecha_vencimiento__lte=hoy + timedelta(days=7)
                    ),
                ),
                compras=Count("compra", distinct=True),
            )
            .order_by("compra__moneda")
        )

        def dinero(valor) -> str:
            return f"{(valor or 0):.2f}"

        return Response(
            [
                {
                    "moneda": f["compra__moneda"],
                    "saldo": dinero(f["saldo"]),
                    "vencido": dinero(f["vencido"]),
                    "por_vencer_7_dias": dinero(f["por_vencer"]),
                    "compras": f["compras"],
                }
                for f in filas
            ]
        )

    @extend_schema(
        tags=TAG,
        request=PagarEntrada,
        responses={201: CompraDetalleSerializer},
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
        """Paga una compra a crédito: el monto cubre las cuotas más antiguas (o la elegida)."""
        compra = self.get_object()
        datos = PagarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        pagos = [
            PagoEntrada(
                medio_pago=_uno(
                    MedioPago, p["medio_pago"], "pagos", "Hay métodos de pago que no existen."
                ),
                cuenta=_uno(
                    CuentaFinanciera, p["cuenta"], "pagos", "Hay cajas o cuentas que no existen.",
                    empresa=compra.empresa,
                ),
                monto=p["monto"],
                fecha=v.get("fecha"),
                referencia=p.get("referencia", ""),
                tipo_cambio=p.get("tipo_cambio"),
                aporte_socio=bool(p.get("aporte_socio", False)),
            )
            for p in v["pagos"]
        ]  # fmt: skip
        clave = clave_desde_request(request)
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            registrar_pagos(compra, pagos=pagos, cuota_ids=v.get("cuotas"))
            return 201, _plano(CompraDetalleSerializer(self._recargar(compra.pk)).data)

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
        tags=TAG, request=AnulacionCompraEntrada, responses={200: CompraDetalleSerializer}
    )
    @action(detail=True, methods=["post"], url_path=r"pagos/(?P<pago_id>\d+)/anular")
    def anular_pago(self, request, pk=None, pago_id=None):
        """Revierte un pago hecho a una compra a crédito (cada cuota recupera lo recibido)."""
        compra = self.get_object()
        pago = PagoCompra.objects.filter(pk=pago_id, compra=compra).first()
        if pago is None:
            raise Http404
        datos = AnulacionCompraEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        anular_pago(pago, motivo=datos.validated_data["motivo"])
        return Response(CompraDetalleSerializer(self._recargar(compra.pk)).data)
