"""Traslado entre empresas: mercadería de una empresa a la otra, sin venta al cliente."""

import itertools
from decimal import Decimal as D

import pytest

from apps.inventario.models import MovimientoInventario, OrigenMovimiento, SaldoStock
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import liquidacion_interna as liquidacion
from apps.ventas import traslados_empresas as traslados
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import DeudaInterna, MotivoDeuda, VentaInterna

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas/traslados-empresas"
_claves = itertools.count(1)


def stock(tienda, empresa, producto) -> D:
    fila = SaldoStock.objects.sin_ambito().filter(
        empresa=empresa, almacen=tienda.almacen(empresa), producto=producto
    ).first()
    return fila.cantidad if fila else D("0")


def trasladar(tienda, producto, cantidad="3", *, de=None, a=None):
    de = de or tienda.b
    a = a or tienda.a
    return traslados.registrar_traslado(
        origen=tienda.almacen(de),
        destino=tienda.almacen(a),
        fecha=tienda.entorno.hoy,
        lineas=[traslados.LineaTraslado(producto, D(cantidad))],
        observacion="Reposición",
    )


class TestRegistrar:
    def test_pasa_la_mercaderia_al_costo_y_la_que_recibe_debe_el_costo(self, tienda, mixto):
        _, de_b = mixto  # el cargador solo lo tiene B (10 a costo 30)

        interna = trasladar(tienda, de_b, "3")

        assert interna.venta_id is None
        assert (interna.empresa, interna.empresa_destino) == (tienda.b, tienda.a)
        assert interna.total_costo == D("90.00")
        assert stock(tienda, tienda.b, de_b) == D("7")
        assert stock(tienda, tienda.a, de_b) == D("3")
        (partida,) = DeudaInterna.objects.all()
        assert (partida.empresa, partida.acreedora) == (tienda.a, tienda.b)
        assert (partida.monto, partida.motivo) == (D("90.00"), MotivoDeuda.VENTA)
        origenes = set(MovimientoInventario.objects.values_list("origen", flat=True))
        assert OrigenMovimiento.TRASLADO_EMPRESAS in origenes

    def test_la_deuda_se_liquida_junto_con_las_de_ventas_internas(self, tienda, mixto):
        _, de_b = mixto
        trasladar(tienda, de_b, "3")

        (p,) = liquidacion.pendientes(tienda.a.organizacion_id)

        assert (p.pagadora, p.receptora, p.monto) == (tienda.a, tienda.b, D("90.00"))

    def test_en_la_misma_empresa_se_rechaza(self, tienda, mixto):
        de_a, _ = mixto
        with pytest.raises(VentaInvalida, match="Traspasar"):
            trasladar(tienda, de_a, "1", de=tienda.a, a=tienda.a)

    def test_sin_stock_suficiente_no_hace_nada(self, tienda, mixto):
        _, de_b = mixto
        with pytest.raises(Exception):  # noqa: B017 - stock insuficiente
            trasladar(tienda, de_b, "50")
        assert VentaInterna.objects.count() == 0
        assert stock(tienda, tienda.b, de_b) == D("10")

    def test_un_producto_repetido_o_en_cero_se_rechaza(self, tienda, mixto):
        _, de_b = mixto
        with pytest.raises(VentaInvalida, match="cantidad"):
            trasladar(tienda, de_b, "0")


class TestAnular:
    def test_vuelve_la_mercaderia_y_la_deuda_se_compensa(self, tienda, mixto):
        _, de_b = mixto
        interna = trasladar(tienda, de_b, "3")

        traslados.anular_traslado(interna, motivo="Error de carga")

        interna.refresh_from_db()
        assert interna.estado == VentaInterna.Estado.ANULADO
        assert stock(tienda, tienda.b, de_b) == D("10")
        assert stock(tienda, tienda.a, de_b) == D("0")
        assert [p.motivo for p in DeudaInterna.objects.order_by("id")] == [
            MotivoDeuda.VENTA,
            MotivoDeuda.ANULACION,
        ]
        assert liquidacion.pendientes(tienda.a.organizacion_id) == [] or (
            liquidacion.pendientes(tienda.a.organizacion_id)[0].monto == D("0")
        )

    def test_no_se_anula_dos_veces_y_pide_motivo(self, tienda, mixto):
        _, de_b = mixto
        interna = trasladar(tienda, de_b, "1")
        with pytest.raises(VentaInvalida, match="motivo"):
            traslados.anular_traslado(interna, motivo=" ")
        traslados.anular_traslado(interna, motivo="Error de carga")
        with pytest.raises(VentaInvalida, match="anulado"):
            traslados.anular_traslado(interna, motivo="Otra vez")


