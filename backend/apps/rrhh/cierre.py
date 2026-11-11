"""Meses con planilla cerrada: lo que ya se pagó no se cambia por detrás.

Una planilla cerrada bloquea la asistencia de su mes y que se programen descuentos en él. Vive en un
módulo aparte para que la asistencia y los adelantos lo consulten sin depender del cálculo.
"""

from datetime import date

from django.core.exceptions import ValidationError

from .models import EstadoPlanilla, Planilla


def mes_cerrado(empresa_id: int, fecha: date) -> bool:
    """¿La empresa ya cerró la planilla del mes de esa fecha?"""
    return Planilla.objects.filter(
        empresa_id=empresa_id,
        periodo=fecha.replace(day=1),
        estado=EstadoPlanilla.CERRADA,
    ).exists()


def exigir_mes_abierto(empresa_id: int, fecha: date, error: type[ValidationError], campo: str):
    """Rechaza el cambio si la planilla de ese mes está cerrada (el error llega junto al campo)."""
    if mes_cerrado(empresa_id, fecha):
        raise error(
            {
                campo: f"La planilla de {fecha:%m/%Y} está cerrada. "
                "Para cambiarlo, reábrala primero en Planilla."
            }
        )
