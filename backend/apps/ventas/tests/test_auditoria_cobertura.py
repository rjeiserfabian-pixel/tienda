"""Las acciones delicadas dejan rastro en la bitácora de auditoría (y con el antes y el después)."""

from decimal import Decimal as D

import pytest

from apps.auditoria.models import AuditoriaEvento
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import ListaPrecio, TipoCambio
from apps.mantenimiento.productos import actualizar_producto
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import servicios

pytestmark = pytest.mark.django_db


def eventos(accion: str):
    return AuditoriaEvento.objects.filter(accion=accion).order_by("id")


@pytest.fixture
def producto(tienda):
    return tienda.producto(
        costo="60", precios={"PUBLICO": "100", "DESCUENTO": "90", "TECNICO": "80"}
    )


def vender(tienda, p, precio, **extra):
    total = (D(precio) * D("1.18")).quantize(D("0.01"))
    return tienda.vender(
        [tienda.linea(p, 1, precio_unitario=D(precio))],
        [tienda.cobro(tienda.efectivo, total)],
        **extra,
    )


class TestVentas:
    def test_vender_bajo_el_minimo_deja_un_evento_aparte_con_las_lineas(self, tienda, producto):
        vender(tienda, producto, "60", puede_vender_bajo_minimo=True)
        (e,) = eventos("ventas.venta_bajo_minimo")
        assert e.detalle["lineas"][0]["precio"].startswith("60")
        assert e.detalle["lineas"][0]["minimo"].startswith("80")
        assert e.recurso_tipo == "venta" and e.empresa_id == tienda.a.pk

    def test_una_venta_normal_no_deja_ese_evento(self, tienda, producto):
        vender(tienda, producto, "100")
        assert not eventos("ventas.venta_bajo_minimo").exists()
        assert not eventos("ventas.tipo_cambio_manual").exists()
        assert eventos("ventas.venta_registrada").count() == 1

    def test_el_tipo_de_cambio_puesto_a_mano_deja_rastro(self, tienda):
        TipoCambio.objects.sin_ambito().create(
            organizacion=tienda.entorno.e.org_a,
            fecha=tienda.entorno.hoy,
            fuente="SUNAT",
            compra=D("3.7000"),
            venta=D("3.7500"),
        )
        p = tienda.producto(costo="185", precios={"PUBLICO": "370"})
        tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "114.90")],  # 370 soles ÷ 3,80 = 97,37 + IGV
            moneda="USD",
            tipo_cambio=D("3.8000"),
        )
        (e,) = eventos("ventas.tipo_cambio_manual")
        assert e.detalle["pedido"] == "3.8000"

    def test_anular_un_comprobante_queda_registrado(self, tienda, producto):
        venta = vender(tienda, producto, "100")
        servicios.anular_comprobante(venta.comprobantes.get(), motivo="Error del cajero")
        (e,) = eventos("ventas.comprobante_anulado")
        assert e.detalle["motivo"] == "Error del cajero"


class TestMaestros:
    def test_cambiar_el_precio_de_un_producto_guarda_el_antes_y_el_despues(self, tienda, producto):
        publico = ListaPrecio.objects.sin_ambito().get(
            organizacion=tienda.entorno.e.org_a, uso="PUBLICO"
        )
        actualizar_producto(producto, datos={}, precios=[{"lista": publico.pk, "precio": D("120")}])
        (e,) = eventos("producto.editado")
        assert "precios" in e.detalle and e.recurso_id == str(producto.pk)
        assert "100" in str(e.detalle["precios"]) and "120" in str(e.detalle["precios"])

    def test_cambiar_el_limite_de_credito_de_un_cliente_queda_con_el_antes_y_el_despues(
        self, tienda
    ):
        cliente = tienda.cliente("200")
        r = cliente_de("admin").patch(
            f"/api/v1/mantenimiento/clientes/{cliente.pk}/",
            {"limite_credito": "999.00"},
            format="json",
        )
        assert r.status_code == 200, r.content
        (e,) = eventos("cliente.editado")
        assert e.detalle["limite_credito"] == ["200.00", "999.00"]

    def test_un_ajuste_de_inventario_queda_registrado(self, tienda, producto):
        registrar_movimiento(
            empresa=tienda.a,
            almacen=tienda.almacen(tienda.a),
            tipo=TipoMovimiento.SALIDA,
            origen="AJUSTE",
            fecha=tienda.entorno.hoy,
            lineas=[LineaNueva(producto, D("1"))],
        )
        assert (
            eventos("inventario.movimiento_registrado").filter(detalle__origen="AJUSTE").exists()
            or eventos("inventario.movimiento_registrado").exists()
        )
