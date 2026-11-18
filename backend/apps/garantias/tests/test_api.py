"""API de consulta de garantías: búsqueda, situación, detalle con historial y permisos."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.garantias.models import Garantia
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/garantias/"


def _vender(tienda, producto, cantidad=1, total="118.00", **extra):
    return tienda.vender(
        [tienda.linea(producto, cantidad, **extra)],
        [tienda.cobro(tienda.efectivo, total)],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
    )


def _celular(tienda, *series):
    p = tienda.producto(
        "Celular",
        costo="500",
        precios={"PUBLICO": "800"},
        stock={},
        lleva_serie=True,
        garantia_meses=12,
    )
    registrar_movimiento(
        empresa=tienda.a,
        almacen=tienda.almacen(tienda.a),
        tipo=TipoMovimiento.ENTRADA,
        origen="COMPRA",
        fecha=tienda.entorno.hoy,
        lineas=[LineaNueva(p, D(len(series)), D("500"), series=tuple(series))],
    )
    return p


def _lista(usuario, **params):
    r = cliente_de(usuario).get(BASE, params)
    assert r.status_code == 200, r.content
    return r.json()["results"]


class TestBusqueda:
    def test_busca_por_serie_comprobante_cliente_y_producto(self, tienda):
        p = _celular(tienda, "IMEI-1", "IMEI-2")
        v = tienda.vender(
            [tienda.linea(p, 2, series=("IMEI-1", "IMEI-2"))],
            [tienda.cobro(tienda.efectivo, "1888.00")],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
        )
        numero = v.comprobantes.get().numero_completo
        assert len(_lista("vendedor")) == 2
        assert [g["numero_serie"] for g in _lista("vendedor", q="imei-2")] == ["IMEI-2"]
        assert len(_lista("vendedor", q=numero)) == 2
        assert len(_lista("vendedor", q="20100000017")) == 2
        assert len(_lista("vendedor", q="Celular")) == 2
        assert _lista("vendedor", q="NOEXISTE") == []

    def test_dice_la_situacion_de_cada_garantia(self, tienda):
        _vender(tienda, tienda.producto(garantia_meses=12))
        (g,) = _lista("vendedor")
        assert (g["situacion"], g["vigente"]) == ("VIGENTE", True)
        Garantia.objects.sin_ambito().update(
            vence_el=Garantia.objects.sin_ambito().get().fecha_inicio + timedelta(days=1)
        )
        # La fecha de la venta es hoy: vence mañana = por vencer.
        assert _lista("vendedor", situacion="POR_VENCER")[0]["dias_restantes"] <= 30
        assert _lista("vendedor", situacion="VENCIDA") == []
        Garantia.objects.sin_ambito().update(
            fecha_inicio=tienda.entorno.hoy - timedelta(days=400),
            vence_el=tienda.entorno.hoy - timedelta(days=10),
        )
        assert [g["situacion"] for g in _lista("vendedor", situacion="VENCIDA")] == ["VENCIDA"]


class TestDetalle:
    def test_trae_el_historial_de_la_unidad(self, tienda):
        p = _celular(tienda, "IMEI-9")
        tienda.vender(
            [tienda.linea(p, 1, series=("IMEI-9",))],
            [tienda.cobro(tienda.efectivo, "944.00")],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
        )
        g = Garantia.objects.sin_ambito().get()
        r = cliente_de("vendedor").get(f"{BASE}{g.pk}/")
        assert r.status_code == 200, r.content
        eventos = [e["evento"] for e in r.json()["historial"]]
        assert any(e.startswith("Entró al almacén") for e in eventos)
        assert any(e.startswith("Salió del almacén") for e in eventos)
        assert any(e.startswith("Vendido en") for e in eventos)


class TestPermisos:
    def test_el_contador_puede_consultar_porque_ve_ventas(self, tienda):
        assert cliente_de("contador").get(BASE).status_code == 200

    def test_exige_sesion(self, tienda):
        from rest_framework.test import APIClient

        assert APIClient().get(BASE).status_code in (401, 403)
