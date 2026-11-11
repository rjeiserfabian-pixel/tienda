import json
from datetime import date

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Subquery
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import diferencia, registrar
from apps.core.idempotencia import clave_desde_request, ejecutar_idempotente
from apps.core.pagination import PaginaEstandar
from apps.inventario import consultas, periodos, ubicaciones
from apps.inventario.models import (
    CierrePeriodo,
    LineaMovimiento,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    registrar_movimiento,
    registrar_traspaso,
)
from apps.mantenimiento.models import (
    Almacen,
    Cliente,
    Producto,
    Proveedor,
    UbicacionProducto,
)
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.exceptions import PermisoDenegado
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import (
    AnulacionEntrada,
    KardexSerializer,
    MovimientoDetalleSerializer,
    MovimientoEntrada,
    MovimientoListaSerializer,
    PeriodoEntrada,
    SerieDatosEntrada,
    SerieSerializer,
    StockSerializer,
    TraspasoEntrada,
    UbicacionAsignarEntrada,
    UbicacionProductoSerializer,
)

TAG = ["inventario"]
VER = "INVENTARIO.VER"
TRASPASAR = "INVENTARIO.TRASPASOS.REGISTRAR"
REGISTRAR = "INVENTARIO.MOVIMIENTOS.REGISTRAR"
ANULAR = "INVENTARIO.MOVIMIENTOS.ANULAR"
AJUSTAR = "INVENTARIO.AJUSTAR"
EDITAR_SERIE = "INVENTARIO.SERIES.EDITAR"
SALDO_INICIAL = "INVENTARIO.SALDO_INICIAL.CARGAR"
CERRAR_PERIODOS = "INVENTARIO.PERIODOS.CERRAR"
ASIGNAR_UBICACION = "INVENTARIO.UBICACIONES.ASIGNAR"

# Además de registrar movimientos, estos orígenes exigen un permiso propio (son más delicados).
_PERMISO_EXTRA_POR_ORIGEN = {
    OrigenMovimiento.AJUSTE: AJUSTAR,
    OrigenMovimiento.MERMA: AJUSTAR,
    OrigenMovimiento.SALDO_INICIAL: SALDO_INICIAL,
}


# ---------------------------------------------------------------------------
# Utilidades de entrada
# ---------------------------------------------------------------------------
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


def _empresa_activa(empresa_id: int) -> Empresa:
    empresa = Empresa.objects.filter(pk=empresa_id, estado=Estado.ACTIVO).first()
    if empresa is None:
        raise ValidationError({"empresa": "Elija una empresa activa."})
    return empresa


def _plano(datos):
    """Datos de una respuesta como JSON simple, para guardarlos en la idempotencia."""
    return json.loads(JSONRenderer().render(datos))


class _EmpresaExplicita:
    """La empresa es obligatoria y explícita (``?empresa=ID``); nunca se asume una por defecto."""

    requiere_empresa = True

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    def _empresa_filtrada(self) -> int:
        return _entero(self.request.query_params, "empresa")


