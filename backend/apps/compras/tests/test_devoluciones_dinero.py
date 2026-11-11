"""El dinero de una devolución: baja la deuda, reembolso a caja y saldo a favor."""

from datetime import timedelta

import pytest

from apps.caja.models import MovimientoCaja
from apps.caja.servicios import saldo_de as saldo_de_caja
from apps.compras.cuentas_por_pagar import registrar_pago, saldo_de
from apps.compras.devoluciones import LineaDevuelta, anular_devolucion, registrar_devolucion
from apps.compras.exceptions import DevolucionInvalida, DevolucionNoAnulable
from apps.compras.models import CreditoProveedor, CuotaCompra, ReembolsoCompra
from apps.compras.servicios import CuotasEntrada, LineaEntrada, PagoEntrada
from apps.mantenimiento.models import TipoComprobante

from .conftest import dec

pytestmark = pytest.mark.django_db


@pytest.fixture
def devolver(compras):
    nota = TipoComprobante.objects.sin_ambito().get(
        organizacion=compras.entorno.e.org_a, codigo="07"
    )
    contador = iter(range(1, 1000))

    def _devolver(compra, cantidad, *, reembolsos=(), **extra):
        linea = compra.lineas.get()
        datos = {
            "empresa": compras.empresa,
            "compra": compra,
            "tipo_comprobante": nota,
            "comprobante_serie": "FC01",
            "comprobante_numero": str(next(contador)),
            "fecha_emision": compras.entorno.hoy,
            "razon": "Mercadería dañada",
            "lineas": [LineaDevuelta(linea.pk, dec(cantidad))],
            "reembolsos": list(reembolsos),
        }
        datos.update(extra)
        return registrar_devolucion(**datos)

    return _devolver


def efectivo(compras, monto, **extra):
    return PagoEntrada(compras.efectivo, compras.caja, dec(monto), **extra)


def contado(compras):
    """Compra al contado: 10 unidades a 10 + IGV = 118,00, pagada con efectivo."""
    return compras.comprar([LineaEntrada(compras.entorno.producto(), dec(10), dec(10))])


def a_credito(compras, cuotas=2):
    """Compra a crédito de 118,00 en cuotas iguales (59,00 si son 2)."""
    linea = LineaEntrada(compras.entorno.producto(), dec(10), dec(10))
    return compras.comprar(
        [linea],
        forma_pago="CREDITO",
        cuotas=CuotasEntrada(cuotas, compras.entorno.hoy, compras.mensual),
    )


def cuotas_de(compra):
    return list(CuotaCompra.objects.filter(compra=compra).order_by("numero"))


def cuadra(d):
    assert d.aplicado_a_deuda + d.reembolsado + d.saldo_a_favor == d.total


