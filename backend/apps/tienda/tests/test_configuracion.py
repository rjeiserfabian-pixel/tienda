"""Configuración de la tienda desde el panel: permisos, validaciones y efecto en lo público."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

import pytest
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda.models import ConfiguracionTienda

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/tienda/admin/configuracion/"


class TestPermisos:
    def test_el_administrador_la_ve_y_el_vendedor_no(self, tienda):
        assert cliente_de("admin").get(URL).status_code == 200
        assert cliente_de("vendedor").get(URL).status_code == 403
        assert cliente_de("almacenero").get(URL).status_code == 403

    def test_sin_sesion_no_entra(self, tienda):
        assert APIClient().get(URL).status_code == 401

    def test_el_vendedor_tampoco_la_cambia(self, tienda):
        r = cliente_de("vendedor").patch(URL, {"activa": False}, format="json")
        assert r.status_code == 403
        assert ConfiguracionTienda.objects.sin_ambito().get(organizacion=tienda.org).activa is True

    def test_otra_organizacion_ve_su_propia_configuracion_no_la_ajena(self, tienda):
        r = cliente_de("otra_org").get(URL)
        assert r.status_code == 200
        assert r.json()["activa"] is False  # una recién creada, no la de la organización A


class TestVer:
    def test_trae_la_configuracion_con_las_opciones_para_elegir(self, tienda):
        d = cliente_de("admin").get(URL).json()
        assert (d["activa"], d["nombre"], d["precios_con_igv"], d["pocas_unidades"]) == (
            True,
            "Technology",
            True,
            5,
        )
        assert d["lista_precio"] is None and d["lista_precio_efectiva"] == tienda.lista.pk
        assert sorted(d["almacenes"]) == sorted([tienda.e.alm1.pk, tienda.e.alm2.pk])
        assert tienda.lista.pk in [ls["id"] for ls in d["opciones"]["listas"]]
        assert {a["id"] for a in d["opciones"]["almacenes"]} >= {tienda.e.alm1.pk}

    def test_trae_el_resumen_de_publicados_y_sin_precio(self, tienda):
        tienda.publicar("Con precio", precio=100)
        tienda.publicar("Sin precio")
        d = cliente_de("admin").get(URL).json()
        assert d["resumen"] == {"publicados": 2, "publicados_sin_precio": 1}

    def test_la_primera_vez_se_crea_apagada_con_los_almacenes_activos(self, tienda):
        ConfiguracionTienda.objects.sin_ambito().filter(organizacion=tienda.org).delete()
        d = cliente_de("admin").get(URL).json()
        assert d["activa"] is False and d["nombre"] == "Tienda"
        assert tienda.e.alm1.pk in d["almacenes"]


class TestCambiar:
    def test_cambia_los_datos_y_se_nota_de_inmediato_en_lo_publico(self, tienda):
        tienda.publicar("Laptop", precio=100)
        publico = APIClient()
        assert publico.get("/api/v1/tienda/menu/").json()["tienda"]["precios_con_igv"] is True
        r = cliente_de("admin").patch(
            URL,
            {"nombre": "  Mi   Tienda ", "precios_con_igv": False, "pocas_unidades": 2},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["nombre"] == "Mi Tienda"
        menu = publico.get("/api/v1/tienda/menu/").json()
        assert menu["tienda"] == {"nombre": "Mi Tienda", "precios_con_igv": False}

    def test_se_puede_apagar_y_la_tienda_deja_de_responder(self, tienda):
        assert cliente_de("admin").patch(URL, {"activa": False}, format="json").status_code == 200
        assert APIClient().get("/api/v1/tienda/menu/").status_code == 503

    def test_no_se_abre_sin_almacenes(self, tienda):
        api = cliente_de("admin")
        api.patch(URL, {"activa": False, "almacenes": []}, format="json")
        r = api.patch(URL, {"activa": True}, format="json")
        assert r.status_code == 400 and "almacén" in r.content.decode()

    def test_los_almacenes_y_la_lista_deben_existir(self, tienda):
        api = cliente_de("admin")
        assert api.patch(URL, {"almacenes": [99999999]}, format="json").status_code == 400
        assert api.patch(URL, {"lista_precio": 99999999}, format="json").status_code == 400

    def test_se_puede_elegir_otra_lista_y_volver_a_la_principal(self, tienda):
        from apps.mantenimiento.models import ListaPrecio

        otra = (
            ListaPrecio.objects.sin_ambito()
            .filter(organizacion=tienda.org, es_principal=False)
            .first()
        )
        api = cliente_de("admin")
        r = api.patch(URL, {"lista_precio": otra.pk}, format="json")
        assert r.json()["lista_precio"] == otra.pk
        r = api.patch(URL, {"lista_precio": None}, format="json")
        assert (
            r.json()["lista_precio"] is None
            and r.json()["lista_precio_efectiva"] == tienda.lista.pk
        )

    def test_un_nombre_vacio_se_rechaza_y_los_valores_se_validan(self, tienda):
        api = cliente_de("admin")
        assert api.patch(URL, {"nombre": "   "}, format="json").status_code == 400
        assert api.patch(URL, {"pocas_unidades": -1}, format="json").status_code == 400
        assert api.patch(URL, {"pocas_unidades": 9999}, format="json").status_code == 400

    def test_cambiar_la_lista_cambia_los_precios_que_ve_el_publico(self, tienda):
        from decimal import Decimal

        from apps.mantenimiento.models import ListaPrecio, PrecioProducto

        p = tienda.publicar("Laptop", precio=100)
        otra = (
            ListaPrecio.objects.sin_ambito()
            .filter(organizacion=tienda.org, es_principal=False)
            .first()
        )
        PrecioProducto.objects.sin_ambito().create(
            organizacion=tienda.org, producto=p, lista=otra, precio=Decimal("80")
        )
        publico = APIClient()
        assert publico.get("/api/v1/tienda/productos/").json()["results"][0]["precio"] == "100.00"
        cliente_de("admin").patch(URL, {"lista_precio": otra.pk}, format="json")
        assert publico.get("/api/v1/tienda/productos/").json()["results"][0]["precio"] == "80.00"


class TestAlmacenesDeOtraEmpresa:
    """Un administrador que solo ve una empresa no debe quitar los almacenes de la otra."""

    def test_guardar_no_borra_el_almacen_de_una_empresa_que_el_usuario_no_ve(self, tienda):
        api = cliente_de("admin")  # administra solo la empresa A1
        d = api.get(URL).json()
        assert sorted(d["almacenes"]) == sorted([tienda.e.alm1.pk, tienda.e.alm2.pk])
        r = api.patch(URL, {"nombre": "Tienda Nueva"}, format="json")
        assert r.status_code == 200
        assert sorted(r.json()["almacenes"]) == sorted([tienda.e.alm1.pk, tienda.e.alm2.pk])

    def test_se_puede_quitar_un_almacen_de_otra_empresa_eligiendo_la_lista(self, tienda):
        api = cliente_de("admin")
        r = api.patch(URL, {"almacenes": [tienda.e.alm1.pk]}, format="json")
        assert r.json()["almacenes"] == [tienda.e.alm1.pk]
        r = api.patch(URL, {"almacenes": [tienda.e.alm1.pk, tienda.e.alm2.pk]}, format="json")
        assert len(r.json()["almacenes"]) == 2
