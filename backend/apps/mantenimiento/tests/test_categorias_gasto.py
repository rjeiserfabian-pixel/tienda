"""Categorías de gasto: carga de fábrica, permisos y aislamiento por organización."""

import pytest

from apps.auditoria import servicios
from apps.mantenimiento.categorias_gasto import CATEGORIAS, sembrar_categorias_gasto
from apps.mantenimiento.models import CategoriaGasto
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento/categorias-gasto"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    sembrar_categorias_gasto(e.org_a.pk)
    sembrar_categorias_gasto(e.org_b.pk)
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


class TestSiembra:
    def test_carga_todas_las_de_fabrica(self, equipo):
        org = equipo["e"].org_a
        assert CategoriaGasto.objects.sin_ambito().filter(organizacion=org).count() == len(
            CATEGORIAS
        )

    def test_repetirla_no_duplica_ni_pisa_lo_editado(self, equipo):
        org = equipo["e"].org_a
        luz = CategoriaGasto.objects.sin_ambito().get(organizacion=org, codigo="SERVICIOS")
        luz.nombre = "Luz y agua"
        luz.save()
        assert sembrar_categorias_gasto(org.pk) == {"categorias_gasto": 0}
        luz.refresh_from_db()
        assert luz.nombre == "Luz y agua"

    def test_lo_que_se_elimino_no_vuelve(self, equipo):
        org = equipo["e"].org_a
        CategoriaGasto.objects.sin_ambito().get(organizacion=org, codigo="ALQUILER").delete()
        assert sembrar_categorias_gasto(org.pk) == {"categorias_gasto": 0}


class TestApi:
    def test_listado(self, equipo):
        r = cliente_de("cajero").get(f"{BASE}/", {"page_size": 100})
        assert r.status_code == 200
        assert r.json()["count"] == len(CATEGORIAS)

    def test_el_contador_crea_y_edita(self, equipo):
        api = cliente_de("contador")
        r = api.post(f"{BASE}/", {"nombre": "Seguridad y vigilancia"}, format="json")
        assert r.status_code == 201, r.content
        edit = api.patch(f"{BASE}/{r.json()['id']}/", {"nombre": "Vigilancia"}, format="json")
        assert (edit.status_code, edit.json()["nombre"]) == (200, "Vigilancia")

    def test_nombre_repetido(self, equipo):
        r = cliente_de("contador").post(f"{BASE}/", {"nombre": "alquiler"}, format="json")
        assert r.status_code in (400, 409)

    def test_permisos(self, equipo):
        assert (
            cliente_de("cajero").post(f"{BASE}/", {"nombre": "X"}, format="json").status_code == 403
        )
        assert cliente_de("vendedor").get(f"{BASE}/").status_code == 403
        assert cliente_de("contador").delete(f"{BASE}/1/").status_code in (403, 404)

    def test_otra_organizacion_no_ve_las_nuestras(self, equipo):
        propia = CategoriaGasto.objects.sin_ambito().get(
            organizacion=equipo["e"].org_a, codigo="ALQUILER"
        )
        assert cliente_de("otra_org").get(f"{BASE}/{propia.pk}/").status_code == 404
