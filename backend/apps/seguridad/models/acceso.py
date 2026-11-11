"""Accesos de un usuario a empresas y sucursales (la "actividad por empresa" de la ficha)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import ViolacionAmbito
from apps.core.models import OrganizacionScopedModel
from apps.organizacion.models import Empresa, Estado, Sucursal


class AccesoEmpresa(OrganizacionScopedModel):
    """Habilita a un usuario para operar en una empresa, con su cargo.

    Un acceso vencido (``vigente_hasta``) o inactivo deja de contar al instante.
    """

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="accesos_empresa"
    )
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="accesos")
    cargo = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    vigente_hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "acceso a empresa"
        verbose_name_plural = "accesos a empresas"
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "empresa"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_acceso_empresa_usuario_empresa_vigente",
            )
        ]
        indexes = [
            models.Index(fields=["usuario", "estado"], name="ix_acceso_usuario_estado"),
            models.Index(fields=["organizacion", "empresa"], name="ix_acceso_org_empresa"),
        ]

    def __str__(self) -> str:
        return f"{self.usuario_id} → {self.empresa_id}"

    def esta_vigente(self, ahora=None) -> bool:
        ahora = ahora or timezone.now()
        return (
            self.eliminado_en is None
            and self.estado == Estado.ACTIVO
            and (self.vigente_hasta is None or self.vigente_hasta > ahora)
        )

    def validar_ambito(self) -> None:
        from .usuario import Usuario

        # La organización se deriva de la empresa (determinista, no un "por defecto").
        if self.organizacion_id is None and self.empresa_id is not None:
            self.organizacion_id = (
                Empresa.objects.sin_ambito(incluir_eliminados=True)
                .filter(pk=self.empresa_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
        super().validar_ambito()
        empresa_ok = (
            Empresa.objects.sin_ambito()
            .filter(pk=self.empresa_id, organizacion_id=self.organizacion_id)
            .exists()
        )
        usuario_ok = Usuario.objects.filter(
            pk=self.usuario_id, organizacion_id=self.organizacion_id
        ).exists()
        if not (empresa_ok and usuario_ok):
            raise ViolacionAmbito(
                "El usuario y la empresa deben pertenecer a la misma organización."
            )


class AccesoSucursal(OrganizacionScopedModel):
    """Restringe un acceso de empresa a sucursales concretas (alcance SUCURSAL, Fase 3)."""

    acceso_empresa = models.ForeignKey(
        AccesoEmpresa, on_delete=models.PROTECT, related_name="sucursales"
    )
    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="accesos")

    class Meta:
        verbose_name = "acceso a sucursal"
        verbose_name_plural = "accesos a sucursales"
        constraints = [
            models.UniqueConstraint(
                fields=["acceso_empresa", "sucursal"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_acceso_sucursal_vigente",
            )
        ]

    def validar_ambito(self) -> None:
        if self.organizacion_id is None and self.acceso_empresa_id is not None:
            self.organizacion_id = (
                AccesoEmpresa.objects.sin_ambito(incluir_eliminados=True)
                .filter(pk=self.acceso_empresa_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
        super().validar_ambito()
        empresa_id = (
            AccesoEmpresa.objects.sin_ambito()
            .filter(pk=self.acceso_empresa_id, organizacion_id=self.organizacion_id)
            .values_list("empresa_id", flat=True)
            .first()
        )
        coincide = (
            empresa_id is not None
            and Sucursal.objects.sin_ambito()
            .filter(pk=self.sucursal_id, empresa_id=empresa_id)
            .exists()
        )
        if not coincide:
            raise ViolacionAmbito("La sucursal debe pertenecer a la empresa del acceso.")
