"""«Mantener sesión activa»: cookie persistente o de sesión, y caducidad de la sesión."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.seguridad.models import Sesion
from apps.seguridad.tests.conftest import iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


def entrar(api, **extra):
    return iniciar_sesion(api, "ana", plataforma="WEB", **extra)


def cookie(respuesta):
    return respuesta.cookies["refresh_token"]


def test_por_defecto_la_sesion_es_persistente(usuario_a, api, settings):
    r = entrar(api)
    assert r.status_code == 200
    assert cookie(r)["max-age"] == settings.REFRESH_TOKEN_DIAS * 24 * 3600
    sesion = Sesion.objects.get()
    assert sesion.persistente
    assert sesion.expira_en > timezone.now() + timedelta(days=settings.REFRESH_TOKEN_DIAS - 1)


def test_sin_recordar_la_cookie_es_de_sesion_y_caduca_antes(usuario_a, api, settings):
    r = entrar(api, recordar=False)
    assert r.status_code == 200
    assert cookie(r)["max-age"] == ""  # se borra al cerrar el navegador
    assert cookie(r)["httponly"]
    sesion = Sesion.objects.get()
    assert not sesion.persistente
    limite = timezone.now() + timedelta(hours=settings.SESION_NO_PERSISTENTE_HORAS, minutes=1)
    assert sesion.expira_en < limite


def test_la_renovacion_conserva_la_preferencia(usuario_a, api):
    entrar(api, recordar=False)
    renovada = api.post(f"{BASE}/auth/refresh/", {}, format="json")
    assert renovada.status_code == 200
    assert cookie(renovada)["max-age"] == ""
    sesion = Sesion.objects.get()
    assert sesion.expira_en < timezone.now() + timedelta(hours=13)


def test_el_valor_de_recordar_pasa_por_el_segundo_factor(rbac, nuevo_usuario, api, monkeypatch):
    import pyotp

    from apps.seguridad.services import mfa

    class Reloj:
        t = 1_800_000_000.0

        def time(self):
            return self.t

    reloj = Reloj()
    monkeypatch.setattr(mfa, "time", reloj)
    usuario = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], [("VENDEDOR", None)])
    secreto = mfa.iniciar_configuracion(usuario, "Clave-Segura-2026!")["secreto"]
    mfa.confirmar_configuracion(usuario, pyotp.TOTP(secreto).at(int(reloj.t)))
    desafio = entrar(api, recordar=False).json()["desafio"]
    reloj.t += 30
    r = api.post(
        f"{BASE}/auth/mfa/verificar/",
        {"desafio": desafio, "codigo": pyotp.TOTP(secreto).at(int(reloj.t))},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert cookie(r)["max-age"] == ""
    assert not Sesion.objects.get(usuario=usuario).persistente
