"""Registro de movimientos: costo, IGV, moneda, fechas atrasadas, comprobantes y aislamiento."""

from decimal import Decimal as D

import pytest

from apps.core.exceptions import EmpresaNoHabilitada
from apps.inventario import periodos
from apps.inventario.exceptions import (
    CierreFueraDeOrden,
    ComprobanteDuplicado,
    MovimientoInvalido,
    PeriodoCerrado,
    PeriodoInvalido,
    ProductoNoInventariable,
    StockInsuficiente,
    TipoCambioNoDisponible,
)
from apps.inventario.models import (
    LineaMovimiento,
    Moneda,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import TipoCambio

from .conftest import comprar, fin_de_mes, saldo_de, vender

pytestmark = pytest.mark.django_db


def kardex(entorno, producto, empresa=None, almacen=None):
    """Las líneas del Kardex en orden cronológico."""
    return list(
        LineaMovimiento.objects.filter(
            empresa=empresa or entorno.e1, almacen=almacen or entorno.alm1, producto=producto
        ).order_by("fecha", "movimiento_id", "id")
    )


class TestCostoPromedio:
    def test_ejemplo_del_cemento_registrado_con_los_servicios(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 50, 20, dias=20)
        vender(entorno, cemento, 5, dias=19)
        vender(entorno, cemento, 5, dias=18)
        comprar(entorno, cemento, 20, 22, dias=15)
        comprar(entorno, cemento, 10, 19, dias=10)

        lineas = kardex(entorno, cemento)
        assert [(ln.saldo_cantidad, ln.saldo_costo_total) for ln in lineas] == [
            (50, 1000),
            (45, 900),
            (40, 800),
            (60, 1240),
            (70, 1430),
        ]
        assert [ln.saldo_costo_unitario.quantize(D("0.01")) for ln in lineas] == [
            D("20.00"),
            D("20.00"),
            D("20.00"),
            D("20.67"),
            D("20.43"),
        ]
        saldo = saldo_de(entorno, cemento)
        assert (saldo.cantidad, saldo.costo_total) == (70, 1430)

    def test_la_salida_sale_al_costo_promedio_y_no_al_precio_de_venta(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 50, 20, dias=3)
        movimiento = vender(entorno, cemento, 5, dias=1, precio=50)
        linea = movimiento.lineas.get()
        assert (linea.costo_unitario, linea.costo_total) == (20, 100)
        assert linea.precio_unitario == 50
        assert movimiento.subtotal == 250  # el comprobante sí usa el precio de venta

    def test_el_costo_de_cada_empresa_es_independiente(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=2)
        comprar(entorno, cemento, 10, 40, dias=2, empresa=entorno.e2, almacen=entorno.alm2)
        assert saldo_de(entorno, cemento).costo_unitario == 20
        assert saldo_de(entorno, cemento, entorno.e2, entorno.alm2).costo_unitario == 40
        vender(entorno, cemento, 5, dias=1)
        assert saldo_de(entorno, cemento, entorno.e2, entorno.alm2).cantidad == 10

    def test_saldo_inicial_y_ajuste_sin_igv(self, entorno):
        cemento = entorno.producto()
        inicial = registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.SALDO_INICIAL,
            fecha=entorno.hace(10),
            lineas=[LineaNueva(cemento, D("100"), D("18.5"))],
        )
        assert (inicial.tipo_operacion, inicial.igv, inicial.total) == ("16", 0, 1850)
        merma = registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.MERMA,
            fecha=entorno.hace(5),
            lineas=[LineaNueva(cemento, D("4"))],
            observacion="  Bolsas  rotas ",
        )
        assert merma.observacion == "Bolsas rotas"
        assert saldo_de(entorno, cemento).cantidad == 96


