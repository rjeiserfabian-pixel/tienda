"""Recibir mercadería contra una orden de compra: cantidades, estados, precios y reversa."""

from datetime import timedelta

import pytest

from apps.compras.devoluciones import LineaDevuelta, registrar_devolucion
from apps.compras.exceptions import CompraInvalida, OrdenCompraNoModificable
from apps.compras.models import LineaOrdenCompra, OrdenCompra
from apps.compras.ordenes import (
    LineaOrden,
    anular_orden,
    cerrar_orden,
    crear_orden,
    emitir_orden,
    pendiente_de_recibir,
    reabrir_orden,
)
from apps.compras.servicios import LineaEntrada, anular_compra, preparar_compra
from apps.inventario.exceptions import ComprobanteDuplicado
from apps.inventario.models import MovimientoInventario
from apps.inventario.tests.conftest import saldo_de
from apps.mantenimiento.models import TipoComprobante
from apps.organizacion.models import ConfiguracionEmpresa

from .conftest import dec

pytestmark = pytest.mark.django_db

Estado = OrdenCompra.Estado


@pytest.fixture
def orden(compras):
    """Orden emitida de 10 unidades de un producto a 10 + IGV."""
    producto = compras.entorno.producto()
    o = crear_orden(
        empresa=compras.empresa,
        proveedor=compras.proveedor,
        almacen=compras.almacen,
        fecha_emision=compras.entorno.hoy,
        lineas=[LineaOrden(producto, dec(10), dec(10))],
    )
    o = emitir_orden(o, puede_aprobar=True)
    o.producto = producto
    return o


def recibir(compras, orden, cantidad, precio="10", **extra):
    """Registra una compra contra la orden, tal como la API: con la orden recién leída."""
    orden = recargar(orden)
    linea = LineaEntrada(
        orden.producto, dec(cantidad), dec(precio), linea_orden=extra.pop("linea", None)
    )
    return compras.comprar([linea], orden=orden, **extra)


def recargar(orden):
    producto = orden.producto
    nueva = OrdenCompra.objects.get(pk=orden.pk)
    nueva.producto = producto
    return nueva


def recibido(orden):
    return LineaOrdenCompra.objects.get(orden=orden).cantidad_recibida


def configurar_tolerancia(compras, valor):
    fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=compras.empresa)
    fila.orden_compra_tolerancia = dec(valor)
    fila.save()


