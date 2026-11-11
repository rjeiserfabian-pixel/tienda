"""Venta interna: un solo comprobante para un carrito mixto, pasando antes la mercadería."""

from decimal import Decimal as D

import pytest

from apps.caja.servicios import saldo_de
from apps.inventario.catalogos import OTROS
from apps.inventario.exceptions import AnulacionNoPermitida
from apps.inventario.models import (
    EstadoSerie,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, anular_movimiento, registrar_movimiento
from apps.ventas import ventas_internas
from apps.ventas.exceptions import PrecioBajoElMinimo, VentaInvalida
from apps.ventas.models import LineaVentaInterna, Venta, VentaInterna

pytestmark = pytest.mark.django_db


def stock(tienda, producto, empresa):
    fila = SaldoStock.objects.filter(
        empresa=empresa, almacen=tienda.almacen(empresa), producto=producto
    ).first()
    return fila.cantidad if fila else D("0")


def vender_interna(tienda, lineas, cobros, **extra):
    extra.setdefault("facturar_por", tienda.a)
    extra.setdefault("puede_venta_interna", True)
    return tienda.vender(lineas, cobros, **extra)


def comprar_en(tienda, empresa, producto, cantidad, precio, **extra):
    return registrar_movimiento(
        empresa=empresa,
        almacen=tienda.almacen(empresa),
        tipo=TipoMovimiento.ENTRADA,
        origen=OrigenMovimiento.COMPRA,
        fecha=tienda.entorno.hoy,
        lineas=[LineaNueva(producto, D(str(cantidad)), D(str(precio)), **extra)],
    )


def movimientos_internos():
    return MovimientoInventario.objects.filter(origen=OrigenMovimiento.VENTA_INTERNA)


class TestFacturarConUnaSolaEmpresa:
    def test_un_comprobante_con_todo_y_el_stock_de_cada_empresa_cuadra(self, tienda, mixto):
        de_a, de_b = mixto
        venta = vender_interna(
            tienda,
            [tienda.linea(de_a, 1), tienda.linea(de_b, 2, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "354.00")],
        )

        (comp,) = venta.comprobantes.all()  # un solo comprobante, de la empresa que factura
        assert comp.empresa == tienda.a and comp.total == D("354.00")
        assert comp.lineas.count() == 2
        # Lo de B salió de su almacén; el de A bajó solo por lo que vendió él mismo.
        assert stock(tienda, de_b, tienda.b) == D("8")
        assert stock(tienda, de_a, tienda.a) == D("9")
        # A recibió las 2 unidades y las vendió enseguida: no le quedan.
        assert stock(tienda, de_b, tienda.a) == D("0")
        # Todo el cobro entró a la caja de la empresa que factura.
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("354.00")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("0")

    def test_deja_la_venta_interna_al_costo_de_quien_entrega(self, tienda, mixto):
        de_a, de_b = mixto
        venta = vender_interna(
            tienda,
            [tienda.linea(de_a, 1), tienda.linea(de_b, 2, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "354.00")],
        )

        (interna,) = venta.ventas_internas.all()
        assert interna.empresa == tienda.b and interna.empresa_destino == tienda.a
        assert interna.numero == 1 and interna.documento == "INTERNO"
        assert interna.total_costo == D("60.00")  # 2 × 30: sin margen entre las empresas
        (linea,) = interna.lineas.all()
        assert (linea.cantidad, linea.costo_unitario, linea.costo_total) == (
            D("2.000"),
            D("30"),
            D("60.00"),
        )
        assert linea.almacen_origen == tienda.almacen(tienda.b)
        assert linea.almacen_destino == tienda.almacen(tienda.a)
        # La venta al cliente sacó la mercadería al mismo costo: el margen es de quien facturó.
        vendida = venta.lineas.get(producto=de_b)
        assert vendida.costo_unitario == D("30") and vendida.costo_total == D("60.00")
        assert vendida.margen(venta.tipo_cambio) == D("140.00")

    def test_el_kardex_de_las_dos_empresas_queda_enlazado(self, tienda, mixto):
        de_a, de_b = mixto
        venta = vender_interna(
            tienda,
            [tienda.linea(de_a, 1), tienda.linea(de_b, 2, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "354.00")],
        )
        interna = venta.ventas_internas.get()
        movimientos = movimientos_internos()
        assert {(m.empresa_id, m.tipo) for m in movimientos} == {
            (tienda.b.pk, TipoMovimiento.SALIDA),
            (tienda.a.pk, TipoMovimiento.ENTRADA),
        }
        assert {m.traspaso_id for m in movimientos} == {interna.codigo}
        assert all(m.tipo_operacion == OTROS for m in movimientos)
        linea = interna.lineas.get()
        assert linea.movimiento_salida.empresa == tienda.b
        assert linea.movimiento_entrada.empresa == tienda.a

    def test_funciona_al_reves_factura_la_otra_empresa(self, tienda, mixto):
        de_a, de_b = mixto
        venta = vender_interna(
            tienda,
            [tienda.linea(de_a, 1), tienda.linea(de_b, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "236.00")],
            facturar_por=tienda.b,
        )

        (comp,) = venta.comprobantes.all()
        assert comp.empresa == tienda.b
        (interna,) = venta.ventas_internas.all()
        assert interna.empresa == tienda.a and interna.empresa_destino == tienda.b
        assert interna.total_costo == D("50.00")
        assert stock(tienda, de_a, tienda.a) == D("9")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("236.00")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")

    def test_el_costo_se_mezcla_con_lo_que_la_facturadora_ya_tenia(self, tienda):
        """Si la facturadora ya tiene el producto a otro costo, sale al promedio del Kardex."""
        p = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "100"}, stock={tienda.a: 10})
        comprar_en(tienda, tienda.b, p, 4, 40)  # B lo compra más caro: 4 a 40

        venta = vender_interna(
            tienda,
            [tienda.linea(p, 1), tienda.linea(p, 4, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "590.00")],
        )

        (interna,) = venta.ventas_internas.all()
        assert interna.total_costo == D("160.00")  # 4 × 40, el costo de B
        # A queda con 10 a 20 y 4 a 40 = 14 unidades a 25.714286; vende 5 a ese promedio.
        assert sum(venta.lineas.values_list("costo_total", flat=True)) == D("128.57")

    def test_las_series_viajan_con_la_mercaderia(self, tienda):
        celular = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        funda = tienda.producto("Funda", costo="10", precios={"PUBLICO": "30"})
        comprar_en(tienda, tienda.b, celular, 2, 500, series=("IMEI-001", "IMEI-002"))

        venta = vender_interna(
            tienda,
            [
                tienda.linea(funda, 1),
                tienda.linea(celular, 1, empresa=tienda.b, series=("IMEI-001",)),
            ],
            [tienda.cobro(tienda.efectivo, "979.40")],
        )

        # La unidad vendida salió de B, pasó por A y de ahí salió al cliente.
        de_b = SerieProducto.objects.get(numero="IMEI-001", empresa=tienda.b)
        de_a = SerieProducto.objects.get(numero="IMEI-001", empresa=tienda.a)
        assert de_b.estado == EstadoSerie.SALIDO and de_a.estado == EstadoSerie.SALIDO
        # La otra unidad no se movió: sigue en el almacén de B.
        quedada = SerieProducto.objects.get(numero="IMEI-002")
        assert quedada.estado == EstadoSerie.EN_STOCK and quedada.empresa == tienda.b
        assert venta.ventas_internas.get().lineas.get().series == ["IMEI-001"]

    def test_numera_las_ventas_internas_por_empresa(self, tienda, mixto):
        de_a, de_b = mixto
        for _ in range(2):
            vender_interna(
                tienda,
                [tienda.linea(de_a, 1), tienda.linea(de_b, 1, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "236.00")],
            )
        numeros = list(VentaInterna.objects.order_by("id").values_list("numero", flat=True))
        assert numeros == [1, 2]


