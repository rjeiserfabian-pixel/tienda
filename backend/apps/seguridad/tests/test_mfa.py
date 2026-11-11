"""Verificación en dos pasos: activación, login en dos pasos, códigos de recuperación, bloqueos."""

import pyotp
import pytest

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.seguridad.models import MfaConfig, Sesion, Usuario
from apps.seguridad.services import mfa
from apps.seguridad.tests.conftest import PASSWORD, autenticar, cliente_de, iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


class Reloj:
    """Reloj controlable: cada código TOTP solo sirve una vez, así que hay que avanzar el tiempo."""

    def __init__(self):
        self.t = 1_800_000_000.0

    def time(self):
        return self.t

    def avanzar(self, segundos=30):
        self.t += segundos


@pytest.fixture
def reloj(monkeypatch):
    r = Reloj()
    monkeypatch.setattr(mfa, "time", r)
    return r


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


def codigo(secreto, reloj):
    return pyotp.TOTP(secreto).at(int(reloj.t))


@pytest.fixture
def ana(rbac, nuevo_usuario, reloj):
    usuario = nuevo_usuario(rbac.org_a, "ana_mfa", [rbac.emp_a1], [("VENDEDOR", None)])
    secreto = mfa.iniciar_configuracion(usuario, PASSWORD)["secreto"]
    codigos = mfa.confirmar_configuracion(usuario, codigo(secreto, reloj))
    usuario.refresh_from_db()
    return usuario, secreto, codigos


def login(api, **extra):
    return iniciar_sesion(api, "ana_mfa", plataforma="MOVIL", **extra)


class TestActivacion:
    def test_flujo_completo_por_la_api(self, rbac, nuevo_usuario, reloj):
        usuario = nuevo_usuario(rbac.org_a, "ana_mfa", [rbac.emp_a1], [("VENDEDOR", None)])
        api = cliente_de("ana_mfa")
        assert api.get(f"{BASE}/mfa/").json()["activo"] is False

        r = api.post(f"{BASE}/mfa/configurar/", {"password": PASSWORD}, format="json")
        assert r.status_code == 200
        secreto = r.json()["secreto"]
        assert r.json()["uri"].startswith("otpauth://totp/")

        mal = api.post(f"{BASE}/mfa/confirmar/", {"codigo": "000000"}, format="json")
        assert (mal.status_code, mal.json()["error"]["codigo"]) == (400, "mfa_codigo_invalido")

        r = api.post(f"{BASE}/mfa/confirmar/", {"codigo": codigo(secreto, reloj)}, format="json")
        assert r.status_code == 200
        assert len(r.json()["codigos_recuperacion"]) == 10
        usuario.refresh_from_db()
        assert usuario.mfa_activo
        assert api.get(f"{BASE}/mfa/").json() == {
            "activo": True,
            "codigos_restantes": 10,
            "obligatorio": False,
        }

    def test_activar_exige_la_contrasena(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "ana_mfa", [rbac.emp_a1], [("VENDEDOR", None)])
        r = cliente_de("ana_mfa").post(
            f"{BASE}/mfa/configurar/", {"password": "incorrecta"}, format="json"
        )
        assert (r.status_code, r.json()["error"]["codigo"]) == (400, "password_actual_incorrecta")

    def test_el_secreto_se_guarda_cifrado(self, ana):
        from django.db import connection

        usuario, secreto, _ = ana
        with connection.cursor() as c:
            c.execute("SELECT secreto FROM seguridad_mfaconfig WHERE usuario_id = %s", [usuario.pk])
            guardado = c.fetchone()[0]
        assert secreto not in guardado and guardado.startswith("1:")
        assert MfaConfig.objects.get(usuario=usuario).secreto == secreto

    def test_la_rotacion_de_claves_tambien_cubre_el_secreto(self, ana, settings):
        from django.core.management import call_command
        from django.db import connection

        usuario, secreto, _ = ana
        settings.CIFRADO_CLAVE_ACTUAL = "2"
        call_command("rotar_clave_cifrado", stdout=__import__("io").StringIO())
        with connection.cursor() as c:
            c.execute("SELECT secreto FROM seguridad_mfaconfig WHERE usuario_id = %s", [usuario.pk])
            assert c.fetchone()[0].startswith("2:")
        assert MfaConfig.objects.get(usuario=usuario).secreto == secreto

    def test_no_se_activa_dos_veces(self, ana):
        usuario, _, _ = ana
        with pytest.raises(Exception) as error:
            mfa.iniciar_configuracion(usuario, PASSWORD)
        assert error.value.codigo == "mfa_ya_activo"


