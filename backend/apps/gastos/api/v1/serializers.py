from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from apps.gastos.models import AdjuntoGasto, FormaPago, Gasto, GastoReparto, Moneda, PagoGasto

DINERO = {"max_digits": 16, "decimal_places": 2}


class PagoEntradaSerializer(serializers.Serializer):
    medio_pago = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    fecha = serializers.DateField(required=False, allow_null=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    aporte_socio = serializers.BooleanField(required=False, default=False)
    tipo_cambio = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )


class RepartoEntradaSerializer(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)
    porcentaje = serializers.DecimalField(max_digits=5, decimal_places=2)


class GastoEntrada(serializers.Serializer):
    """Lo que se envía para registrar un gasto, con o sin comprobante."""

    empresa = serializers.IntegerField(min_value=1)
    categoria = serializers.IntegerField(min_value=1)
    fecha = serializers.DateField()
    descripcion = serializers.CharField(max_length=250)
    con_comprobante = serializers.BooleanField()
    tipo_comprobante = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    comprobante_serie = serializers.CharField(max_length=10, required=False, allow_blank=True)
    comprobante_numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    proveedor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    base_gravada = serializers.DecimalField(required=False, **DINERO)
    igv = serializers.DecimalField(required=False, **DINERO)
    no_gravado = serializers.DecimalField(required=False, **DINERO)
    gastado_por = serializers.CharField(max_length=120, required=False, allow_blank=True)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, required=False)
    tipo_cambio = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )
    forma_pago = serializers.ChoiceField(choices=FormaPago.choices, required=False)
    fecha_vencimiento = serializers.DateField(required=False, allow_null=True)
    pagos = PagoEntradaSerializer(many=True, required=False, max_length=20)
    reparto = RepartoEntradaSerializer(many=True, required=False, max_length=10)
    recurrente = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class PagarEntrada(serializers.Serializer):
    pagos = PagoEntradaSerializer(many=True, allow_empty=False, max_length=20)


class AnulacionEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


class AdjuntoGastoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdjuntoGasto
        fields = [
            "id",
            "gasto",
            "tipo_contenido",
            "nombre_original",
            "tamano",
            "subido_por_nombre",
            "creado_en",
        ]
        read_only_fields = fields


class AdjuntoGastoEntrada(serializers.Serializer):
    gasto = serializers.IntegerField(min_value=1)
    archivo = serializers.FileField(max_length=200, allow_empty_file=False)


def estado_de_pago(gasto: Gasto, pagado: Decimal) -> str:
    """ANULADO, PAGADO, VENCIDO (por pagar y pasado de fecha), PARCIAL o PENDIENTE."""
    if gasto.estado != Gasto.Estado.EMITIDO:
        return "ANULADO"
    if pagado >= gasto.total:
        return "PAGADO"
    vencido = gasto.fecha_vencimiento and gasto.fecha_vencimiento < timezone.localdate()
    if vencido:
        return "VENCIDO"
    return "PARCIAL" if pagado > 0 else "PENDIENTE"


class GastoSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.SerializerMethodField()
    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    tipo_comprobante_nombre = serializers.CharField(
        source="tipo_comprobante.nombre", default="", read_only=True
    )
    recurrente_nombre = serializers.CharField(
        source="recurrente.nombre", default="", read_only=True
    )
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", default="", read_only=True)
    proveedor_documento = serializers.CharField(
        source="proveedor.numero_documento", default="", read_only=True
    )
    sucursal_nombre = serializers.CharField(source="sucursal.nombre", default="", read_only=True)
    comprobante = serializers.CharField(read_only=True)
    sin_sustento = serializers.BooleanField(read_only=True)
    pagado = serializers.SerializerMethodField()
    saldo = serializers.SerializerMethodField()
    estado_pago = serializers.SerializerMethodField()
    repartido = serializers.SerializerMethodField()
    adjuntos_cantidad = serializers.SerializerMethodField()

    class Meta:
        model = Gasto
        fields = [
            "id",
            "numero",
            "empresa",
            "empresa_nombre",
            "categoria",
            "categoria_nombre",
            "fecha",
            "descripcion",
            "observacion",
            "sucursal",
            "sucursal_nombre",
            "con_comprobante",
            "sin_sustento",
            "tipo_comprobante",
            "tipo_comprobante_nombre",
            "comprobante_serie",
            "comprobante_numero",
            "comprobante",
            "proveedor",
            "proveedor_nombre",
            "proveedor_documento",
            "gastado_por",
            "moneda",
            "tipo_cambio",
            "base_gravada",
            "igv",
            "no_gravado",
            "total",
            "forma_pago",
            "fecha_vencimiento",
            "pagado",
            "saldo",
            "estado",
            "estado_pago",
            "motivo_anulacion",
            "repartido",
            "adjuntos_cantidad",
            "recurrente",
            "recurrente_nombre",
            "creado_en",
        ]
        read_only_fields = fields

    def _pagado(self, gasto) -> Decimal:
        valor = getattr(gasto, "pagado_calc", None)
        return gasto.pagado() if valor is None else valor

    def get_empresa_nombre(self, gasto) -> str:
        return gasto.empresa.nombre_comercial or gasto.empresa.razon_social

    def get_pagado(self, gasto) -> str:
        return f"{self._pagado(gasto):.2f}"

    def get_saldo(self, gasto) -> str:
        if gasto.estado != Gasto.Estado.EMITIDO:
            return "0.00"
        return f"{gasto.total - self._pagado(gasto):.2f}"

    def get_estado_pago(self, gasto) -> str:
        return estado_de_pago(gasto, self._pagado(gasto))

    def get_repartido(self, gasto) -> bool:
        return len(gasto.repartos.all()) > 0

    def get_adjuntos_cantidad(self, gasto) -> int:
        return len(gasto.adjuntos.all())


class PagoGastoSerializer(serializers.ModelSerializer):
    medio_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    moneda_cuenta = serializers.CharField(source="cuenta.moneda", read_only=True)

    class Meta:
        model = PagoGasto
        fields = [
            "id",
            "medio_pago",
            "medio_nombre",
            "cuenta",
            "cuenta_nombre",
            "moneda_cuenta",
            "fecha",
            "monto",
            "referencia",
            "tipo_cambio",
            "monto_cuenta",
            "anulado",
            "motivo_anulacion",
        ]
        read_only_fields = fields


class RepartoSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.SerializerMethodField()

    class Meta:
        model = GastoReparto
        fields = ["id", "empresa", "empresa_nombre", "porcentaje", "monto"]
        read_only_fields = fields

    def get_empresa_nombre(self, reparto) -> str:
        return reparto.empresa.nombre_comercial or reparto.empresa.razon_social


class GastoDetalleSerializer(GastoSerializer):
    pagos = serializers.SerializerMethodField()
    repartos = RepartoSerializer(many=True, read_only=True)
    adjuntos = AdjuntoGastoSerializer(many=True, read_only=True)

    class Meta(GastoSerializer.Meta):
        fields = [*GastoSerializer.Meta.fields, "pagos", "repartos", "adjuntos"]
        read_only_fields = fields

    def get_pagos(self, gasto) -> list:
        return PagoGastoSerializer(
            gasto.pagos.select_related("medio_pago", "cuenta"), many=True
        ).data
