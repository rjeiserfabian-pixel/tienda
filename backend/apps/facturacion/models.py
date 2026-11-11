"""Facturación electrónica: el registro de lo que se envía a SUNAT por la API de facturación.

Cada documento electrónico (factura, boleta, nota de crédito o guía de remisión) tiene UNA fila de
``EnvioSunat`` que se va actualizando en cada intento. Aquí se guarda lo que el sistema envió y
lo que la API respondió; la lectura de «aceptado» o «rechazado» de SUNAT se interpreta aparte.

Nunca se guarda lo que se ENVÍA (lleva las claves SOL de la empresa) ni la parte de la respuesta
que trae datos internos de la sesión de SUNAT.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import EmpresaScopedModel


class OrigenDocumento(models.TextChoices):
    COMPROBANTE = "COMPROBANTE", "Factura o boleta"
    NOTA_CREDITO = "NOTA_CREDITO", "Nota de crédito"
    GUIA = "GUIA", "Guía de remisión"


class EstadoEnvio(models.TextChoices):
    EN_PROCESO = "EN_PROCESO", "Enviando"
    ENVIADO = "ENVIADO", "Enviado a la API"
    ERROR_API = "ERROR_API", "La API devolvió un error"
    SIN_CONEXION = "SIN_CONEXION", "No se pudo conectar con la API"


class EnvioSunat(EmpresaScopedModel):
    """El envío de un documento electrónico a SUNAT (por la API de facturación)."""

    origen = models.CharField(max_length=12, choices=OrigenDocumento.choices)
    origen_id = models.PositiveBigIntegerField()
    # Tabla 10 de SUNAT: 01 factura, 03 boleta, 07 nota de crédito, 09 guía de remisión.
    tipo_documento = models.CharField(max_length=2)
    serie = models.CharField(max_length=10)
    numero = models.PositiveIntegerField()

    estado = models.CharField(
        max_length=12, choices=EstadoEnvio.choices, default=EstadoEnvio.EN_PROCESO, db_index=True
    )
    intentos = models.PositiveSmallIntegerField(default=0)
    iniciado_en = models.DateTimeField(null=True, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    # Beta o producción, tal como estaba la empresa al enviar.
    modo = models.CharField(max_length=10, blank=True)

    # Lo que respondió la API (ya limpio de datos de sesión).
    codigo_respuesta = models.CharField(max_length=20, blank=True)
    mensaje = models.CharField(max_length=500, blank=True)
    ticket = models.CharField(max_length=80, blank=True)
    codigo_hash = models.CharField(max_length=80, blank=True)
    respuesta = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "envío a SUNAT"
        verbose_name_plural = "envíos a SUNAT"
        ordering = ["-actualizado_en"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "origen", "origen_id"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_enviosunat_documento",
            )
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_enviosunat_estado")]

    def __str__(self) -> str:
        return f"{self.tipo_documento} {self.serie}-{self.numero:08d} ({self.estado})"