class TestLoginEnDosPasos:
    def test_la_contrasena_sola_no_abre_sesion(self, ana, api):
        r = login(api)
        assert r.status_code == 200
        assert r.json()["mfa_requerido"] is True
        assert "access" not in r.json() and "refresh" not in r.json()
        assert not Sesion.objects.filter(usuario=ana[0]).exists()

    def test_con_el_codigo_correcto_se_abre_la_sesion(self, ana, api, reloj):
        _, secreto, _ = ana
        desafio = login(api).json()["desafio"]
        reloj.avanzar()
        r = api.post(
            f"{BASE}/auth/mfa/verificar/",
            {"desafio": desafio, "codigo": codigo(secreto, reloj)},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["access"]
        assert Sesion.objects.filter(usuario=ana[0]).count() == 1
        assert AuditoriaEvento.objects.filter(
            accion="sesion.login_ok", detalle__metodo="mfa_totp"
        ).exists()

    def test_un_codigo_no_se_puede_reutilizar(self, ana, api, reloj):
        _, secreto, _ = ana
        reloj.avanzar()
        usado = codigo(secreto, reloj)
        desafio = login(api).json()["desafio"]
        datos = {"desafio": desafio, "codigo": usado}
        assert api.post(f"{BASE}/auth/mfa/verificar/", datos, format="json").status_code == 200
        otra = login(api).json()["desafio"]
        r = api.post(
            f"{BASE}/auth/mfa/verificar/", {"desafio": otra, "codigo": usado}, format="json"
        )
        assert (r.status_code, r.json()["error"]["codigo"]) == (400, "mfa_codigo_invalido")

    def test_un_codigo_incorrecto_se_audita_y_no_abre_sesion(self, ana, api):
        desafio = login(api).json()["desafio"]
        r = api.post(
            f"{BASE}/auth/mfa/verificar/", {"desafio": desafio, "codigo": "123456"}, format="json"
        )
        assert r.status_code == 400
        assert not Sesion.objects.filter(usuario=ana[0]).exists()
        assert AuditoriaEvento.objects.filter(accion="mfa.intento_fallido", exito=False).exists()

    def test_tras_varios_fallos_se_bloquea(self, ana, api, settings):
        desafio = login(api).json()["desafio"]
        for _ in range(settings.MFA_MAX_FALLOS):
            api.post(
                f"{BASE}/auth/mfa/verificar/",
                {"desafio": desafio, "codigo": "000000"},
                format="json",
            )
        r = api.post(
            f"{BASE}/auth/mfa/verificar/", {"desafio": desafio, "codigo": "000000"}, format="json"
        )
        assert r.status_code == 429
        assert "Retry-After" in r

    def test_el_desafio_alterado_o_vencido_no_vale(self, ana, api, settings):
        desafio = login(api).json()["desafio"]
        r = api.post(
            f"{BASE}/auth/mfa/verificar/", {"desafio": desafio + "x", "codigo": "1"}, format="json"
        )
        assert (r.status_code, r.json()["error"]["codigo"]) == (401, "desafio_mfa_invalido")
        settings.MFA_DESAFIO_SEG = -1
        r = api.post(
            f"{BASE}/auth/mfa/verificar/", {"desafio": desafio, "codigo": "1"}, format="json"
        )
        assert r.status_code == 401

    def test_usuario_desactivado_entre_pasos(self, ana, api):
        usuario, _, _ = ana
        desafio = login(api).json()["desafio"]
        Usuario.objects.filter(pk=usuario.pk).update(is_active=False)
        r = api.post(
            f"{BASE}/auth/mfa/verificar/", {"desafio": desafio, "codigo": "123456"}, format="json"
        )
        assert r.status_code == 401

    def test_codigo_de_recuperacion_sirve_una_sola_vez(self, ana, api):
        _, _, codigos = ana
        for intento in range(2):
            desafio = login(api).json()["desafio"]
            r = api.post(
                f"{BASE}/auth/mfa/verificar/",
                {"desafio": desafio, "codigo": codigos[0].upper()},
                format="json",
            )
            assert r.status_code == (200 if intento == 0 else 400)
        assert AuditoriaEvento.objects.filter(accion="mfa.codigo_recuperacion_usado").exists()
        assert mfa.codigos_restantes(ana[0]) == 9

    def test_los_codigos_de_recuperacion_se_guardan_como_huella(self, ana):
        from apps.seguridad.models import CodigoRecuperacionMfa

        _, _, codigos = ana
        guardadas = set(CodigoRecuperacionMfa.objects.values_list("huella", flat=True))
        assert not guardadas & {c.replace("-", "") for c in codigos}
        assert len(guardadas) == 10


class TestGestionDelFactor:
    def test_desactivar_pide_contrasena_y_codigo(self, ana, reloj):
        usuario, secreto, _ = ana
        reloj.avanzar()
        with pytest.raises(Exception) as error:
            mfa.desactivar(usuario, "otra", codigo(secreto, reloj))
        assert error.value.codigo == "password_actual_incorrecta"
        mfa.desactivar(usuario, PASSWORD, codigo(secreto, reloj))
        usuario.refresh_from_db()
        assert not usuario.mfa_activo
        assert not MfaConfig.objects.filter(usuario=usuario).exists()

    def test_regenerar_invalida_los_codigos_anteriores(self, ana, reloj):
        usuario, secreto, anteriores = ana
        reloj.avanzar()
        nuevos = mfa.regenerar_codigos(usuario, PASSWORD, codigo(secreto, reloj))
        assert not set(nuevos) & set(anteriores)
        assert mfa.codigos_restantes(usuario) == 10
        reloj.avanzar()
        with pytest.raises(Exception) as error:
            mfa.verificar(usuario, anteriores[0])
        assert error.value.codigo == "mfa_codigo_invalido"

    def test_un_administrador_restablece_el_factor_de_otro(self, rbac, nuevo_usuario, ana):
        usuario, _, _ = ana
        nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        api = cliente_de("jefe")
        r = api.post(f"{BASE}/usuarios/{usuario.pk}/restablecer-mfa/")
        assert r.status_code == 200, r.content
        assert r.json()["mfa_activo"] is False
        usuario.refresh_from_db()
        assert not usuario.mfa_activo
        assert AuditoriaEvento.objects.filter(accion="mfa.restablecido").exists()
        # Ya puede entrar solo con la contraseña.
        assert "access" in login(cliente_de("jefe")).json()

    def test_restablecer_exige_permiso_y_no_se_hace_sobre_si_mismo(self, rbac, nuevo_usuario, ana):
        usuario, _, _ = ana
        nuevo_usuario(rbac.org_a, "otro", [rbac.emp_a1], [("VENDEDOR", None)])
        assert (
            cliente_de("otro").post(f"{BASE}/usuarios/{usuario.pk}/restablecer-mfa/").status_code
            == 403
        )
        jefe = nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        r = cliente_de("jefe").post(f"{BASE}/usuarios/{jefe.pk}/restablecer-mfa/")
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "operacion_sobre_si_mismo")


