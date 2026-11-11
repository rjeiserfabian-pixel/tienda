"""Cheques: registro, depósito, cobro (con su transferencia), rechazo, anulación y avisos."""

from datetime import timedelta

import pytest

from apps.caja import cheques, servicios
from apps.caja.exceptions import ChequeInvalido, ChequeNoModificable
from apps.caja.models import Cheque, MovimientoCaja, Origen
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec

pytestmark = pytest.mark.django_db

Estado = Cheque.Estado


@pytest.fixture
def cuentas(compras):
    """Un banco, una cuenta de cheques con 1 000 por cobrar y un banco en dólares."""
    e = compras.entorno

    def nueva(nombre, tipo="BANCO", moneda="PEN", saldo="0"):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.e1, nombre=nombre, tipo=tipo, moneda=moneda, saldo_inicial=dec(saldo)
        )

    return {
        "bcp": nueva("BCP soles"),
        "cheques": nueva("Cheques por cobrar", tipo="BILLETERA", saldo="1000"),
        "usd": nueva("BCP dólares", moneda="USD"),
        "caja": compras.caja,
    }


def recibir(compras, cuentas, importe="300", **extra):
    datos = {
        "empresa": compras.empresa,
        "tipo": "RECIBIDO",
        "numero": "000123",
        "banco": "BBVA",
        "importe": dec(importe),
        "fecha_emision": compras.entorno.hoy,
        "tercero": "Mago SAC",
        "cuenta_cartera": cuentas["cheques"],
    }
    datos.update(extra)
    return cheques.registrar_cheque(**datos)


def girar(compras, cuentas, importe="500", **extra):
    datos = {
        "empresa": compras.empresa,
        "tipo": "EMITIDO",
        "numero": "7788",
        "banco": "BCP",
        "importe": dec(importe),
        "fecha_emision": compras.entorno.hoy,
        "proveedor": compras.proveedor,
        "cuenta": cuentas["bcp"],
    }
    datos.update(extra)
    return cheques.registrar_cheque(**datos)


class TestRegistrar:
    def test_un_recibido_queda_en_cartera_y_un_emitido_girado(self, compras, cuentas):
        assert recibir(compras, cuentas).estado == Estado.EN_CARTERA
        girado = girar(compras, cuentas)
        assert girado.estado == Estado.GIRADO
        assert girado.tercero == compras.proveedor.nombre  # toma el nombre del proveedor

    def test_no_se_repite_el_mismo_cheque(self, compras, cuentas):
        recibir(compras, cuentas)
        with pytest.raises(ChequeInvalido, match="Ya hay un cheque"):
            recibir(compras, cuentas)

    def test_uno_anulado_deja_registrar_otro_con_el_mismo_numero(self, compras, cuentas):
        c = recibir(compras, cuentas)
        cheques.anular(c, motivo="Lo devolvimos")
        assert recibir(compras, cuentas).estado == Estado.EN_CARTERA

    def test_valida_importe_fechas_y_cuentas(self, compras, cuentas):
        with pytest.raises(ChequeInvalido, match="mayor que cero"):
            recibir(compras, cuentas, importe="0")
        with pytest.raises(ChequeInvalido, match="futura"):
            recibir(compras, cuentas, fecha_emision=compras.entorno.hoy + timedelta(days=1))
        with pytest.raises(ChequeInvalido, match="anterior"):
            recibir(compras, cuentas, fecha_pago=compras.entorno.hoy - timedelta(days=1))
        with pytest.raises(ChequeInvalido, match="misma moneda"):
            girar(compras, cuentas, cuenta=cuentas["usd"])
        with pytest.raises(ChequeInvalido, match="cuenta de banco"):
            girar(compras, cuentas, cuenta=cuentas["caja"])

    def test_un_recibido_no_es_de_un_proveedor_ni_un_girado_de_un_cliente(self, compras, cuentas):
        with pytest.raises(ChequeInvalido, match="no de un proveedor"):
            recibir(compras, cuentas, proveedor=compras.proveedor)
        with pytest.raises(ChequeInvalido, match="no a un cliente"):
            girar(compras, cuentas, cliente=compras.entorno.cliente)

    def test_sin_nombre_del_tercero_se_rechaza(self, compras, cuentas):
        with pytest.raises(ChequeInvalido, match="Indique quién"):
            recibir(compras, cuentas, tercero="")


