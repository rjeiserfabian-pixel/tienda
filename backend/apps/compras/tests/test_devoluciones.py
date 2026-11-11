from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.compras.devoluciones import (
    LineaDevuelta,
    ParteLinea,
    Previo,
    anular_devolucion,
    calcular_devolucion,
    pendiente_de_devolver,
    registrar_devolucion,
)
from apps.compras.exceptions import CompraNoAnulable, DevolucionInvalida
from apps.compras.models import DevolucionCompra
from apps.compras.servicios import LineaEntrada, anular_compra
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.inventario.exceptions import ComprobanteDuplicado, StockInsuficiente
from apps.inventario.models import (
    EstadoSerie,
    MovimientoInventario,
    OrigenMovimiento,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.inventario.tests.conftest import saldo_de, vender
from apps.mantenimiento.models import TipoComprobante

from .conftest import dec

pytestmark = pytest.mark.django_db

CERO = Decimal("0")


def parte(cantidad, valor, impuesto="0", costo=None, pedida="1", previo=None, factor="1"):
    return ParteLinea(
        cantidad=dec(cantidad),
        cantidad_base=dec(cantidad) * dec(factor),
        factor=dec(factor),
        valor_venta=dec(valor),
        impuesto=dec(impuesto),
        costo_soles=dec(costo if costo is not None else valor),
        grupo="GRAVADO",
        tipo_impuesto="IGV",
        previo=previo or Previo(),
        pedida=dec(pedida),
    )


class TestCalculo:
    def test_proporcional(self):
        r = calcular_devolucion([parte("10", "100", "18", pedida="4")])
        ln = r.lineas[0]
        assert (ln.valor_venta, ln.impuesto, ln.total, ln.costo_soles) == (
            dec("40.00"),
            dec("7.20"),
            dec("47.20"),
            dec("40.00"),
        )
        assert (r.op_gravada, r.igv, r.total, r.queda_pendiente) == (
            dec("40.00"),
            dec("7.20"),
            dec("47.20"),
            True,
        )

    def test_devolver_todo_toma_la_linea_completa(self):
        r = calcular_devolucion([parte("3", "100", "18", pedida="3")])
        assert (r.lineas[0].valor_venta, r.lineas[0].impuesto) == (dec("100"), dec("18"))
        assert r.queda_pendiente is False

    def test_devoluciones_sucesivas_suman_exactamente_la_linea(self):
        valores = []
        previo = Previo()
        for _ in range(3):
            r = calcular_devolucion(
                [parte("3", "100", "18", costo="100.01", pedida="1", previo=previo)]
            )
            ln = r.lineas[0]
            valores.append((ln.valor_venta, ln.impuesto, ln.costo_soles))
            previo = Previo(
                previo.cantidad + 1,
                previo.cantidad_base + 1,
                previo.valor_venta + ln.valor_venta,
                previo.impuesto + ln.impuesto,
                previo.costo_soles + ln.costo_soles,
            )
        assert sum(v[0] for v in valores) == dec("100")
        assert sum(v[1] for v in valores) == dec("18")
        assert sum(v[2] for v in valores) == dec("100.01")

    def test_no_se_puede_devolver_mas_de_lo_pendiente(self):
        previo = Previo(dec("8"), dec("8"), dec("80"), dec("14.4"), dec("80"))
        with pytest.raises(DevolucionInvalida, match="Solo se puede devolver 2"):
            calcular_devolucion([parte("10", "100", "18", pedida="3", previo=previo)])

    def test_cantidad_cero_o_negativa(self):
        with pytest.raises(DevolucionInvalida):
            calcular_devolucion([parte("10", "100", pedida="0")])

    def test_ajuste_de_redondeo_va_al_total_y_no_al_costo(self):
        r = calcular_devolucion(
            [parte("10", "100", "18", pedida="4")], ajuste_redondeo=dec("-0.02")
        )
        assert (r.total, r.costo_soles) == (dec("47.18"), dec("40.00"))

    def test_ajuste_fuera_de_tope(self):
        with pytest.raises(DevolucionInvalida):
            calcular_devolucion([parte("10", "100", pedida="1")], ajuste_redondeo=dec("0.50"))

    def test_presentacion_convierte_a_unidad_base(self):
        r = calcular_devolucion([parte("5", "100", pedida="2", factor="12")])
        assert r.lineas[0].cantidad_base == dec("24")

    def test_grupos_exonerado_e_inafecto(self):
        exo = replace(parte("1", "50", pedida="1"), grupo="EXONERADO", tipo_impuesto="NINGUNO")
        ina = replace(parte("1", "30", pedida="1"), grupo="INAFECTO", tipo_impuesto="NINGUNO")
        gr = parte("1", "100", "18", pedida="1")
        r = calcular_devolucion([gr, exo, ina])
        assert (r.op_gravada, r.igv, r.op_exonerada, r.op_inafecta, r.total) == (
            dec("100"),
            dec("18"),
            dec("50"),
            dec("30"),
            dec("198"),
        )


@pytest.fixture
def nota(compras):
    return TipoComprobante.objects.sin_ambito().get(
        organizacion=compras.entorno.e.org_a, codigo="07"
    )


@pytest.fixture
def devolver(compras, nota):
    contador = iter(range(1, 1000))

    def _devolver(compra, lineas, **extra):
        datos = {
            "empresa": compras.empresa,
            "compra": compra,
            "tipo_comprobante": nota,
            "comprobante_serie": "FC01",
            "comprobante_numero": str(next(contador)),
            "fecha_emision": compras.entorno.hoy,
            "razon": "Mercadería dañada",
            "lineas": lineas,
        }
        datos.update(extra)
        return registrar_devolucion(**datos)

    return _devolver


def una_compra(compras, cantidad="10", precio="10", **extra):
    producto = extra.pop("producto", None) or compras.entorno.producto()
    c = compras.comprar([LineaEntrada(producto, dec(cantidad), dec(precio), **extra)])
    return producto, c, c.lineas.get()


class TestRegistrar:
    def test_devolucion_parcial_saca_stock_al_costo_de_la_compra(self, compras, devolver):
        producto, c, ln = una_compra(compras)
        d = devolver(c, [LineaDevuelta(ln.pk, dec("4"))])
        assert (d.numero, d.estado, d.motivo, d.moneda) == (1, "EMITIDO", "POR_ITEM", "PEN")
        assert (d.op_gravada, d.igv, d.total, d.costo_soles) == (
            dec("40"),
            dec("7.20"),
            dec("47.20"),
            dec("40"),
        )
        saldo = saldo_de(compras.entorno, producto)
        assert (saldo.cantidad, saldo.costo_total) == (dec("6"), dec("60"))
        m = d.movimiento
        assert (m.tipo, m.origen, m.comprobante_tipo, m.comprobante_serie) == (
            "SALIDA",
            "DEVOLUCION_PROVEEDOR",
            "07",
            "FC01",
        )
        assert (m.proveedor_id, m.referencia_tipo, m.total) == (
            compras.proveedor.pk,
            "devolucion_compra",
            dec("47.20"),
        )
        linea = d.lineas.get()
        assert (linea.cantidad, linea.cantidad_base, linea.total) == (
            dec("4"),
            dec("4"),
            dec("47.20"),
        )

    def test_devolucion_total_deja_la_compra_sin_pendiente(self, compras, devolver):
        producto, c, ln = una_compra(compras)
        d = devolver(c, [LineaDevuelta(ln.pk, dec("10"))])
        assert (d.motivo, d.total) == ("TOTAL", c.total)
        assert saldo_de(compras.entorno, producto).cantidad == 0
        assert pendiente_de_devolver(c)[0]["pendiente"] == 0

    def test_dos_devoluciones_suman_la_compra_completa(self, compras, devolver):
        producto, c, ln = una_compra(compras, cantidad="3", precio="33.33")
        d1 = devolver(c, [LineaDevuelta(ln.pk, dec("1"))])
        d2 = devolver(c, [LineaDevuelta(ln.pk, dec("2"))])
        assert (d1.motivo, d2.motivo) == ("POR_ITEM", "TOTAL")
        assert d1.total + d2.total == c.total
        assert d1.igv + d2.igv == c.igv
        assert d1.costo_soles + d2.costo_soles == ln.costo_soles
        assert [d1.numero, d2.numero] == [1, 2]

    def test_sale_al_costo_de_esa_compra_y_no_al_promedio(self, compras, devolver):
        producto, c1, ln1 = una_compra(compras, precio="10")
        compras.comprar([LineaEntrada(producto, dec(10), dec("20"))])
        assert saldo_de(compras.entorno, producto).costo_unitario == dec("15")
        d = devolver(c1, [LineaDevuelta(ln1.pk, dec("5"))])
        assert d.costo_soles == dec("50")
        saldo = saldo_de(compras.entorno, producto)
        assert (saldo.cantidad, saldo.costo_total) == (dec("15"), dec("250"))

    def test_no_se_devuelve_mas_de_lo_pendiente(self, compras, devolver):
        _, c, ln = una_compra(compras)
        devolver(c, [LineaDevuelta(ln.pk, dec("8"))])
        with pytest.raises(DevolucionInvalida, match="Solo se puede devolver 2"):
            devolver(c, [LineaDevuelta(ln.pk, dec("3"))])

    def test_no_se_devuelve_lo_que_ya_se_vendio(self, compras, devolver):
        producto, c, ln = una_compra(compras)
        vender(compras.entorno, producto, 8)
        with pytest.raises(StockInsuficiente):
            devolver(c, [LineaDevuelta(ln.pk, dec("5"))])
        assert not DevolucionCompra.objects.exists()
        assert saldo_de(compras.entorno, producto).cantidad == 2

    def test_compra_anulada_no_se_devuelve(self, compras, devolver):
        _, c, ln = una_compra(compras)
        anular_compra(c, motivo="Error")
        with pytest.raises(DevolucionInvalida, match="anulada"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))])

    def test_misma_nota_del_proveedor_no_se_registra_dos_veces(self, compras, devolver):
        _, c, ln = una_compra(compras)
        devolver(c, [LineaDevuelta(ln.pk, dec("1"))], comprobante_numero="55")
        with pytest.raises(ComprobanteDuplicado):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))], comprobante_numero="55")
        assert DevolucionCompra.objects.count() == 1

    def test_la_falla_no_deja_nada_a_medias(self, compras, devolver):
        producto, c, ln = una_compra(compras)
        devolver(c, [LineaDevuelta(ln.pk, dec("1"))], comprobante_numero="9")
        antes = MovimientoInventario.objects.count()
        with pytest.raises(ComprobanteDuplicado):
            devolver(c, [LineaDevuelta(ln.pk, dec("2"))], comprobante_numero="9")
        assert MovimientoInventario.objects.count() == antes
        assert saldo_de(compras.entorno, producto).cantidad == 9