class TestStockNegativo:
    def test_se_rechaza_y_no_deja_ningun_rastro(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 40, 20, dias=5)
        antes = MovimientoInventario.objects.count()
        with pytest.raises(StockInsuficiente) as error:
            vender(entorno, cemento, 45, dias=1)
        assert "Cemento Pacasmayo MS" in error.value.mensaje
        assert MovimientoInventario.objects.count() == antes
        assert LineaMovimiento.objects.count() == 1
        assert saldo_de(entorno, cemento).cantidad == 40
        # El correlativo no se consumió: el siguiente movimiento es el 2.
        assert comprar(entorno, cemento, 1, 20).numero == 2

    def test_un_movimiento_con_varias_lineas_es_todo_o_nada(self, entorno):
        cemento, arena = entorno.producto(), entorno.producto("Arena")
        comprar(entorno, cemento, 10, 20, dias=3)
        with pytest.raises(StockInsuficiente):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.SALIDA,
                origen=OrigenMovimiento.VENTA,
                fecha=entorno.hoy,
                lineas=[LineaNueva(cemento, D("5")), LineaNueva(arena, D("1"))],
            )
        assert saldo_de(entorno, cemento).cantidad == 10
        assert not SaldoStock.objects.filter(producto=arena).exclude(cantidad=0).exists()

    def test_misma_cantidad_repetida_en_dos_lineas_cuenta_junta(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=3)
        with pytest.raises(StockInsuficiente):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.SALIDA,
                origen=OrigenMovimiento.VENTA,
                fecha=entorno.hoy,
                lineas=[LineaNueva(cemento, D("6")), LineaNueva(cemento, D("6"))],
            )
        assert saldo_de(entorno, cemento).cantidad == 10


class TestIgvYMoneda:
    def test_precio_sin_igv(self, entorno):
        cemento = entorno.producto()
        m = comprar(
            entorno,
            cemento,
            10,
            100,
            dias=1,
            comprobante_tipo="01",
            comprobante_serie="F001",
            comprobante_numero="1",
        )
        assert (m.subtotal, m.igv, m.total) == (1000, 180, 1180)
        assert m.lineas.get().costo_unitario == 100

    def test_precio_con_igv_incluido_se_divide_entre_1_18(self, entorno):
        cemento = entorno.producto()
        m = comprar(
            entorno,
            cemento,
            10,
            118,
            dias=1,
            precios_incluyen_igv=True,
            comprobante_tipo="01",
            comprobante_serie="F001",
            comprobante_numero="2",
        )
        assert (m.subtotal, m.igv, m.total) == (1000, 180, 1180)
        assert m.lineas.get().costo_unitario == 100  # el costo siempre va sin IGV

    def test_compra_en_dolares_con_el_tipo_de_cambio_venta_del_dia(self, entorno):
        cemento = entorno.producto()
        TipoCambio.objects.create(
            organizacion=entorno.e.org_a,
            fecha=entorno.hace(3),
            moneda="USD",
            fuente="SUNAT",
            compra=D("3.70"),
            venta=D("3.75"),
        )
        m = comprar(entorno, cemento, 10, 100, dias=2, moneda=Moneda.USD)
        assert m.tipo_cambio == D("3.75")  # sin dato del día se usa el anterior
        assert m.lineas.get().costo_total == 3750
        assert m.subtotal == 1000  # el comprobante conserva sus dólares

    def test_venta_en_dolares_usa_el_tipo_de_cambio_compra(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=5)
        TipoCambio.objects.create(
            organizacion=entorno.e.org_a,
            fecha=entorno.hace(3),
            moneda="USD",
            fuente="SUNAT",
            compra=D("3.70"),
            venta=D("3.75"),
        )
        assert vender(entorno, cemento, 1, dias=1, precio=10, moneda=Moneda.USD).tipo_cambio == D(
            "3.70"
        )

    def test_sin_tipo_de_cambio_no_deja_registrar(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(TipoCambioNoDisponible):
            comprar(entorno, cemento, 10, 100, moneda=Moneda.USD)
        assert MovimientoInventario.objects.count() == 0

    def test_tipo_de_cambio_indicado_a_mano(self, entorno):
        cemento = entorno.producto()
        m = comprar(entorno, cemento, 2, 10, moneda=Moneda.USD, tipo_cambio=D("3.8"))
        assert m.lineas.get().costo_total == D("76.00")


class TestFechas:
    def test_no_admite_fecha_futura(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, cemento, 1, 1, dias=-1)

    def test_una_compra_atrasada_recalcula_el_costo_de_las_salidas_posteriores(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 10, dias=10)
        venta = vender(entorno, cemento, 5, dias=5)
        assert venta.lineas.get().costo_total == 50  # promedio 10

        comprar(entorno, cemento, 10, 20, dias=7)  # llegó tarde la factura, pero es del día 7

        venta_linea = LineaMovimiento.objects.get(movimiento=venta)
        assert venta_linea.costo_total == 75  # ahora el promedio era 15
        assert (venta_linea.saldo_cantidad, venta_linea.saldo_costo_total) == (15, 225)
        saldo = saldo_de(entorno, cemento)
        assert (saldo.cantidad, saldo.costo_total, saldo.costo_unitario) == (15, 225, 15)

    def test_una_salida_atrasada_sin_stock_en_esa_fecha_se_rechaza(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=3)
        with pytest.raises(StockInsuficiente) as error:
            vender(entorno, cemento, 5, dias=8)  # ese día todavía no había mercadería
        assert "hay 0" in error.value.mensaje
        assert len(kardex(entorno, cemento)) == 1

    def test_una_salida_atrasada_que_deja_sin_stock_a_otra_posterior_se_rechaza(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=10)
        vender(entorno, cemento, 8, dias=5)
        with pytest.raises(StockInsuficiente):
            vender(entorno, cemento, 5, dias=7)  # la venta del día 5 ya no tendría stock
        assert saldo_de(entorno, cemento).cantidad == 2

    def test_el_orden_entre_movimientos_del_mismo_dia_es_el_de_registro(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=2)
        vender(entorno, cemento, 10, dias=2)
        assert [ln.saldo_cantidad for ln in kardex(entorno, cemento)] == [10, 0]


class TestComprobantes:
    def test_el_comprobante_de_un_proveedor_no_se_registra_dos_veces(self, entorno):
        cemento = entorno.producto()
        datos = {
            "proveedor": entorno.proveedor,
            "comprobante_tipo": "01",
            "comprobante_serie": " f001 ",
            "comprobante_numero": "1245",
        }
        primera = comprar(entorno, cemento, 5, 20, dias=2, **datos)
        assert primera.comprobante_serie == "F001"
        with pytest.raises(ComprobanteDuplicado):
            comprar(entorno, cemento, 5, 20, dias=1, **datos)
        assert saldo_de(entorno, cemento).cantidad == 5
        # Otro proveedor puede usar la misma serie y número.
        comprar(entorno, cemento, 5, 20, **{**datos, "proveedor": entorno.otro_proveedor})

    def test_el_comprobante_de_una_venta_no_se_repite(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=3)
        datos = {"comprobante_tipo": "03", "comprobante_serie": "B001", "comprobante_numero": "55"}
        vender(entorno, cemento, 1, dias=2, **datos)
        with pytest.raises(ComprobanteDuplicado):
            vender(entorno, cemento, 1, dias=1, **datos)
        assert saldo_de(entorno, cemento).cantidad == 9

    def test_tras_anular_el_comprobante_se_puede_registrar_de_nuevo(self, entorno):
        from apps.inventario.movimientos import anular_movimiento

        cemento = entorno.producto()
        datos = {
            "proveedor": entorno.proveedor,
            "comprobante_tipo": "01",
            "comprobante_serie": "F001",
            "comprobante_numero": "7",
        }
        primera = comprar(entorno, cemento, 5, 20, dias=2, **datos)
        anular_movimiento(primera, motivo="Error de digitación")
        comprar(entorno, cemento, 5, 20, dias=1, **datos)
        assert saldo_de(entorno, cemento).cantidad == 5

    def test_validaciones_del_comprobante(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, cemento, 1, 1, comprobante_tipo="77")
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, cemento, 1, 1, comprobante_serie="F001")  # sin tipo
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, cemento, 1, 1, comprobante_tipo="01", comprobante_numero="12 ; DROP")

    def test_proveedor_y_cliente_a_la_vez_no_valen(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, cemento, 1, 1, proveedor=entorno.proveedor, cliente=entorno.cliente)


