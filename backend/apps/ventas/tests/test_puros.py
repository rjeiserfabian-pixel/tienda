"""Reglas de precio mínimo, IGV y reparto de cobros: cálculo puro, sin base de datos."""

from decimal import Decimal as D

import pytest

from apps.compras.calculo import EXONERADO, GRAVADO, IGV, INAFECTO, NINGUNO, EntradaLinea
from apps.ventas import calculo, cobros, precios
from apps.ventas.exceptions import VentaInvalida


class TestPrecioMinimo:
    def test_es_el_menor_entre_descuento_y_tecnico(self):
        minimo = precios.precio_minimo(
            precio_lista=D("100"), descuento=D("90"), tecnico=D("80"), costo=D("50")
        )
        assert minimo == D("80")

    def test_con_una_sola_lista_de_piso(self):
        assert precios.precio_minimo(
            precio_lista=D("100"), descuento=D("90"), tecnico=None, costo=D("50")
        ) == D("90")

    def test_sin_listas_el_piso_es_el_costo(self):
        assert precios.precio_minimo(
            precio_lista=D("100"), descuento=None, tecnico=None, costo=D("60")
        ) == D("60")

    def test_nunca_baja_del_costo(self):
        # El descuento configurado (70) está bajo el costo (75): manda el costo.
        assert precios.precio_minimo(
            precio_lista=D("100"), descuento=D("70"), tecnico=None, costo=D("75")
        ) == D("75")

    def test_sin_listas_ni_costo_no_hay_descuento(self):
        assert precios.precio_minimo(
            precio_lista=D("100"), descuento=None, tecnico=None, costo=D("0")
        ) == D("100")

    def test_un_precio_en_cero_no_cuenta(self):
        assert precios.precio_minimo(
            precio_lista=D("100"), descuento=D("0"), tecnico=D("85"), costo=D("50")
        ) == D("85")

    def test_nunca_pasa_del_precio_de_lista(self):
        assert precios.precio_minimo(
            precio_lista=D("100"), descuento=None, tecnico=None, costo=D("130")
        ) == D("100")

    def test_con_permiso_el_limite_es_el_costo(self):
        assert precios.precio_absoluto(precio_lista=D("100"), costo=D("60")) == D("60")
        # Si la propia lista está bajo el costo (dato mal cargado), la lista siempre se vende.
        assert precios.precio_absoluto(precio_lista=D("40"), costo=D("60")) == D("40")


class TestEvaluarPrecio:
    @pytest.mark.parametrize(
        ("precio", "esperado"),
        [
            (D("120"), precios.OK),  # subir es libre
            (D("100"), precios.OK),
            (D("80"), precios.OK),  # justo el mínimo
            (D("79.99"), precios.BAJO_MINIMO),
            (D("60"), precios.BAJO_MINIMO),  # justo el costo: con permiso
            (D("59.99"), precios.BAJO_COSTO),
        ],
    )
    def test_casos(self, precio, esperado):
        assert precios.evaluar_precio(precio, minimo=D("80"), absoluto=D("60")) == esperado


class TestMoneda:
    def test_en_soles_no_cambia(self):
        assert precios.a_moneda(D("100"), "PEN", D("3.75")) == D("100")

    def test_en_dolares_divide_por_el_tipo_de_cambio(self):
        assert precios.a_moneda(D("375"), "USD", D("3.75")) == D("100.000000")


def _linea(cantidad, precio, grupo=GRAVADO):
    impuesto = IGV if grupo == GRAVADO else NINGUNO
    tasa = D("18") if grupo == GRAVADO else D("0")
    return EntradaLinea(D(cantidad), D(precio), grupo, impuesto, tasa)


class TestCalculo:
    def test_el_igv_se_suma_al_precio_de_lista(self):
        t = calculo.calcular_comprobante([_linea("2", "100")])
        assert (t.op_gravada, t.igv, t.total) == (D("200.00"), D("36.00"), D("236.00"))

    def test_mezcla_de_afectaciones(self):
        t = calculo.calcular_comprobante(
            [_linea("1", "100"), _linea("1", "50", EXONERADO), _linea("1", "10", INAFECTO)]
        )
        assert (t.op_gravada, t.op_exonerada, t.op_inafecta) == (D("100"), D("50"), D("10"))
        assert (t.igv, t.total) == (D("18.00"), D("178.00"))

    def test_las_lineas_suman_el_total_sin_perder_centimos(self):
        lineas = [_linea("3", "0.33"), _linea("7", "1.17"), _linea("1", "9.99")]
        t = calculo.calcular_comprobante(lineas)
        assert sum(ln.total for ln in t.lineas) == t.total
        assert sum(ln.igv for ln in t.lineas) == t.igv
        assert t.total == t.op_gravada + t.igv

    def test_rechaza_cantidad_cero_y_afectacion_incoherente(self):
        with pytest.raises(VentaInvalida):
            calculo.calcular_comprobante([_linea("0", "10")])
        with pytest.raises(VentaInvalida):
            calculo.calcular_comprobante([EntradaLinea(D("1"), D("10"), GRAVADO, NINGUNO, D("0"))])
        with pytest.raises(VentaInvalida):
            calculo.calcular_comprobante([])


class TestCobros:
    def test_una_empresa_un_cobro(self):
        assert cobros.repartir_cobros([D("100")], [D("100")]) == [cobros.Fragmento(0, 0, D("100"))]

    def test_un_cobro_se_parte_entre_dos_comprobantes(self):
        partes = cobros.repartir_cobros([D("118"), D("59")], [D("177")])
        assert [(f.comprobante, f.monto) for f in partes] == [(0, D("118")), (1, D("59"))]

    def test_varios_cobros_llenan_en_orden(self):
        partes = cobros.repartir_cobros([D("100"), D("50")], [D("60"), D("40"), D("50")])
        assert [(f.comprobante, f.cobro, f.monto) for f in partes] == [
            (0, 0, D("60")),
            (0, 1, D("40")),
            (1, 2, D("50")),
        ]

    def test_un_cobro_que_cruza_la_frontera(self):
        partes = cobros.repartir_cobros([D("100"), D("50")], [D("120"), D("30")])
        assert [(f.comprobante, f.cobro, f.monto) for f in partes] == [
            (0, 0, D("100")),
            (1, 0, D("20")),
            (1, 1, D("30")),
        ]

    def test_cada_comprobante_cobra_exactamente_su_total(self):
        totales = [D("118.07"), D("59.93")]
        partes = cobros.repartir_cobros(totales, [D("100.00"), D("78.00")])
        for posicion, total in enumerate(totales):
            assert sum(f.monto for f in partes if f.comprobante == posicion) == total

    def test_los_cobros_deben_sumar_el_total(self):
        with pytest.raises(VentaInvalida):
            cobros.repartir_cobros([D("100")], [D("99.99")])

    def test_vuelto(self):
        assert cobros.calcular_vuelto(D("73.50"), D("100")) == D("26.50")
        assert cobros.calcular_vuelto(D("50"), None) == D("0")
        with pytest.raises(VentaInvalida):
            cobros.calcular_vuelto(D("50"), D("49.99"))
