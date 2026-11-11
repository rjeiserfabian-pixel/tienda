"""Serializadores del panel de gestión: usuarios, accesos, roles y excepciones."""

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.organizacion.models import Estado
from apps.seguridad.models import (
    AccesoEmpresa,
    Alcance,
    Rol,
    RolPermiso,
    TipoExcepcion,
    Usuario,
    UsuarioPermiso,
    UsuarioRol,
)


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class RolResumenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = ("id", "codigo", "nombre")
        read_only_fields = fields


class AsignacionSerializer(serializers.ModelSerializer):
    rol = RolResumenSerializer(read_only=True)

    class Meta:
        model = UsuarioRol
        fields = ("id", "rol", "empresa", "vigente_hasta")
        read_only_fields = fields


class ExcepcionSerializer(serializers.ModelSerializer):
    codigo = serializers.CharField(source="permiso.codigo", read_only=True)

    class Meta:
        model = UsuarioPermiso
        fields = ("id", "codigo", "tipo", "empresa", "alcance", "vigente_hasta", "motivo")
        read_only_fields = fields


class AccesoSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.CharField(source="empresa.razon_social", read_only=True)
    sucursales = serializers.SerializerMethodField()

    class Meta:
        model = AccesoEmpresa
        fields = ("empresa", "empresa_nombre", "cargo", "estado", "vigente_hasta", "sucursales")
        read_only_fields = fields

    def get_sucursales(self, obj) -> list[int]:
        return [fila.sucursal_id for fila in obj.sucursales.all()]


class UsuarioListaSerializer(serializers.ModelSerializer):
    nombres = serializers.CharField(source="first_name")
    apellidos = serializers.CharField(source="last_name")
    activo = serializers.BooleanField(source="is_active")
    mfa_activo = serializers.BooleanField(read_only=True)
    ultimo_acceso = serializers.DateTimeField(source="last_login")
    empresas = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = (
            "id",
            "username",
            "email",
            "nombres",
            "apellidos",
            "activo",
            "mfa_activo",
            "ultimo_acceso",
            "empresas",
            "roles",
        )
        read_only_fields = fields

    def get_empresas(self, obj) -> list[dict]:
        return [
            {"id": a.empresa_id, "nombre": a.empresa.razon_social}
            for a in obj.accesos_empresa.all()
        ]

    def get_roles(self, obj) -> list[str]:
        return sorted({a.rol.codigo for a in obj.roles_asignados.all()})


class UsuarioDetalleSerializer(UsuarioListaSerializer):
    accesos = serializers.SerializerMethodField()
    asignaciones = serializers.SerializerMethodField()
    excepciones = serializers.SerializerMethodField()
    trabajador = serializers.SerializerMethodField()

    class Meta(UsuarioListaSerializer.Meta):
        fields = (
            *UsuarioListaSerializer.Meta.fields,
            "telefono",
            "documento_numero",
            "trabajador",
            "debe_cambiar_password",
            "creado_en",
            "accesos",
            "asignaciones",
            "excepciones",
        )
        read_only_fields = fields

    def get_trabajador(self, obj) -> dict | None:
        """Trabajador vinculado (app Mantenimiento), por la relación inversa y sin importarla."""
        try:
            t = obj.trabajador
        except ObjectDoesNotExist:
            return None
        if t.eliminado_en is not None:
            return None
        return {"id": t.pk, "nombre": t.nombre_completo, "empresa": t.empresa_id}

    def get_accesos(self, obj) -> list[dict]:
        accesos = (
            AccesoEmpresa.objects.filter(usuario=obj)
            .select_related("empresa")
            .prefetch_related("sucursales")
            .order_by("empresa__razon_social")
        )
        return AccesoSerializer(accesos, many=True).data

    def get_asignaciones(self, obj) -> list[dict]:
        filas = UsuarioRol.objects.filter(usuario=obj).select_related("rol").order_by("id")
        return AsignacionSerializer(filas, many=True).data

    def get_excepciones(self, obj) -> list[dict]:
        filas = UsuarioPermiso.objects.filter(usuario=obj).select_related("permiso").order_by("id")
        return ExcepcionSerializer(filas, many=True).data


