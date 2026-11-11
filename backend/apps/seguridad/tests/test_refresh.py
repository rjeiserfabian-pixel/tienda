"""Refresh rotativo: rotación, reutilización, concurrencia, expiración y revocación."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.seguridad.models import MotivoRevocacion, Sesion
from apps.seguridad.tests.conftest import autenticar

pytestmark = pytest.mark.django_db

REFRESH = "/api/v1/seguridad/auth/refresh/"


@pytest.fixture
def sesion_movil(usuario_a, login):
    return login(plataforma="MOVIL").json()


def refrescar(api, token):
    return api.post(REFRESH, {"refresh": token}, format="json")


class TestRotacion:
    def test_entrega_un_par_nuevo_y_el_anterior_queda_obsoleto(self, api, sesion_movil):
        r = refrescar(api, sesion_movil["refresh"])
        assert r.status_code == 200
        nuevo = r.json()
        assert nuevo["refresh"] != sesion_movil["refresh"]
        assert nuevo["access"] and nuevo["sesion_id"] == sesion_movil["sesion_id"]

    def test_la_cadena_sigue_funcionando_con_el_ultimo_token(self, api, sesion_movil):
        token = sesion_movil["refresh"]
        for _ in range(3):
            token = refrescar(api, token).json()["refresh"]
        assert refrescar(api, token).status_code == 200

    def test_web_rota_la_cookie_sin_exponer_el_refresh(self, usuario_a, api, login):
        login(plataforma="WEB")
        r = api.post(REFRESH, {}, format="json")  # el cliente envía la cookie solo
        assert r.status_code == 200
        assert "refresh" not in r.json()
        assert r.cookies["refresh_token"].value

    def test_refresca_las_empresas_con_los_accesos_actuales(self, api, escenario, sesion_movil):
        from apps.seguridad.models import AccesoEmpresa

        AccesoEmpresa.objects.sin_ambito().filter(empresa=escenario.emp_a2).update(
            estado="INACTIVO"
        )
        r = refrescar(api, sesion_movil["refresh"]).json()
        assert [e["id"] for e in r["empresas"]] == [escenario.emp_a1.pk]


class TestReutilizacion:
    def test_reusar_un_token_viejo_revoca_toda_la_cadena(self, api, sesion_movil):
        viejo = sesion_movil["refresh"]
        vigente = refrescar(api, viejo).json()["refresh"]
        # Pasada la ventana de gracia, presentar el viejo se considera robo.
        Sesion.objects.update(rotado_en=timezone.now() - timedelta(minutes=5))

        assert refrescar(api, viejo).status_code == 401
        sesion = Sesion.objects.get()
        assert sesion.revocada and sesion.motivo_revocacion == MotivoRevocacion.REUSO
        # Incluso el token legítimo más reciente deja de servir.
        assert refrescar(api, vigente).status_code == 401

    def test_dos_refrescos_casi_simultaneos_no_revocan_la_sesion(self, api, sesion_movil):
        viejo = sesion_movil["refresh"]
        refrescar(api, viejo)
        r = refrescar(api, viejo)  # dentro de la ventana de gracia (dos pestañas)
        assert r.status_code == 409
        assert r.json()["error"]["codigo"] == "refresh_concurrente"
        assert Sesion.objects.get().revocada is False


class TestRechazos:
    @pytest.mark.parametrize("token", ["", "basura", "a.b.c"])
    def test_tokens_malformados(self, api, token):
        r = refrescar(api, token)
        assert r.status_code == 401
        assert r.json()["error"]["codigo"] == "sesion_invalida"

    def test_un_access_token_no_sirve_como_refresh(self, api, sesion_movil):
        assert refrescar(api, sesion_movil["access"]).status_code == 401

    def test_sesion_revocada(self, api, sesion_movil):
        Sesion.objects.update(revocada=True)
        assert refrescar(api, sesion_movil["refresh"]).status_code == 401

    def test_sesion_expirada_se_revoca(self, api, sesion_movil):
        Sesion.objects.update(expira_en=timezone.now() - timedelta(seconds=1))
        assert refrescar(api, sesion_movil["refresh"]).status_code == 401
        assert Sesion.objects.get().motivo_revocacion == MotivoRevocacion.EXPIRADA

    def test_tope_absoluto_de_la_sesion(self, api, sesion_movil, settings):
        Sesion.objects.update(
            creado_en=timezone.now() - timedelta(days=settings.SESION_MAXIMA_DIAS + 1)
        )
        assert refrescar(api, sesion_movil["refresh"]).status_code == 401

    def test_usuario_desactivado_no_puede_refrescar(self, api, usuario_a, sesion_movil):
        usuario_a.is_active = False
        usuario_a.save()
        assert refrescar(api, sesion_movil["refresh"]).status_code == 401

    def test_sin_accesos_vigentes_no_refresca(self, api, sesion_movil):
        from apps.seguridad.models import AccesoEmpresa

        AccesoEmpresa.objects.sin_ambito().update(estado="INACTIVO")
        r = refrescar(api, sesion_movil["refresh"])
        assert r.status_code == 403
        assert Sesion.objects.get().revocada is True

    def test_el_token_de_una_sesion_ajena_no_sirve_con_otro_usuario(
        self, api, usuario_a, escenario, sesion_movil
    ):
        """El refresh está ligado a (usuario, sesión): no se puede cruzar."""
        from apps.seguridad.services.usuarios import crear_usuario
        from apps.seguridad.tests.conftest import PASSWORD

        crear_usuario(
            organizacion=escenario.org_a,
            username="beto",
            email="b@x.com",
            password=PASSWORD,
            empresa_ids=[escenario.emp_a1.pk],
        )
        Sesion.objects.update(usuario=usuario_a.__class__.objects.get(username="beto"))
        assert refrescar(api, sesion_movil["refresh"]).status_code == 401


def test_el_access_de_una_sesion_cerrada_se_rechaza_al_instante(api, sesion_movil):
    autenticar(api, sesion_movil["access"])
    assert api.get("/api/v1/seguridad/me/").status_code == 200
    assert api.post("/api/v1/seguridad/auth/logout/").status_code == 204
    assert api.get("/api/v1/seguridad/me/").status_code == 401
