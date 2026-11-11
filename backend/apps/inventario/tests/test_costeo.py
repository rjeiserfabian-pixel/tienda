"""Costo promedio ponderado: el cálculo puro, con el ejemplo del Kardex del contador."""

from decimal import Decimal as D

import pytest

from apps.inventario.costeo import Saldo, aplicar_entrada, aplicar_salida
from apps.inventario.exceptions import StockInsuficiente


def test_ejemplo_del_cemento_del_kardex():
    saldo = aplicar_entrada(Saldo(), D("50"), D("1000"))  # 50 bolsas a S/ 20
    assert (saldo.cantidad, saldo.costo_total, saldo.costo_unitario) == (50, 1000, 20)

    saldo, importe = aplicar_salida(saldo, D("5"))
    assert (importe, saldo.cantidad, saldo.costo_total, saldo.costo_unitario) == (100, 45, 900, 20)

    saldo, importe = aplicar_salida(saldo, D("5"))
    assert (importe, saldo.cantidad, saldo.costo_total) == (100, 40, 800)

    saldo = aplicar_entrada(saldo, D("20"), D("440"))  # 20 a S/ 22
    assert (saldo.cantidad, saldo.costo_total) == (60, 1240)
    assert saldo.costo_unitario == D("20.666667")
    assert saldo.costo_unitario.quantize(D("0.01")) == D("20.67")

    saldo = aplicar_entrada(saldo, D("10"), D("190"))  # 10 a S/ 19
    assert (saldo.cantidad, saldo.costo_total) == (70, 1430)
    assert saldo.costo_unitario.quantize(D("0.01")) == D("20.43")


def test_la_salida_no_cambia_el_promedio_salvo_el_redondeo_al_centavo():
    saldo = aplicar_entrada(Saldo(), D("60"), D("1240"))
    despues, importe = aplicar_salida(saldo, D("7"))
    assert importe == D("144.67")  # 7 × 20.666667, al centavo: lo que se registra en los libros
    # El costo total manda: el promedio se deriva de él y solo difiere por esos centavos.
    assert abs(despues.costo_unitario - saldo.costo_unitario) < D("0.001")
    assert despues.costo_unitario.quantize(D("0.01")) == D("20.67")


def test_vaciar_el_saldo_deja_el_costo_total_en_cero():
    # 3 unidades por 10.00: cada una vale 3.3333…; al sacar las 3 no puede sobrar un centavo.
    saldo = aplicar_entrada(Saldo(), D("3"), D("10.00"))
    saldo, primera = aplicar_salida(saldo, D("1"))
    saldo, segunda = aplicar_salida(saldo, D("1"))
    saldo, tercera = aplicar_salida(saldo, D("1"))
    assert primera + segunda + tercera == D("10.00")
    assert (saldo.cantidad, saldo.costo_total) == (0, 0)


def test_con_el_saldo_en_cero_se_conserva_el_ultimo_promedio_y_la_compra_siguiente_lo_reemplaza():
    saldo = aplicar_entrada(Saldo(), D("10"), D("200"))
    saldo, _ = aplicar_salida(saldo, D("10"))
    assert saldo.costo_unitario == 20
    saldo = aplicar_entrada(saldo, D("5"), D("150"))
    assert saldo.costo_unitario == 30


def test_no_hay_stock_negativo():
    saldo = aplicar_entrada(Saldo(), D("40"), D("800"))
    with pytest.raises(StockInsuficiente) as error:
        aplicar_salida(saldo, D("45"))  # el caso del Excel: salían 45 y solo había 40
    assert error.value.detalle == {"disponible": "40", "solicitado": "45"}


def test_salida_sin_nada_en_el_almacen():
    with pytest.raises(StockInsuficiente):
        aplicar_salida(Saldo(), D("1"))


def test_salida_con_importe_fijo_resta_exactamente_ese_valor():
    saldo = aplicar_entrada(Saldo(), D("20"), D("500"))
    despues, importe = aplicar_salida(saldo, D("10"), importe_fijo=D("200"))
    assert importe == 200
    assert (despues.cantidad, despues.costo_total) == (10, 300)


def test_importe_fijo_mayor_al_costo_disponible_se_rechaza():
    saldo = aplicar_entrada(Saldo(), D("20"), D("500"))
    with pytest.raises(StockInsuficiente):
        aplicar_salida(saldo, D("10"), importe_fijo=D("600"))


def test_importe_fijo_que_vacia_el_saldo_absorbe_el_resto():
    saldo = aplicar_entrada(Saldo(), D("10"), D("200"))
    despues, importe = aplicar_salida(saldo, D("10"), importe_fijo=D("150"))
    assert importe == 200
    assert (despues.cantidad, despues.costo_total) == (0, 0)
