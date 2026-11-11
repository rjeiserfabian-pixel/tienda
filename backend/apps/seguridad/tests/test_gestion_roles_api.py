"""Panel de roles: listado, alta, edición, borrado y matriz de permisos."""

import pytest

from apps.seguridad.models import Rol
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad/roles/"


@pytest.fixture
def panel(nuevo_usuario, rbac):
    e = rbac
    return {
        "e": e,
        "superadmin": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "admin": nuevo_usuario(e.org_a, "admin", [e.emp_a1, e.emp_a2], [("ADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otro_b": nuevo_usuario(e.org_b, "otro_b", [e.emp_b1], [("ADMIN", None)]),
    }


def error(respuesta):
    return respuesta.json()["error"]["codigo"]


def crear(api, **extra):
    datos = {"codigo": "SUPERVISOR", "nombre": "Supervisor", **extra}
    return api.post(BASE, datos, format="json")


def rol_de(organizacion, codigo):
    return Rol.objects.sin_ambito().get(organizacion=organizacion, codigo=codigo)


def test_listado_con_conteos(panel):
    api = cliente_de("admin")
    r = api.get(BASE)
    assert r.status_code == 200
    por_codigo = {f["codigo"]: f for f in r.json()["results"]}
    assert {"SUPERADMIN", "ADMIN", "VENDEDOR", "CAJERO"} <= set(por_codigo)
    assert por_codigo["VENDEDOR"]["n_usuarios"] == 1
    assert por_codigo["SUPERADMIN"]["es_sistema"] is True
    assert por_codigo["VENDEDOR"]["n_permisos"] > 0


def test_ver_roles_requiere_permiso(panel):
    assert cliente_de("vendedor").get(BASE).status_code == 403


def test_el_detalle_trae_la_matriz(panel):
    api, e = cliente_de("admin"), panel["e"]
    r = api.get(f"{BASE}{rol_de(e.org_a, 'VENDEDOR').pk}/")
    assert r.status_code == 200
    assert r.json()["permisos"]["VENTAS.VENDER"] == "EMPRESA"
    assert api.get(f"{BASE}{rol_de(e.org_a, 'VENDEDOR').pk}/permisos/").json()["permisos"]


def test_alta_de_rol_con_permisos_y_codigo_repetido(panel):
    api = cliente_de("admin")
    r = crear(api, permisos={"VENTAS.VER": "EMPRESA"})
    assert r.status_code == 201, r.content
    assert r.json()["permisos"] == {"VENTAS.VER": "EMPRESA"}
    r = crear(api)
    assert r.status_code == 400  # código repetido: error de validación, no un 500
    assert crear(api, codigo="mal codigo").status_code == 400
    assert crear(api, codigo="OTRO", permisos={"NO.EXISTE": "EMPRESA"}).status_code == 400
    assert crear(api, codigo="OTRO2", permisos={"VENTAS.VER": "GALAXIA"}).status_code == 400


def test_sin_permiso_no_se_crean_roles(panel):
    assert crear(cliente_de("vendedor")).status_code == 403


def test_edicion_y_borrado(panel):
    api = cliente_de("admin")
    rol_id = crear(api).json()["id"]
    r = api.patch(f"{BASE}{rol_id}/", {"nombre": "Jefe de turno"}, format="json")
    assert r.status_code == 200
    assert r.json()["nombre"] == "Jefe de turno"
    assert api.delete(f"{BASE}{rol_id}/").status_code == 204
    assert api.get(f"{BASE}{rol_id}/").status_code == 404
    assert crear(api).status_code == 201  # el código vuelve a estar libre


def test_un_rol_con_usuarios_no_se_borra(panel):
    api, e = cliente_de("admin"), panel["e"]
    r = api.delete(f"{BASE}{rol_de(e.org_a, 'VENDEDOR').pk}/")
    assert (r.status_code, error(r)) == (409, "rol_en_uso")


def test_los_roles_de_sistema_son_intocables(panel):
    api, e = cliente_de("super"), panel["e"]
    superadmin = rol_de(e.org_a, "SUPERADMIN").pk
    r = api.patch(f"{BASE}{superadmin}/", {"nombre": "Otro"}, format="json")
    assert (r.status_code, error(r)) == (409, "rol_de_sistema_intocable")
    r = api.put(f"{BASE}{superadmin}/permisos/", {"permisos": {}}, format="json")
    assert (r.status_code, error(r)) == (409, "rol_de_sistema_intocable")
    assert error(api.delete(f"{BASE}{superadmin}/")) == "rol_de_sistema_intocable"


def test_reemplazar_la_matriz(panel):
    api = cliente_de("admin")
    rol_id = crear(api, permisos={"VENTAS.VER": "EMPRESA", "VENTAS.VENDER": "PROPIO"}).json()["id"]
    r = api.put(
        f"{BASE}{rol_id}/permisos/",
        {"permisos": {"VENTAS.VER": "ORGANIZACION", "MANTENIMIENTO.CLIENTES.VER": "EMPRESA"}},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.json()["permisos"] == {
        "VENTAS.VER": "ORGANIZACION",
        "MANTENIMIENTO.CLIENTES.VER": "EMPRESA",
    }
    assert r.json()["n_permisos"] == 2


def test_no_se_otorga_en_un_rol_lo_que_no_se_posee(panel, nuevo_usuario):
    e = panel["e"]
    admin = cliente_de("admin")
    gestor_rol = crear(
        admin,
        codigo="GESTOR_ROLES",
        permisos={"SEGURIDAD.ROLES.VER": "EMPRESA", "SEGURIDAD.ROLES.GESTIONAR": "EMPRESA"},
    ).json()["id"]
    gestor = nuevo_usuario(e.org_a, "gestor", [e.emp_a1, e.emp_a2])
    r = admin.post(
        f"/api/v1/seguridad/usuarios/{gestor.pk}/roles/",
        {"rol": gestor_rol, "empresa": None},
        format="json",
    )
    assert r.status_code == 201, r.content

    api = cliente_de("gestor")
    objetivo = crear(admin, codigo="OBJETIVO").json()["id"]
    r = api.put(
        f"{BASE}{objetivo}/permisos/", {"permisos": {"VENTAS.VENDER": "EMPRESA"}}, format="json"
    )
    assert (r.status_code, error(r)) == (403, "escalada_de_privilegios")
    assert api.get(f"{BASE}{objetivo}/permisos/").json()["permisos"] == {}


def test_los_roles_de_otra_organizacion_no_son_visibles(panel):
    e = panel["e"]
    api = cliente_de("otro_b")
    codigos = {f["codigo"] for f in api.get(BASE).json()["results"]}
    assert "SUPERADMIN" in codigos  # los suyos
    assert api.get(f"{BASE}{rol_de(e.org_a, 'VENDEDOR').pk}/").status_code == 404
    assert api.delete(f"{BASE}{rol_de(e.org_a, 'VENDEDOR').pk}/").status_code == 404
    assert (
        api.get(BASE).json()["count"]
        == Rol.objects.sin_ambito().filter(organizacion=e.org_b).count()
    )
