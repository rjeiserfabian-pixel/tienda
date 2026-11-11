"""Reutiliza las fixtures de seguridad (usuarios, RBAC, estado limpio entre pruebas)."""

from apps.seguridad.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    api,
    nuevo_usuario,
    rbac,
)
