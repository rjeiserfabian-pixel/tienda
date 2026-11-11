from rest_framework import serializers

from apps.facturacion.models import EnvioSunat, OrigenDocumento
from apps.organizacion.models import ConfiguracionEmpresa


class ConfiguracionEntrada(serializers.Serializer):
    """Los secretos solo se escriben: vacío o ausente = no cambia el que ya está guardado."""

    empresa = serializers.IntegerField(min_value=1)
    activo = serializers.BooleanField(required=False)
    modo = serializers.ChoiceField(choices=ConfiguracionEmpresa.ModoSunat.choices, required=False)
    usuario_sol = serializers.CharField(max_length=40, required=False, allow_blank=True)
    clave_sol = serializers.CharField(
        max_length=80, required=False, allow_blank=True, trim_whitespace=False
    )
    gre_client_id = serializers.CharField(max_length=80, required=False, allow_blank=True)
    gre_client_secret = serializers.CharField(
        max_length=120, required=False, allow_blank=True, trim_whitespace=False
    )
    ubigeo_fiscal = serializers.RegexField(r"^\d{6}$", required=False, allow_blank=True)
    urbanizacion = serializers.CharField(max_length=100, required=False, allow_blank=True)
    codigo_sunat_defecto = serializers.RegexField(r"^\d{8}$", required=False, allow_blank=True)


class EmpresaEntrada(serializers.Serializer):
    empresa = serializers.IntegerField(min_value=1)


class DocumentoEntrada(serializers.Serializer):
    origen = serializers.ChoiceField(choices=OrigenDocumento.choices)
    id = serializers.IntegerField(min_value=1)


class EnvioSerializer(serializers.ModelSerializer):
    estado_nombre = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = EnvioSunat
        fields = (
            "id",
            "origen",
            "origen_id",
            "tipo_documento",
            "serie",
            "numero",
            "estado",
            "estado_nombre",
            "intentos",
            "modo",
            "codigo_respuesta",
            "mensaje",
            "ticket",
            "codigo_hash",
            "enviado_en",
        )
        read_only_fields = fields
