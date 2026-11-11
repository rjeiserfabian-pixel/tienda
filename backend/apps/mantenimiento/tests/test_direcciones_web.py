"""Direcciones web estables de familias, categorías y marcas (para las páginas de la tienda)."""

import pytest

from apps.seguridad.tests.conftest import cliente_de

from .test_productos import BASE, _auditoria_al_instante, equipo  # noqa: F401

pytestmark = pytest.mark.django_db


def crear(api, ruta, **datos):
    r = api.post(f"{BASE}/{ruta}/", datos, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def test_cada_uno_recibe_su_direccion_a_partir_del_nombre(equipo):  # noqa: F811
    api = cliente_de("super")
    familia = crear(api, "familias", nombre="Computadoras y Movilidad")
    categoria = crear(api, "categorias", familia=familia["id"], nombre="Laptops")
    marca = crear(api, "marcas", nombre="Cooler Master")
    assert familia["slug"] == "computadoras-y-movilidad"
    assert categoria["slug"] == "laptops"
    assert marca["slug"] == "cooler-master"


def test_los_nombres_con_tildes_y_simbolos_dan_direcciones_limpias(equipo):  # noqa: F811
    api = cliente_de("super")
    familia = crear(api, "familias", nombre="Teléfonos / Móviles & más")
    assert familia["slug"] == "telefonos-moviles-mas"


def test_dos_categorias_con_el_mismo_nombre_en_distinta_familia_no_chocan(equipo):  # noqa: F811
    api = cliente_de("super")
    a = crear(api, "familias", nombre="Computadoras")
    b = crear(api, "familias", nombre="Energía")
    uno = crear(api, "categorias", familia=a["id"], nombre="Accesorios")
    dos = crear(api, "categorias", familia=b["id"], nombre="Accesorios")
    assert (uno["slug"], dos["slug"]) == ("accesorios", "accesorios-2")


def test_renombrar_no_cambia_la_direccion(equipo):  # noqa: F811
    api = cliente_de("super")
    marca = crear(api, "marcas", nombre="Lenovo")
    r = api.patch(f"{BASE}/marcas/{marca['id']}/", {"nombre": "Lenovo Group"}, format="json")
    assert r.status_code == 200
    assert r.json()["slug"] == "lenovo"


def test_una_direccion_liberada_por_borrado_se_puede_reusar(equipo):  # noqa: F811
    api = cliente_de("super")
    marca = crear(api, "marcas", nombre="Genius")
    assert api.delete(f"{BASE}/marcas/{marca['id']}/").status_code == 204
    otra = crear(api, "marcas", nombre="Genius")
    assert otra["slug"] in ("genius", "genius-2")


def test_cada_organizacion_tiene_sus_propias_direcciones(equipo):  # noqa: F811
    uno = crear(cliente_de("super"), "marcas", nombre="Logitech")
    otro = crear(cliente_de("otra_org"), "marcas", nombre="Logitech")
    assert uno["slug"] == otro["slug"] == "logitech"
