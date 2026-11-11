"""Recuperación de contraseña por correo: seguridad del enlace y efectos sobre la cuenta."""

import re
from datetime import timedelta

import pyotp
import pytest
from django.core import mail
from django.utils import timezone

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.seguridad.models import Sesion, TokenRecuperacion
from apps.seguridad.services import mfa
from apps.seguridad.tests.conftest import PASSWORD, cliente_de, iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad/auth"
NUEVA = "Clave-Nueva-Segura-2027!"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def ana(rbac, nuevo_usuario):
    return nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], [("VENDEDOR", None)])


def pedir(api, identificador="ana"):
    return api.post(f"{BASE}/recuperar/", {"identificador": identificador}, format="json")


def token_del_correo() -> str:
    assert len(mail.outbox) == 1
    return re.search(r"#token=([\w-]+)", mail.outbox[0].body).group(1)


def confirmar(api, token, nueva=NUEVA, **extra):
    return api.post(
        f"{BASE}/recuperar/confirmar/", {"token": token, "nueva": nueva, **extra}, format="json"
    )


class TestSolicitud:
    def test_envia_el_correo_con_un_enlace_de_un_solo_uso(self, ana, api):
        r = pedir(api)
        assert r.status_code == 202
        assert mail.outbox[0].to == ["ana@ejemplo.com"]
        assert "/recuperar/confirmar#token=" in mail.outbox[0].body
        assert TokenRecuperacion.objects.filter(usuario=ana, usado_en__isnull=True).count() == 1

    def test_responde_igual_exista_o_no_la_cuenta(self, ana, api):
        existente = pedir(api, "ana")
        fantasma = pedir(api, "no-existe@x.com")
        assert (existente.status_code, existente.json()) == (fantasma.status_code, fantasma.json())
        assert len(mail.outbox) == 1  # solo la cuenta real recibió correo

    def test_el_token_no_se_guarda_en_claro(self, ana, api):
        pedir(api)
        token = token_del_correo()
        assert not TokenRecuperacion.objects.filter(huella=token).exists()
        assert len(TokenRecuperacion.objects.get().huella) == 64

    def test_un_enlace_nuevo_invalida_el_anterior(self, ana, api):
        pedir(api)
        primero = token_del_correo()
        mail.outbox.clear()
        pedir(api)
        segundo = token_del_correo()
        assert confirmar(api, primero).status_code == 400
        assert confirmar(api, segundo).status_code == 204

    def test_limite_de_solicitudes_por_cuenta(self, ana, api, settings):
        for _ in range(settings.RECUPERACION_MAX_SOLICITUDES_HORA + 2):
            assert pedir(api).status_code == 202
        assert len(mail.outbox) == settings.RECUPERACION_MAX_SOLICITUDES_HORA

    def test_cuentas_inactivas_no_reciben_correo(self, ana, api):
        ana.is_active = False
        ana.save(update_fields=["is_active"])
        pedir(api)
        assert mail.outbox == []

    def test_la_solicitud_queda_auditada_sin_el_token(self, ana, api):
        pedir(api)
        token = token_del_correo()
        evento = AuditoriaEvento.objects.get(accion="password.recuperacion_solicitada")
        assert token not in str(evento.detalle) + evento.resumen


class TestConfirmacion:
    def test_restablece_la_clave_y_cierra_todas_las_sesiones(self, ana, api):
        cliente_de("ana")
        assert Sesion.objects.filter(usuario=ana, revocada=False).count() == 1
        pedir(api)
        r = confirmar(api, token_del_correo())
        assert r.status_code == 204
        assert not Sesion.objects.filter(usuario=ana, revocada=False).exists()
        assert iniciar_sesion(api, "ana", PASSWORD).status_code == 401
        assert iniciar_sesion(api, "ana", NUEVA).status_code == 200
        assert AuditoriaEvento.objects.filter(accion="password.recuperada").exists()

    def test_el_token_sirve_una_sola_vez(self, ana, api):
        pedir(api)
        token = token_del_correo()
        assert confirmar(api, token).status_code == 204
        r = confirmar(api, token, "Otra-Clave-Distinta-2028!")
        assert (r.status_code, r.json()["error"]["codigo"]) == (400, "token_recuperacion_invalido")

    def test_un_token_vencido_o_falso_no_vale(self, ana, api):
        pedir(api)
        token = token_del_correo()
        TokenRecuperacion.objects.update(expira_en=timezone.now() - timedelta(seconds=1))
        assert confirmar(api, token).status_code == 400
        assert confirmar(api, "inventado").status_code == 400

    def test_una_clave_debil_no_consume_el_token(self, ana, api):
        pedir(api)
        token = token_del_correo()
        assert confirmar(api, token, "123").status_code == 400
        assert confirmar(api, token).status_code == 204

    def test_no_se_puede_volver_a_la_clave_actual(self, ana, api):
        pedir(api)
        r = confirmar(api, token_del_correo(), PASSWORD)
        assert (r.status_code, r.json()["error"]["codigo"]) == (400, "password_reutilizada")

    def test_levanta_el_bloqueo_por_intentos_fallidos(self, ana, api, settings):
        for _ in range(settings.LOGIN_FALLOS_PARA_BLOQUEO):
            iniciar_sesion(api, "ana", "mala-clave-9")
        assert iniciar_sesion(api, "ana", PASSWORD).status_code == 429
        pedir(api)
        confirmar(api, token_del_correo())
        assert iniciar_sesion(api, "ana", NUEVA).status_code == 200

    def test_una_cuenta_con_segundo_factor_tambien_necesita_el_codigo(self, ana, api):
        reloj_t = [1_800_000_000.0]

        class Reloj:
            def time(self):
                return reloj_t[0]

        original = mfa.time
        mfa.time = Reloj()
        try:
            secreto = mfa.iniciar_configuracion(ana, PASSWORD)["secreto"]
            mfa.confirmar_configuracion(ana, pyotp.TOTP(secreto).at(int(reloj_t[0])))
            pedir(api)
            token = token_del_correo()
            sin_codigo = confirmar(api, token)
            assert (sin_codigo.status_code, sin_codigo.json()["error"]["codigo"]) == (
                400,
                "mfa_codigo_invalido",
            )
            reloj_t[0] += 30
            con_codigo = confirmar(api, token, codigo_mfa=pyotp.TOTP(secreto).at(int(reloj_t[0])))
            assert con_codigo.status_code == 204
        finally:
            mfa.time = original
