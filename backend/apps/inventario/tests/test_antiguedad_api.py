"""Antigüedad del stock: reporte (vista y Excel), configuración, aviso en la venta e Inicio."""

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.auditoria import servicios
from apps.inventario import antiguedad
from apps.inventario.tests.ayudas_api import BASE, cuerpo, registrar
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture(autouse=True)
def _cache_limpia():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _ingreso(mundo, api, producto, cantidad, dias, empresa=1):
    fecha = (timezone.localdate() - timedelta(days=dias)).isoformat()
    r = registrar(api, cuerpo(mundo, producto, empresa=empresa, cantidad=cantidad, fecha=fecha))
    assert r.status_code == 201, r.content


@pytest.fixture
def con_stock(mundo):
    """Un mouse con 10 unidades de hace 120 días y 5 de hace 10, y un teclado reciente."""
    api = cliente_de("super")
    mouse, teclado = mundo.producto("Mouse"), mundo.producto("Teclado")
    _ingreso(mundo, api, mouse, "10", 120)
    _ingreso(mundo, api, mouse, "5", 10)
    _ingreso(mundo, api, teclado, "3", 5)
    return api, mouse, teclado


def _vista(api, mundo, **extra):
    return api.get(f"{BASE}/reportes/antiguedad/vista/", {"empresa": mundo.e1.pk, **extra})


class TestReporte:
    def test_la_vista_muestra_tramos_dias_y_valor_de_lo_antiguo(self, mundo, con_stock):
        api, mouse, _ = con_stock
        r = _vista(api, mundo)
        assert r.status_code == 200, r.content
        d = r.json()
        fila = next(f for f in d["filas"] if f["producto"] == "Mouse")
        assert (fila["stock"], fila["t1"], fila["t4"], fila["dias"]) == (
            "15.000",
            "5.000",
            "10.000",
            "120",
        )
        assert (
            fila["antiguas"] == "10.000" and fila["valor"] == "200.00" and fila["antiguo"] is True
        )
        assert d["filas"][0]["producto"] == "Mouse"  # lo más antiguo primero
        resumen = {x["titulo"]: x["valor"] for x in d["resumen"]}
        assert resumen["Con stock antiguo"] == "1" and resumen["Unidades antiguas"] == "10.000"
        assert "90 días" in d["encabezado"]

    def test_solo_antiguo_y_filtros(self, mundo, con_stock):
        api, mouse, teclado = con_stock
        assert [f["producto"] for f in _vista(api, mundo, solo_antiguo="true").json()["filas"]] == [
            "Mouse"
        ]
        assert (
            _vista(api, mundo, almacen=mundo.alm[2].pk).status_code == 400
        )  # almacén de otra empresa
        con_marca = _vista(api, mundo, categoria=mouse.categoria_id).json()
        assert con_marca["total_filas"] == 2  # ambos son de la misma categoría de prueba
        assert _vista(api, mundo, categoria=999999).json()["total_filas"] == 0

    def test_el_umbral_configurado_cambia_lo_que_es_antiguo(self, mundo, con_stock):
        api, _, _ = con_stock
        r = api.patch(
            f"{BASE}/antiguedad/configuracion/", {"empresa": mundo.e1.pk, "dias": 7}, format="json"
        )
        assert r.status_code == 200 and r.json()["dias"] == 7
        resumen = {x["titulo"]: x["valor"] for x in _vista(api, mundo).json()["resumen"]}
        # Con 7 días: los 10 mouse de hace 120 y los 5 de hace 10 pasan; el teclado (5 días) no.
        assert resumen["Con stock antiguo"] == "1"
        assert resumen["Unidades antiguas"] == "15.000"

    def test_excel_con_las_mismas_cifras_y_auditoria(self, mundo, con_stock):
        api, _, _ = con_stock
        r = api.get(f"{BASE}/reportes/antiguedad/", {"empresa": mundo.e1.pk, "formato": "xlsx"})
        assert r.status_code == 200, r.content
        hoja = load_workbook(io.BytesIO(r.content)).active
        textos = [[c.value for c in fila] for fila in hoja.iter_rows()]
        fila = next(f for f in textos if f and "Mouse" in [str(x) for x in f])
        assert 10 in [float(x) for x in fila if isinstance(x, int | float)] or "10" in str(fila)
        assert any("ANTIGÜEDAD" in str(x) for f in textos for x in f)

    def test_solo_excel_no_pdf(self, mundo, con_stock):
        api, _, _ = con_stock
        r = api.get(f"{BASE}/reportes/antiguedad/", {"empresa": mundo.e1.pk, "formato": "pdf"})
        assert r.status_code == 400

    def test_permisos(self, mundo, con_stock):
        assert _vista(cliente_de("vendedor"), mundo).status_code == 403
        assert _vista(APIClient(), mundo).status_code == 401