class TestPoliticaObligatoria:
    def activar_politica(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "dueno", [rbac.emp_a1], [("SUPERADMIN", None)])
        r = cliente_de("dueno").patch(
            "/api/v1/organizacion/", {"mfa_obligatorio": True}, format="json"
        )
        assert r.status_code == 200 and r.json()["mfa_obligatorio"] is True

    def test_sin_factor_solo_se_puede_configurarlo(self, rbac, nuevo_usuario, reloj):
        nuevo_usuario(rbac.org_a, "ana_mfa", [rbac.emp_a1], [("ADMIN", None)])
        api = cliente_de("ana_mfa")  # inicia sesión antes de que exista la política
        self.activar_politica(rbac, nuevo_usuario)

        r = api.get(f"{BASE}/usuarios/")
        assert (r.status_code, r.json()["error"]["codigo"]) == (403, "mfa_configuracion_requerida")
        assert api.get(f"{BASE}/me/").json()["usuario"]["debe_configurar_mfa"] is True

        secreto = api.post(f"{BASE}/mfa/configurar/", {"password": PASSWORD}, format="json").json()[
            "secreto"
        ]
        api.post(f"{BASE}/mfa/confirmar/", {"codigo": codigo(secreto, reloj)}, format="json")
        assert api.get(f"{BASE}/usuarios/").status_code == 200

    def test_con_la_politica_no_se_puede_desactivar(self, rbac, nuevo_usuario, ana, reloj):
        usuario, secreto, _ = ana
        self.activar_politica(rbac, nuevo_usuario)
        reloj.avanzar()
        with pytest.raises(Exception) as error:
            mfa.desactivar(usuario, PASSWORD, codigo(secreto, reloj))
        assert error.value.codigo == "mfa_obligatoria"

    def test_cambiar_la_politica_queda_auditado(self, rbac, nuevo_usuario):
        self.activar_politica(rbac, nuevo_usuario)
        e = AuditoriaEvento.objects.get(accion="organizacion.editada")
        assert e.detalle == {"mfa_obligatorio": [False, True]}


