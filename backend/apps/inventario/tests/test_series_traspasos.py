"""Series o IMEI y traspasos entre almacenes: reglas del motor."""

from decimal import Decimal as D

import pytest

from apps.core.exceptions import DocumentoYaAnulado
from apps.inventario.exceptions import (
    AnulacionNoPermitida,
    MovimientoInvalido,
    StockInsuficiente,
)
from apps.inventario.models import (
    EstadoSerie,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    registrar_movimiento,
    registrar_traspaso,
)
from apps.mantenimiento.models import Almacen

from .conftest import comprar, saldo_de, vender

pytestmark = pytest.mark.django_db


@pytest.fixture
def celular(entorno):
    return entorno.producto("Celular X", lleva_serie=True)


@pytest.fixture
def alm1b(entorno):
    """Un segundo almacén de la empresa A1."""
    return Almacen.objects.sin_ambito().create(
        empresa=entorno.e1, sucursal=entorno.alm1.sucursal, codigo="ALM2", nombre="Almacén 1B"
    )


def entrar(entorno, producto, series, precio="500", *, dias=3, empresa=None, almacen=None, **extra):
    return registrar_movimiento(
        empresa=empresa or entorno.e1,
        almacen=almacen or entorno.alm1,
        tipo=TipoMovimiento.ENTRADA,
        origen=OrigenMovimiento.COMPRA,
        fecha=entorno.hace(dias),
        lineas=[LineaNueva(producto, D(len(series)), D(precio), series=tuple(series))],
        **extra,
    )


def sacar(entorno, producto, series, *, dias=1, almacen=None, origen=OrigenMovimiento.MERMA):
    return registrar_movimiento(
        empresa=entorno.e1,
        almacen=almacen or entorno.alm1,
        tipo=TipoMovimiento.SALIDA,
        origen=origen,
        fecha=entorno.hace(dias),
        lineas=[LineaNueva(producto, D(len(series)), series=tuple(series))],
    )


def series_de(producto, estado=None, almacen=None):
    consulta = SerieProducto.objects.sin_ambito().filter(producto=producto)
    if estado:
        consulta = consulta.filter(estado=estado)
    if almacen:
        consulta = consulta.filter(almacen=almacen)
    return sorted(consulta.values_list("numero", flat=True))


def trasladar(entorno, origen, destino, producto, cantidad, series=(), dias=1):
    return registrar_traspaso(
        empresa=entorno.e1,
        origen=origen,
        destino=destino,
        fecha=entorno.hace(dias),
        lineas=[LineaNueva(producto, D(cantidad), series=tuple(series))],
    )


