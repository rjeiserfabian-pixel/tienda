"""Numeración de las series de comprobantes que emite una empresa.

El número lo entrega ``siguiente_numero`` con la fila de la serie bloqueada: dos cajas que emiten
a la vez reciben números distintos y seguidos. Un número entregado no se devuelve, ni siquiera si
el comprobante se anula (SUNAT no permite repetir ni reutilizar números).
"""

from django.db import transaction

from apps.organizacion.models import Empresa

from .exceptions import CorrelativoNoPuedeBajar, SerieAgotada, SerieInactiva, SerieNoDisponible
from .models import EstadoRegistro, SerieComprobante


def formatear(serie: str, numero: int) -> str:
    """``F001`` y 25 → ``F001-00000025`` (el correlativo con 8 dígitos)."""
    return f"{serie}-{numero:08d}"


def validar_correlativo(serie: SerieComprobante, nuevo: int) -> None:
    """Reglas para cambiar a mano el último número: libre al inicio, después solo hacia arriba."""
    if serie.emitidos > 0 and nuevo < serie.ultimo_numero:
        raise CorrelativoNoPuedeBajar()


@transaction.atomic
def siguiente_numero(empresa: Empresa, serie_id: int) -> tuple[str, int]:
    """Entrega el próximo número de la serie: ``(serie, numero)``. Todo o nada."""
    fila = (
        SerieComprobante.objects.sin_ambito()
        .select_for_update()
        .filter(pk=serie_id, empresa=empresa)
        .first()
    )
    if fila is None:
        raise SerieNoDisponible()
    if fila.estado != EstadoRegistro.ACTIVO:
        raise SerieInactiva()
    if fila.ultimo_numero >= SerieComprobante.MAXIMO_NUMERO:
        raise SerieAgotada()
    fila.ultimo_numero += 1
    fila.emitidos += 1
    fila.save(update_fields=["ultimo_numero", "emitidos"])
    return fila.serie, fila.ultimo_numero
