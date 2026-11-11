"""Escenario de caja y bancos: el de compras (que ya trae cajas, métodos de pago y catálogos)."""

import pytest

from apps.compras.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    api,
    compras,
    dec,
    entorno,
    mundo,
    nuevo_usuario,
    rbac,
)
from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja
from apps.mantenimiento.models import ConceptoCaja


@pytest.fixture
def conceptos(compras):  # noqa: F811
    """Los conceptos de fábrica ya cargados, por código."""
    sembrar_conceptos_caja(compras.entorno.e.org_a.pk)
    return {
        c.codigo: c
        for c in ConceptoCaja.objects.sin_ambito().filter(organizacion=compras.entorno.e.org_a)
    }
