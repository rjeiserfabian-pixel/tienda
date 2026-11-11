"""Consulta pública por enlace y avisos automáticos por WhatsApp."""

from unittest import mock

import pytest
import requests
from django.conf import settings

from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import notificaciones, proveedores, publico, recepcion, servicios
from apps.servicio_tecnico.models import (
    ConfiguracionAvisos,
    EstadoNotificacion,
    EstadoOrden,
    EventoAviso,
    NotificacionServicio,
)
from apps.servicio_tecnico.tasks import enviar_notificacion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/servicio-tecnico"
E = EstadoOrden


def _recibir(taller, acepta=True, **extra):
    datos = {
        "empresa": taller.empresa,
        "cliente": taller.cliente,
        "equipo": recepcion.EquipoEntrada(existente=taller.equipo),
        "falla_reportada": "No enciende",
        "acepta_whatsapp": acepta,
    }
    datos.update(extra)
    return recepcion.recibir_equipo(**datos)


def _encender(taller, **campos):
    config, _ = ConfiguracionAvisos.objects.get_or_create(empresa=taller.empresa)
    config.whatsapp_activo = True
    for campo, valor in campos.items():
        setattr(config, campo, valor)
    config.save()


def _con_telefono(taller, numero="987 654 321"):
    taller.cliente.telefono = numero
    taller.cliente.save()


@pytest.fixture
def consola(settings):
    settings.WHATSAPP_PROVEEDOR = "consola"
    settings.SERVICIO_TECNICO_URL_PUBLICA = "https://taller.ejemplo.pe"


class TestTelefono:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("987 654 321", "51987654321"),
            ("+51 987-654-321", "51987654321"),
            ("0051987654321", "51987654321"),
            ("51987654321", "51987654321"),
            ("+1 305 555 0100", "13055550100"),
            ("12345", None),
            ("", None),
            ("abc", None),
            ("887654321", None),  # 9 dígitos que no son de celular peruano
        ],
    )
    def test_normaliza(self, texto, esperado):
        assert notificaciones.normalizar_telefono(texto) == esperado


class TestEstadoPublico:
    def test_se_ve_sin_iniciar_sesion_y_solo_lo_permitido(self, taller, api):
        orden = taller.orden(
            estado=E.EN_DIAGNOSTICO,
            nota_cliente="Estamos esperando una pieza.",
            nota_interna="Pedir a Lima, no decirle al cliente",
            diagnostico="Placa madre dañada",
            clave_equipo="clave-secreta",
        )
        r = api.get(f"{BASE}/publico/{orden.token_publico}/")
        assert r.status_code == 200, r.content
        cuerpo = r.content.decode()
        datos = r.json()
        assert datos["codigo"] == orden.codigo
        assert datos["estado"]["titulo"] == "En revisión"
        assert datos["equipo"] == "Laptop HP Pavilion"
        assert datos["mensaje_del_taller"] == "Estamos esperando una pieza."
        for secreto in (
            "Luis Ramos",
            "45871236",
            "5CD123",
            "Placa madre",
            "clave-secreta",
            "Pedir a Lima",
            "No enciende",
        ):
            assert secreto not in cuerpo, secreto
        assert r["Cache-Control"] == "no-store"
        assert "noindex" in r["X-Robots-Tag"]

    def test_un_enlace_que_no_existe_responde_siempre_lo_mismo(self, taller, api):
        orden = taller.orden()
        mensajes = {
            api.get(f"{BASE}/publico/{token}/").json()["error"]["mensaje"]
            for token in ("a" * 16, "mal formado!", "x", orden.token_publico + "z")
        }
        assert len(mensajes) == 1
        assert api.get(f"{BASE}/publico/{'a' * 16}/").status_code == 404

    def test_la_linea_de_tiempo_cuenta_el_camino_en_palabras_del_cliente(self, taller, api):
        orden = taller.orden(estado=E.TERMINADO)
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        datos = api.get(f"{BASE}/publico/{orden.token_publico}/").json()
        assert datos["estado"]["titulo"] == "Listo para recoger"
        assert [p["titulo"] for p in datos["linea_de_tiempo"]] == ["Listo para recoger"]
        assert datos["garantia"] is None

    def test_entregada_muestra_la_garantia_y_oculta_la_fecha_prometida(self, taller, api):
        import datetime

        orden = taller.orden(
            estado=E.ENTREGADO,
            garantia_dias=30,
            garantia_hasta=datetime.date(2030, 1, 31),
            fecha_promesa=datetime.date(2030, 1, 1),
        )
        datos = api.get(f"{BASE}/publico/{orden.token_publico}/").json()
        assert datos["garantia"] == {"dias": 30, "hasta": "2030-01-31"}
        assert datos["fecha_promesa"] is None

    def test_cada_estado_tiene_su_texto_para_el_cliente(self):
        assert set(publico.ETAPAS) == set(EstadoOrden.values)

    def test_el_token_malo_no_llega_a_la_base_de_datos(self, taller):
        with mock.patch.object(publico.OrdenServicio.objects, "sin_ambito") as consulta:
            assert publico.orden_por_token("no valido!") is None
            consulta.assert_not_called()


