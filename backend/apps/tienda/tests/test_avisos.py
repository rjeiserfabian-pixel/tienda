"""Avisos de pedido: correo y WhatsApp con su registro (bandeja de salida)."""

# ruff: noqa: F811

from unittest import mock

import pytest
from django.core import mail

from apps.organizacion.models import ConfiguracionWhatsApp
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import avisos
from apps.tienda.models import AvisoPedido, CuentaCliente, PedidoTienda

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso  # noqa: F401
from .test_pedidos import vende  # noqa: F401
from .test_pedidos_admin import ADMIN, estado, pagado

pytestmark = pytest.mark.django_db

CORREO = AvisoPedido.Canal.CORREO
WHATSAPP = AvisoPedido.Canal.WHATSAPP
TOKEN = "EAAGtokenSUPERsecreto1234567890"


def aviso(numero, evento, canal):
    return (
        AvisoPedido.objects.sin_ambito()
        .filter(pedido__numero=numero, evento=evento, canal=canal)
        .first()
    )


def cuenta_acepta_whatsapp(correo="ana@ejemplo.pe", celular=None):
    cambios = {"acepta_whatsapp": True}
    if celular is not None:
        cambios["celular"] = celular
    CuentaCliente.objects.sin_ambito().filter(correo=correo).update(**cambios)


def whatsapp_activo(org, **plantillas):
    return ConfiguracionWhatsApp.objects.sin_ambito().create(
        organizacion_id=org.pk,
        modo="ACTIVO",
        telefono_id="1234567890",
        token=TOKEN,
        plantillas=plantillas or {"PEDIDO_PREPARACION": "pedido_preparacion"},
    )


