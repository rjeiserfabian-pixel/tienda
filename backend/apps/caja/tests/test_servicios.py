from datetime import timedelta
from decimal import Decimal

import pytest

from apps.caja import servicios
from apps.caja.exceptions import MovimientoInvalido, MovimientoNoAnulable
from apps.caja.models import MovimientoCaja, Origen
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio

from .conftest import dec

pytestmark = pytest.mark.django_db

INGRESO, EGRESO = "INGRESO", "EGRESO"


def mover(compras, conceptos, tipo=INGRESO, monto="100", codigo=None, **extra):
    codigo = codigo or ("APORTE_CAPITAL" if tipo == INGRESO else "GASTOS_VARIOS")
    datos = {
        "empresa": compras.empresa,
        "cuenta": compras.caja,
        "tipo": tipo,
        "monto": dec(monto),
        "concepto": conceptos[codigo],
        **extra,
    }
    return servicios.registrar_movimiento(**datos)


class TestRegistrar:
    def test_un_ingreso_y_un_egreso_cambian_el_saldo(self, compras, conceptos):
        compras.caja.saldo_inicial = dec("50")
        compras.caja.save()
        mover(compras, conceptos, INGRESO, "200")
        mover(compras, conceptos, EGRESO, "30.50")
        assert servicios.saldo_de(compras.caja) == dec("219.50")

    def test_el_correlativo_avanza_por_empresa(self, compras, conceptos):
        numeros = [mover(compras, conceptos).numero for _ in range(3)]
        assert numeros == [1, 2, 3]

    def test_guarda_su_origen_la_glosa_y_la_referencia(self, compras, conceptos):
        m = mover(compras, conceptos, glosa="  Aporte   inicial ", referencia=" OP-1 ")
        assert (m.glosa, m.referencia, m.origen_tipo) == ("Aporte inicial", "OP-1", Origen.MANUAL)
        assert m.estado == "EMITIDO"

    @pytest.mark.parametrize("monto", ["0", "-1", "1.001"])
    def test_monto_invalido(self, compras, conceptos, monto):
        with pytest.raises(MovimientoInvalido):
            mover(compras, conceptos, monto=monto)

    def test_el_concepto_debe_ser_del_mismo_tipo(self, compras, conceptos):
        with pytest.raises(MovimientoInvalido, match="no corresponde"):
            mover(compras, conceptos, INGRESO, codigo="GASTOS_VARIOS")

    def test_concepto_o_cuenta_inactivos(self, compras, conceptos):
        concepto = conceptos["APORTE_CAPITAL"]
        concepto.estado = "INACTIVO"
        concepto.save()
        with pytest.raises(MovimientoInvalido, match="inactivo"):
            mover(compras, conceptos)
        concepto.estado = "ACTIVO"
        concepto.save()
        compras.caja.estado = "INACTIVO"
        compras.caja.save()
        with pytest.raises(MovimientoInvalido, match="inactiva"):
            mover(compras, conceptos)

    def test_cuenta_de_otra_empresa(self, compras, conceptos):
        otra = compras.entorno.e2
        with pytest.raises(MovimientoInvalido, match="no pertenece"):
            servicios.registrar_movimiento(
                empresa=otra,
                cuenta=compras.caja,
                tipo=INGRESO,
                monto=dec("10"),
                concepto=conceptos["APORTE_CAPITAL"],
            )

    def test_fecha_futura_o_anterior_al_saldo_inicial(self, compras, conceptos):
        with pytest.raises(MovimientoInvalido, match="futura"):
            mover(compras, conceptos, fecha=compras.entorno.hoy + timedelta(days=1))
        compras.caja.fecha_saldo_inicial = compras.entorno.hoy
        compras.caja.save()
        with pytest.raises(MovimientoInvalido, match="anterior al saldo inicial"):
            mover(compras, conceptos, fecha=compras.entorno.hoy - timedelta(days=3))

    def test_un_egreso_que_deja_en_negativo_se_permite(self, compras, conceptos):
        mover(compras, conceptos, EGRESO, "40")
        assert servicios.saldo_de(compras.caja) == dec("-40")


