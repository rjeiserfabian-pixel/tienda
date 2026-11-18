"""El porcentaje de comisión de los técnicos: el propio de cada uno o el general de la empresa.

* Cada empresa tiene un porcentaje GENERAL (por defecto 1 %, se puede cambiar).
* Un técnico puede tener el SUYO (aunque sea 0 %); si no lo tiene, usa el general.
* La comisión de una orden se congela al entregarla (ver ``entrega._congelar_comision``).
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from apps.mantenimiento.models import Personal

from .models import ComisionTecnico, ConfiguracionComisionTecnicos

PORCENTAJE_INICIAL = Decimal("1.00")
CERO = Decimal("0")


def validar(valor) -> Decimal:
    """El porcentaje como número de 0 a 100 con dos decimales (``ValueError`` si no lo es)."""
    try:
        numero = Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Escriba un porcentaje válido.") from None
    if not numero.is_finite() or not (CERO <= numero <= 100):
        raise ValueError("El porcentaje va de 0 a 100.")
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def por_defecto(empresa_id: int) -> Decimal:
    """El porcentaje general de la empresa para los técnicos sin uno propio."""
    fila = ConfiguracionComisionTecnicos.objects.filter(empresa_id=empresa_id).first()
    return fila.porcentaje_defecto if fila else PORCENTAJE_INICIAL


def fijar_por_defecto(empresa_id: int, porcentaje) -> ConfiguracionComisionTecnicos:
    """Guarda el porcentaje general (vale para las entregas que vengan)."""
    valor = validar(porcentaje)
    fila, _ = ConfiguracionComisionTecnicos.objects.update_or_create(
        empresa_id=empresa_id, defaults={"porcentaje_defecto": valor}
    )
    return fila


def de_tecnico(personal: Personal) -> tuple[Decimal, bool]:
    """(porcentaje que gana, si es propio). Sin uno propio gana el general de la empresa."""
    fila = ComisionTecnico.objects.filter(personal_id=personal.pk).first()
    if fila is not None and fila.porcentaje is not None:
        return fila.porcentaje, True
    return por_defecto(personal.empresa_id), False


def quitar_propio(personal: Personal) -> bool:
    """El técnico vuelve a usar el general. Devuelve si tenía uno propio."""
    fila = ComisionTecnico.objects.filter(personal_id=personal.pk).first()
    if fila is None or fila.porcentaje is None:
        return False
    fila.porcentaje = None
    fila.save(update_fields=["porcentaje", "actualizado_en"])
    return True
