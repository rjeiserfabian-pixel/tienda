from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.organizacion.models import Estado
from apps.seguridad.models import AccesoEmpresa, Sesion
from apps.seguridad.services.usuarios import crear_admin_plataforma
from apps.seguridad.tests.conftest import PASSWORD, autenticar

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/seguridad/auth/login/"


class TestLoginCorrecto:
    def test_devuelve_access_y_las_empresas_permitidas(self, usuario_a, escenario, login):
        r = login(plataforma="MOVIL")
        assert r.status_code == 200
        cuerpo = r.json()
        assert {e["id"] for e in cuerpo["empresas"]} == {escenario.emp_a1.pk, escenario.emp_a2.pk}
        assert cuerpo["organizacion"]["id"] == escenario.org_a.pk
        assert cuerpo["usuario"]["email"] == "ana@ejemplo.com"
        assert "password" not in cuerpo["usuario"]

    def test_el_access_lleva_org_y_empresas_habilitadas(self, usuario_a, escenario, login):
        access = AccessToken(login(plataforma="MOVIL").json()["access"])
        assert access["org_id"] == escenario.org_a.pk
        assert set(access["empresas"]) == {escenario.emp_a1.pk, escenario.emp_a2.pk}
        assert access["user_id"] == str(usuario_a.pk)

    def test_web_entrega_el_refresh_solo_en_cookie_httponly(self, usuario_a, login):
        r = login(plataforma="WEB")
        assert "refresh" not in r.json()
        cookie = r.cookies["refresh_token"]
        assert cookie["httponly"] is True
        assert cookie["samesite"] == "Strict"
        assert cookie["path"] == "/api/v1/seguridad/auth/"

    def test_movil_recibe_el_refresh_en_el_cuerpo_y_sin_cookie(self, usuario_a, login):
        r = login(plataforma="MOVIL", dispositivo="Pixel 8", push_token="tok-123")
        assert r.json()["refresh"]
        assert "refresh_token" not in r.cookies
        sesion = Sesion.objects.get()
        assert (sesion.dispositivo, sesion.push_token) == ("Pixel 8", "tok-123")

    def test_se_puede_entrar_con_correo_en_cualquier_capitalizacion(self, usuario_a, login):
        assert login(identificador="ANA@ejemplo.COM").status_code == 200
        assert login(identificador="ANA").status_code == 200

    def test_no_se_expone_el_push_token_en_la_sesion_listada(self, usuario_a, api, login):
        autenticar(api, login(plataforma="MOVIL", push_token="secreto").json()["access"])
        assert "secreto" not in api.get("/api/v1/seguridad/sesiones/").content.decode()


class TestLoginRechazado:
    def test_mismo_mensaje_para_usuario_inexistente_y_clave_incorrecta(self, usuario_a, login):
        inexistente = login(identificador="nadie", password="x" * 12)
        equivocada = login(password="otra-clave-cualquiera")
        assert inexistente.status_code == equivocada.status_code == 401
        a, b = inexistente.json()["error"], equivocada.json()["error"]
        assert (a["codigo"], a["mensaje"]) == (b["codigo"], b["mensaje"])

    def test_usuario_desactivado_no_entra_y_el_mensaje_no_lo_delata(self, usuario_a, login):
        usuario_a.is_active = False
        usuario_a.save()
        r = login()
        assert r.status_code == 401
        assert r.json()["error"]["codigo"] == "credenciales_invalidas"

    def test_sin_accesos_a_empresas(self, usuario_a, login):
        AccesoEmpresa.objects.sin_ambito().filter(usuario=usuario_a).update(estado=Estado.INACTIVO)
        r = login()
        assert r.status_code == 403
        assert r.json()["error"]["codigo"] == "sin_acceso_empresas"

    def test_organizacion_suspendida(self, usuario_a, escenario, login):
        escenario.org_a.estado = Estado.SUSPENDIDO
        escenario.org_a.save()
        assert login().json()["error"]["codigo"] == "organizacion_inactiva"

    def test_datos_incompletos(self, api):
        r = api.post(LOGIN, {"identificador": "ana"}, format="json")
        assert r.status_code == 400
        assert r.json()["error"]["codigo"] == "validacion"


