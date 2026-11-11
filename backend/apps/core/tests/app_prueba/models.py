"""Modelos SOLO para pruebas: uno por ámbito. Se cargan únicamente con settings.test."""

from django.db import models

from apps.core.crypto import CampoCifrado
from apps.core.models import DocumentoInmutable, EmpresaScopedModel, OrganizacionScopedModel


class ItemOrganizacion(OrganizacionScopedModel):
    nombre = models.CharField(max_length=50)
    asignado_id = models.UUIDField(null=True, blank=True)

    class Meta:
        app_label = "app_prueba"


class ItemEmpresa(EmpresaScopedModel):
    nombre = models.CharField(max_length=50)
    asignado_id = models.UUIDField(null=True, blank=True)
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        app_label = "app_prueba"


class ComprobantePrueba(DocumentoInmutable):
    numero = models.CharField(max_length=20)

    class Meta:
        app_label = "app_prueba"


class SecretoPrueba(OrganizacionScopedModel):
    secreto = CampoCifrado()

    class Meta:
        app_label = "app_prueba"
