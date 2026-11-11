"""Alerta de bancarización: pagos y cobros grandes en efectivo.

La ley de bancarización exige usar un medio de pago del sistema financiero (transferencia,
depósito, tarjeta, cheque) en operaciones desde S/ 2 000 o US$ 500; pagar o cobrar eso en efectivo
puede hacer perder el gasto o el crédito fiscal. El sistema AVISA: no bloquea, porque hay
excepciones (zonas sin bancos, por ejemplo). Los montos están por confirmar con el contador.
"""

from decimal import Decimal

from django.db.models import Q

from apps.organizacion.models import Empresa

from .models import MovimientoCaja, Origen
from .reportes import INTERNOS

UMBRALES = {"PEN": Decimal("2000"), "USD": Decimal("500")}
# Mover o cuadrar la propia caja no es pagar ni cobrar a un tercero.
CONCEPTOS_EXENTOS = (*INTERNOS, "FALTANTE_CAJA", "SOBRANTE_CAJA")
ORIGENES_EXENTOS = (Origen.ARQUEO, Origen.EXTRACTO, Origen.TRANSFERENCIA)


def supera_umbral(monto: Decimal, moneda: str) -> bool:
    return monto >= UMBRALES[moneda]


def es_sin_bancarizar(movimiento: MovimientoCaja) -> bool:
    """El movimiento es de una caja de efectivo, no es interno y llega al umbral."""
    cuenta = movimiento.cuenta
    return (
        cuenta.tipo == "CAJA"
        and movimiento.origen_tipo not in ORIGENES_EXENTOS
        and movimiento.concepto.codigo not in CONCEPTOS_EXENTOS
        and supera_umbral(movimiento.monto, cuenta.moneda)
    )


def sin_bancarizar(empresa: Empresa, desde, hasta):
    """Movimientos vigentes en efectivo de la empresa que llegan al umbral, en el rango."""
    umbral = Q()
    for moneda, monto in UMBRALES.items():
        umbral |= Q(cuenta__moneda=moneda, monto__gte=monto)
    return (
        MovimientoCaja.objects.filter(
            empresa=empresa,
            estado=MovimientoCaja.Estado.EMITIDO,
            cuenta__tipo="CAJA",
            fecha__gte=desde,
            fecha__lte=hasta,
        )
        .filter(umbral)
        .exclude(concepto__codigo__in=CONCEPTOS_EXENTOS)
        .exclude(origen_tipo__in=ORIGENES_EXENTOS)
        .select_related("cuenta", "concepto")
        .order_by("-fecha", "-id")
    )
