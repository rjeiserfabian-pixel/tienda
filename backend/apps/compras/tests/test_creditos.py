"""Usar el saldo a favor de un proveedor para pagar compras a crédito."""

from datetime import timedelta

import pytest

from apps.caja.models import MovimientoCaja
from apps.compras.creditos import (
    aplicar_credito,
    creditos_disponibles,
    deshacer_aplicacion,
    saldo_a_favor_total,
)
from apps.compras.cuentas_por_pagar import registrar_pago, saldo_de
from apps.compras.devoluciones import LineaDevuelta, anular_devolucion, registrar_devolucion
from apps.compras.exceptions import CompraNoAnulable, CreditoInvalido, DevolucionNoAnulable
from apps.compras.models import CreditoProveedor, CuotaCompra
from apps.compras.servicios import CuotasEntrada, LineaEntrada, PagoEntrada, anular_compra
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.mantenimiento.models import TipoComprobante

from .conftest import dec

pytestmark = pytest.mark.django_db


@pytest.fixture
def nota(compras):
    return TipoComprobante.objects.sin_ambito().get(
        organizacion=compras.entorno.e.org_a, codigo="07"
    )


@pytest.fixture
def con_saldo(compras, nota):
    """Una devolución de 47,20 de una compra al contado: queda ese saldo a favor."""
    compra = compras.comprar([LineaEntrada(compras.entorno.producto(), dec(10), dec(10))])
    devolucion = registrar_devolucion(
        empresa=compras.empresa,
        compra=compra,
        tipo_comprobante=nota,
        comprobante_serie="FC01",
        comprobante_numero="1",
        fecha_emision=compras.entorno.hoy,
        razon="Mercadería dañada",
        lineas=[LineaDevuelta(compra.lineas.get().pk, dec(4))],
    )
    return devolucion.credito


def a_credito(compras, cuotas=2, **extra):
    """Compra a crédito de 118,00 (59,00 por cuota si son 2) del mismo proveedor."""
    linea = LineaEntrada(compras.entorno.producto(), dec(10), dec(10))
    return compras.comprar(
        [linea],
        forma_pago="CREDITO",
        cuotas=CuotasEntrada(cuotas, compras.entorno.hoy, compras.mensual),
        **extra,
    )


def cuotas_de(compra):
    return list(CuotaCompra.objects.filter(compra=compra).order_by("numero"))


class TestAplicar:
    def test_paga_cuotas_sin_mover_dinero(self, compras, con_saldo):
        c = a_credito(compras)
        movimientos = MovimientoCaja.objects.count()
        ap = aplicar_credito(con_saldo, c, monto=dec("47.20"))
        assert [q.pagado for q in cuotas_de(c)] == [dec("47.20"), 0]
        assert saldo_de(c) == dec("70.80")
        con_saldo.refresh_from_db()
        assert (con_saldo.usado, con_saldo.disponible) == (dec("47.20"), 0)
        assert (ap.monto, ap.anulada, ap.detalles.count()) == (dec("47.20"), False, 1)
        assert MovimientoCaja.objects.count() == movimientos

    def test_parcial_y_varias_cuotas(self, compras, con_saldo):
        c = a_credito(compras)
        aplicar_credito(con_saldo, c, monto=dec("20"))
        assert saldo_a_favor_total(compras.proveedor.pk, "PEN") == dec("27.20")
        ap = aplicar_credito(con_saldo, c, monto=dec("27.20"))
        assert [q.pagado for q in cuotas_de(c)] == [dec("47.20"), 0]
        assert ap.monto == dec("27.20")
        assert creditos_disponibles(compras.proveedor.pk, "PEN") == []

    def test_cuota_elegida(self, compras, con_saldo):
        c = a_credito(compras)
        segunda = cuotas_de(c)[1]
        aplicar_credito(con_saldo, c, monto=dec("30"), cuota_ids=[segunda.pk])
        assert [q.pagado for q in cuotas_de(c)] == [0, dec("30")]

    def test_se_puede_terminar_de_pagar_con_dinero(self, compras, con_saldo):
        c = a_credito(compras)
        aplicar_credito(con_saldo, c, monto=dec("47.20"))
        registrar_pago(c, pago=PagoEntrada(compras.efectivo, compras.caja, dec("70.80")))
        assert saldo_de(c) == 0

    def test_no_pasa_de_lo_disponible_ni_de_la_deuda(self, compras, con_saldo):
        c = a_credito(compras)
        with pytest.raises(CreditoInvalido, match="disponible 47.20"):
            aplicar_credito(con_saldo, c, monto=dec("50"))
        chica = a_credito(compras, cuotas=1)
        registrar_pago(chica, pago=PagoEntrada(compras.efectivo, compras.caja, dec("100")))
        with pytest.raises(CreditoInvalido, match="pasa de lo que se debe"):
            aplicar_credito(con_saldo, chica, monto=dec("30"))
        assert CreditoProveedor.objects.get().usado == 0

    def test_monto_invalido(self, compras, con_saldo):
        c = a_credito(compras)
        for monto in (dec("0"), dec("-1"), dec("1.001")):
            with pytest.raises(CreditoInvalido):
                aplicar_credito(con_saldo, c, monto=monto)

    def test_otro_proveedor(self, compras, con_saldo):
        c = a_credito(compras, proveedor=compras.entorno.otro_proveedor)
        with pytest.raises(CreditoInvalido, match="otro proveedor"):
            aplicar_credito(con_saldo, c, monto=dec("10"))

    def test_otra_moneda(self, compras, con_saldo):
        c = a_credito(compras)
        CreditoProveedor.objects.filter(pk=con_saldo.pk).update(moneda="USD")
        con_saldo.refresh_from_db()
        with pytest.raises(CreditoInvalido, match="monedas distintas"):
            aplicar_credito(con_saldo, c, monto=dec("10"))

    def test_compra_al_contado_o_anulada(self, compras, con_saldo):
        contado = compras.comprar()
        with pytest.raises(CreditoInvalido, match="al contado"):
            aplicar_credito(con_saldo, contado, monto=dec("10"))
        c = a_credito(compras)
        anular_compra(c, motivo="Error")
        c.refresh_from_db()
        with pytest.raises(CreditoInvalido, match="anulada"):
            aplicar_credito(con_saldo, c, monto=dec("10"))

    def test_fechas(self, compras, con_saldo):
        c = a_credito(compras)
        hoy = compras.entorno.hoy
        with pytest.raises(CreditoInvalido, match="futura"):
            aplicar_credito(con_saldo, c, monto=dec("10"), fecha=hoy + timedelta(days=1))
        with pytest.raises(CreditoInvalido, match="anterior"):
            aplicar_credito(con_saldo, c, monto=dec("10"), fecha=hoy - timedelta(days=2))

    def test_credito_anulado(self, compras, con_saldo):
        c = a_credito(compras)
        CreditoProveedor.objects.filter(pk=con_saldo.pk).update(anulado=True)
        con_saldo.refresh_from_db()
        with pytest.raises(CreditoInvalido, match="anulado"):
            aplicar_credito(con_saldo, c, monto=dec("10"))


