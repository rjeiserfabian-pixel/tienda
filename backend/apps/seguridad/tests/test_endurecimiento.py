"""Endurecimiento: bloqueo de la API por clave temporal, cabeceras y tareas de retención."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.seguridad.models import MotivoRevocacion, Sesion, TokenRecuperacion
from apps.seguridad.services.usuarios import crear_usuario
from apps.seguridad.tasks import purgar_sesiones
from apps.seguridad.tests.conftest import PASSWORD, cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


@pytest.fixture
def temporal(rbac, nuevo_usuario):
    """Usuario ADMIN cuya contraseña es temporal (alta desde el panel)."""
    crear_usuario(
        organizacion=rbac.org_a,
        username="temporal",
        email="temporal@ejemplo.com",
        password=PASSWORD,
        empresa_ids=[rbac.emp_a1.pk],
        debe_cambiar_password=True,
    )
    from apps.seguridad.models import Usuario
    from apps.seguridad.services.roles import asignar_rol_de_sistema

    asignar_rol_de_sistema(Usuario.objects.get(username="temporal"), "ADMIN")
    return rbac


class TestClaveTemporal:
    def test_la_api_bloquea_todo_salvo_cambiar_la_clave(self, temporal):
        api = cliente_de("temporal")
        for ruta in (f"{BASE}/usuarios/", f"{BASE}/roles/", "/api/v1/organizacion/empresas/"):
            r = api.get(ruta)
            assert (r.status_code, r.json()["error"]["codigo"]) == (
                403,
                "cambio_password_requerido",
            )
        # Lo mínimo para resolver la situación sigue disponible.
        assert api.get(f"{BASE}/me/").status_code == 200
        assert api.get(f"{BASE}/menu/").status_code == 200
        assert api.get(f"{BASE}/permisos/mios/").status_code == 200

    def test_al_cambiarla_se_levanta_el_bloqueo(self, temporal):
        api = cliente_de("temporal")
        r = api.post(
            f"{BASE}/auth/cambiar-password/",
            {"actual": PASSWORD, "nueva": "Clave-Definitiva-2027!"},
            format="json",
        )
        assert r.status_code == 204
        assert api.get(f"{BASE}/usuarios/").status_code == 200

    def test_las_sesiones_tambien_quedan_bloqueadas(self, temporal):
        api = cliente_de("temporal")
        assert api.get(f"{BASE}/sesiones/").status_code == 403

    def test_un_usuario_normal_no_se_ve_afectado(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "normal", [rbac.emp_a1], [("ADMIN", None)])
        assert cliente_de("normal").get(f"{BASE}/usuarios/").status_code == 200


class TestCabeceras:
    def test_las_respuestas_de_la_api_no_se_cachean_ni_incrustan(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "normal", [rbac.emp_a1], [("ADMIN", None)])
        r = cliente_de("normal").get(f"{BASE}/me/")
        assert r["Cache-Control"] == "no-store"
        assert r["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert "camera=()" in r["Permissions-Policy"]
        assert r["X-Content-Type-Options"] == "nosniff"

    def test_tambien_en_errores(self, api):
        r = api.get(f"{BASE}/me/")
        assert r.status_code == 401
        assert r["Cache-Control"] == "no-store"

    def test_la_documentacion_queda_fuera_de_la_politica_estricta(self, api):
        r = api.get("/api/v1/docs/")
        assert "default-src 'none'" not in r.get("Content-Security-Policy", "")


class TestRetencion:
    def test_se_purgan_sesiones_viejas_y_tokens_vencidos(self, rbac, nuevo_usuario, settings):
        settings.SESIONES_RETENCION_DIAS = 30
        usuario = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        ahora = timezone.now()

        def sesion(**campos):
            return Sesion.objects.create(
                usuario=usuario,
                plataforma="WEB",
                jti_actual="x",
                ultimo_uso=ahora,
                expira_en=campos.pop("expira_en", ahora + timedelta(days=5)),
                **campos,
            )

        activa = sesion()
        revocada_vieja = sesion(
            revocada=True,
            revocada_en=ahora - timedelta(days=40),
            motivo_revocacion=MotivoRevocacion.LOGOUT,
        )
        revocada_reciente = sesion(revocada=True, revocada_en=ahora - timedelta(days=2))
        vencida_vieja = sesion(expira_en=ahora - timedelta(days=40))
        TokenRecuperacion.objects.create(
            usuario=usuario, huella="a" * 64, expira_en=ahora - timedelta(hours=1)
        )
        vigente = TokenRecuperacion.objects.create(
            usuario=usuario, huella="b" * 64, expira_en=ahora + timedelta(hours=1)
        )

        resultado = purgar_sesiones()
        assert resultado == {"sesiones": 2, "tokens": 1}
        quedan = set(Sesion.objects.values_list("pk", flat=True))
        assert quedan == {activa.pk, revocada_reciente.pk}
        assert {revocada_vieja.pk, vencida_vieja.pk}.isdisjoint(quedan)
        assert TokenRecuperacion.objects.get().pk == vigente.pk
