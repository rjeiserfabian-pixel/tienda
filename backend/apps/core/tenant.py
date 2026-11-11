"""Contexto de tenant (organización + empresas habilitadas) por request.

Se guarda en un ``ContextVar``: es seguro con hilos y con ``asyncio``. Los
gestores de los modelos con ámbito leen este contexto y, si no existe, fallan
cerrado (``ContextoTenantNoDefinido``) en vez de devolver datos de otro tenant.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

from .exceptions import ContextoTenantNoDefinido


@dataclass(frozen=True, slots=True)
class ContextoTenant:
    organizacion_id: int
    empresa_ids: frozenset[int]
    usuario_id: UUID | None = None

    def empresa_habilitada(self, empresa_id: int | None) -> bool:
        return empresa_id is not None and empresa_id in self.empresa_ids


_contexto: ContextVar[ContextoTenant | None] = ContextVar("contexto_tenant", default=None)


def obtener_contexto() -> ContextoTenant | None:
    return _contexto.get()


def obtener_contexto_requerido() -> ContextoTenant:
    contexto = _contexto.get()
    if contexto is None:
        raise ContextoTenantNoDefinido()
    return contexto


def establecer_contexto(
    organizacion_id: int,
    empresa_ids: Iterable[int],
    usuario_id: UUID | None = None,
) -> Token:
    """Activa el contexto y devuelve el token para restablecerlo."""
    return _contexto.set(
        ContextoTenant(
            organizacion_id=organizacion_id,
            empresa_ids=frozenset(empresa_ids),
            usuario_id=usuario_id,
        )
    )


def restablecer_contexto(token: Token) -> None:
    _contexto.reset(token)


def limpiar_contexto() -> None:
    _contexto.set(None)


@contextmanager
def contexto_tenant(
    organizacion_id: int,
    empresa_ids: Iterable[int],
    usuario_id: UUID | None = None,
) -> Iterator[ContextoTenant]:
    """Activa un contexto dentro de un bloque ``with`` (tareas, comandos, tests)."""
    token = establecer_contexto(organizacion_id, empresa_ids, usuario_id)
    try:
        yield _contexto.get()  # type: ignore[misc]
    finally:
        restablecer_contexto(token)
