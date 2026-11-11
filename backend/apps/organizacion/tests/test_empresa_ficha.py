"""Ficha comercial de la empresa: logo, contacto, web y empresa principal."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.auditoria import servicios
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/organizacion/empresas"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture(autouse=True)
def _media_temporal(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def imagen(ancho=20, alto=10, formato="PNG", modo="RGBA") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new(modo, (ancho, alto), (200, 30, 30, 0)[: len(modo)]).save(buffer, format=formato)
    return SimpleUploadedFile("logo", buffer.getvalue(), "image/png")


def subir(api, empresa, archivo):
    return api.post(f"{BASE}/{empresa.pk}/logo/", {"logo": archivo}, format="multipart")


class TestLogo:
    def test_se_recodifica_a_png_y_se_sirve_con_sesion(self, equipo):
        api, empresa = cliente_de("super"), equipo["e"].emp_a1
        r = subir(api, empresa, imagen(3000, 1500))
        assert r.status_code == 200 and r.json()["tiene_logo"] is True
        servido = api.get(f"{BASE}/{empresa.pk}/logo/")
        assert servido.status_code == 200 and servido["Content-Type"] == "image/png"
        pieza = Image.open(io.BytesIO(b"".join(servido.streaming_content)))
        assert pieza.format == "PNG" and max(pieza.size) <= 800

    def test_se_conserva_la_transparencia(self, equipo):
        api, empresa = cliente_de("super"), equipo["e"].emp_a1
        subir(api, empresa, imagen())
        pieza = Image.open(
            io.BytesIO(b"".join(api.get(f"{BASE}/{empresa.pk}/logo/").streaming_content))
        )
        assert pieza.mode == "RGBA" and pieza.getpixel((0, 0))[3] == 0

    def test_un_archivo_que_no_es_imagen_se_rechaza(self, equipo):
        falso = SimpleUploadedFile("logo.png", b"<svg onload=alert(1)>", "image/png")
        r = subir(cliente_de("super"), equipo["e"].emp_a1, falso)
        assert r.status_code == 400 and r.json()["error"]["codigo"] == "logo_invalido"

    def test_pesa_mas_de_2_mb(self, equipo):
        grande = SimpleUploadedFile("logo.png", b"0" * (2 * 1024 * 1024 + 1), "image/png")
        assert subir(cliente_de("super"), equipo["e"].emp_a1, grande).status_code == 400

    def test_quitar_el_logo(self, equipo):
        api, empresa = cliente_de("super"), equipo["e"].emp_a1
        subir(api, empresa, imagen())
        r = api.delete(f"{BASE}/{empresa.pk}/logo/")
        assert r.status_code == 200 and r.json()["tiene_logo"] is False
        assert api.get(f"{BASE}/{empresa.pk}/logo/").status_code == 404

    def test_reemplazar_no_deja_archivos_huerfanos(self, equipo, tmp_path):
        api, empresa = cliente_de("super"), equipo["e"].emp_a1
        subir(api, empresa, imagen())
        subir(api, empresa, imagen())
        assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 1

    def test_el_vendedor_no_puede_cambiarlo(self, equipo):
        assert subir(cliente_de("vendedor"), equipo["e"].emp_a1, imagen()).status_code == 403

    def test_otra_organizacion_no_ve_ni_toca_el_logo(self, equipo):
        empresa = equipo["e"].emp_a1
        subir(cliente_de("super"), empresa, imagen())
        ajeno = cliente_de("otra_org")
        assert ajeno.get(f"{BASE}/{empresa.pk}/logo/").status_code == 404
        assert subir(ajeno, empresa, imagen()).status_code == 404


class TestFicha:
    def test_guarda_contacto_y_web(self, equipo):
        api, empresa = cliente_de("super"), equipo["e"].emp_a1
        datos = {
            "razon_social": empresa.razon_social,
            "estado": "ACTIVO",
            "direccion_fiscal": "Av. Lima 123, Lima",
            "telefono": "999 888 777",
            "correo": "ventas@ejemplo.pe",
            "sitio_web": "https://ejemplo.pe",
            "tienda_web": "https://tienda.ejemplo.pe",
        }
        r = api.patch(f"{BASE}/{empresa.pk}/", datos, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["tienda_web"] == "https://tienda.ejemplo.pe"
        assert api.get(f"{BASE}/{empresa.pk}/").json()["correo"] == "ventas@ejemplo.pe"

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("sitio_web", "javascript:alert(1)"),
            ("tienda_web", "ftp://ejemplo.pe"),
            ("sitio_web", "no es una url"),
            ("correo", "sin-arroba"),
        ],
    )
    def test_rechaza_valores_invalidos(self, equipo, campo, valor):
        empresa = equipo["e"].emp_a1
        datos = {"razon_social": empresa.razon_social, "estado": "ACTIVO", campo: valor}
        r = cliente_de("super").patch(f"{BASE}/{empresa.pk}/", datos, format="json")
        assert r.status_code == 400

    def test_solo_una_empresa_es_la_principal(self, equipo):
        api, e = cliente_de("super"), equipo["e"]
        for empresa in (e.emp_a1, e.emp_a2):
            datos = {"razon_social": empresa.razon_social, "estado": "ACTIVO", "es_principal": True}
            assert api.patch(f"{BASE}/{empresa.pk}/", datos, format="json").status_code == 200
        principales = [x for x in api.get(f"{BASE}/").json()["results"] if x["es_principal"]]
        assert [x["id"] for x in principales] == [e.emp_a2.pk]

    def test_editar_otra_cosa_no_pierde_la_ficha(self, equipo):
        api, empresa = cliente_de("super"), equipo["e"].emp_a1
        base = {"razon_social": empresa.razon_social, "estado": "ACTIVO"}
        api.patch(f"{BASE}/{empresa.pk}/", {**base, "telefono": "123"}, format="json")
        r = api.patch(f"{BASE}/{empresa.pk}/", {**base, "nombre_comercial": "Nuevo"}, format="json")
        assert r.json()["telefono"] == "123"
