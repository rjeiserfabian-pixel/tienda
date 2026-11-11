"""Clases base abstractas del sistema.

Jerarquía::

    ModeloBase                 trazabilidad + borrado lógico
     ├─ OrganizacionScopedModel   datos compartidos de la organización
     └─ EmpresaScopedModel        datos separados por empresa (RUC)
         └─ DocumentoInmutable       comprobantes/movimientos: solo se anulan

Nota: ``creado_por_id`` y similares guardan el UUID del usuario SIN clave
foránea. Así la huella de auditoría sobrevive aunque el usuario cambie y se
evitan dependencias circulares entre apps.
"""

from django.db import models, transaction
from django.utils import timezone

from .exceptions import (
    DocumentoInmutableError,
    DocumentoYaAnulado,
    EmpresaNoHabilitada,
    MotivoObligatorio,
    ViolacionAmbito,
)
from .managers import GestorBase, GestorEmpresa, GestorEmpresaInmutable, GestorOrganizacion
from .tenant import obtener_contexto


class ModeloBase(models.Model):
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por_id = models.UUIDField(null=True, blank=True, editable=False)
    actualizado_por_id = models.UUIDField(null=True, blank=True, editable=False)
    eliminado_en = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)

    objects = GestorBase()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.preparar_para_guardar()
        campos = kwargs.get("update_fields")
        if campos:
            kwargs["update_fields"] = {*campos, "actualizado_en", "actualizado_por_id"}
        super().save(*args, **kwargs)

    def preparar_para_guardar(self) -> None:
        """Completa la huella de auditoría y valida el ámbito. También lo usa bulk_create."""
        contexto = obtener_contexto()
        if contexto is not None and contexto.usuario_id is not None:
            if self._state.adding and self.creado_por_id is None:
                self.creado_por_id = contexto.usuario_id
            self.actualizado_por_id = contexto.usuario_id
        self.validar_ambito()

    def validar_ambito(self) -> None:
        """Las subclases con ámbito verifican aquí que el registro es del tenant activo."""

    def delete(self, using=None, keep_parents=False):
        """Borrado lógico. Para el borrado físico no hay camino desde la aplicación."""
        self.eliminado_en = timezone.now()
        self.save(update_fields=["eliminado_en"])
        return 1, {self._meta.label: 1}

    def restaurar(self) -> None:
        self.eliminado_en = None
        self.save(update_fields=["eliminado_en"])

    @property
    def eliminado(self) -> bool:
        return self.eliminado_en is not None


class OrganizacionScopedModel(ModeloBase):
    """Dato compartido por todas las empresas de una organización (productos, clientes…)."""

    organizacion = models.ForeignKey("organizacion.Organizacion", on_delete=models.PROTECT)

    objects = GestorOrganizacion()

    class Meta:
        abstract = True

    def validar_ambito(self) -> None:
        contexto = obtener_contexto()
        if self.organizacion_id is None:
            if contexto is None:
                raise ViolacionAmbito("Debe indicar la organización del registro.")
            self.organizacion_id = contexto.organizacion_id
        elif contexto is not None and self.organizacion_id != contexto.organizacion_id:
            raise ViolacionAmbito()


class EmpresaScopedModel(ModeloBase):
    """Dato propio de una empresa (ventas, stock, series…). La empresa es SIEMPRE explícita."""

    empresa = models.ForeignKey("organizacion.Empresa", on_delete=models.PROTECT)

    objects = GestorEmpresa()

    class Meta:
        abstract = True

    def validar_ambito(self) -> None:
        if self.empresa_id is None:
            raise ViolacionAmbito("Toda operación debe declarar explícitamente su empresa.")
        contexto = obtener_contexto()
        if contexto is not None and not contexto.empresa_habilitada(self.empresa_id):
            raise EmpresaNoHabilitada()


class DocumentoInmutable(EmpresaScopedModel):
    """Documento emitido: no se edita ni se elimina; solo se anula con motivo."""

    class Estado(models.TextChoices):
        EMITIDO = "EMITIDO", "Emitido"
        ANULADO = "ANULADO", "Anulado"

    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.EMITIDO, db_index=True
    )
    anulado_en = models.DateTimeField(null=True, blank=True, editable=False)
    anulado_por_id = models.UUIDField(null=True, blank=True, editable=False)
    motivo_anulacion = models.TextField(blank=True, editable=False)

    objects = GestorEmpresaInmutable()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding and not getattr(self, "_anulando", False):
            raise DocumentoInmutableError()
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise DocumentoInmutableError()

    def anular(self, *, motivo: str) -> None:
        """Única modificación permitida. El motivo es obligatorio y se bloquea la fila."""
        motivo = (motivo or "").strip()
        if not motivo:
            raise MotivoObligatorio()
        contexto = obtener_contexto()
        with transaction.atomic():
            actual = type(self)._base_manager.select_for_update().get(pk=self.pk)
            if actual.estado == self.Estado.ANULADO:
                raise DocumentoYaAnulado()
            self.estado = self.Estado.ANULADO
            self.anulado_en = timezone.now()
            self.anulado_por_id = contexto.usuario_id if contexto else None
            self.motivo_anulacion = motivo
            self._anulando = True
            try:
                self.save(
                    update_fields=["estado", "anulado_en", "anulado_por_id", "motivo_anulacion"]
                )
            finally:
                self._anulando = False


class RegistroIdempotencia(models.Model):
    """Resultado guardado de una operación crítica para que un reintento no la duplique."""

    class Estado(models.TextChoices):
        EN_PROCESO = "EN_PROCESO", "En proceso"
        COMPLETADO = "COMPLETADO", "Completado"

    organizacion = models.ForeignKey("organizacion.Organizacion", on_delete=models.CASCADE)
    usuario_id = models.UUIDField(null=True, blank=True)
    clave = models.CharField(max_length=128)
    metodo = models.CharField(max_length=10)
    ruta = models.CharField(max_length=255)
    hash_peticion = models.CharField(max_length=64)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.EN_PROCESO)
    codigo_http = models.PositiveSmallIntegerField(null=True, blank=True)
    respuesta = models.JSONField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "clave"], name="uq_idempotencia_organizacion_clave"
            )
        ]

    def __str__(self) -> str:
        return f"{self.metodo} {self.ruta} [{self.clave}]"