class TestRecibido:
    def test_depositar_y_cobrar_pasa_el_dinero_de_la_cuenta_de_cheques_al_banco(
        self, compras, cuentas
    ):
        c = recibir(compras, cuentas, importe="300")
        cheques.depositar(c, cuenta=cuentas["bcp"])
        c.refresh_from_db()
        assert (c.estado, c.cuenta_id) == (Estado.DEPOSITADO, cuentas["bcp"].pk)
        assert servicios.saldo_de(cuentas["cheques"]) == dec("1000")  # aún nada se movió
        cheques.cobrar(c)
        c.refresh_from_db()
        assert (c.estado, c.cobrado_en) == (Estado.COBRADO, compras.entorno.hoy)
        assert servicios.saldo_de(cuentas["cheques"]) == dec("700")
        assert servicios.saldo_de(cuentas["bcp"]) == dec("300")
        assert c.transferencia_id is not None

    def test_se_puede_cobrar_directo_desde_cartera_indicando_el_banco(self, compras, cuentas):
        c = recibir(compras, cuentas)
        cheques.cobrar(c, cuenta=cuentas["bcp"])
        c.refresh_from_db()
        assert c.estado == Estado.COBRADO and servicios.saldo_de(cuentas["bcp"]) == dec("300")

    def test_sin_banco_o_sin_cuenta_de_cheques_no_se_cobra(self, compras, cuentas):
        c = recibir(compras, cuentas)
        with pytest.raises(ChequeInvalido, match="banco donde se cobró"):
            cheques.cobrar(c)
        sin_cartera = recibir(compras, cuentas, numero="9", cuenta_cartera=None)
        with pytest.raises(ChequeInvalido, match="cuenta de cheques"):
            cheques.cobrar(sin_cartera, cuenta=cuentas["bcp"])

    def test_no_se_cobra_mas_de_lo_que_se_anoto_al_vender(self, compras, cuentas):
        c = recibir(compras, cuentas, importe="1500")
        with pytest.raises(ChequeInvalido, match="solo hay 1,000.00"):
            cheques.cobrar(c, cuenta=cuentas["bcp"])
        c.refresh_from_db()
        assert c.estado == Estado.EN_CARTERA

    def test_solo_se_deposita_lo_que_esta_en_cartera_y_el_deposito_exige_banco(
        self, compras, cuentas
    ):
        c = recibir(compras, cuentas)
        with pytest.raises(ChequeInvalido, match="cuenta de banco"):
            cheques.depositar(c, cuenta=cuentas["caja"])
        cheques.depositar(c, cuenta=cuentas["bcp"])
        with pytest.raises(ChequeNoModificable):
            cheques.depositar(c, cuenta=cuentas["bcp"])

    def test_un_emitido_no_se_deposita(self, compras, cuentas):
        with pytest.raises(ChequeNoModificable, match="recibido"):
            cheques.depositar(girar(compras, cuentas), cuenta=cuentas["bcp"])

    def test_rechazar_con_comision_anota_el_egreso_del_banco(self, compras, cuentas):
        c = recibir(compras, cuentas)
        cheques.depositar(c, cuenta=cuentas["bcp"])
        with pytest.raises(ChequeInvalido, match="motivo"):
            cheques.rechazar(c, motivo="")
        cheques.rechazar(c, motivo="Sin fondos", comision=dec("25"))
        c.refresh_from_db()
        assert (c.estado, c.motivo) == (Estado.RECHAZADO, "Sin fondos")
        comision = MovimientoCaja.objects.get(origen_tipo=Origen.CHEQUE_RECHAZADO, origen_id=c.pk)
        assert (comision.cuenta_id, comision.monto) == (cuentas["bcp"].pk, dec("25"))
        assert servicios.saldo_de(cuentas["cheques"]) == dec("1000")  # el cheque no movió nada

    def test_rechazar_la_comision_pide_el_banco(self, compras, cuentas):
        c = recibir(compras, cuentas)
        with pytest.raises(ChequeInvalido, match="banco del cheque"):
            cheques.rechazar(c, motivo="Sin fondos", comision=dec("25"))

    def test_un_cobrado_no_se_rechaza_ni_anula(self, compras, cuentas):
        c = recibir(compras, cuentas)
        cheques.cobrar(c, cuenta=cuentas["bcp"])
        with pytest.raises(ChequeNoModificable):
            cheques.rechazar(c, motivo="Tarde")
        with pytest.raises(ChequeNoModificable):
            cheques.anular(c, motivo="Tarde")

    def test_deshacer_el_cobro_devuelve_el_dinero_a_la_cuenta_de_cheques(self, compras, cuentas):
        c = recibir(compras, cuentas)
        cheques.depositar(c, cuenta=cuentas["bcp"])
        cheques.cobrar(c)
        cheques.deshacer_cobro(c, motivo="Marcado por error")
        c.refresh_from_db()
        assert (c.estado, c.transferencia_id, c.cobrado_en) == (Estado.DEPOSITADO, None, None)
        assert servicios.saldo_de(cuentas["cheques"]) == dec("1000")
        assert servicios.saldo_de(cuentas["bcp"]) == dec("0")


