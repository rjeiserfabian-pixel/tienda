"""Ventas a crédito: cuotas por comprobante, límite del cliente, abonos y su reversión."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.caja.models import MovimientoCaja, Origen
from apps.caja.servicios import saldo_de
from apps.core.exceptions import DocumentoYaAnulado, ErrorDominio
from apps.inventario.models import SaldoStock
from apps.ventas import credito, cuentas_por_cobrar, servicios
from apps.ventas.exceptions import LimiteDeCreditoExcedido, PrecioBajoElMinimo, VentaInvalida
from apps.ventas.models import AbonoVenta, ComprobanteVenta, CuotaVenta, Venta

pytestmark = pytest.mark.django_db


@pytest.fixture
def producto(tienda):
    # Público 100, crédito 120 (sin IGV): una unidad a crédito son 141,60 con IGV.
    return tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})


def cuotas_de(comprobante):
    return list(CuotaVenta.objects.sin_ambito().filter(comprobante=comprobante).order_by("numero"))


class TestVentaACredito:
    def test_usa_el_precio_de_credito_y_deja_todo_por_cobrar(self, tienda, producto):
        venta = tienda.credito([tienda.linea(producto, 1)])
        assert venta.forma_pago == "CREDITO" and venta.total == D("141.60")
        assert venta.lista == tienda.listas["CREDITO"]
        (comp,) = venta.comprobantes.all()
        assert comp.lineas.get().precio_unitario == D("120")
        cuotas = cuotas_de(comp)
        assert [c.monto for c in cuotas] == [D("47.20")] * 3
        assert sum(c.monto for c in cuotas) == comp.total
        assert [c.fecha_vencimiento for c in cuotas][0] == tienda.entorno.hoy + timedelta(days=30)
        assert all(c.pagado == 0 for c in cuotas)
        # Salió el stock, pero no entró dinero.
        assert SaldoStock.objects.get(producto=producto, empresa=tienda.a).cantidad == D("9")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        assert not MovimientoCaja.objects.sin_ambito().exists()

    def test_con_pago_inicial_el_resto_queda_en_cuotas(self, tienda, producto):
        venta = tienda.credito(
            [tienda.linea(producto, 1)], [tienda.cobro(tienda.efectivo, "41.60")]
        )
        (comp,) = venta.comprobantes.all()
        assert sum(c.monto for c in cuotas_de(comp)) == D("100.00")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("41.60")
        assert venta.cobros.get().monto == D("41.60")

    def test_en_dos_empresas_cada_una_tiene_sus_cuotas_con_las_mismas_fechas(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30", "CREDITO": "30"})
        pb = tienda.producto(
            "Mouse", costo="20", precios={"PUBLICO": "50", "CREDITO": "50"}, stock={tienda.b: 10}
        )
        venta = tienda.credito(
            [tienda.linea(pa, 2), tienda.linea(pb, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "30.00")],
        )
        a, b = venta.comprobantes.order_by("id")
        # A vale 70,80 y B 59,00 (129,80): el crédito de 99,80 se reparte según lo que vale cada
        # comprobante.
        creditos = [sum(c.monto for c in cuotas_de(x)) for x in (a, b)]
        assert sum(creditos) == D("99.80") and creditos == [D("54.44"), D("45.36")]
        assert [c.fecha_vencimiento for c in cuotas_de(a)] == [
            c.fecha_vencimiento for c in cuotas_de(b)
        ]
        # Lo pagado al momento entra a la caja de cada empresa, en proporción.
        assert saldo_de(tienda.cajas[tienda.a.pk]) + saldo_de(tienda.cajas[tienda.b.pk]) == D(
            "30.00"
        )
        assert saldo_de(tienda.cajas[tienda.a.pk]) == a.total - creditos[0]
        assert saldo_de(tienda.cajas[tienda.b.pk]) == b.total - creditos[1]

    def test_sin_el_permiso_no_se_vende_a_credito(self, tienda, producto):
        with pytest.raises(VentaInvalida, match="permiso"):
            tienda.credito([tienda.linea(producto, 1)], puede_credito=False)

    def test_exige_un_cliente_identificado_con_credito_autorizado(self, tienda, producto):
        with pytest.raises(VentaInvalida, match="cliente identificado"):
            tienda.credito([tienda.linea(producto, 1)], cliente=None)
        with pytest.raises(VentaInvalida, match="no tiene crédito autorizado"):
            tienda.credito([tienda.linea(producto, 1)], cliente=tienda.cliente("0"))
        assert not Venta.objects.sin_ambito().exists()

    def test_exige_la_lista_de_credito_y_el_precio_de_cada_producto(self, tienda):
        sin_precio = tienda.producto("Mouse", precios={"PUBLICO": "100"})
        with pytest.raises(VentaInvalida, match="no tiene precio en la lista «Crédito»"):
            tienda.credito([tienda.linea(sin_precio, 1)])
        tienda.listas["CREDITO"].uso = "OTRA"
        tienda.listas["CREDITO"].save()
        with pytest.raises(VentaInvalida, match="lista de precios de crédito"):
            tienda.credito([tienda.linea(sin_precio, 1)])

    def test_valida_el_pago_inicial_y_las_cuotas(self, tienda, producto):
        linea = [tienda.linea(producto, 1)]
        with pytest.raises(VentaInvalida, match="menor que el total"):
            tienda.credito(linea, [tienda.cobro(tienda.efectivo, "141.60")])
        with pytest.raises(VentaInvalida, match="cuotas"):
            tienda.credito(linea, cuotas=tienda.cuotas(0))
        with pytest.raises(VentaInvalida, match="cuotas"):
            tienda.credito(linea, cuotas=tienda.cuotas(61))
        with pytest.raises(VentaInvalida, match="antes de la venta"):
            tienda.credito(linea, cuotas=tienda.cuotas(3, dias=-1))
        with pytest.raises(VentaInvalida, match="cuotas"):
            tienda.credito(linea, cuotas=None)
        with pytest.raises(VentaInvalida, match="muy pequeño"):
            tienda.credito(
                linea, [tienda.cobro(tienda.efectivo, "141.55")], cuotas=tienda.cuotas(12)
            )
        assert not Venta.objects.sin_ambito().exists()


class TestPrecioDeCredito:
    @pytest.fixture
    def con_descuento(self, tienda):
        # Crédito 120; el descuento (90) y el técnico (80) están por debajo del crédito.
        return tienda.producto(
            costo="50",
            precios={"PUBLICO": "100", "CREDITO": "120", "DESCUENTO": "90", "TECNICO": "80"},
        )

    def test_a_credito_no_se_puede_bajar_del_precio_de_credito(self, tienda, con_descuento):
        with pytest.raises(PrecioBajoElMinimo, match="precio de crédito"):
            tienda.credito([tienda.linea(con_descuento, 1, precio_unitario=D("100"))])
        assert not Venta.objects.sin_ambito().exists()

    def test_ni_siquiera_con_el_permiso_de_vender_bajo_el_minimo(self, tienda, con_descuento):
        with pytest.raises(PrecioBajoElMinimo, match="precio de crédito"):
            tienda.credito(
                [tienda.linea(con_descuento, 1, precio_unitario=D("119.99"))],
                puede_vender_bajo_minimo=True,
            )

    def test_el_precio_de_credito_o_mayor_si_se_puede(self, tienda, con_descuento):
        justo = tienda.credito([tienda.linea(con_descuento, 1, precio_unitario=D("120"))])
        assert justo.lineas.get().precio_unitario == D("120")
        mayor = tienda.credito(
            [tienda.linea(con_descuento, 1, precio_unitario=D("150"))],
            cliente=tienda.cliente("5000"),
        )
        assert mayor.lineas.get().precio_unitario == D("150")


class TestCreditoSinTope:
    def test_el_cliente_sin_tope_compra_a_credito_sin_importar_cuanto_deba(self, tienda, producto):
        cliente = tienda.cliente("0", credito_sin_limite=True)
        cliente.credito_sin_limite = True
        cliente.save()
        for _ in range(3):
            tienda.credito([tienda.linea(producto, 1)], cliente=cliente)
        assert credito.deuda_en_soles(cliente) == D("424.80")
        assert credito.situacion(cliente) == {
            "limite": None,
            "sin_limite": True,
            "deuda": D("424.80"),
            "disponible": None,
        }

    def test_sin_tope_no_es_lo_mismo_que_sin_credito(self, tienda, producto):
        cliente = tienda.cliente("0")
        assert not credito.tiene_credito(cliente)
        with pytest.raises(VentaInvalida, match="no tiene crédito autorizado"):
            tienda.credito([tienda.linea(producto, 1)], cliente=cliente)


class TestLimite:
    def test_no_pasa_del_limite_del_cliente(self, tienda, producto):
        cliente = tienda.cliente("200")
        tienda.credito([tienda.linea(producto, 1)], cliente=cliente)  # 141,60 de 200
        assert credito.deuda_en_soles(cliente) == D("141.60")
        with pytest.raises(LimiteDeCreditoExcedido, match="solo se le pueden vender S/ 58.40"):
            tienda.credito([tienda.linea(producto, 1)], cliente=cliente)

    def test_lo_que_ya_pago_vuelve_a_dejarle_disponible(self, tienda, producto):
        cliente = tienda.cliente("200")
        venta = tienda.credito([tienda.linea(producto, 1)], cliente=cliente)
        (comp,) = venta.comprobantes.all()
        cuentas_por_cobrar.registrar_abonos(comp, abonos=[tienda.cobro(tienda.efectivo, "100.00")])
        assert credito.situacion(cliente) == {
            "limite": D("200.00"),
            "sin_limite": False,
            "deuda": D("41.60"),
            "disponible": D("158.40"),
        }
        tienda.credito([tienda.linea(producto, 1)], cliente=cliente)

    def test_con_el_permiso_especial_se_puede_pasar_el_limite(self, tienda, producto):
        cliente = tienda.cliente("100")
        with pytest.raises(LimiteDeCreditoExcedido):
            tienda.credito([tienda.linea(producto, 1)], cliente=cliente)
        venta = tienda.credito(
            [tienda.linea(producto, 1)], cliente=cliente, puede_exceder_limite=True
        )
        assert venta.total == D("141.60")

    def test_el_pago_inicial_no_cuenta_para_el_limite(self, tienda, producto):
        cliente = tienda.cliente("100")
        tienda.credito(
            [tienda.linea(producto, 1)], [tienda.cobro(tienda.efectivo, "41.60")], cliente=cliente
        )

    def test_una_venta_anulada_ya_no_cuenta_en_la_deuda(self, tienda, producto):
        cliente = tienda.cliente("200")
        venta = tienda.credito([tienda.linea(producto, 1)], cliente=cliente)
        servicios.anular_venta(venta, motivo="Se devolvió")
        assert credito.deuda_en_soles(cliente) == D("0.00")

    def test_la_deuda_en_dolares_se_convierte_a_soles(self, tienda):
        from apps.mantenimiento.models import TipoCambio

        TipoCambio.objects.sin_ambito().create(
            organizacion=tienda.entorno.e.org_a,
            fecha=tienda.entorno.hoy,
            fuente="SUNAT",
            compra=D("3.7000"),
            venta=D("3.7500"),
        )
        # Crédito de 370 soles = 100 USD; con IGV 118 USD = 436,60 soles.
        p = tienda.producto("Laptop", costo="185", precios={"PUBLICO": "370", "CREDITO": "370"})
        cuenta_usd = tienda.compras.caja_usd
        assert cuenta_usd.moneda == "USD"
        cliente = tienda.cliente("1000")
        tienda.credito([tienda.linea(p, 1)], cliente=cliente, moneda="USD")
        assert credito.deuda_en_soles(cliente) == D("436.60")


class TestAbonos:
    @pytest.fixture
    def comprobante(self, tienda, producto):
        venta = tienda.credito([tienda.linea(producto, 1)])  # 3 cuotas de 47,20
        return venta.comprobantes.get()

    def test_un_abono_cubre_las_cuotas_mas_antiguas_primero(self, tienda, comprobante):
        (abono,) = cuentas_por_cobrar.registrar_abonos(
            comprobante, abonos=[tienda.cobro(tienda.efectivo, "60.00")]
        )
        c1, c2, c3 = cuotas_de(comprobante)
        assert (c1.pagado, c2.pagado, c3.pagado) == (D("47.20"), D("12.80"), D("0"))
        assert abono.cuenta == tienda.cajas[tienda.a.pk]
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("60.00")
        mov = MovimientoCaja.objects.sin_ambito().get(origen_tipo=Origen.ABONO_VENTA)
        assert mov.medio_pago == tienda.efectivo and mov.origen_id == abono.pk
        assert cuentas_por_cobrar.saldo_de(comprobante) == D("81.60")

    def test_se_puede_elegir_la_cuota_y_pagar_con_varios_metodos(self, tienda, comprobante):
        _, _, c3 = cuotas_de(comprobante)
        abonos = cuentas_por_cobrar.registrar_abonos(
            comprobante,
            abonos=[
                tienda.cobro(tienda.efectivo, "20.00"),
                tienda.cobro(tienda.yape, "27.20", referencia="OP-9"),
            ],
            cuota_ids=[c3.pk],
        )
        assert len(abonos) == 2
        assert cuotas_de(comprobante)[2].pagado == D("47.20")
        assert saldo_de(tienda.billeteras[tienda.a.pk]) == D("27.20")

    def test_el_efectivo_da_vuelto(self, tienda, comprobante):
        (abono,) = cuentas_por_cobrar.registrar_abonos(
            comprobante, abonos=[tienda.cobro(tienda.efectivo, "47.20", recibido=D("50.00"))]
        )
        assert (abono.recibido, abono.vuelto) == (D("50.00"), D("2.80"))
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("47.20")

    def test_no_se_cobra_mas_de_lo_que_se_debe(self, tienda, comprobante):
        with pytest.raises(VentaInvalida, match="más de lo que se debe"):
            cuentas_por_cobrar.registrar_abonos(
                comprobante, abonos=[tienda.cobro(tienda.efectivo, "141.61")]
            )
        cuentas_por_cobrar.registrar_abonos(
            comprobante, abonos=[tienda.cobro(tienda.efectivo, "141.60")]
        )
        with pytest.raises(VentaInvalida, match="por completo"):
            cuentas_por_cobrar.registrar_abonos(
                comprobante, abonos=[tienda.cobro(tienda.efectivo, "1")]
            )

    def test_la_cuota_elegida_no_admite_mas_de_su_saldo(self, tienda, comprobante):
        c1 = cuotas_de(comprobante)[0]
        with pytest.raises(VentaInvalida, match="solo tienen pendiente"):
            cuentas_por_cobrar.registrar_abonos(
                comprobante, abonos=[tienda.cobro(tienda.efectivo, "50.00")], cuota_ids=[c1.pk]
            )

    def test_todo_o_nada_si_un_abono_no_es_valido(self, tienda, comprobante):
        with pytest.raises(VentaInvalida, match="número de operación"):
            cuentas_por_cobrar.registrar_abonos(
                comprobante,
                abonos=[tienda.cobro(tienda.efectivo, "10.00"), tienda.cobro(tienda.yape, "10.00")],
            )
        assert not AbonoVenta.objects.sin_ambito().exists()
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")

    def test_una_venta_al_contado_no_se_abona(self, tienda, producto):
        venta = tienda.vender(
            [tienda.linea(producto, 1)], [tienda.cobro(tienda.efectivo, "118.00")]
        )
        with pytest.raises(VentaInvalida, match="al contado"):
            cuentas_por_cobrar.registrar_abonos(
                venta.comprobantes.get(), abonos=[tienda.cobro(tienda.efectivo, "1.00")]
            )

    def test_anular_un_abono_devuelve_el_dinero_y_la_deuda(self, tienda, comprobante):
        (abono,) = cuentas_por_cobrar.registrar_abonos(
            comprobante, abonos=[tienda.cobro(tienda.efectivo, "60.00")]
        )
        cuentas_por_cobrar.anular_abono(abono, motivo="Se equivocó de cliente")
        assert [c.pagado for c in cuotas_de(comprobante)] == [D("0")] * 3
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        abono.refresh_from_db()
        assert abono.anulado and abono.motivo_anulacion
        with pytest.raises(DocumentoYaAnulado):
            cuentas_por_cobrar.anular_abono(abono, motivo="Otra vez")
        with pytest.raises(ErrorDominio):
            cuentas_por_cobrar.anular_abono(abono, motivo=" ")

    def test_anular_el_comprobante_devuelve_stock_cobros_y_abonos(self, tienda, producto):
        venta = tienda.credito(
            [tienda.linea(producto, 1)], [tienda.cobro(tienda.efectivo, "41.60")]
        )
        comp = venta.comprobantes.get()
        cuentas_por_cobrar.registrar_abonos(comp, abonos=[tienda.cobro(tienda.efectivo, "30.00")])
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("71.60")
        servicios.anular_venta(venta, motivo="Devolución total")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        assert SaldoStock.objects.get(producto=producto, empresa=tienda.a).cantidad == D("10")
        assert AbonoVenta.objects.sin_ambito().get().anulado
        assert ComprobanteVenta.objects.sin_ambito().get().estado == "ANULADO"
        with pytest.raises(VentaInvalida, match="anulado"):
            cuentas_por_cobrar.registrar_abonos(
                comp, abonos=[tienda.cobro(tienda.efectivo, "1.00")]
            )

    def test_cada_empresa_cobra_en_su_caja(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30", "CREDITO": "30"})
        pb = tienda.producto(
            "Mouse", costo="20", precios={"PUBLICO": "50", "CREDITO": "50"}, stock={tienda.b: 10}
        )
        venta = tienda.credito([tienda.linea(pa, 2), tienda.linea(pb, 1, empresa=tienda.b)])
        a, b = venta.comprobantes.order_by("id")
        cuentas_por_cobrar.registrar_abonos(b, abonos=[tienda.cobro(tienda.efectivo, "20.00")])
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("20.00")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        assert cuentas_por_cobrar.saldo_de(a) == D("70.80")
