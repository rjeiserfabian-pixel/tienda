"""Motor de permisos: ``tiene_permiso(usuario, codigo, empresa)``.

Orden de decisión (la empresa de la operación se pasa SIEMPRE)::

    usuario autenticado y activo
      → acceso vigente a esa empresa?          no → denegar
      → administrador de plataforma?           sí → permitir (alcance ORGANIZACION)
      → DENY directo (esa empresa o general)?  sí → denegar
      → ALLOW directo y roles vigentes         → permitir con el alcance MÁS AMPLIO
      → denegar

``empresa_id=None`` significa "dato de la organización" (clientes, productos…): se
consideran todas las asignaciones del usuario, y solo los DENY generales lo bloquean.

Rendimiento: el resultado completo de un (usuario, empresa) se guarda en caché (Redis en
producción) y se invalida por versión: ``uv`` (usuario) y ``ov`` (organización) forman parte
de la clave, así que subir un contador deja obsoletas todas sus entradas sin borrarlas.
Una asignación temporal acorta el TTL de la entrada hasta su vencimiento.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from apps.organizacion.models import Estado
from apps.seguridad.exceptions import PermisoDenegado, SeparacionDeFunciones
from apps.seguridad.models import (
    AccesoEmpresa,
    AccesoSucursal,
    RolPermiso,
    TipoExcepcion,
    UsuarioPermiso,
    UsuarioRol,
)
from apps.seguridad.permisos_catalogo import CODIGOS

TTL_SEGUNDOS = 300

ORDEN_ALCANCE = {"PROPIO": 0, "ASIGNADO": 1, "SUCURSAL": 2, "EMPRESA": 3, "ORGANIZACION": 4}


def mas_amplio(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if ORDEN_ALCANCE[a] >= ORDEN_ALCANCE[b] else b


def alcance_cubre(tengo: str | None, requerido: str | None) -> bool:
    """¿Un alcance ``tengo`` alcanza para lo que se pide (``requerido``)?"""
    if tengo is None:
        return False
    return requerido is None or ORDEN_ALCANCE[tengo] >= ORDEN_ALCANCE[requerido]


@dataclass(frozen=True, slots=True)
class PermisosEmpresa:
    acceso: bool
    permisos: dict[str, str]  # codigo -> alcance
    sucursal_ids: frozenset[int]

    def a_cache(self) -> dict:
        return {"a": self.acceso, "p": self.permisos, "s": sorted(self.sucursal_ids)}

    @classmethod
    def desde_cache(cls, datos: dict) -> "PermisosEmpresa":
        return cls(datos["a"], datos["p"], frozenset(datos["s"]))


SIN_ACCESO = PermisosEmpresa(False, {}, frozenset())


# ---------------------------------------------------------------------------
# Versiones de caché
# ---------------------------------------------------------------------------
def _k_uv(usuario_id) -> str:
    return f"perm:uv:{usuario_id}"


def _k_ov(organizacion_id) -> str:
    return f"perm:ov:{organizacion_id or 0}"


def _incrementar(clave: str) -> None:
    cache.add(clave, 1, None)
    cache.incr(clave)


def invalidar_usuario(usuario_id) -> None:
    """Deja obsoletos los permisos y empresas en caché de UN usuario."""
    _incrementar(_k_uv(usuario_id))


def invalidar_organizacion(organizacion_id) -> None:
    """Deja obsoletos los permisos de TODOS los usuarios de la organización (cambio de roles)."""
    _incrementar(_k_ov(organizacion_id))


def _versiones(usuario) -> tuple[int, int]:
    claves = [_k_uv(usuario.pk), _k_ov(usuario.organizacion_id)]
    valores = cache.get_many(claves)
    return valores.get(claves[0], 1), valores.get(claves[1], 1)


# ---------------------------------------------------------------------------
# Cálculo (consulta a la base) — solo se ejecuta ante un fallo de caché
# ---------------------------------------------------------------------------
def _vigente(ahora: datetime) -> Q:
    return Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gt=ahora)


def _calcular(usuario, empresa_id: int | None) -> tuple[PermisosEmpresa, datetime | None]:
    if usuario.es_admin_plataforma:
        return PermisosEmpresa(True, dict.fromkeys(CODIGOS, "ORGANIZACION"), frozenset()), None
    if usuario.organizacion_id is None:
        return SIN_ACCESO, None

    ahora = timezone.now()
    vencimientos: list[datetime] = []
    acceso_pk = None

    if empresa_id is not None:
        acceso = (
            AccesoEmpresa.objects.sin_ambito()
            .filter(
                _vigente(ahora),
                usuario=usuario,
                empresa_id=empresa_id,
                organizacion_id=usuario.organizacion_id,
                estado=Estado.ACTIVO,
                empresa__estado=Estado.ACTIVO,
                empresa__eliminado_en__isnull=True,
            )
            .values("pk", "vigente_hasta")
            .first()
        )
        if acceso is None:
            return SIN_ACCESO, None
        acceso_pk = acceso["pk"]
        if acceso["vigente_hasta"]:
            vencimientos.append(acceso["vigente_hasta"])

    # --- Roles vigentes (de esa empresa o generales) ---
    asignaciones = UsuarioRol.objects.sin_ambito().filter(
        _vigente(ahora), usuario=usuario, rol__eliminado_en__isnull=True
    )
    if empresa_id is not None:
        asignaciones = asignaciones.filter(Q(empresa__isnull=True) | Q(empresa_id=empresa_id))
    rol_ids = set()
    for fila in asignaciones.values("rol_id", "vigente_hasta"):
        rol_ids.add(fila["rol_id"])
        if fila["vigente_hasta"]:
            vencimientos.append(fila["vigente_hasta"])

    permisos: dict[str, str] = {}
    if rol_ids:
        filas = (
            RolPermiso.objects.sin_ambito()
            .filter(rol_id__in=rol_ids, permiso__activo=True)
            .values_list("permiso__codigo", "alcance")
        )
        for codigo, alcance in filas:
            permisos[codigo] = mas_amplio(permisos.get(codigo), alcance)

    # --- Excepciones individuales: ALLOW suma, DENY gana siempre ---
    excepciones = UsuarioPermiso.objects.sin_ambito().filter(
        _vigente(ahora), usuario=usuario, permiso__activo=True
    )
    if empresa_id is not None:
        excepciones = excepciones.filter(Q(empresa__isnull=True) | Q(empresa_id=empresa_id))
    denegados: set[str] = set()
    for fila in excepciones.values(
        "permiso__codigo", "tipo", "alcance", "empresa_id", "vigente_hasta"
    ):
        codigo = fila["permiso__codigo"]
        if fila["tipo"] == TipoExcepcion.DENY:
            # Un DENY de una empresa concreta no bloquea la consulta a nivel organización.
            if empresa_id is not None or fila["empresa_id"] is None:
                denegados.add(codigo)
        else:
            permisos[codigo] = mas_amplio(permisos.get(codigo), fila["alcance"])
        if fila["vigente_hasta"]:
            vencimientos.append(fila["vigente_hasta"])
    for codigo in denegados:
        permisos.pop(codigo, None)

    sucursales: frozenset[int] = frozenset()
    if acceso_pk is not None:
        sucursales = frozenset(
            AccesoSucursal.objects.sin_ambito()
            .filter(acceso_empresa_id=acceso_pk, sucursal__eliminado_en__isnull=True)
            .values_list("sucursal_id", flat=True)
        )

    return PermisosEmpresa(True, permisos, sucursales), (
        min(vencimientos) if vencimientos else None
    )


def permisos_de(usuario, empresa_id: int | None = None) -> PermisosEmpresa:
    """Permisos efectivos del usuario en una empresa (o a nivel organización si es None)."""
    if usuario is None or not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return SIN_ACCESO
    uv, ov = _versiones(usuario)
    clave = f"perm:{usuario.pk}:{uv}:{ov}:{empresa_id or 0}"
    guardado = cache.get(clave)
    if guardado is not None:
        return PermisosEmpresa.desde_cache(guardado)

    resultado, vence = _calcular(usuario, empresa_id)
    ttl = TTL_SEGUNDOS
    if vence is not None:
        ttl = max(1, min(ttl, int((vence - timezone.now()).total_seconds())))
    cache.set(clave, resultado.a_cache(), ttl)
    return resultado


def empresas_ids_de(usuario) -> list[int]:
    """Ids de las empresas con acceso vigente (en caché, invalidado por versión de usuario)."""
    if usuario is None or not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return []
    if usuario.organizacion_id is None:
        return []
    uv, ov = _versiones(usuario)
    clave = f"perm:{usuario.pk}:{uv}:{ov}:empresas"
    guardado = cache.get(clave)
    if guardado is not None:
        return guardado
    ahora = timezone.now()
    filas = list(
        AccesoEmpresa.objects.sin_ambito()
        .filter(
            _vigente(ahora),
            usuario=usuario,
            organizacion_id=usuario.organizacion_id,
            estado=Estado.ACTIVO,
            empresa__estado=Estado.ACTIVO,
            empresa__eliminado_en__isnull=True,
        )
        .values_list("empresa_id", "vigente_hasta")
        .order_by("empresa_id")
    )
    ids = [empresa_id for empresa_id, _ in filas]
    vencimientos = [v for _, v in filas if v]
    ttl = TTL_SEGUNDOS
    if vencimientos:
        ttl = max(1, min(ttl, int((min(vencimientos) - ahora).total_seconds())))
    cache.set(clave, ids, ttl)
    return ids


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def alcance_de(usuario, codigo: str, empresa_id: int | None = None) -> str | None:
    """Alcance con el que el usuario tiene el permiso, o None si no lo tiene."""
    return permisos_de(usuario, empresa_id).permisos.get(codigo)


def tiene_permiso(
    usuario, codigo: str, empresa_id: int | None = None, *, alcance_minimo: str | None = None
) -> bool:
    return alcance_cubre(alcance_de(usuario, codigo, empresa_id), alcance_minimo)


def exigir_permiso(usuario, codigo: str, empresa_id: int | None = None) -> str:
    """Devuelve el alcance o lanza ``PermisoDenegado``."""
    alcance = alcance_de(usuario, codigo, empresa_id)
    if alcance is None:
        raise PermisoDenegado(detalle={"permiso": codigo, "empresas": [empresa_id]})
    return alcance


def exigir_permiso_en_empresas(
    usuario, codigo: str, empresa_ids: Iterable[int | None]
) -> dict[int | None, str]:
    """Operación con varias empresas (p. ej. un carrito con líneas de A y B).

    Se verifica CADA empresa distinta y, si falta una sola, se rechaza TODO antes de
    guardar nada. Devuelve ``{empresa_id: alcance}``.
    """
    distintas = list(dict.fromkeys(empresa_ids))
    alcances = {e: alcance_de(usuario, codigo, e) for e in distintas}
    faltantes = [e for e, alcance in alcances.items() if alcance is None]
    if faltantes:
        raise PermisoDenegado(detalle={"permiso": codigo, "empresas": faltantes})
    return alcances  # type: ignore[return-value]


def codigos_en_alguna_empresa(usuario) -> set[str]:
    """Unión de permisos en todas las empresas habilitadas y a nivel organización (para el menú)."""
    codigos = set(permisos_de(usuario, None).permisos)
    for empresa_id in empresas_ids_de(usuario):
        codigos.update(permisos_de(usuario, empresa_id).permisos)
    return codigos


def exigir_separacion_de_funciones(usuario_actual_id, usuario_otro_paso_id) -> None:
    """Para operaciones en dos pasos (autorizar/recibir): no pueden ser la misma persona."""
    if usuario_otro_paso_id is not None and str(usuario_actual_id) == str(usuario_otro_paso_id):
        raise SeparacionDeFunciones()