class TestSeries:
    def test_la_compra_crea_una_fila_por_unidad(self, entorno, celular):
        m = entrar(entorno, celular, ["imei001", " imei 002".replace(" ", ""), "IMEI003"])
        assert series_de(celular, EstadoSerie.EN_STOCK) == ["IMEI001", "IMEI002", "IMEI003"]
        linea = m.lineas.get()
        assert SerieProducto.objects.sin_ambito().filter(entrada=linea).count() == 3
        saldo = saldo_de(entorno, celular)
        assert (saldo.cantidad, saldo.costo_total) == (3, 1500)

    def test_las_series_deben_coincidir_con_la_cantidad(self, entorno, celular):
        base = {
            "empresa": entorno.e1,
            "almacen": entorno.alm1,
            "tipo": TipoMovimiento.ENTRADA,
            "origen": OrigenMovimiento.COMPRA,
            "fecha": entorno.hace(1),
        }
        casos = [
            LineaNueva(celular, D("3"), D("500"), series=("AAA111", "BBB222")),  # faltan
            LineaNueva(celular, D("1"), D("500"), series=("AAA111", "BBB222")),  # sobran
            LineaNueva(celular, D("2"), D("500")),  # ninguna
            LineaNueva(celular, D("1.5"), D("500"), series=("AAA111", "BBB222")),  # no entera
            LineaNueva(celular, D("2"), D("500"), series=("AAA111", "AAA111")),  # repetida
            LineaNueva(celular, D("1"), D("500"), series=("AB",)),  # muy corta
            LineaNueva(celular, D("1"), D("500"), series=("AAA 111;DROP",)),  # caracteres raros
        ]
        for linea in casos:
            with pytest.raises(MovimientoInvalido):
                registrar_movimiento(**base, lineas=[linea])
        assert SerieProducto.objects.sin_ambito().count() == 0
        assert MovimientoInventario.objects.sin_ambito().count() == 0

    def test_un_producto_sin_serie_no_las_acepta(self, entorno):
        cemento = entorno.producto()
        with pytest.raises(MovimientoInvalido):
            entrar(entorno, cemento, ["AAA111"])

    def test_la_misma_serie_en_dos_lineas_del_movimiento(self, entorno, celular):
        with pytest.raises(MovimientoInvalido):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.ENTRADA,
                origen=OrigenMovimiento.COMPRA,
                fecha=entorno.hace(1),
                lineas=[
                    LineaNueva(celular, D("1"), D("500"), series=("AAA111",)),
                    LineaNueva(celular, D("1"), D("500"), series=("AAA111",)),
                ],
            )

    def test_una_serie_no_puede_estar_en_stock_dos_veces_ni_en_otra_empresa(self, entorno, celular):
        entrar(entorno, celular, ["AAA111"])
        with pytest.raises(MovimientoInvalido) as error:
            entrar(entorno, celular, ["AAA111"], dias=1)
        assert "ya está en stock" in error.value.mensaje
        with pytest.raises(MovimientoInvalido):
            entrar(entorno, celular, ["AAA111"], dias=1, empresa=entorno.e2, almacen=entorno.alm2)
        assert saldo_de(entorno, celular).cantidad == 1

    def test_la_salida_cierra_la_serie_y_se_puede_volver_a_ingresar(self, entorno, celular):
        entrar(entorno, celular, ["AAA111", "BBB222"])
        m = sacar(entorno, celular, ["AAA111"])
        cerrada = SerieProducto.objects.sin_ambito().get(numero="AAA111")
        assert (cerrada.estado, cerrada.salida.movimiento_id) == (EstadoSerie.SALIDO, m.pk)
        assert series_de(celular, EstadoSerie.EN_STOCK) == ["BBB222"]
        # Vuelve (devolución): fila nueva, el historial de la anterior se conserva.
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.DEVOLUCION_CLIENTE,
            fecha=entorno.hoy,
            lineas=[LineaNueva(celular, D("1"), D("450"), series=("AAA111",))],
        )
        assert series_de(celular, EstadoSerie.EN_STOCK) == ["AAA111", "BBB222"]
        assert SerieProducto.objects.sin_ambito().filter(numero="AAA111").count() == 2

    def test_solo_salen_las_series_que_estan_en_ese_almacen(self, entorno, celular, alm1b):
        entrar(entorno, celular, ["AAA111"])
        with pytest.raises(MovimientoInvalido) as error:
            sacar(entorno, celular, ["ZZZ999"])
        assert "no está en este almacén" in error.value.mensaje
        with pytest.raises(MovimientoInvalido):
            sacar(entorno, celular, ["AAA111"], almacen=alm1b)
        with pytest.raises(MovimientoInvalido):
            sacar(entorno, celular, [])  # sin series no se puede sacar un producto con serie
        assert saldo_de(entorno, celular).cantidad == 1
        assert series_de(celular, EstadoSerie.EN_STOCK) == ["AAA111"]

    def test_el_stock_siempre_coincide_con_las_series_en_stock(self, entorno, celular, alm1b):
        entrar(entorno, celular, ["A1A1A1", "B2B2B2", "C3C3C3", "D4D4D4"])
        sacar(entorno, celular, ["A1A1A1"])
        trasladar(entorno, entorno.alm1, alm1b, celular, 2, ["B2B2B2", "C3C3C3"])
        for almacen in (entorno.alm1, alm1b):
            saldo = saldo_de(entorno, celular, almacen=almacen)
            assert saldo.cantidad == len(series_de(celular, EstadoSerie.EN_STOCK, almacen))

    def test_anular_una_compra_con_series_las_cierra(self, entorno, celular):
        compra = entrar(entorno, celular, ["AAA111", "BBB222"])
        anular_movimiento(compra, motivo="Error de digitación")
        assert series_de(celular, EstadoSerie.EN_STOCK) == []
        assert saldo_de(entorno, celular).cantidad == 0

    def test_no_se_anula_una_compra_si_una_de_sus_series_ya_salio(self, entorno, celular):
        compra = entrar(entorno, celular, ["AAA111", "BBB222"])
        sacar(entorno, celular, ["AAA111"])
        with pytest.raises(AnulacionNoPermitida):
            anular_movimiento(compra, motivo="Error")
        assert series_de(celular, EstadoSerie.EN_STOCK) == ["BBB222"]
        assert saldo_de(entorno, celular).cantidad == 1

    def test_anular_una_salida_devuelve_las_mismas_series(self, entorno, celular):
        entrar(entorno, celular, ["AAA111", "BBB222"])
        salida = sacar(entorno, celular, ["AAA111", "BBB222"])
        anular_movimiento(salida, motivo="Cliente se arrepintió")
        assert series_de(celular, EstadoSerie.EN_STOCK) == ["AAA111", "BBB222"]
        assert saldo_de(entorno, celular).cantidad == 2

    def test_no_se_puede_cambiar_lleva_serie_con_movimientos(self, entorno, celular):
        from django.core.exceptions import ValidationError

        from apps.mantenimiento.productos import actualizar_producto

        libre = entorno.producto("Sin movimientos")
        actualizar_producto(libre, datos={"lleva_serie": True}, precios=None)  # sin historial: sí
        entrar(entorno, celular, ["AAA111"])
        with pytest.raises(ValidationError) as error:
            actualizar_producto(celular, datos={"lleva_serie": False}, precios=None)
        assert "movimientos" in str(error.value)

    def test_una_salida_no_lleva_importe_fijo(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 5, 10, dias=3)
        with pytest.raises(MovimientoInvalido):
            registrar_movimiento(
                empresa=entorno.e1,
                almacen=entorno.alm1,
                tipo=TipoMovimiento.SALIDA,
                origen=OrigenMovimiento.MERMA,
                fecha=entorno.hoy,
                lineas=[LineaNueva(cemento, D("1"), importe=D("5"))],
            )