class TestCompraAlContado:
    def test_reembolso_total_entra_a_la_caja(self, compras, devolver):
        c = contado(compras)
        antes = saldo_de_caja(compras.caja)
        d = devolver(c, "4", reembolsos=[efectivo(compras, "47.20")])
        assert (d.aplicado_a_deuda, d.reembolsado, d.saldo_a_favor) == (0, dec("47.20"), 0)
        cuadra(d)
        assert saldo_de_caja(compras.caja) == antes + dec("47.20")
        mov = MovimientoCaja.objects.get(origen_tipo="REEMBOLSO_COMPRA")
        assert (mov.tipo, mov.monto, mov.cuenta_id) == ("INGRESO", dec("47.20"), compras.caja.pk)
        assert mov.origen_id == d.reembolsos.get().pk
        assert not CreditoProveedor.objects.exists()

    def test_reembolso_parcial_deja_el_resto_como_saldo_a_favor(self, compras, devolver):
        c = contado(compras)
        d = devolver(c, "4", reembolsos=[efectivo(compras, "20")])
        assert (d.reembolsado, d.saldo_a_favor) == (dec("20"), dec("27.20"))
        cuadra(d)
        credito = d.credito
        assert (credito.monto, credito.usado, credito.moneda, credito.disponible) == (
            dec("27.20"),
            0,
            "PEN",
            dec("27.20"),
        )
        assert credito.proveedor_id == compras.proveedor.pk

    def test_sin_reembolso_todo_queda_como_saldo_a_favor(self, compras, devolver):
        c = contado(compras)
        antes = saldo_de_caja(compras.caja)
        d = devolver(c, "4")
        assert (d.reembolsado, d.saldo_a_favor) == (0, dec("47.20"))
        assert saldo_de_caja(compras.caja) == antes
        assert not ReembolsoCompra.objects.exists()

    def test_varios_medios_de_reembolso(self, compras, devolver):
        c = contado(compras)
        banco = PagoEntrada(compras.transferencia, compras.caja, dec("30"), referencia="OP-77")
        d = devolver(c, "4", reembolsos=[efectivo(compras, "17.20"), banco])
        assert d.reembolsado == dec("47.20")
        assert d.reembolsos.count() == 2

    def test_el_reembolso_no_puede_pasar_de_lo_pagado(self, compras, devolver):
        c = contado(compras)
        with pytest.raises(DevolucionInvalida, match="no puede pasar de 47.20"):
            devolver(c, "4", reembolsos=[efectivo(compras, "50")])

    def test_si_el_reembolso_falla_no_queda_nada(self, compras, devolver):
        from apps.inventario.models import MovimientoInventario

        c = contado(compras)
        movimientos = MovimientoInventario.objects.count()
        with pytest.raises(DevolucionInvalida):
            devolver(c, "4", reembolsos=[efectivo(compras, "99")])
        assert MovimientoInventario.objects.count() == movimientos
        assert not MovimientoCaja.objects.filter(origen_tipo="REEMBOLSO_COMPRA").exists()

    def test_validaciones_del_reembolso(self, compras, devolver):
        c = contado(compras)
        con_aporte = efectivo(compras, "10", aporte_socio=True)
        with pytest.raises(DevolucionInvalida, match="aporte"):
            devolver(c, "4", reembolsos=[con_aporte])
        antes_de_la_nota = efectivo(compras, "10", fecha=compras.entorno.hoy - timedelta(days=3))
        with pytest.raises(DevolucionInvalida, match="anterior a la nota"):
            devolver(c, "4", reembolsos=[antes_de_la_nota])
        en_dolares = PagoEntrada(compras.efectivo, compras.caja_usd, dec("10"))
        with pytest.raises(Exception, match="tipo de cambio"):
            devolver(c, "4", reembolsos=[en_dolares])

    def test_reembolso_a_una_cuenta_en_dolares_con_tipo_de_cambio(self, compras, devolver):
        c = contado(compras)
        en_dolares = PagoEntrada(
            compras.efectivo, compras.caja_usd, dec("37.20"), tipo_cambio=dec("3.7200")
        )
        d = devolver(c, "4", reembolsos=[efectivo(compras, "10"), en_dolares])
        r = d.reembolsos.get(cuenta=compras.caja_usd)
        assert (r.monto, r.monto_cuenta, r.tipo_cambio) == (dec("37.20"), dec("10.00"), dec("3.72"))
        assert saldo_de_caja(compras.caja_usd) == dec("10.00")


