"""Registrar y anular ventas: una empresa, dos empresas, precios, cobros y deshacer."""

from decimal import Decimal as D

import pytest

from apps.caja.models import MovimientoCaja, Origen
from apps.caja.servicios import saldo_de
from apps.core.exceptions import DocumentoYaAnulado, ErrorDominio
from apps.inventario.exceptions import StockInsuficiente
from apps.inventario.models import SaldoStock, TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import Cliente, CuentaFinanciera, SerieComprobante, TipoCambio
from apps.organizacion.models import ConfiguracionEmpresa
from apps.ventas import servicios
from apps.ventas.exceptions import (
    CuentaDeCobroNoConfigurada,
    PrecioBajoElMinimo,
    VentaInvalida,
)
from apps.ventas.models import CobroVenta, ComprobanteVenta, LineaVenta, Venta

pytestmark = pytest.mark.django_db


def stock(tienda, producto, empresa):
    return SaldoStock.objects.get(
        empresa=empresa, almacen=tienda.almacen(empresa), producto=producto
    ).cantidad


def cliente(tienda, tipo="RUC", numero="20100000017", **extra):
    return Cliente.objects.sin_ambito().create(
        organizacion=tienda.entorno.e.org_a,
        tipo_documento=tipo,
        numero_documento=numero,
        nombre="Ferretería El Sol",
        **extra,
    )


