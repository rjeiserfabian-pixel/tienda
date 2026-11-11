"""Una salida no puede dejar en negativo una caja de efectivo (ni un banco sin sobregiro)."""

import pytest

from apps.caja import servicios
from apps.caja.exceptions import SaldoInsuficiente
from apps.caja.models import MovimientoCaja, Origen
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec
from .test_servicios import EGRESO, INGRESO, mover

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def bloqueo_activo(settings):
    settings.CAJA_BLOQUEA_SALDO_NEGATIVO = True


class TestCajaDeEfectivo:
    def test_sin_saldo_la_salida_se_rechaza(self, compras, conceptos):
        with pytest.raises(SaldoInsuficiente, match="tiene S/ 0.00"):
            mover(compras, conceptos, EGRESO, "10")
        assert MovimientoCaja.objects.sin_ambito().count() == 0

    def test_con_saldo_alcanza_hasta_el_ultimo_centimo(self, compras, conceptos):
        mover(compras, conceptos, INGRESO, "100")
        mover(compras, conceptos, EGRESO, "100")
        assert servicios.saldo_de(compras.caja) == dec("0")
        with pytest.raises(SaldoInsuficiente):
            mover(compras, conceptos, EGRESO, "0.01")

    def test_el_saldo_inicial_cuenta(self, compras, conceptos):
        compras.caja.saldo_inicial = dec("50")
        compras.caja.save()
        mover(compras, conceptos, EGRESO, "50")
        with pytest.raises(SaldoInsuficiente):
            mover(compras, conceptos, EGRESO, "1")

    def test_un_movimiento_anulado_no_da_saldo(self, compras, conceptos):
        ingreso = mover(compras, conceptos, INGRESO, "100")
        servicios.anular_movimiento(ingreso, motivo="Error de digitación")
        with pytest.raises(SaldoInsuficiente):
            mover(compras, conceptos, EGRESO, "10")

    def test_el_mensaje_dice_cuanto_hay_y_que_hacer(self, compras, conceptos):
        mover(compras, conceptos, INGRESO, "40")
        with pytest.raises(SaldoInsuficiente) as error:
            mover(compras, conceptos, EGRESO, "75.50")
        texto = str(error.value)
        assert "S/ 40.00" in texto and "S/ 75.50" in texto and "Transferencias" in texto

    def test_lo_que_ya_paso_fuera_del_sistema_se_asienta(self, compras, conceptos):
        # El conteo del cajón (faltante) es un hecho: negarlo no devuelve el dinero.
        movimiento = mover(compras, conceptos, EGRESO, "10", origen_tipo=Origen.ARQUEO)
        assert movimiento.estado == "EMITIDO"
        assert servicios.saldo_de(compras.caja) == dec("-10")

    def test_un_ingreso_nunca_se_bloquea(self, compras, conceptos):
        assert mover(compras, conceptos, INGRESO, "10").pk


class TestBancoYBilletera:
    @pytest.fixture
    def banco(self, compras):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=compras.empresa, nombre="BCP soles", tipo="BANCO", banco="BCP"
        )

    def _salida(self, compras, conceptos, banco):
        return servicios.registrar_movimiento(
            empresa=compras.empresa,
            cuenta=banco,
            tipo=EGRESO,
            monto=dec("25"),
            concepto=conceptos["GASTOS_VARIOS"],
        )

    def test_sin_sobregiro_se_bloquea(self, compras, conceptos, banco):
        with pytest.raises(SaldoInsuficiente):
            self._salida(compras, conceptos, banco)

    def test_con_sobregiro_pasa_y_queda_en_negativo(self, compras, conceptos, banco):
        banco.permite_saldo_negativo = True
        banco.save()
        self._salida(compras, conceptos, banco)
        assert servicios.saldo_de(banco) == dec("-25")

    def test_una_caja_de_efectivo_no_admite_sobregiro(self, compras):
        from django.core.exceptions import ValidationError

        compras.caja.permite_saldo_negativo = True
        with pytest.raises(ValidationError):
            compras.caja.full_clean()


class TestPagadoPorElSocio:
    """El socio pagó de su bolsillo: su aporte entra a la caja y el pago lo gasta."""

    @staticmethod
    def _libro(origen):
        return list(MovimientoCaja.objects.filter(origen_tipo=origen).order_by("id"))

    def test_sin_el_aporte_la_compra_no_se_registra(self, compras):
        from apps.compras.servicios import LineaEntrada, PagoEntrada

        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        with pytest.raises(SaldoInsuficiente):
            compras.comprar(
                [linea], pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"))]
            )
        assert servicios.saldo_de(compras.caja) == dec("0")

    def test_con_el_aporte_la_caja_queda_en_cero(self, compras):
        from apps.compras.servicios import LineaEntrada, PagoEntrada

        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        compras.comprar(
            [linea],
            pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"), aporte_socio=True)],
        )
        [aporte] = self._libro(Origen.APORTE_PAGO_COMPRA)
        [pago] = self._libro(Origen.PAGO_COMPRA)
        assert (aporte.tipo, aporte.monto, aporte.concepto.codigo) == (
            "INGRESO",
            dec("118"),
            "APORTE_CAPITAL",
        )
        assert pago.tipo == "EGRESO" and pago.id > aporte.id
        assert servicios.saldo_de(compras.caja) == dec("0")

    def test_anular_la_compra_anula_tambien_el_aporte(self, compras):
        from apps.compras.servicios import LineaEntrada, PagoEntrada, anular_compra

        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        compra = compras.comprar(
            [linea],
            pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"), aporte_socio=True)],
        )
        anular_compra(compra, motivo="Se registró dos veces")
        assert {m.estado for m in self._libro(Origen.APORTE_PAGO_COMPRA)} == {"ANULADO"}
        assert {m.estado for m in self._libro(Origen.PAGO_COMPRA)} == {"ANULADO"}
        assert servicios.saldo_de(compras.caja) == dec("0")

    def test_pago_de_cuotas_con_aporte(self, compras):
        from apps.compras.cuentas_por_pagar import registrar_pagos
        from apps.compras.servicios import CuotasEntrada, LineaEntrada, PagoEntrada

        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        compra = compras.comprar(
            [linea],
            forma_pago="CREDITO",
            cuotas=CuotasEntrada(2, compras.entorno.hoy, compras.mensual),
        )
        with pytest.raises(SaldoInsuficiente):
            registrar_pagos(compra, pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("30"))])
        registrar_pagos(
            compra,
            pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("30"), aporte_socio=True)],
        )
        assert servicios.saldo_de(compras.caja) == dec("0")
