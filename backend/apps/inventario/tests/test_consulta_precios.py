"""Consulta rápida de precios del vendedor: búsqueda, escáner, stock, ubicación y sin costos."""

import pytest

from apps.auditoria import servicios
from apps.inventario.tests.ayudas_api import BASE, cuerpo, registrar
from apps.mantenimiento.models import ListaPrecio, PrecioProducto, Ubicacion, UbicacionProducto
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

URL = f"{BASE}/consulta-precios/"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def surtido(mundo):
    """Un mouse con barras, precio y stock (20 en la empresa 1), ubicado en V1."""
    mouse = mundo.producto("Mouse inalámbrico Logitech", codigo_barras="7750182001234", costo="14")
    lista = ListaPrecio.objects.sin_ambito().create(
        organizacion=mundo.e.org_a, nombre="Público", es_principal=True
    )
    PrecioProducto.objects.sin_ambito().create(
        organizacion=mundo.e.org_a, producto=mouse, lista=lista, precio="35", utilidad="150"
    )
    assert registrar(cliente_de("super"), cuerpo(mundo, mouse, cantidad="20")).status_code == 201
    ubicacion = Ubicacion.objects.sin_ambito().create(
        empresa=mundo.e1, almacen=mundo.alm[1], codigo="V1", nombre="Vitrina 1"
    )
    UbicacionProducto.objects.sin_ambito().create(
        empresa=mundo.e1, almacen=mundo.alm[1], producto=mouse, ubicacion=ubicacion
    )
    return mouse


def _buscar(usuario, texto):
    return cliente_de(usuario).get(URL, {"q": texto})


class TestConsultaPrecios:
    def test_busca_por_nombre_y_trae_precio_stock_y_ubicacion(self, mundo, surtido):
        r = _buscar("vendedor", "mouse")
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["exacto"] is False
        p = datos["results"][0]
        assert p["nombre"] == "Mouse inalámbrico Logitech"
        assert [(x["nombre"], x["precio"]) for x in p["precios"]] == [("Público", "35.0000")]
        propia = next(e for e in p["stock"] if e["propia"])
        assert propia["cantidad"] == "20.000"
        assert propia["almacenes"][0]["ubicacion_codigo"] == "V1"

    def test_el_codigo_de_barras_exacto_devuelve_solo_ese(self, mundo, surtido):
        mundo.producto("Mouse gamer", codigo_barras="9990000000001")
        datos = _buscar("vendedor", "7750182001234").json()
        assert datos["exacto"] is True
        assert [p["nombre"] for p in datos["results"]] == ["Mouse inalámbrico Logitech"]

    def test_nunca_expone_costos_ni_utilidad(self, mundo, surtido):
        crudo = _buscar("vendedor", "mouse").content.decode()
        for prohibido in ("costo", "utilidad"):
            assert prohibido not in crudo

    def test_menos_de_dos_letras_no_busca(self, mundo, surtido):
        assert _buscar("vendedor", "m").json()["results"] == []

    def test_no_muestra_productos_inactivos(self, mundo, surtido):
        surtido.estado = "INACTIVO"
        surtido.save()
        assert _buscar("vendedor", "mouse").json()["results"] == []

    def test_el_servicio_no_lleva_stock(self, mundo):
        mundo.producto("Instalación de software", tipo="SERVICIO", controla_stock=False)
        p = _buscar("vendedor", "instalación").json()["results"][0]
        assert p["stock"] is None

    def test_exige_sesion_y_permiso_de_productos(self, mundo, surtido, api):
        assert api.get(URL, {"q": "mouse"}).status_code in (401, 403)
        assert _buscar("otra_org", "mouse").json()["results"] == []

    def test_otra_organizacion_no_ve_el_catalogo(self, mundo, surtido):
        assert _buscar("otra_org", "mouse").json()["results"] == []

    def test_sin_permiso_de_inventario_no_ve_el_stock(self, mundo, surtido):
        # El vendedor de la empresa 2 solo ve la cantidad de la otra empresa si tiene el permiso.
        p = _buscar("vendedor_a2", "mouse").json()["results"][0]
        for empresa in p["stock"]:
            if not empresa["propia"]:
                assert "almacenes" not in empresa