class TestRecibir:
    def test_recepcion_completa_deja_la_orden_recibida(self, compras, orden):
        c = recibir(compras, orden, 10)
        assert c.orden_id == orden.pk
        ln = c.lineas.get()
        assert ln.linea_orden_id == orden.lineas.get().pk and ln.precio_pactado == dec("10")
        o = recargar(orden)
        assert o.estado == Estado.RECIBIDA and recibido(o) == 10
        assert saldo_de(compras.entorno, orden.producto).cantidad == 10

    def test_recepciones_por_partes(self, compras, orden):
        recibir(compras, orden, 4)
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.PARCIAL, 4)
        fila = pendiente_de_recibir(o)[0]
        assert (fila["recibido"], fila["pendiente"], fila["maximo_recibible"]) == (4, 6, 6)
        recibir(compras, orden, 6)
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.RECIBIDA, 10)

    def test_no_se_recibe_mas_de_lo_pedido(self, compras, orden):
        recibir(compras, orden, 8)
        with pytest.raises(CompraInvalida, match="como máximo se pueden recibir 2"):
            recibir(compras, orden, 3)
        o = recargar(orden)
        assert recibido(o) == 8 and o.compras.count() == 1
        assert saldo_de(compras.entorno, orden.producto).cantidad == 8

    def test_la_tolerancia_permite_recibir_un_poco_mas(self, compras, orden):
        configurar_tolerancia(compras, "10")
        recibir(compras, orden, 11)
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.RECIBIDA, 11)
        with pytest.raises(CompraInvalida, match="por completo"):
            recibir(compras, orden, 1)  # ya está recibida

    def test_la_tolerancia_tiene_tope(self, compras, orden):
        configurar_tolerancia(compras, "10")
        with pytest.raises(CompraInvalida, match="como máximo se pueden recibir 11"):
            recibir(compras, orden, 12)

    def test_una_falla_posterior_no_deja_la_orden_a_medias(self, compras, orden):
        # El comprobante repetido falla al registrar la entrada: la orden no debe cambiar.
        recibir(compras, orden, 2, comprobante_numero="777")
        with pytest.raises(ComprobanteDuplicado):
            recibir(compras, orden, 3, comprobante_numero="777")
        o = recargar(orden)
        assert recibido(o) == 2 and o.compras.count() == 1

    def test_dos_lineas_de_la_compra_para_la_misma_de_la_orden_se_suman(self, compras, orden):
        lineas = [
            LineaEntrada(orden.producto, dec(6), dec(10)),
            LineaEntrada(orden.producto, dec(5), dec(10)),
        ]
        with pytest.raises(CompraInvalida, match="como máximo se pueden recibir 10"):
            compras.comprar(lineas, orden=orden)

    def test_cada_linea_va_a_la_suya(self, compras):
        a, b = compras.entorno.producto("A"), compras.entorno.producto("B")
        o = emitir_orden(
            crear_orden(
                empresa=compras.empresa,
                proveedor=compras.proveedor,
                almacen=compras.almacen,
                fecha_emision=compras.entorno.hoy,
                lineas=[LineaOrden(a, dec(5), dec(2)), LineaOrden(b, dec(5), dec(3))],
            ),
            puede_aprobar=True,
        )
        compras.comprar([LineaEntrada(b, dec(5), dec(3))], orden=o)
        lineas = {ln.producto_id: ln for ln in LineaOrdenCompra.objects.filter(orden=o)}
        assert (lineas[a.pk].cantidad_recibida, lineas[b.pk].cantidad_recibida) == (0, 5)
        assert recargar_estado(o) == Estado.PARCIAL

    def test_la_linea_de_orden_indicada_debe_ser_la_del_producto(self, compras, orden):
        otro = compras.entorno.producto("Otro")
        con_dos = emitir_orden(
            crear_orden(
                empresa=compras.empresa,
                proveedor=compras.proveedor,
                almacen=compras.almacen,
                fecha_emision=compras.entorno.hoy,
                lineas=[
                    LineaOrden(orden.producto, dec(5), dec(10)),
                    LineaOrden(otro, dec(5), dec(10)),
                ],
            ),
            puede_aprobar=True,
        )
        con_dos.producto = orden.producto
        de_otro = LineaOrdenCompra.objects.get(orden=con_dos, producto=otro).pk
        with pytest.raises(CompraInvalida, match="no coincide"):
            recibir(compras, con_dos, 1, linea=de_otro)
        # y una línea de OTRA orden tampoco vale
        ajena = orden.lineas.get().pk
        with pytest.raises(CompraInvalida, match="no pertenece a la orden"):
            recibir(compras, con_dos, 1, linea=ajena)
        with pytest.raises(CompraInvalida, match="no pertenece a la orden"):
            recibir(compras, con_dos, 1, linea=999_999)

    def test_la_linea_de_orden_indicada_se_respeta(self, compras, orden):
        propia = orden.lineas.get().pk
        c = recibir(compras, orden, 2, linea=propia)
        assert c.lineas.get().linea_orden_id == propia

    def test_producto_fuera_de_la_orden(self, compras, orden):
        extra = compras.entorno.producto("Extra")
        with pytest.raises(CompraInvalida, match="no está en la orden"):
            compras.comprar([LineaEntrada(extra, dec(1), dec(1))], orden=orden)

    def test_presentacion_distinta_a_la_de_la_orden(self, compras, orden):
        from apps.mantenimiento.models import PresentacionProducto, UnidadMedida

        caja = UnidadMedida.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, nombre="Caja", abreviatura="CJ", codigo_sunat="BX"
        )
        pres = PresentacionProducto.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a,
            producto=orden.producto,
            unidad=caja,
            factor=dec(12),
        )
        with pytest.raises(CompraInvalida, match="en otra presentación"):
            compras.comprar(
                [LineaEntrada(orden.producto, dec(1), dec(120), presentacion=pres)], orden=orden
            )

    def test_linea_de_orden_sin_orden(self, compras, orden):
        with pytest.raises(CompraInvalida, match="pero no la orden"):
            compras.comprar(
                [LineaEntrada(orden.producto, dec(1), dec(10), linea_orden=orden.lineas.get().pk)]
            )


def recargar_estado(o):
    return OrdenCompra.objects.get(pk=o.pk).estado


class TestQueOrdenesRecibenYComo:
    def _otra(self, compras, producto, cantidad=5):
        return crear_orden(
            empresa=compras.empresa,
            proveedor=compras.proveedor,
            almacen=compras.almacen,
            fecha_emision=compras.entorno.hoy,
            lineas=[LineaOrden(producto, dec(cantidad), dec(10))],
        )

    def _intentar(self, compras, orden, producto):
        compras.comprar([LineaEntrada(producto, dec(1), dec(10))], orden=orden)

    def test_borrador(self, compras, orden):
        with pytest.raises(CompraInvalida, match="borrador"):
            self._intentar(compras, self._otra(compras, orden.producto), orden.producto)

    def test_por_aprobar(self, compras, orden):
        fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=compras.empresa)
        fila.orden_compra_monto_aprobacion = dec("10")
        fila.save()
        pendiente = emitir_orden(self._otra(compras, orden.producto), puede_aprobar=False)
        assert pendiente.estado == Estado.PENDIENTE
        with pytest.raises(CompraInvalida, match="por aprobar"):
            self._intentar(compras, pendiente, orden.producto)

    def test_anulada(self, compras, orden):
        anulada = anular_orden(self._otra(compras, orden.producto), motivo="Error")
        with pytest.raises(CompraInvalida, match="anulada"):
            self._intentar(compras, anulada, orden.producto)

    def test_recibida_por_completo(self, compras, orden):
        recibir(compras, orden, 10)
        with pytest.raises(CompraInvalida, match="por completo"):
            recibir(compras, orden, 1)

    def test_orden_cerrada_no_recibe(self, compras, orden):
        recibir(compras, orden, 3)
        cerrar_orden(recargar(orden), motivo="No entrega más")
        with pytest.raises(CompraInvalida, match="cerrada"):
            recibir(compras, orden, 1)

    def test_otro_proveedor_otra_moneda_y_fecha_anterior(self, compras, orden):
        linea = [LineaEntrada(orden.producto, dec(1), dec(10))]
        with pytest.raises(CompraInvalida, match="otro proveedor"):
            compras.comprar(linea, orden=orden, proveedor=compras.entorno.otro_proveedor)
        with pytest.raises(CompraInvalida, match="otra moneda"):
            compras.comprar(linea, orden=orden, moneda="USD", tipo_cambio=dec("3.75"))
        with pytest.raises(CompraInvalida, match="anterior a la orden"):
            compras.comprar(
                linea, orden=orden, fecha_emision=compras.entorno.hoy - timedelta(days=1)
            )


class TestPrecios:
    def _previa(self, compras, orden, precio, **extra):
        return preparar_compra(
            empresa=compras.empresa,
            proveedor=compras.proveedor,
            almacen=compras.almacen,
            tipo_comprobante=compras.factura,
            comprobante_serie="F001",
            comprobante_numero="1",
            fecha_emision=compras.entorno.hoy,
            lineas=[LineaEntrada(orden.producto, dec(2), dec(precio))],
            forma_pago="CREDITO",
            completa=False,
            orden=orden,
            **extra,
        )

    def test_mismo_precio_no_avisa(self, compras, orden):
        assert self._previa(compras, orden, "10").avisos_precio == []

    def test_precio_distinto_avisa_con_la_diferencia(self, compras, orden):
        avisos = self._previa(compras, orden, "11").avisos_precio
        assert len(avisos) == 1
        a = avisos[0]
        assert (a["precio_pactado"], a["precio_facturado"], a["diferencia"], a["porcentaje"]) == (
            dec("10"),
            dec("11"),
            dec("1.0000"),
            dec("10.00"),
        )
        assert a["producto_nombre"] == orden.producto.nombre

    def test_manda_el_precio_del_comprobante(self, compras, orden):
        c = recibir(compras, orden, 2, precio="11")
        ln = c.lineas.get()
        assert (ln.precio_unitario, ln.precio_pactado) == (dec("11"), dec("10"))
        assert saldo_de(compras.entorno, orden.producto).costo_total == dec("22")

    def test_si_solo_cambia_la_forma_de_escribirlo_no_avisa(self, compras, orden):
        # 11,80 con IGV equivale a 10,00 sin IGV, que es lo pactado.
        previa = self._previa(compras, orden, "11.80", precios_incluyen_igv=True)
        assert previa.avisos_precio == []

    def test_la_vista_previa_no_escribe_nada(self, compras, orden):
        self._previa(compras, orden, "12")
        assert MovimientoInventario.objects.count() == 0 and recibido(orden) == 0


