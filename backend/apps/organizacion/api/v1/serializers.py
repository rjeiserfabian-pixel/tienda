from rest_framework import serializers

from apps.mantenimiento.api.v1.campos import CampoUbigeo
from apps.organizacion.models import Empresa, Estado, Organizacion, Sucursal


class OrganizacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organizacion
        fields = ("id", "nombre", "estado", "mfa_obligatorio", "calculo_precios")
        read_only_fields = ("id", "estado")


class EmpresaSerializer(serializers.ModelSerializer):
    tiene_logo = serializers.SerializerMethodField()

    class Meta:
        model = Empresa
        fields = (
            "id",
            "ruc",
            "razon_social",
            "nombre_comercial",
            "estado",
            "direccion_fiscal",
            "telefono",
            "correo",
            "sitio_web",
            "tienda_web",
            "es_principal",
            "tiene_logo",
            "actualizado_en",
            "creado_en",
        )
        read_only_fields = fields

    def get_tiene_logo(self, empresa) -> bool:
        return bool(empresa.logo)


class EmpresaCrearSerializer(serializers.Serializer):
    ruc = serializers.CharField(max_length=11)
    razon_social = serializers.CharField(max_length=250)
    nombre_comercial = serializers.CharField(
        max_length=250, required=False, allow_blank=True, default=""
    )
    codigo_sucursal = serializers.CharField(max_length=10, required=False, default="001")
    nombre_sucursal = serializers.CharField(max_length=150, required=False, default="Principal")


class EmpresaActualizarSerializer(serializers.Serializer):
    """``ruc`` es opcional: solo lo cambia quien gestiona la organización (lo exige la vista)."""

    ruc = serializers.CharField(max_length=11, required=False)
    razon_social = serializers.CharField(max_length=250)
    nombre_comercial = serializers.CharField(max_length=250, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=Estado.choices)
    direccion_fiscal = serializers.CharField(max_length=250, required=False, allow_blank=True)
    telefono = serializers.CharField(max_length=30, required=False, allow_blank=True)
    correo = serializers.CharField(max_length=150, required=False, allow_blank=True)
    sitio_web = serializers.CharField(max_length=200, required=False, allow_blank=True)
    tienda_web = serializers.CharField(max_length=200, required=False, allow_blank=True)
    es_principal = serializers.BooleanField(required=False)


class SucursalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sucursal
        fields = (
            "id",
            "empresa",
            "nombre",
            "codigo",
            "local_fisico",
            "direccion",
            "ubigeo",
            "estado",
            "creado_en",
        )
        read_only_fields = fields


class SucursalCrearSerializer(serializers.Serializer):
    empresa = serializers.IntegerField()
    nombre = serializers.CharField(max_length=150)
    codigo = serializers.CharField(max_length=10)
    local_fisico = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default=""
    )
    direccion = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    ubigeo = CampoUbigeo(default="")


class SucursalActualizarSerializer(serializers.Serializer):
    """Empresa y código no cambian: otros datos (series, accesos) dependen de ellos."""

    nombre = serializers.CharField(max_length=150)
    local_fisico = serializers.CharField(max_length=50, required=False, allow_blank=True)
    direccion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    ubigeo = CampoUbigeo()
    estado = serializers.ChoiceField(choices=Estado.choices)
