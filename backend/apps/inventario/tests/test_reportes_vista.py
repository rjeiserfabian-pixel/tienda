"""Vista previa en pantalla de los reportes: mismas cifras que el archivo, mismos permisos."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.inventario.tests.ayudas_api import BASE, cuerpo, registrar
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


def _rango():
    hoy = timezone.localdate()
    return {"desde": (hoy - timedelta(days=10)).isoformat(), "hasta": hoy.isoformat()}


def _vista(api, tipo, mundo, **extra):
    return api.get(f"{BASE}/reportes/{tipo}/vista/", {"empresa": mundo.e1.pk, **_rango(), **extra})


@pytest.fixture
def con_stock(mundo):
    producto = mundo.producto("Mouse")
    api = cliente_de("super")
    assert registrar(api, cuerpo(mundo, producto, cantidad="10", precio="20")).status_code == 201
    return api, producto


class TestVistaPrevia:
    def test_kardex_trae_filas_y_resumen(self, mundo, con_stock):
        api, producto = con_stock
        r = _vista(api, "kardex-valorizado", mundo, almacen=mundo.alm[1].pk, producto=producto.pk)
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["total_filas"] == 1 and not datos["recortado"]
        assert datos["filas"][0]["entrada"] == "10.000"
        resumen = {x["titulo"]: x["valor"] for x in datos["resumen"]}
        assert resumen["Entradas"] == "10.000" and resumen["Saldo final"] == "10.000"
        assert "Mouse" in datos["encabezado"]

    def test_kardex_exige_almacen_y_producto(self, mundo, con_stock):
        api, _ = con_stock
        assert _vista(api, "kardex-fisico", mundo).status_code == 400

    def test_saldos_suma_el_valor(self, mundo, con_stock):
        api, _ = con_stock
        r = api.get(f"{BASE}/reportes/saldos/vista/", {"empresa": mundo.e1.pk})
        datos = r.json()
        assert r.status_code == 200, r.content
        assert datos["filas"][0]["producto"] == "Mouse"
        assert {x["titulo"]: x["valor"] for x in datos["resumen"]}["Valor total"] == "200.00"

    def test_costo_de_venta_y_movimientos(self, mundo, con_stock):
        api, _ = con_stock
        assert _vista(api, "costo-venta", mundo).json()["total_filas"] == 1
        libro = _vista(api, "movimientos", mundo).json()
        assert (libro["total_filas"], libro["filas"][0]["productos"]) == (1, "1")

    def test_rango_invalido_se_explica(self, mundo, con_stock):
        api, _ = con_stock
        r = api.get(
            f"{BASE}/reportes/movimientos/vista/",
            {"empresa": mundo.e1.pk, "desde": "2026-10-10", "hasta": "2026-10-01"},
        )
        assert r.status_code == 400

    def test_tipo_desconocido_es_404(self, mundo, con_stock):
        api, _ = con_stock
        assert _vista(api, "inventado", mundo).status_code == 404

    def test_sin_permiso_de_exportar_se_rechaza(self, mundo, con_stock):
        assert _vista(cliente_de("vendedor"), "saldos", mundo).status_code == 403

    def test_el_contador_si_puede(self, mundo, con_stock):
        assert _vista(cliente_de("contador"), "movimientos", mundo).status_code == 200

    def test_otra_organizacion_no_ve_nada(self, mundo, con_stock):
        assert _vista(cliente_de("otra_org"), "movimientos", mundo).status_code in (400, 403, 404)
