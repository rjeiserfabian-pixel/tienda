"""Banners del inicio: subida segura de imágenes, enlaces, vigencia y lectura pública."""

# ruff: noqa: F811

import io
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import banners
from apps.tienda.models import BannerTienda

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/banners/"
PUBLICO = "/api/v1/tienda/banners"


def imagen(ancho=2000, alto=900, formato="PNG", color=(30, 60, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), color).save(buffer, format=formato)
    return SimpleUploadedFile(f"banner.{formato.lower()}", buffer.getvalue())


def cuerpo(**extra):
    return {
        "titulo": "Cyber Technology",
        "subtitulo": "Hasta 30 % de descuento",
        "boton_texto": "Ver ofertas",
        "enlace": "/ofertas",
        "alt": "Laptops y monitores en oferta",
        "imagen_escritorio": imagen(),
        **extra,
    }


def subir(**extra):
    r = cliente_de("admin").post(ADMIN, cuerpo(**extra), format="multipart")
    assert r.status_code == 201, r.content
    return r.json()


def publico():
    cache.clear()
    return APIClient().get(PUBLICO)


class TestSubida:
    def test_sube_recorta_a_webp_y_sirve_con_version(self, tienda):
        b = subir(imagen_movil=imagen(900, 1200))
        assert b["tiene_escritorio"] and b["tiene_movil"] and b["estado"] == "VIGENTE"
        lista = publico().json()
        assert len(lista) == 1
        esc = lista[0]["imagen_escritorio"]
        assert esc.startswith(f"/api/v1/tienda/banners/{b['id']}/escritorio/")
        assert lista[0]["imagen_movil"].startswith(f"/api/v1/tienda/banners/{b['id']}/movil/")
        archivo = APIClient().get(esc)
        assert archivo.status_code == 200 and archivo["Content-Type"] == "image/webp"
        assert "immutable" in archivo["Cache-Control"]
        assert Image.open(io.BytesIO(b"".join(archivo.streaming_content))).size == (1600, 600)
        movil = APIClient().get(lista[0]["imagen_movil"])
        assert Image.open(io.BytesIO(b"".join(movil.streaming_content))).size == (800, 800)

    def test_una_imagen_nueva_es_otra_direccion(self, tienda):
        b = subir()
        antes = publico().json()[0]["imagen_escritorio"]
        r = cliente_de("admin").patch(
            f"{ADMIN}{b['id']}/",
            {"imagen_escritorio": imagen(color=(200, 10, 10))},
            format="multipart",
        )
        assert r.status_code == 200
        despues = publico().json()[0]["imagen_escritorio"]
        assert despues != antes and APIClient().get(antes).status_code == 404

    @pytest.mark.parametrize(
        "archivo",
        [
            SimpleUploadedFile("x.png", b"<svg onload=alert(1)>"),
            SimpleUploadedFile("x.png", b"GIF89a" + b"0" * 50),
            SimpleUploadedFile("x.jpg", b"no es una imagen"),
        ],
    )
    def test_rechaza_lo_que_no_es_una_imagen_valida(self, tienda, archivo):
        r = cliente_de("admin").post(ADMIN, cuerpo(imagen_escritorio=archivo), format="multipart")
        assert r.status_code == 400
        assert not BannerTienda.objects.sin_ambito().exists()

    def test_rechaza_imagenes_muy_pesadas(self, tienda, monkeypatch):
        monkeypatch.setattr(banners, "TAMANO_MAXIMO", 1000)
        r = cliente_de("admin").post(ADMIN, cuerpo(), format="multipart")
        assert r.status_code == 400 and "3 MB" in str(r.json())

    def test_sin_imagen_o_sin_texto_alternativo_no_se_crea(self, tienda):
        admin = cliente_de("admin")
        sin_imagen = {k: v for k, v in cuerpo().items() if k != "imagen_escritorio"}
        assert admin.post(ADMIN, sin_imagen, format="multipart").status_code == 400
        sin_alt = {k: v for k, v in cuerpo().items() if k != "alt"}
        assert admin.post(ADMIN, sin_alt, format="multipart").status_code == 400

    def test_si_falla_la_imagen_de_celular_no_quedan_archivos_sueltos(self, tienda, settings):
        import os

        r = cliente_de("admin").post(
            ADMIN,
            cuerpo(imagen_movil=SimpleUploadedFile("m.png", b"basura")),
            format="multipart",
        )
        assert r.status_code == 400
        carpeta = os.path.join(settings.MEDIA_ROOT, "tienda")
        archivos = (
            [f for _, _, fs in os.walk(carpeta) for f in fs] if os.path.isdir(carpeta) else []
        )
        assert archivos == []


