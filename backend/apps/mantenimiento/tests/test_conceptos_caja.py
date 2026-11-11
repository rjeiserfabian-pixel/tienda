"""Conceptos de caja: carga de fábrica, permisos y protección de los que usa el sistema."""

import pytest

from apps.auditoria import servicios
from apps.mantenimiento.conceptos_caja import CONCEPTOS, sembrar_conceptos_caja
from apps.mantenimiento.models import ConceptoCaja
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento/conceptos-caja"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    sembrar_conceptos_caja(e.org_a.pk)
    sembrar_conceptos_caja(e.org_b.pk)
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def por_codigo(org, codigo):
    return ConceptoCaja.objects.sin_ambito().get(organizacion=org, codigo=codigo)


class TestSiembra:
    def test_carga_todos_los_de_fabrica(self, equipo):
        assert ConceptoCaja.objects.sin_ambito().filter(
            organizacion=equipo["e"].org_a
        ).count() == len(CONCEPTOS)

    def test_repetirla_no_duplica_ni_pisa_lo_editado(self, equipo):
        org = equipo["e"].org_a
        gastos = por_codigo(org, "GASTOS_VARIOS")
        gastos.nombre = "Gastos de la tienda"
        gastos.save()
        assert sembrar_conceptos_caja(org.pk) == {"conceptos_caja": 0}
        assert por_codigo(org, "GASTOS_VARIOS").nombre == "Gastos de la tienda"

    def test_lo_que_se_elimino_no_vuelve(self, equipo):
        org = equipo["e"].org_a
        por_codigo(org, "INTERESES").delete()
        assert sembrar_conceptos_caja(org.pk) == {"conceptos_caja": 0}
        assert (
            not ConceptoCaja.objects.sin_ambito()
            .filter(organizacion=org, codigo="INTERESES")
            .exists()
        )

    def test_un_concepto_propio_con_el_mismo_nombre_pasa_a_ser_del_sistema(self, rbac):
        ConceptoCaja.objects.sin_ambito().create(
            organizacion=rbac.org_a, nombre="Pago a proveedor", tipo="EGRESO"
        )
        sembrar_conceptos_caja(rbac.org_a.pk)
        propio = ConceptoCaja.objects.sin_ambito().get(
            organizacion=rbac.org_a, nombre="Pago a proveedor"
        )
        assert (propio.codigo, propio.automatico) == ("PAGO_PROVEEDOR", True)


class TestApi:
    def test_listado_y_filtro_de_los_que_se_usan_a_mano(self, equipo):
        api = cliente_de("contador")
        todos = api.get(f"{BASE}/", {"page_size": 100}).json()
        manuales = api.get(f"{BASE}/", {"manual": "1", "page_size": 100}).json()
        assert todos["count"] == len(CONCEPTOS)
        assert manuales["count"] == len([c for c in CONCEPTOS if not c[3]])
        assert all(not c["automatico"] for c in manuales["results"])
        egresos = api.get(f"{BASE}/", {"tipo": "INGRESO", "page_size": 100}).json()
        assert all(c["tipo"] == "INGRESO" for c in egresos["results"])

    def test_el_contador_crea_y_edita_su_propio_concepto(self, equipo):
        api = cliente_de("contador")
        r = api.post(f"{BASE}/", {"nombre": "Propinas", "tipo": "INGRESO"}, format="json")
        assert r.status_code == 201, r.content
        assert (r.json()["automatico"], r.json()["tipo_nombre"]) == (False, "Ingreso")
        edit = api.patch(f"{BASE}/{r.json()['id']}/", {"nombre": "Propinas del mes"}, format="json")
        assert edit.status_code == 200
        assert edit.json()["nombre"] == "Propinas del mes"

    def test_nombre_repetido_en_el_mismo_tipo(self, equipo):
        api = cliente_de("contador")
        assert api.post(
            f"{BASE}/", {"nombre": "Aporte de capital", "tipo": "INGRESO"}, format="json"
        ).status_code in (400, 409)
        # El mismo nombre en el otro tipo sí se puede.
        assert (
            api.post(
                f"{BASE}/", {"nombre": "Aporte de capital", "tipo": "EGRESO"}, format="json"
            ).status_code
            == 201
        )

    def test_los_del_sistema_no_se_borran_ni_se_desactivan_ni_cambian_de_tipo(self, equipo):
        org = equipo["e"].org_a
        pago = por_codigo(org, "PAGO_PROVEEDOR")
        api = cliente_de("super")
        assert api.delete(f"{BASE}/{pago.pk}/").status_code == 400
        assert (
            api.patch(f"{BASE}/{pago.pk}/", {"estado": "INACTIVO"}, format="json").status_code
            == 400
        )
        assert (
            api.patch(f"{BASE}/{pago.pk}/", {"tipo": "INGRESO"}, format="json").status_code == 400
        )
        assert (
            api.patch(
                f"{BASE}/{pago.pk}/", {"nombre": "Pagos a proveedores"}, format="json"
            ).status_code
            == 200
        )

    def test_uno_de_fabrica_que_no_usa_el_sistema_si_se_elimina(self, equipo):
        concepto = por_codigo(equipo["e"].org_a, "INTERESES")
        assert cliente_de("super").delete(f"{BASE}/{concepto.pk}/").status_code == 204

    def test_el_tipo_no_cambia(self, equipo):
        concepto = por_codigo(equipo["e"].org_a, "GASTOS_VARIOS")
        r = cliente_de("super").patch(f"{BASE}/{concepto.pk}/", {"tipo": "INGRESO"}, format="json")
        assert r.status_code == 400

    def test_permisos_y_aislamiento(self, equipo):
        assert cliente_de("cajero").get(f"{BASE}/").status_code == 200
        assert (
            cliente_de("cajero")
            .post(f"{BASE}/", {"nombre": "X", "tipo": "INGRESO"}, format="json")
            .status_code
            == 403
        )
        assert (
            cliente_de("contador")
            .delete(f"{BASE}/{por_codigo(equipo['e'].org_a, 'INTERESES').pk}/")
            .status_code
            == 403
        )
        otra = cliente_de("otra_org").get(f"{BASE}/", {"page_size": 100}).json()
        assert otra["count"] == len(CONCEPTOS)
        ids_a = set(
            ConceptoCaja.objects.sin_ambito()
            .filter(organizacion=equipo["e"].org_a)
            .values_list("id", flat=True)
        )
        assert not ({c["id"] for c in otra["results"]} & ids_a)
