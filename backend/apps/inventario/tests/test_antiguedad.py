"""Antigüedad del stock (PEPS) calculada desde el Kardex, sin tocar el costeo."""

from decimal import Decimal

import pytest

from apps.inventario import antiguedad
from apps.inventario.models import OrigenMovimiento, TipoMovimiento
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    registrar_movimiento,
    registrar_traspaso,
)

from .conftest import comprar, saldo_de, vender

pytestmark = pytest.mark.django_db


def capas(entorno, producto, empresa=None, almacen=None):
    """Las capas (fecha, cantidad) de un producto en un almacén."""
    empresa = empresa or entorno.e1
    almacen = almacen or entorno.alm1
    for a in antiguedad.capas_de(empresa.pk, producto_ids=[producto.pk]):
        if a.almacen_id == almacen.pk:
            return a
    return None


def pares(a):
    return [(c.fecha, c.cantidad) for c in a.capas]


class TestCapas:
    def test_la_venta_consume_primero_lo_mas_antiguo(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)  # ingreso del día -60
        comprar(entorno, mouse, 5, 20, dias=30)  # ingreso del día -30
        vender(entorno, mouse, 12, dias=10)

        a = capas(entorno, mouse)
        assert pares(a) == [(entorno.hace(30), Decimal("3"))]
        assert a.saldo == 3 and a.descuadre == 0 and a.sin_fecha == 0
        assert a.dias_de_la_mas_antigua(entorno.hoy) == 30

    def test_una_venta_parcial_deja_lo_que_falta_de_la_capa_vieja(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 5, 20, dias=30)
        vender(entorno, mouse, 4, dias=10)

        a = capas(entorno, mouse)
        assert pares(a) == [(entorno.hace(60), Decimal("6")), (entorno.hace(30), Decimal("5"))]

    def test_el_orden_lo_da_la_fecha_aunque_se_registre_atrasado(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 5, 20, dias=10)  # se registra primero, pero es más nuevo
        comprar(entorno, mouse, 10, 20, dias=50)  # se registra después con fecha antigua
        vender(entorno, mouse, 3, dias=1)

        assert pares(capas(entorno, mouse)) == [
            (entorno.hace(50), Decimal("7")),
            (entorno.hace(10), Decimal("5")),
        ]

    def test_una_venta_anulada_no_cuenta_y_la_mercaderia_vuelve_a_su_capa(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 5, 20, dias=30)
        venta = vender(entorno, mouse, 12, dias=10)
        anular_movimiento(venta, motivo="Se devolvió todo")

        a = capas(entorno, mouse)
        assert pares(a) == [(entorno.hace(60), Decimal("10")), (entorno.hace(30), Decimal("5"))]
        assert a.descuadre == 0

    def test_una_compra_anulada_no_deja_capa(self, entorno):
        mouse = entorno.producto("Mouse")
        compra = comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 5, 20, dias=30)
        anular_movimiento(compra, motivo="Factura mal digitada")

        a = capas(entorno, mouse)
        assert pares(a) == [(entorno.hace(30), Decimal("5"))] and a.descuadre == 0

    def test_la_devolucion_al_proveedor_saca_de_lo_mas_antiguo(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 5, 20, dias=30)
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.DEVOLUCION_PROVEEDOR,
            fecha=entorno.hace(5),
            lineas=[LineaNueva(mouse, Decimal("4"), None)],
        )
        a = capas(entorno, mouse)
        assert pares(a) == [(entorno.hace(60), Decimal("6")), (entorno.hace(30), Decimal("5"))]

    def test_una_devolucion_de_cliente_cuenta_desde_su_fecha(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        vender(entorno, mouse, 10, dias=20)
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.DEVOLUCION_CLIENTE,
            fecha=entorno.hace(2),
            lineas=[LineaNueva(mouse, Decimal("2"), Decimal("20"))],
        )
        assert pares(capas(entorno, mouse)) == [(entorno.hace(2), Decimal("2"))]

    def test_el_traspaso_entre_almacenes_conserva_la_antiguedad(self, entorno):
        # Una segunda bodega de la MISMA empresa.
        from apps.mantenimiento.models import Almacen

        alm1b = Almacen.objects.sin_ambito().create(
            empresa=entorno.e1, sucursal=entorno.alm1.sucursal, codigo="ALM2", nombre="Bodega 2"
        )
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 10, 20, dias=30)
        registrar_traspaso(
            empresa=entorno.e1,
            origen=entorno.alm1,
            destino=alm1b,
            fecha=entorno.hace(5),
            lineas=[LineaNueva(mouse, Decimal("12"), None)],
        )
        origen = capas(entorno, mouse)
        destino = capas(entorno, mouse, almacen=alm1b)
        # Salieron 10 de hace 60 días y 2 de hace 30: llegan con SU fecha, no con la del traspaso.
        assert pares(destino) == [
            (entorno.hace(60), Decimal("10")),
            (entorno.hace(30), Decimal("2")),
        ]
        assert pares(origen) == [(entorno.hace(30), Decimal("8"))]

    def test_un_traspaso_anulado_no_mueve_nada(self, entorno):
        from apps.mantenimiento.models import Almacen

        alm1b = Almacen.objects.sin_ambito().create(
            empresa=entorno.e1, sucursal=entorno.alm1.sucursal, codigo="ALM2", nombre="Bodega 2"
        )
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        salida, _ = registrar_traspaso(
            empresa=entorno.e1,
            origen=entorno.alm1,
            destino=alm1b,
            fecha=entorno.hace(5),
            lineas=[LineaNueva(mouse, Decimal("4"), None)],
        )
        anular_movimiento(salida, motivo="Fue un error")
        assert pares(capas(entorno, mouse)) == [(entorno.hace(60), Decimal("10"))]
        assert capas(entorno, mouse, almacen=alm1b) is None  # nada en la otra bodega

    def test_cada_empresa_tiene_su_propia_antiguedad(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 3, 20, dias=7, empresa=entorno.e2, almacen=entorno.alm2)
        assert pares(capas(entorno, mouse)) == [(entorno.hace(60), Decimal("10"))]
        assert pares(capas(entorno, mouse, empresa=entorno.e2, almacen=entorno.alm2)) == [
            (entorno.hace(7), Decimal("3"))
        ]

    def test_sin_stock_no_hay_capas(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 5, 20, dias=10)
        vender(entorno, mouse, 5, dias=1)
        assert capas(entorno, mouse) is None

    def test_siempre_cuadra_con_el_saldo_real(self, entorno):
        """Una secuencia larga de entradas y salidas: las capas suman el saldo del almacén."""
        mouse = entorno.producto("Mouse")
        for dias, cant in ((90, 10), (75, 4), (40, 8), (12, 6)):
            comprar(entorno, mouse, cant, 20, dias=dias)
        for dias, cant in ((60, 3), (30, 9), (5, 2)):
            vender(entorno, mouse, cant, dias=dias)
        a = capas(entorno, mouse)
        assert sum(c.cantidad for c in a.capas) == saldo_de(entorno, mouse).cantidad == 14
        assert a.descuadre == 0 and a.sin_fecha == 0

    def test_si_el_kardex_no_explica_el_saldo_se_informa(self, entorno):
        from apps.inventario.models import SaldoStock

        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        SaldoStock.objects.sin_ambito().filter(producto=mouse).update(cantidad=Decimal("13"))
        a = capas(entorno, mouse)
        assert a.sin_fecha == 3 and a.descuadre == -3  # faltan 3 por explicar: no se inventan
        SaldoStock.objects.sin_ambito().filter(producto=mouse).update(cantidad=Decimal("8"))
        a = capas(entorno, mouse)
        assert a.descuadre == 2 and sum(c.cantidad for c in a.capas) == 8  # sobraban 2

    def test_no_depende_del_costeo(self, entorno):
        """El costo promedio no cambia por calcular antigüedad ni se usa para ella."""
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 10, 20, dias=60)
        comprar(entorno, mouse, 10, 30, dias=30)
        vender(entorno, mouse, 5, dias=10)
        antes = saldo_de(entorno, mouse)
        capas(entorno, mouse)
        despues = saldo_de(entorno, mouse)
        assert (antes.costo_total, antes.costo_unitario) == (
            despues.costo_total,
            despues.costo_unitario,
        )
        assert antes.costo_unitario == 25


