"""Correlativo de movimientos por empresa.

La fila del correlativo se bloquea durante toda la transacción: además de numerar sin saltos ni
repeticiones, sirve de cerrojo por empresa. Registrar un movimiento y cerrar un periodo pasan
por aquí, de modo que nunca pueden cruzarse (un movimiento no se cuela en un mes que se cierra).
"""

from apps.mantenimiento.models import Correlativo
from apps.organizacion.models import Empresa


def bloquear(empresa: Empresa) -> Correlativo:
    """Devuelve la fila del correlativo bloqueada. Debe llamarse dentro de una transacción."""
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"inventario:movimiento:{empresa.pk}"
    )
    return Correlativo.objects.select_for_update().get(pk=fila.pk)


def siguiente(fila: Correlativo) -> int:
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo
