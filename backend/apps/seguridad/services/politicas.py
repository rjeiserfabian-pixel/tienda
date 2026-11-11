"""Políticas de seguridad de la organización (con caché corta: se consultan en cada petición)."""

from django.core.cache import cache

from apps.organizacion.models import Organizacion

_CLAVE = "seguridad:politica:mfa_obligatorio:{}"
_TTL_SEG = 60


def mfa_obligatorio(organizacion_id: int | None) -> bool:
    if organizacion_id is None:
        return False
    clave = _CLAVE.format(organizacion_id)
    valor = cache.get(clave)
    if valor is None:
        valor = (
            Organizacion.objects.filter(pk=organizacion_id)
            .values_list("mfa_obligatorio", flat=True)
            .first()
            or False
        )
        cache.set(clave, valor, _TTL_SEG)
    return valor


def invalidar(organizacion_id: int) -> None:
    cache.delete(_CLAVE.format(organizacion_id))


def debe_configurar_mfa(usuario) -> bool:
    """El usuario debe activar el segundo factor antes de operar (política de la organización)."""
    return not usuario.mfa_activo and mfa_obligatorio(usuario.organizacion_id)