class TestTramos:
    def test_reparte_las_unidades_en_tramos_y_cuenta_las_antiguas(self, entorno):
        mouse = entorno.producto("Mouse")
        for dias, cant in ((200, 1), (100, 2), (70, 3), (45, 4), (10, 5)):
            comprar(entorno, mouse, cant, 20, dias=dias)
        a = capas(entorno, mouse)
        assert a.por_tramos(entorno.hoy) == [5, 4, 3, 2, 1]  # 0-30, 31-60, 61-90, 91-180, 181+
        assert a.unidades_con_mas_de(90, entorno.hoy) == 3  # las de 100 y 200 días
        assert a.unidades_con_mas_de(30, entorno.hoy) == 10

    def test_el_dia_del_limite_aun_no_es_antiguo(self, entorno):
        mouse = entorno.producto("Mouse")
        comprar(entorno, mouse, 4, 20, dias=90)
        a = capas(entorno, mouse)
        assert a.unidades_con_mas_de(90, entorno.hoy) == 0  # justo 90 días: todavía no
        assert a.unidades_con_mas_de(89, entorno.hoy) == 4


class TestConfiguracion:
    def test_por_defecto_90_dias_y_se_puede_cambiar(self, entorno):
        from apps.organizacion.models import ConfiguracionEmpresa

        assert antiguedad.dias_para_considerar_antiguo(entorno.e1.pk) == 90
        fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=entorno.e1)
        fila.dias_stock_antiguo = 45
        fila.save()
        assert antiguedad.dias_para_considerar_antiguo(entorno.e1.pk) == 45
        assert antiguedad.dias_para_considerar_antiguo(entorno.e2.pk) == 90
