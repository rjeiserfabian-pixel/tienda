from decimal import Decimal

from rest_framework import serializers

from apps.inventario.models import (
    LineaMovimiento,
    Moneda,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.mantenimiento.models import UbicacionProducto

# Orígenes que una persona puede registrar a mano. La venta la genera el módulo de Ventas, la
# devolución a un proveedor sale de una compra (módulo de Compras) y el extorno lo crea el
# sistema al anular.
ORIGENES_MANUALES = [
    OrigenMovimiento.COMPRA,
    OrigenMovimiento.DEVOLUCION_CLIENTE,
    OrigenMovimiento.SALDO_INICIAL,
    OrigenMovimiento.AJUSTE,
    OrigenMovimiento.MERMA,
]


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class SerieEntrada(serializers.Field):
    """Una serie: el texto del número, o ``{"numero": ..., "otros_datos": ...}``."""

    default_error_messages = {
        "invalid": "Cada serie es un texto o un objeto con «numero» y «otros_datos».",
        "vacia": "Hay una serie vacía.",
        "larga": "Una serie admite hasta 40 caracteres.",
        "datos_largos": "Los otros datos de una serie admiten hasta 120 caracteres.",
    }

    def to_internal_value(self, dato):
        if isinstance(dato, str):
            numero, otros = dato, ""
        elif isinstance(dato, dict):
            numero, otros = dato.get("numero"), dato.get("otros_datos") or ""
        else:
            self.fail("invalid")
        if not isinstance(numero, str) or not isinstance(otros, str):
            self.fail("invalid")
        numero, otros = numero.strip(), " ".join(otros.split())
        if not numero:
            self.fail("vacia")
        if len(numero) > 40:
            self.fail("larga")
        if len(otros) > 120:
            self.fail("datos_largos")
        return {"numero": numero, "otros_datos": otros}

    def to_representation(self, valor):
        return valor


class LineaEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    precio_unitario = serializers.DecimalField(
        max_digits=16, decimal_places=6, min_value=Decimal("0"), required=False, allow_null=True
    )
    # Productos con serie o IMEI: una por unidad (el servidor exige que coincidan con la cantidad).
    series = serializers.ListField(child=SerieEntrada(), required=False, max_length=2000)
    # Solo en entradas: deja al producto en esa ubicación del almacén (vacío = no la toca).
    ubicacion = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class LineaTraspasoEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    # En un traspaso las series viajan con sus otros datos: aquí solo se dice cuáles.
    series = serializers.ListField(child=SerieEntrada(), required=False, max_length=2000)


class TraspasoEntrada(serializers.Serializer):
    """Mueve mercadería entre dos almacenes de la misma empresa (sin precios: se valoriza solo)."""

    empresa = serializers.IntegerField(min_value=1)
    almacen_origen = serializers.IntegerField(min_value=1)
    almacen_destino = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    observacion = serializers.CharField(max_length=200, required=False, allow_blank=True)
    lineas = serializers.ListField(child=LineaTraspasoEntrada(), min_length=1, max_length=200)


class MovimientoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    almacen = serializers.IntegerField(min_value=1)
    tipo = serializers.ChoiceField(choices=TipoMovimiento.choices)
    origen = serializers.ChoiceField(choices=[(o.value, o.label) for o in ORIGENES_MANUALES])
    fecha = serializers.DateField()
    tipo_operacion = serializers.CharField(max_length=2, required=False, allow_blank=True)
    proveedor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cliente = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    comprobante_tipo = serializers.CharField(max_length=2, required=False, allow_blank=True)
    comprobante_serie = serializers.CharField(max_length=10, required=False, allow_blank=True)
    comprobante_numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    comprobante_fecha = serializers.DateField(required=False, allow_null=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )
    precios_incluyen_igv = serializers.BooleanField(default=False)
    igv_porcentaje = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    lineas = serializers.ListField(child=LineaEntrada(), min_length=1, max_length=200)


class AnulacionEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


class PeriodoEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    periodo = serializers.RegexField(r"^\d{6}$", help_text="AAAAMM")


class UbicacionAsignarEntrada(serializers.Serializer):
    """``ubicacion`` en ``null`` quita la ubicación que el producto tenía en ese almacén."""

    empresa = serializers.IntegerField(min_value=1)
    almacen = serializers.IntegerField(min_value=1)
    producto = serializers.IntegerField(min_value=1)
    ubicacion = serializers.IntegerField(min_value=1, allow_null=True)


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class UbicacionProductoSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    ubicacion_codigo = serializers.CharField(source="ubicacion.codigo", read_only=True)
    ubicacion_nombre = serializers.CharField(source="ubicacion.nombre", read_only=True)

    class Meta:
        model = UbicacionProducto
        fields = (
            "id",
            "empresa",
            "almacen",
            "almacen_nombre",
            "producto",
            "ubicacion",
            "ubicacion_codigo",
            "ubicacion_nombre",
        )
        read_only_fields = fields


class LineaMovimientoSerializer(serializers.ModelSerializer):
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    unidad = serializers.CharField(source="producto.unidad.abreviatura", read_only=True)
    series = serializers.SerializerMethodField()
    series_detalle = serializers.SerializerMethodField()

    class Meta:
        model = LineaMovimiento
        fields = (
            "id",
            "orden",
            "producto",
            "producto_codigo",
            "producto_nombre",
            "unidad",
            "cantidad",
            "precio_unitario",
            "costo_unitario",
            "costo_total",
            "saldo_cantidad",
            "saldo_costo_total",
            "saldo_costo_unitario",
            "series",
            "series_detalle",
        )
        read_only_fields = fields

    def _series_de(self, linea):
        origen = (
            linea.series_entrada if linea.tipo == TipoMovimiento.ENTRADA else linea.series_salida
        )
        return sorted(origen.all(), key=lambda s: s.numero)

    def get_series(self, linea) -> list[str]:
        """Las series que entraron (o salieron) con esta línea; vacío si no lleva serie."""
        return [s.numero for s in self._series_de(linea)]

    def get_series_detalle(self, linea) -> list[dict]:
        """Lo mismo, con los otros datos de cada serie."""
        return [{"numero": s.numero, "otros_datos": s.otros_datos} for s in self._series_de(linea)]


class MovimientoListaSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    tercero = serializers.SerializerMethodField()
    cantidad_lineas = serializers.SerializerMethodField()

    class Meta:
        model = MovimientoInventario
        fields = (
            "id",
            "empresa",
            "almacen",
            "almacen_nombre",
            "numero",
            "tipo",
            "origen",
            "tipo_operacion",
            "fecha",
            "periodo",
            "comprobante_tipo",
            "comprobante_serie",
            "comprobante_numero",
            "comprobante_fecha",
            "proveedor",
            "cliente",
            "tercero",
            "moneda",
            "tipo_cambio",
            "precios_incluyen_igv",
            "igv_porcentaje",
            "subtotal",
            "igv",
            "total",
            "observacion",
            "estado",
            "anulado_en",
            "motivo_anulacion",
            "extorna",
            "traspaso_id",
            "cantidad_lineas",
            "creado_en",
        )
        read_only_fields = fields

    def get_tercero(self, movimiento) -> str:
        tercero = movimiento.proveedor or movimiento.cliente
        return tercero.nombre if tercero else ""

    def get_cantidad_lineas(self, movimiento) -> int:
        anotada = getattr(movimiento, "cantidad_lineas", None)
        return anotada if anotada is not None else movimiento.lineas.count()


class MovimientoDetalleSerializer(MovimientoListaSerializer):
    lineas = LineaMovimientoSerializer(many=True, read_only=True)

    class Meta(MovimientoListaSerializer.Meta):
        fields = (*MovimientoListaSerializer.Meta.fields, "lineas")
        read_only_fields = fields


class StockSerializer(serializers.ModelSerializer):
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    unidad = serializers.CharField(source="producto.unidad.abreviatura", read_only=True)
    stock_minimo = serializers.DecimalField(
        source="producto.stock_minimo", max_digits=12, decimal_places=3, read_only=True
    )
    bajo_minimo = serializers.SerializerMethodField()
    # Los anota StockViewSet (una subconsulta por fila, sin consultas extra).
    ubicacion_codigo = serializers.CharField(default=None, read_only=True)
    ubicacion_nombre = serializers.CharField(default=None, read_only=True)

    class Meta:
        model = SaldoStock
        fields = (
            "id",
            "empresa",
            "almacen",
            "almacen_nombre",
            "producto",
            "producto_codigo",
            "producto_nombre",
            "unidad",
            "ubicacion_codigo",
            "ubicacion_nombre",
            "cantidad",
            "costo_unitario",
            "costo_total",
            "stock_minimo",
            "bajo_minimo",
        )
        read_only_fields = fields

    def get_bajo_minimo(self, saldo) -> bool:
        minimo = saldo.producto.stock_minimo
        return minimo > 0 and saldo.cantidad <= minimo


class KardexSerializer(serializers.ModelSerializer):
    """Una línea del Kardex con los datos de su movimiento."""

    movimiento_numero = serializers.IntegerField(source="movimiento.numero", read_only=True)
    origen = serializers.CharField(source="movimiento.origen", read_only=True)
    tipo_operacion = serializers.CharField(source="movimiento.tipo_operacion", read_only=True)
    comprobante_tipo = serializers.CharField(source="movimiento.comprobante_tipo", read_only=True)
    comprobante_serie = serializers.CharField(source="movimiento.comprobante_serie", read_only=True)
    comprobante_numero = serializers.CharField(
        source="movimiento.comprobante_numero", read_only=True
    )
    estado_movimiento = serializers.CharField(source="movimiento.estado", read_only=True)

    class Meta:
        model = LineaMovimiento
        fields = (
            "id",
            "fecha",
            "movimiento",
            "movimiento_numero",
            "tipo",
            "origen",
            "tipo_operacion",
            "comprobante_tipo",
            "comprobante_serie",
            "comprobante_numero",
            "estado_movimiento",
            "cantidad",
            "costo_unitario",
            "costo_total",
            "saldo_cantidad",
            "saldo_costo_unitario",
            "saldo_costo_total",
        )
        read_only_fields = fields


class ParametrosReporte(serializers.Serializer):
    """Parámetros (en la URL) de los reportes exportables. Según el reporte se usan unos u otros."""

    empresa = serializers.IntegerField(min_value=1)
    formato = serializers.ChoiceField(choices=["xlsx", "pdf"], default="xlsx")
    almacen = serializers.IntegerField(min_value=1, required=False)
    producto = serializers.IntegerField(min_value=1, required=False)
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)
    fecha = serializers.DateField(required=False)
    categoria = serializers.IntegerField(min_value=1, required=False)
    marca = serializers.IntegerField(min_value=1, required=False)
    solo_antiguo = serializers.BooleanField(required=False, default=False)