class TestEnlaceDelCliente:
    def test_el_enlace_lleva_a_la_tienda_y_se_puede_volver_al_panel(self, taller, settings):
        orden = _recibir(taller)
        tienda = settings.TIENDA_URL.rstrip("/")
        assert (
            notificaciones.url_publica(orden) == f"{tienda}/servicio-tecnico/{orden.token_publico}"
        )
        settings.SERVICIO_TECNICO_ENLACE_EN_TIENDA = False
        settings.SERVICIO_TECNICO_URL_PUBLICA = "https://taller.ejemplo.pe"
        assert (
            notificaciones.url_publica(orden)
            == f"https://taller.ejemplo.pe/estado/{orden.token_publico}"
        )


class TestAvisosAutomaticos:
    def test_al_recibir_el_equipo_se_avisa_y_sale(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        orden = _recibir(taller)
        aviso = NotificacionServicio.objects.get(orden=orden)
        assert (aviso.evento, aviso.estado) == (EventoAviso.RECIBIDO, EstadoNotificacion.ENVIADO)
        assert aviso.telefono == "51987654321" and aviso.externo_id == "consola"
        assert orden.codigo in aviso.mensaje
        assert (
            f"{settings.TIENDA_URL.rstrip('/')}/servicio-tecnico/{orden.token_publico}"
            in aviso.mensaje
        )
        assert aviso.enviado_en is not None

    def test_el_mensaje_no_lleva_precios_ni_diagnostico(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        orden = _recibir(taller)
        orden.diagnostico = "Placa madre dañada"
        for evento in EventoAviso.values:
            texto = notificaciones.texto_del_aviso(evento, orden)
            assert "S/" not in texto and "Placa" not in texto and "Ramos" not in texto
            assert texto.startswith("Hola Luis")

    def test_sin_consentimiento_o_con_el_aviso_apagado_no_se_manda(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        _recibir(taller, acepta=False)
        _encender(taller, aviso_recibido=False)
        _recibir(taller)
        ConfiguracionAvisos.objects.filter(empresa=taller.empresa).update(whatsapp_activo=False)
        _recibir(taller)
        assert NotificacionServicio.objects.count() == 0

    def test_por_defecto_todo_esta_apagado(self, taller, consola):
        _con_telefono(taller)
        _recibir(taller)
        assert NotificacionServicio.objects.count() == 0

    def test_sin_telefono_valido_queda_como_no_enviado(self, taller, consola):
        _con_telefono(taller, "12")
        _encender(taller)
        aviso = NotificacionServicio.objects.get(orden=_recibir(taller))
        assert aviso.estado == EstadoNotificacion.OMITIDO and "teléfono" in aviso.detalle

    def test_con_el_proveedor_apagado_no_se_envia(self, taller, settings):
        settings.WHATSAPP_PROVEEDOR = "apagado"
        _con_telefono(taller)
        _encender(taller)
        aviso = NotificacionServicio.objects.get(orden=_recibir(taller))
        assert aviso.estado == EstadoNotificacion.OMITIDO and "apagados" in aviso.detalle

    def test_los_cambios_de_estado_avisan_una_sola_vez_por_evento(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        orden = taller.orden(estado=E.TERMINADO, acepta_whatsapp=True)
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        assert [n.evento for n in NotificacionServicio.objects.filter(orden=orden)] == ["LISTO"]
        # La orden vuelve a pasar por «listo» y no se le repite el aviso.
        notificaciones.avisar_por_estado(orden, E.LISTO_ENTREGA)
        assert NotificacionServicio.objects.filter(orden=orden).count() == 1

    def test_un_rechazo_definitivo_queda_como_fallido(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        with mock.patch.object(
            proveedores.ProveedorConsola,
            "enviar",
            side_effect=proveedores.ErrorProveedor("Número no registrado en WhatsApp"),
        ):
            aviso = NotificacionServicio.objects.get(orden=_recibir(taller))
        assert aviso.estado == EstadoNotificacion.FALLIDO
        assert aviso.detalle == "Número no registrado en WhatsApp"

    def test_al_agotar_los_reintentos_queda_como_fallido(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        aviso = NotificacionServicio.objects.get(orden=_recibir(taller))
        aviso.estado, aviso.intentos = EstadoNotificacion.PENDIENTE, 3
        aviso.save()
        with mock.patch.object(
            proveedores.ProveedorConsola, "enviar", side_effect=proveedores.ErrorTemporal("caído")
        ):
            assert enviar_notificacion.run(aviso.pk) == "fallido"
        aviso.refresh_from_db()
        assert aviso.estado == EstadoNotificacion.FALLIDO and "reintentos" in aviso.detalle

    def test_un_aviso_ya_enviado_no_se_manda_dos_veces(self, taller, consola):
        _con_telefono(taller)
        _encender(taller)
        aviso = NotificacionServicio.objects.get(orden=_recibir(taller))
        with mock.patch.object(proveedores.ProveedorConsola, "enviar") as envio:
            assert enviar_notificacion.run(aviso.pk) == "omitido"
            envio.assert_not_called()

    def test_el_reingreso_hereda_el_consentimiento(self, banco, settings):
        from apps.servicio_tecnico import garantia
        from apps.servicio_tecnico.tests.test_garantia import _entregar, _terminada

        original = _terminada(banco, (banco.ram, 1), acepta_whatsapp=True)
        _entregar(banco, original)
        nueva = garantia.reingreso_por_garantia(original, falla_reportada="Vuelve a fallar")
        assert nueva.acepta_whatsapp is True


class TestProveedorMeta:
    @pytest.fixture(autouse=True)
    def _config(self, settings):
        settings.WHATSAPP_PROVEEDOR = "meta"
        settings.WHATSAPP_META_TOKEN = "token-super-secreto"
        settings.WHATSAPP_META_TELEFONO_ID = "1234567890"
        settings.WHATSAPP_PLANTILLAS = {"RECIBIDO": "orden_recibida"}

    def _mensaje(self):
        return proveedores.Mensaje(
            "51987654321", "RECIBIDO", "texto", ("Luis", "OS-000001", "https://x")
        )

    def _respuesta(self, codigo, cuerpo=None):
        r = mock.Mock(status_code=codigo)
        r.json.return_value = cuerpo or {}
        return r

    def test_envia_la_plantilla_con_sus_parametros_y_el_tiempo_limite(self, settings):
        ok = self._respuesta(200, {"messages": [{"id": "wamid.ABC"}]})
        with mock.patch("requests.post", return_value=ok) as post:
            assert proveedores.ProveedorMeta().enviar(self._mensaje()) == "wamid.ABC"
        _, kwargs = post.call_args
        cuerpo = kwargs["json"]
        assert cuerpo["to"] == "51987654321" and cuerpo["template"]["name"] == "orden_recibida"
        parametros = cuerpo["template"]["components"][0]["parameters"]
        assert [p["text"] for p in parametros] == ["Luis", "OS-000001", "https://x"]
        assert kwargs["timeout"] == settings.WHATSAPP_TIMEOUT
        assert kwargs["headers"]["Authorization"] == "Bearer token-super-secreto"

    def test_los_fallos_pasajeros_se_reintentan(self):
        for respuesta in (self._respuesta(429), self._respuesta(503)):
            with (
                mock.patch("requests.post", return_value=respuesta),
                pytest.raises(proveedores.ErrorTemporal),
            ):
                proveedores.ProveedorMeta().enviar(self._mensaje())
        with (
            mock.patch("requests.post", side_effect=requests.Timeout("lento")),
            pytest.raises(proveedores.ErrorTemporal),
        ):
            proveedores.ProveedorMeta().enviar(self._mensaje())

    def test_un_rechazo_no_se_reintenta_y_no_revela_el_token(self):
        rechazo = self._respuesta(400, {"error": {"message": "Plantilla no aprobada"}})
        with mock.patch("requests.post", return_value=rechazo):
            with pytest.raises(proveedores.ErrorProveedor, match="Plantilla no aprobada") as error:
                proveedores.ProveedorMeta().enviar(self._mensaje())
        assert "token-super-secreto" not in str(error.value)

    def test_dice_que_falta_para_poder_enviar(self, settings):
        meta = proveedores.ProveedorMeta()
        assert meta.falta("RECIBIDO") == ""
        assert "plantilla" in meta.falta("LISTO")
        settings.WHATSAPP_META_TOKEN = ""
        assert "token" in meta.falta("RECIBIDO")

    def test_sin_plantilla_el_aviso_queda_como_no_enviado(self, taller):
        _con_telefono(taller)
        _encender(taller, aviso_listo=True)
        orden = taller.orden(estado=E.TERMINADO, acepta_whatsapp=True)
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        aviso = NotificacionServicio.objects.get(orden=orden)
        assert aviso.estado == EstadoNotificacion.OMITIDO and "plantilla" in aviso.detalle


class TestApi:
    def test_configuracion_de_avisos(self, taller, settings):
        settings.WHATSAPP_PROVEEDOR = "apagado"
        api = cliente_de("admin")
        base = {"empresa": taller.empresa.pk}
        r = api.get(f"{BASE}/avisos/configuracion/", base)
        assert r.status_code == 200, r.content
        assert r.json()["configuracion"]["whatsapp_activo"] is False
        assert r.json()["proveedor"]["nombre"] == "apagado"
        r = api.put(
            f"{BASE}/avisos/configuracion/?empresa={taller.empresa.pk}",
            {"whatsapp_activo": True, "aviso_entregado": True},
            format="json",
        )
        assert r.status_code == 200
        assert r.json()["configuracion"]["whatsapp_activo"] is True
        assert (
            api.get(f"{BASE}/avisos/configuracion/", base).json()["configuracion"][
                "aviso_entregado"
            ]
            is True
        )

    def test_solo_quien_gestiona_los_avisos(self, taller):
        for usuario in ("tecnico", "vendedor"):
            api = cliente_de(usuario)
            assert (
                api.get(f"{BASE}/avisos/configuracion/", {"empresa": taller.empresa.pk}).status_code
                == 403
            )

    def test_recibir_con_consentimiento_y_ver_el_enlace_y_el_numero(self, taller):
        taller.cliente.telefono = "987654321"
        taller.cliente.save()
        from apps.servicio_tecnico.models import TipoEquipo

        tipo = TipoEquipo.objects.get(codigo="PC").pk
        cuerpo = {
            "empresa": taller.empresa.pk,
            "cliente": taller.cliente.pk,
            "equipo": {"tipo": tipo, "marca": "Dell", "modelo": "Optiplex"},
            "falla_reportada": "No da video",
            "acepta_whatsapp": True,
        }
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/", cuerpo, format="json", HTTP_IDEMPOTENCY_KEY="clave-aviso-0001"
        )
        assert r.status_code == 201, r.content
        datos = r.json()
        assert datos["acepta_whatsapp"] is True
        assert datos["whatsapp"]["numero"] == "51987654321"
        assert "OS-000001" in datos["whatsapp"]["mensaje"]
        assert "/servicio-tecnico/" in datos["url_publica"]  # el enlace lleva a la tienda
        assert datos["notificaciones"] == []  # los avisos automáticos están apagados