class TestCorreo:
    def test_cada_cambio_de_estado_deja_su_aviso_anotado(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"))
        # el correo de confirmación ya existía: ahora además queda anotado
        pagado_ = aviso(numero, "PEDIDO_PAGADO", CORREO)
        assert pagado_ is not None and pagado_.estado == "ENVIADO"
        admin = cliente_de("admin")
        n = len(mail.outbox)
        assert estado(admin, numero, "EN_PREPARACION").status_code == 200
        assert len(mail.outbox) == n + 1 and "preparando" in mail.outbox[-1].body
        assert aviso(numero, "PEDIDO_PREPARACION", CORREO).estado == "ENVIADO"
        assert estado(admin, numero, "ENVIADO", seguimiento="Olva 1").status_code == 200
        assert aviso(numero, "PEDIDO_ENVIADO", CORREO).estado == "ENVIADO"
        n = len(mail.outbox)
        assert estado(admin, numero, "ENTREGADO").status_code == 200
        assert len(mail.outbox) == n + 1 and "entregado" in mail.outbox[-1].subject
        assert aviso(numero, "PEDIDO_ENTREGADO", CORREO).estado == "ENVIADO"

    def test_cancelar_avisa_al_cliente(self, vende):
        from .test_pedidos_admin import hacer_pedido

        _, p = hacer_pedido(vende, registrada("ana@ejemplo.pe"), "Mouse C")
        n = len(mail.outbox)
        assert estado(cliente_de("admin"), p["numero"], "CANCELADO").status_code == 200
        assert len(mail.outbox) == n + 1 and "cancelado" in mail.outbox[-1].subject
        assert aviso(p["numero"], "PEDIDO_CANCELADO", CORREO).estado == "ENVIADO"

    def test_un_aviso_no_se_repite(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"))
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        n = len(mail.outbox)
        assert avisos.procesar(pedido.pk, "PEDIDO_PREPARACION") == []
        assert len(mail.outbox) == n
        assert AvisoPedido.objects.sin_ambito().filter(evento="PEDIDO_PREPARACION").count() == 1

    def test_un_correo_caido_no_rompe_el_cambio_de_estado(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"))
        with mock.patch("apps.tienda.avisos.send_mail", side_effect=OSError("sin red")):
            r = estado(cliente_de("admin"), numero, "EN_PREPARACION")
        assert r.status_code == 200 and r.json()["estado"] == "EN_PREPARACION"
        a = aviso(numero, "PEDIDO_PREPARACION", CORREO)
        assert a.estado == "FALLIDO" and "sin red" not in a.detalle


class TestWhatsApp:
    def test_si_el_cliente_no_acepto_no_se_anota_nada(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"))
        whatsapp_activo(cobra.org)
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        assert aviso(numero, "PEDIDO_PREPARACION", WHATSAPP) is None

    def test_sin_cuenta_de_whatsapp_queda_como_no_enviado_con_el_motivo(self, cobra, culqi_falso):
        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp()
        numero = pagado(cobra, c)
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        a = aviso(numero, "PEDIDO_PREPARACION", WHATSAPP)
        assert a.estado == "OMITIDO" and "WhatsApp" in a.detalle
        assert a.destino.endswith("321") and "987654" not in a.destino  # no se muestra entero

    def test_sin_celular_valido_queda_como_no_enviado(self, cobra, culqi_falso):
        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp(celular="12")
        numero = pagado(cobra, c)
        whatsapp_activo(cobra.org)
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        a = aviso(numero, "PEDIDO_PREPARACION", WHATSAPP)
        assert a.estado == "OMITIDO" and "celular" in a.detalle

    def test_en_modo_prueba_se_simula(self, cobra, culqi_falso):
        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp()
        ConfiguracionWhatsApp.objects.sin_ambito().create(
            organizacion_id=cobra.org.pk, modo="PRUEBA"
        )
        numero = pagado(cobra, c)
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        assert aviso(numero, "PEDIDO_PREPARACION", WHATSAPP).estado == "ENVIADO"

    def test_con_la_cuenta_activa_se_envia_con_la_plantilla_y_los_tres_datos(
        self, cobra, culqi_falso
    ):
        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp()
        whatsapp_activo(cobra.org)
        numero = pagado(cobra, c)
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"messages": [{"id": "wamid.OK"}]}
        with mock.patch("apps.servicio_tecnico.proveedores.requests.post") as post:
            post.return_value = respuesta
            estado(cliente_de("admin"), numero, "EN_PREPARACION")
        a = aviso(numero, "PEDIDO_PREPARACION", WHATSAPP)
        assert a.estado == "ENVIADO" and a.externo_id == "wamid.OK" and a.enviado_en
        cuerpo = post.call_args.kwargs["json"]
        assert cuerpo["to"] == "51987654321"
        assert cuerpo["template"]["name"] == "pedido_preparacion"
        nombre, pedido, enlace = (
            p["text"] for p in cuerpo["template"]["components"][0]["parameters"]
        )
        assert pedido == numero and nombre == "Ana"
        assert enlace.endswith(f"/cuenta/pedidos/{numero}")
        assert TOKEN not in str(a.detalle)

    def test_falta_la_plantilla_de_ese_aviso(self, cobra, culqi_falso):
        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp()
        whatsapp_activo(cobra.org, PEDIDO_ENVIADO="pedido_enviado")  # no tiene la de preparación
        numero = pagado(cobra, c)
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        a = aviso(numero, "PEDIDO_PREPARACION", WHATSAPP)
        assert a.estado == "OMITIDO" and "plantilla" in a.detalle

    def test_un_fallo_pasajero_se_reintenta_y_uno_definitivo_se_cierra(self, cobra, culqi_falso):
        from apps.servicio_tecnico import proveedores

        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp()
        whatsapp_activo(cobra.org)
        numero = pagado(cobra, c)
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        nuevo = avisos.preparar_whatsapp(pedido, "PEDIDO_PREPARACION")
        assert nuevo is not None and nuevo.estado == "PENDIENTE"
        with mock.patch(
            "apps.servicio_tecnico.proveedores.requests.post",
            side_effect=proveedores.requests.RequestException,
        ):
            with pytest.raises(proveedores.ErrorTemporal):
                avisos.mandar_whatsapp(nuevo.pk)
        nuevo.refresh_from_db()
        assert nuevo.estado == "PENDIENTE" and nuevo.intentos == 1
        malo = mock.Mock(status_code=400)
        malo.json.return_value = {"error": {"message": "Número inexistente"}}
        with mock.patch("apps.servicio_tecnico.proveedores.requests.post", return_value=malo):
            assert avisos.mandar_whatsapp(nuevo.pk) == "fallido"
        nuevo.refresh_from_db()
        assert nuevo.estado == "FALLIDO" and "inexistente" in nuevo.detalle
        assert avisos.mandar_whatsapp(nuevo.pk) == "omitido"  # ya cerrado: no se reenvía


class TestPanelYCuenta:
    def test_el_detalle_del_pedido_trae_los_avisos_y_el_enlace_manual(self, cobra, culqi_falso):
        c = registrada("ana@ejemplo.pe")
        cuenta_acepta_whatsapp()
        numero = pagado(cobra, c)
        estado(cliente_de("admin"), numero, "EN_PREPARACION")
        d = cliente_de("admin").get(f"{ADMIN}/{numero}/").json()
        eventos = {(a["evento"], a["canal"]) for a in d["avisos"]}
        assert ("PEDIDO_PAGADO", "CORREO") in eventos
        assert ("PEDIDO_PREPARACION", "CORREO") in eventos
        assert ("PEDIDO_PREPARACION", "WHATSAPP") in eventos
        assert d["cliente"]["acepta_whatsapp"] is True
        manual = d["whatsapp_manual"]
        assert manual["telefono"] == "51987654321"
        assert manual["url"].startswith("https://wa.me/51987654321?text=")
        assert numero in manual["url"]

    def test_sin_celular_valido_no_hay_enlace_manual(self, cobra, culqi_falso):
        c = registrada("ana@ejemplo.pe")
        CuentaCliente.objects.sin_ambito().update(celular="")
        numero = pagado(cobra, c)
        d = cliente_de("admin").get(f"{ADMIN}/{numero}/").json()
        assert d["whatsapp_manual"] is None

    def test_el_cliente_elige_si_acepta_whatsapp(self, tienda):
        c = registrada("ana@ejemplo.pe")
        assert c.get("/api/v1/tienda/cuenta/perfil").json()["acepta_whatsapp"] is False
        r = c.patch("/api/v1/tienda/cuenta/perfil", {"acepta_whatsapp": True}, format="json")
        assert r.status_code == 200 and r.json()["acepta_whatsapp"] is True
        assert CuentaCliente.objects.sin_ambito().get().acepta_whatsapp is True
