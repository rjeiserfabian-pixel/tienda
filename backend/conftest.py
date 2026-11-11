"""Fixtures compartidas: dos organizaciones, cada una con dos empresas."""

import uuid
from dataclasses import dataclass

import pytest

from apps.organizacion.models import Empresa, Organizacion
from apps.organizacion.validators import _PESOS


def ruc_valido(base10: str) -> str:
    """Completa 10 dígitos con su dígito verificador para obtener un RUC válido."""
    suma = sum(int(d) * p for d, p in zip(base10, _PESOS, strict=True))
    return base10 + str((11 - suma % 11) % 10)


@dataclass
class Escenario:
    org_a: Organizacion
    org_b: Organizacion
    emp_a1: Empresa
    emp_a2: Empresa
    emp_b1: Empresa
    usuario_id: uuid.UUID


def _crear_empresa(org: Organizacion, base10: str, nombre: str) -> Empresa:
    return Empresa.objects.sin_ambito().create(
        organizacion=org, razon_social=nombre, ruc=ruc_valido(base10)
    )


@pytest.fixture
def escenario(db) -> Escenario:
    from apps.mantenimiento.fiscal import sembrar_catalogos_fiscales

    org_a = Organizacion.objects.create(nombre="Organización A")
    org_b = Organizacion.objects.create(nombre="Organización B")
    # Toda organización nace con los catálogos fiscales de SUNAT (como al crearla de verdad).
    sembrar_catalogos_fiscales(org_a.pk)
    sembrar_catalogos_fiscales(org_b.pk)
    return Escenario(
        org_a=org_a,
        org_b=org_b,
        emp_a1=_crear_empresa(org_a, "2010000001", "Empresa A1"),
        emp_a2=_crear_empresa(org_a, "2010000002", "Empresa A2"),
        emp_b1=_crear_empresa(org_b, "2010000003", "Empresa B1"),
        usuario_id=uuid.uuid4(),
    )
