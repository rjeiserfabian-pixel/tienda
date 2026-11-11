"""Deshacer una venta interna: anular o devolver regresa la mercadería a quien la entregó."""

from decimal import Decimal as D

import pytest

from apps.caja.servicios import saldo_de
from apps.core.tenant import establecer_contexto
from apps.inventario.models import (
    EstadoSerie,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.ventas import notas_credito
from apps.ventas.exceptions import VentaInvalida, VentaNoAnulable
from apps.ventas.models import DevolucionInterna, NotaCredito, VentaInterna
from apps.ventas.servicios import anular_venta

from .test_venta_interna import comprar_en, movimientos_internos, vender_interna

pytestmark = pytest.mark.django_db


def saldo(tienda, producto, empresa):
    return SaldoStock.objects.get(
        empresa=empresa, almacen=tienda.almacen(empresa), producto=producto
    )


def hacer(tienda, mixto, cantidad_b=2, cobro="354.00"):
    de_a, de_b = mixto
    return vender_interna(
        tienda,
        [tienda.linea(de_a, 1), tienda.linea(de_b, cantidad_b, empresa=tienda.b)],
        [tienda.cobro(tienda.efectivo, cobro)],
    )


def devolver(venta, producto, cantidad, **extra):
    comprobante = venta.comprobantes.get()
    linea = comprobante.lineas.get(producto=producto)
    return notas_credito.LineaDevuelta(linea, D(str(cantidad)), **extra)


def emitir_nota(tienda, venta, devueltas, reembolso, **extra):
    return notas_credito.crear_nota_credito(
        venta.comprobantes.get(),
        motivo="07",
        devueltas=devueltas,
        reembolsos=[tienda.cobro(tienda.efectivo, reembolso)],
        **extra,
    )


class TestAnularLaVenta:
    def test_anular_deja_el_stock_y_el_costo_como_estaban_en_las_dos_empresas(self, tienda, mixto):
        de_a, de_b = mixto
        venta = hacer(tienda, mixto)

        anular_venta(venta, motivo="El cliente se arrepintió")

        # B recupera sus 10 unidades Y su valor (10 × 30); A no se queda con nada de B.
        en_b = saldo(tienda, de_b, tienda.b)
        assert (en_b.cantidad, en_b.costo_total) == (D("10"), D("300.00"))
        en_a = saldo(tienda, de_b, tienda.a)
        assert (en_a.cantidad, en_a.costo_total) == (D("0"), D("0"))
        assert saldo(tienda, de_a, tienda.a).cantidad == D("10")
        # El dinero de la venta salió de la caja de quien facturó.
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")

    def test_queda_anulada_la_venta_interna_y_sus_movimientos(self, tienda, mixto):
        venta = hacer(tienda, mixto)

        anular_venta(venta, motivo="Error de cobro")

        interna = VentaInterna.objects.get(venta=venta)
        assert interna.estado == "ANULADO" and interna.motivo_anulacion == "Error de cobro"
        originales = movimientos_internos().exclude(origen=OrigenMovimiento.EXTORNO)
        assert originales.count() == 2
        assert all(m.estado == "ANULADO" for m in originales)
        # Cada mitad tiene su extorno, en la empresa que le tocaba.
        extornos = MovimientoInventario.objects.filter(extorna__in=originales)
        assert {(m.empresa_id, m.tipo) for m in extornos} == {
            (tienda.a.pk, TipoMovimiento.SALIDA),
            (tienda.b.pk, TipoMovimiento.ENTRADA),
        }

    def test_las_series_vuelven_a_estar_en_la_empresa_que_las_entrego(self, tienda):
        celular = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        funda = tienda.producto("Funda", costo="10", precios={"PUBLICO": "30"})
        comprar_en(tienda, tienda.b, celular, 1, 500, series=("IMEI-900",))
        venta = vender_interna(
            tienda,
            [
                tienda.linea(funda, 1),
                tienda.linea(celular, 1, empresa=tienda.b, series=("IMEI-900",)),
            ],
            [tienda.cobro(tienda.efectivo, "979.40")],
        )

        anular_venta(venta, motivo="Prueba")

        vigente = SerieProducto.objects.get(numero="IMEI-900", estado=EstadoSerie.EN_STOCK)
        assert vigente.empresa == tienda.b

    def test_sin_acceso_a_la_otra_empresa_se_dice_claro_y_no_se_toca_nada(self, tienda, mixto):
        venta = hacer(tienda, mixto)
        org = tienda.entorno.e.org_a
        establecer_contexto(org.pk, [tienda.a.pk], tienda.entorno.e.usuario_id)

        with pytest.raises(VentaNoAnulable, match="acceso también a"):
            anular_venta(venta, motivo="Prueba")

        establecer_contexto(org.pk, [tienda.a.pk, tienda.b.pk], tienda.entorno.e.usuario_id)
        assert venta.comprobantes.get().estado == "EMITIDO"
        assert VentaInterna.objects.get(venta=venta).estado == "EMITIDO"

    def test_con_una_nota_de_credito_ya_no_se_puede_anular(self, tienda, mixto):
        _, de_b = mixto
        venta = hacer(tienda, mixto)
        emitir_nota(tienda, venta, [devolver(venta, de_b, 1)], "118.00")

        with pytest.raises(VentaNoAnulable, match="notas de crédito"):
            anular_venta(venta, motivo="Tarde")


class TestDevolucion:
    def test_lo_devuelto_vuelve_a_quien_lo_entrego_al_costo_con_que_salio(self, tienda, mixto):
        de_a, de_b = mixto
        venta = hacer(tienda, mixto)

        nota = emitir_nota(tienda, venta, [devolver(venta, de_b, 1)], "118.00")

        # B recibe 1 unidad por 30 (lo que le costó); A no se queda con ella.
        en_b = saldo(tienda, de_b, tienda.b)
        assert (en_b.cantidad, en_b.costo_total) == (D("9"), D("270.00"))
        assert saldo(tienda, de_b, tienda.a).cantidad == D("0")
        (devolucion,) = DevolucionInterna.objects.filter(nota=nota)
        assert devolucion.empresa == tienda.b
        assert (devolucion.cantidad, devolucion.costo_total) == (D("1.000"), D("30.00"))
        assert devolucion.movimiento_salida.empresa == tienda.a
        assert devolucion.movimiento_entrada.empresa == tienda.b
        # El reembolso al cliente salió de la caja de quien facturó.
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("236.00")

    def test_lo_que_salio_del_stock_propio_se_queda_en_quien_facturo(self, tienda, mixto):
        de_a, de_b = mixto
        venta = hacer(tienda, mixto)

        emitir_nota(tienda, venta, [devolver(venta, de_a, 1)], "118.00")

        assert saldo(tienda, de_a, tienda.a).cantidad == D("10")
        assert not DevolucionInterna.objects.exists()
        assert saldo(tienda, de_b, tienda.b).cantidad == D("8")  # B no se enteró

    def test_devolver_todo_deja_a_cada_empresa_como_al_principio(self, tienda, mixto):
        de_a, de_b = mixto
        venta = hacer(tienda, mixto)

        notas_credito.crear_nota_credito(
            venta.comprobantes.get(),
            motivo="06",
            reembolsos=[tienda.cobro(tienda.efectivo, "354.00")],
        )

        en_b = saldo(tienda, de_b, tienda.b)
        assert (en_b.cantidad, en_b.costo_total) == (D("10"), D("300.00"))
        assert saldo(tienda, de_a, tienda.a).cantidad == D("10")
        assert saldo(tienda, de_b, tienda.a).cantidad == D("0")

    def test_en_partes_los_centavos_cierran_exactos(self, tienda):
        """3 unidades que costaron 10.00: la nota redondea a 3.33 y no se inventa el céntimo."""
        p = tienda.producto("Tornillo", costo="3.333333", precios={"PUBLICO": "10"}, stock={})
        de_a = tienda.producto("Audífonos", costo="50", precios={"PUBLICO": "100"})
        comprar_en(tienda, tienda.b, p, 3, "3.333333")
        venta = vender_interna(
            tienda,
            [tienda.linea(de_a, 1), tienda.linea(p, 3, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "153.40")],
        )
        interna_costo = VentaInterna.objects.get(venta=venta).total_costo

        for _ in range(3):
            emitir_nota(tienda, venta, [devolver(venta, p, 1)], "11.80")

        importes = list(
            DevolucionInterna.objects.order_by("id").values_list("costo_total", flat=True)
        )
        assert interna_costo == D("10.00")
        # A solo pudo reingresar 3.33 por unidad: eso es lo que vuelve (nada de valor inventado).
        assert importes == [D("3.33"), D("3.33"), D("3.33")]
        en_b = saldo(tienda, p, tienda.b)
        assert (en_b.cantidad, en_b.costo_total) == (D("3"), D("9.99"))
        # Y A queda en cero, sin sobrantes ni faltantes.
        en_a = saldo(tienda, p, tienda.a)
        assert (en_a.cantidad, en_a.costo_total) == (D("0"), D("0"))

    def test_las_series_devueltas_vuelven_a_quien_las_entrego(self, tienda):
        celular = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        funda = tienda.producto("Funda", costo="10", precios={"PUBLICO": "30"})
        comprar_en(tienda, tienda.b, celular, 1, 500, series=("IMEI-123",))
        venta = vender_interna(
            tienda,
            [
                tienda.linea(funda, 1),
                tienda.linea(celular, 1, empresa=tienda.b, series=("IMEI-123",)),
            ],
            [tienda.cobro(tienda.efectivo, "979.40")],
        )

        emitir_nota(tienda, venta, [devolver(venta, celular, 1, series=("IMEI-123",))], "944.00")

        vigente = SerieProducto.objects.get(numero="IMEI-123", estado=EstadoSerie.EN_STOCK)
        assert vigente.empresa == tienda.b

    def test_si_no_reingresa_al_stock_nada_vuelve_a_la_otra_empresa(self, tienda, mixto):
        _, de_b = mixto
        venta = hacer(tienda, mixto)

        emitir_nota(tienda, venta, [devolver(venta, de_b, 1)], "118.00", reingresa_stock=False)

        assert saldo(tienda, de_b, tienda.b).cantidad == D("8")
        assert not DevolucionInterna.objects.exists()

    def test_sin_acceso_a_la_otra_empresa_no_se_devuelve_y_se_dice_claro(self, tienda, mixto):
        _, de_b = mixto
        venta = hacer(tienda, mixto)
        org = tienda.entorno.e.org_a
        establecer_contexto(org.pk, [tienda.a.pk], tienda.entorno.e.usuario_id)

        with pytest.raises(VentaInvalida, match="acceso también a"):
            emitir_nota(tienda, venta, [devolver(venta, de_b, 1)], "118.00")

        establecer_contexto(org.pk, [tienda.a.pk, tienda.b.pk], tienda.entorno.e.usuario_id)
        assert not NotaCredito.objects.exists()

    def test_devolver_algo_propio_no_pide_acceso_a_la_otra_empresa(self, tienda, mixto):
        de_a, _ = mixto
        venta = hacer(tienda, mixto)
        org = tienda.entorno.e.org_a
        establecer_contexto(org.pk, [tienda.a.pk], tienda.entorno.e.usuario_id)

        nota = emitir_nota(tienda, venta, [devolver(venta, de_a, 1)], "118.00")

        assert nota.pk is not None