class TestValidaciones:
    def test_el_comprobante_debe_ser_nota_de_credito(self, compras, devolver):
        _, c, ln = una_compra(compras)
        with pytest.raises(DevolucionInvalida, match="nota de crédito"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))], tipo_comprobante=compras.factura)

    def test_fecha_futura_o_anterior_a_la_compra(self, compras, devolver):
        _, c, ln = una_compra(compras)
        hoy = compras.entorno.hoy
        with pytest.raises(DevolucionInvalida, match="futura"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))], fecha_emision=hoy + timedelta(days=1))
        with pytest.raises(DevolucionInvalida, match="anterior"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))], fecha_emision=hoy - timedelta(days=5))

    def test_razon_obligatoria(self, compras, devolver):
        _, c, ln = una_compra(compras)
        with pytest.raises(DevolucionInvalida, match="por qué"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))], razon="  ")

    def test_sin_lineas_o_linea_ajena_o_repetida(self, compras, devolver):
        _, c, ln = una_compra(compras)
        _, otra, ln_otra = una_compra(compras)
        with pytest.raises(DevolucionInvalida):
            devolver(c, [])
        with pytest.raises(DevolucionInvalida, match="no pertenece"):
            devolver(c, [LineaDevuelta(ln_otra.pk, dec("1"))])
        with pytest.raises(DevolucionInvalida, match="se repite"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1")), LineaDevuelta(ln.pk, dec("1"))])

    def test_cantidad_con_mas_de_tres_decimales(self, compras, devolver):
        _, c, ln = una_compra(compras)
        with pytest.raises(DevolucionInvalida, match="3 decimales"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1.0001"))])

    def test_empresa_distinta_a_la_de_la_compra(self, compras, devolver):
        _, c, ln = una_compra(compras)
        with pytest.raises(DevolucionInvalida, match="no pertenece"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"))], empresa=compras.entorno.e2)


class TestAnular:
    def test_anular_devuelve_el_stock_y_libera_lo_pendiente(self, compras, devolver):
        producto, c, ln = una_compra(compras)
        d = devolver(c, [LineaDevuelta(ln.pk, dec("4"))])
        anular_devolucion(d, motivo="Se envió por error")
        d.refresh_from_db()
        assert d.estado == "ANULADO"
        saldo = saldo_de(compras.entorno, producto)
        assert (saldo.cantidad, saldo.costo_total) == (dec("10"), dec("100"))
        assert pendiente_de_devolver(c)[0]["pendiente"] == 10
        d2 = devolver(c, [LineaDevuelta(ln.pk, dec("10"))])
        assert d2.motivo == "TOTAL"

    def test_motivo_obligatorio_y_no_se_anula_dos_veces(self, compras, devolver):
        _, c, ln = una_compra(compras)
        d = devolver(c, [LineaDevuelta(ln.pk, dec("2"))])
        with pytest.raises(MotivoObligatorio):
            anular_devolucion(d, motivo=" ")
        anular_devolucion(d, motivo="Error")
        with pytest.raises(DocumentoYaAnulado):
            anular_devolucion(d, motivo="Otra vez")

    def test_la_compra_con_devolucion_vigente_no_se_anula(self, compras, devolver):
        _, c, ln = una_compra(compras)
        d = devolver(c, [LineaDevuelta(ln.pk, dec("2"))])
        with pytest.raises(CompraNoAnulable, match="devoluciones"):
            anular_compra(c, motivo="Error")
        anular_devolucion(d, motivo="Error")
        anular_compra(c, motivo="Error")
        c.refresh_from_db()
        assert c.estado == "ANULADO"


class TestSeries:
    def test_devuelve_las_series_elegidas(self, compras, devolver):
        producto = compras.entorno.producto("Celular", lleva_serie=True)
        _, c, ln = una_compra(
            compras,
            cantidad="2",
            precio="500",
            producto=producto,
            series=("IMEI0001", "IMEI0002"),
        )
        d = devolver(c, [LineaDevuelta(ln.pk, dec("1"), ("imei0002",))])
        estados = dict(SerieProducto.objects.values_list("numero", "estado"))
        assert estados == {"IMEI0001": EstadoSerie.EN_STOCK, "IMEI0002": EstadoSerie.SALIDO}
        anular_devolucion(d, motivo="Error")
        estados = dict(SerieProducto.objects.values_list("numero", "estado"))
        assert set(estados.values()) == {EstadoSerie.EN_STOCK}

    def test_serie_que_no_es_de_la_compra_o_cantidad_distinta(self, compras, devolver):
        producto = compras.entorno.producto("Celular", lleva_serie=True)
        _, c, ln = una_compra(
            compras, cantidad="2", precio="500", producto=producto, series=("IMEI0001", "IMEI0002")
        )
        with pytest.raises(DevolucionInvalida, match="no pertenece a esta compra"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"), ("IMEI9999",))])
        with pytest.raises(DevolucionInvalida, match="indique 1 serie"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"), ())])

    def test_serie_ya_vendida_no_se_devuelve(self, compras, devolver):
        producto = compras.entorno.producto("Celular", lleva_serie=True)
        _, c, ln = una_compra(
            compras, cantidad="2", precio="500", producto=producto, series=("IMEI0001", "IMEI0002")
        )
        registrar_movimiento(
            empresa=compras.empresa,
            almacen=compras.almacen,
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.VENTA,
            fecha=compras.entorno.hoy,
            lineas=[LineaNueva(producto, dec(1), series=("IMEI0001",))],
        )
        with pytest.raises(DevolucionInvalida, match="ya no está en el almacén"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"), ("IMEI0001",))])

    def test_producto_sin_serie_no_acepta_series(self, compras, devolver):
        _, c, ln = una_compra(compras)
        with pytest.raises(DevolucionInvalida, match="no lleva serie"):
            devolver(c, [LineaDevuelta(ln.pk, dec("1"), ("ABC123",))])
