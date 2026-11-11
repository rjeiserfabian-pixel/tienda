"""Cuenta del cliente de la tienda: registro, correo, ingreso, recuperación y direcciones."""

# ruff: noqa: F811

import re

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.mantenimiento.models import Ubigeo
from apps.tienda.models import CuentaCliente, DireccionCuenta, SesionCuenta, TokenCuenta

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

BASE = "/api/v1/tienda/cuenta/"
CLAVE = "Clave-segura-9"
GENERICA = {"detalle": "Si los datos son correctos, te enviamos un correo."}


def nuevo_cliente() -> APIClient:
    return APIClient(HTTP_X_REQUESTED_WITH="tienda")


def datos(correo="ana@ejemplo.pe", **extra):
    return {
        "correo": correo,
        "password": CLAVE,
        "nombres": "Ana",
        "apellidos": "Pérez",
        "celular": "987654321",
        "acepta_terminos": True,
        **extra,
    }


def post(cliente, ruta, cuerpo=None):
    return cliente.post(BASE + ruta, cuerpo or {}, format="json")


def token_del_correo(indice=-1) -> str:
    return re.search(r"#token=(\S+)", mail.outbox[indice].body).group(1)


def registrada(correo="ana@ejemplo.pe", verificar=True) -> APIClient:
    c = nuevo_cliente()
    assert post(c, "registro", datos(correo)).status_code == 202
    if verificar:
        assert post(c, "verificar", {"token": token_del_correo()}).status_code == 200
    r = post(c, "ingresar", {"correo": correo, "password": CLAVE})
    assert r.status_code == 200, r.content
    return c


@pytest.fixture
def ubigeo():
    return Ubigeo.objects.filter(codigo="150101").first() or Ubigeo.objects.create(
        codigo="150101", departamento="Lima", provincia="Lima", distrito="Lima"
    )


class TestRegistro:
    def test_crea_la_cuenta_y_envia_el_correo_de_confirmacion(self, tienda):
        r = post(nuevo_cliente(), "registro", datos())
        assert r.status_code == 202
        cuenta = CuentaCliente.objects.sin_ambito().get(correo="ana@ejemplo.pe")
        assert not cuenta.verificada and cuenta.password != CLAVE and cuenta.acepta_terminos_en
        assert len(mail.outbox) == 1 and "ana@ejemplo.pe" in mail.outbox[0].to
        assert "/cuenta/verificar#token=" in mail.outbox[0].body  # el token va en el fragmento

    def test_responde_igual_si_el_correo_ya_tiene_cuenta(self, tienda):
        registrada()
        r = post(nuevo_cliente(), "registro", datos(nombres="Otra"))
        assert r.status_code == 202 and r.json() == GENERICA
        assert CuentaCliente.objects.sin_ambito().get().nombres == "Ana"  # no se pisa
        assert "Ya tienes una cuenta" in mail.outbox[-1].subject

    def test_una_cuenta_sin_confirmar_la_toma_quien_vuelve_a_registrarse(self, tienda):
        c1 = nuevo_cliente()
        post(c1, "registro", datos())
        post(c1, "ingresar", {"correo": "ana@ejemplo.pe", "password": CLAVE})
        post(nuevo_cliente(), "registro", datos(nombres="Dueña"))
        assert CuentaCliente.objects.sin_ambito().get().nombres == "Dueña"
        assert c1.get(BASE + "perfil").status_code == 401  # la sesión anterior se cerró

    @pytest.mark.parametrize(
        "cambio",
        [
            {"password": "corta1"},
            {"password": "12345678901"},
            {"password": "password123"},
            {"correo": "no-es-correo"},
            {"acepta_terminos": False},
            {"celular": "abc"},
            {"nombres": "   "},
        ],
    )
    def test_rechaza_datos_invalidos(self, tienda, cambio):
        r = post(nuevo_cliente(), "registro", {**datos(), **cambio})
        assert r.status_code == 400, r.content
        assert not CuentaCliente.objects.sin_ambito().exists()

    def test_pide_la_cabecera_anti_csrf(self, tienda):
        assert APIClient().post(BASE + "registro", datos(), format="json").status_code == 403

    def test_limita_los_correos_por_direccion(self, tienda, settings):
        c = nuevo_cliente()
        for _ in range(5):
            post(c, "registro", datos())
        assert len(mail.outbox) == settings.TIENDA_CORREOS_MAX_HORA

    def test_tienda_cerrada(self, tienda):
        from django.core.cache import cache

        tienda.config.activa = False
        tienda.config.save()
        cache.clear()
        assert post(nuevo_cliente(), "registro", datos()).status_code == 503