class TestTraspasos:
    def test_mueve_stock_y_costo_entre_almacenes(self, entorno, alm1b):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=5)
        salida, entrada = trasladar(entorno, entorno.alm1, alm1b, cemento, 4)

        assert (salida.tipo, salida.origen) == (TipoMovimiento.SALIDA, OrigenMovimiento.TRASPASO)
        assert (entrada.tipo, entrada.origen) == (TipoMovimiento.ENTRADA, OrigenMovimiento.TRASPASO)
        assert salida.traspaso_id and salida.traspaso_id == entrada.traspaso_id
        assert (salida.tipo_operacion, entrada.tipo_operacion) == ("99", "99")
        origen, destino = saldo_de(entorno, cemento), saldo_de(entorno, cemento, almacen=alm1b)
        assert (origen.cantidad, origen.costo_total) == (6, 120)
        assert (destino.cantidad, destino.costo_total, destino.costo_unitario) == (4, 80, 20)
        # El total de la empresa no cambia: nada se creó ni se perdió.
        assert origen.cantidad + destino.cantidad == 10
        assert origen.costo_total + destino.costo_total == 200

    def test_el_costo_llega_mezclado_con_lo_que_ya_habia_en_el_destino(self, entorno, alm1b):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=5)
        comprar(entorno, cemento, 10, 30, dias=5, almacen=alm1b)
        trasladar(entorno, entorno.alm1, alm1b, cemento, 5)
        destino = saldo_de(entorno, cemento, almacen=alm1b)
        assert (destino.cantidad, destino.costo_total) == (15, 400)  # 300 + 5 × 20
        assert destino.costo_unitario == D("26.666667")

    def test_no_se_pierden_centavos_al_traspasar_en_partes(self, entorno, alm1b):
        cemento = entorno.producto()
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.SALDO_INICIAL,
            fecha=entorno.hace(5),
            lineas=[LineaNueva(cemento, D("3"), D("3.333333"))],  # 3 unidades por 10.00
        )
        for cantidad in (1, 1, 1):
            trasladar(entorno, entorno.alm1, alm1b, cemento, cantidad)
        origen, destino = saldo_de(entorno, cemento), saldo_de(entorno, cemento, almacen=alm1b)
        assert (origen.cantidad, origen.costo_total) == (0, 0)
        assert (destino.cantidad, destino.costo_total) == (3, D("10.00"))

    def test_sin_stock_en_el_origen_no_se_hace_nada(self, entorno, alm1b):
        cemento = entorno.producto()
        comprar(entorno, cemento, 2, 20, dias=5)
        total = MovimientoInventario.objects.sin_ambito().count()
        with pytest.raises(StockInsuficiente):
            trasladar(entorno, entorno.alm1, alm1b, cemento, 5)
        assert MovimientoInventario.objects.sin_ambito().count() == total
        assert saldo_de(entorno, cemento).cantidad == 2
        assert (
            not SaldoStock.objects.sin_ambito().filter(almacen=alm1b).exclude(cantidad=0).exists()
        )

    def test_validaciones(self, entorno, alm1b):
        cemento = entorno.producto()
        comprar(entorno, cemento, 5, 20, dias=5)
        with pytest.raises(MovimientoInvalido):  # mismo almacén
            trasladar(entorno, entorno.alm1, entorno.alm1, cemento, 1)
        with pytest.raises(MovimientoInvalido):  # almacén de otra empresa
            trasladar(entorno, entorno.alm1, entorno.alm2, cemento, 1)
        with pytest.raises(MovimientoInvalido):  # con precio
            registrar_traspaso(
                empresa=entorno.e1,
                origen=entorno.alm1,
                destino=alm1b,
                fecha=entorno.hoy,
                lineas=[LineaNueva(cemento, D("1"), D("20"))],
            )

    def test_las_series_viajan_con_la_mercaderia(self, entorno, celular, alm1b):
        entrar(entorno, celular, ["AAA111", "BBB222", "CCC333"])
        trasladar(entorno, entorno.alm1, alm1b, celular, 2, ["AAA111", "BBB222"])
        assert series_de(celular, EstadoSerie.EN_STOCK, entorno.alm1) == ["CCC333"]
        assert series_de(celular, EstadoSerie.EN_STOCK, alm1b) == ["AAA111", "BBB222"]
        sacar(entorno, celular, ["AAA111"], almacen=alm1b)  # ya se puede vender desde el destino
        with pytest.raises(MovimientoInvalido):
            sacar(entorno, celular, ["BBB222"])  # y ya no desde el origen

    def test_anular_un_traspaso_deshace_las_dos_mitades(self, entorno, celular, alm1b):
        entrar(entorno, celular, ["AAA111", "BBB222"])
        salida, entrada = trasladar(entorno, entorno.alm1, alm1b, celular, 2, ["AAA111", "BBB222"])

        extorno = anular_movimiento(entrada, motivo="Se envió al almacén equivocado")

        assert extorno.extorna_id == entrada.pk
        assert saldo_de(entorno, celular).cantidad == 2
        assert saldo_de(entorno, celular, almacen=alm1b).cantidad == 0
        assert series_de(celular, EstadoSerie.EN_STOCK, entorno.alm1) == ["AAA111", "BBB222"]
        for m in (salida, entrada):
            m.refresh_from_db()
            assert m.estado == MovimientoInventario.Estado.ANULADO
        with pytest.raises(DocumentoYaAnulado):
            anular_movimiento(salida, motivo="otra vez")

    def test_anular_desde_la_salida_tambien_anula_la_entrada(self, entorno, alm1b):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=5)
        salida, entrada = trasladar(entorno, entorno.alm1, alm1b, cemento, 4)
        anular_movimiento(salida, motivo="Error")
        assert saldo_de(entorno, cemento).cantidad == 10
        assert saldo_de(entorno, cemento, almacen=alm1b).cantidad == 0
        entrada.refresh_from_db()
        assert entrada.estado == MovimientoInventario.Estado.ANULADO

    def test_no_se_anula_si_lo_traspasado_ya_se_vendio(self, entorno, alm1b):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20, dias=5)
        salida, _ = trasladar(entorno, entorno.alm1, alm1b, cemento, 4)
        vender(entorno, cemento, 4, almacen=alm1b, dias=0)
        total = MovimientoInventario.objects.sin_ambito().count()
        with pytest.raises(AnulacionNoPermitida):
            anular_movimiento(salida, motivo="Error")
        assert MovimientoInventario.objects.sin_ambito().count() == total  # nada a medias
        salida.refresh_from_db()
        assert salida.estado == MovimientoInventario.Estado.EMITIDO