class TestEnlaces:
    @pytest.mark.parametrize(
        "enlace",
        [
            "javascript:alert(1)",
            "//sitio-malo.com",
            "http://inseguro.com",
            "data:text/html,x",
            "ofertas",
        ],
    )
    def test_rechaza_enlaces_peligrosos(self, tienda, enlace):
        r = cliente_de("admin").post(ADMIN, cuerpo(enlace=enlace), format="multipart")
        assert r.status_code == 400, enlace

    @pytest.mark.parametrize(
        "enlace", ["/ofertas", "/categoria/laptops?orden=precio_asc", "https://culqi.com/x", ""]
    )
    def test_acepta_rutas_de_la_tienda_y_https(self, tienda, enlace):
        assert (
            cliente_de("admin").post(ADMIN, cuerpo(enlace=enlace), format="multipart").status_code
            == 201
        )


class TestVigencia:
    def test_solo_salen_los_vigentes_en_orden(self, tienda):
        ahora = timezone.now()
        subir(titulo="Segundo", orden=2)
        subir(titulo="Primero", orden=1)
        subir(titulo="Futuro", desde=(ahora + timedelta(days=1)).isoformat())
        subir(titulo="Vencido", hasta=(ahora - timedelta(days=1)).isoformat())
        subir(titulo="Pausado", activo=False)
        assert [b["titulo"] for b in publico().json()] == ["Primero", "Segundo"]
        estados = {b["titulo"]: b["estado"] for b in cliente_de("admin").get(ADMIN).json()}
        assert estados["Futuro"] == "PROGRAMADO" and estados["Vencido"] == "VENCIDO"
        assert estados["Pausado"] == "PAUSADO"

    def test_maximo_ocho_en_el_inicio(self, tienda):
        for i in range(10):
            subir(titulo=f"B{i}", orden=i)
        assert len(publico().json()) == banners.MAXIMO_PUBLICO

    def test_la_imagen_de_un_banner_vencido_ya_no_se_sirve(self, tienda):
        b = subir()
        url = publico().json()[0]["imagen_escritorio"]
        BannerTienda.objects.sin_ambito().update(hasta=timezone.now() - timedelta(minutes=1))
        cache.clear()
        assert APIClient().get(url).status_code == 404
        assert b["id"]

    def test_la_tienda_cerrada_no_responde(self, tienda):
        subir()
        tienda.config.activa = False
        tienda.config.save()
        cache.clear()
        assert APIClient().get(PUBLICO).status_code == 503


class TestPanel:
    def test_editar_pausar_y_eliminar(self, tienda):
        b = subir()
        admin = cliente_de("admin")
        r = admin.patch(f"{ADMIN}{b['id']}/", {"activo": False, "titulo": "Nuevo"}, format="json")
        assert (
            r.status_code == 200
            and r.json()["estado"] == "PAUSADO"
            and r.json()["titulo"] == "Nuevo"
        )
        assert publico().json() == []
        assert admin.delete(f"{ADMIN}{b['id']}/").status_code == 204
        assert BannerTienda.objects.sin_ambito(incluir_eliminados=True).count() == 1

    def test_vista_previa_con_sesion_aunque_no_este_vigente(self, tienda):
        b = subir(activo=False)
        r = cliente_de("admin").get(f"{ADMIN}{b['id']}/imagen/escritorio/")
        assert r.status_code == 200 and r["Content-Type"] == "image/webp"
        b"".join(r.streaming_content)
        assert APIClient().get(f"{ADMIN}{b['id']}/imagen/escritorio/").status_code == 401

    def test_quita_la_imagen_de_celular(self, tienda):
        b = subir(imagen_movil=imagen(900, 1200))
        r = cliente_de("admin").patch(
            f"{ADMIN}{b['id']}/", {"quitar_imagen_movil": True}, format="json"
        )
        assert r.json()["tiene_movil"] is False and publico().json()[0]["imagen_movil"] is None

    def test_permisos_y_aislamiento(self, tienda):
        b = subir()
        assert cliente_de("almacenero").get(ADMIN).status_code == 403
        assert APIClient().get(ADMIN).status_code == 401
        otra = cliente_de("otra_org")
        assert otra.get(ADMIN).json() == []
        assert otra.patch(f"{ADMIN}{b['id']}/", {"titulo": "x"}, format="json").status_code == 404
        assert otra.delete(f"{ADMIN}{b['id']}/").status_code == 404
