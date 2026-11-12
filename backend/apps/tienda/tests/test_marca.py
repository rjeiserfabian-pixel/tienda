"""Marca, contacto, textos y logo propio de la tienda: panel (admin) y lectura pública."""

# ruff: noqa: F811

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.organizacion.models import Empresa
from apps.seguridad.tests.conftest import cliente_de

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/configuracion/"
LOGO_ADMIN = "/api/v1/tienda/admin/logo/"
PUBLICA = "/api/v1/tienda/configuracion/"


def _logo(formato="PNG", color=(10, 90, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (120, 40), color).save(buffer, format=formato)
    return SimpleUploadedFile("logo." + formato.lower(), buffer.getvalue())


def _publica():
    return APIClient().get(PUBLICA)


class TestContenido:
    def test_guarda_contacto_y_textos_y_lo_muestra_la_parte_publica(self, tienda):
        r = cliente_de("admin").patch(
            ADMIN,
            {
                "whatsapp": "987 654 321",
                "correo": "ventas@ejemplo.pe",
                "horario": "Lunes a sábado, 9 a 7",
                "portada_titulo": "Todo para tu oficina",
                "avisos": ["Envío a todo el país", "  ", "Garantía real"],
                "servicio_visible": True,
                "servicio_puntos": ["Diagnóstico claro"],
                "color_principal": "#1a56db",
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        d = _publica().json()
        assert d["contacto"]["whatsapp"] == "51987654321"  # se completa el código de país
        assert d["contacto"]["correo"] == "ventas@ejemplo.pe"
        assert d["portada"]["titulo"] == "Todo para tu oficina"
        assert d["avisos"] == ["Envío a todo el país", "Garantía real"]
        assert d["servicio"] == {
            "visible": True,
            "titulo": None,
            "texto": None,
            "puntos": ["Diagnóstico claro"],
        }
        assert d["color"] == "#1A56DB"

    def test_lo_vacio_se_toma_de_la_ficha_de_la_empresa_principal(self, tienda):
        Empresa.objects.sin_ambito().filter(pk=tienda.e.e1.pk).update(
            es_principal=True, telefono="014445555", direccion_fiscal="Av. Lima 123"
        )
        d = _publica().json()
        assert d["contacto"]["telefono"] == "014445555"
        assert d["contacto"]["direccion"] == "Av. Lima 123"
        assert d["legal"]["ruc"] == tienda.e.e1.ruc
        assert d["contacto"]["whatsapp"] is None  # el WhatsApp no se inventa
        cliente_de("admin").patch(ADMIN, {"telefono": "999111222"}, format="json")
        assert _publica().json()["contacto"]["telefono"] == "999111222"

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("facebook", "javascript:alert(1)"),
            ("mapa_url", "no es un enlace"),
            ("correo", "sin-arroba"),
            ("whatsapp", "123"),
            ("color_principal", "rojo"),
            ("color_principal", "#FFFF99"),  # muy claro: el texto blanco no se leería
            ("avisos", ["a", "b", "c", "d"]),
        ],
    )
    def test_rechaza_valores_invalidos(self, tienda, campo, valor):
        r = cliente_de("admin").patch(ADMIN, {campo: valor}, format="json")
        assert r.status_code == 400, r.content

    def test_el_vendedor_no_cambia_nada(self, tienda):
        r = cliente_de("vendedor").patch(ADMIN, {"horario": "x"}, format="json")
        assert r.status_code == 403

    def test_la_lectura_publica_no_filtra_datos_internos(self, tienda):
        texto = _publica().content.decode()
        for prohibido in ("organizacion", "costo", "almacen", "lista_precio"):
            assert prohibido not in texto

    def test_tienda_apagada_no_responde(self, tienda):
        tienda.config.activa = False
        tienda.config.save()
        from django.core.cache import cache

        cache.clear()
        assert _publica().status_code == 503


class TestLogo:
    def test_sube_y_se_sirve_en_publico_con_su_version(self, tienda):
        r = cliente_de("admin").post(LOGO_ADMIN, {"logo": _logo()}, format="multipart")
        assert r.status_code == 200, r.content
        assert r.json()["tiene_logo"] is True
        ruta = _publica().json()["logo"]
        assert ruta.startswith("/api/v1/tienda/logo/")
        archivo = APIClient().get(ruta)
        assert archivo.status_code == 200
        assert archivo["Content-Type"] == "image/webp"  # los logos nuevos se guardan livianos
        assert "immutable" in archivo["Cache-Control"]
        b"".join(archivo.streaming_content)

    def test_un_logo_grande_se_achica_y_pesa_mucho_menos(self, tienda):
        import os

        ruido = Image.frombytes("RGBA", (800, 320), os.urandom(800 * 320 * 4))
        buffer = io.BytesIO()
        ruido.save(buffer, format="PNG")
        original = buffer.getvalue()
        archivo = SimpleUploadedFile("logo.png", original)
        r = cliente_de("admin").post(LOGO_ADMIN, {"logo": archivo}, format="multipart")
        assert r.status_code == 200, r.content
        servido = APIClient().get(_publica().json()["logo"])
        contenido = b"".join(servido.streaming_content)
        imagen = Image.open(io.BytesIO(contenido))
        assert imagen.format == "WEBP"
        assert imagen.width <= 600 and imagen.height <= 240
        assert len(contenido) < len(original)

    def test_un_logo_guardado_antes_como_png_se_sigue_sirviendo_como_png(self):
        from types import SimpleNamespace

        from apps.tienda import servicios

        viejo = SimpleNamespace(logo=SimpleNamespace(name="tienda/1/logo_abc.png"))
        nuevo = SimpleNamespace(logo=SimpleNamespace(name="tienda/1/logo_abc.webp"))
        assert servicios.tipo_de_logo(viejo) == "image/png"
        assert servicios.tipo_de_logo(nuevo) == "image/webp"

    def test_un_logo_nuevo_cambia_la_direccion(self, tienda):
        c = cliente_de("admin")
        c.post(LOGO_ADMIN, {"logo": _logo(color=(1, 2, 3))}, format="multipart")
        antes = _publica().json()["logo"]
        c.post(LOGO_ADMIN, {"logo": _logo(color=(200, 2, 3))}, format="multipart")
        assert _publica().json()["logo"] != antes
        assert APIClient().get(antes).status_code == 404

    def test_se_quita(self, tienda):
        c = cliente_de("admin")
        c.post(LOGO_ADMIN, {"logo": _logo()}, format="multipart")
        assert c.delete(LOGO_ADMIN).json()["tiene_logo"] is False
        assert _publica().json()["logo"] is None

    def test_rechaza_archivos_que_no_son_imagen(self, tienda):
        malo = SimpleUploadedFile("logo.png", b"<svg onload=alert(1)>")
        r = cliente_de("admin").post(LOGO_ADMIN, {"logo": malo}, format="multipart")
        assert r.status_code == 400
        assert cliente_de("admin").post(LOGO_ADMIN, {}, format="multipart").status_code == 400

    def test_sin_permiso_no_sube(self, tienda):
        r = cliente_de("vendedor").post(LOGO_ADMIN, {"logo": _logo()}, format="multipart")
        assert r.status_code == 403

    def test_version_inexistente_da_404(self, tienda):
        assert APIClient().get("/api/v1/tienda/logo/abcdef012345/").status_code == 404


class TestRecorteDelLogo:
    def test_quita_el_aire_alrededor_del_dibujo(self, tienda):
        from apps.tienda import servicios

        lienzo = Image.new("RGB", (400, 200), (255, 255, 255))
        lienzo.paste(Image.new("RGB", (100, 40), (10, 90, 200)), (150, 80))
        buffer = io.BytesIO()
        lienzo.save(buffer, format="PNG")
        recortado = Image.open(io.BytesIO(servicios.recortar_margenes(buffer.getvalue())))
        assert recortado.size == (108, 48)  # el dibujo más 4 px por lado

    def test_un_logo_sin_margen_o_ilegible_queda_igual(self, tienda):
        from apps.tienda import servicios

        assert servicios.recortar_margenes(b"no es una imagen") == b"no es una imagen"


class TestAvisoALaTienda:
    def test_al_cambiar_algo_se_avisa_una_vez_con_el_secreto(self, tienda, settings, monkeypatch):
        import requests

        from apps.tienda import catalogo

        settings.TIENDA_RENOVAR_URL = "http://tienda.local/api/renovar"
        settings.TIENDA_RENOVAR_TOKEN = "secreto"
        llamadas = []

        def falso(url, **kw):
            llamadas.append((url, kw["headers"]["Authorization"], kw["allow_redirects"]))
            return type("R", (), {"status_code": 200})()

        monkeypatch.setattr(requests, "post", falso)
        catalogo.invalidar()
        catalogo.invalidar()  # un cambio seguido de otro: un solo aviso
        assert llamadas == [("http://tienda.local/api/renovar", "Bearer secreto", False)]

    def test_sin_configurar_no_llama_a_nadie_y_un_fallo_no_rompe(
        self, tienda, settings, monkeypatch
    ):
        import requests

        from apps.tienda import catalogo, tasks

        monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no debía llamar"))
        catalogo.invalidar()
        settings.TIENDA_RENOVAR_URL = "http://tienda.local/api/renovar"
        settings.TIENDA_RENOVAR_TOKEN = "secreto"

        def cae(*a, **k):
            raise requests.ConnectionError()

        monkeypatch.setattr(requests, "post", cae)
        assert tasks.renovar_tienda() is False
