"""Entrega de la tienda: zonas con tarifa por peso, puntos de recojo con stock y su panel."""

# ruff: noqa: F811

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import envios
from apps.tienda.models import CoberturaZona, PuntoRecojo, ZonaEnvio

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/envios/"
LIMA, MIRAFLORES, SJL, AREQUIPA, PUNO = "150101", "150122", "150132", "040101", "210101"


def zona_lima(**extra):
    return {
        "nombre": "Lima",
        "modalidad": "TIENDA",
        "plazo": "24 a 48 horas",
        "tarifas": [
            {"hasta_kg": "2", "costo": "10"},
            {"hasta_kg": "5", "costo": "15"},
            {"hasta_kg": "10", "costo": "22.50"},
        ],
        "coberturas": ["1501"],  # toda la provincia de Lima
        "kg_adicional": "3",
        **extra,
    }


def crear_zona(datos):
    r = cliente_de("admin").post(ADMIN + "zonas/", datos, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def ctx(tienda):
    from apps.tienda import catalogo

    return catalogo.contexto()


class TestCotizacion:
    def test_el_costo_depende_del_peso_y_sube_por_kg_adicional(self, tienda):
        crear_zona(zona_lima())
        c = ctx(tienda)
        costo = lambda peso: envios.cotizar_envio(  # noqa: E731
            c, ubigeo=MIRAFLORES, peso=Decimal(peso), subtotal=Decimal("100")
        )["costo"]
        assert costo("1.5") == "10.00" and costo("2") == "10.00"
        assert costo("2.01") == "15.00" and costo("10") == "22.50"
        assert costo("11") == "25.50"  # 22.50 + 1 kg adicional
        assert costo("12.2") == "31.50"  # 22.50 + 3 kg (se redondea hacia arriba)

    def test_sin_kg_adicional_no_se_atiende_un_peso_mayor(self, tienda):
        crear_zona(zona_lima(kg_adicional=None))
        r = envios.cotizar_envio(
            ctx(tienda), ubigeo=LIMA, peso=Decimal("30"), subtotal=Decimal("500")
        )
        assert r["disponible"] is False and "coordinarlo" in r["motivo"]

    def test_gratis_desde_un_monto(self, tienda):
        crear_zona(zona_lima(envio_gratis_desde="300"))
        c = ctx(tienda)
        con = envios.cotizar_envio(c, ubigeo=LIMA, peso=Decimal("1"), subtotal=Decimal("300"))
        sin = envios.cotizar_envio(c, ubigeo=LIMA, peso=Decimal("1"), subtotal=Decimal("299.99"))
        assert (con["costo"], con["gratis"]) == ("0.00", True)
        assert (sin["costo"], sin["gratis"]) == ("10.00", False)

    def test_la_cobertura_mas_especifica_gana(self, tienda):
        crear_zona(zona_lima())
        crear_zona(
            {
                "nombre": "Lima norte",
                "modalidad": "TIENDA",
                "tarifas": [{"hasta_kg": "5", "costo": "30"}],
                "coberturas": [SJL],
            }
        )
        c = ctx(tienda)
        assert envios.zona_para(c.organizacion_id, SJL).nombre == "Lima norte"
        assert envios.zona_para(c.organizacion_id, MIRAFLORES).nombre == "Lima"

    def test_agencia_no_cobra_el_envio_en_la_compra(self, tienda):
        crear_zona(
            {
                "nombre": "Provincias",
                "modalidad": "DESTINO",
                "detalle": "Enviamos por Olva o Shalom.",
                "coberturas": ["04", "21"],
            }
        )
        r = envios.cotizar_envio(
            ctx(tienda), ubigeo=PUNO, peso=Decimal("3"), subtotal=Decimal("90")
        )
        assert r["disponible"] and r["paga_en_destino"] and r["costo"] == "0.00"
        assert r["detalle"] == "Enviamos por Olva o Shalom."

    def test_lugar_sin_cobertura_o_zona_apagada_no_se_atiende(self, tienda):
        zona = crear_zona(zona_lima())["zonas"][0]
        c = ctx(tienda)
        assert (
            envios.cotizar_envio(c, ubigeo=PUNO, peso=Decimal("1"), subtotal=Decimal("1"))[
                "disponible"
            ]
            is False
        )
        cliente_de("admin").patch(f"{ADMIN}zonas/{zona['id']}/", {"activa": False}, format="json")
        r = envios.cotizar_envio(c, ubigeo=LIMA, peso=Decimal("1"), subtotal=Decimal("1"))
        assert r["disponible"] is False

    def test_la_tienda_puede_apagar_el_envio(self, tienda):
        crear_zona(zona_lima())
        cliente_de("admin").patch(
            "/api/v1/tienda/admin/configuracion/", {"permite_envio": False}, format="json"
        )
        from django.core.cache import cache

        cache.clear()
        r = envios.cotizar_envio(ctx(tienda), ubigeo=LIMA, peso=Decimal("1"), subtotal=Decimal("1"))
        assert r["disponible"] is False

    def test_peso_del_producto_o_el_de_la_tienda_por_defecto(self, tienda):
        con_peso = tienda.publicar("Pesado", precio=10, stock=5, peso_kg=Decimal("2.5"))
        sin_peso = tienda.publicar("Liviano", precio=10, stock=5)
        c = ctx(tienda)
        assert envios.peso_total([(con_peso, 2), (sin_peso, 1)], c) == Decimal(
            "6.0"
        )  # 5 + 1 (def.)


class TestRecojo:
    def punto(self, tienda, almacenes, **extra):
        return {
            "nombre": "Tienda Centro",
            "direccion": "Av. Lima 14",
            "horario": "L a S 9 a 7",
            "almacenes": [a.pk for a in almacenes],
            **extra,
        }

    def test_solo_se_ofrecen_los_puntos_que_tienen_todo_el_pedido(self, tienda):
        e = tienda.e
        a = tienda.publicar("Mouse", precio=20, stock=3)
        r = cliente_de("admin").post(ADMIN + "puntos/", self.punto(tienda, [e.alm1]), format="json")
        assert r.status_code == 201, r.content
        c = ctx(tienda)
        ok = envios.puntos_de_recojo(c, [(a, 3)])
        assert ok[0]["disponible"] is True and ok[0]["nombre"] == "Tienda Centro"
        falta = envios.puntos_de_recojo(c, [(a, 4)])
        assert falta[0]["disponible"] is False and falta[0]["faltan"] == [a.pk]

    def test_un_punto_sin_almacenes_no_tiene_stock(self, tienda):
        a = tienda.publicar("Mouse", precio=20, stock=3)
        cliente_de("admin").post(ADMIN + "puntos/", self.punto(tienda, []), format="json")
        assert envios.puntos_de_recojo(ctx(tienda), [(a, 1)])[0]["disponible"] is False

    def test_puntos_apagados_y_recojo_desactivado(self, tienda):
        e = tienda.e
        salida = (
            cliente_de("admin")
            .post(ADMIN + "puntos/", self.punto(tienda, [e.alm1]), format="json")
            .json()
        )
        pid = salida["puntos"][0]["id"]
        cliente_de("admin").patch(f"{ADMIN}puntos/{pid}/", {"activo": False}, format="json")
        assert envios.puntos_de_recojo(ctx(tienda), []) == []
        cliente_de("admin").patch(f"{ADMIN}puntos/{pid}/", {"activo": True}, format="json")
        cliente_de("admin").patch(
            "/api/v1/tienda/admin/configuracion/", {"permite_recojo": False}, format="json"
        )
        from django.core.cache import cache

        cache.clear()
        assert envios.puntos_de_recojo(ctx(tienda), []) == []

    def test_rechaza_almacenes_inexistentes(self, tienda):
        r = cliente_de("admin").post(
            ADMIN + "puntos/", {**self.punto(tienda, []), "almacenes": [999999]}, format="json"
        )
        assert r.status_code == 400


class TestPanel:
    def test_solo_el_administrador_configura_envios(self, tienda):
        assert cliente_de("admin").get(ADMIN).status_code == 200
        assert cliente_de("vendedor").get(ADMIN).status_code == 403
        assert APIClient().get(ADMIN).status_code == 401
        r = cliente_de("vendedor").post(ADMIN + "zonas/", zona_lima(), format="json")
        assert r.status_code == 403

    def test_un_lugar_no_puede_estar_en_dos_zonas(self, tienda):
        crear_zona(zona_lima())
        r = cliente_de("admin").post(
            ADMIN + "zonas/",
            {"nombre": "Otra", "modalidad": "TIENDA", "tarifas": [{"hasta_kg": "1", "costo": "5"}],
             "coberturas": ["1501"]},
            format="json",
        )  # fmt: skip
        assert r.status_code == 400 and "ya está en la zona" in str(r.json())

    @pytest.mark.parametrize(
        "cambio",
        [
            {"tarifas": []},
            {"tarifas": [{"hasta_kg": "2", "costo": "5"}, {"hasta_kg": "2", "costo": "6"}]},
            {"tarifas": [{"hasta_kg": "-1", "costo": "5"}]},
            {"coberturas": ["99"]},
            {"coberturas": ["abc"]},
            {"modalidad": "OTRA"},
            {"nombre": "  "},
        ],
    )
    def test_rechaza_datos_invalidos(self, tienda, cambio):
        r = cliente_de("admin").post(ADMIN + "zonas/", {**zona_lima(), **cambio}, format="json")
        assert r.status_code == 400, r.content

    def test_editar_reemplaza_tarifas_y_lugares_y_eliminar_los_libera(self, tienda):
        zona = crear_zona(zona_lima())["zonas"][0]
        admin = cliente_de("admin")
        r = admin.patch(
            f"{ADMIN}zonas/{zona['id']}/",
            {"tarifas": [{"hasta_kg": "3", "costo": "12"}], "coberturas": ["150101", "150122"]},
            format="json",
        )
        assert r.status_code == 200
        editada = r.json()["zonas"][0]
        assert [t["costo"] for t in editada["tarifas"]] == ["12.00"]
        assert {c["prefijo"] for c in editada["coberturas"]} == {"150101", "150122"}
        assert admin.delete(f"{ADMIN}zonas/{zona['id']}/").json()["zonas"] == []
        assert not CoberturaZona.objects.sin_ambito().exists()
        crear_zona(zona_lima())  # los lugares y el nombre quedaron libres
        assert ZonaEnvio.objects.sin_ambito().count() == 1

    def test_otra_organizacion_no_ve_ni_toca_estas_zonas(self, tienda):
        zona = crear_zona(zona_lima())["zonas"][0]
        otra = cliente_de("otra_org")
        assert otra.get(ADMIN).json()["zonas"] == []
        assert (
            otra.patch(f"{ADMIN}zonas/{zona['id']}/", {"nombre": "X"}, format="json").status_code
            == 404
        )
        assert otra.delete(f"{ADMIN}zonas/{zona['id']}/").status_code == 404

    def test_lista_de_lugares_para_elegir(self, tienda):
        admin = cliente_de("admin")
        deptos = admin.get(ADMIN + "ubigeos/").json()
        lima = next(d for d in deptos if d["codigo"] == "15")
        assert any(p["codigo"] == "1501" for p in lima["provincias"])
        distritos = admin.get(ADMIN + "ubigeos/?provincia=1501").json()
        assert any(d["codigo"] == "150122" for d in distritos)
        assert admin.get(ADMIN + "ubigeos/?provincia=xx").status_code == 400

    def test_punto_eliminado_se_conserva_y_libera_el_nombre(self, tienda):
        e = tienda.e
        admin = cliente_de("admin")
        datos = {"nombre": "Centro", "direccion": "Av. 1", "almacenes": [e.alm1.pk]}
        pid = admin.post(ADMIN + "puntos/", datos, format="json").json()["puntos"][0]["id"]
        admin.delete(f"{ADMIN}puntos/{pid}/")
        assert PuntoRecojo.objects.sin_ambito(incluir_eliminados=True).count() == 1
        assert admin.post(ADMIN + "puntos/", datos, format="json").status_code == 201
