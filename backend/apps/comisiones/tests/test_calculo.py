"""Comisión ganada por cada comprobante: contado, crédito, devoluciones, anulaciones y dólares."""

from decimal import Decimal as D

import pytest

from apps.comisiones import calculo, servicios
from apps.comisiones.models import ComisionComprobante, MovimientoComision
from apps.mantenimiento.models import TipoCambio
from apps.seguridad.models import Usuario
from apps.ventas import cuentas_por_cobrar, notas_credito
from apps.ventas import servicios as ventas

pytestmark = pytest.mark.django_db


def org(tienda):
    return tienda.entorno.e.org_a


def ana():
    return Usuario.objects.get(username="vendedor")


def regla(tienda, alcance="GENERAL", porcentaje="3", **extra):
    return servicios.crear(org(tienda).pk, {"alcance": alcance, "porcentaje": porcentaje, **extra})


def vender(tienda, producto, cantidad=1, total=None, vendedor=True, **extra):
    total = total or f"{118 * cantidad}.00"
    datos = {"tipo_comprobante": "01", "cliente": tienda.cliente(), **extra}
    if vendedor:
        datos["vendedor_id"] = ana().pk
    return tienda.vender(
        [tienda.linea(producto, cantidad)], [tienda.cobro(tienda.efectivo, total)], **datos
    )


def plan_de(venta):
    return ComisionComprobante.objects.sin_ambito().get(comprobante=venta.comprobantes.get())


def ganado(venta):
    return calculo.ganado_por(venta.comprobantes.get())


def devolver(comp, cantidad):
    return notas_credito.LineaDevuelta(comp.lineas.get(), D(str(cantidad)))


class TestContado:
    def test_al_contado_gana_todo_al_vender(self, tienda):
        regla(tienda, porcentaje="3")
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 10})
        venta = vender(tienda, p, 2)  # venta neta 200 → 3 % = 6,00
        plan = plan_de(venta)
        assert (plan.base_neta, plan.comision_total) == (D("200.00"), D("6.00"))
        assert ganado(venta) == D("6.00")
        (mov,) = MovimientoComision.objects.sin_ambito().all()
        assert (mov.monto, mov.motivo, mov.vendedor_id) == (D("6.00"), "COBRO", ana().pk)
        assert plan.detalle[0]["porcentaje"] == "3.00" and plan.detalle[0]["comision"] == "6.00"

    def test_sin_vendedor_no_hay_comision_la_tienda_web(self, tienda):
        regla(tienda)
        p = tienda.producto(precios={"PUBLICO": "100"})
        venta = vender(tienda, p, vendedor=False)
        assert not ComisionComprobante.objects.sin_ambito().exists()
        assert ganado(venta) == 0

    def test_sin_reglas_el_plan_vale_cero_y_no_hay_movimientos(self, tienda):
        p = tienda.producto(precios={"PUBLICO": "100"})
        venta = vender(tienda, p)
        assert plan_de(venta).comision_total == 0
        assert not MovimientoComision.objects.sin_ambito().exists()

    def test_cambiar_las_reglas_despues_no_toca_lo_ya_vendido(self, tienda):
        r = regla(tienda, porcentaje="3")
        p = tienda.producto(precios={"PUBLICO": "100"})
        venta = vender(tienda, p)
        servicios.actualizar(r, {"porcentaje": "10"})
        assert plan_de(venta).comision_total == D("3.00")
        assert ganado(venta) == D("3.00")

    def test_cada_linea_usa_su_regla_mas_especifica(self, tienda):
        regla(tienda, porcentaje="2")
        cable = tienda.producto("Cable", precios={"PUBLICO": "100"}, stock={tienda.a: 10})
        mouse = tienda.producto("Mouse", precios={"PUBLICO": "50"}, stock={tienda.a: 10})
        regla(tienda, "PRODUCTO", "10", producto=cable.pk)
        venta = tienda.vender(
            [tienda.linea(cable, 1), tienda.linea(mouse, 2)],
            [tienda.cobro(tienda.efectivo, "236.00")],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
            vendedor_id=ana().pk,
        )
        # Cable 100 × 10 % = 10,00 y Mouse 100 × 2 % = 2,00.
        assert plan_de(venta).comision_total == D("12.00")
        assert ganado(venta) == D("12.00")


