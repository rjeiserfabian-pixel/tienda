from rest_framework import serializers

from apps.seguridad.models import Permiso, Plataforma, Sesion, Usuario
from apps.seguridad.services import politicas


class LoginSerializer(serializers.Serializer):
    identificador = serializers.CharField(max_length=254, help_text="Usuario o correo.")
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    plataforma = serializers.ChoiceField(choices=Plataforma.choices, default=Plataforma.WEB)
    dispositivo = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )
    push_token = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    recordar = serializers.BooleanField(
        default=True, help_text="Mantener la sesión activa (cookie persistente)."
    )


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class CambiarPasswordSerializer(serializers.Serializer):
    actual = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    nueva = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class MfaVerificarSerializer(serializers.Serializer):
    desafio = serializers.CharField(max_length=2000)
    codigo = serializers.CharField(max_length=32, trim_whitespace=True)


class MfaDesafioRespuestaSerializer(serializers.Serializer):
    mfa_requerido = serializers.BooleanField()
    desafio = serializers.CharField()


class MfaPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)


class MfaCodigoSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=32, trim_whitespace=True)


class MfaCredencialesSerializer(MfaPasswordSerializer, MfaCodigoSerializer):
    """Contraseña + código: lo que piden las operaciones sensibles del segundo factor."""


class MfaEstadoSerializer(serializers.Serializer):
    activo = serializers.BooleanField()
    codigos_restantes = serializers.IntegerField()
    obligatorio = serializers.BooleanField()


class MfaConfiguracionSerializer(serializers.Serializer):
    secreto = serializers.CharField()
    uri = serializers.CharField(help_text="URI otpauth:// para generar el código QR.")


class MfaCodigosRecuperacionSerializer(serializers.Serializer):
    codigos_recuperacion = serializers.ListField(child=serializers.CharField())


class RecuperarSolicitudSerializer(serializers.Serializer):
    identificador = serializers.CharField(max_length=254)


class RecuperarConfirmarSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)
    nueva = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)
    codigo_mfa = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default="", trim_whitespace=True
    )


class SucursalHabilitadaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()
    codigo = serializers.CharField()


class EmpresaHabilitadaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    ruc = serializers.CharField()
    razon_social = serializers.CharField()
    nombre_comercial = serializers.CharField()
    cargo = serializers.CharField()
    sucursales = SucursalHabilitadaSerializer(many=True)


class UsuarioPublicoSerializer(serializers.ModelSerializer):
    """Solo los datos que el propio usuario necesita ver de sí mismo."""

    nombres = serializers.CharField(source="first_name")
    apellidos = serializers.CharField(source="last_name")
    debe_configurar_mfa = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = (
            "id",
            "username",
            "email",
            "nombres",
            "apellidos",
            "es_admin_plataforma",
            "debe_cambiar_password",
            "mfa_activo",
            "debe_configurar_mfa",
        )
        read_only_fields = fields

    def get_debe_configurar_mfa(self, obj) -> bool:
        return politicas.debe_configurar_mfa(obj)


class OrganizacionResumenSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()


class SesionSerializer(serializers.ModelSerializer):
    """No expone jti, push_token ni user_agent completo."""

    actual = serializers.SerializerMethodField()

    class Meta:
        model = Sesion
        fields = ("id", "plataforma", "dispositivo", "ip", "creado_en", "ultimo_uso", "actual")
        read_only_fields = fields

    def get_actual(self, obj) -> bool:
        return str(obj.pk) == str(self.context.get("sesion_actual_id"))


class AutenticacionRespuestaSerializer(serializers.Serializer):
    """Documenta la respuesta de login/refresh (``refresh`` solo en clientes no web)."""

    access = serializers.CharField()
    refresh = serializers.CharField(required=False)
    sesion_id = serializers.UUIDField()
    usuario = UsuarioPublicoSerializer()
    organizacion = OrganizacionResumenSerializer(allow_null=True)
    empresas = EmpresaHabilitadaSerializer(many=True)


class PermisoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permiso
        fields = ("codigo", "modulo", "accion", "descripcion", "es_critico")
        read_only_fields = fields


class MisPermisosSerializer(serializers.Serializer):
    empresa = serializers.IntegerField(allow_null=True)
    permisos = serializers.DictField(child=serializers.CharField(), help_text="codigo → alcance")


class NodoMenuSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    ruta = serializers.CharField(allow_blank=True)
    icono = serializers.CharField(allow_blank=True)
    hijos = serializers.ListField(child=serializers.DictField())
