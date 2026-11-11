from decimal import Decimal

from rest_framework import serializers

from apps.compras.models import Compra, CuotaCompra, FormaPago, LineaCompra, Moneda, PagoCompra
from apps.inventario.api.v1.serializers import SerieEntrada

DINERO = {"max_digits": 16, "decimal_places": 2}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class LineaCompraEntrada(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    presentacion = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    precio_unitario = serializers.DecimalField(
        max_digits=16, decimal_places=6, min_value=Decimal("0")
    )
    # Código SUNAT de la afectación (10, 20, 30…). Vacío = la que propone el sistema.
    afectacion = serializers.CharField(max_length=2, required=False, allow_blank=True)
    series = serializers.ListField(child=SerieEntrada(), required=False, max_length=2000)
    ubicacion = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    lote = serializers.CharField(max_length=40, required=False, allow_blank=True)
    # Si la compra recibe una orden: la línea de la orden a la que corresponde (vacío = la del
    # mismo producto y presentación).
    linea_orden = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class PagoCompraEntrada(serializers.Serializer):
    medio_pago = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    fecha = serializers.DateField(required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    aporte_socio = serializers.BooleanField(required=False, default=False)
    # Solo si la caja o cuenta es de otra moneda que la compra.
    tipo_cambio = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )


class CuotasEntrada(serializers.Serializer):
    cantidad = serializers.IntegerField(min_value=1, max_value=60)
    primera_fecha = serializers.DateField()
    periodicidad = serializers.IntegerField(min_value=1)


class FleteEntrada(serializers.Serializer):
    monto = serializers.DecimalField(min_value=Decimal("0"), **DINERO)
    al_costo = serializers.BooleanField(default=True)
    comprobante_tipo = serializers.CharField(max_length=2, required=False, allow_blank=True)
    comprobante_serie = serializers.CharField(max_length=10, required=False, allow_blank=True)
    comprobante_numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    pagos = serializers.ListField(child=PagoCompraEntrada(), required=False, max_length=20)


class CompraEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    proveedor = serializers.IntegerField(min_value=1)
    almacen = serializers.IntegerField(min_value=1)
    tipo_comprobante = serializers.CharField(max_length=2, help_text="Código SUNAT (01, 03…).")
    comprobante_serie = serializers.CharField(max_length=10, required=False, allow_blank=True)
    comprobante_numero = serializers.CharField(max_length=20)
    fecha_emision = serializers.DateField()
    nro_guia = serializers.CharField(max_length=30, required=False, allow_blank=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )
    precios_incluyen_igv = serializers.BooleanField(default=False)
    ajuste_redondeo = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("-0.10"),
        max_value=Decimal("0.10"),
        default=Decimal("0"),
    )
    forma_pago = serializers.ChoiceField(choices=FormaPago.choices)
    # La orden de compra contra la que se recibe esta mercadería (opcional).
    orden = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    lineas = serializers.ListField(child=LineaCompraEntrada(), min_length=1, max_length=200)
    pagos = serializers.ListField(child=PagoCompraEntrada(), required=False, max_length=20)
    cuotas = CuotasEntrada(required=False, allow_null=True)
    flete = FleteEntrada(required=False, allow_null=True)


class AnulacionCompraEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class LineaCompraSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)

    class Meta:
        model = LineaCompra
        fields = [
            "id",
            "orden",
            "producto",
            "producto_codigo",
            "producto_nombre",
            "presentacion",
            "unidad",
            "factor",
            "cantidad",
            "cantidad_base",
            "afectacion_codigo",
            "tasa",
            "precio_unitario",
            "lote",
            "linea_orden",
            "precio_pactado",
            "valor_venta",
            "impuesto",
            "total",
            "costo_soles",
            "flete_asignado",
        ]
        read_only_fields = fields


class PagoCompraSerializer(serializers.ModelSerializer):
    medio_pago_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    moneda_cuenta = serializers.CharField(source="cuenta.moneda", read_only=True)
    cuotas_pagadas = serializers.SerializerMethodField()

    def get_cuotas_pagadas(self, pago) -> list[dict]:
        """Qué cuotas cubrió (solo los pagos hechos después de registrar una compra a crédito)."""
        return [
            {"numero": a.cuota.numero, "monto": f"{a.monto:.2f}"} for a in pago.aplicaciones.all()
        ]

    class Meta:
        model = PagoCompra
        fields = [
            "id",
            "tipo",
            "medio_pago",
            "medio_pago_nombre",
            "cuenta",
            "cuenta_nombre",
            "fecha",
            "monto",
            "referencia",
            "tipo_cambio",
            "monto_cuenta",
            "moneda_cuenta",
            "anulado",
            "anulado_en",
            "motivo_anulacion",
            "cuotas_pagadas",
        ]
        read_only_fields = fields