# ---------------------------------------------------------------------------
# Movimientos
# ---------------------------------------------------------------------------
class MovimientoViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Movimientos de inventario de una empresa (``?empresa=ID`` obligatorio).

    Filtros: ``almacen``, ``producto``, ``tipo``, ``origen``, ``estado``, ``desde``, ``hasta``
    (fechas AAAA-MM-DD) y ``q`` (comprobante, observación o proveedor/cliente).
    """

    modelo = MovimientoInventario
    serializer_class = MovimientoListaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "post", "head", "options"]
    lookup_value_regex = r"\d+"
    requiere_empresa = True
    permisos_por_accion = {
        "list": VER,
        "retrieve": VER,
        "create": REGISTRAR,
        "traspaso": TRASPASAR,
        "anular": ANULAR,
    }

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                MovimientoInventario.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        return [empresa_declarada(request, self)]

    def get_serializer_class(self):
        if self.action in ("retrieve", "anular"):
            return MovimientoDetalleSerializer
        return MovimientoListaSerializer

    def _base(self):
        return MovimientoInventario.objects.select_related("almacen", "proveedor", "cliente")

    def _con_lineas(self, queryset):
        return queryset.prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaMovimiento.objects.select_related("producto__unidad")
                .prefetch_related("series_entrada", "series_salida")
                .order_by("orden", "id"),
            )
        )

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = self._base()
        if self.action in ("retrieve", "anular"):
            queryset = self._con_lineas(queryset)
        elif self.action == "list":
            queryset = queryset.annotate(cantidad_lineas=Count("lineas"))
        queryset = filtrar_por_alcance(queryset, self.request.user, codigo)
        if self.action != "list":
            return queryset
        params = self.request.query_params
        empresa_id = _entero(params, "empresa")
        if empresa_id is not None:
            queryset = queryset.filter(empresa_id=empresa_id)
        for campo in ("tipo", "origen", "estado"):
            valor = params.get(campo)
            if valor:
                queryset = queryset.filter(**{campo: valor})
        if (almacen := _entero(params, "almacen")) is not None:
            queryset = queryset.filter(almacen_id=almacen)
        if (desde := _fecha(params, "desde")) is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if (hasta := _fecha(params, "hasta")) is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        if (producto := _entero(params, "producto")) is not None:
            queryset = queryset.filter(
                Exists(
                    LineaMovimiento.objects.filter(movimiento=OuterRef("pk"), producto_id=producto)
                )
            )
        q = (params.get("q") or "").strip()
        if q:
            condicion = (
                Q(comprobante_numero__icontains=q)
                | Q(comprobante_serie__icontains=q)
                | Q(observacion__icontains=q)
                | Q(proveedor__nombre__icontains=q)
                | Q(cliente__nombre__icontains=q)
            )
            if q.isdigit() and len(q) <= 9:
                condicion |= Q(numero=int(q))
            queryset = queryset.filter(condicion)
        return queryset.order_by("-fecha", "-id")

    # -- registrar ----------------------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=MovimientoEntrada,
        responses={201: MovimientoDetalleSerializer},
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
        datos = MovimientoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        validados = datos.validated_data
        empresa = _empresa_activa(validados["empresa"])
        extra = _PERMISO_EXTRA_POR_ORIGEN.get(validados["origen"])
        if extra:
            motor.exigir_permiso(request.user, extra, empresa.pk)
        clave = clave_desde_request(request)
        argumentos = self._argumentos(validados, empresa)
        ubicadas = self._ubicaciones_pedidas(validados, empresa)
        # Huella estable del cuerpo (el cuerpo crudo ya lo consumió el parser de DRF).
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            # Movimiento y ubicaciones van juntos: si una ubicación no vale, no se registra nada.
            with transaction.atomic():
                movimiento = registrar_movimiento(**argumentos)
                for producto_id, ubicacion_id in ubicadas.items():
                    ubicaciones.asignar_ubicacion(
                        empresa=empresa,
                        almacen_id=validados["almacen"],
                        producto_id=producto_id,
                        ubicacion_id=ubicacion_id,
                    )
            return 201, _plano(MovimientoDetalleSerializer(self._recargar(movimiento.pk)).data)

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

    def _recargar(self, pk: int) -> MovimientoInventario:
        return self._con_lineas(self._base()).get(pk=pk)

    def _ubicaciones_pedidas(self, validados: dict, empresa: Empresa) -> dict[int, int]:
        """Producto → ubicación pedida en las líneas. Solo las entradas pueden fijarla."""
        pedidas = {
            linea["producto"]: linea["ubicacion"]
            for linea in validados["lineas"]
            if linea.get("ubicacion")
        }
        if not pedidas:
            return {}
        if validados["tipo"] != TipoMovimiento.ENTRADA:
            raise ValidationError({"lineas": "La ubicación solo se indica en las entradas."})
        motor.exigir_permiso(self.request.user, ASIGNAR_UBICACION, empresa.pk)
        return pedidas

    def _argumentos(self, validados: dict, empresa: Empresa) -> dict:
        almacen = Almacen.objects.filter(pk=validados["almacen"], empresa=empresa).first()
        if almacen is None:
            raise ValidationError({"almacen": "Elija un almacén de la empresa."})
        productos = self._productos(validados["lineas"])
        return {
            "empresa": empresa,
            "almacen": almacen,
            "tipo": validados["tipo"],
            "origen": validados["origen"],
            "fecha": validados["fecha"],
            "tipo_operacion": validados.get("tipo_operacion") or None,
            "proveedor": self._tercero(Proveedor, validados.get("proveedor"), "proveedor"),
            "cliente": self._tercero(Cliente, validados.get("cliente"), "cliente"),
            "comprobante_tipo": validados.get("comprobante_tipo", ""),
            "comprobante_serie": validados.get("comprobante_serie", ""),
            "comprobante_numero": validados.get("comprobante_numero", ""),
            "comprobante_fecha": validados.get("comprobante_fecha"),
            "moneda": validados["moneda"],
            "tipo_cambio": validados.get("tipo_cambio"),
            "precios_incluyen_igv": validados["precios_incluyen_igv"],
            "igv_porcentaje": validados.get("igv_porcentaje"),
            "observacion": validados.get("observacion", ""),
            "lineas": [
                LineaNueva(
                    productos[linea["producto"]],
                    linea["cantidad"],
                    linea.get("precio_unitario"),
                    tuple(s["numero"] for s in linea.get("series", ())),
                    tuple(s["otros_datos"] for s in linea.get("series", ())),
                )
                for linea in validados["lineas"]
            ],
        }

    @staticmethod
    def _productos(lineas: list[dict]) -> dict[int, Producto]:
        pedidos = {linea["producto"] for linea in lineas}
        productos = {p.pk: p for p in Producto.objects.filter(pk__in=pedidos)}
        if set(productos) != pedidos:
            raise ValidationError({"lineas": "Hay productos que no existen."})
        return productos

    @staticmethod
    def _tercero(modelo, pk, campo: str):
        if pk is None:
            return None
        tercero = modelo.objects.filter(pk=pk).first()
        if tercero is None:
            raise ValidationError({campo: "No existe."})
        return tercero

    # -- traspaso entre almacenes -------------------------------------------------
    @extend_schema(
        tags=TAG,
        request=TraspasoEntrada,
        responses={201: dict},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                str,
                OpenApiParameter.HEADER,
                required=True,
                description="Clave única por intento (8 a 128 caracteres).",
            )
        ],
    )
    @action(detail=False, methods=["post"], url_path="traspaso")
    def traspaso(self, request):
        """Traspasa mercadería entre dos almacenes de la empresa. Responde salida y entrada."""
        datos = TraspasoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        empresa = _empresa_activa(v["empresa"])
        clave = clave_desde_request(request)
        almacenes = {
            campo: Almacen.objects.filter(pk=v[campo], empresa=empresa).first()
            for campo in ("almacen_origen", "almacen_destino")
        }
        for campo, almacen in almacenes.items():
            if almacen is None:
                raise ValidationError({campo: "Elija un almacén de la empresa."})
        productos = self._productos(v["lineas"])
        lineas = [
            LineaNueva(
                productos[linea["producto"]],
                linea["cantidad"],
                series=tuple(s["numero"] for s in linea.get("series", ())),
            )
            for linea in v["lineas"]
        ]
        cuerpo = json.dumps(request.data, sort_keys=True, default=str).encode()

        def operacion():
            salida, entrada = registrar_traspaso(
                empresa=empresa,
                origen=almacenes["almacen_origen"],
                destino=almacenes["almacen_destino"],
                fecha=v["fecha"],
                lineas=lineas,
                observacion=v.get("observacion", ""),
            )
            return 201, _plano(
                {
                    "salida": MovimientoDetalleSerializer(self._recargar(salida.pk)).data,
                    "entrada": MovimientoDetalleSerializer(self._recargar(entrada.pk)).data,
                }
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

    # -- anular -------------------------------------------------------------------
    @extend_schema(tags=TAG, request=AnulacionEntrada, responses={200: MovimientoDetalleSerializer})
    @action(detail=True, methods=["post"], url_path="anular")
    def anular(self, request, pk=None):
        """Anula el movimiento creando su extorno. Responde con ambos."""
        movimiento = self.get_object()
        datos = AnulacionEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        extorno = anular_movimiento(movimiento, motivo=datos.validated_data["motivo"])
        return Response(
            {
                "movimiento": MovimientoDetalleSerializer(self._recargar(movimiento.pk)).data,
                "extorno": MovimientoDetalleSerializer(self._recargar(extorno.pk)).data,
            }
        )


# ---------------------------------------------------------------------------
# Stock y Kardex
# ---------------------------------------------------------------------------
class StockViewSet(
    _EmpresaExplicita, ScopedQuerysetMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Existencias actuales por almacén y producto (``?empresa=ID`` obligatorio).

    Filtros: ``almacen``, ``producto``, ``q`` (nombre, código o código de barras),
    ``bajo_minimo=1`` e ``incluir_cero=1`` (por defecto solo lo que tiene stock). ``orden=reciente``
    pone primero lo que tuvo movimiento más recientemente.
    """

    modelo = SaldoStock
    campo_propio = None  # el stock no pertenece a quien lo movió
    serializer_class = StockSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    permisos_por_accion = {"list": VER}

    def get_queryset(self):
        queryset = super().get_queryset().select_related("almacen", "producto__unidad")
        params = self.request.query_params
        queryset = queryset.filter(empresa_id=self._empresa_filtrada())
        # Dónde está cada producto en su almacén (una subconsulta; sin consultas por fila).
        donde = UbicacionProducto.objects.filter(
            almacen_id=OuterRef("almacen_id"), producto_id=OuterRef("producto_id")
        )
        queryset = queryset.annotate(
            ubicacion_id=Subquery(donde.values("ubicacion_id")[:1]),
            ubicacion_codigo=Subquery(donde.values("ubicacion__codigo")[:1]),
            ubicacion_nombre=Subquery(donde.values("ubicacion__nombre")[:1]),
        )
        if (ubicacion := _entero(params, "ubicacion")) is not None:
            queryset = queryset.filter(ubicacion_id=ubicacion)
        if (almacen := _entero(params, "almacen")) is not None:
            queryset = queryset.filter(almacen_id=almacen)
        if (producto := _entero(params, "producto")) is not None:
            queryset = queryset.filter(producto_id=producto)
        if params.get("incluir_cero") != "1":
            queryset = queryset.filter(cantidad__gt=0)
        if params.get("bajo_minimo") == "1":
            queryset = queryset.filter(
                producto__stock_minimo__gt=0, cantidad__lte=F("producto__stock_minimo")
            )
        q = (params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                Q(producto__nombre__icontains=q)
                | Q(producto__codigo__icontains=q)
                | Q(producto__codigo_barras__icontains=q)
            )
        if params.get("orden") == "reciente":  # lo que se movió último, primero
            return queryset.order_by("-actualizado_en", "id")
        return queryset.order_by("producto__nombre", "almacen__codigo", "id")


