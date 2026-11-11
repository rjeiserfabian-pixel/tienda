from decimal import Decimal

import pytest

from apps.core.utils.dinero import (
    MontoInvalido,
    a_decimal,
    calcular_igv,
    calcular_vuelto,
    redondear_moneda,
)


def test_rechaza_float():
    with pytest.raises(MontoInvalido):
        a_decimal(0.1)


def test_redondeo_comercial():
    assert redondear_moneda("0.005") == Decimal("0.01")
    assert redondear_moneda("2.675") == Decimal("2.68")  # con float daría 2.67


def test_igv_exacto():
    assert calcular_igv("100.00") == Decimal("18.00")
    assert calcular_igv("3597.00") == Decimal("647.46")


def test_vuelto():
    assert calcular_vuelto("4244.46", "4300") == Decimal("55.54")
    assert calcular_vuelto("10.00", "10.00") == Decimal("0.00")


def test_no_se_cobra_si_lo_recibido_es_menor_al_total():
    # Caso de la pantalla de referencia: total 4,244.46 recibido 4,244.00.
    with pytest.raises(MontoInvalido):
        calcular_vuelto("4244.46", "4244.00")