class TestUnaEmpresa:
    def test_vende_y_deja_todo_al_dia(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        venta = tienda.vender([tienda.linea(p, 2)], [tienda.cobro(tienda.efectivo, "236.00")])

        assert venta.total == D("236.00") and venta.numero == 1
        (comp,) = venta.comprobantes.all()
        assert comp.numero_completo == "N001-00000001"
        assert (comp.op_gravada, comp.igv, comp.total) == (D("200.00"), D("36.00"), D("236.00"))
        (linea,) = comp.lineas.all()
        assert (linea.precio_lista, linea.precio_unitario) == (D("100"), D("100"))
        assert linea.tasa_igv == D("18.00")
        # Salió al costo y el margen es lo vendido sin IGV menos el costo.
        assert (linea.costo_unitario, linea.costo_total) == (D("50"), D("100.00"))
        assert linea.margen(venta.tipo_cambio) == D("100.00")
        assert stock(tienda, p, tienda.a) == D("8")
        # El cobro entró a la caja de la empresa.
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("236.00")
        mov = MovimientoCaja.objects.get(origen_tipo=Origen.COBRO_VENTA)
        assert mov.medio_pago == tienda.efectivo and mov.monto == D("236.00")

    def test_el_efectivo_da_vuelto_y_la_caja_solo_recibe_lo_cobrado(self, tienda):
        p = tienda.producto()
        venta = tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "118.00", recibido=D("200.00"))],
        )
        cobro = venta.cobros.get()
        assert (cobro.recibido, cobro.vuelto, cobro.monto) == (D("200.00"), D("82.00"), D("118.00"))
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("118.00")

    def test_varios_metodos_van_a_su_cuenta(self, tienda):
        p = tienda.producto()
        tienda.vender(
            [tienda.linea(p, 1)],
            [
                tienda.cobro(tienda.efectivo, "18.00"),
                tienda.cobro(tienda.yape, "100.00", referencia="OP-77"),
            ],
        )
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("18.00")
        assert saldo_de(tienda.billeteras[tienda.a.pk]) == D("100.00")

    def test_el_metodo_con_referencia_la_exige(self, tienda):
        p = tienda.producto()
        with pytest.raises(VentaInvalida, match="número de operación"):
            tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.yape, "118.00")])

    def test_solo_el_efectivo_lleva_recibido(self, tienda):
        p = tienda.producto()
        with pytest.raises(VentaInvalida, match="efectivo"):
            tienda.vender(
                [tienda.linea(p, 1)],
                [tienda.cobro(tienda.yape, "118.00", referencia="1", recibido=D("200"))],
            )

    def test_los_cobros_deben_sumar_el_total(self, tienda):
        p = tienda.producto()
        with pytest.raises(VentaInvalida, match="sumar"):
            tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "100.00")])
        assert not Venta.objects.exists()

    def test_numera_sin_saltos(self, tienda):
        p = tienda.producto()
        for _ in range(3):
            tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")])
        numeros = ComprobanteVenta.objects.order_by("numero").values_list("numero", flat=True)
        assert list(numeros) == [1, 2, 3]
        internos = Venta.objects.order_by("numero").values_list("numero", flat=True)
        assert list(internos) == [1, 2, 3]

    def test_el_mismo_producto_en_dos_lineas_mantiene_cada_costo(self, tienda):
        p = tienda.producto(costo="50")
        venta = tienda.vender(
            [tienda.linea(p, 1), tienda.linea(p, 2, precio_unitario=D("120"))],
            [tienda.cobro(tienda.efectivo, "401.20")],
        )
        lineas = list(LineaVenta.objects.filter(venta=venta).order_by("orden"))
        assert [(ln.cantidad, ln.precio_unitario, ln.costo_total) for ln in lineas] == [
            (D("1"), D("100"), D("50.00")),
            (D("2"), D("120"), D("100.00")),
        ]

    def test_un_servicio_no_mueve_stock(self, tienda):
        s = tienda.producto(
            "Instalación", costo="20", stock={}, tipo="SERVICIO", controla_stock=False
        )
        venta = tienda.vender(
            [servicios.LineaEntrada(s, D("1"), tienda.a)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        linea = venta.lineas.get()
        assert linea.almacen is None and linea.movimiento is None
        assert linea.costo_total == D("20.00")


class TestDosEmpresas:
    @pytest.fixture
    def carrito(self, tienda):
        pa = tienda.producto(
            "Cable HDMI", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10}
        )
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        return pa, pb, [tienda.linea(pa, 2), tienda.linea(pb, 1, empresa=tienda.b)]

    def test_emite_un_comprobante_por_empresa(self, tienda, carrito):
        pa, pb, lineas = carrito
        # A: 2×30 = 60 + 10,80 de IGV = 70,80. B: 50 + 9 = 59,00. Total 129,80.
        venta = tienda.vender(lineas, [tienda.cobro(tienda.efectivo, "129.80")])
        a, b = venta.comprobantes.order_by("id")
        assert (a.empresa, a.serie, a.numero, a.total) == (tienda.a, "N001", 1, D("70.80"))
        assert (b.empresa, b.serie, b.numero, b.total) == (tienda.b, "N002", 1, D("59.00"))
        assert (a.igv, b.igv) == (D("10.80"), D("9.00"))
        assert venta.total == D("129.80")
        assert stock(tienda, pa, tienda.a) == D("8")
        assert stock(tienda, pb, tienda.b) == D("9")

    def test_el_cobro_se_reparte_y_cada_empresa_cobra_lo_suyo(self, tienda, carrito):
        _, _, lineas = carrito
        venta = tienda.vender(lineas, [tienda.cobro(tienda.efectivo, "129.80", recibido=D("200"))])
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("70.80")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("59.00")
        partes = list(venta.cobros.order_by("id"))
        assert [p.monto for p in partes] == [D("70.80"), D("59.00")]
        # El vuelto se anota una sola vez, en el primer pedazo.
        assert [(p.recibido, p.vuelto) for p in partes] == [(D("200"), D("70.20")), (None, D("0"))]

    def test_cada_metodo_entra_a_la_cuenta_de_la_empresa_del_comprobante(self, tienda, carrito):
        _, _, lineas = carrito
        tienda.vender(
            lineas,
            [
                tienda.cobro(tienda.efectivo, "20.80"),
                tienda.cobro(tienda.yape, "109.00", referencia="OP-1"),
            ],
        )
        # A cobra 70,80: 20,80 en efectivo y 50 de Yape. B cobra 59 de Yape.
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("20.80")
        assert saldo_de(tienda.billeteras[tienda.a.pk]) == D("50.00")
        assert saldo_de(tienda.billeteras[tienda.b.pk]) == D("59.00")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("0")

    def test_la_empresa_principal_va_primero_aunque_la_linea_sea_de_la_otra(self, tienda, carrito):
        pa, pb, _ = carrito
        venta = tienda.vender(
            [tienda.linea(pb, 1, empresa=tienda.b), tienda.linea(pa, 2)],
            [tienda.cobro(tienda.efectivo, "129.80")],
        )
        assert venta.comprobantes.order_by("id").first().empresa == tienda.a

    def test_vender_stock_de_otra_empresa_exige_permiso(self, tienda, carrito):
        _, _, lineas = carrito
        with pytest.raises(VentaInvalida, match="permiso"):
            tienda.vender(
                lineas,
                [tienda.cobro(tienda.efectivo, "129.80")],
                puede_vender_stock_otra_empresa=False,
            )
        assert not Venta.objects.exists()

    def test_si_una_empresa_no_tiene_stock_no_queda_nada_a_medias(self, tienda, carrito):
        pa, pb, _ = carrito
        serie = tienda.series[(tienda.a.pk, "NV")]
        with pytest.raises(StockInsuficiente):
            tienda.vender(
                [tienda.linea(pa, 2), tienda.linea(pb, 11, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "719.80")],
            )
        assert not Venta.objects.exists() and not CobroVenta.objects.exists()
        assert stock(tienda, pa, tienda.a) == D("10")
        assert SerieComprobante.objects.get(pk=serie.pk).ultimo_numero == 0
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")

    def test_sugiere_la_empresa_principal_si_tiene_stock(self, tienda):
        p = tienda.producto(stock={tienda.a: 5, tienda.b: 8})
        sugerido = servicios.sugerir_surtidor(p, D("3"), [tienda.b, tienda.a])
        assert sugerido == (tienda.a, tienda.almacen(tienda.a))

    def test_sugiere_la_otra_si_la_principal_no_alcanza(self, tienda):
        p = tienda.producto(stock={tienda.a: 2, tienda.b: 8})
        assert servicios.sugerir_surtidor(p, D("3"), [tienda.a, tienda.b])[0] == tienda.b
        assert servicios.sugerir_surtidor(p, D("9"), [tienda.a, tienda.b]) is None


class TestPrecios:
    @pytest.fixture
    def producto(self, tienda):
        # Lista 100; descuento 90; técnico 80; costo 60 → mínimo 80; con permiso, hasta 60.
        return tienda.producto(
            costo="60", precios={"PUBLICO": "100", "DESCUENTO": "90", "TECNICO": "80"}
        )

    def vender(self, tienda, p, precio, **extra):
        total = (D(precio) * D("1.18")).quantize(D("0.01"))
        return tienda.vender(
            [tienda.linea(p, 1, precio_unitario=D(precio))],
            [tienda.cobro(tienda.efectivo, total)],
            **extra,
        )

    def test_subir_el_precio_es_libre(self, tienda, producto):
        linea = self.vender(tienda, producto, "150").lineas.get()
        assert (linea.precio_lista, linea.precio_unitario, linea.bajo_minimo) == (
            D("100"),
            D("150"),
            False,
        )

    def test_bajar_hasta_el_minimo_se_puede(self, tienda, producto):
        linea = self.vender(tienda, producto, "80").lineas.get()
        assert linea.precio_minimo == D("80") and not linea.bajo_minimo

    def test_bajo_el_minimo_no_se_puede_sin_permiso(self, tienda, producto):
        with pytest.raises(PrecioBajoElMinimo, match="mínimo"):
            self.vender(tienda, producto, "79.99")
        assert not Venta.objects.exists()
        assert stock(tienda, producto, tienda.a) == D("10")

    def test_con_permiso_se_puede_bajar_hasta_el_costo_y_queda_marcado(self, tienda, producto):
        linea = self.vender(tienda, producto, "60", puede_vender_bajo_minimo=True).lineas.get()
        assert linea.bajo_minimo and linea.precio_unitario == D("60")

    def test_nunca_bajo_el_costo_ni_con_permiso(self, tienda, producto):
        with pytest.raises(PrecioBajoElMinimo, match="costo"):
            self.vender(tienda, producto, "59.99", puede_vender_bajo_minimo=True)

    def test_sin_listas_de_descuento_el_piso_es_el_costo(self, tienda):
        p = tienda.producto(costo="70", precios={"PUBLICO": "100"})
        self.vender(tienda, p, "70")
        with pytest.raises(PrecioBajoElMinimo):
            self.vender(tienda, p, "69.99")

    def test_precio_en_cero_o_sin_precio_en_la_lista(self, tienda):
        p = tienda.producto(precios={"PUBLICO": "100"})
        with pytest.raises(VentaInvalida, match="precio"):
            tienda.vender(
                [tienda.linea(p, 1, precio_unitario=D("0"))],
                [tienda.cobro(tienda.efectivo, "0.01")],
            )
        with pytest.raises(VentaInvalida, match="no tiene precio"):
            tienda.vender(
                [tienda.linea(p, 1)],
                [tienda.cobro(tienda.efectivo, "118.00")],
                lista=tienda.listas["TECNICO"],
                puede_precio_tecnico=True,
            )

    def test_las_listas_de_descuento_y_tecnico_piden_permiso(self, tienda, producto):
        total = [tienda.cobro(tienda.efectivo, "94.40")]
        with pytest.raises(VentaInvalida, match="descuento"):
            tienda.vender([tienda.linea(producto, 1)], total, lista=tienda.listas["DESCUENTO"])
        with pytest.raises(VentaInvalida, match="técnico"):
            tienda.vender([tienda.linea(producto, 1)], total, lista=tienda.listas["TECNICO"])
        venta = tienda.vender(
            [tienda.linea(producto, 1)],
            [tienda.cobro(tienda.efectivo, "106.20")],
            lista=tienda.listas["DESCUENTO"],
            puede_descontar=True,
        )
        assert venta.lineas.get().precio_lista == D("90")

    def test_la_lista_de_credito_no_aplica_al_contado(self, tienda, producto):
        with pytest.raises(VentaInvalida, match="crédito"):
            tienda.vender(
                [tienda.linea(producto, 1)],
                [tienda.cobro(tienda.efectivo, "118.00")],
                lista=tienda.listas["CREDITO"],
            )


class TestIgvYComprobantes:
    def test_en_la_amazonia_un_cliente_de_la_region_no_paga_igv(self, tienda):
        fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=tienda.a)
        fila.regimen_igv = "AMAZONIA"
        fila.save()
        p = tienda.producto()
        venta = tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "100.00")],
            cliente=cliente(tienda, zona="DENTRO"),
        )
        comp = venta.comprobantes.get()
        assert (comp.op_exonerada, comp.igv, comp.total) == (D("100.00"), D("0.00"), D("100.00"))
        # Fuera de la región sí se grava.
        fuera = tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            cliente=cliente(tienda, "DNI", "12345678", zona="FUERA"),
        )
        assert fuera.comprobantes.get().igv == D("18.00")

    def test_la_factura_exige_cliente_con_ruc(self, tienda):
        p = tienda.producto()
        cobro = [tienda.cobro(tienda.efectivo, "118.00")]
        with pytest.raises(VentaInvalida, match="RUC"):
            tienda.vender([tienda.linea(p, 1)], cobro, tipo_comprobante="01")
        with pytest.raises(VentaInvalida, match="RUC"):
            tienda.vender(
                [tienda.linea(p, 1)],
                cobro,
                tipo_comprobante="01",
                cliente=cliente(tienda, "DNI", "12345678"),
            )
        venta = tienda.vender(
            [tienda.linea(p, 1)], cobro, tipo_comprobante="01", cliente=cliente(tienda)
        )
        assert venta.comprobantes.get().numero_completo == "F001-00000001"
        assert venta.cliente_nombre == "Ferretería El Sol"

    def test_la_boleta_grande_exige_cliente_identificado(self, tienda):
        p = tienda.producto(costo="400", precios={"PUBLICO": "600"})
        cobro = [tienda.cobro(tienda.efectivo, "708.00")]
        with pytest.raises(VentaInvalida, match="identificado"):
            tienda.vender([tienda.linea(p, 1)], cobro, tipo_comprobante="03")
        venta = tienda.vender(
            [tienda.linea(p, 1)],
            cobro,
            tipo_comprobante="03",
            cliente=cliente(tienda, "DNI", "12345678"),
        )
        assert venta.comprobantes.get().serie == "B001"

    def test_la_boleta_chica_va_a_clientes_varios(self, tienda):
        p = tienda.producto()
        venta = tienda.vender(
            [tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")], tipo_comprobante="03"
        )
        assert venta.cliente is None and venta.cliente_nombre == "CLIENTES VARIOS"

    def test_solo_se_emiten_los_tipos_de_venta(self, tienda):
        p = tienda.producto()
        with pytest.raises(VentaInvalida, match="tipo de comprobante"):
            tienda.vender(
                [tienda.linea(p, 1)],
                [tienda.cobro(tienda.efectivo, "118.00")],
                tipo_comprobante="07",
            )

    def test_la_empresa_sin_serie_no_puede_vender(self, tienda):
        p = tienda.producto()
        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("NV")
        ).update(estado="INACTIVO")
        with pytest.raises(VentaInvalida, match="serie"):
            tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")])

    def test_la_cuenta_de_cobro_sin_configurar_avisa(self, tienda):
        p = tienda.producto()
        with pytest.raises(CuentaDeCobroNoConfigurada, match="Tarjeta"):
            tienda.vender(
                [tienda.linea(p, 1)], [tienda.cobro(tienda.tarjeta, "118.00", referencia="V-1")]
            )

    def test_sin_sesion_de_caja_no_se_vende(self, tienda):
        CuentaFinanciera.objects.sin_ambito().filter(pk=tienda.cajas[tienda.a.pk].pk).update(
            exige_sesion=True
        )
        p = tienda.producto()
        with pytest.raises(ErrorDominio, match="sesión"):
            tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")])
        assert not Venta.objects.exists()
        assert stock(tienda, p, tienda.a) == D("10")


