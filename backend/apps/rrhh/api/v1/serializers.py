from decimal import Decimal

from rest_framework import serializers

from apps.mantenimiento.models import EstadoRegistro
from apps.rrhh.models import (
    CategoriaAsistencia,
    CodigoParametro,
    ConceptoPlanilla,
    Feriado,
    NombreAfp,
    ParametroLaboral,
    RegimenLaboral,
    TasaAfp,
    TipoAsistencia,
    TipoConcepto,
    TramoRenta5,
)

ESTADO = serializers.ChoiceField(choices=EstadoRegistro.choices, required=False)


def _porcentaje(**extra):
    return serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("100"), **extra
    )


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class RegimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegimenLaboral
        fields = (
            "id",
            "codigo",
            "nombre",
            "tasa_essalud",
            "dias_vacaciones",
            "factor_gratificacion",
            "factor_cts",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class ParametroSerializer(serializers.ModelSerializer):
    codigo_nombre = serializers.CharField(source="get_codigo_display", read_only=True)
    unidad = serializers.CharField(read_only=True)

    class Meta:
        model = ParametroLaboral
        fields = (
            "id",
            "codigo",
            "codigo_nombre",
            "unidad",
            "valor",
            "vigente_desde",
            "nota",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class TasaAfpSerializer(serializers.ModelSerializer):
    afp_nombre = serializers.CharField(source="get_afp_display", read_only=True)

    class Meta:
        model = TasaAfp
        fields = (
            "id",
            "afp",
            "afp_nombre",
            "vigente_desde",
            "aporte_obligatorio",
            "prima_seguro",
            "comision_flujo",
            "comision_mixta",
            "remuneracion_maxima_asegurable",
            "nota",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class TipoAsistenciaSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source="get_categoria_display", read_only=True)

    class Meta:
        model = TipoAsistencia
        fields = (
            "id",
            "codigo",
            "nombre",
            "categoria",
            "categoria_nombre",
            "se_paga",
            "cuenta_dia_laborado",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class FeriadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feriado
        fields = ("id", "fecha", "nombre", "estado", "creado_en")
        read_only_fields = fields


class ConceptoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = ConceptoPlanilla
        fields = (
            "id",
            "codigo",
            "nombre",
            "tipo",
            "tipo_nombre",
            "afecto_pension",
            "afecto_essalud",
            "afecto_renta5",
            "codigo_plame",
            "orden",
            "es_del_sistema",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class RegimenEntrada(serializers.Serializer):
    codigo = serializers.CharField(max_length=20)
    nombre = serializers.CharField(max_length=80)
    tasa_essalud = _porcentaje()
    dias_vacaciones = serializers.IntegerField(min_value=1, max_value=60)
    factor_gratificacion = serializers.DecimalField(
        max_digits=4, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("3")
    )
    factor_cts = serializers.DecimalField(
        max_digits=4, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("3")
    )
    estado = ESTADO


class ParametroEntrada(serializers.Serializer):
    codigo = serializers.ChoiceField(choices=CodigoParametro.choices)
    valor = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0"))
    vigente_desde = serializers.DateField()
    nota = serializers.CharField(max_length=200, required=False, allow_blank=True)
    estado = ESTADO


class TasaAfpEntrada(serializers.Serializer):
    afp = serializers.ChoiceField(choices=NombreAfp.choices)
    vigente_desde = serializers.DateField()
    aporte_obligatorio = _porcentaje()
    prima_seguro = _porcentaje()
    comision_flujo = _porcentaje()
    comision_mixta = _porcentaje()
    remuneracion_maxima_asegurable = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0")
    )
    nota = serializers.CharField(max_length=200, required=False, allow_blank=True)
    estado = ESTADO


class TipoAsistenciaEntrada(serializers.Serializer):
    codigo = serializers.CharField(max_length=6)
    nombre = serializers.CharField(max_length=60)
    categoria = serializers.ChoiceField(choices=CategoriaAsistencia.choices)
    se_paga = serializers.BooleanField(required=False)
    cuenta_dia_laborado = serializers.BooleanField(required=False)
    estado = ESTADO


class FeriadoEntrada(serializers.Serializer):
    fecha = serializers.DateField()
    nombre = serializers.CharField(max_length=80)
    estado = ESTADO


class ConceptoEntrada(serializers.Serializer):
    codigo = serializers.CharField(max_length=30)
    nombre = serializers.CharField(max_length=100)
    tipo = serializers.ChoiceField(choices=TipoConcepto.choices)
    afecto_pension = serializers.BooleanField(required=False)
    afecto_essalud = serializers.BooleanField(required=False)
    afecto_renta5 = serializers.BooleanField(required=False)
    codigo_plame = serializers.CharField(max_length=10, required=False, allow_blank=True)
    orden = serializers.IntegerField(min_value=0, max_value=999, required=False)
    estado = ESTADO


class TramoRenta5Serializer(serializers.ModelSerializer):
    class Meta:
        model = TramoRenta5
        fields = ("id", "vigente_desde", "orden", "hasta_uit", "tasa", "estado", "creado_en")
        read_only_fields = fields


class TramoRenta5Entrada(serializers.Serializer):
    vigente_desde = serializers.DateField()
    orden = serializers.IntegerField(min_value=1, max_value=20)
    hasta_uit = serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True
    )
    tasa = _porcentaje()
    estado = ESTADO
