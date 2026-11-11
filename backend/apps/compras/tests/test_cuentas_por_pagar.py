from datetime import timedelta

import pytest

from apps.compras.cuentas_por_pagar import anular_pago, registrar_pago, registrar_pagos, saldo_de
from apps.compras.exceptions import CompraInvalida, CompraNoAnulable
from apps.compras.models import AplicacionPago, CuotaCompra
from apps.compras.servicios import CuotasEntrada, LineaEntrada, PagoEntrada, anular_compra
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio

from .conftest import dec

pytestmark = pytest.mark.django_db


@pytest.fixture
def credito(compras):
    """Compra a crédito de 118,00 en 3 cuotas: 39,34 + 39,33 + 39,33."""
    linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
    cuotas = CuotasEntrada(3, compras.entorno.hoy, compras.mensual)
    compra = compras.comprar([linea], forma_pago="CREDITO", cuotas=cuotas)
    compra.ayuda = compras
    return compra


def pagar(credito, monto, *, cuota_id=None, medio=None, cuenta=None, **extra):
    c = credito.ayuda
    pago = PagoEntrada(medio or c.efectivo, cuenta or c.caja, dec(monto), **extra)
    return registrar_pago(credito, pago=pago, cuota_id=cuota_id)


def cuotas_de(credito):
    return list(CuotaCompra.objects.filter(compra=credito).order_by("numero"))


class TestPagar:
    def test_el_pago_cubre_la_cuota_mas_antigua(self, credito):
        pago = pagar(credito, "39.34")
        assert [c.pagado for c in cuotas_de(credito)] == [dec("39.34"), 0, 0]
        assert (pago.tipo, pago.monto, pago.anulado) == ("COMPRA", dec("39.34"), False)
        assert saldo_de(credito) == dec("78.66")

    def test_un_pago_puede_cubrir_varias_cuotas(self, credito):
        pago = pagar(credito, "50")
        assert [c.pagado for c in cuotas_de(credito)] == [dec("39.34"), dec("10.66"), 0]
        aplicaciones = AplicacionPago.objects.filter(pago=pago).order_by("cuota__numero")
        assert [a.monto for a in aplicaciones] == [dec("39.34"), dec("10.66")]

    def test_pagos_parciales_se_acumulan_hasta_saldar(self, credito):
        for monto in ("20", "20", "78"):
            pagar(credito, monto)
        assert saldo_de(credito) == 0
        assert all(c.pagado == c.monto for c in cuotas_de(credito))

    def test_a_una_cuota_elegida(self, credito):
        tercera = cuotas_de(credito)[2]
        pagar(credito, "39.33", cuota_id=tercera.pk)
        assert [c.pagado for c in cuotas_de(credito)] == [0, 0, dec("39.33")]

    def test_no_se_paga_mas_que_la_cuota_elegida(self, credito):
        primera = cuotas_de(credito)[0]
        with pytest.raises(CompraInvalida, match="pendiente"):
            pagar(credito, "40", cuota_id=primera.pk)
        assert saldo_de(credito) == dec("118")

    def test_no_se_paga_mas_de_lo_que_se_debe(self, credito):
        with pytest.raises(CompraInvalida, match="más de lo que se debe"):
            pagar(credito, "118.01")
        assert saldo_de(credito) == dec("118")

    def test_ya_pagada_por_completo(self, credito):
        pagar(credito, "118")
        with pytest.raises(CompraInvalida, match="por completo"):
            pagar(credito, "1")

    def test_cuota_de_otra_compra(self, credito, compras):
        otra = compras.comprar(
            [LineaEntrada(compras.entorno.producto(), dec(1), dec(10))],
            forma_pago="CREDITO",
            cuotas=CuotasEntrada(2, compras.entorno.hoy, compras.mensual),
        )
        ajena = CuotaCompra.objects.filter(compra=otra).first()
        with pytest.raises(CompraInvalida, match="no pertenece"):
            pagar(credito, "10", cuota_id=ajena.pk)

    def test_una_compra_al_contado_no_se_paga_de_nuevo(self, compras):
        contado = compras.comprar()
        contado.ayuda = compras
        with pytest.raises(CompraInvalida, match="contado"):
            pagar(contado, "10")

    def test_una_compra_anulada_no_se_paga(self, credito):
        anular_compra(credito, motivo="Error")
        with pytest.raises(CompraInvalida, match="anulada"):
            pagar(credito, "10")

    def test_validaciones_del_pago(self, credito):
        c = credito.ayuda
        with pytest.raises(CompraInvalida, match="operación"):
            pagar(credito, "10", medio=c.transferencia)
        with pytest.raises(CompraInvalida, match="moneda"):
            pagar(credito, "10", cuenta=c.caja_usd)
        with pytest.raises(CompraInvalida, match="mayor"):
            pagar(credito, "0")
        with pytest.raises(CompraInvalida, match="futura"):
            pagar(credito, "10", fecha=c.entorno.hoy + timedelta(days=1))
        with pytest.raises(CompraInvalida, match="anterior"):
            pagar(credito, "10", fecha=c.entorno.hoy - timedelta(days=30))
        assert saldo_de(credito) == dec("118")

    def test_transferencia_con_numero_de_operacion(self, credito):
        pago = pagar(credito, "10", medio=credito.ayuda.transferencia, referencia="OP-77")
        assert pago.referencia == "OP-77"


