from datetime import timedelta
from decimal import Decimal

import pytest

from apps.caja import servicios, transferencias
from apps.caja.exceptions import MovimientoInvalido, MovimientoNoAnulable
from apps.caja.models import MovimientoCaja, Origen
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec

pytestmark = pytest.mark.django_db


@pytest.fixture
def cuentas(compras):
    """Cajas y bancos de la empresa A1 (soles y dólares) y una caja de la empresa A2."""
    e = compras.entorno

    def nueva(empresa, nombre, tipo="BANCO", moneda="PEN"):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=empresa,
            nombre=nombre,
            tipo=tipo,
            moneda=moneda,
            banco="BCP" if tipo == "BANCO" else "",
        )

    return {
        "caja": compras.caja,
        "caja_usd": compras.caja_usd,
        "bcp": nueva(e.e1, "BCP soles"),
        "bbva": nueva(e.e1, "BBVA soles"),
        "bcp_usd": nueva(e.e1, "BCP dólares", moneda="USD"),
        "caja_a2": nueva(e.e2, "Caja A2", tipo="CAJA"),
    }


def mover(compras, origen, destino, monto, **extra):
    return transferencias.registrar_transferencia(
        empresa=origen.empresa,
        cuenta_origen=origen,
        cuenta_destino=destino,
        monto=dec(monto),
        **extra,
    )


def libro(t):
    return list(
        MovimientoCaja.objects.filter(origen_tipo=Origen.TRANSFERENCIA, origen_id=t.pk).order_by(
            "id"
        )
    )


class TestRegistrar:
    def test_un_deposito_pasa_efectivo_al_banco(self, compras, cuentas):
        t = mover(compras, cuentas["caja"], cuentas["bcp"], "500", referencia="OP-1")
        assert (t.clase, t.numero, t.monto_origen, t.monto_destino, t.tipo_cambio) == (
            "DEPOSITO", 1, dec("500"), dec("500"), None,
        )  # fmt: skip
        salida, entrada = libro(t)
        assert (salida.tipo, salida.cuenta_id, salida.concepto.codigo) == (
            "EGRESO", cuentas["caja"].pk, "TRANSFERENCIA_SALIDA",
        )  # fmt: skip
        assert (entrada.tipo, entrada.cuenta_id, entrada.concepto.codigo) == (
            "INGRESO", cuentas["bcp"].pk, "TRANSFERENCIA_ENTRADA",
        )  # fmt: skip
        assert entrada.referencia == "OP-1"
        assert servicios.saldo_de(cuentas["caja"]) == dec("-500")
        assert servicios.saldo_de(cuentas["bcp"]) == dec("500")

    def test_un_retiro_y_una_transferencia(self, compras, cuentas):
        assert mover(compras, cuentas["bcp"], cuentas["caja"], "100").clase == "RETIRO"
        assert mover(compras, cuentas["bcp"], cuentas["bbva"], "100").clase == "TRANSFERENCIA"
        assert mover(compras, cuentas["caja"], cuentas["bcp"], "1").numero == 3

    def test_comision_e_itf_salen_de_la_cuenta_de_origen(self, compras, cuentas):
        t = mover(
            compras, cuentas["bcp"], cuentas["bbva"], "1000", comision=dec("3.50"), itf=dec("0.05")
        )
        conceptos = {m.concepto.codigo: m.monto for m in libro(t)}
        assert conceptos == {
            "TRANSFERENCIA_SALIDA": dec("1000"),
            "TRANSFERENCIA_ENTRADA": dec("1000"),
            "COMISION_BANCARIA": dec("3.50"),
            "ITF": dec("0.05"),
        }
        assert servicios.saldo_de(cuentas["bcp"]) == dec("-1003.55")
        assert servicios.saldo_de(cuentas["bbva"]) == dec("1000")

    def test_soles_a_dolares_divide_entre_el_tipo_de_cambio(self, compras, cuentas):
        t = mover(compras, cuentas["bcp"], cuentas["bcp_usd"], "375", tipo_cambio=dec("3.7500"))
        assert (t.monto_origen, t.monto_destino, t.tipo_cambio) == (
            dec("375"),
            dec("100"),
            dec("3.75"),
        )
        assert servicios.saldo_de(cuentas["bcp_usd"]) == dec("100")

    def test_dolares_a_soles_multiplica(self, compras, cuentas):
        t = mover(compras, cuentas["bcp_usd"], cuentas["bcp"], "100", tipo_cambio=dec("3.6000"))
        assert t.monto_destino == dec("360")

    def test_se_puede_dar_lo_que_el_banco_abono_de_verdad(self, compras, cuentas):
        t = mover(
            compras,
            cuentas["bcp"],
            cuentas["bcp_usd"],
            "375",
            tipo_cambio=dec("3.75"),
            monto_destino=dec("99.80"),
        )
        assert t.monto_destino == dec("99.80")

    def test_monedas_distintas_exigen_tipo_de_cambio(self, compras, cuentas):
        with pytest.raises(MovimientoInvalido, match="tipo de cambio"):
            mover(compras, cuentas["bcp"], cuentas["bcp_usd"], "100")

    def test_misma_moneda_no_lleva_tipo_de_cambio(self, compras, cuentas):
        with pytest.raises(MovimientoInvalido, match="no hay tipo de cambio"):
            mover(compras, cuentas["bcp"], cuentas["bbva"], "100", tipo_cambio=dec("3.75"))

    def test_validaciones(self, compras, cuentas):
        with pytest.raises(MovimientoInvalido, match="distintos"):
            mover(compras, cuentas["bcp"], cuentas["bcp"], "10")
        for monto in ("0", "-5", "1.001"):
            with pytest.raises(MovimientoInvalido):
                mover(compras, cuentas["bcp"], cuentas["bbva"], monto)
        with pytest.raises(MovimientoInvalido, match="futura"):
            mover(
                compras,
                cuentas["bcp"],
                cuentas["bbva"],
                "10",
                fecha=compras.entorno.hoy + timedelta(days=1),
            )
        cuentas["bbva"].estado = "INACTIVO"
        cuentas["bbva"].save()
        with pytest.raises(MovimientoInvalido, match="inactiva"):
            mover(compras, cuentas["bcp"], cuentas["bbva"], "10")
        assert MovimientoCaja.objects.count() == 0

    def test_entre_empresas_cada_movimiento_queda_en_su_empresa(self, compras, cuentas):
        t = mover(compras, cuentas["caja"], cuentas["caja_a2"], "200")
        salida, entrada = libro(t)
        assert salida.empresa_id == compras.empresa.pk
        assert entrada.empresa_id == compras.entorno.e2.pk
        assert t.empresa_destino_id == compras.entorno.e2.pk
        assert servicios.saldo_de(cuentas["caja_a2"]) == dec("200")

    def test_la_fecha_no_puede_ser_anterior_al_saldo_inicial_de_una_cuenta(self, compras, cuentas):
        cuentas["bbva"].fecha_saldo_inicial = compras.entorno.hoy
        cuentas["bbva"].save()
        with pytest.raises(MovimientoInvalido, match="anterior al saldo inicial"):
            mover(
                compras,
                cuentas["bcp"],
                cuentas["bbva"],
                "10",
                fecha=compras.entorno.hoy - timedelta(days=5),
            )
        assert MovimientoCaja.objects.count() == 0