def test_el_acceso_sigue_funcionando_con_el_token_de_la_sesion_mfa(ana, api, reloj):
    _, secreto, _ = ana
    desafio = login(api).json()["desafio"]
    reloj.avanzar()
    r = api.post(
        f"{BASE}/auth/mfa/verificar/",
        {"desafio": desafio, "codigo": codigo(secreto, reloj)},
        format="json",
    )
    autenticar(api, r.json()["access"])
    assert api.get(f"{BASE}/me/").json()["usuario"]["mfa_activo"] is True


class TestCalculoDePrecios:
    """La organización elige si piensa su ganancia como utilidad (sobre el costo) o como margen."""

    def test_por_defecto_es_utilidad_y_se_puede_cambiar_a_margen(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "dueno_precios", [rbac.emp_a1], [("SUPERADMIN", None)])
        api = cliente_de("dueno_precios")
        assert api.get("/api/v1/organizacion/").json()["calculo_precios"] == "UTILIDAD"
        r = api.patch("/api/v1/organizacion/", {"calculo_precios": "MARGEN"}, format="json")
        assert (r.status_code, r.json()["calculo_precios"]) == (200, "MARGEN")
        assert api.get("/api/v1/organizacion/").json()["calculo_precios"] == "MARGEN"

    def test_un_valor_desconocido_se_rechaza(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "dueno_precios2", [rbac.emp_a1], [("SUPERADMIN", None)])
        r = cliente_de("dueno_precios2").patch(
            "/api/v1/organizacion/", {"calculo_precios": "OTRO"}, format="json"
        )
        assert r.status_code == 400

    def test_quien_no_gestiona_la_organizacion_no_lo_cambia(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "vende_precios", [rbac.emp_a1], [("VENDEDOR", None)])
        r = cliente_de("vende_precios").patch(
            "/api/v1/organizacion/", {"calculo_precios": "MARGEN"}, format="json"
        )
        assert r.status_code == 403
