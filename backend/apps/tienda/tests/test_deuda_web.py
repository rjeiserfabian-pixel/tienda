"""Deuda entre empresas por pedidos mixtos de la tienda: libreta, liquidación, asiento y reversa."""

# ruff: noqa: F811

from decimal import Decimal

import pytest

from apps.caja.servicios import saldo_de
from apps.mantenimiento.models import CuentaFinanciera
from apps.tienda import deuda_web
from apps.tienda.models import DeudaCobroTienda
from apps.ventas import liquidacion_interna
from apps.ventas import servicios as ventas_srv
from apps.ventas.cuentas_web import CUENTA_COBRA, CUENTA_PUENTE, LOCAL_WEB
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import (
    DeudaInterna,
    LiquidacionInterna,
    OrigenDeuda,
    TransferenciaPuente,
    Venta,
)

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_pagar import (  # noqa: F401
    TestPedidoMixto,
    cobra,
    culqi_falso,
    pagar_pedido,
)
from .test_pedidos import contexto, pedido_de_prueba, vende  # noqa: F401

pytestmark = pytest.mark.django_db


def cuenta(empresa, nombre):
    return CuentaFinanciera.objects.sin_ambito().get(empresa=empresa, nombre=nombre)


@pytest.fixture
def mixto_pagado(cobra, culqi_falso):
    """Un pedido con productos de las dos empresas, ya pagado: la empresa 1 cobró lo de la 2."""
    a, b, c, pedido = TestPedidoMixto()._mixto(cobra)
    assert pagar_pedido(c).status_code == 200
    contexto(cobra)
    e = cobra.e
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.e2,
        nombre="BCP empresa 2",
        tipo=CuentaFinanciera.Tipo.BANCO,
        moneda=CuentaFinanciera.Moneda.PEN,
    )
    deuda = DeudaCobroTienda.objects.sin_ambito().get()
    return cobra, deuda, banco


