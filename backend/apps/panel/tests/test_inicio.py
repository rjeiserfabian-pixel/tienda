"""Panel de Inicio: cada bloque sale solo con su permiso y los datos son de la empresa pedida."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

URL = "/api/v1/panel/inicio/"


@pytest.fixture(autouse=True)
def _sin_cache():
    cache.clear()
    yield
    cache.clear()


class TestAcceso:
    def test_sin_sesion_no_entra(self, escena):
        r = APIClient().get(URL, {"empresa": escena.empresa.pk})
        assert r.status_code == 401

    def test_pide_la_empresa(self, escena):
        r = cliente_de("admin").get(URL)
        assert r.status_code == 400

    def test_una_empresa_que_no_existe_se_rechaza(self, escena):
        r = cliente_de("admin").get(URL, {"empresa": 99999999})
        assert r.status_code == 403

    def test_no_se_cachea_en_el_navegador(self, escena):
        r = cliente_de("admin").get(URL, {"empresa": escena.empresa.pk})
        assert r.status_code == 200, r.content
        assert r["Cache-Control"] == "no-store"


class TestBloques:
    def test_el_administrador_ve_todos_los_bloques_sin_errores(self, escena):
        r = cliente_de("admin").get(URL, {"empresa": escena.empresa.pk})
        assert r.status_code == 200, r.content
        bloques = r.json()["bloques"]
        assert {
            "ventas",
            "por_cobrar",
            "compras",
            "gastos",
            "inventario",
            "caja",
            "servicio",
        } <= set(bloques)
        assert not [n for n, b in bloques.items() if b.get("error")]

    def test_un_vendedor_no_ve_compras_ni_gastos(self, escena):
        bloques = cliente_de("vendedor").get(URL, {"empresa": escena.empresa.pk}).json()["bloques"]
        assert "gastos" not in bloques
        assert "compras" not in bloques

    def test_sin_datos_todo_viene_en_cero_y_sin_mezclar_monedas(self, escena):
        d = cliente_de("admin").get(URL, {"empresa": escena.empresa.pk}).json()["bloques"]
        assert d["ventas"]["hoy"] == [] and d["ventas"]["mes"] == []
        assert d["compras"]["por_pagar"] == []
        assert d["inventario"]["unidades"] == "0.00"
        assert d["servicio"]["abiertas"] == 0

    def test_el_resultado_se_guarda_un_minuto_por_usuario(self, escena):
        c = cliente_de("admin")
        primero = c.get(URL, {"empresa": escena.empresa.pk}).json()
        segundo = c.get(URL, {"empresa": escena.empresa.pk}).json()
        assert primero == segundo


class TestConDatos:
    def test_una_compra_se_ve_en_compras_e_inventario(self, escena):
        escena.compras.comprar()  # 10 unidades a 10,00 + IGV = 118,00 al contado
        cache.clear()
        d = cliente_de("admin").get(URL, {"empresa": escena.empresa.pk}).json()["bloques"]
        assert d["compras"]["mes"] == [{"moneda": "PEN", "total": "118.00", "cantidad": 1}]
        assert d["compras"]["por_pagar"] == []  # fue al contado: no se debe nada
        assert d["inventario"]["unidades"] == "10.00"
        assert d["inventario"]["productos_con_stock"] == 1
        assert d["inventario"]["productos_agotados"] == 0

    def test_la_otra_empresa_no_ve_lo_de_esta(self, escena):
        escena.compras.comprar()
        cache.clear()
        d = cliente_de("admin").get(URL, {"empresa": escena.otra.pk}).json()["bloques"]
        assert d["compras"]["mes"] == []
        assert d["inventario"]["unidades"] == "0.00"