class TestVerificacion:
    def test_el_enlace_confirma_el_correo_una_sola_vez(self, tienda):
        post(nuevo_cliente(), "registro", datos())
        token = token_del_correo()
        c = nuevo_cliente()
        assert post(c, "verificar", {"token": token}).status_code == 200
        assert CuentaCliente.objects.sin_ambito().get().verificada
        assert post(c, "verificar", {"token": token}).status_code == 400

    def test_token_falso(self, tienda):
        assert post(nuevo_cliente(), "verificar", {"token": "x" * 40}).status_code == 400

    def test_el_token_no_queda_guardado_en_claro(self, tienda):
        post(nuevo_cliente(), "registro", datos())
        assert token_del_correo() not in TokenCuenta.objects.get().huella


class TestIngreso:
    def test_ingresa_con_cookie_httponly_y_sin_token_en_el_cuerpo(self, tienda):
        c = nuevo_cliente()
        post(c, "registro", datos())
        r = post(c, "ingresar", {"correo": "ANA@ejemplo.pe", "password": CLAVE})
        assert r.status_code == 200
        cookie = r.cookies["tienda_sesion"]
        assert cookie["httponly"] and cookie["samesite"] == "Lax"
        assert cookie.value not in r.content.decode()
        assert SesionCuenta.objects.get().huella != cookie.value  # solo se guarda la huella
        assert r["Cache-Control"] == "no-store"

    def test_credenciales_incorrectas_no_dicen_cual_fallo(self, tienda):
        registrada()
        a = post(nuevo_cliente(), "ingresar", {"correo": "ana@ejemplo.pe", "password": "mala"})
        b = post(nuevo_cliente(), "ingresar", {"correo": "nadie@ejemplo.pe", "password": "mala"})
        assert a.status_code == b.status_code == 401
        assert a.json()["error"]["codigo"] == b.json()["error"]["codigo"]
        assert a.json()["error"]["mensaje"] == b.json()["error"]["mensaje"]

    def test_se_bloquea_tras_varios_fallos(self, tienda):
        registrada()
        c = nuevo_cliente()
        for _ in range(5):
            post(c, "ingresar", {"correo": "ana@ejemplo.pe", "password": "mala"})
        r = post(c, "ingresar", {"correo": "ana@ejemplo.pe", "password": CLAVE})
        assert r.status_code == 429

    def test_salir_cierra_la_sesion(self, tienda):
        c = registrada()
        assert c.get(BASE + "perfil").status_code == 200
        assert post(c, "salir").status_code == 200
        assert c.get(BASE + "perfil").status_code == 401

    def test_una_cuenta_desactivada_no_entra(self, tienda):
        c = registrada()
        CuentaCliente.objects.sin_ambito().update(activa=False)
        assert c.get(BASE + "perfil").status_code == 401
        r = post(nuevo_cliente(), "ingresar", {"correo": "ana@ejemplo.pe", "password": CLAVE})
        assert r.status_code == 401


class TestRecuperacion:
    def test_recupera_la_clave_y_cierra_las_sesiones(self, tienda):
        c = registrada()
        n = len(mail.outbox)
        post(nuevo_cliente(), "recuperar", {"correo": "ana@ejemplo.pe"})
        assert len(mail.outbox) == n + 1
        token = token_del_correo()
        r = post(
            nuevo_cliente(), "recuperar/confirmar", {"token": token, "password": "Otra-clave-77"}
        )
        assert r.status_code == 200
        assert c.get(BASE + "perfil").status_code == 401
        entrada = post(
            nuevo_cliente(), "ingresar", {"correo": "ana@ejemplo.pe", "password": "Otra-clave-77"}
        )
        assert entrada.status_code == 200
        reuso = post(
            nuevo_cliente(), "recuperar/confirmar", {"token": token, "password": "Tercera-clave-8"}
        )
        assert reuso.status_code == 400

    def test_no_revela_si_el_correo_existe(self, tienda):
        r = post(nuevo_cliente(), "recuperar", {"correo": "nadie@ejemplo.pe"})
        assert r.status_code == 202 and r.json() == GENERICA and len(mail.outbox) == 0

    def test_rechaza_una_clave_debil(self, tienda):
        registrada()
        post(nuevo_cliente(), "recuperar", {"correo": "ana@ejemplo.pe"})
        r = post(
            nuevo_cliente(), "recuperar/confirmar", {"token": token_del_correo(), "password": "123"}
        )
        assert r.status_code == 400