class TestCredito:
    def venta_a_credito(self, tienda):
        regla(tienda, porcentaje="5")
        p = tienda.producto(precios={"PUBLICO": "100", "CREDITO": "120"}, stock={tienda.a: 10})
        venta = tienda.credito(
            [tienda.linea(p, 1)], cliente=tienda.cliente("1000"), vendedor_id=ana().pk
        )
        return venta, venta.comprobantes.get()

    def esperado(self, plan, comp, cobrado):
        return (plan.comision_total * D(str(cobrado)) / comp.total).quantize(D("0.01"))

    def test_a_credito_se_gana_a_medida_que_se_cobra(self, tienda):
        venta, comp = self.venta_a_credito(tienda)
        plan = plan_de(venta)
        assert plan.comision_total > 0 and ganado(venta) == 0  # nada cobrado todavía
        cuentas_por_cobrar.registrar_abonos(comp, abonos=[tienda.cobro(tienda.efectivo, "40.00")])
        assert ganado(venta) == self.esperado(plan, comp, "40.00")
        cuentas_por_cobrar.registrar_abonos(
            comp, abonos=[tienda.cobro(tienda.efectivo, str(comp.total - D("40.00")))]
        )
        assert ganado(venta) == plan.comision_total  # todo cobrado: todo ganado

    def test_un_abono_anulado_le_quita_lo_ganado(self, tienda):
        venta, comp = self.venta_a_credito(tienda)
        (abono,) = cuentas_por_cobrar.registrar_abonos(
            comp, abonos=[tienda.cobro(tienda.efectivo, "40.00")]
        )
        assert ganado(venta) > 0
        cuentas_por_cobrar.anular_abono(abono, motivo="Error de digitación")
        assert ganado(venta) == 0
        motivos = list(MovimientoComision.objects.sin_ambito().values_list("motivo", flat=True))
        assert motivos == ["COBRO", "AJUSTE"]

    def test_anular_la_venta_a_credito_quita_todo(self, tienda):
        venta, comp = self.venta_a_credito(tienda)
        cuentas_por_cobrar.registrar_abonos(comp, abonos=[tienda.cobro(tienda.efectivo, "40.00")])
        ventas.anular_comprobante(comp, motivo="El cliente no la quiso")
        assert ganado(venta) == 0


class TestDevolucionesYAnulaciones:
    def test_una_nota_de_credito_baja_la_comision_de_lo_devuelto(self, tienda):
        regla(tienda, porcentaje="3")
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 10})
        venta = vender(tienda, p, 2)  # gana 6,00
        comp = venta.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[devolver(comp, 1)],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        assert ganado(venta) == D("3.00")
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[devolver(comp, 1)],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        assert ganado(venta) == 0

    def test_anular_el_comprobante_quita_la_comision(self, tienda):
        regla(tienda, porcentaje="3")
        p = tienda.producto(precios={"PUBLICO": "100"})
        venta = vender(tienda, p)
        ventas.anular_comprobante(venta.comprobantes.get(), motivo="Error")
        assert ganado(venta) == 0
        assert MovimientoComision.objects.sin_ambito().last().motivo == "ANULACION"

    def test_recalcular_dos_veces_no_duplica_nada(self, tienda):
        regla(tienda, porcentaje="3")
        p = tienda.producto(precios={"PUBLICO": "100"})
        venta = vender(tienda, p)
        comp = venta.comprobantes.get()
        assert calculo.recalcular(comp) == 0 and calculo.recalcular(comp) == 0
        assert MovimientoComision.objects.sin_ambito().count() == 1


class TestDolares:
    def test_la_comision_se_calcula_en_soles(self, tienda):
        TipoCambio.objects.sin_ambito().create(
            organizacion=org(tienda),
            fecha=tienda.entorno.hoy,
            fuente="SUNAT",
            compra=D("3.7000"),
            venta=D("3.7500"),
        )
        regla(tienda, porcentaje="3")
        p = tienda.producto(costo="185", precios={"PUBLICO": "370"})
        venta = tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            moneda="USD",
            tipo_comprobante="01",
            cliente=tienda.cliente(),
            vendedor_id=ana().pk,
        )
        # 100 dólares netos = 370 soles; 3 % = 11,10 soles.
        assert plan_de(venta).base_neta == D("370.00")
        assert ganado(venta) == D("11.10")


class TestNoFrenaLaVenta:
    def test_si_el_calculo_falla_la_venta_sale_igual(self, tienda, monkeypatch):
        regla(tienda)

        def roto(*_a, **_k):
            raise RuntimeError("fallo de prueba")

        monkeypatch.setattr(calculo, "alta_de_venta", roto)
        p = tienda.producto(precios={"PUBLICO": "100"})
        venta = vender(tienda, p)
        assert venta.comprobantes.exists()
        assert not ComisionComprobante.objects.sin_ambito().exists()