class TestConfiguracion:
    URL = f"{BASE}/antiguedad/configuracion/"

    def test_se_lee_con_ver_y_se_cambia_con_el_permiso(self, mundo):
        assert cliente_de("almacenero").get(self.URL, {"empresa": mundo.e1.pk}).json()["dias"] == 90
        r = cliente_de("almacenero").patch(
            self.URL, {"empresa": mundo.e1.pk, "dias": 30}, format="json"
        )
        assert r.status_code == 403  # el almacenero no configura
        admin = cliente_de("admin")
        assert (
            admin.patch(self.URL, {"empresa": mundo.e1.pk, "dias": 30}, format="json").status_code
            == 200
        )
        assert admin.get(self.URL, {"empresa": mundo.e1.pk}).json()["dias"] == 30

    @pytest.mark.parametrize("dias", [0, -1, 4000, "x"])
    def test_rechaza_valores_invalidos(self, mundo, dias):
        r = cliente_de("admin").patch(
            self.URL, {"empresa": mundo.e1.pk, "dias": dias}, format="json"
        )
        assert r.status_code == 400

    def test_otra_empresa_no_se_toca(self, mundo):
        r = cliente_de("admin").patch(self.URL, {"empresa": mundo.e2.pk, "dias": 30}, format="json")
        assert r.status_code == 403  # el admin solo está asignado a la empresa A1


class TestAvisoDeVenta:
    URL = f"{BASE}/antiguedad/venta/"

    def _items(self, mundo, *productos):
        return ",".join(f"{mundo.e1.pk}:{mundo.alm[1].pk}:{p.pk}" for p in productos)

    def test_solo_avisa_de_lo_que_pasa_el_umbral_y_sin_costos(self, mundo, con_stock):
        _, mouse, teclado = con_stock
        r = cliente_de("vendedor").get(self.URL, {"items": self._items(mundo, mouse, teclado)})
        assert r.status_code == 200, r.content
        datos = r.json()
        assert [a["producto"] for a in datos] == [mouse.pk]
        assert datos[0]["dias"] == 120 and datos[0]["unidades_antiguas"] == "10.000"
        assert datos[0]["ingreso"] == (timezone.localdate() - timedelta(days=120)).isoformat()
        assert not {"costo", "valor", "costo_unitario"} & set(datos[0])

    def test_pide_permiso_de_vender_en_cada_empresa(self, mundo, con_stock):
        _, mouse, _ = con_stock
        item_otra_empresa = f"{mundo.e2.pk}:{mundo.alm[2].pk}:{mouse.pk}"
        assert cliente_de("vendedor").get(self.URL, {"items": item_otra_empresa}).status_code == 403
        assert (
            cliente_de("contador").get(self.URL, {"items": self._items(mundo, mouse)}).status_code
            == 403
        )
        assert APIClient().get(self.URL, {"items": self._items(mundo, mouse)}).status_code == 401

    @pytest.mark.parametrize("items", ["abc", "1:2", "0:1:1", "1:2:3:4"])
    def test_valida_lo_que_llega(self, mundo, items):
        assert cliente_de("vendedor").get(self.URL, {"items": items}).status_code == 400

    def test_tope_de_productos_por_consulta(self, mundo):
        items = ",".join(f"{mundo.e1.pk}:{mundo.alm[1].pk}:{i}" for i in range(1, 60))
        assert cliente_de("vendedor").get(self.URL, {"items": items}).status_code == 400

    def test_sin_items_responde_vacio(self, mundo):
        assert cliente_de("vendedor").get(self.URL).json() == []


class TestInicio:
    def test_el_resumen_cuenta_lo_antiguo_y_se_guarda_un_rato(self, mundo, con_stock):
        resumen = antiguedad.resumen_de_empresa(mundo.e1.pk)
        assert resumen["productos"] == 1 and resumen["unidades"] == 10
        assert str(resumen["valor_costo_soles"]) == "200.00" and resumen["umbral_dias"] == 90

    def test_aparece_en_el_bloque_de_inventario_del_inicio(self, mundo, con_stock):
        api, _, _ = con_stock
        r = api.get("/api/v1/panel/inicio/", {"empresa": mundo.e1.pk})
        assert r.status_code == 200, r.content
        bloque = r.json()["bloques"]["inventario"]
        assert bloque["stock_antiguo"]["productos"] == 1