class TestValidaciones:
    def test_cantidad_y_precio(self, entorno):
        cemento = entorno.producto()
        for cantidad, precio in [("0", "1"), ("-1", "1"), ("1.0001", "1"), ("1", "-1")]:
            with pytest.raises(MovimientoInvalido):
                comprar(entorno, cemento, cantidad, precio)
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, cemento, "NaN", "1")

    def test_la_entrada_exige_precio_y_necesita_al_menos_una_linea(self, entorno):
        cemento = entorno.producto()
        base = {
            "empresa": entorno.e1,
            "almacen": entorno.alm1,
            "tipo": TipoMovimiento.ENTRADA,
            "origen": OrigenMovimiento.COMPRA,
            "fecha": entorno.hoy,
        }
        with pytest.raises(MovimientoInvalido):
            registrar_movimiento(**base, lineas=[LineaNueva(cemento, D("1"))])
        with pytest.raises(MovimientoInvalido):
            registrar_movimiento(**base, lineas=[])

    def test_el_tipo_debe_corresponder_al_origen(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(MovimientoInvalido):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.SALIDA,
                origen=OrigenMovimiento.COMPRA,
                fecha=entorno.hoy,
                lineas=[LineaNueva(cemento, D("1"))],
            )

    def test_el_extorno_no_se_puede_registrar_a_mano(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(MovimientoInvalido):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.SALIDA,
                origen=OrigenMovimiento.EXTORNO,
                fecha=entorno.hoy,
                lineas=[LineaNueva(cemento, D("1"))],
            )

    def test_un_servicio_no_lleva_stock(self, entorno):
        with pytest.raises(ProductoNoInventariable):
            comprar(entorno, entorno.servicio, 1, 50)

    def test_almacen_inactivo(self, entorno):
        entorno.alm1.estado = "INACTIVO"
        entorno.alm1.save(update_fields=["estado"])
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, entorno.producto(), 1, 1)


