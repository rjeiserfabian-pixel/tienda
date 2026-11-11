"""Deuda y liquidación entre las dos empresas por sus ventas internas."""

from decimal import Decimal as D

import pytest

from apps.caja.models import Transferencia
from apps.caja.servicios import saldo_de
from apps.inventario.models import SaldoStock
from apps.ventas import liquidacion_interna as liquidacion
from apps.ventas import notas_credito
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import DeudaInterna, LiquidacionInterna, MotivoDeuda
from apps.ventas.servicios import anular_venta

from .test_venta_interna import vender_interna

pytestmark = pytest.mark.django_db


def org_id(tienda):
    return tienda.entorno.e.org_a.pk


def hacer(tienda, mixto, *, facturar_por=None, cantidad_b=2, cobro="354.00", medio=None):
    de_a, de_b = mixto
    return vender_interna(
        tienda,
        [tienda.linea(de_a, 1), tienda.linea(de_b, cantidad_b, empresa=tienda.b)],
        [tienda.cobro(medio or tienda.efectivo, cobro, referencia="OP-0001")],
        facturar_por=facturar_por or tienda.a,
    )


def pendiente(tienda):
    (p,) = liquidacion.pendientes(org_id(tienda))
    return p


class TestLibreta:
    def test_una_venta_interna_deja_lo_que_la_que_factura_le_debe_a_la_que_entrego(
        self, tienda, mixto
    ):
        hacer(tienda, mixto)

        (partida,) = DeudaInterna.objects.all()
        assert partida.empresa == tienda.a and partida.acreedora == tienda.b  # A le debe a B
        assert (partida.monto, partida.motivo) == (D("60.00"), MotivoDeuda.VENTA)
        assert partida.liquidacion is None
        p = pendiente(tienda)
        assert (p.pagadora, p.receptora, p.monto) == (tienda.a, tienda.b, D("60.00"))

    def test_una_devolucion_resta_y_una_anulacion_deja_todo_en_cero(self, tienda, mixto):
        _, de_b = mixto
        venta = hacer(tienda, mixto)
        linea = venta.comprobantes.get().lineas.get(producto=de_b)
        notas_credito.crear_nota_credito(
            venta.comprobantes.get(),
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(linea, D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )

        partidas = list(DeudaInterna.objects.order_by("id"))
        assert [(p.motivo, p.empresa_id, p.monto) for p in partidas] == [
            (MotivoDeuda.VENTA, tienda.a.pk, D("60.00")),
            (MotivoDeuda.DEVOLUCION, tienda.b.pk, D("30.00")),  # B le devuelve 30 a A
        ]
        assert pendiente(tienda).monto == D("30.00")  # neto: A todavía le debe 30 a B

    def test_anular_antes_de_liquidar_compensa_la_deuda(self, tienda, mixto):
        venta = hacer(tienda, mixto)

        anular_venta(venta, motivo="Error")

        assert [p.motivo for p in DeudaInterna.objects.order_by("id")] == [
            MotivoDeuda.VENTA,
            MotivoDeuda.ANULACION,
        ]
        assert pendiente(tienda).monto == D("0")


class TestLiquidar:
    def test_una_transferencia_entre_las_cajas_y_las_partidas_quedan_ligadas(self, tienda, mixto):
        hacer(tienda, mixto)

        liq = liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        assert (liq.empresa, liq.empresa_destino, liq.monto) == (tienda.a, tienda.b, D("60.00"))
        assert liq.numero == 1 and liq.transferencia is not None
        # A tenía los 354 del cliente; paga 60 a B desde su caja a la caja de B.
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("294.00")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("60.00")
        assert DeudaInterna.objects.filter(liquidacion=liq).count() == 1
        assert liquidacion.pendientes(org_id(tienda)) == []

    def test_compensa_lo_que_se_deben_las_dos_en_una_sola_transferencia(self, tienda, mixto):
        de_a, de_b = mixto
        hacer(tienda, mixto)  # A factura y le debe 60 a B
        vender_interna(  # B factura y le debe 50 a A (el audífono cuesta 50)
            tienda,
            [tienda.linea(de_b, 1, empresa=tienda.b), tienda.linea(de_a, 1)],
            [tienda.cobro(tienda.efectivo, "236.00")],
            facturar_por=tienda.b,
        )

        p = pendiente(tienda)
        assert (p.pagadora, p.monto) == (tienda.a, D("10.00"))
        assert (p.debe_pagadora, p.debe_receptora) == (D("60.00"), D("50.00"))
        liq = liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        assert liq.monto == D("10.00")
        assert Transferencia.objects.count() == 1
        assert DeudaInterna.objects.filter(liquidacion=liq).count() == 2

    def test_si_se_compensan_exactamente_no_hay_transferencia_pero_queda_constancia(self, tienda):
        p1 = tienda.producto("Mouse A", costo="50", precios={"PUBLICO": "100"})
        p2 = tienda.producto("Mouse B", costo="50", precios={"PUBLICO": "100"}, stock={tienda.b: 5})
        vender_interna(  # A factura, B entrega p2: A le debe 50 a B
            tienda,
            [tienda.linea(p1, 1), tienda.linea(p2, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "236.00")],
            facturar_por=tienda.a,
        )
        vender_interna(  # B factura, A entrega p1: B le debe 50 a A
            tienda,
            [tienda.linea(p2, 1, empresa=tienda.b), tienda.linea(p1, 1)],
            [tienda.cobro(tienda.efectivo, "236.00")],
            facturar_por=tienda.b,
        )

        assert pendiente(tienda).monto == D("0")
        liq = liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        assert liq.monto == D("0") and liq.transferencia is None
        assert not Transferencia.objects.exists()
        assert DeudaInterna.objects.filter(liquidacion=liq).count() == 2

    def test_una_devolucion_despues_de_liquidar_deja_una_deuda_en_sentido_contrario(
        self, tienda, mixto
    ):
        _, de_b = mixto
        venta = hacer(tienda, mixto)
        liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")
        linea = venta.comprobantes.get().lineas.get(producto=de_b)

        notas_credito.crear_nota_credito(
            venta.comprobantes.get(),
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(linea, D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )

        p = pendiente(tienda)
        assert (p.pagadora, p.receptora, p.monto) == (tienda.b, tienda.a, D("30.00"))

    def test_no_se_liquida_dos_veces_lo_mismo(self, tienda, mixto):
        hacer(tienda, mixto)
        liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        with pytest.raises(VentaInvalida, match="nada por liquidar"):
            liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

    def test_si_cambio_quien_debe_no_se_liquida_a_ciegas(self, tienda, mixto):
        hacer(tienda, mixto)

        with pytest.raises(VentaInvalida, match="Las cuentas cambiaron"):
            liquidacion.liquidar(pagadora=tienda.b, receptora=tienda.a, local="")

        assert not LiquidacionInterna.objects.exists()

    def test_sin_efectivo_en_la_caja_avisa_y_deja_elegir_otra_cuenta(self, tienda, mixto, settings):
        settings.CAJA_BLOQUEA_SALDO_NEGATIVO = True  # como en producción
        # El cliente pagó con Yape: la caja de A está en cero, el dinero está en su billetera.
        hacer(tienda, mixto, medio=tienda.yape)
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")

        with pytest.raises(VentaInvalida, match="También puede elegir otra cuenta"):
            liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")
        assert not LiquidacionInterna.objects.exists()

        liq = liquidacion.liquidar(
            pagadora=tienda.a,
            receptora=tienda.b,
            local="",
            cuenta_origen=tienda.billeteras[tienda.a.pk],
            cuenta_destino=tienda.billeteras[tienda.b.pk],
        )
        assert liq.monto == D("60.00")
        assert saldo_de(tienda.billeteras[tienda.b.pk]) == D("60.00")

    def test_la_cuenta_debe_ser_de_la_empresa_correspondiente(self, tienda, mixto):
        hacer(tienda, mixto)

        with pytest.raises(VentaInvalida, match="debe ser de"):
            liquidacion.liquidar(
                pagadora=tienda.a,
                receptora=tienda.b,
                local="",
                cuenta_origen=tienda.cajas[tienda.b.pk],
            )


class TestAnularLaLiquidacion:
    def test_vuelve_el_dinero_y_las_partidas_quedan_pendientes(self, tienda, mixto):
        hacer(tienda, mixto)
        liq = liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        liquidacion.anular_liquidacion(liq, motivo="Se liquidó por error")

        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("354.00")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("0")
        liq.refresh_from_db()
        assert liq.estado == "ANULADO"
        assert pendiente(tienda).monto == D("60.00")
        # Y se puede liquidar de nuevo, con el siguiente número.
        otra = liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")
        assert otra.numero == 2

    def test_el_stock_no_se_toca_al_liquidar(self, tienda, mixto):
        _, de_b = mixto
        hacer(tienda, mixto)
        antes = SaldoStock.objects.get(
            empresa=tienda.b, almacen=tienda.almacen(tienda.b), producto=de_b
        ).cantidad

        liquidacion.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        despues = SaldoStock.objects.get(
            empresa=tienda.b, almacen=tienda.almacen(tienda.b), producto=de_b
        ).cantidad
        assert antes == despues == D("8")