class TestCompraACredito:
    def test_la_nota_baja_primero_la_deuda_de_las_cuotas_mas_antiguas(self, compras, devolver):
        c = a_credito(compras)
        d = devolver(c, "4")
        assert (d.aplicado_a_deuda, d.reembolsado, d.saldo_a_favor) == (dec("47.20"), 0, 0)
        cuadra(d)
        assert [q.monto for q in cuotas_de(c)] == [dec("11.80"), dec("59.00")]
        assert saldo_de(c) == dec("70.80")
        assert not CreditoProveedor.objects.exists()

    def test_no_hay_reembolso_si_todo_se_debe(self, compras, devolver):
        c = a_credito(compras)
        with pytest.raises(DevolucionInvalida, match="no puede pasar de 0"):
            devolver(c, "4", reembolsos=[efectivo(compras, "1")])

    def test_una_cuota_puede_quedar_en_cero(self, compras, devolver):
        c = a_credito(compras)
        d = devolver(c, "5")  # 59,00 = justo la primera cuota
        assert [q.monto for q in cuotas_de(c)] == [dec("0"), dec("59.00")]
        assert d.aplicaciones.count() == 1
        assert saldo_de(c) == dec("59.00")

    def test_devolucion_mas_grande_que_la_deuda_reembolsa_lo_pagado(self, compras, devolver):
        c = a_credito(compras, cuotas=1)
        registrar_pago(c, pago=efectivo(compras, "100"))
        antes = saldo_de_caja(compras.caja)
        d = devolver(c, "10", reembolsos=[efectivo(compras, "100")])
        assert (d.aplicado_a_deuda, d.reembolsado, d.saldo_a_favor) == (
            dec("18"),
            dec("100"),
            0,
        )
        cuadra(d)
        assert saldo_de(c) == 0
        assert saldo_de_caja(compras.caja) == antes + dec("100")

    def test_lo_pagado_sin_reembolso_queda_como_saldo_a_favor(self, compras, devolver):
        c = a_credito(compras, cuotas=1)
        registrar_pago(c, pago=efectivo(compras, "100"))
        d = devolver(c, "10")
        assert (d.aplicado_a_deuda, d.saldo_a_favor) == (dec("18"), dec("100"))
        assert d.credito.monto == dec("100")

    def test_pagar_despues_de_la_nota_respeta_el_nuevo_monto(self, compras, devolver):
        c = a_credito(compras)
        devolver(c, "4")
        registrar_pago(c, pago=efectivo(compras, "70.80"))
        assert saldo_de(c) == 0
        with pytest.raises(Exception, match="ya está pagada"):
            registrar_pago(c, pago=efectivo(compras, "1"))


class TestAnular:
    def test_anular_deshace_la_deuda_el_reembolso_y_el_saldo(self, compras, devolver):
        c = contado(compras)
        antes = saldo_de_caja(compras.caja)
        d = devolver(c, "4", reembolsos=[efectivo(compras, "20")])
        anular_devolucion(d, motivo="Nota mal emitida")
        assert saldo_de_caja(compras.caja) == antes
        mov = MovimientoCaja.objects.get(origen_tipo="REEMBOLSO_COMPRA")
        assert mov.estado == "ANULADO"
        assert d.reembolsos.get().anulado is True
        d.credito.refresh_from_db()
        assert d.credito.anulado is True and d.credito.disponible == 0

    def test_las_cuotas_recuperan_su_monto(self, compras, devolver):
        c = a_credito(compras)
        d = devolver(c, "4")
        anular_devolucion(d, motivo="Error")
        assert [q.monto for q in cuotas_de(c)] == [dec("59.00"), dec("59.00")]
        assert saldo_de(c) == dec("118.00")

    def test_si_ya_se_pago_lo_rebajado_la_deuda_reaparece(self, compras, devolver):
        c = a_credito(compras)
        d = devolver(c, "4")
        registrar_pago(c, pago=efectivo(compras, "11.80"))
        anular_devolucion(d, motivo="Error")
        assert saldo_de(c) == dec("106.20")
        assert [q.pagado for q in cuotas_de(c)] == [dec("11.80"), 0]

    def test_no_se_anula_si_el_saldo_a_favor_ya_se_uso(self, compras, devolver):
        c = contado(compras)
        d = devolver(c, "4")
        CreditoProveedor.objects.filter(pk=d.credito.pk).update(usado=dec("10"))
        with pytest.raises(DevolucionNoAnulable, match="ya se usó"):
            anular_devolucion(d, motivo="Error")
        d.refresh_from_db()
        assert d.estado == "EMITIDO"

    def test_nada_se_anula_a_medias(self, compras, devolver, monkeypatch):
        c = contado(compras)
        d = devolver(c, "4", reembolsos=[efectivo(compras, "47.20")])
        from apps.caja import servicios as caja_servicios
        from apps.caja.exceptions import MovimientoNoAnulable

        def falla(*args, **kwargs):
            raise MovimientoNoAnulable("sesión cerrada")

        monkeypatch.setattr(caja_servicios, "anular_movimiento", falla)
        with pytest.raises(MovimientoNoAnulable):
            anular_devolucion(d, motivo="Error")
        d.refresh_from_db()
        assert d.estado == "EMITIDO"
        assert MovimientoCaja.objects.get(origen_tipo="REEMBOLSO_COMPRA").estado == "EMITIDO"
        assert ReembolsoCompra.objects.get().anulado is False
