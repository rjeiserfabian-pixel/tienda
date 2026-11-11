from decimal import Decimal

from rest_framework import serializers

from apps.caja import bancarizacion
from apps.caja.models import MovimientoCaja, TipoMovimiento, Transferencia

DINERO = {"max_digits": 16, "decimal_places": 2}


class MovimientoEntrada(serializers.Serializer):
    """Un ingreso o egreso hecho a mano. Los que generan otros módulos no pasan por aquí."""

    empresa = serializers.IntegerField(min_value=1)
    cuenta = serializers.IntegerField(min_value=1)
    tipo = serializers.ChoiceField(choices=TipoMovimiento.choices)
    concepto = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    fecha = serializers.DateField(required=False, allow_null=True)
    glosa = serializers.CharField(max_length=250, required=False, allow_blank=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    medio_pago = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class AnulacionEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


_MEDIO_SEGUN_CUENTA = {"CAJA": "Efectivo", "BANCO": "Banco", "BILLETERA": "Billetera digital"}


def medio_de(movimiento) -> str:
    """El método con que se pagó; si no se indicó, el que corresponde al tipo de cuenta."""
    if movimiento.medio_pago_id:
        return movimiento.medio_pago.nombre
    return _MEDIO_SEGUN_CUENTA.get(movimiento.cuenta.tipo, "")


class MovimientoSerializer(serializers.ModelSerializer):
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    moneda = serializers.CharField(read_only=True)
    concepto_nombre = serializers.CharField(source="concepto.nombre", read_only=True)
    cuenta_tipo = serializers.CharField(source="cuenta.tipo", read_only=True)
    cuenta_tipo_nombre = serializers.CharField(source="cuenta.get_tipo_display", read_only=True)
    medio_nombre = serializers.SerializerMethodField()
    puede_anularse = serializers.SerializerMethodField()
    sin_bancarizar = serializers.SerializerMethodField()
    adjuntos_cantidad = serializers.SerializerMethodField()
    saldo_despues = serializers.SerializerMethodField()

    class Meta:
        model = MovimientoCaja
        fields = [
            "id",
            "numero",
            "empresa",
            "cuenta",
            "cuenta_nombre",
            "moneda",
            "fecha",
            "tipo",
            "monto",
            "concepto",
            "concepto_nombre",
            "glosa",
            "referencia",
            "origen_tipo",
            "origen_id",
            "sesion",
            "estado",
            "anulado_en",
            "motivo_anulacion",
            "cuenta_tipo",
            "cuenta_tipo_nombre",
            "medio_pago",
            "medio_nombre",
            "puede_anularse",
            "sin_bancarizar",
            "adjuntos_cantidad",
            "saldo_despues",
            "creado_en",
        ]
        read_only_fields = fields

    def get_medio_nombre(self, movimiento) -> str:
        return medio_de(movimiento)

    def get_puede_anularse(self, movimiento) -> bool:
        return (
            movimiento.estado == MovimientoCaja.Estado.EMITIDO
            and movimiento.es_manual
            and not (movimiento.sesion_id and movimiento.sesion.estado == "CERRADA")
        )

    def get_sin_bancarizar(self, movimiento) -> bool:
        return (
            movimiento.estado == MovimientoCaja.Estado.EMITIDO
            and bancarizacion.es_sin_bancarizar(movimiento)
        )

    def get_adjuntos_cantidad(self, movimiento) -> int:
        return len(movimiento.adjuntos.all())

    def get_saldo_despues(self, movimiento) -> str | None:
        """Saldo de la cuenta justo después de este movimiento (solo si se pidió una cuenta)."""
        neto = getattr(movimiento, "neto_acumulado", None)
        if movimiento.estado != MovimientoCaja.Estado.EMITIDO or not hasattr(
            movimiento, "neto_acumulado"
        ):
            return None
        return f"{movimiento.cuenta.saldo_inicial + (neto or Decimal(0)):.2f}"


class TransferenciaEntrada(serializers.Serializer):
    """Mueve dinero de una cuenta a otra. ``tipo_cambio`` solo si las monedas son distintas."""

    empresa = serializers.IntegerField(min_value=1)
    cuenta_origen = serializers.IntegerField(min_value=1)
    cuenta_destino = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    fecha = serializers.DateField(required=False, allow_null=True)
    tipo_cambio = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
        allow_null=True,
    )
    monto_destino = serializers.DecimalField(
        min_value=Decimal("0.01"), required=False, allow_null=True, **DINERO
    )
    comision = serializers.DecimalField(min_value=Decimal("0"), required=False, **DINERO)
    itf = serializers.DecimalField(min_value=Decimal("0"), required=False, **DINERO)
    glosa = serializers.CharField(max_length=250, required=False, allow_blank=True)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)


class TransferenciaSerializer(serializers.ModelSerializer):
    clase_nombre = serializers.CharField(source="get_clase_display", read_only=True)
    origen_nombre = serializers.CharField(source="cuenta_origen.nombre", read_only=True)
    origen_moneda = serializers.CharField(source="cuenta_origen.moneda", read_only=True)
    destino_nombre = serializers.CharField(source="cuenta_destino.nombre", read_only=True)
    destino_moneda = serializers.CharField(source="cuenta_destino.moneda", read_only=True)
    empresa_nombre = serializers.SerializerMethodField()
    empresa_destino_nombre = serializers.SerializerMethodField()
    entre_empresas = serializers.SerializerMethodField()

    class Meta:
        model = Transferencia
        fields = [
            "id",
            "numero",
            "empresa",
            "empresa_nombre",
            "empresa_destino",
            "empresa_destino_nombre",
            "entre_empresas",
            "clase",
            "clase_nombre",
            "fecha",
            "cuenta_origen",
            "origen_nombre",
            "origen_moneda",
            "cuenta_destino",
            "destino_nombre",
            "destino_moneda",
            "monto_origen",
            "monto_destino",
            "tipo_cambio",
            "comision",
            "itf",
            "glosa",
            "referencia",
            "estado",
            "anulado_en",
            "motivo_anulacion",
            "creado_en",
        ]
        read_only_fields = fields

    @staticmethod
    def _nombre(empresa) -> str:
        return empresa.nombre_comercial or empresa.razon_social

    def get_empresa_nombre(self, t) -> str:
        return self._nombre(t.empresa)

    def get_empresa_destino_nombre(self, t) -> str:
        return self._nombre(t.empresa_destino)

    def get_entre_empresas(self, t) -> bool:
        return t.empresa_id != t.empresa_destino_id