class TestAnularLaCompra:
    def test_revierte_lo_recibido_y_el_estado(self, compras, orden):
        c1 = recibir(compras, orden, 4)
        c2 = recibir(compras, orden, 6)
        assert recargar_estado(orden) == Estado.RECIBIDA
        anular_compra(c2, motivo="Factura repetida")
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.PARCIAL, 4)
        anular_compra(c1, motivo="Factura repetida")
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.EMITIDA, 0)

    def test_se_puede_volver_a_recibir_lo_anulado(self, compras, orden):
        c = recibir(compras, orden, 10)
        anular_compra(c, motivo="Error")
        recibir(compras, orden, 10)
        assert recargar_estado(orden) == Estado.RECIBIDA

    def test_en_una_orden_cerrada_se_revierten_las_cantidades_pero_sigue_cerrada(
        self, compras, orden
    ):
        c = recibir(compras, orden, 4)
        cerrar_orden(recargar(orden), motivo="No entrega más")
        anular_compra(c, motivo="Error")
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.CERRADA, 0)

    def test_la_orden_no_se_reabre_ni_anula_mientras_haya_compras_vigentes(self, compras, orden):
        c = recibir(compras, orden, 4)
        with pytest.raises(OrdenCompraNoModificable, match="reabrir"):
            reabrir_orden(recargar(orden))
        with pytest.raises(OrdenCompraNoModificable, match="anular"):
            anular_orden(recargar(orden), motivo="Error")
        anular_compra(c, motivo="Error")
        anular_orden(recargar(orden), motivo="Ya no se necesita")
        assert recargar_estado(orden) == Estado.ANULADA

    def test_con_una_compra_vigente_enlazada_tampoco_se_reabre(self, compras, orden):
        # Aunque el estado no se hubiera actualizado, la compra enlazada lo impide.
        recibir(compras, orden, 4)
        OrdenCompra.objects.filter(pk=orden.pk).update(estado=Estado.EMITIDA)
        LineaOrdenCompra.objects.filter(orden=orden).update(cantidad_recibida=0)
        with pytest.raises(OrdenCompraNoModificable, match="ya recibió"):
            reabrir_orden(recargar(orden))

    def test_una_compra_sin_orden_se_anula_como_siempre(self, compras):
        c = compras.comprar()
        anular_compra(c, motivo="Error")
        c.refresh_from_db()
        assert c.estado == "ANULADO" and c.orden_id is None


class TestConOtrasOperaciones:
    def test_una_devolucion_no_cambia_lo_recibido(self, compras, orden):
        c = recibir(compras, orden, 10)
        nota = TipoComprobante.objects.sin_ambito().get(
            organizacion=compras.entorno.e.org_a, codigo="07"
        )
        registrar_devolucion(
            empresa=compras.empresa,
            compra=c,
            tipo_comprobante=nota,
            comprobante_serie="FC01",
            comprobante_numero="1",
            fecha_emision=compras.entorno.hoy,
            razon="Mercadería dañada",
            lineas=[LineaDevuelta(c.lineas.get().pk, dec(4))],
        )
        o = recargar(orden)
        assert (o.estado, recibido(o)) == (Estado.RECIBIDA, 10)

    def test_las_compras_sin_orden_no_se_ven_afectadas(self, compras, orden):
        c = compras.comprar()
        assert c.orden_id is None and c.lineas.get().linea_orden_id is None
        assert recibido(orden) == 0