class TestVariosMedios:
    def test_cada_medio_es_un_pago_y_todos_se_reparten_en_orden(self, credito):
        c = credito.ayuda
        pagos = registrar_pagos(
            credito,
            pagos=[
                PagoEntrada(c.efectivo, c.caja, dec("30")),
                PagoEntrada(c.transferencia, c.caja, dec("20"), referencia="OP-1"),
            ],
        )
        assert [(p.medio_pago_id, p.monto) for p in pagos] == [
            (c.efectivo.pk, dec("30")),
            (c.transferencia.pk, dec("20")),
        ]
        assert [x.pagado for x in cuotas_de(credito)] == [dec("39.34"), dec("10.66"), 0]
        assert AplicacionPago.objects.filter(pago=pagos[0]).count() == 1  # solo cuota 1
        assert AplicacionPago.objects.filter(pago=pagos[1]).count() == 2  # cuota 1 y cuota 2

    def test_se_puede_anular_uno_solo(self, credito):
        c = credito.ayuda
        efectivo, yape = registrar_pagos(
            credito,
            pagos=[
                PagoEntrada(c.efectivo, c.caja, dec("30")),
                PagoEntrada(c.transferencia, c.caja, dec("20"), referencia="OP-1"),
            ],
        )
        anular_pago(yape, motivo="La transferencia rebotó")
        assert saldo_de(credito) == dec("88")
        efectivo.refresh_from_db()
        assert efectivo.anulado is False

    def test_todo_o_nada(self, credito):
        c = credito.ayuda
        with pytest.raises(CompraInvalida, match="operación"):
            registrar_pagos(
                credito,
                pagos=[
                    PagoEntrada(c.efectivo, c.caja, dec("30")),
                    PagoEntrada(c.transferencia, c.caja, dec("20")),  # falta el N° de operación
                ],
            )
        assert saldo_de(credito) == dec("118")
        with pytest.raises(CompraInvalida, match="al menos un pago"):
            registrar_pagos(credito, pagos=[])


class TestAnularPago:
    def test_devuelve_a_cada_cuota_lo_que_recibio(self, credito):
        pago = pagar(credito, "50")
        anular_pago(pago, motivo="Pagué la cuenta equivocada")
        pago.refresh_from_db()
        assert (pago.anulado, pago.motivo_anulacion) == (True, "Pagué la cuenta equivocada")
        assert pago.anulado_en is not None
        assert [c.pagado for c in cuotas_de(credito)] == [0, 0, 0]
        assert saldo_de(credito) == dec("118")

    def test_solo_se_revierte_ese_pago(self, credito):
        primero = pagar(credito, "39.34")
        pagar(credito, "10")
        anular_pago(primero, motivo="Error")
        assert [c.pagado for c in cuotas_de(credito)] == [0, dec("10"), 0]

    def test_motivo_obligatorio_y_doble_anulacion(self, credito):
        pago = pagar(credito, "10")
        with pytest.raises(MotivoObligatorio):
            anular_pago(pago, motivo="  ")
        anular_pago(pago, motivo="Primera vez")
        with pytest.raises(DocumentoYaAnulado):
            anular_pago(pago, motivo="Segunda vez")
        assert saldo_de(credito) == dec("118")

    def test_el_pago_de_una_compra_al_contado_no_se_anula_suelto(self, compras):
        contado = compras.comprar()
        with pytest.raises(CompraNoAnulable, match="anula la compra"):
            anular_pago(contado.pagos.get(), motivo="Quiero deshacerlo")

    def test_se_puede_pagar_de_nuevo_tras_anular(self, credito):
        anular_pago(pagar(credito, "118"), motivo="Error")
        pagar(credito, "118")
        assert saldo_de(credito) == 0


class TestAnularLaCompra:
    def test_con_pagos_primero_hay_que_anularlos(self, credito):
        pago = pagar(credito, "10")
        with pytest.raises(CompraNoAnulable):
            anular_compra(credito, motivo="Quiero anularla")
        anular_pago(pago, motivo="Pago equivocado")
        anular_compra(credito, motivo="Ahora sí")
        credito.refresh_from_db()
        assert credito.estado == "ANULADO"

    def test_los_pagos_anulados_antes_conservan_su_motivo(self, credito):
        pago = pagar(credito, "10")
        anular_pago(pago, motivo="Pago equivocado")
        anular_compra(credito, motivo="Se canceló la compra")
        pago.refresh_from_db()
        assert pago.motivo_anulacion == "Pago equivocado"


class TestVariasCuotasElegidas:
    def test_se_paga_solo_entre_las_cuotas_elegidas(self, credito):
        c = credito.ayuda
        cuotas = cuotas_de(credito)
        elegidas = [cuotas[0].pk, cuotas[2].pk]  # la 1 y la 3, no la 2
        registrar_pagos(
            credito,
            pagos=[PagoEntrada(c.efectivo, c.caja, dec("50"))],
            cuota_ids=elegidas,
        )
        assert [x.pagado for x in cuotas_de(credito)] == [dec("39.34"), 0, dec("10.66")]

    def test_no_se_paga_mas_que_la_suma_de_las_elegidas(self, credito):
        c = credito.ayuda
        cuotas = cuotas_de(credito)
        with pytest.raises(CompraInvalida, match="elegidas solo tienen pendiente 78.67"):
            registrar_pagos(
                credito,
                pagos=[PagoEntrada(c.efectivo, c.caja, dec("80"))],
                cuota_ids=[cuotas[0].pk, cuotas[2].pk],
            )
        assert saldo_de(credito) == dec("118")

    def test_una_cuota_ajena_se_rechaza(self, credito):
        c = credito.ayuda
        with pytest.raises(CompraInvalida, match="no pertenece"):
            registrar_pagos(
                credito,
                pagos=[PagoEntrada(c.efectivo, c.caja, dec("10"))],
                cuota_ids=[cuotas_de(credito)[0].pk, 999_999],
            )
