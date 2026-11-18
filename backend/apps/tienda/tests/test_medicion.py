"""Posicionamiento y medición: códigos de Google/Meta en la configuración y feed de productos."""

# ruff: noqa: F811

import xml.etree.ElementTree as ET

import pytest
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_pedidos import contexto, vende  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/configuracion/"
PUBLICA = "/api/v1/tienda/configuracion"
FEED = "/api/v1/tienda/feed/google.xml"
G = "{http://base.google.com/ns/1.0}"


class TestCodigos:
    def test_se_guardan_y_salen_en_lo_publico(self, tienda):
        a = cliente_de("admin")
        r = a.patch(
            ADMIN,
            {
                "ga4_id": "G-ABC123XYZ9",
                "meta_pixel_id": "123456789012345",
                "google_verificacion": "abcDEF1234567890_-xyz",
                "seo_titulo_inicio": "Tecnología al mejor precio",
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        d = APIClient().get(PUBLICA).json()
        assert d["medicion"] == {"ga4": "G-ABC123XYZ9", "pixel": "123456789012345"}
        assert d["seo"] == {
            "titulo_inicio": "Tecnología al mejor precio",
            "google_verificacion": "abcDEF1234567890_-xyz",
        }

    def test_vacios_no_se_publican(self, tienda):
        d = APIClient().get(PUBLICA).json()
        assert d["medicion"] == {"ga4": None, "pixel": None}

    def test_se_validan_los_formatos(self, tienda):
        a = cliente_de("admin")
        for campo, malo in (
            ("ga4_id", "UA-123"),
            ("ga4_id", "<script>"),
            ("meta_pixel_id", "abc"),
            ("meta_pixel_id", "12"),
            ("google_verificacion", "a b"),
        ):
            assert a.patch(ADMIN, {campo: malo}, format="json").status_code == 400, (campo, malo)

    def test_solo_quien_configura_puede_cambiarlos(self, tienda):
        r = cliente_de("vendedor").patch(ADMIN, {"ga4_id": "G-ABC123XYZ9"}, format="json")
        assert r.status_code == 403


class TestFeed:
    def test_lista_los_productos_con_precio_y_foto(self, vende):
        contexto(vende)
        vende.publicar("Mouse & Teclado <Pro>", precio=100, stock=5)
        r = APIClient().get(FEED)
        assert r.status_code == 200 and r["Content-Type"].startswith("application/xml")
        raiz = ET.fromstring(r.content)  # noqa: S314 aunque el nombre traiga & y <
        items = raiz.findall("./channel/item")
        assert len(items) == 1
        item = items[0]
        assert item.find(f"{G}title").text == "Mouse & Teclado <Pro>"
        assert item.find(f"{G}price").text == "118.00 PEN"
        assert item.find(f"{G}availability").text == "in_stock"
        assert item.find(f"{G}condition").text == "new"
        assert "/producto/" in item.find(f"{G}link").text
        assert item.find(f"{G}image_link").text.startswith("http")

    def test_un_producto_agotado_sale_como_sin_stock(self, vende):
        from decimal import Decimal

        from apps.inventario.models import SaldoStock

        contexto(vende)
        p = vende.publicar("Cámara", precio=100, stock=5)
        SaldoStock.objects.sin_ambito().filter(producto=p).update(cantidad=Decimal("0"))
        item = ET.fromstring(APIClient().get(FEED).content).find(  # noqa: S314
            "./channel/item"
        )
        assert item.find(f"{G}availability").text == "out_of_stock"

    def test_nunca_lleva_costos_ni_stock_exacto(self, vende):
        contexto(vende)
        vende.publicar("Disco", precio=100, stock=7)
        texto = APIClient().get(FEED).content.decode()
        assert "costo" not in texto.lower() and "unidades" not in texto.lower()