class TestEmitido:
    def test_cobrarlo_solo_cambia_el_estado_sin_mover_dinero(self, compras, cuentas):
        c = girar(compras, cuentas)
        antes = servicios.saldo_de(cuentas["bcp"])
        cheques.cobrar(c)
        c.refresh_from_db()
        assert c.estado == Estado.COBRADO and servicios.saldo_de(cuentas["bcp"]) == antes
        assert not MovimientoCaja.objects.filter(cuenta=cuentas["bcp"]).exists()

    def test_se_anula_si_no_se_cobro(self, compras, cuentas):
        c = girar(compras, cuentas)
        cheques.anular(c, motivo="No se entregó")
        c.refresh_from_db()
        assert c.estado == Estado.ANULADO

    def test_un_girado_puede_volver_de_cobrado(self, compras, cuentas):
        c = girar(compras, cuentas)
        cheques.cobrar(c)
        cheques.deshacer_cobro(c, motivo="Error")
        c.refresh_from_db()
        assert c.estado == Estado.GIRADO


class TestAvisos:
    def test_vence_a_los_30_dias_de_la_fecha_de_pago_o_emision(self, compras, cuentas):
        c = recibir(compras, cuentas, fecha_emision=compras.entorno.hace(10))
        assert c.vence == compras.entorno.hace(10) + timedelta(days=30)
        diferido = recibir(
            compras,
            cuentas,
            numero="2",
            fecha_emision=compras.entorno.hace(10),
            fecha_pago=compras.entorno.hoy,
        )
        assert diferido.vence == compras.entorno.hoy + timedelta(days=30)

    def test_cuenta_vencidos_por_vencer_y_girados_sin_cobrar(self, compras, cuentas):
        hoy = compras.entorno.hoy
        recibir(compras, cuentas, numero="1", fecha_emision=compras.entorno.hace(40))  # vencido
        recibir(compras, cuentas, numero="2", fecha_emision=compras.entorno.hace(27))  # en 3 días
        recibir(compras, cuentas, numero="3", fecha_emision=hoy)  # lejos
        girar(compras, cuentas, numero="9", fecha_emision=compras.entorno.hace(40))
        girar(compras, cuentas, numero="10", fecha_emision=compras.entorno.hace(5))
        assert cheques.resumen_de_avisos(compras.empresa, hoy) == {
            "vencidos": 1,
            "por_vencer": 1,
            "emitidos_sin_cobrar": 1,
        }

    def test_los_cobrados_no_cuentan(self, compras, cuentas):
        c = recibir(compras, cuentas, fecha_emision=compras.entorno.hace(40))
        cheques.cobrar(c, cuenta=cuentas["bcp"])
        assert cheques.resumen_de_avisos(compras.empresa)["vencidos"] == 0

    def test_los_avisos_de_caja_los_incluyen(self, compras, cuentas):
        from apps.caja import alertas

        recibir(compras, cuentas, fecha_emision=compras.entorno.hace(40))
        codigos = {a["codigo"] for a in alertas.alertas(compras.empresa)}
        assert "cheques_vencidos" in codigos


def test_decimales_no_validos_se_rechazan(compras, cuentas):
    with pytest.raises(ChequeInvalido, match="2 decimales"):
        recibir(compras, cuentas, importe="10.123")
