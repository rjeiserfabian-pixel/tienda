import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Plataforma(models.TextChoices):
    WEB = "WEB", "Panel web"
    MOVIL = "MOVIL", "Aplicación móvil"


class MotivoRevocacion(models.TextChoices):
    LOGOUT = "LOGOUT", "Cierre de sesión"
    LOGOUT_GLOBAL = "LOGOUT_GLOBAL", "Cierre de todas las sesiones"
    REMOTA = "REMOTA", "Revocada desde otra sesión"
    REUSO = "REUSO", "Reutilización de un refresh token"
    CAMBIO_PASSWORD = "CAMBIO_PASSWORD", "Cambio de contraseña"
    USUARIO_INACTIVO = "USUARIO_INACTIVO", "Usuario desactivado"
    SIN_ACCESO = "SIN_ACCESO", "Sin acceso a empresas"
    EXPIRADA = "EXPIRADA", "Sesión expirada"
    RECUPERACION = "RECUPERACION", "Recuperación de contraseña"
    MFA_RESTABLECIDO = "MFA_RESTABLECIDO", "Segundo factor restablecido"
    CLAVE_RESTABLECIDA = "CLAVE_RESTABLECIDA", "Contraseña restablecida por un administrador"


class Sesion(models.Model):
    """Una sesión = una cadena de refresh tokens de un dispositivo.

    ``id`` viaja en los tokens como ``sid``; ``jti_actual`` es el único refresh token
    válido. Presentar uno anterior (reutilización) revoca toda la sesión.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sesiones"
    )
    plataforma = models.CharField(max_length=10, choices=Plataforma.choices)
    dispositivo = models.CharField(max_length=200, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    push_token = models.CharField(max_length=255, blank=True)
    # "Mantener sesión activa": si es False la cookie es de sesión (se borra al cerrar el
    # navegador) y la sesión caduca antes (``SESION_NO_PERSISTENTE_HORAS``).
    persistente = models.BooleanField(default=True)

    jti_actual = models.CharField(max_length=64)
    jti_anterior = models.CharField(max_length=64, blank=True)
    rotado_en = models.DateTimeField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    ultimo_uso = models.DateTimeField()
    expira_en = models.DateTimeField()

    revocada = models.BooleanField(default=False)
    revocada_en = models.DateTimeField(null=True, blank=True)
    motivo_revocacion = models.CharField(
        max_length=20, choices=MotivoRevocacion.choices, blank=True
    )

    class Meta:
        verbose_name = "sesión"
        verbose_name_plural = "sesiones"
        indexes = [
            models.Index(
                fields=["usuario", "revocada", "expira_en"], name="ix_sesion_usuario_activa"
            ),
            models.Index(fields=["expira_en"], name="ix_sesion_expira"),
        ]

    def __str__(self) -> str:
        return f"{self.usuario_id} [{self.plataforma}] {self.id}"

    def esta_activa(self, ahora=None) -> bool:
        return not self.revocada and self.expira_en > (ahora or timezone.now())
