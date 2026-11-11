"""El dinero de Compras llega al libro de caja y bancos, y vuelve a salir si se anula."""

import pytest
from django.db import connection

from apps.caja import servicios
from apps.caja.models import MovimientoCaja, Origen
from apps.compras.cuentas_por_pagar import anular_pago, registrar_pagos
from apps.compras.recuperar_caja import crear_movimientos_de_pagos
from apps.compras.servicios import (
    CuotasEntrada,
    FleteEntrada,
    LineaEntrada,
    PagoEntrada,
    anular_compra,
)

from .conftest import dec

pytestmark = pytest.mark.django_db


def vaciar_libro():
    """Borra el libro por SQL (los movimientos no se borran desde la aplicación)."""
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM caja_movimientocaja")


def movimientos(**filtros):
    return list(MovimientoCaja.objects.filter(**filtros).order_by("id"))


@pytest.fixture
def credito(compras):
    linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
    cuotas = CuotasEntrada(2, compras.entorno.hoy, compras.mensual)
    return compras.comprar([linea], forma_pago="CREDITO", cuotas=cuotas)


class TestAlContado:
    def test_el_pago_sale_de_la_caja(self, compras):
        compra = compras.comprar()
        [m] = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert (m.tipo, m.monto, m.cuenta_id, m.estado) == (
            "EGRESO",
            dec("118"),
            compras.caja.pk,
            "EMITIDO",
        )
        assert m.concepto.codigo == "PAGO_PROVEEDOR"
        assert compra.comprobante in m.glosa and f"N° {compra.numero:06d}" in m.glosa
        assert servicios.saldo_de(compras.caja) == dec("-118")

    def test_con_dos_medios_son_dos_egresos(self, compras):
        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        compras.comprar(
            [linea],
            comprobante_numero="900",
            pagos=[
                PagoEntrada(compras.efectivo, compras.caja, dec("100")),
                PagoEntrada(compras.transferencia, compras.caja, dec("18"), referencia="OP-1"),
            ],
        )
        montos = sorted(m.monto for m in movimientos(origen_tipo=Origen.PAGO_COMPRA))
        assert montos == [dec("18"), dec("100")]
        assert any(m.referencia == "OP-1" for m in movimientos())

    def test_el_flete_tambien_sale_de_la_caja(self, compras):
        flete = FleteEntrada(
            dec("10"), True, pagos=(PagoEntrada(compras.efectivo, compras.caja, dec("10")),)
        )
        compras.comprar(flete=flete)
        glosas = [m.glosa for m in movimientos(origen_tipo=Origen.PAGO_COMPRA)]
        assert len(glosas) == 2
        assert any(g.startswith("Flete de la compra") for g in glosas)
        assert servicios.saldo_de(compras.caja) == dec("-128")

    def test_anular_la_compra_devuelve_el_dinero_a_la_caja(self, compras):
        compra = compras.comprar()
        anular_compra(compra, motivo="Se registró dos veces")
        [m] = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert m.estado == "ANULADO"
        assert "Se registró dos veces" in m.motivo_anulacion
        assert servicios.saldo_de(compras.caja) == dec("0")


class TestAlCredito:
    def test_registrar_a_credito_no_mueve_dinero(self, credito):
        assert movimientos(origen_tipo=Origen.PAGO_COMPRA) == []

    def test_cada_pago_de_cuotas_es_un_egreso(self, compras, credito):
        registrar_pagos(
            credito,
            pagos=[
                PagoEntrada(compras.efectivo, compras.caja, dec("30")),
                PagoEntrada(compras.transferencia, compras.caja, dec("20"), referencia="OP-9"),
            ],
        )
        filas = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert [(m.monto, m.referencia) for m in filas] == [(dec("30"), ""), (dec("20"), "OP-9")]
        assert "cuotas 1" in filas[0].glosa
        assert servicios.saldo_de(compras.caja) == dec("-50")

    def test_anular_un_pago_anula_solo_su_movimiento(self, compras, credito):
        efectivo, yape = registrar_pagos(
            credito,
            pagos=[
                PagoEntrada(compras.efectivo, compras.caja, dec("30")),
                PagoEntrada(compras.transferencia, compras.caja, dec("20"), referencia="OP-9"),
            ],
        )
        anular_pago(yape, motivo="La transferencia rebotó")
        estados = {m.origen_id: m.estado for m in movimientos(origen_tipo=Origen.PAGO_COMPRA)}
        assert estados == {efectivo.pk: "EMITIDO", yape.pk: "ANULADO"}
        assert servicios.saldo_de(compras.caja) == dec("-30")

    def test_un_pago_que_falla_no_deja_movimientos(self, compras, credito):
        from apps.compras.exceptions import CompraInvalida

        with pytest.raises(CompraInvalida):
            registrar_pagos(
                credito,
                pagos=[
                    PagoEntrada(compras.efectivo, compras.caja, dec("30")),
                    PagoEntrada(
                        compras.transferencia, compras.caja, dec("20")
                    ),  # sin N° de operación
                ],
            )
        assert movimientos(origen_tipo=Origen.PAGO_COMPRA) == []