class TestDolares:
    def test_vende_en_dolares_con_el_tipo_de_cambio_de_compra(self, tienda):
        TipoCambio.objects.sin_ambito().create(
            organizacion=tienda.entorno.e.org_a,
            fecha=tienda.entorno.hoy,
            fuente="SUNAT",
            compra=D("3.7000"),
            venta=D("3.7500"),
        )
        p = tienda.producto(costo="185", precios={"PUBLICO": "370"})
        # Lista de 370 soles = 100 dólares al tipo de cambio de compra (3,70).
        venta = tienda.vender(
            [tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")], moneda="USD"
        )
        assert venta.moneda == "USD" and venta.tipo_cambio == D("3.7000")
        linea = venta.lineas.get()
        assert linea.precio_unitario == D("100.000000") and venta.total == D("118.00")
        # El costo queda en soles y el margen se mide en soles.
        assert linea.costo_total == D("185.00")
        assert linea.margen(venta.tipo_cambio) == D("185.00")
        assert saldo_de(tienda.compras.caja_usd) == D("118.00")


class TestAnular:
    def vender_dos(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        venta = tienda.vender(
            [tienda.linea(pa, 2), tienda.linea(pb, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "129.80")],
        )
        return pa, pb, venta

    def test_anular_un_comprobante_devuelve_su_stock_y_su_dinero(self, tienda):
        pa, pb, venta = self.vender_dos(tienda)
        _, b = venta.comprobantes.order_by("id")
        servicios.anular_comprobante(b, motivo="El cliente se arrepintió del mouse")

        assert stock(tienda, pb, tienda.b) == D("10")
        assert stock(tienda, pa, tienda.a) == D("8")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("0")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("70.80")
        venta.refresh_from_db()
        assert venta.estado == Venta.Estado.EMITIDO  # el otro comprobante sigue vigente
        b.refresh_from_db()
        assert b.estado == ComprobanteVenta.Estado.ANULADO and b.numero == 1

    def test_al_anular_el_ultimo_la_venta_queda_anulada(self, tienda):
        pa, pb, venta = self.vender_dos(tienda)
        servicios.anular_venta(venta, motivo="Venta duplicada")
        venta.refresh_from_db()
        assert venta.estado == Venta.Estado.ANULADO
        assert stock(tienda, pa, tienda.a) == D("10")
        assert stock(tienda, pb, tienda.b) == D("10")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("0")

    def test_la_numeracion_no_se_reutiliza(self, tienda):
        p = tienda.producto()
        primera = tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")])
        servicios.anular_venta(primera, motivo="Error de digitación")
        segunda = tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")])
        assert segunda.comprobantes.get().numero == 2

    def test_no_se_anula_dos_veces_ni_sin_motivo(self, tienda):
        p = tienda.producto()
        venta = tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "118.00")])
        (comp,) = venta.comprobantes.all()
        with pytest.raises(ErrorDominio):
            servicios.anular_comprobante(comp, motivo="  ")
        servicios.anular_comprobante(comp, motivo="Error")
        with pytest.raises(DocumentoYaAnulado):
            servicios.anular_comprobante(comp, motivo="Otra vez")
        with pytest.raises(ErrorDominio):
            servicios.anular_venta(venta, motivo="Otra vez")

    def test_las_series_vuelven_a_estar_disponibles(self, tienda):
        p = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        registrar_movimiento(
            empresa=tienda.a,
            almacen=tienda.almacen(tienda.a),
            tipo=TipoMovimiento.ENTRADA,
            origen="COMPRA",
            fecha=tienda.entorno.hoy,
            lineas=[LineaNueva(p, D("2"), D("500"), series=("IMEI-1", "IMEI-2"))],
        )
        cobro = [tienda.cobro(tienda.efectivo, "944.00")]
        venta = tienda.vender(
            [tienda.linea(p, 1, series=("IMEI-1",))],
            cobro,
            tipo_comprobante="03",
            cliente=cliente(tienda, "DNI", "12345678"),
        )
        assert venta.lineas.get().series == ["IMEI-1"]
        servicios.anular_venta(venta, motivo="Devolución inmediata")
        otra = tienda.vender(
            [tienda.linea(p, 1, series=("IMEI-1",))],
            cobro,
            cliente=cliente(tienda, "DNI", "87654321"),
        )
        assert otra.lineas.get().series == ["IMEI-1"]