class TestAislamiento:
    def test_empresa_fuera_del_contexto(self, entorno):
        with pytest.raises(EmpresaNoHabilitada):
            comprar(entorno, entorno.producto(), 1, 1, empresa=entorno.eb)

    def test_almacen_de_otra_empresa(self, entorno):
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, entorno.producto(), 1, 1, almacen=entorno.alm2)

    def test_producto_de_otra_organizacion(self, entorno):
        ajeno = entorno.ajeno
        with pytest.raises(MovimientoInvalido):
            comprar(entorno, ajeno, 1, 1)


class TestPeriodos:
    def test_un_mes_cerrado_no_admite_movimientos_y_los_posteriores_siguen_abiertos(self, entorno):
        cemento = entorno.producto()
        fin_pasado = fin_de_mes(entorno.hoy, 1)
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=fin_pasado,
            lineas=[LineaNueva(cemento, D("10"), D("20"))],
        )
        periodo = periodos.periodo_de(fin_pasado)
        periodos.cerrar_periodo(entorno.e1, periodo)

        with pytest.raises(PeriodoCerrado) as error:
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.ENTRADA,
                origen=OrigenMovimiento.COMPRA,
                fecha=fin_pasado,
                lineas=[LineaNueva(cemento, D("1"), D("20"))],
            )
        assert "fecha posterior" in error.value.mensaje
        # El mes en curso sigue abierto, y la otra empresa no se ve afectada.
        comprar(entorno, cemento, 1, 20)
        comprar(entorno, cemento, 1, 20, dias=60, empresa=entorno.e2, almacen=entorno.alm2)

    def test_no_se_puede_cerrar_el_mes_en_curso_ni_uno_invalido(self, entorno):
        with pytest.raises(PeriodoInvalido):
            periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(entorno.hoy))
        for malo in ("202613", "2026-10", "", "abc"):
            with pytest.raises(PeriodoInvalido):
                periodos.cerrar_periodo(entorno.e1, malo)

    def test_los_periodos_se_cierran_en_orden(self, entorno):
        cemento = entorno.producto()
        hace_dos, hace_uno = fin_de_mes(entorno.hoy, 2), fin_de_mes(entorno.hoy, 1)
        for fecha in (hace_dos, hace_uno):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.ENTRADA,
                origen=OrigenMovimiento.COMPRA,
                fecha=fecha,
                lineas=[LineaNueva(cemento, D("1"), D("20"))],
            )
        with pytest.raises(CierreFueraDeOrden):
            periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(hace_uno))
        periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(hace_dos))
        periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(hace_uno))
        with pytest.raises(PeriodoCerrado):
            periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(hace_uno))

    def test_no_se_puede_registrar_antes_de_un_mes_cerrado(self, entorno):
        cemento = entorno.producto()
        hace_uno = fin_de_mes(entorno.hoy, 1)
        periodos.cerrar_periodo(entorno.e1, periodos.periodo_de(hace_uno))
        with pytest.raises(PeriodoCerrado):
            comprar(entorno, cemento, 1, 20, dias=(entorno.hoy - fin_de_mes(entorno.hoy, 3)).days)

    def test_solo_se_reabre_el_ultimo_cerrado(self, entorno):
        cemento = entorno.producto()
        hace_dos, hace_uno = fin_de_mes(entorno.hoy, 2), fin_de_mes(entorno.hoy, 1)
        for fecha in (hace_dos, hace_uno):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.ENTRADA,
                origen=OrigenMovimiento.COMPRA,
                fecha=fecha,
                lineas=[LineaNueva(cemento, D("1"), D("20"))],
            )
        p2, p1 = periodos.periodo_de(hace_dos), periodos.periodo_de(hace_uno)
        periodos.cerrar_periodo(entorno.e1, p2)
        periodos.cerrar_periodo(entorno.e1, p1)
        with pytest.raises(CierreFueraDeOrden):
            periodos.reabrir_periodo(entorno.e1, p2)
        periodos.reabrir_periodo(entorno.e1, p1)
        assert periodos.cerrados(entorno.e1) == [p2]
        periodos.cerrar_periodo(entorno.e1, p1)  # se puede volver a cerrar


