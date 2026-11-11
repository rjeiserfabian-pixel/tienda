"""Aritmética de dinero con ``Decimal`` exacto (nunca ``float``)."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTIMO = Decimal("0.01")
CIEN = Decimal("100")


class MontoInvalido(ValueError):
    pass


def a_decimal(valor) -> Decimal:
    """Convierte str/int/Decimal a Decimal. Rechaza ``float`` por su imprecisión."""
    if isinstance(valor, float | bool):
        raise MontoInvalido("Los montos deben enviarse como texto o Decimal, no como float.")
    try:
        return valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except (InvalidOperation, ValueError) as exc:
        raise MontoInvalido(f"Monto inválido: {valor!r}") from exc


def redondear_moneda(valor) -> Decimal:
    """Redondeo comercial a 2 decimales (0.005 -> 0.01)."""
    return a_decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def calcular_igv(base_imponible, tasa=Decimal("18")) -> Decimal:
    """IGV sobre una base imponible. ``tasa`` en porcentaje (18 = 18 %)."""
    return redondear_moneda(a_decimal(base_imponible) * a_decimal(tasa) / CIEN)


def calcular_vuelto(total, recibido) -> Decimal:
    """Vuelto exacto. No permite cobrar si lo recibido es menor al total."""
    total = redondear_moneda(total)
    recibido = redondear_moneda(recibido)
    if recibido < total:
        raise MontoInvalido(f"El monto recibido ({recibido}) es menor al total ({total}).")
    return recibido - total