class TestAnular:
    def test_anula_todos_los_movimientos_y_devuelve_el_dinero(self, compras, cuentas):
        t = mover(
            compras, cuentas["bcp"], cuentas["bbva"], "100", comision=dec("1"), itf=dec("0.01")
        )
        transferencias.anular_transferencia(t, motivo="Cuenta equivocada")
        t.refresh_from_db()
        assert (t.estado, t.motivo_anulacion) == ("ANULADO", "Cuenta equivocada")
        assert {m.estado for m in libro(t)} == {"ANULADO"}
        assert servicios.saldo_de(cuentas["bcp"]) == dec("0")
        assert servicios.saldo_de(cuentas["bbva"]) == dec("0")

    def test_motivo_obligatorio_y_una_sola_vez(self, compras, cuentas):
        t = mover(compras, cuentas["bcp"], cuentas["bbva"], "100")
        with pytest.raises(MotivoObligatorio):
            transferencias.anular_transferencia(t, motivo=" ")
        transferencias.anular_transferencia(t, motivo="Error")
        with pytest.raises(DocumentoYaAnulado):
            transferencias.anular_transferencia(t, motivo="Otra vez")
        assert {m.estado for m in libro(t)} == {"ANULADO"}

    def test_un_movimiento_de_la_transferencia_no_se_anula_suelto(self, compras, cuentas):
        t = mover(compras, cuentas["bcp"], cuentas["bbva"], "100")
        with pytest.raises(MovimientoNoAnulable, match="anula ese documento"):
            servicios.anular_movimiento(libro(t)[0], motivo="Quiero anularlo")

    def test_anular_una_entre_empresas(self, compras, cuentas):
        t = mover(compras, cuentas["caja"], cuentas["caja_a2"], "50")
        transferencias.anular_transferencia(t, motivo="Error")
        assert servicios.saldo_de(cuentas["caja_a2"]) == dec("0")


def test_decimal_helper():
    assert isinstance(dec("1"), Decimal)