class TestNumeracion:
    def test_correlativo_por_empresa(self, entorno):
        cemento = entorno.producto()
        a = comprar(entorno, cemento, 1, 1, dias=2)
        b = comprar(entorno, cemento, 1, 1, dias=1)
        c = comprar(entorno, cemento, 1, 1, empresa=entorno.e2, almacen=entorno.alm2)
        assert (a.numero, b.numero, c.numero) == (1, 2, 1)
        assert str(a).startswith("Entrada N° 000001")

    def test_el_movimiento_registrado_no_se_puede_editar(self, entorno):
        from apps.core.exceptions import DocumentoInmutableError

        m = comprar(entorno, entorno.producto(), 1, 1)
        m.observacion = "cambio"
        with pytest.raises(DocumentoInmutableError):
            m.save()
        with pytest.raises(DocumentoInmutableError):
            MovimientoInventario.objects.filter(pk=m.pk).update(observacion="x")
        with pytest.raises(DocumentoInmutableError):
            m.delete()


class TestCaminoRapidoDeEntradas:
    """La carga masiva calcula de una vez los productos nuevos; debe dar lo mismo que lo normal."""

    def _registrar(self, entorno, empresa, almacen, producto):
        return registrar_movimiento(
            empresa=empresa,
            almacen=almacen,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.SALDO_INICIAL,
            fecha=entorno.hace(5),
            lineas=[LineaNueva(producto, D("7.5"), D("12.345678"))],
        )

    def test_da_exactamente_lo_mismo_que_el_camino_normal(self, entorno, monkeypatch):
        from apps.inventario import movimientos

        cemento = entorno.producto()
        usados = []
        real = movimientos._entradas_sin_historial

        def espiar(*args, **kwargs):
            resultado = real(*args, **kwargs)
            usados.append(resultado)
            return resultado

        monkeypatch.setattr(movimientos, "_entradas_sin_historial", espiar)
        rapido = self._registrar(entorno, entorno.e1, entorno.alm1, cemento)
        assert usados[-1] == {cemento.pk}  # sí tomó el camino rápido

        monkeypatch.setattr(movimientos, "_entradas_sin_historial", lambda *a, **k: set())
        normal = self._registrar(entorno, entorno.e2, entorno.alm2, cemento)

        campos = (
            "cantidad",
            "precio_unitario",
            "costo_unitario",
            "costo_total",
            "saldo_cantidad",
            "saldo_costo_total",
            "saldo_costo_unitario",
        )
        de = lambda m: [getattr(m.lineas.get(), c) for c in campos]  # noqa: E731
        assert de(rapido) == de(normal)
        a, b = saldo_de(entorno, cemento), saldo_de(entorno, cemento, entorno.e2, entorno.alm2)
        assert (a.cantidad, a.costo_total, a.costo_unitario) == (
            b.cantidad,
            b.costo_total,
            b.costo_unitario,
        )

    def test_un_producto_con_historial_sigue_el_camino_normal(self, entorno, monkeypatch):
        from apps.inventario import movimientos

        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=9)
        usados = []
        real = movimientos._entradas_sin_historial
        monkeypatch.setattr(
            movimientos,
            "_entradas_sin_historial",
            lambda *a, **k: usados.append(real(*a, **k)) or usados[-1],
        )
        comprar(entorno, cemento, 10, 30, dias=2)
        assert usados[-1] == set()
        assert saldo_de(entorno, cemento).costo_unitario == 25

    def test_el_mismo_producto_dos_veces_en_un_movimiento(self, entorno):
        cemento = entorno.producto()
        m = registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=entorno.hace(1),
            lineas=[
                LineaNueva(cemento, D("10"), D("10")),
                LineaNueva(cemento, D("10"), D("20")),
            ],
        )
        primera, segunda = m.lineas.order_by("orden")
        assert (primera.saldo_cantidad, primera.saldo_costo_total) == (10, 100)
        assert (segunda.saldo_cantidad, segunda.saldo_costo_total) == (20, 300)
        assert saldo_de(entorno, cemento).costo_unitario == 15
