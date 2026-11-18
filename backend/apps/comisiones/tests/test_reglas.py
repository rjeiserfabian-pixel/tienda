"""Reglas de comisión: validación, cuál gana y la API."""

from datetime import date

import pytest

from apps.auditoria.models import AuditoriaEvento
from apps.comisiones import servicios
from apps.comisiones.models import ReglaComision
from apps.comisiones.servicios import ReglaInvalida
from apps.mantenimiento.models import Marca
from apps.seguridad.models import Usuario
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/comisiones/reglas/"
HOY = date(2026, 11, 18)


def org(tienda):
    return tienda.entorno.e.org_a


def vendedor(tienda, nombre="vendedor"):
    return Usuario.objects.get(username=nombre)


def producto(tienda, nombre="Celular", marca=None, **extra):
    p = tienda.producto(nombre, **extra)
    if marca:
        p.marca = Marca.objects.sin_ambito().get_or_create(organizacion=org(tienda), nombre=marca)[
            0
        ]
        p.save()
    return p


def regla(tienda, alcance="GENERAL", porcentaje="3", **extra):
    return servicios.crear(org(tienda).pk, {"alcance": alcance, "porcentaje": porcentaje, **extra})


def pct(tienda, p, quien=None, fecha=HOY):
    r = servicios.porcentaje_para(
        org(tienda).pk, vendedor_id=quien.pk if quien else None, producto=p, fecha=fecha
    )
    return r.porcentaje, r.regla


class TestCrear:
    def test_crea_una_regla_general(self, tienda):
        r = regla(tienda, porcentaje="2,5")
        assert (r.alcance, str(r.porcentaje), r.vendedor_id, r.activa) == (
            "GENERAL",
            "2.50",
            None,
            True,
        )

    @pytest.mark.parametrize("valor", ["", "abc", "-1", "100,01", "NaN"])
    def test_el_porcentaje_debe_ser_un_numero_de_0_a_100(self, tienda, valor):
        with pytest.raises(ReglaInvalida):
            regla(tienda, porcentaje=valor)

    def test_una_regla_de_marca_pide_la_marca(self, tienda):
        with pytest.raises(ReglaInvalida, match="marca"):
            regla(tienda, "MARCA")
        with pytest.raises(ReglaInvalida, match="marca"):
            regla(tienda, "MARCA", marca=999999)

    def test_una_regla_de_producto_necesita_un_producto_de_la_organizacion(self, tienda):
        with pytest.raises(ReglaInvalida, match="producto"):
            regla(tienda, "PRODUCTO", producto=999999)

    def test_el_vendedor_debe_ser_de_la_organizacion(self, tienda):
        with pytest.raises(ReglaInvalida, match="vendedor"):
            regla(tienda, vendedor_id="00000000-0000-0000-0000-000000000001")

    def test_las_fechas_van_en_orden(self, tienda):
        with pytest.raises(ReglaInvalida, match="anterior"):
            regla(tienda, vigente_desde="2026-12-01", vigente_hasta="2026-11-01")

    def test_no_se_repite_una_regla_activa_igual_pero_si_en_otras_fechas(self, tienda):
        regla(tienda, vigente_hasta="2026-12-31")
        with pytest.raises(ReglaInvalida, match="igual"):
            regla(tienda, porcentaje="4")
        regla(tienda, porcentaje="4", vigente_desde="2027-01-01")  # otro periodo: vale
        regla(tienda, porcentaje="1", vendedor_id=str(vendedor(tienda).pk))  # otro vendedor: vale

    def test_una_regla_pausada_no_estorba(self, tienda):
        regla(tienda, activa=False)
        regla(tienda)

    def test_queda_en_la_auditoria(self, tienda):
        r = regla(tienda, "GENERAL", "2")
        assert AuditoriaEvento.objects.filter(
            accion="comisiones.regla_creada", recurso_id=str(r.pk)
        ).exists()


