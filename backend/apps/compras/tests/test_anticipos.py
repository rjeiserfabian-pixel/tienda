"""Anticipos a proveedores: salida de dinero, saldo a favor, devolución, anulación y órdenes."""

import pytest

from apps.caja import servicios as caja
from apps.caja.exceptions import SaldoInsuficiente
from apps.caja.models import MovimientoCaja, Origen
from apps.compras.anticipos import (
    anular_anticipo,
    devolver_anticipo,
    registrar_anticipo,
    total_anticipado,
)
from apps.compras.anticipos import devuelto as devuelto_de
from apps.compras.creditos import aplicar_credito, creditos_disponibles, saldo_a_favor_total
from apps.compras.exceptions import AnticipoInvalido
from apps.compras.models import AnticipoProveedor, CreditoProveedor, CuotaCompra, OrdenCompra
from apps.compras.ordenes import LineaOrden, crear_orden, emitir_orden
from apps.compras.servicios import CuotasEntrada, LineaEntrada

from .conftest import dec

pytestmark = pytest.mark.django_db


def anticipar(compras, monto="100", **extra):
    datos = {
        "empresa": compras.empresa,
        "proveedor": compras.proveedor,
        "monto": dec(monto),
        "cuenta": compras.caja,
        "moneda": "PEN",
    }
    datos.update(extra)
    return registrar_anticipo(**datos)


@pytest.fixture
def con_fondos(compras):
    """La caja arranca con 1 000 para poder anticipar."""
    compras.caja.saldo_inicial = dec("1000")
    compras.caja.save()
    return compras


def orden_emitida(compras, total_base="100"):
    """Una orden de 10 × (total_base/10) + IGV, ya emitida."""
    orden = crear_orden(
        empresa=compras.empresa,
        proveedor=compras.proveedor,
        almacen=compras.almacen,
        fecha_emision=compras.entorno.hoy,
        lineas=[LineaOrden(compras.entorno.producto(), dec(10), dec(total_base) / 10)],
    )
    return emitir_orden(orden, puede_aprobar=True)


class TestRegistrar:
    def test_sale_el_dinero_y_nace_el_saldo_a_favor(self, con_fondos):
        a = anticipar(con_fondos, "300")
        assert (a.numero, a.codigo, a.estado) == (1, "ANT-000001", "EMITIDO")
        assert caja.saldo_de(con_fondos.caja) == dec("700")
        mov = MovimientoCaja.objects.get(origen_tipo=Origen.ANTICIPO_PROVEEDOR, origen_id=a.pk)
        assert (mov.tipo, mov.monto, mov.concepto.codigo) == (
            "EGRESO",
            dec("300"),
            "ANTICIPO_PROVEEDOR",
        )
        credito = a.credito
        assert (credito.monto, credito.disponible, credito.devolucion_id) == (
            dec("300"),
            dec("300"),
            None,
        )
        assert saldo_a_favor_total(con_fondos.proveedor.pk, "PEN") == dec("300")

    def test_el_correlativo_sigue(self, con_fondos):
        assert [anticipar(con_fondos).numero, anticipar(con_fondos).numero] == [1, 2]

    def test_el_monto_y_la_cuenta_se_validan(self, con_fondos):
        with pytest.raises(AnticipoInvalido, match="mayor que cero"):
            anticipar(con_fondos, "0")
        with pytest.raises(AnticipoInvalido, match="2 decimales"):
            anticipar(con_fondos, "10.123")
        with pytest.raises(AnticipoInvalido, match="misma moneda"):
            anticipar(con_fondos, cuenta=con_fondos.caja_usd)

    def test_sin_saldo_en_la_caja_no_se_anticipa_y_no_deja_nada(self, compras, settings):
        settings.CAJA_BLOQUEA_SALDO_NEGATIVO = True
        compras.caja.saldo_inicial = dec("50")
        compras.caja.save()
        with pytest.raises(SaldoInsuficiente):
            anticipar(compras, "300")
        assert not AnticipoProveedor.objects.exists()
        assert not CreditoProveedor.objects.exists()

    def test_el_anticipo_se_usa_como_saldo_a_favor_en_una_compra_a_credito(self, con_fondos):
        a = anticipar(con_fondos, "100")
        compra = con_fondos.comprar(
            [LineaEntrada(con_fondos.entorno.producto(), dec(10), dec(10))],
            forma_pago="CREDITO",
            cuotas=CuotasEntrada(2, con_fondos.entorno.hoy, con_fondos.mensual),
        )
        aplicar_credito(a.credito, compra, monto=dec("100"))
        cuotas = list(CuotaCompra.objects.filter(compra=compra).order_by("numero"))
        assert sum(c.pagado for c in cuotas) == dec("100")
        a.credito.refresh_from_db()
        assert a.credito.disponible == dec("0")
        assert creditos_disponibles(con_fondos.proveedor.pk, "PEN") == []