class TestMensajesDeSerie:
    """Una serie que no se puede vender dice por qué y qué hacer."""

    @pytest.fixture
    def celular(self, tienda):
        p = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        for empresa, series in ((tienda.a, ("A-1",)), (tienda.b, ("B-1",))):
            registrar_movimiento(
                empresa=empresa,
                almacen=tienda.almacen(empresa),
                tipo=TipoMovimiento.ENTRADA,
                origen="COMPRA",
                fecha=tienda.entorno.hoy,
                lineas=[LineaNueva(p, D("1"), D("500"), series=series)],
            )
        return p

    def vender(self, tienda, producto, serie):
        return tienda.vender(
            [tienda.linea(producto, 1, series=(serie,))],
            [tienda.cobro(tienda.efectivo, "944.00")],
        )

    def test_la_serie_de_la_otra_empresa_dice_donde_esta(self, tienda, celular):
        with pytest.raises(VentaInvalida) as error:
            self.vender(tienda, celular, "B-1")
        mensaje = error.value.mensaje
        assert "B-1" in mensaje and "está en el stock de" in mensaje
        assert "Cambia la empresa de la línea" in mensaje

    def test_una_serie_que_no_existe(self, tienda, celular):
        with pytest.raises(VentaInvalida, match="no existe para Celular"):
            self.vender(tienda, celular, "NO-EXISTE")

    def test_una_serie_ya_vendida(self, tienda, celular):
        self.vender(tienda, celular, "A-1")
        with pytest.raises(VentaInvalida, match="ya salió del almacén"):
            self.vender(tienda, celular, "A-1")
