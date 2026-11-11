"""Menú dinámico: el árbol de módulos filtrado por los permisos del usuario."""

from apps.seguridad.models import Modulo
from apps.seguridad.services import permisos_engine as motor


def menu_de(usuario) -> list[dict]:
    """Módulos que el usuario puede ver en AL MENOS una de sus empresas.

    Un módulo sin ``permiso_ver`` es visible para todos. Un padre sin ruta solo aparece
    si conserva algún hijo visible.
    """
    visibles = motor.codigos_en_alguna_empresa(usuario)
    modulos = list(
        Modulo.objects.filter(activo=True).select_related("permiso_ver").order_by("orden", "id")
    )
    hijos_de: dict[int | None, list[Modulo]] = {}
    for modulo in modulos:
        hijos_de.setdefault(modulo.padre_id, []).append(modulo)

    def construir(modulo: Modulo) -> dict | None:
        permiso = modulo.permiso_ver
        if permiso is not None and permiso.codigo not in visibles:
            return None
        hijos = [n for n in map(construir, hijos_de.get(modulo.pk, [])) if n is not None]
        if not modulo.ruta and not hijos:
            return None
        return {
            "codigo": modulo.codigo,
            "nombre": modulo.nombre,
            "ruta": modulo.ruta,
            "icono": modulo.icono,
            "hijos": hijos,
        }

    return [n for n in map(construir, hijos_de.get(None, [])) if n is not None]
