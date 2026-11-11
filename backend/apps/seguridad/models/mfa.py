"""Segundo factor (TOTP), códigos de recuperación del factor y tokens de recuperación de clave."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.crypto import CampoCifrado


class MfaConfig(models.Model):
    """Secreto TOTP del usuario (cifrado). Solo cuenta cuando ``confirmado_en`` está lleno."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa"
    )
    secreto = CampoCifrado()
    creado_en = models.DateTimeField(auto_now_add=True)
    confirmado_en = models.DateTimeField(null=True, blank=True)
    # Último intervalo de 30 s aceptado: un mismo código no sirve dos veces (anti repetición).
    ultimo_paso = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = "segundo factor"
        verbose_name_plural = "segundos factores"

    def __str__(self) -> str:
        return f"MFA de {self.usuario_id}"


class CodigoRecuperacionMfa(models.Model):
    """Código de un solo uso para entrar si se pierde el dispositivo. Solo se guarda su huella."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="codigos_mfa"
    )
    huella = models.CharField(max_length=64)
    usado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "código de recuperación del segundo factor"
        verbose_name_plural = "códigos de recuperación del segundo factor"
        constraints = [
            models.UniqueConstraint(fields=["usuario", "huella"], name="uq_codigo_mfa_usuario")
        ]

    def __str__(self) -> str:
        return f"Código de recuperación de {self.usuario_id}"


class TokenRecuperacion(models.Model):
    """Enlace de un solo uso para restablecer la contraseña. Solo se guarda su huella."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tokens_recuperacion"
    )
    huella = models.CharField(max_length=64, unique=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField(db_index=True)
    usado_en = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = "token de recuperación"
        verbose_name_plural = "tokens de recuperación"
        indexes = [
            models.Index(
                fields=["usuario"],
                condition=Q(usado_en__isnull=True),
                name="ix_tokenrecup_pendiente",
            )
        ]

    def __str__(self) -> str:
        return f"Recuperación de {self.usuario_id}"