class TestLibreta:
    def test_el_pago_mixto_deja_la_partida_en_la_libreta_de_liquidacion(self, mixto_pagado):
        cobra, deuda, _ = mixto_pagado
        e = cobra.e
        partida = DeudaInterna.objects.sin_ambito().get()
        assert partida.origen == OrigenDeuda.COBRO_TIENDA and partida.origen_id == deuda.pk
        assert partida.local == LOCAL_WEB and partida.venta_interna_id is None
        assert (partida.empresa_id, partida.acreedora_id) == (e.e1.pk, e.e2.pk)  # cobró → debe
        assert partida.monto == deuda.monto and partida.referencia == "Pedido T-000001"
        (grupo,) = liquidacion_interna.pendientes(cobra.org.pk)
        assert grupo.local == LOCAL_WEB and grupo.monto == deuda.monto
        assert (grupo.pagadora.pk, grupo.receptora.pk) == (e.e1.pk, e.e2.pk)

    def test_un_pedido_de_una_sola_empresa_no_deja_deuda(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        assert pagar_pedido(c).status_code == 200
        assert not DeudaInterna.objects.sin_ambito().exists()

    def test_la_partida_no_se_duplica(self, mixto_pagado):
        cobra, deuda, _ = mixto_pagado
        e = cobra.e
        otra = liquidacion_interna.partida_de_cobro_web(
            cobro_id=deuda.pk, pedido="T-000001", cobra=e.e1, otra=e.e2, monto=deuda.monto
        )
        assert otra is None and DeudaInterna.objects.sin_ambito().count() == 1


class TestLiquidar:
    def _saldos(self, cobra, banco):
        e = cobra.e
        return {
            "culqi1": saldo_de(cuenta(e.e1, CUENTA_COBRA)),
            "puente2": saldo_de(cuenta(e.e2, CUENTA_PUENTE)),
            "banco2": saldo_de(banco),
        }

    def test_liquidar_deja_la_puente_en_cero_y_el_banco_con_lo_cobrado(self, mixto_pagado):
        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        antes = self._saldos(cobra, banco)
        assert antes["puente2"] == deuda.monto and antes["banco2"] == 0
        liquidacion = liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        assert liquidacion.monto == deuda.monto
        despues = self._saldos(cobra, banco)
        assert despues["puente2"] == 0  # sin saldo virtual permanente
        assert despues["banco2"] == deuda.monto  # la otra empresa recibió su dinero
        assert despues["culqi1"] == antes["culqi1"]  # la que cobró conserva solo lo suyo
        # dos transferencias: el reconocimiento previo y el pago neto; la partida queda ligada
        assert TransferenciaPuente.objects.filter(liquidacion=liquidacion).count() == 1
        assert DeudaInterna.objects.sin_ambito().get().liquidacion_id == liquidacion.pk
        assert liquidacion_interna.pendientes(cobra.org.pk) == []

    def test_no_se_liquida_dos_veces(self, mixto_pagado):
        cobra, _, banco = mixto_pagado
        e = cobra.e
        liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        with pytest.raises(VentaInvalida, match="nada por liquidar"):
            liquidacion_interna.liquidar(
                pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
            )

    def test_anular_la_liquidacion_devuelve_todo_a_como_estaba(self, mixto_pagado):
        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        antes = self._saldos(cobra, banco)
        liquidacion = liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        liquidacion_interna.anular_liquidacion(
            LiquidacionInterna.objects.sin_ambito().get(pk=liquidacion.pk), motivo="error de prueba"
        )
        assert self._saldos(cobra, banco) == antes
        assert DeudaInterna.objects.sin_ambito().get().liquidacion_id is None
        (grupo,) = liquidacion_interna.pendientes(cobra.org.pk)
        assert grupo.monto == deuda.monto

    def test_sin_banco_elegido_pide_elegirlo(self, mixto_pagado):
        cobra, _, banco = mixto_pagado
        CuentaFinanciera.objects.sin_ambito().filter(pk=banco.pk).update(estado="INACTIVO")
        e = cobra.e
        with pytest.raises(VentaInvalida, match="Elija las cuentas"):
            liquidacion_interna.liquidar(pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB)

    def test_se_compensa_con_una_deuda_contraria_del_mismo_origen(self, mixto_pagado):
        """Si la otra empresa también cobró algo de la primera, se liquida solo la diferencia."""
        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        liquidacion_interna.partida_de_cobro_web(
            cobro_id=999, pedido="T-000099", cobra=e.e2, otra=e.e1, monto=Decimal("10.00")
        )
        (grupo,) = liquidacion_interna.pendientes(cobra.org.pk)
        assert grupo.monto == deuda.monto - Decimal("10.00")
        assert grupo.debe_receptora == Decimal("10.00")


class TestApi:
    def test_la_pantalla_ve_el_origen_y_cuentas_propuestas(self, mixto_pagado, nuevo_usuario):
        from apps.seguridad.tests.conftest import cliente_de

        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        nuevo_usuario(cobra.org, "super_liq", [e.e1, e.e2], [("SUPERADMIN", None)])
        c = cliente_de("super_liq")
        r = c.get(f"/api/v1/ventas/liquidaciones-internas/pendientes/?empresa={e.e1.pk}")
        assert r.status_code == 200, r.content
        (g,) = r.json()
        assert g["local"] == LOCAL_WEB and g["origen"] == "COBRO_TIENDA"
        assert g["cuenta_origen"]["nombre"] == CUENTA_COBRA
        assert g["cuenta_destino"]["id"] == banco.pk  # el primer banco de la receptora
        (p,) = g["partidas"]
        assert p["origen"] == "COBRO_TIENDA" and p["referencia"] == "Pedido T-000001"
        assert p["venta_interna"] is None and p["venta"] is None


class TestEstadoYReversa:
    def test_estado_pendiente_y_liquidada(self, mixto_pagado):
        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        assert deuda_web.estado_de(deuda)["estado"] == deuda_web.PENDIENTE
        liquidacion = liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        estado = deuda_web.estado_de(deuda)
        assert estado["estado"] == deuda_web.LIQUIDADA
        assert estado["liquidacion_numero"] == liquidacion.numero

    def test_revertir_antes_de_liquidar_anula_la_partida(self, mixto_pagado):
        from apps.tienda.models import PedidoTienda

        cobra, deuda, _ = mixto_pagado
        pedido = PedidoTienda.objects.sin_ambito().get()
        resumen = deuda_web.revertir_deuda_de_pedido(pedido, motivo="reembolso")
        assert [r["resultado"] for r in resumen] == [deuda_web.ANULADA]
        assert liquidacion_interna.pendientes(cobra.org.pk) == []
        deuda.refresh_from_db()
        assert deuda.revertida_en is not None
        assert deuda_web.estado_de(deuda)["estado"] == deuda_web.ANULADA
        assert deuda_web.revertir_deuda_de_pedido(pedido) == []  # idempotente

    def test_revertir_despues_de_liquidar_deja_una_partida_contraria(self, mixto_pagado):
        from apps.tienda.models import PedidoTienda

        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        pedido = PedidoTienda.objects.sin_ambito().get()
        resumen = deuda_web.revertir_deuda_de_pedido(pedido)
        assert [r["resultado"] for r in resumen] == [deuda_web.REVERSA_PENDIENTE]
        (grupo,) = liquidacion_interna.pendientes(cobra.org.pk)
        # ahora es la OTRA empresa la que devuelve lo que ya había recibido
        assert (grupo.pagadora.pk, grupo.receptora.pk) == (e.e2.pk, e.e1.pk)
        assert grupo.monto == deuda.monto
        assert deuda_web.estado_de(deuda)["estado"] == deuda_web.REVERSA_PENDIENTE

    def test_la_reversa_liquidada_cuadra_las_cuentas(self, mixto_pagado):
        from apps.tienda.models import PedidoTienda

        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        pedido = PedidoTienda.objects.sin_ambito().get()
        # El reembolso anula la venta (se revierten sus cobros) y revierte la deuda entre empresas.
        ventas_srv.anular_venta(
            Venta.objects.sin_ambito().get(pk=pedido.venta_id), motivo="reembolso"
        )
        assert saldo_de(cuenta(e.e2, CUENTA_PUENTE)) == -deuda.monto  # la puente quedó al revés
        deuda_web.revertir_deuda_de_pedido(pedido)
        banco1 = CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.e1,
            nombre="BCP empresa 1",
            tipo=CuentaFinanciera.Tipo.BANCO,
            moneda=CuentaFinanciera.Moneda.PEN,
        )
        liquidacion_interna.liquidar(
            pagadora=e.e2,
            receptora=e.e1,
            local=LOCAL_WEB,
            cuenta_origen=banco,
            cuenta_destino=banco1,
        )
        # la otra empresa devolvió lo recibido y su cuenta puente no quedó con saldo
        assert saldo_de(banco) == 0
        assert saldo_de(cuenta(e.e2, CUENTA_PUENTE)) == 0
        assert saldo_de(banco1) == deuda.monto

    def test_el_detalle_del_pedido_muestra_el_estado_de_la_deuda(self, mixto_pagado, nuevo_usuario):
        from apps.seguridad.tests.conftest import cliente_de

        cobra, deuda, _ = mixto_pagado
        nuevo_usuario(cobra.org, "super_ped", [cobra.e.e1, cobra.e.e2], [("SUPERADMIN", None)])
        r = cliente_de("super_ped").get("/api/v1/tienda/admin/pedidos/T-000001/")
        assert r.status_code == 200, r.content
        (d,) = r.json()["deudas_entre_empresas"]
        assert d["estado"] == "PENDIENTE" and d["estado_texto"] == "Por liquidar"
        assert d["liquidada"] is False and d["monto"] == format(deuda.monto, "f")