class TestDeshacer:
    def test_vuelve_la_deuda_y_el_saldo(self, compras, con_saldo):
        c = a_credito(compras)
        ap = aplicar_credito(con_saldo, c, monto=dec("47.20"))
        deshacer_aplicacion(ap, motivo="Se aplicó a la compra equivocada")
        assert [q.pagado for q in cuotas_de(c)] == [0, 0]
        assert saldo_de(c) == dec("118.00")
        con_saldo.refresh_from_db()
        assert (con_saldo.usado, con_saldo.disponible) == (0, dec("47.20"))
        ap.refresh_from_db()
        assert ap.anulada is True and ap.motivo_anulacion.startswith("Se aplicó")

    def test_motivo_obligatorio_y_una_sola_vez(self, compras, con_saldo):
        c = a_credito(compras)
        ap = aplicar_credito(con_saldo, c, monto=dec("10"))
        with pytest.raises(MotivoObligatorio):
            deshacer_aplicacion(ap, motivo="  ")
        deshacer_aplicacion(ap, motivo="Error")
        with pytest.raises(DocumentoYaAnulado):
            deshacer_aplicacion(ap, motivo="Otra vez")
        con_saldo.refresh_from_db()
        assert con_saldo.usado == 0

    def test_otra_vez_se_puede_usar(self, compras, con_saldo):
        c = a_credito(compras)
        ap = aplicar_credito(con_saldo, c, monto=dec("47.20"))
        deshacer_aplicacion(ap, motivo="Error")
        aplicar_credito(con_saldo, c, monto=dec("47.20"))
        assert saldo_de(c) == dec("70.80")


class TestRelacionConOtrasOperaciones:
    def test_la_devolucion_no_se_anula_si_su_saldo_se_uso(self, compras, con_saldo):
        c = a_credito(compras)
        ap = aplicar_credito(con_saldo, c, monto=dec("10"))
        devolucion = con_saldo.devolucion
        with pytest.raises(DevolucionNoAnulable, match="ya se usó"):
            anular_devolucion(devolucion, motivo="Error")
        deshacer_aplicacion(ap, motivo="Error")
        anular_devolucion(devolucion, motivo="Error")
        con_saldo.refresh_from_db()
        assert con_saldo.anulado is True

    def test_la_compra_pagada_con_saldo_no_se_anula_hasta_deshacerlo(self, compras, con_saldo):
        c = a_credito(compras)
        ap = aplicar_credito(con_saldo, c, monto=dec("10"))
        with pytest.raises(CompraNoAnulable, match="cuotas pagadas"):
            anular_compra(c, motivo="Error")
        deshacer_aplicacion(ap, motivo="Error")
        anular_compra(c, motivo="Error")
        c.refresh_from_db()
        assert c.estado == "ANULADO"