class TestConOrden:
    def test_se_liga_a_la_orden_y_suma_lo_anticipado(self, con_fondos):
        orden = orden_emitida(con_fondos)  # total 118
        anticipar(con_fondos, "40", orden=orden)
        anticipar(con_fondos, "50", orden=orden)
        assert total_anticipado(orden) == dec("90")

    def test_no_pasa_del_total_de_la_orden(self, con_fondos):
        orden = orden_emitida(con_fondos)  # total 118
        anticipar(con_fondos, "100", orden=orden)
        with pytest.raises(AnticipoInvalido, match="pasaría del total"):
            anticipar(con_fondos, "30", orden=orden)

    def test_la_orden_debe_estar_emitida(self, con_fondos):
        borrador = crear_orden(
            empresa=con_fondos.empresa,
            proveedor=con_fondos.proveedor,
            almacen=con_fondos.almacen,
            fecha_emision=con_fondos.entorno.hoy,
            lineas=[LineaOrden(con_fondos.entorno.producto(), dec(1), dec(10))],
        )
        with pytest.raises(AnticipoInvalido, match="emitida"):
            anticipar(con_fondos, "10", orden=borrador)

    def test_la_orden_debe_ser_del_mismo_proveedor_y_moneda(self, con_fondos):
        orden = orden_emitida(con_fondos)
        with pytest.raises(AnticipoInvalido, match="este proveedor"):
            anticipar(con_fondos, "10", orden=orden, proveedor=con_fondos.entorno.otro_proveedor)

    def test_un_anticipo_anulado_no_cuenta_para_el_tope(self, con_fondos):
        orden = orden_emitida(con_fondos)
        a = anticipar(con_fondos, "100", orden=orden)
        anular_anticipo(a, motivo="Error de monto")
        assert total_anticipado(orden) == dec("0")
        anticipar(con_fondos, "100", orden=orden)


class TestDevolver:
    def test_el_proveedor_devuelve_parte_y_baja_el_saldo(self, con_fondos):
        a = anticipar(con_fondos, "300")
        credito = devolver_anticipo(a, monto=dec("100"), cuenta=con_fondos.caja)
        assert (credito.usado, credito.disponible) == (dec("100"), dec("200"))
        assert caja.saldo_de(con_fondos.caja) == dec("800")  # 1000 - 300 + 100
        assert devuelto_de(a) == dec("100")
        mov = MovimientoCaja.objects.get(origen_tipo=Origen.DEVOLUCION_ANTICIPO, origen_id=a.pk)
        assert (mov.tipo, mov.concepto.codigo) == ("INGRESO", "DEVOLUCION_ANTICIPO")

    def test_no_devuelve_mas_de_lo_que_queda(self, con_fondos):
        a = anticipar(con_fondos, "300")
        devolver_anticipo(a, monto=dec("250"), cuenta=con_fondos.caja)
        with pytest.raises(AnticipoInvalido, match="solo quedan 50.00"):
            devolver_anticipo(a, monto=dec("60"), cuenta=con_fondos.caja)

    def test_la_fecha_no_puede_ser_anterior_al_anticipo(self, con_fondos):
        a = anticipar(con_fondos, "300")
        with pytest.raises(AnticipoInvalido, match="fecha"):
            devolver_anticipo(
                a, monto=dec("10"), cuenta=con_fondos.caja, fecha=con_fondos.entorno.hace(3)
            )


class TestAnular:
    def test_devuelve_el_dinero_a_la_caja_y_cancela_el_saldo(self, con_fondos):
        a = anticipar(con_fondos, "300")
        anular_anticipo(a, motivo="Se anticipó al proveedor equivocado")
        a.refresh_from_db()
        assert a.estado == "ANULADO"
        assert caja.saldo_de(con_fondos.caja) == dec("1000")
        a.credito.refresh_from_db()
        assert a.credito.anulado is True
        assert saldo_a_favor_total(con_fondos.proveedor.pk, "PEN") == dec("0")

    def test_pide_motivo(self, con_fondos):
        a = anticipar(con_fondos)
        with pytest.raises(AnticipoInvalido, match="motivo"):
            anular_anticipo(a, motivo=" ")

    def test_no_se_anula_si_ya_se_devolvio_o_se_uso_parte(self, con_fondos):
        a = anticipar(con_fondos, "300")
        devolver_anticipo(a, monto=dec("10"), cuenta=con_fondos.caja)
        with pytest.raises(AnticipoInvalido, match="Ya se usó o se devolvió"):
            anular_anticipo(a, motivo="Equivocado")

    def test_uno_anulado_no_se_devuelve_ni_se_anula_otra_vez(self, con_fondos):
        a = anticipar(con_fondos)
        anular_anticipo(a, motivo="Equivocado")
        with pytest.raises(AnticipoInvalido, match="anulado"):
            devolver_anticipo(a, monto=dec("10"), cuenta=con_fondos.caja)


def test_el_anticipo_no_cambia_el_estado_de_la_orden(con_fondos):
    orden = orden_emitida(con_fondos)
    anticipar(con_fondos, "50", orden=orden)
    orden.refresh_from_db()
    assert orden.estado == OrdenCompra.Estado.EMITIDA
