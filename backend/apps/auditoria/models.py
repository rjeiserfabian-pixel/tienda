"""Registro de auditoría: quién hizo qué, cuándo y desde dónde. SOLO se agrega, nunca se edita.

Los identificadores (organización, usuario, empresa) se guardan SIN clave foránea: el rastro
debe sobrevivir aunque el registro original cambie, y no debe frenar ninguna operación.
La inmutabilidad se hace cumplir en el modelo y en el QuerySet; la única salida es la
purga por retención (``purgar_anteriores``). En producción conviene reforzarla en la base
de datos (ver docs/DESPLIEGUE_VPS.md).
"""

from django.db import models
from django.utils import timezone


class AuditoriaInmutable(Exception):
    """Se intentó modificar o borrar un evento de auditoría."""


class EventoQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditoriaInmutable("Los eventos de auditoría no se modifican.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AuditoriaInmutable("Los eventos de auditoría no se modifican.")

    def delete(self):
        raise AuditoriaInmutable("Los eventos de auditoría no se eliminan; use la purga.")

    def purgar_anteriores(self, fecha) -> int:
        """Única vía de borrado: retención de eventos más antiguos que ``fecha``."""
        eliminados, _ = models.QuerySet.delete(self.filter(creado_en__lt=fecha))
        return eliminados


class AuditoriaEvento(models.Model):
    creado_en = models.DateTimeField(default=timezone.now)
    organizacion_id = models.BigIntegerField(null=True, blank=True)
    usuario_id = models.UUIDField(null=True, blank=True)
    empresa_id = models.BigIntegerField(null=True, blank=True)
    accion = models.CharField(max_length=60)  # p. ej. "usuario.creado", "sesion.login_fallido"
    recurso_tipo = models.CharField(max_length=40, blank=True)
    recurso_id = models.CharField(max_length=64, blank=True)
    resumen = models.CharField(max_length=250, blank=True)
    detalle = models.JSONField(default=dict, blank=True)  # SIN secretos (se sanea al registrar)
    exito = models.BooleanField(default=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    objects = EventoQuerySet.as_manager()

    class Meta:
        verbose_name = "evento de auditoría"
        verbose_name_plural = "eventos de auditoría"
        ordering = ["-creado_en", "-id"]
        indexes = [
            models.Index(fields=["organizacion_id", "-creado_en"], name="ix_audit_org_fecha"),
            models.Index(
                fields=["organizacion_id", "accion", "-creado_en"], name="ix_audit_org_accion"
            ),
            models.Index(
                fields=["organizacion_id", "recurso_tipo", "recurso_id"], name="ix_audit_recurso"
            ),
            models.Index(fields=["usuario_id", "-creado_en"], name="ix_audit_usuario_fecha"),
            models.Index(fields=["creado_en"], name="ix_audit_fecha"),
        ]

    def __str__(self) -> str:
        return f"{self.creado_en:%Y-%m-%d %H:%M:%S} {self.accion}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditoriaInmutable("Los eventos de auditoría no se modifican.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditoriaInmutable("Los eventos de auditoría no se eliminan.")