class TestSaldos:
    def test_saldo_a_una_fecha(self, compras, conceptos):
        hoy = compras.entorno.hoy
        mover(compras, conceptos, INGRESO, "100", fecha=hoy - timedelta(days=5))
        mover(compras, conceptos, EGRESO, "30", fecha=hoy)
        assert servicios.saldo_de(compras.caja, hasta=hoy - timedelta(days=1)) == dec("100")
        assert servicios.saldo_de(compras.caja) == dec("70")

    def test_las_anuladas_no_cuentan(self, compras, conceptos):
        m = mover(compras, conceptos, INGRESO, "100")
        servicios.anular_movimiento(m, motivo="Error")
        assert servicios.saldo_de(compras.caja) == dec("0")

    def test_el_resumen_por_cuenta_y_monedas_separadas(self, compras, conceptos):
        mover(compras, conceptos, INGRESO, "100")
        mover(compras, conceptos, EGRESO, "25")
        filas = {f["cuenta"].nombre: f for f in servicios.saldos_de_la_empresa(compras.empresa)}
        caja = filas["Caja soles"]
        assert (caja["ingresos"], caja["egresos"], caja["saldo"], caja["movimientos"]) == (
            dec("100"),
            dec("25"),
            dec("75"),
            2,
        )
        assert filas["Caja dólares"]["saldo"] == dec("0")
        assert filas["Caja dólares"]["cuenta"].moneda == "USD"

    def test_una_cuenta_inactiva_sin_movimientos_no_sale(self, compras, conceptos):
        compras.caja_usd.estado = "INACTIVO"
        compras.caja_usd.save()
        nombres = [f["cuenta"].nombre for f in servicios.saldos_de_la_empresa(compras.empresa)]
        assert "Caja dólares" not in nombres


class TestAnular:
    def test_motivo_obligatorio_y_doble_anulacion(self, compras, conceptos):
        m = mover(compras, conceptos)
        with pytest.raises(MotivoObligatorio):
            servicios.anular_movimiento(m, motivo="  ")
        servicios.anular_movimiento(m, motivo="Se registró por error")
        m.refresh_from_db()
        assert (m.estado, m.motivo_anulacion) == ("ANULADO", "Se registró por error")
        with pytest.raises(DocumentoYaAnulado):
            servicios.anular_movimiento(m, motivo="Otra vez")

    def test_el_de_otro_documento_no_se_anula_a_mano(self, compras, conceptos):
        m = mover(compras, conceptos, EGRESO, origen_tipo=Origen.PAGO_COMPRA, origen_id=99)
        with pytest.raises(MovimientoNoAnulable, match="anula ese documento"):
            servicios.anular_movimiento(m, motivo="Quiero anularlo")

    def test_anular_por_origen(self, compras, conceptos):
        mover(compras, conceptos, EGRESO, origen_tipo=Origen.PAGO_COMPRA, origen_id=7)
        mover(compras, conceptos, EGRESO, origen_tipo=Origen.PAGO_COMPRA, origen_id=8)
        assert servicios.anular_por_origen(Origen.PAGO_COMPRA, 7, motivo="Pago anulado") == 1
        estados = dict(MovimientoCaja.objects.values_list("origen_id", "estado"))
        assert estados == {7: "ANULADO", 8: "EMITIDO"}
        assert servicios.anular_por_origen(Origen.PAGO_COMPRA, 7, motivo="Otra vez") == 0

    def test_concepto_del_sistema_se_carga_si_falta(self, compras):
        concepto = servicios.concepto_del_sistema(compras.empresa, "PAGO_PROVEEDOR")
        assert (concepto.nombre, concepto.tipo, concepto.automatico) == (
            "Pago a proveedor",
            EGRESO,
            True,
        )


def test_dec_es_decimal():
    assert isinstance(dec("1"), Decimal)
