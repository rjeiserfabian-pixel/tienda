from decimal import Decimal as D

import pytest

from apps.compras.calculo import EntradaLinea, calcular_compra, repartir_por_peso
from apps.compras.exceptions import CompraInvalida


def gravada(cantidad, precio, tasa="18"):
    return EntradaLinea(D(str(cantidad)), D(str(precio)), "GRAVADO", "IGV", D(tasa))


def exonerada(cantidad, precio):
    return EntradaLinea(D(str(cantidad)), D(str(precio)), "EXONERADO", "NINGUNO", D("0"))


def inafecta(cantidad, precio):
    return EntradaLinea(D(str(cantidad)), D(str(precio)), "INAFECTO", "NINGUNO", D("0"))


def calc(lineas, **kw):
    kw.setdefault("precios_incluyen_igv", False)
    kw.setdefault("igv_al_costo", False)
    return calcular_compra(lineas, **kw)


def test_precio_sin_igv():
    r = calc([gravada(2, "100")])
    assert (r.op_gravada, r.igv, r.total) == (D("200.00"), D("36.00"), D("236.00"))
    assert r.lineas[0].costo_soles == D("200.00")


def test_precio_con_igv():
    r = calc([gravada(1, "118")], precios_incluyen_igv=True)
    assert (r.op_gravada, r.igv, r.total) == (D("100.00"), D("18.00"), D("118.00"))


def test_con_igv_el_total_es_lo_escrito():
    r = calc([gravada(3, "10.00")], precios_incluyen_igv=True)
    assert r.total == D("30.00")
    assert r.op_gravada + r.igv == D("30.00")


def test_igv_al_costo_suma_el_impuesto():
    r = calc([gravada(1, "100")], igv_al_costo=True)
    assert r.lineas[0].costo_soles == D("118.00")
    assert r.total == D("118.00")


def test_exonerada_e_inafecta_no_pagan_impuesto():
    r = calc([exonerada(1, "50"), inafecta(2, "10")], igv_al_costo=True)
    assert (r.op_exonerada, r.op_inafecta, r.igv, r.total) == (
        D("50.00"),
        D("20.00"),
        D("0.00"),
        D("70.00"),
    )
    assert [ln.costo_soles for ln in r.lineas] == [D("50.00"), D("20.00")]


def test_mezcla_de_afectaciones_cuadra():
    r = calc([gravada(1, "100"), exonerada(1, "30"), inafecta(1, "5")])
    assert r.total == r.op_gravada + r.igv + r.op_exonerada + r.op_inafecta
    assert r.total == D("153.00")


def test_igv_por_grupo_y_cuadre_en_la_linea_mayor():
    # Tres líneas de 0,05 + 0,05 + 0,05: el IGV por línea sería 0,01 ×3 = 0,03; por grupo, 0,03.
    r = calc([gravada(1, "0.05")] * 3)
    assert r.igv == sum((ln.impuesto for ln in r.lineas), D("0"))
    assert r.op_gravada == sum((ln.valor_venta for ln in r.lineas), D("0"))


@pytest.mark.parametrize("incluye", [False, True])
def test_las_lineas_siempre_suman_los_totales(incluye):
    lineas = [
        gravada("3", "9.99"),
        gravada("7", "1.33"),
        gravada("2", "0.37"),
        exonerada(5, "2.22"),
    ]
    r = calc(lineas, precios_incluyen_igv=incluye)
    assert sum((ln.valor_venta for ln in r.lineas), D("0")) == r.op_gravada + r.op_exonerada
    assert sum((ln.impuesto for ln in r.lineas), D("0")) == r.igv
    assert sum((ln.total for ln in r.lineas), D("0")) == r.total


def test_ivap_aparte_del_igv():
    ivap = EntradaLinea(D("1"), D("100"), "GRAVADO", "IVAP", D("4"))
    r = calc([gravada(1, "100"), ivap])
    assert (r.op_gravada, r.igv, r.op_ivap, r.ivap) == (
        D("100.00"),
        D("18.00"),
        D("100.00"),
        D("4.00"),
    )
    assert r.total == D("222.00")


def test_dolares_se_convierten_a_soles_por_linea():
    r = calc([gravada(1, "100")], tipo_cambio=D("3.7500"))
    assert r.total == D("118.00")  # el comprobante sigue en su moneda
    assert r.lineas[0].costo_soles == D("375.00")


def test_flete_se_reparte_exacto_y_entra_al_costo():
    r = calc([gravada(1, "100"), gravada(1, "200"), gravada(1, "300")], flete=D("10.00"))
    partes = [ln.flete_asignado for ln in r.lineas]
    assert sum(partes) == D("10.00")
    assert partes == [D("1.67"), D("3.33"), D("5.00")]
    assert [ln.costo_soles for ln in r.lineas] == [D("101.67"), D("203.33"), D("305.00")]


def test_flete_no_cambia_los_totales_del_comprobante():
    sin = calc([gravada(1, "100")])
    con = calc([gravada(1, "100")], flete=D("15"))
    assert sin.total == con.total


def test_flete_fuera_del_costo():
    r = calc([gravada(1, "100")], flete=D("15"), flete_al_costo=False)
    assert r.lineas[0].flete_asignado == D("0")
    assert r.lineas[0].costo_soles == D("100.00")


def test_ajuste_de_redondeo_en_el_total_pero_no_en_el_costo():
    r = calc([gravada(1, "100")], ajuste_redondeo=D("-0.04"), igv_al_costo=True)
    assert r.total == D("117.96")
    assert r.lineas[0].costo_soles == D("118.00")


@pytest.mark.parametrize("ajuste", ["0.11", "-0.11", "0.001"])
def test_ajuste_invalido(ajuste):
    with pytest.raises(CompraInvalida):
        calc([gravada(1, "1")], ajuste_redondeo=D(ajuste))


def test_repartir_por_peso_suma_exacta():
    for monto, pesos in [
        ("0.01", ["1", "1", "1"]),
        ("100", ["1", "1", "1"]),
        ("99.99", ["33.33", "33.33", "33.33"]),
        ("7.77", ["0.01", "999.99", "5"]),
    ]:
        partes = repartir_por_peso(D(monto), [D(p) for p in pesos])
        assert sum(partes) == D(monto)
        assert all(p >= 0 for p in partes)


def test_repartir_sin_valor_falla():
    with pytest.raises(CompraInvalida):
        repartir_por_peso(D("5"), [D("0"), D("0")])


@pytest.mark.parametrize(
    "linea",
    [
        gravada(0, "1"),
        gravada(1, "-1"),
        EntradaLinea(D("1"), D("1"), "GRAVADO", "NINGUNO", D("0")),
        EntradaLinea(D("1"), D("1"), "EXONERADO", "IGV", D("18")),
        EntradaLinea(D("1"), D("1"), "GRAVADO", "IGV", D("101")),
        EntradaLinea(D("1"), D("1"), "OTRO", "NINGUNO", D("0")),
    ],
)
def test_lineas_invalidas(linea):
    with pytest.raises(CompraInvalida):
        calc([linea])


def test_sin_lineas_y_tipo_de_cambio():
    with pytest.raises(CompraInvalida):
        calc([])
    with pytest.raises(CompraInvalida):
        calc([gravada(1, "1")], tipo_cambio=D("0"))
    with pytest.raises(CompraInvalida):
        calc([gravada(1, "1")], flete=D("-1"))