class TestSoloSeHaceEnVentaMixta:
    def test_si_todo_es_de_la_facturadora_no_hay_venta_interna(self, tienda, mixto):
        de_a, _ = mixto
        with pytest.raises(VentaInvalida, match="venta normal"):
            vender_interna(
                tienda, [tienda.linea(de_a, 1)], [tienda.cobro(tienda.efectivo, "118.00")]
            )

    def test_si_todo_es_de_la_otra_empresa_se_factura_con_esa(self, tienda, mixto):
        _, de_b = mixto
        with pytest.raises(VentaInvalida, match="se factura con esa empresa"):
            vender_interna(
                tienda,
                [tienda.linea(de_b, 1, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "118.00")],
            )
        assert not VentaInterna.objects.exists()

    def test_sin_permiso_no_se_hace(self, tienda, mixto):
        de_a, de_b = mixto
        with pytest.raises(VentaInvalida, match="permiso"):
            vender_interna(
                tienda,
                [tienda.linea(de_a, 1), tienda.linea(de_b, 1, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "236.00")],
                puede_venta_interna=False,
            )
        assert stock(tienda, de_b, tienda.b) == D("10")

    def test_la_factura_entre_empresas_aun_no_esta_disponible(self, tienda, mixto):
        de_a, de_b = mixto
        with pytest.raises(VentaInvalida, match="factura electrónica"):
            vender_interna(
                tienda,
                [tienda.linea(de_a, 1), tienda.linea(de_b, 1, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "236.00")],
                documento_interno="FACTURA",
            )
        assert stock(tienda, de_b, tienda.b) == D("10")

    def test_sin_facturar_por_la_venta_mixta_sigue_con_dos_comprobantes(self, tienda, mixto):
        de_a, de_b = mixto
        venta = tienda.vender(
            [tienda.linea(de_a, 1), tienda.linea(de_b, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "236.00")],
        )
        assert venta.comprobantes.count() == 2
        assert not VentaInterna.objects.exists()


