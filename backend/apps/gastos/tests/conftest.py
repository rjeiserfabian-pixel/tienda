"""Escenario de gastos: el de compras (cajas, métodos de pago, comprobantes) más categorías."""

import pytest

from apps.caja.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    api,
    compras,
    conceptos,
    dec,
    entorno,
    mundo,
    nuevo_usuario,
    rbac,
)
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.categorias_gasto import sembrar_categorias_gasto
from apps.mantenimiento.models import CategoriaGasto, TipoComprobante


@pytest.fixture
def categorias(compras):  # noqa: F811
    """Las categorías de fábrica de la organización, por código."""
    org = compras.entorno.e.org_a
    sembrar_categorias_gasto(org.pk)
    return {c.codigo: c for c in CategoriaGasto.objects.sin_ambito().filter(organizacion=org)}


@pytest.fixture
def escena(nuevo_usuario, compras, categorias, settings, tmp_path):  # noqa: F811
    settings.MEDIA_ROOT = tmp_path
    e = compras.entorno
    org = e.e.org_a
    for nombre, rol in (
        ("admin", "ADMIN"),
        ("contador", "CONTADOR"),
        ("cajero", "CAJERO"),
        ("vendedor", "VENDEDOR"),
    ):
        nuevo_usuario(org, nombre, [e.e1, e.e2], [(rol, None)])
    establecer_contexto(org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)

    def tipo(codigo):
        return TipoComprobante.objects.sin_ambito().get(organizacion=org, codigo=codigo)

    return type(
        "Escena",
        (),
        {
            "compras": compras,
            "empresa": e.e1,
            "otra": e.e2,
            "proveedor": e.proveedor,
            "caja": compras.caja,
            "efectivo": compras.efectivo,
            "categorias": categorias,
            "factura": tipo("01"),
        },
    )
