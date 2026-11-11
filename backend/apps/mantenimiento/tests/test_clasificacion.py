"""Familias, categorías y marcas: catálogos de la organización, compartidos por sus empresas."""

import pytest

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento.models import Categoria, Familia
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        # Trabaja solo en la empresa 1 y en la 2 por separado: ven el mismo catálogo.
        "tienda1": nuevo_usuario(e.org_a, "tienda1", [e.emp_a1], [("ALMACENERO", None)]),
        "tienda2": nuevo_usuario(e.org_a, "tienda2", [e.emp_a2], [("ALMACENERO", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def crear_familia(api, nombre="Repuestos", **extra):
    r = api.post(f"{BASE}/familias/", {"nombre": nombre, **extra}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def crear_categoria(api, familia, nombre="Teclado", **extra):
    r = api.post(
        f"{BASE}/categorias/", {"familia": familia["id"], "nombre": nombre, **extra}, format="json"
    )
    assert r.status_code == 201, r.content
    return r.json()


# ---------------------------------------------------------------------------
# Compartido por las dos empresas
# ---------------------------------------------------------------------------
class TestCompartidoEntreEmpresas:
    def test_lo_que_crea_una_tienda_lo_ve_la_otra(self, equipo):
        super_ = cliente_de("super")
        familia = crear_familia(super_)
        crear_categoria(super_, familia)
        super_.post(f"{BASE}/marcas/", {"nombre": "Logitech"}, format="json")
        for usuario in ("tienda1", "tienda2"):  # cada una trabaja con su propia empresa
            api = cliente_de(usuario)
            assert [f["nombre"] for f in api.get(f"{BASE}/familias/").json()["results"]] == [
                "Repuestos"
            ]
            categorias = api.get(f"{BASE}/categorias/", {"familia": familia["id"]}).json()
            assert [c["nombre"] for c in categorias["results"]] == ["Teclado"]
            assert api.get(f"{BASE}/marcas/").json()["count"] == 1

    def test_otra_organizacion_no_ve_ni_toca_nada(self, equipo):
        super_ = cliente_de("super")
        familia = crear_familia(super_)
        ajeno = cliente_de("otra_org")
        assert ajeno.get(f"{BASE}/familias/").json()["count"] == 0
        assert ajeno.get(f"{BASE}/familias/{familia['id']}/").status_code == 404
        assert (
            ajeno.patch(
                f"{BASE}/familias/{familia['id']}/", {"nombre": "X"}, format="json"
            ).status_code
            == 404
        )
        # No puede colgar una categoría de una familia ajena.
        r = ajeno.post(
            f"{BASE}/categorias/", {"familia": familia["id"], "nombre": "X"}, format="json"
        )
        assert r.status_code == 400
        # Y puede tener su propia familia con el mismo nombre.
        assert (
            ajeno.post(f"{BASE}/familias/", {"nombre": "Repuestos"}, format="json").status_code
            == 201
        )


# ---------------------------------------------------------------------------
# Familias
# ---------------------------------------------------------------------------
class TestFamilias:
    def test_alta_edicion_cuenta_de_categorias_y_auditoria(self, equipo):
        api = cliente_de("super")
        familia = crear_familia(api, "  Redes   y comunicaciones ")
        assert familia["nombre"] == "Redes y comunicaciones"  # espacios normalizados
        assert familia["estado"] == "ACTIVO" and familia["n_categorias"] == 0
        crear_categoria(api, familia, "Router")
        crear_categoria(api, familia, "Switch")
        lista = api.get(f"{BASE}/familias/").json()["results"]
        assert lista[0]["n_categorias"] == 2
        r = api.patch(f"{BASE}/familias/{familia['id']}/", {"nombre": "Redes"}, format="json")
        assert r.status_code == 200 and r.json()["nombre"] == "Redes"
        acciones = set(AuditoriaEvento.objects.values_list("accion", flat=True))
        assert {"familia.creado", "familia.editado", "categoria.creado"} <= acciones

    def test_el_nombre_no_se_repite_ni_con_otras_mayusculas(self, equipo):
        api = cliente_de("super")
        crear_familia(api, "Repuestos")
        for repetido in ("Repuestos", "REPUESTOS", " repuestos "):
            r = api.post(f"{BASE}/familias/", {"nombre": repetido}, format="json")
            assert r.status_code == 400 and "nombre" in str(r.json()), repetido
        assert api.post(f"{BASE}/familias/", {"nombre": "  "}, format="json").status_code == 400

    def test_no_se_elimina_una_familia_con_categorias(self, equipo):
        api = cliente_de("super")
        familia = crear_familia(api)
        categoria = crear_categoria(api, familia)
        r = api.delete(f"{BASE}/familias/{familia['id']}/")
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "familia_con_categorias")
        # Vacía, sí.
        assert api.delete(f"{BASE}/categorias/{categoria['id']}/").status_code == 204
        assert api.delete(f"{BASE}/familias/{familia['id']}/").status_code == 204
        assert Familia.objects.sin_ambito(incluir_eliminados=True).filter(pk=familia["id"]).exists()
        # El nombre queda libre para volver a usarlo.
        crear_familia(api, "Repuestos")

    def test_una_familia_inactiva_no_recibe_categorias_nuevas(self, equipo):
        api = cliente_de("super")
        familia = crear_familia(api)
        api.patch(f"{BASE}/familias/{familia['id']}/", {"estado": "INACTIVO"}, format="json")
        r = api.post(
            f"{BASE}/categorias/", {"familia": familia["id"], "nombre": "Teclado"}, format="json"
        )
        assert r.status_code == 400 and "familia" in str(r.json())


# ---------------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------------
class TestCategorias:
    def test_el_nombre_es_unico_por_familia_no_en_todo_el_sistema(self, equipo):
        api = cliente_de("super")
        repuestos = crear_familia(api, "Repuestos")
        accesorios = crear_familia(api, "Accesorios")
        crear_categoria(api, repuestos, "Teclado")
        r = api.post(
            f"{BASE}/categorias/", {"familia": repuestos["id"], "nombre": "TECLADO"}, format="json"
        )
        assert r.status_code == 400
        # El mismo nombre en otra familia es otra categoría.
        otra = crear_categoria(api, accesorios, "Teclado")
        assert otra["familia_nombre"] == "Accesorios"

    def test_se_filtra_busca_y_pagina(self, equipo):
        api = cliente_de("super")
        repuestos = crear_familia(api, "Repuestos")
        accesorios = crear_familia(api, "Accesorios")
        for nombre in ("Teclado", "Impresora", "Pantalla"):
            crear_categoria(api, repuestos, nombre)
        crear_categoria(api, accesorios, "Cargador")
        todas = api.get(f"{BASE}/categorias/").json()
        assert todas["count"] == 4 and {"next", "previous", "results"} <= todas.keys()
        assert api.get(f"{BASE}/categorias/", {"familia": repuestos["id"]}).json()["count"] == 3
        assert api.get(f"{BASE}/categorias/", {"q": "carg"}).json()["count"] == 1
        assert (
            api.get(f"{BASE}/categorias/", {"q": "accesorios"}).json()["count"] == 1
        )  # por familia
        assert api.get(f"{BASE}/categorias/", {"familia": "abc"}).status_code == 400
        assert [
            c["nombre"]
            for c in api.get(f"{BASE}/categorias/", {"familia": repuestos["id"]}).json()["results"]
        ] == [
            "Impresora",
            "Pantalla",
            "Teclado",
        ]

    def test_se_mueve_a_otra_familia_y_se_desactiva(self, equipo):
        api = cliente_de("super")
        repuestos = crear_familia(api, "Repuestos")
        accesorios = crear_familia(api, "Accesorios")
        crear_categoria(api, accesorios, "Cargador")
        cargador = crear_categoria(api, repuestos, "Cargador")  # mismo nombre, otra familia
        url = f"{BASE}/categorias/{cargador['id']}/"
        # No puede quedar duplicada al moverla a donde ya existe.
        assert api.patch(url, {"familia": accesorios["id"]}, format="json").status_code == 400
        assert api.patch(url, {"nombre": "Cable USB"}, format="json").status_code == 200
        movida = api.patch(url, {"familia": accesorios["id"], "estado": "INACTIVO"}, format="json")
        assert movida.status_code == 200, movida.content
        assert (movida.json()["familia"], movida.json()["estado"]) == (accesorios["id"], "INACTIVO")
        assert Categoria.objects.sin_ambito().get(pk=cargador["id"]).familia_id == accesorios["id"]


# ---------------------------------------------------------------------------
# Marcas
# ---------------------------------------------------------------------------
class TestMarcas:
    def test_alta_unica_por_nombre_y_baja_logica(self, equipo):
        api = cliente_de("super")
        r = api.post(f"{BASE}/marcas/", {"nombre": "Logitech"}, format="json")
        assert r.status_code == 201
        assert api.post(f"{BASE}/marcas/", {"nombre": "logitech"}, format="json").status_code == 400
        assert api.delete(f"{BASE}/marcas/{r.json()['id']}/").status_code == 204
        assert api.post(f"{BASE}/marcas/", {"nombre": "Logitech"}, format="json").status_code == 201


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------
class TestPermisos:
    def test_el_almacenero_consulta_pero_no_modifica(self, equipo):
        familia = crear_familia(cliente_de("super"))
        api = cliente_de("tienda1")
        assert api.get(f"{BASE}/familias/").status_code == 200
        assert api.get(f"{BASE}/marcas/").status_code == 200
        assert api.post(f"{BASE}/familias/", {"nombre": "Otra"}, format="json").status_code == 403
        assert (
            api.patch(
                f"{BASE}/familias/{familia['id']}/", {"nombre": "X"}, format="json"
            ).status_code
            == 403
        )
        assert api.delete(f"{BASE}/familias/{familia['id']}/").status_code == 403
        assert api.post(f"{BASE}/marcas/", {"nombre": "Nueva"}, format="json").status_code == 403

    def test_sin_permiso_no_entra(self, equipo):
        for ruta in ("familias", "categorias", "marcas"):
            assert cliente_de("vendedor").get(f"{BASE}/{ruta}/").status_code == 403, ruta
