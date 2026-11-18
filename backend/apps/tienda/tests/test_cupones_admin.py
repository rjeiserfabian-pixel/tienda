"""Panel de cupones: crear, validar, pausar, ver su uso y aislamiento entre organizaciones."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda.models import Cupon, UsoCupon

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_cupones import CODIGO, hacer_cupon, mouse, pedir
from .test_pagar import cobra, culqi_falso  # noqa: F401
from .test_pedidos import vende  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/tienda/admin/cupones/"


def datos(**extra):
    return {"codigo": "navidad10", "tipo": "PORCENTAJE", "valor": "10", **extra}


class TestPermisos:
    def test_solo_quien_gestiona_ofertas(self, tienda):
        assert cliente_de("admin").get(URL).status_code == 200
        assert cliente_de("vendedor").get(URL).status_code == 403
        assert cliente_de("almacenero").post(URL, datos(), format="json").status_code == 403
        assert APIClient().get(URL).status_code == 401

    def test_otra_organizacion_no_ve_ni_toca_estos_cupones(self, tienda):
        cupon = hacer_cupon(tienda)
        otra = cliente_de("otra_org")
        assert otra.get(URL).json()["count"] == 0
        assert otra.get(f"{URL}{cupon.pk}/").status_code == 404
        assert otra.patch(f"{URL}{cupon.pk}/", {"activo": False}, format="json").status_code == 404
        assert otra.delete(f"{URL}{cupon.pk}/").status_code == 404


class TestCrear:
    def test_crea_y_normaliza_el_codigo(self, tienda):
        r = cliente_de("admin").post(
            URL, datos(compra_minima="100", usos_maximos=50), format="json"
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["codigo"] == "NAVIDAD10" and d["estado"] == "VIGENTE" and d["usos"] == 0
        assert d["compra_minima"] == "100.00" and d["usos_maximos"] == 50
        assert d["incluye_ofertas"] is False  # de fábrica no se combina con ofertas

    @pytest.mark.parametrize(
        ("extra", "texto"),
        [
            ({"valor": "0"}, "entre 1 y 100"),
            ({"valor": "150"}, "entre 1 y 100"),
            ({"tipo": "MONTO", "valor": "0"}, "mayor que cero"),
            ({"codigo": "a b!"}, "solo puede tener"),
            ({"codigo": "ab"}, "solo puede tener"),
            (
                {
                    "inicia_en": (timezone.now() + timedelta(days=2)).isoformat(),
                    "termina_en": (timezone.now() + timedelta(days=1)).isoformat(),
                },
                "posterior",
            ),
            ({"alcance": "PRODUCTOS"}, "al menos un elemento"),
            ({"alcance": "MARCAS", "marcas": [999999]}, "marcas de tu tienda"),
        ],
    )
    def test_validaciones(self, tienda, extra, texto):
        r = cliente_de("admin").post(URL, datos(**extra), format="json")
        assert r.status_code == 400 and texto in str(r.json()), r.content
        assert Cupon.objects.sin_ambito().count() == 0  # nada queda a medias

    def test_no_repite_codigos(self, tienda):
        c = cliente_de("admin")
        assert c.post(URL, datos(), format="json").status_code == 201
        r = c.post(URL, datos(codigo="NAVIDAD10"), format="json")
        assert r.status_code == 400 and "Ya tienes" in str(r.json())

    def test_el_envio_gratis_ignora_el_valor_y_el_tope(self, tienda):
        r = cliente_de("admin").post(
            URL, datos(tipo="ENVIO_GRATIS", valor="50", tope_descuento="5"), format="json"
        )
        assert r.status_code == 201
        assert r.json()["valor"] == "0.00" and r.json()["tope_descuento"] is None

    def test_alcance_por_marca(self, tienda):
        c = cliente_de("admin")
        opciones = c.get(URL + "opciones/").json()
        marca = opciones["marcas"][0]["id"]
        r = c.post(URL, datos(alcance="MARCAS", marcas=[marca]), format="json")
        assert r.status_code == 201 and r.json()["marcas"][0]["id"] == marca


class TestGestionar:
    def test_pausar_editar_y_estados(self, tienda):
        c = cliente_de("admin")
        cupon = c.post(URL, datos(), format="json").json()
        r = c.patch(f"{URL}{cupon['id']}/", {"activo": False, "valor": "15"}, format="json")
        assert (
            r.status_code == 200
            and r.json()["estado"] == "PAUSADO"
            and r.json()["valor"] == "15.00"
        )
        r = c.patch(f"{URL}{cupon['id']}/", {"activo": True}, format="json")
        assert r.json()["estado"] == "VIGENTE"
        pasado = {"termina_en": (timezone.now() - timedelta(days=1)).isoformat(), "inicia_en": None}
        assert c.patch(f"{URL}{cupon['id']}/", pasado, format="json").json()["estado"] == "VENCIDO"

    def test_se_borra_solo_si_nunca_se_uso(self, vende):
        c = cliente_de("admin")
        libre = c.post(URL, datos(), format="json").json()
        assert c.delete(f"{URL}{libre['id']}/").status_code == 204
        assert c.get(f"{URL}{libre['id']}/").status_code == 404
        usado = hacer_cupon(vende)
        pedir(vende, registrada(), mouse(vende), cantidad=1, cupon=CODIGO)
        r = c.delete(f"{URL}{usado.pk}/")
        assert r.status_code == 400 and "pausa el cupón" in str(r.json())

    def test_el_uso_se_ve_en_la_lista_y_en_el_detalle_de_usos(self, cobra, culqi_falso):
        from .test_pagar import pagar_pedido
        from .test_pedidos import contexto

        hacer_cupon(cobra)
        contexto(cobra)
        p = cobra.publicar("Mouse", costo=Decimal("40"), precio=100, stock=10)
        cliente = registrada("ana@ejemplo.pe")
        contexto(cobra)
        numero = pedir(cobra, cliente, p, cantidad=1, cupon=CODIGO).json()["numero"]
        admin = cliente_de("admin")
        fila = admin.get(URL).json()["results"][0]
        assert fila["usos"] == 1 and fila["usos_pagados"] == 0 and fila["descontado"] == "0.00"
        assert pagar_pedido(cliente, numero).status_code == 200
        fila = admin.get(URL).json()["results"][0]
        assert fila["usos_pagados"] == 1 and fila["descontado"] == "23.60"
        usos = admin.get(f"{URL}{fila['id']}/usos/").json()["results"]
        assert usos[0]["pedido"] == numero and usos[0]["cliente"] == "ana@ejemplo.pe"
        assert usos[0]["estado"] == "CONSUMIDO" and UsoCupon.objects.sin_ambito().count() == 1

    def test_un_cupon_agotado(self, vende):
        cupon = hacer_cupon(vende, usos_maximos=1)
        pedir(vende, registrada(), mouse(vende), cantidad=1, cupon=CODIGO)
        assert cliente_de("admin").get(f"{URL}{cupon.pk}/").json()["estado"] == "AGOTADO"