class SerieDatosEntrada(serializers.Serializer):
    """Corrección de los otros datos de una serie (el número de serie no se edita)."""

    otros_datos = serializers.CharField(max_length=120, allow_blank=True)

    def validate_otros_datos(self, valor: str) -> str:
        return " ".join(valor.split())


class SerieSerializer(serializers.ModelSerializer):
    """Una serie o IMEI con dónde está y por qué movimientos pasó."""

    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    entrada_movimiento = serializers.IntegerField(source="entrada.movimiento_id", read_only=True)
    entrada_numero = serializers.IntegerField(source="entrada.movimiento.numero", read_only=True)
    entrada_fecha = serializers.DateField(source="entrada.fecha", read_only=True)
    salida_movimiento = serializers.IntegerField(
        source="salida.movimiento_id", default=None, read_only=True
    )
    salida_numero = serializers.IntegerField(
        source="salida.movimiento.numero", default=None, read_only=True
    )
    salida_fecha = serializers.DateField(source="salida.fecha", default=None, read_only=True)

    class Meta:
        model = SerieProducto
        fields = (
            "id",
            "numero",
            "otros_datos",
            "estado",
            "producto",
            "producto_codigo",
            "producto_nombre",
            "almacen",
            "almacen_nombre",
            "entrada_movimiento",
            "entrada_numero",
            "entrada_fecha",
            "salida_movimiento",
            "salida_numero",
            "salida_fecha",
        )
        read_only_fields = fields