class TestEmpresasHabilitadas:
    def test_un_acceso_vencido_o_inactivo_deja_de_contar(self, usuario_a, escenario, login):
        accesos = AccesoEmpresa.objects.sin_ambito().filter(usuario=usuario_a)
        accesos.filter(empresa=escenario.emp_a1).update(
            vigente_hasta=timezone.now() - timedelta(minutes=1)
        )
        ids = [e["id"] for e in login().json()["empresas"]]
        assert ids == [escenario.emp_a2.pk]

    def test_una_empresa_inactiva_no_se_habilita(self, usuario_a, escenario, login):
        escenario.emp_a2.estado = Estado.INACTIVO
        escenario.emp_a2.save()
        assert [e["id"] for e in login().json()["empresas"]] == [escenario.emp_a1.pk]

    def test_un_acceso_futuro_si_cuenta(self, usuario_a, escenario, login):
        AccesoEmpresa.objects.sin_ambito().filter(usuario=usuario_a).update(
            vigente_hasta=timezone.now() + timedelta(days=1)
        )
        assert len(login().json()["empresas"]) == 2


class TestAdminPlataforma:
    def test_entra_sin_organizacion_ni_empresas(self, api):
        crear_admin_plataforma(username="root", email="root@x.com", password=PASSWORD)
        r = api.post(LOGIN, {"identificador": "root", "password": PASSWORD}, format="json")
        assert r.status_code == 200
        cuerpo = r.json()
        assert cuerpo["organizacion"] is None and cuerpo["empresas"] == []
        assert AccessToken(cuerpo["access"])["org_id"] is None


class TestBloqueoProgresivo:
    def _fallar(self, login, veces, identificador="ana"):
        return [
            login(identificador=identificador, password="incorrecta-123").status_code
            for _ in range(veces)
        ]

    def test_bloquea_al_quinto_fallo_incluso_con_la_clave_correcta(self, usuario_a, login):
        assert self._fallar(login, 5) == [401] * 5
        r = login()  # clave correcta, pero la cuenta está en pausa
        assert r.status_code == 429
        assert int(r["Retry-After"]) >= 1
        assert r.json()["error"]["codigo"] == "login_bloqueado"

    def test_un_login_correcto_antes_del_umbral_reinicia_el_conteo(self, usuario_a, login):
        self._fallar(login, 4)
        assert login().status_code == 200
        assert self._fallar(login, 4) == [401] * 4
        assert login().status_code == 200

    def test_el_bloqueo_crece_con_cada_fallo(self, usuario_a, login):
        self._fallar(login, 5)
        primero = int(login()["Retry-After"])
        # Se fuerza el vencimiento del bloqueo para seguir fallando y ver la escalada.
        from django.core.cache import cache

        from apps.seguridad.services.auth import _claves_bloqueo

        cache.delete(_claves_bloqueo("ana")[1])
        self._fallar(login, 1)
        assert int(login()["Retry-After"]) > primero

    def test_tambien_se_bloquea_un_usuario_inexistente(self, login):
        """Evita enumerar cuentas: el comportamiento es idéntico al de una cuenta real."""
        assert self._fallar(login, 5, "fantasma") == [401] * 5
        assert login(identificador="fantasma").status_code == 429

    def test_el_bloqueo_de_un_usuario_no_afecta_a_otro(self, usuario_a, escenario, login):
        from apps.seguridad.services.usuarios import crear_usuario

        crear_usuario(
            organizacion=escenario.org_a,
            username="beto",
            email="beto@x.com",
            password=PASSWORD,
            empresa_ids=[escenario.emp_a1.pk],
        )
        self._fallar(login, 5)
        assert login(identificador="beto").status_code == 200


def test_el_throttle_por_ip_limita_el_login(api, monkeypatch):
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "login", "3/min")
    estados = [
        api.post(LOGIN, {"identificador": f"u{i}", "password": "x"}, format="json").status_code
        for i in range(5)
    ]
    assert estados == [401, 401, 401, 429, 429]
