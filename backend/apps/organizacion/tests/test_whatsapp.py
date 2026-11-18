"""WhatsApp Business: la cuenta de Meta se configura desde el panel (token cifrado)."""

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.organizacion.models import ConfiguracionWhatsApp
from apps.organizacion.services.creacion import crear_organizacion_con_empresa
from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import proveedores
from conftest import ruc_valido

pytestmark = pytest.mark.django_db

URL = "/api/v1/organizacion/whatsapp/"
PROBAR = URL + "probar/"
TOKEN = "EAAGtokenSUPERsecreto1234567890"


@pytest.fixture
def mundo(nuevo_usuario):
    creada = crear_organizacion_con_empresa(
        nombre_organizacion="Grupo Demo", razon_social="Demo SAC", ruc=ruc_valido("2012345678")
    )
    nuevo_usuario(creada.organizacion, "dueno", [creada.empresa], [("SUPERADMIN", None)])
    nuevo_usuario(creada.organizacion, "vendedor", [creada.empresa], [("VENDEDOR", creada.empresa)])
    return creada


def completo(c, **extra):
    datos = {
        "telefono_id": "1234567890",
        "token": TOKEN,
        "numero": "987654321",
        "plantillas": {"PEDIDO_PAGADO": "pedido_pagado"},
        **extra,
    }
    return c.patch(URL, datos, format="json")


class TestPermisos:
    def test_solo_quien_gestiona_la_organizacion(self, mundo):
        assert cliente_de("dueno").get(URL).status_code == 200
        assert cliente_de("vendedor").get(URL).status_code == 403
        assert cliente_de("vendedor").patch(URL, {}, format="json").status_code == 403
        assert APIClient().get(URL).status_code == 401


class TestConfiguracion:
    def test_de_inicio_esta_apagado_y_trae_el_catalogo_de_avisos(self, mundo):
        r = cliente_de("dueno").get(URL).json()
        assert r["modo"] == "APAGADO" and r["tiene_token"] is False
        claves = {e["clave"] for e in r["eventos"]}
        assert {"RECIBIDO", "PEDIDO_PAGADO", "PEDIDO_ENVIADO"} <= claves
        assert all("{{1}}" in e["texto_sugerido"] for e in r["eventos"])

    def test_el_token_se_guarda_y_nunca_se_devuelve(self, mundo):
        c = cliente_de("dueno")
        r = completo(c)
        assert r.status_code == 200, r.content
        assert TOKEN not in r.content.decode()
        assert r.json()["tiene_token"] is True and r.json()["token_final"] == TOKEN[-4:]
        assert TOKEN not in c.get(URL).content.decode()
        assert ConfiguracionWhatsApp.objects.sin_ambito().get().token == TOKEN

    def test_no_se_activa_sin_los_datos_necesarios(self, mundo):
        c = cliente_de("dueno")
        r = c.patch(URL, {"modo": "ACTIVO"}, format="json")
        assert r.status_code == 400
        assert "modo" in r.json() or "modo" in str(r.json())

    def test_se_activa_con_todo_y_se_apaga_si_se_quita_el_token(self, mundo):
        c = cliente_de("dueno")
        assert completo(c, modo="ACTIVO").json()["modo"] == "ACTIVO"
        r = c.patch(URL, {"quitar_token": True}, format="json")
        assert r.json()["modo"] == "APAGADO" and r.json()["tiene_token"] is False

    def test_valida_las_plantillas(self, mundo):
        c = cliente_de("dueno")
        assert c.patch(URL, {"plantillas": {"INVENTADO": "x"}}, format="json").status_code == 400
        malo = {"plantillas": {"PEDIDO_PAGADO": "Pedido Pagado!"}}
        assert c.patch(URL, malo, format="json").status_code == 400

    def test_el_token_no_queda_en_la_auditoria(self, mundo):
        from apps.auditoria.models import AuditoriaEvento as EventoAuditoria

        completo(cliente_de("dueno"))
        for evento in EventoAuditoria.objects.all():
            assert TOKEN not in str(evento.detalle)


class TestProveedor:
    def test_sin_configuracion_manda_el_servidor_como_antes(self, mundo, settings):
        settings.WHATSAPP_PROVEEDOR = "consola"
        assert proveedores.obtener(mundo.organizacion.pk).nombre == "consola"
        assert proveedores.obtener().nombre == "consola"

    def test_lo_guardado_en_el_panel_manda_sobre_el_servidor(self, mundo, settings):
        settings.WHATSAPP_PROVEEDOR = "meta"
        c = cliente_de("dueno")
        org = mundo.organizacion.pk
        c.patch(URL, {"modo": "APAGADO"}, format="json")
        assert proveedores.obtener(org).nombre == "apagado"
        c.patch(URL, {"modo": "PRUEBA"}, format="json")
        assert proveedores.obtener(org).nombre == "consola"
        completo(c, modo="ACTIVO")
        meta = proveedores.obtener(org)
        assert meta.nombre == "meta" and meta.configurado()
        assert meta._plantilla("PEDIDO_PAGADO") == "pedido_pagado"

    def test_el_mensaje_usa_la_cuenta_del_panel(self, mundo):
        c = cliente_de("dueno")
        completo(c, modo="ACTIVO", version_api="v20.0")
        meta = proveedores.obtener(mundo.organizacion.pk)
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"messages": [{"id": "wamid.X"}]}
        with mock.patch("apps.servicio_tecnico.proveedores.requests.post") as post:
            post.return_value = respuesta
            externo = meta.enviar(
                proveedores.Mensaje(
                    "51987654321", "PEDIDO_PAGADO", "t", ("Ana", "T-1", "https://x")
                )
            )
        assert externo == "wamid.X"
        url = post.call_args.args[0]
        assert url == "https://graph.facebook.com/v20.0/1234567890/messages"
        assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        cuerpo = post.call_args.kwargs["json"]
        assert cuerpo["template"]["name"] == "pedido_pagado"
        assert len(cuerpo["template"]["components"][0]["parameters"]) == 3


class TestProbar:
    def test_en_modo_prueba_se_simula(self, mundo):
        c = cliente_de("dueno")
        c.patch(URL, {"modo": "PRUEBA"}, format="json")
        r = c.post(PROBAR, {"telefono": "987 654 321"}, format="json")
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_apagado_pide_encenderlo(self, mundo):
        r = cliente_de("dueno").post(PROBAR, {"telefono": "987654321"}, format="json")
        assert r.status_code == 400

    def test_telefono_invalido(self, mundo):
        c = cliente_de("dueno")
        c.patch(URL, {"modo": "PRUEBA"}, format="json")
        assert c.post(PROBAR, {"telefono": "12"}, format="json").status_code == 400

    def test_con_meta_usa_la_plantilla_de_fabrica_sin_variables(self, mundo):
        c = cliente_de("dueno")
        completo(c, modo="ACTIVO")
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"messages": [{"id": "wamid.P"}]}
        with mock.patch("apps.servicio_tecnico.proveedores.requests.post") as post:
            post.return_value = respuesta
            r = c.post(PROBAR, {"telefono": "987654321"}, format="json")
        assert r.json() == {"ok": True, "mensaje": "Mensaje enviado.", "referencia": "wamid.P"}
        cuerpo = post.call_args.kwargs["json"]
        assert cuerpo["template"]["name"] == "hello_world"
        assert cuerpo["template"]["language"]["code"] == "en_US"
        assert "components" not in cuerpo["template"]
        assert TOKEN not in r.content.decode()