class TestCualGana:
    def test_sin_reglas_no_paga(self, tienda):
        assert pct(tienda, producto(tienda)) == (0, None)

    def test_la_mas_especifica_gana_producto_marca_categoria_general(self, tienda):
        p = producto(tienda, "Galaxy", marca="Samsung")
        regla(tienda, porcentaje="1")
        assert str(pct(tienda, p)[0]) == "1.00"
        regla(tienda, "CATEGORIA", "2", categoria=p.categoria_id)
        assert str(pct(tienda, p)[0]) == "2.00"
        regla(tienda, "MARCA", "3", marca=p.marca_id)
        assert str(pct(tienda, p)[0]) == "3.00"
        regla(tienda, "PRODUCTO", "5", producto=p.pk)
        assert str(pct(tienda, p)[0]) == "5.00"

    def test_otra_marca_u_otro_producto_no_se_mezclan(self, tienda):
        samsung = producto(tienda, "Galaxy", marca="Samsung")
        otro = producto(tienda, "Redmi", marca="Xiaomi")
        regla(tienda, "MARCA", "3", marca=samsung.marca_id)
        assert str(pct(tienda, samsung)[0]) == "3.00"
        assert pct(tienda, otro)[0] == 0

    def test_un_producto_sin_marca_no_encaja_con_una_regla_de_marca(self, tienda):
        regla(tienda, "GENERAL", "1")
        sin_marca = producto(tienda, "Cable")
        regla(tienda, "MARCA", "9", marca=producto(tienda, "Otro", marca="Sony").marca_id)
        assert str(pct(tienda, sin_marca)[0]) == "1.00"

    def test_la_regla_del_vendedor_le_gana_a_la_de_todos_en_el_mismo_alcance(self, tienda):
        p = producto(tienda)
        ana = vendedor(tienda)
        regla(tienda, porcentaje="2")
        regla(tienda, porcentaje="4", vendedor_id=str(ana.pk))
        assert str(pct(tienda, p, ana)[0]) == "4.00"
        assert str(pct(tienda, p, vendedor(tienda, "cajero"))[0]) == "2.00"

    def test_el_alcance_pesa_mas_que_ser_de_un_vendedor(self, tienda):
        p = producto(tienda, "Galaxy", marca="Samsung")
        ana = vendedor(tienda)
        regla(tienda, porcentaje="9", vendedor_id=str(ana.pk))
        regla(tienda, "MARCA", "1", marca=p.marca_id)
        assert str(pct(tienda, p, ana)[0]) == "1.00"

    def test_respeta_la_vigencia_y_las_pausas(self, tienda):
        p = producto(tienda)
        r = regla(tienda, porcentaje="3", vigente_desde="2026-12-01", vigente_hasta="2026-12-31")
        assert pct(tienda, p)[0] == 0
        assert str(pct(tienda, p, fecha=date(2026, 12, 15))[0]) == "3.00"
        assert pct(tienda, p, fecha=date(2027, 1, 1))[0] == 0
        servicios.actualizar(r, {"activa": False})
        assert pct(tienda, p, fecha=date(2026, 12, 15))[0] == 0

    def test_cambiar_una_regla_queda_con_el_antes_y_el_despues(self, tienda):
        r = regla(tienda, porcentaje="3")
        servicios.actualizar(r, {"porcentaje": "4,5"})
        evento = AuditoriaEvento.objects.get(accion="comisiones.regla_editada")
        assert evento.detalle["porcentaje"] == ["3.00", "4.50"]
        servicios.eliminar(r)
        assert not ReglaComision.objects.sin_ambito().exists()
        assert AuditoriaEvento.objects.filter(accion="comisiones.regla_eliminada").exists()


class TestApi:
    def test_el_administrador_crea_lista_cambia_y_borra(self, tienda):
        admin = cliente_de("admin")
        r = admin.post(BASE, {"alcance": "GENERAL", "porcentaje": "2.5"}, format="json")
        assert r.status_code == 201, r.content
        pk = r.json()["id"]
        assert r.json()["objetivo"] == "Cualquier venta"
        assert r.json()["vendedor_nombre"] == "Todos los vendedores"
        lista = admin.get(BASE).json()["results"]
        assert [x["id"] for x in lista] == [pk]
        r = admin.patch(f"{BASE}{pk}/", {"porcentaje": "3"}, format="json")
        assert r.status_code == 200 and r.json()["porcentaje"] == "3.00"
        assert admin.delete(f"{BASE}{pk}/").status_code == 204
        assert admin.get(BASE).json()["results"] == []

    def test_error_de_regla_responde_400(self, tienda):
        r = cliente_de("admin").post(
            BASE, {"alcance": "GENERAL", "porcentaje": "150"}, format="json"
        )
        assert r.status_code == 400

    def test_el_vendedor_no_ve_ni_define_reglas(self, tienda):
        v = cliente_de("vendedor")
        assert v.get(BASE).status_code == 403
        assert (
            v.post(BASE, {"alcance": "GENERAL", "porcentaje": "9"}, format="json").status_code
            == 403
        )

    def test_las_opciones_traen_marcas_categorias_y_vendedores(self, tienda):
        producto(tienda, "Galaxy", marca="Samsung")
        d = cliente_de("admin").get(f"{BASE}opciones/").json()
        assert [m["nombre"] for m in d["marcas"]] == ["Samsung"]
        assert d["categorias"]
        assert "vendedor" in [v["nombre"] for v in d["vendedores"]]

    def test_simular_explica_de_donde_sale_el_porcentaje(self, tienda):
        p = producto(tienda, "Galaxy", marca="Samsung")
        sin_regla = producto(tienda, "Cable")  # se crean antes: la API limpia el contexto
        regla(tienda, "MARCA", "1.5", marca=p.marca_id)
        admin = cliente_de("admin")
        d = admin.get(f"{BASE}simular/", {"producto": p.pk}).json()
        assert d["porcentaje"] == "1.50" and "Samsung" in d["texto"]
        d = admin.get(f"{BASE}simular/", {"producto": sin_regla.pk}).json()
        assert d["porcentaje"] in ("0", "0.00") and d["regla"] is None
        assert admin.get(f"{BASE}simular/").status_code == 400

    def test_exige_sesion(self, tienda):
        from rest_framework.test import APIClient

        assert APIClient().get(BASE).status_code in (401, 403)