class TestRecuperacion:
    def test_los_pagos_anteriores_al_libro_se_pasan_una_sola_vez(self, compras, credito):
        compras.comprar(comprobante_numero="800")
        registrar_pagos(credito, pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("40"))])
        vaciar_libro()  # como si el libro se hubiera creado después de los pagos
        org = compras.entorno.e.org_a.pk
        assert crear_movimientos_de_pagos(org) == 2
        assert crear_movimientos_de_pagos(org) == 0

    def test_las_compras_anuladas_no_generan_nada(self, compras):
        compra = compras.comprar()
        anular_compra(compra, motivo="Error")
        vaciar_libro()
        assert crear_movimientos_de_pagos(compras.entorno.e.org_a.pk) == 0


class TestPagoEnOtraMoneda:
    """Una compra en dólares se paga con una cuenta en soles (y al revés), con su tipo de cambio."""

    def _compra_usd(self, compras, **extra):
        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        return compras.comprar(
            [linea],
            moneda="USD",
            tipo_cambio=dec("3.6000"),
            comprobante_numero=extra.pop("numero", "700"),
            **extra,
        )

    def test_una_compra_en_dolares_pagada_con_soles(self, compras):
        # Total 118 US$ (100 + IGV); pagado desde la caja en soles a 3,60.
        pago = PagoEntrada(compras.efectivo, compras.caja, dec("118"), tipo_cambio=dec("3.6000"))
        compra = self._compra_usd(compras, pagos=[pago])
        registrado = compra.pagos.get()
        assert (registrado.monto, registrado.tipo_cambio, registrado.monto_cuenta) == (
            dec("118"),
            dec("3.6000"),
            dec("424.80"),
        )
        [m] = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert (m.monto, m.cuenta_id) == (dec("424.80"), compras.caja.pk)  # sale en soles
        assert "US$ 118.00 a 3.6000" in m.glosa
        assert servicios.saldo_de(compras.caja) == dec("-424.80")

    def test_sin_tipo_de_cambio_se_rechaza(self, compras):
        from apps.compras.exceptions import CompraInvalida

        with pytest.raises(CompraInvalida, match="tipo de cambio"):
            self._compra_usd(
                compras, pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"))]
            )

    def test_misma_moneda_ignora_el_tipo_de_cambio(self, compras):
        pago = PagoEntrada(compras.efectivo, compras.caja_usd, dec("118"), tipo_cambio=dec("3.6"))
        compra = self._compra_usd(compras, pagos=[pago])
        registrado = compra.pagos.get()
        assert (registrado.tipo_cambio, registrado.monto_cuenta) == (None, None)
        [m] = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert m.monto == dec("118")

    def test_una_compra_en_soles_pagada_desde_una_cuenta_en_dolares(self, compras):
        pago = PagoEntrada(compras.efectivo, compras.caja_usd, dec("118"), tipo_cambio=dec("3.7"))
        compra = compras.comprar(pagos=[pago])
        assert compra.pagos.get().monto_cuenta == dec("31.89")  # 118 / 3,70
        [m] = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert (m.monto, m.cuenta_id) == (dec("31.89"), compras.caja_usd.pk)

    def test_pagar_una_cuota_en_dolares_con_una_cuenta_en_soles(self, compras):
        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        cuotas = CuotasEntrada(2, compras.entorno.hoy, compras.mensual)
        compra = compras.comprar(
            [linea], moneda="USD", tipo_cambio=dec("3.6"), forma_pago="CREDITO", cuotas=cuotas
        )
        [pago] = registrar_pagos(
            compra,
            pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("59"), tipo_cambio=dec("3.65"))],
        )
        assert pago.monto_cuenta == dec("215.35")
        [m] = movimientos(origen_tipo=Origen.PAGO_COMPRA)
        assert (m.monto, m.cuenta_id) == (dec("215.35"), compras.caja.pk)
        assert [c.pagado for c in compra.cuotas.order_by("numero")] == [
            dec("59"),
            0,
        ]  # la deuda baja en dólares

    def test_anular_el_pago_devuelve_lo_que_salio_de_la_cuenta(self, compras):
        linea = LineaEntrada(compras.entorno.producto(), dec(1), dec(100))
        cuotas = CuotasEntrada(1, compras.entorno.hoy, compras.mensual)
        compra = compras.comprar(
            [linea], moneda="USD", tipo_cambio=dec("3.6"), forma_pago="CREDITO", cuotas=cuotas
        )
        [pago] = registrar_pagos(
            compra,
            pagos=[PagoEntrada(compras.efectivo, compras.caja, dec("118"), tipo_cambio=dec("3.6"))],
        )
        anular_pago(pago, motivo="Error")
        assert servicios.saldo_de(compras.caja) == dec("0")