class CuotaCompraSerializer(serializers.ModelSerializer):
    saldo = serializers.DecimalField(read_only=True, **DINERO)

    class Meta:
        model = CuotaCompra
        fields = ["id", "numero", "fecha_vencimiento", "monto", "pagado", "saldo"]
        read_only_fields = fields


class CompraListaSerializer(serializers.ModelSerializer):
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    almacen_nombre = serializers.CharField(source="almacen.nombre", read_only=True)
    tipo_comprobante_codigo = serializers.CharField(
        source="tipo_comprobante.codigo", read_only=True
    )
    tipo_comprobante_nombre = serializers.CharField(
        source="tipo_comprobante.nombre", read_only=True
    )
    comprobante = serializers.CharField(read_only=True)

    class Meta:
        model = Compra
        fields = [
            "id",
            "numero",
            "empresa",
            "proveedor",
            "proveedor_nombre",
            "almacen",
            "almacen_nombre",
            "tipo_comprobante_codigo",
            "tipo_comprobante_nombre",
            "comprobante",
            "fecha_emision",
            "moneda",
            "total",
            "forma_pago",
            "estado",
        ]
        read_only_fields = fields


class CompraDetalleSerializer(CompraListaSerializer):
    orden_codigo = serializers.SerializerMethodField()
    lineas = LineaCompraSerializer(many=True, read_only=True)
    pagos = PagoCompraSerializer(many=True, read_only=True)
    cuotas = CuotaCompraSerializer(many=True, read_only=True)

    class Meta(CompraListaSerializer.Meta):
        fields = [
            *CompraListaSerializer.Meta.fields,
            "comprobante_serie",
            "comprobante_numero",
            "nro_guia",
            "observacion",
            "tipo_cambio",
            "precios_incluyen_igv",
            "igv_al_costo",
            "op_gravada",
            "igv",
            "op_ivap",
            "ivap",
            "op_exonerada",
            "op_inafecta",
            "ajuste_redondeo",
            "flete",
            "flete_al_costo",
            "flete_comprobante_tipo",
            "flete_comprobante_serie",
            "flete_comprobante_numero",
            "movimiento",
            "orden",
            "orden_codigo",
            "anulado_en",
            "motivo_anulacion",
            "lineas",
            "pagos",
            "cuotas",
        ]
        read_only_fields = fields

    def get_orden_codigo(self, compra) -> str | None:
        return compra.orden.codigo if compra.orden_id else None


class PagoParteEntrada(serializers.Serializer):
    """Un medio de pago de la operación: con qué se paga, de qué caja o cuenta y cuánto."""

    medio_pago = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    aporte_socio = serializers.BooleanField(required=False, default=False)
    tipo_cambio = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )


class PagarEntrada(serializers.Serializer):
    """Pago de una compra a crédito con uno o varios medios; sin ``cuota``, a las más antiguas."""

    pagos = serializers.ListField(child=PagoParteEntrada(), min_length=1, max_length=10)
    fecha = serializers.DateField(required=False, allow_null=True)
    cuotas = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=60
    )


class PorPagarSerializer(serializers.ModelSerializer):
    """Una compra a crédito con deuda: cuánto falta, cuánto está vencido y para cuándo es."""

    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    tipo_comprobante_nombre = serializers.CharField(
        source="tipo_comprobante.nombre", read_only=True
    )
    comprobante = serializers.CharField(read_only=True)
    pagado = serializers.DecimalField(read_only=True, **DINERO)
    saldo = serializers.DecimalField(read_only=True, **DINERO)
    saldo_vencido = serializers.DecimalField(read_only=True, default=Decimal("0"), **DINERO)
    proximo_vencimiento = serializers.DateField(read_only=True)
    dias_atraso = serializers.SerializerMethodField()

    class Meta:
        model = Compra
        fields = [
            "id",
            "numero",
            "empresa",
            "proveedor",
            "proveedor_nombre",
            "tipo_comprobante_nombre",
            "comprobante",
            "fecha_emision",
            "moneda",
            "total",
            "pagado",
            "saldo",
            "saldo_vencido",
            "proximo_vencimiento",
            "dias_atraso",
        ]
        read_only_fields = fields

    def get_dias_atraso(self, compra) -> int:
        """Días desde el vencimiento de la cuota impaga más antigua (0 si nada está vencido)."""
        if not compra.saldo_vencido or compra.proximo_vencimiento is None:
            return 0
        return max((self.context["hoy"] - compra.proximo_vencimiento).days, 0)
