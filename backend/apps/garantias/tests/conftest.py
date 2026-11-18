"""Reusa el escenario de ventas (dos empresas, caja, series, listas y stock)."""

from apps.ventas.tests.conftest import (  # noqa: F401
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
    tienda,
)
