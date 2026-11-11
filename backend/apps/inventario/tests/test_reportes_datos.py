"""Datos de los reportes: kardex, saldos a una fecha, costo de venta y libro de movimientos."""

from decimal import Decimal as D

import pytest

from apps.inventario.exceptions import ReporteDemasiadoGrande
from apps.inventario.reportes import datos

from .conftest import comprar, vender

pytestmark = pytest.mark.django_db


@pytest.fixture
def historia(entorno):
    """Cemento: compra 50 a 20 (día 40), venta de 5 (35), compra 20 a 22 (20) y venta de 10 (10)."""
    cemento = entorno.producto()
    comprar(entorno, cemento, 50, 20, dias=40)
    vender(entorno, cemento, 5, dias=35)
    comprar(entorno, cemento, 20, 22, dias=20)
    vender(entorno, cemento, 10, dias=10)
    return cemento


def test_kardex_trae_el_saldo_inicial_y_solo_el_rango(entorno, historia):
    k = datos.kardex(entorno.e1, entorno.alm1, historia, entorno.hace(30), entorno.hoy)
    assert (k.saldo_inicial.cantidad, k.saldo_inicial.costo_total) == (45, 900)
    assert [(ln.tipo, ln.cantidad) for ln in k.lineas] == [("ENTRADA", 20), ("SALIDA", 10)]
    assert k.lineas[-1].saldo_cantidad == 55


def test_kardex_sin_movimientos_en_el_rango(entorno, historia):
    k = datos.kardex(entorno.e1, entorno.alm1, historia, entorno.hace(5), entorno.hoy)
    assert k.lineas == []
    assert k.saldo_inicial.cantidad == 55


def test_saldos_a_una_fecha(entorno, historia):
    hoy = datos.saldos_a_fecha(entorno.e1, entorno.hoy, None)
    assert [(f.producto.pk, f.cantidad) for f in hoy] == [(historia.pk, 55)]
    assert hoy[0].costo_total == D("1133.85")
    antes = datos.saldos_a_fecha(entorno.e1, entorno.hace(25), None)
    assert (antes[0].cantidad, antes[0].costo_total) == (45, 900)
    assert datos.saldos_a_fecha(entorno.e1, entorno.hace(50), None) == []


def test_saldos_no_mezclan_empresas_ni_muestran_lo_agotado(entorno, historia):
    arena = entorno.producto("Arena")
    comprar(entorno, arena, 3, 10, dias=5)
    vender(entorno, arena, 3, dias=4)  # se agotó
    comprar(entorno, historia, 7, 50, dias=3, empresa=entorno.e2, almacen=entorno.alm2)
    filas = datos.saldos_a_fecha(entorno.e1, entorno.hoy, None)
    assert [f.producto.pk for f in filas] == [historia.pk]
    de_a2 = datos.saldos_a_fecha(entorno.e2, entorno.hoy, None)
    assert [(f.cantidad, f.costo_total) for f in de_a2] == [(7, 350)]


def test_costo_de_venta_cuadra_con_el_inventario(entorno, historia):
    filas = datos.costo_de_venta(entorno.e1, entorno.hace(30), entorno.hoy, None)
    assert len(filas) == 1
    f = filas[0]
    assert (f.inicial_cantidad, f.inicial_valor) == (45, 900)
    assert (f.entradas_cantidad, f.entradas_valor) == (20, 440)
    assert (f.salidas_cantidad, f.salidas_valor) == (10, D("206.15"))
    assert (f.final_cantidad, f.final_valor) == (55, D("1133.85"))
    # inventario inicial + entradas − inventario final = costo de venta = lo que salió
    assert f.costo_de_venta == f.salidas_valor == D("206.15")


def test_costo_de_venta_con_producto_sin_movimientos_en_el_periodo(entorno, historia):
    filas = datos.costo_de_venta(entorno.e1, entorno.hace(5), entorno.hoy, None)
    f = filas[0]
    assert (f.inicial_valor, f.entradas_valor, f.salidas_valor, f.costo_de_venta) == (
        D("1133.85"),
        0,
        0,
        0,
    )


def test_el_libro_de_movimientos_trae_cabeceras_y_lineas_en_orden(entorno, historia):
    libro = datos.movimientos(entorno.e1, entorno.hace(45), entorno.hoy)
    assert [m.numero for m in libro.movimientos] == [1, 2, 3, 4]
    assert [len(m.lineas.all()) for m in libro.movimientos] == [1, 1, 1, 1]
    assert datos.movimientos(entorno.e2, entorno.hace(45), entorno.hoy).movimientos == []


def test_un_reporte_demasiado_grande_se_rechaza(entorno, historia, monkeypatch):
    monkeypatch.setattr(datos, "MAX_FILAS", 2)
    with pytest.raises(ReporteDemasiadoGrande):
        datos.kardex(entorno.e1, entorno.alm1, historia, entorno.hace(45), entorno.hoy)
    with pytest.raises(ReporteDemasiadoGrande):
        datos.movimientos(entorno.e1, entorno.hace(45), entorno.hoy)
