from django.conf import settings
from django.db import models


class HistorialPassword(models.Model):
    """Hashes de las últimas contraseñas, para impedir reutilizarlas."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="historial_passwords"
    )
    password_hash = models.CharField(max_length=255)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "historial de contraseña"
        verbose_name_plural = "historial de contraseñas"
        indexes = [models.Index(fields=["usuario", "-creado_en"], name="ix_histpass_usuario_fecha")]

    def __str__(self) -> str:
        return f"Historial de {self.usuario_id} ({self.creado_en:%Y-%m-%d})"
