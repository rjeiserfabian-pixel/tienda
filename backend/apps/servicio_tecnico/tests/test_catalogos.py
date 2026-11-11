"""Catálogos del taller: carga de fábrica, API, permisos y aislamiento por organización."""

import pytest

from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import catalogos
from apps.servicio_tecnico.models import (
    AccesorioEquipo,
    CategoriaServicio,
    ItemChecklist,
    TipoEquipo,
    TipoServicio,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/servicio-tecnico"


class TestSiembra:
    def test_carga_todo_lo_de_fabrica(self, taller):
        org = taller.org
        assert TipoEquipo.objects.sin_ambito().filter(organizacion=org).count() == len(
            catalogos.TIPOS_EQUIPO
        )
        assert AccesorioEquipo.objects.sin_ambito().filter(organizacion=org).count() == len(
            catalogos.ACCESORIOS
        )
        assert ItemChecklist.objects.sin_ambito().filter(organizacion=org).count() == len(
            catalogos.REVISIONES
        )
        assert TipoServicio.objects.sin_ambito().filter(organizacion=org).count() == len(
            catalogos.TIPOS_SERVICIO
        )

    def test_repetirla_no_duplica_ni_pisa_lo_editado(self, taller):
        laptop = TipoEquipo.objects.sin_ambito().get(organizacion=taller.org, codigo="LAPTOP")
        laptop.nombre = "Portátil"
        laptop.save()
        assert catalogos.sembrar_catalogos_servicio(taller.org.pk) == {
            "tipos_equipo": 0,
            "accesorios": 0,
            "revisiones": 0,
            "tipos_servicio": 0,
        }
        laptop.refresh_from_db()
        assert laptop.nombre == "Portátil"

    def test_lo_que_se_elimino_no_vuelve(self, taller):
        TipoEquipo.objects.sin_ambito().get(organizacion=taller.org, codigo="TABLET").delete()
        assert catalogos.sembrar_catalogos_servicio(taller.org.pk)["tipos_equipo"] == 0

    def test_hay_servicios_de_las_tres_categorias(self, taller):
        categorias = set(
            TipoServicio.objects.sin_ambito()
            .filter(organizacion=taller.org)
            .values_list("categoria", flat=True)
        )
        assert categorias == {
            CategoriaServicio.DIAGNOSTICO,
            CategoriaServicio.MANTENIMIENTO,
            CategoriaServicio.REPARACION,
        }


class TestApi:
    def test_el_administrador_lista_y_el_otro_no_ve_los_de_su_org(self, taller):
        api = cliente_de("admin")
        r = api.get(f"{BASE}/tipos-equipo/", {"page_size": 100})
        assert r.status_code == 200
        assert r.json()["count"] == len(catalogos.TIPOS_EQUIPO)

    def test_crea_edita_y_busca_un_tipo_de_equipo(self, taller):
        api = cliente_de("admin")
        r = api.post(f"{BASE}/tipos-equipo/", {"nombre": "Consola de juegos"}, format="json")
        assert r.status_code == 201, r.content
        identificador = r.json()["id"]
        edit = api.patch(
            f"{BASE}/tipos-equipo/{identificador}/", {"nombre": "Consola"}, format="json"
        )
        assert (edit.status_code, edit.json()["nombre"]) == (200, "Consola")
        buscar = api.get(f"{BASE}/tipos-equipo/", {"q": "consola"})
        assert buscar.json()["count"] == 1

    def test_nombre_repetido(self, taller):
        r = cliente_de("admin").post(f"{BASE}/tipos-equipo/", {"nombre": "laptop"}, format="json")
        assert r.status_code in (400, 409)

    def test_tipo_de_equipo_en_uso_no_se_elimina(self, taller):
        r = cliente_de("admin").delete(f"{BASE}/tipos-equipo/{taller.equipo.tipo_id}/")
        assert r.status_code in (400, 409)
        assert TipoEquipo.objects.sin_ambito().filter(pk=taller.equipo.tipo_id).exists()

    def test_tipo_sin_uso_se_elimina(self, taller):
        api = cliente_de("admin")
        creado = api.post(f"{BASE}/tipos-equipo/", {"nombre": "Proyector"}, format="json").json()
        assert api.delete(f"{BASE}/tipos-equipo/{creado['id']}/").status_code == 204

    def test_tipo_de_servicio_con_garantia_y_precio(self, taller):
        api = cliente_de("admin")
        r = api.post(
            f"{BASE}/tipos-servicio/",
            {
                "nombre": "Cambio de teclado",
                "categoria": "REPARACION",
                "garantia_dias": 60,
                "precio_referencial": "35.00",
            },
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["garantia_dias"] == 60
        assert r.json()["categoria_nombre"] == "Reparación"

    def test_precio_negativo_se_rechaza(self, taller):
        r = cliente_de("admin").post(
            f"{BASE}/tipos-servicio/",
            {"nombre": "Algo", "precio_referencial": "-1"},
            format="json",
        )
        assert r.status_code == 400

    def test_revisiones_por_tipo_incluyen_las_generales(self, taller):
        api = cliente_de("admin")
        laptop = taller.equipo.tipo_id
        propia = api.post(
            f"{BASE}/revisiones/",
            {"nombre": "Bisagras", "tipo_equipo": laptop, "orden": 20},
            format="json",
        )
        assert propia.status_code == 201, propia.content
        impresora = (
            TipoEquipo.objects.sin_ambito().get(organizacion=taller.org, codigo="IMPRESORA").pk
        )
        de_laptop = api.get(f"{BASE}/revisiones/", {"tipo_equipo": laptop, "page_size": 100})
        de_impresora = api.get(f"{BASE}/revisiones/", {"tipo_equipo": impresora, "page_size": 100})
        nombres_laptop = {f["nombre"] for f in de_laptop.json()["results"]}
        nombres_impresora = {f["nombre"] for f in de_impresora.json()["results"]}
        assert "Bisagras" in nombres_laptop
        assert "Bisagras" not in nombres_impresora
        assert len(nombres_impresora) == len(catalogos.REVISIONES)

    def test_revision_con_tipo_de_otra_org_se_rechaza(self, taller):
        ajeno = TipoEquipo.objects.sin_ambito().filter(organizacion=taller.e.org_b).first()
        r = cliente_de("admin").post(
            f"{BASE}/revisiones/", {"nombre": "Algo", "tipo_equipo": ajeno.pk}, format="json"
        )
        assert r.status_code == 400

    def test_aislamiento_entre_organizaciones(self, taller):
        propio = TipoEquipo.objects.sin_ambito().get(organizacion=taller.org, codigo="LAPTOP")
        r = cliente_de("otra_org").get(f"{BASE}/tipos-equipo/{propio.pk}/")
        assert r.status_code == 404
        assert (
            cliente_de("otra_org")
            .patch(f"{BASE}/tipos-equipo/{propio.pk}/", {"nombre": "X"}, format="json")
            .status_code
            == 404
        )


class TestPermisos:
    def test_el_vendedor_no_toca_los_catalogos(self, taller):
        api = cliente_de("vendedor")
        assert api.get(f"{BASE}/tipos-equipo/").status_code == 403
        assert api.post(f"{BASE}/tipos-equipo/", {"nombre": "X"}, format="json").status_code == 403

    def test_el_tecnico_no_edita_los_catalogos(self, taller):
        api = cliente_de("tecnico")
        assert (
            api.post(f"{BASE}/tipos-servicio/", {"nombre": "X"}, format="json").status_code == 403
        )

    def test_sin_sesion_no_hay_acceso(self, taller, api):
        assert api.get(f"{BASE}/tipos-equipo/").status_code in (401, 403)
