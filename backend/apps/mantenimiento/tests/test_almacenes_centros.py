"""Almacenes (por empresa y sucursal) y centros de costo (de la organización, dos niveles)."""

import pytest

from apps.auditoria import servicios
from apps.mantenimiento.models import Almacen, CentroCosto
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    sucursales = {
        "a1": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre="Principal", codigo="001"
        ),
        "a2": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a2, nombre="Principal", codigo="001"
        ),
    }
    return {
        "e": e,
        "suc": sucursales,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "admin_a1": nuevo_usuario(e.org_a, "admin_a1", [e.emp_a1], [("ADMIN", e.emp_a1)]),
        "almacen": nuevo_usuario(e.org_a, "almacen", [e.emp_a1], [("ALMACENERO", e.emp_a1)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def almacen_json(equipo, empresa="a1", **extra):
    emp = equipo["e"].emp_a1 if empresa == "a1" else equipo["e"].emp_a2
    return {
        "empresa": emp.pk,
        "codigo": "alm-01",
        "nombre": "Almacén principal",
        "sucursal": equipo["suc"][empresa].pk,
        "tipo": "PRINCIPAL",
        **extra,
    }


def crear_personal(api, empresa, doc="71234567"):
    r = api.post(
        f"{BASE}/personal/",
        {
            "empresa": empresa.pk,
            "tipo_documento": "DNI",
            "numero_documento": doc,
            "nombres": "Luis",
            "apellidos": "Ramos",
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    return r.json()


def texto(respuesta) -> str:
    return str(respuesta.json()).lower()


# ---------------------------------------------------------------------------
# Almacenes
# ---------------------------------------------------------------------------
class TestAlmacenes:
    def test_alta_normaliza_el_codigo_y_queda_auditado(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        api = cliente_de("super")
        r = api.post(f"{BASE}/almacenes/", almacen_json(equipo), format="json")
        assert r.status_code == 201, r.content
        a = r.json()
        assert (a["codigo"], a["sucursal_nombre"], a["permite_venta"], a["estado"]) == (
            "ALM-01",
            "Principal",
            True,
            "ACTIVO",
        )
        assert AuditoriaEvento.objects.filter(accion="almacen.creado").exists()

    def test_codigo_y_nombre_no_se_repiten_en_la_empresa_pero_si_entre_empresas(self, equipo):
        api = cliente_de("super")
        assert (
            api.post(f"{BASE}/almacenes/", almacen_json(equipo), format="json").status_code == 201
        )
        por_codigo = api.post(
            f"{BASE}/almacenes/", almacen_json(equipo, nombre="Otro nombre"), format="json"
        )
        assert por_codigo.status_code == 400 and "codigo" in texto(por_codigo)
        por_nombre = api.post(
            f"{BASE}/almacenes/",
            almacen_json(equipo, codigo="ALM-02", nombre="ALMACÉN PRINCIPAL"),
            format="json",
        )
        assert por_nombre.status_code == 400 and "nombre" in texto(por_nombre)
        # La otra empresa puede usar los mismos.
        assert (
            api.post(f"{BASE}/almacenes/", almacen_json(equipo, "a2"), format="json").status_code
            == 201
        )

    def test_la_sucursal_y_el_responsable_deben_ser_de_la_misma_empresa(self, equipo):
        api = cliente_de("super")
        e = equipo["e"]
        de_otra = almacen_json(equipo, sucursal=equipo["suc"]["a2"].pk)  # sucursal de la empresa 2
        assert api.post(f"{BASE}/almacenes/", de_otra, format="json").status_code == 400
        persona_a2 = crear_personal(api, e.emp_a2)
        malo = almacen_json(equipo, responsable=persona_a2["id"])
        assert api.post(f"{BASE}/almacenes/", malo, format="json").status_code == 400
        persona_a1 = crear_personal(api, e.emp_a1, "71234568")
        ok = api.post(
            f"{BASE}/almacenes/", almacen_json(equipo, responsable=persona_a1["id"]), format="json"
        )
        assert ok.status_code == 201 and ok.json()["responsable_nombre"] == "Luis Ramos"

    def test_una_sucursal_inactiva_no_recibe_almacenes(self, equipo):
        Sucursal.objects.sin_ambito().filter(pk=equipo["suc"]["a1"].pk).update(estado="INACTIVO")
        r = cliente_de("super").post(f"{BASE}/almacenes/", almacen_json(equipo), format="json")
        assert r.status_code == 400 and "sucursal" in texto(r)

    def test_edicion_cambio_de_responsable_y_la_empresa_no_cambia(self, equipo):
        api = cliente_de("super")
        e = equipo["e"]
        creado = api.post(f"{BASE}/almacenes/", almacen_json(equipo), format="json").json()
        url = f"{BASE}/almacenes/{creado['id']}/"
        persona = crear_personal(api, e.emp_a1)
        r = api.patch(
            url,
            {"responsable": persona["id"], "tipo": "EXHIBICION", "permite_venta": False},
            format="json",
        )
        assert r.status_code == 200
        assert (r.json()["tipo"], r.json()["permite_venta"]) == ("EXHIBICION", False)
        assert api.patch(url, {"responsable": None}, format="json").json()["responsable"] is None
        assert api.patch(url, {"empresa": e.emp_a2.pk}, format="json").status_code == 400

    def test_alcance_por_empresa_y_permisos(self, equipo):
        e = equipo["e"]
        super_ = cliente_de("super")
        super_.post(f"{BASE}/almacenes/", almacen_json(equipo), format="json")
        super_.post(
            f"{BASE}/almacenes/", almacen_json(equipo, "a2", codigo="ALM-09"), format="json"
        )
        # El administrador de la empresa 1 solo ve y crea en la 1.
        admin = cliente_de("admin_a1")
        vistos = {a["empresa"] for a in admin.get(f"{BASE}/almacenes/").json()["results"]}
        assert vistos == {e.emp_a1.pk}
        ajeno = admin.post(
            f"{BASE}/almacenes/", almacen_json(equipo, "a2", codigo="X"), format="json"
        )
        assert ajeno.status_code == 403
        # El almacenero consulta pero no modifica; el vendedor ni entra.
        almacenero = cliente_de("almacen")
        assert almacenero.get(f"{BASE}/almacenes/").status_code == 200
        intento = almacenero.post(
            f"{BASE}/almacenes/", almacen_json(equipo, codigo="Z"), format="json"
        )
        assert intento.status_code == 403
        assert cliente_de("vendedor").get(f"{BASE}/almacenes/").status_code == 403

    def test_busqueda_filtro_baja_logica_y_aislamiento(self, equipo):
        api = cliente_de("super")
        a = api.post(f"{BASE}/almacenes/", almacen_json(equipo), format="json").json()
        api.post(
            f"{BASE}/almacenes/",
            almacen_json(
                equipo, codigo="MER-01", nombre="Averiados", tipo="MERMAS", permite_venta=False
            ),
            format="json",
        )
        assert api.get(f"{BASE}/almacenes/", {"q": "averia"}).json()["count"] == 1
        assert api.get(f"{BASE}/almacenes/", {"tipo": "MERMAS"}).json()["count"] == 1
        assert api.get(f"{BASE}/almacenes/", {"empresa": "x"}).status_code == 400
        assert api.delete(f"{BASE}/almacenes/{a['id']}/").status_code == 204
        assert Almacen.objects.sin_ambito(incluir_eliminados=True).filter(pk=a["id"]).exists()
        # El código vuelve a estar libre.
        assert (
            api.post(f"{BASE}/almacenes/", almacen_json(equipo), format="json").status_code == 201
        )
        assert cliente_de("otra_org").get(f"{BASE}/almacenes/").json()["count"] == 0


# ---------------------------------------------------------------------------
# Centros de costo
# ---------------------------------------------------------------------------
def crear_centro(api, codigo="CC-01", nombre="Administración", **extra):
    r = api.post(
        f"{BASE}/centros-costo/", {"codigo": codigo, "nombre": nombre, **extra}, format="json"
    )
    assert r.status_code == 201, r.content
    return r.json()


class TestCentrosCosto:
    def test_alta_codigo_normalizado_y_compartido_por_las_empresas(self, equipo):
        centro = crear_centro(cliente_de("super"), "cc 01")
        assert centro["codigo"] == "CC01"
        for usuario in ("super", "admin_a1"):  # cualquier empresa ve el mismo catálogo
            assert cliente_de(usuario).get(f"{BASE}/centros-costo/").json()["count"] == 1
        assert cliente_de("otra_org").get(f"{BASE}/centros-costo/").json()["count"] == 0

    def test_codigo_y_nombre_son_unicos(self, equipo):
        api = cliente_de("super")
        crear_centro(api)
        por_codigo = api.post(
            f"{BASE}/centros-costo/", {"codigo": "cc-01", "nombre": "Otro"}, format="json"
        )
        assert por_codigo.status_code == 400 and "codigo" in texto(por_codigo)
        por_nombre = api.post(
            f"{BASE}/centros-costo/", {"codigo": "CC-02", "nombre": "ADMINISTRACIÓN"}, format="json"
        )
        assert por_nombre.status_code == 400 and "nombre" in texto(por_nombre)

    def test_dos_niveles_grupo_y_centro(self, equipo):
        api = cliente_de("super")
        grupo = crear_centro(api, "CC-10", "Operaciones")
        hijo = crear_centro(api, "CC-11", "Servicio técnico", padre=grupo["id"])
        assert (hijo["padre"], hijo["padre_nombre"]) == (grupo["id"], "Operaciones")
        tercer_nivel = {"codigo": "CC-12", "nombre": "X", "padre": hijo["id"]}
        assert api.post(f"{BASE}/centros-costo/", tercer_nivel, format="json").status_code == 400
        url = f"{BASE}/centros-costo/{grupo['id']}/"
        assert api.patch(url, {"padre": grupo["id"]}, format="json").status_code == 400
        otro = crear_centro(api, "CC-20", "Comercial")
        # Un grupo con centros dentro no puede pasar a ser hijo.
        assert api.patch(url, {"padre": otro["id"]}, format="json").status_code == 400
        assert api.get(f"{BASE}/centros-costo/", {"padre": "ninguno"}).json()["count"] == 2
        assert api.get(f"{BASE}/centros-costo/", {"padre": grupo["id"]}).json()["count"] == 1
        assert api.get(f"{BASE}/centros-costo/", {"padre": "abc"}).status_code == 400
        lista = api.get(f"{BASE}/centros-costo/").json()["results"]
        assert {c["codigo"]: c["n_hijos"] for c in lista}["CC-10"] == 1

    def test_no_se_elimina_un_grupo_con_centros_dentro(self, equipo):
        api = cliente_de("super")
        grupo = crear_centro(api, "CC-10", "Operaciones")
        hijo = crear_centro(api, "CC-11", "Servicio técnico", padre=grupo["id"])
        r = api.delete(f"{BASE}/centros-costo/{grupo['id']}/")
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "centro_con_hijos")
        assert api.delete(f"{BASE}/centros-costo/{hijo['id']}/").status_code == 204
        assert api.delete(f"{BASE}/centros-costo/{grupo['id']}/").status_code == 204
        borrados = CentroCosto.objects.sin_ambito(incluir_eliminados=True)
        assert borrados.filter(pk=grupo["id"]).exists()

    def test_permisos(self, equipo):
        # El almacenero no tiene centros de costo; el vendedor tampoco puede crearlos.
        assert cliente_de("almacen").get(f"{BASE}/centros-costo/").status_code == 403
        intento = cliente_de("vendedor").post(
            f"{BASE}/centros-costo/", {"codigo": "A", "nombre": "B"}, format="json"
        )
        assert intento.status_code == 403
