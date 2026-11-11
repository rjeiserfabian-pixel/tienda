"""Anulación de movimientos: el extorno compensa exactamente y no rompe el Kardex."""

import pytest

from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.inventario.exceptions import AnulacionNoPermitida
from apps.inventario.models import MovimientoInventario, OrigenMovimiento, TipoMovimiento
from apps.inventario.movimientos import anular_movimiento

from .conftest import comprar, saldo_de, vender

pytestmark = pytest.mark.django_db


def test_anular_una_compra_saca_lo_que_entro_por_el_mismo_valor(entorno):
    cemento = entorno.producto()
    compra = comprar(entorno, cemento, 10, 20, dias=3)

    extorno = anular_movimiento(compra, motivo="  Factura mal digitada ")

    compra.refresh_from_db()
    assert compra.estado == MovimientoInventario.Estado.ANULADO
    assert compra.motivo_anulacion == "Factura mal digitada"
    assert (extorno.tipo, extorno.origen) == (TipoMovimiento.SALIDA, OrigenMovimiento.EXTORNO)
    assert extorno.extorna_id == compra.pk
    assert extorno.fecha == entorno.hoy  # el extorno va con fecha de hoy, no reescribe el pasado
    assert extorno.tipo_operacion == compra.tipo_operacion
    saldo = saldo_de(entorno, cemento)
    assert (saldo.cantidad, saldo.costo_total) == (0, 0)
    # El rastro completo queda en el Kardex: la entrada, el extorno y nada se borra.
    assert compra.lineas.count() == 1 and extorno.lineas.count() == 1


def test_anular_una_venta_devuelve_la_mercaderia_a_su_costo_original(entorno):
    cemento = entorno.producto()
    comprar(entorno, cemento, 10, 20, dias=5)
    comprar(entorno, cemento, 10, 30, dias=4)  # promedio 25
    venta = vender(entorno, cemento, 10, dias=2)
    assert venta.lineas.get().costo_total == 250

    extorno = anular_movimiento(venta, motivo="Cliente devolvió todo")

    assert extorno.tipo == TipoMovimiento.ENTRADA
    saldo = saldo_de(entorno, cemento)
    assert (saldo.cantidad, saldo.costo_total, saldo.costo_unitario) == (20, 500, 25)


def test_se_puede_anular_una_compra_si_queda_stock_para_devolver(entorno):
    cemento = entorno.producto()
    compra = comprar(entorno, cemento, 10, 20, dias=5)  # 200
    comprar(entorno, cemento, 10, 30, dias=4)  # 300
    vender(entorno, cemento, 5, dias=2)  # 5 a 25 = 125 -> quedan 15 por 375

    anular_movimiento(compra, motivo="Proveedor equivocado")

    saldo = saldo_de(entorno, cemento)
    assert (saldo.cantidad, saldo.costo_total) == (5, 175)


def test_no_se_anula_una_compra_cuya_mercaderia_ya_salio(entorno):
    cemento = entorno.producto()
    compra = comprar(entorno, cemento, 10, 20, dias=5)
    vender(entorno, cemento, 10, dias=2)
    total = MovimientoInventario.objects.count()

    with pytest.raises(AnulacionNoPermitida) as error:
        anular_movimiento(compra, motivo="Me equivoqué")

    assert "ya salió" in error.value.mensaje
    compra.refresh_from_db()
    assert compra.estado == MovimientoInventario.Estado.EMITIDO
    assert MovimientoInventario.objects.count() == total
    assert saldo_de(entorno, cemento).cantidad == 0


def test_el_motivo_es_obligatorio(entorno):
    compra = comprar(entorno, entorno.producto(), 1, 1)
    for vacio in ("", "   ", None):
        with pytest.raises(MotivoObligatorio):
            anular_movimiento(compra, motivo=vacio)
    compra.refresh_from_db()
    assert compra.estado == MovimientoInventario.Estado.EMITIDO


def test_no_se_anula_dos_veces(entorno):
    compra = comprar(entorno, entorno.producto(), 1, 1)
    anular_movimiento(compra, motivo="Primera")
    with pytest.raises(DocumentoYaAnulado):
        anular_movimiento(compra, motivo="Segunda")


def test_un_extorno_no_se_anula(entorno):
    compra = comprar(entorno, entorno.producto(), 1, 1)
    extorno = anular_movimiento(compra, motivo="Error")
    with pytest.raises(AnulacionNoPermitida):
        anular_movimiento(extorno, motivo="Quiero revertirlo")


def test_anular_en_un_mes_cerrado_pasa_a_hoy_y_no_toca_el_cerrado(entorno):
    from apps.inventario import periodos

    from .conftest import fin_de_mes

    cemento = entorno.producto()
    fin_pasado = fin_de_mes(entorno.hoy, 1)
    compra = comprar(entorno, cemento, 10, 20, dias=(entorno.hoy - fin_pasado).days)
    periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(fin_pasado))

    extorno = anular_movimiento(compra, motivo="Error detectado después del cierre")

    assert extorno.fecha == entorno.hoy
    assert compra.fecha == fin_pasado  # la entrada del mes cerrado queda como estaba
    assert saldo_de(entorno, cemento).cantidad == 0
