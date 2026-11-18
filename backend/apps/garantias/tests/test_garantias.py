"""Alta y anulación automática de garantías al vender, anular y devolver."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.garantias.models import EstadoGarantia, Garantia
from apps.garantias.servicios import sumar_meses
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.ventas import notas_credito, servicios


def _vender(tienda, producto, cantidad=1, total="118.00", **extra):
    return tienda.vender(
        [tienda.linea(producto, cantidad)],
        [tienda.cobro(tienda.efectivo, total)],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
        **extra,
    )


def _celular_con_series(tienda, *series, meses=12):
    p = tienda.producto(
        "Celular",
        costo="500",
        precios={"PUBLICO": "800"},
        stock={},
        lleva_serie=True,
        garantia_meses=meses,
    )
    registrar_movimiento(
        empresa=tienda.a,
        almacen=tienda.almacen(tienda.a),
        tipo=TipoMovimiento.ENTRADA,
        origen="COMPRA",
        fecha=tienda.entorno.hoy,
        lineas=[LineaNueva(p, D(len(series)), D("500"), series=tuple(series))],
    )
    return p


class TestFechas:
    def test_suma_meses_sin_pasarse_de_fin_de_mes(self):
        assert sumar_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)
        assert sumar_meses(date(2026, 3, 15), 12) == date(2027, 3, 15)


class TestAlta:
    def test_producto_con_garantia_crea_una_por_la_linea(self, tienda):
        p = tienda.producto(garantia_meses=12)
        venta = _vender(tienda, p, 2, "236.00")
        (g,) = Garantia.objects.sin_ambito().all()
        comp = venta.comprobantes.get()
        assert (g.numero_serie, g.cantidad, g.meses) == ("", D("2"), 12)
        assert g.fecha_inicio == comp.fecha
        assert g.vence_el == sumar_meses(comp.fecha, 12)
        assert g.comprobante == comp and g.cliente_documento == "20100000017"
        assert g.vigente() or g.vence_el < date.today()

    def test_producto_sin_garantia_no_crea_nada(self, tienda):
        _vender(tienda, tienda.producto())
        assert not Garantia.objects.sin_ambito().exists()

    def test_con_series_hay_una_garantia_por_unidad(self, tienda):
        p = _celular_con_series(tienda, "IMEI-1", "IMEI-2", "IMEI-3")
        tienda.vender(
            [tienda.linea(p, 2, series=("IMEI-1", "IMEI-3"))],
            [tienda.cobro(tienda.efectivo, "1888.00")],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
        )
        series = sorted(Garantia.objects.sin_ambito().values_list("numero_serie", flat=True))
        assert series == ["IMEI-1", "IMEI-3"]

    def test_los_meses_quedan_copiados(self, tienda):
        p = tienda.producto(garantia_meses=6)
        _vender(tienda, p)
        p.garantia_meses = 24
        p.save()
        assert Garantia.objects.sin_ambito().get().meses == 6


class TestAnulacion:
    def test_anular_el_comprobante_anula_las_garantias(self, tienda):
        p = tienda.producto(garantia_meses=12)
        venta = _vender(tienda, p)
        servicios.anular_comprobante(venta.comprobantes.get(), motivo="Error de digitación")
        g = Garantia.objects.sin_ambito().get()
        assert g.estado == EstadoGarantia.ANULADA and g.anulada_en is not None
        assert "Error de digitación" in g.motivo_anulacion
        assert not g.vigente()

    def test_nota_de_credito_parcial_descuenta_cantidad(self, tienda):
        p = tienda.producto(garantia_meses=12)
        venta = _vender(tienda, p, 2, "236.00")
        comp = venta.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        g = Garantia.objects.sin_ambito().get()
        assert (g.estado, g.cantidad) == (EstadoGarantia.ACTIVA, D("1.000"))

    def test_nota_de_credito_total_anula_la_garantia(self, tienda):
        p = tienda.producto(garantia_meses=12)
        venta = _vender(tienda, p)
        comp = venta.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        assert Garantia.objects.sin_ambito().get().estado == EstadoGarantia.ANULADA

    def test_devolver_una_serie_anula_solo_esa_unidad(self, tienda):
        p = _celular_con_series(tienda, "IMEI-1", "IMEI-2")
        venta = tienda.vender(
            [tienda.linea(p, 2, series=("IMEI-1", "IMEI-2"))],
            [tienda.cobro(tienda.efectivo, "1888.00")],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
        )
        comp = venta.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"), ("IMEI-2",))],
            reembolsos=[tienda.cobro(tienda.efectivo, "944.00")],
        )
        estados = dict(Garantia.objects.sin_ambito().values_list("numero_serie", "estado"))
        assert estados == {"IMEI-1": EstadoGarantia.ACTIVA, "IMEI-2": EstadoGarantia.ANULADA}


@pytest.mark.parametrize("meses", [0, None])
def test_cero_o_vacio_no_es_garantia(tienda, meses):
    _vender(tienda, tienda.producto(garantia_meses=meses))
    assert not Garantia.objects.sin_ambito().exists()