class TestAvisosYTodoONada:
    def test_sin_stock_en_quien_entrega_avisa_y_no_deja_nada(self, tienda, mixto):
        de_a, de_b = mixto
        with pytest.raises(VentaInvalida, match="tiene 10.000 y se necesitan 11.000"):
            vender_interna(
                tienda,
                [tienda.linea(de_a, 1), tienda.linea(de_b, 11, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "1416.00")],
            )
        assert stock(tienda, de_b, tienda.b) == D("10")
        assert not Venta.objects.exists() and not VentaInterna.objects.exists()
        assert not movimientos_internos().exists()

    def test_sin_costo_avisa_antes_de_cobrar(self, tienda):
        sin_costo = tienda.producto(
            "Regalo", costo="0", precios={"PUBLICO": "10"}, stock={tienda.b: 5}
        )
        de_a = tienda.producto("Audífonos", costo="50", precios={"PUBLICO": "100"})
        with pytest.raises(VentaInvalida, match="no tiene costo"):
            vender_interna(
                tienda,
                [tienda.linea(de_a, 1), tienda.linea(sin_costo, 1, empresa=tienda.b)],
                [tienda.cobro(tienda.efectivo, "129.80")],
            )
        assert stock(tienda, sin_costo, tienda.b) == D("5")

    def test_revisar_informa_sin_escribir_nada(self, tienda, mixto):
        de_a, de_b = mixto
        lineas = [tienda.linea(de_a, 1), tienda.linea(de_b, 11, empresa=tienda.b)]

        (revision,) = ventas_internas.revisar(lineas, tienda.a)

        assert revision.disponible == D("10") and revision.costo_unitario == D("30")
        assert revision.almacen_destino == tienda.almacen(tienda.a)
        assert len(revision.problemas) == 1 and "se necesitan 11.000" in revision.problemas[0]
        assert not movimientos_internos().exists()

    def test_si_la_venta_falla_despues_se_deshace_tambien_el_traslado(self, tienda, mixto):
        de_a, de_b = mixto
        with pytest.raises(PrecioBajoElMinimo):
            vender_interna(
                tienda,
                [
                    tienda.linea(de_a, 1),
                    # Por debajo del costo: la venta se rechaza después de pasar la mercadería.
                    tienda.linea(de_b, 1, empresa=tienda.b, precio_unitario=D("1")),
                ],
                [tienda.cobro(tienda.efectivo, "100.00")],
            )
        assert stock(tienda, de_b, tienda.b) == D("10")
        assert stock(tienda, de_b, tienda.a) == D("0")
        assert not VentaInterna.objects.exists() and not LineaVentaInterna.objects.exists()
        assert not movimientos_internos().exists()


class TestKardex:
    def test_un_movimiento_de_venta_interna_no_se_anula_suelto_desde_el_kardex(self, tienda, mixto):
        de_a, de_b = mixto
        vender_interna(
            tienda,
            [tienda.linea(de_a, 1), tienda.linea(de_b, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "236.00")],
        )
        salida = movimientos_internos().get(tipo=TipoMovimiento.SALIDA)
        with pytest.raises(AnulacionNoPermitida, match="venta interna"):
            anular_movimiento(salida, motivo="Prueba")