class RolListaSerializer(serializers.ModelSerializer):
    n_usuarios = serializers.IntegerField(read_only=True, default=0)
    n_permisos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Rol
        fields = (
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "es_sistema",
            "es_critico",
            "n_usuarios",
            "n_permisos",
        )
        read_only_fields = fields


class RolDetalleSerializer(RolListaSerializer):
    permisos = serializers.SerializerMethodField()

    class Meta(RolListaSerializer.Meta):
        fields = (*RolListaSerializer.Meta.fields, "permisos")
        read_only_fields = fields

    def get_permisos(self, obj) -> dict[str, str]:
        filas = RolPermiso.objects.filter(rol=obj).select_related("permiso")
        return {f.permiso.codigo: f.alcance for f in filas}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class UsuarioCrearSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    nombres = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    apellidos = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    empresa_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=100
    )
    cargo = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    telefono = serializers.RegexField(
        r"^[0-9+()\- ]{6,20}$",
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
        error_messages={
            "invalid": "Use solo números, espacios, + ( ) y guion (6 a 20 caracteres)."
        },
    )
    documento_numero = serializers.RegexField(
        r"^[A-Za-z0-9]{6,15}$",
        max_length=15,
        required=False,
        allow_blank=True,
        default="",
        error_messages={"invalid": "Use de 6 a 15 letras o números, sin espacios."},
    )
    activo = serializers.BooleanField(required=False, default=True)
    rol = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)


class UsuarioActualizarSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False)
    nombres = serializers.CharField(max_length=150, required=False, allow_blank=True)
    apellidos = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=254, required=False)
    telefono = serializers.CharField(max_length=20, required=False, allow_blank=True)
    documento_numero = serializers.CharField(max_length=15, required=False, allow_blank=True)

    CAMPOS_MODELO = {"nombres": "first_name", "apellidos": "last_name"}

    def a_campos_modelo(self) -> dict:
        return {
            self.CAMPOS_MODELO.get(nombre, nombre): valor
            for nombre, valor in self.validated_data.items()
        }


class AccesoEntradaSerializer(serializers.Serializer):
    cargo = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    estado = serializers.ChoiceField(choices=Estado.choices, default=Estado.ACTIVO)
    vigente_hasta = serializers.DateTimeField(required=False, allow_null=True, default=None)
    sucursales = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, default=list, max_length=200
    )


class AsignarRolSerializer(serializers.Serializer):
    rol = serializers.IntegerField(min_value=1)
    empresa = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    vigente_hasta = serializers.DateTimeField(required=False, allow_null=True, default=None)


class ExcepcionEntradaSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=100)
    tipo = serializers.ChoiceField(choices=TipoExcepcion.choices)
    motivo = serializers.CharField(max_length=500)
    empresa = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    alcance = serializers.ChoiceField(choices=Alcance.choices, default=Alcance.EMPRESA)
    vigente_hasta = serializers.DateTimeField(required=False, allow_null=True, default=None)


class RolCrearSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=40)
    nombre = serializers.CharField(max_length=100)
    descripcion = serializers.CharField(
        max_length=250, required=False, allow_blank=True, default=""
    )
    es_critico = serializers.BooleanField(required=False, default=False)
    permisos = serializers.DictField(
        child=serializers.ChoiceField(choices=Alcance.choices), required=False, default=dict
    )


class RolActualizarSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=100)
    descripcion = serializers.CharField(max_length=250, required=False, allow_blank=True)


class MatrizPermisosSerializer(serializers.Serializer):
    permisos = serializers.DictField(child=serializers.ChoiceField(choices=Alcance.choices))