class TestPresentaciones:
    @pytest.fixture
    def con_caja(self, mundo, surtido):
        """El mouse también se vende por caja de 10, con su propio código de barras y precio."""
        from apps.mantenimiento.models import (
            ListaPrecio,
            PrecioPresentacion,
            PresentacionProducto,
            UnidadMedida,
        )

        caja = UnidadMedida.objects.sin_ambito().create(
            organizacion=mundo.e.org_a, nombre="Caja", abreviatura="CAJA", codigo_sunat="BX"
        )
        presentacion = PresentacionProducto.objects.sin_ambito().create(
            organizacion=mundo.e.org_a,
            producto=surtido,
            unidad=caja,
            factor=10,
            codigo_barras="7750009990001",
        )
        lista = ListaPrecio.objects.sin_ambito().get(organizacion=mundo.e.org_a, nombre="Público")
        PrecioPresentacion.objects.sin_ambito().create(
            organizacion=mundo.e.org_a,
            presentacion=presentacion,
            lista=lista,
            precio="320",
            utilidad="128.57",
        )
        return presentacion

    def test_muestra_el_precio_de_cada_unidad(self, mundo, con_caja):
        p = _buscar("vendedor", "mouse").json()["results"][0]
        (caja,) = p["presentaciones"]
        assert (caja["unidad_nombre"], caja["factor"]) == ("Caja", "10")
        assert [(x["nombre"], x["precio"]) for x in caja["precios"]] == [("Público", "320.0000")]

    def test_escanear_la_caja_lleva_al_producto_con_esa_presentacion_marcada(self, mundo, con_caja):
        datos = _buscar("vendedor", "7750009990001").json()
        assert datos["exacto"] is True
        assert datos["presentacion_escaneada"] == con_caja.pk
        assert [p["nombre"] for p in datos["results"]] == ["Mouse inalámbrico Logitech"]

    def test_escanear_la_unidad_base_no_marca_ninguna_presentacion(self, mundo, con_caja):
        datos = _buscar("vendedor", "7750182001234").json()
        assert datos["exacto"] is True and datos["presentacion_escaneada"] is None

    def test_nunca_expone_costos_ni_utilidades_de_las_presentaciones(self, mundo, con_caja):
        crudo = _buscar("vendedor", "mouse").content.decode()
        assert "utilidad" not in crudo and "costo" not in crudo and "128.57" not in crudo

    def test_una_presentacion_desactivada_no_se_ofrece_ni_se_reconoce(self, mundo, con_caja):
        con_caja.estado = "INACTIVO"
        con_caja.save()
        assert _buscar("vendedor", "mouse").json()["results"][0]["presentaciones"] == []
        assert _buscar("vendedor", "7750009990001").json()["results"] == []

    def test_no_muestra_precios_de_listas_desactivadas(self, mundo, con_caja):
        from apps.mantenimiento.models import ListaPrecio

        ListaPrecio.objects.sin_ambito().filter(
            organizacion=mundo.e.org_a, nombre="Público"
        ).update(estado="INACTIVO")
        assert (
            _buscar("vendedor", "mouse").json()["results"][0]["presentaciones"][0]["precios"] == []
        )


class TestUnidadBaseConMovimientos:
    def test_no_se_cambia_la_unidad_base_de_un_producto_con_stock(self, mundo, surtido):
        from apps.mantenimiento.models import UnidadMedida

        otra = UnidadMedida.objects.sin_ambito().create(
            organizacion=mundo.e.org_a, nombre="Docena", abreviatura="DOC", codigo_sunat="DZN"
        )
        api = cliente_de("super")
        r = api.patch(
            f"/api/v1/mantenimiento/productos/{surtido.pk}/", {"unidad": otra.pk}, format="json"
        )
        assert r.status_code == 400
        assert "movimientos" in str(r.json())