class TestPerfil:
    def test_requiere_sesion(self, tienda):
        assert nuevo_cliente().get(BASE + "perfil").status_code == 401

    def test_edita_su_perfil_pero_no_el_correo(self, tienda):
        c = registrada()
        r = c.patch(
            BASE + "perfil",
            {"nombres": "María", "correo": "otro@x.pe", "celular": "999888777"},
            format="json",
        )
        assert r.status_code == 200 and r.json()["nombres"] == "María"
        assert r.json()["correo"] == "ana@ejemplo.pe" and r.json()["correo_verificado"] is True

    def test_cambiar_la_clave_cierra_las_otras_sesiones(self, tienda):
        c = registrada()
        otro = nuevo_cliente()
        post(otro, "ingresar", {"correo": "ana@ejemplo.pe", "password": CLAVE})
        mala = post(c, "cambiar-password", {"actual": "mala", "nueva": "Nueva-clave-55"})
        assert mala.status_code == 400
        ok = post(c, "cambiar-password", {"actual": CLAVE, "nueva": "Nueva-clave-55"})
        assert ok.status_code == 200
        assert c.get(BASE + "perfil").status_code == 200
        assert otro.get(BASE + "perfil").status_code == 401

    def test_reenviar_la_confirmacion_solo_si_falta(self, tienda):
        c = registrada(verificar=False)
        n = len(mail.outbox)
        assert post(c, "reenviar-verificacion").status_code == 202
        assert len(mail.outbox) == n + 1


class TestDirecciones:
    def dir(self, ubigeo, **extra):
        return {
            "receptor": "Ana Pérez",
            "celular": "987654321",
            "ubigeo": ubigeo.codigo,
            "direccion": "Av. Lima 123",
            **extra,
        }

    def test_la_primera_es_la_principal_y_se_puede_cambiar(self, tienda, ubigeo):
        c = registrada()
        a = post(c, "direcciones", self.dir(ubigeo, etiqueta="Casa")).json()
        assert a[0]["es_principal"] is True and a[0]["ubicacion"].startswith("LIMA")
        b = post(c, "direcciones", self.dir(ubigeo, etiqueta="Oficina", es_principal=True)).json()
        assert [d["etiqueta"] for d in b if d["es_principal"]] == ["Oficina"]

    def test_borrar_la_principal_deja_otra_como_principal(self, tienda, ubigeo):
        c = registrada()
        post(c, "direcciones", self.dir(ubigeo, etiqueta="Casa"))
        lista = post(c, "direcciones", self.dir(ubigeo, etiqueta="Oficina")).json()
        principal = next(d for d in lista if d["es_principal"])
        r = c.delete(f"{BASE}direcciones/{principal['id']}").json()
        assert len(r) == 1 and r[0]["es_principal"] is True
        assert (
            DireccionCuenta.objects.sin_ambito(incluir_eliminados=True).count() == 2
        )  # se conserva

    def test_valida_el_distrito_y_el_tope(self, tienda, ubigeo):
        c = registrada()
        assert post(c, "direcciones", {**self.dir(ubigeo), "ubigeo": "999999"}).status_code == 400
        for _ in range(10):
            assert post(c, "direcciones", self.dir(ubigeo)).status_code == 201
        assert post(c, "direcciones", self.dir(ubigeo)).status_code == 400

    def test_un_cliente_no_toca_las_direcciones_de_otro(self, tienda, ubigeo):
        ana = registrada()
        lista = post(ana, "direcciones", self.dir(ubigeo)).json()
        luis = registrada(correo="luis@ejemplo.pe")
        assert luis.get(BASE + "direcciones").json() == []
        url = f"{BASE}direcciones/{lista[0]['id']}"
        assert luis.patch(url, {"direccion": "Hackeada"}, format="json").status_code == 400
        assert luis.delete(url).status_code == 400
        assert DireccionCuenta.objects.sin_ambito().get().direccion == "Av. Lima 123"


class TestSesion:
    def test_responde_200_con_o_sin_sesion(self, tienda):
        assert nuevo_cliente().get(BASE + "sesion").json() == {"autenticado": False, "perfil": None}
        c = registrada()
        datos = c.get(BASE + "sesion").json()
        assert datos["autenticado"] is True and datos["perfil"]["correo"] == "ana@ejemplo.pe"