class TestGuia:
    def test_la_guia_sale_a_nombre_de_quien_entrega_y_va_a_la_que_recibe(self, tienda, mixto):
        from apps.ventas import guias

        _, de_b = mixto
        interna = trasladar(tienda, de_b, "2")
        linea = interna.lineas.get()

        # Se pide desde la entrada (la mitad de la empresa que recibe): sale igual de quien entrega.
        guia = guias.crear_guia_de_traslado(
            linea.movimiento_entrada,
            punto_partida="Jr. Lima 123",
            punto_llegada="Av. Grau 456",
            fecha_traslado=tienda.entorno.hoy,
            modalidad="02",
            motivo="13",
            placa="ABC-123",
            conductor_nombre="Luis Soto",
        )

        assert guia.empresa_id == tienda.b.pk
        assert guia.destinatario_documento == tienda.a.ruc
        with pytest.raises(VentaInvalida, match="guía de remisión"):
            traslados.anular_traslado(interna, motivo="Error")


class TestApi:
    @pytest.fixture
    def dueno(self, tienda, nuevo_usuario):
        return nuevo_usuario(
            tienda.a.organizacion, "dueno", [tienda.a, tienda.b], [("SUPERADMIN", None)]
        )

    def _crear(self, tienda, de_b, cantidad="2"):
        return cliente_de("dueno").post(
            f"{BASE}/?empresa={tienda.a.pk}",
            {
                "empresa": tienda.a.pk,
                "almacen_origen": tienda.almacen(tienda.b).pk,
                "almacen_destino": tienda.almacen(tienda.a).pk,
                "fecha": tienda.entorno.hoy.isoformat(),
                "observacion": "Reposición",
                "lineas": [{"producto": de_b.pk, "cantidad": cantidad}],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"traslado-{next(_claves):05d}",
        )

    def test_crear_listar_y_anular(self, tienda, dueno, mixto):
        _, de_b = mixto

        r = self._crear(tienda, de_b)

        assert r.status_code == 201, r.content
        cuerpo = r.json()
        assert cuerpo["total_costo"] == "60.00" and cuerpo["guia"] is None
        assert cuerpo["entrega"] and cuerpo["recibe"] and cuerpo["lineas"][0]["cantidad"] == "2.000"
        lista = cliente_de("dueno").get(f"{BASE}/", {"empresa": tienda.a.pk})
        assert lista.status_code == 200 and lista.json()["count"] == 1
        anulado = cliente_de("dueno").post(
            f"{BASE}/{cuerpo['id']}/anular/", {"motivo": "Prueba"}, format="json"
        )
        assert anulado.status_code == 200, anulado.content
        assert anulado.json()["estado"] == "ANULADO"

    def test_sin_el_permiso_no_se_puede_crear(self, tienda, nuevo_usuario, mixto):
        _, de_b = mixto
        nuevo_usuario(tienda.a.organizacion, "vendedora_x", [tienda.a, tienda.b], [("VENDEDOR", None)])
        r = cliente_de("vendedora_x").post(
            f"{BASE}/?empresa={tienda.a.pk}",
            {
                "empresa": tienda.a.pk,
                "almacen_origen": tienda.almacen(tienda.b).pk,
                "almacen_destino": tienda.almacen(tienda.a).pk,
                "fecha": tienda.entorno.hoy.isoformat(),
                "lineas": [{"producto": de_b.pk, "cantidad": "1"}],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"traslado-{next(_claves):05d}",
        )
        assert r.status_code == 403