class UbicacionProductoViewSet(
    _EmpresaExplicita, ScopedQuerysetMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Ubicación de cada producto en cada almacén (``?empresa=ID`` obligatorio).

    Filtros: ``almacen``, ``producto``. ``POST asignar/`` pone, cambia o quita (``ubicacion``
    en ``null``) la ubicación de un producto en un almacén.
    """

    modelo = UbicacionProducto
    campo_propio = None
    serializer_class = UbicacionProductoSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    permisos_por_accion = {"list": VER, "asignar": ASIGNAR_UBICACION}

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(empresa_id=self._empresa_filtrada())
            .select_related("almacen", "ubicacion")
        )
        params = self.request.query_params
        if (almacen := _entero(params, "almacen")) is not None:
            queryset = queryset.filter(almacen_id=almacen)
        if (producto := _entero(params, "producto")) is not None:
            queryset = queryset.filter(producto_id=producto)
        return queryset.order_by("almacen__codigo", "id")

    @extend_schema(tags=TAG, request=UbicacionAsignarEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="asignar")
    def asignar(self, request):
        datos = UbicacionAsignarEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        asignada = ubicaciones.asignar_ubicacion(
            empresa=_empresa_activa(v["empresa"]),
            almacen_id=v["almacen"],
            producto_id=v["producto"],
            ubicacion_id=v["ubicacion"],
        )
        if asignada is None:  # se quitó la ubicación
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(UbicacionProductoSerializer(asignada).data)


class KardexViewSet(
    _EmpresaExplicita, ScopedQuerysetMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Kardex de UN producto en UN almacén (``empresa``, ``almacen`` y ``producto`` obligatorios).

    Opcionales: ``desde`` y ``hasta`` (AAAA-MM-DD). Devuelve las líneas en orden cronológico con
    el saldo después de cada una, y el ``saldo_inicial`` con el que arranca el rango pedido.
    """

    modelo = LineaMovimiento
    campo_propio = None
    serializer_class = KardexSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    permisos_por_accion = {"list": VER}

    def _parametros(self):
        params = self.request.query_params
        faltan = [n for n in ("empresa", "almacen", "producto") if not params.get(n)]
        if faltan:
            raise ValidationError(dict.fromkeys(faltan, "Es obligatorio para consultar el Kardex."))
        return (
            _entero(params, "empresa"),
            _entero(params, "almacen"),
            _entero(params, "producto"),
            _fecha(params, "desde"),
            _fecha(params, "hasta"),
        )

    def get_queryset(self):
        empresa, almacen, producto, desde, hasta = self._parametros()
        queryset = (
            super()
            .get_queryset()
            .filter(empresa_id=empresa, almacen_id=almacen, producto_id=producto)
            .select_related("movimiento")
        )
        if desde is not None:
            queryset = queryset.filter(fecha__gte=desde)
        if hasta is not None:
            queryset = queryset.filter(fecha__lte=hasta)
        return queryset.order_by("fecha", "movimiento_id", "id")

    def list(self, request, *args, **kwargs):
        respuesta = super().list(request, *args, **kwargs)
        empresa, almacen, producto, desde, _ = self._parametros()
        respuesta.data["saldo_inicial"] = consultas.saldo_al_inicio(
            empresa, almacen, producto, desde
        )
        return respuesta


class SerieViewSet(
    _EmpresaExplicita,
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Series o IMEI de una empresa y por dónde pasó cada una (``?empresa=ID`` obligatorio).

    Filtros: ``q`` (parte del número o de los otros datos), ``producto``, ``almacen`` y ``estado``
    (``EN_STOCK`` o ``SALIDO``). ``PATCH`` corrige los otros datos de una serie.
    """

    modelo = SerieProducto
    campo_propio = None
    serializer_class = SerieSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    pagination_class = PaginaEstandar
    http_method_names = ["get", "patch", "head", "options"]
    permisos_por_accion = {"list": VER, "partial_update": EDITAR_SERIE}

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(empresa_id=self._empresa_filtrada())
            .select_related("producto", "almacen", "entrada__movimiento", "salida__movimiento")
        )
        params = self.request.query_params
        if (producto := _entero(params, "producto")) is not None:
            queryset = queryset.filter(producto_id=producto)
        if (almacen := _entero(params, "almacen")) is not None:
            queryset = queryset.filter(almacen_id=almacen)
        if estado := params.get("estado"):
            queryset = queryset.filter(estado=estado)
        if q := " ".join((params.get("q") or "").split()):
            queryset = queryset.filter(Q(numero__icontains=q.upper()) | Q(otros_datos__icontains=q))
        return queryset.order_by("-id")

    @extend_schema(
        tags=TAG,
        request=SerieDatosEntrada,
        responses={200: SerieSerializer},
        parameters=[OpenApiParameter("empresa", int, required=True)],
    )
    def partial_update(self, request, *args, **kwargs):
        """Corrige los otros datos de la serie; no toca el stock ni el número."""
        serie = self.get_object()
        datos = SerieDatosEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        nuevo = datos.validated_data["otros_datos"]
        anterior = serie.otros_datos
        if nuevo != anterior:
            serie.otros_datos = nuevo
            serie.save(update_fields=["otros_datos"])
            registrar(
                "serie.datos_corregidos",
                recurso_tipo="serie_producto",
                recurso_id=serie.pk,
                empresa_id=serie.empresa_id,
                resumen=f"Otros datos de la serie {serie.numero} corregidos",
                detalle=diferencia({"otros_datos": anterior}, {"otros_datos": nuevo}),
            )
        return Response(SerieSerializer(serie).data)


class DisponibilidadView(APIView):
    """Existencias de un producto en las empresas de la organización.

    Sirve a la venta mixta: muestra qué empresa tiene stock. Cada persona ve solo lo que sus
    permisos permiten (detalle con costos en sus empresas; solo la cantidad total en las demás,
    si tiene ``INVENTARIO.STOCK_OTRA_EMPRESA.VER``).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=TAG, responses={200: dict})
    def get(self, request, producto_id: int):
        producto = Producto.objects.filter(pk=producto_id).first()
        if producto is None:
            raise Http404
        empresas = consultas.disponibilidad(request.user, producto)
        if not empresas:
            raise PermisoDenegado("No tiene permiso para ver el stock de este producto.")
        return Response(
            {
                "producto": {
                    "id": producto.pk,
                    "codigo": producto.codigo,
                    "nombre": producto.nombre,
                    "controla_stock": producto.controla_stock,
                },
                "empresas": empresas,
            }
        )


# ---------------------------------------------------------------------------
# Periodos
# ---------------------------------------------------------------------------
class PeriodoViewSet(viewsets.GenericViewSet):
    """Cierre mensual del inventario de una empresa."""

    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    requiere_empresa = True
    permisos_por_accion = {"list": VER, "cerrar": CERRAR_PERIODOS, "reabrir": CERRAR_PERIODOS}

    def empresas_de_la_operacion(self, request):
        return [empresa_declarada(request, self)]

    @extend_schema(
        tags=TAG,
        parameters=[OpenApiParameter("empresa", int, required=True)],
        responses={200: dict},
    )
    def list(self, request):
        """Periodos cerrados y el próximo por cerrar (``?empresa=ID``)."""
        empresa = _empresa_activa(_entero(request.query_params, "empresa"))
        hoy = periodos.periodo_de(timezone.localdate())
        cerrados = periodos.cerrados(empresa)
        proximo = (
            MovimientoInventario.objects.filter(empresa=empresa, periodo__lt=hoy)
            .exclude(periodo__in=CierrePeriodo.objects.filter(empresa=empresa).values("periodo"))
            .order_by("periodo")
            .values_list("periodo", flat=True)
            .first()
        )
        return Response({"empresa": empresa.pk, "cerrados": cerrados, "proximo_a_cerrar": proximo})

    @extend_schema(tags=TAG, request=PeriodoEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="cerrar")
    def cerrar(self, request):
        datos = PeriodoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        empresa = _empresa_activa(datos.validated_data["empresa"])
        periodos.cerrar_periodo(empresa, datos.validated_data["periodo"])
        return Response(
            {"empresa": empresa.pk, "cerrados": periodos.cerrados(empresa)},
            status=status.HTTP_200_OK,
        )

    @extend_schema(tags=TAG, request=PeriodoEntrada, responses={200: dict})
    @action(detail=False, methods=["post"], url_path="reabrir")
    def reabrir(self, request):
        datos = PeriodoEntrada(data=request.data)
        datos.is_valid(raise_exception=True)
        empresa = _empresa_activa(datos.validated_data["empresa"])
        periodos.reabrir_periodo(empresa, datos.validated_data["periodo"])
        return Response({"empresa": empresa.pk, "cerrados": periodos.cerrados(empresa)})
