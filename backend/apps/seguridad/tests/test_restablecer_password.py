"""Restablecimiento de contraseña por un administrador (usuario sin acceso a su correo)."""

import pytest
from django.contrib.auth.password_validation import validate_password

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.seguridad.models import MotivoRevocacion, Sesion, Usuario
from apps.seguridad.services import gestion_usuarios as gestion
from apps.seguridad.tests.conftest import PASSWORD, cliente_de, iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def olvidadizo(rbac, nuevo_usuario):
    return nuevo_usuario(rbac.org_a, "olvidadizo", [rbac.emp_a1], [("VENDEDOR", None)])


def restablecer(api, usuario):
    return api.post(f"{BASE}/usuarios/{usuario.pk}/restablecer-password/")


class TestGeneracion:
    def test_la_clave_generada_cumple_la_politica_y_es_distinta_cada_vez(self, olvidadizo):
        claves = {gestion.generar_password_temporal(olvidadizo) for _ in range(30)}
        assert len(claves) == 30
        for clave in claves:
            validate_password(clave, olvidadizo)
            assert len(clave) >= 14
            assert not set(clave) & set("0O1lI")  # sin caracteres ambiguos


class TestRestablecer:
    def test_admin_restablece_y_el_usuario_entra_con_la_temporal(
        self, rbac, nuevo_usuario, olvidadizo
    ):
        nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        sesion_vieja = iniciar_sesion(cliente_de_api(), "olvidadizo")
        assert sesion_vieja.status_code == 200

        r = restablecer(cliente_de("jefe"), olvidadizo)
        assert r.status_code == 200, r.content
        assert r["Cache-Control"] == "no-store"
        temporal = r.json()["password_temporal"]

        olvidadizo.refresh_from_db()
        assert olvidadizo.debe_cambiar_password is True
        assert olvidadizo.check_password(temporal)
        # La contraseña anterior ya no sirve y las sesiones abiertas quedaron cerradas.
        assert iniciar_sesion(cliente_de_api(), "olvidadizo", PASSWORD).status_code == 401
        assert Sesion.objects.filter(
            usuario=olvidadizo, motivo_revocacion=MotivoRevocacion.CLAVE_RESTABLECIDA
        ).exists()
        entrada = iniciar_sesion(cliente_de_api(), "olvidadizo", temporal)
        assert entrada.status_code == 200
        assert entrada.json()["usuario"]["debe_cambiar_password"] is True

    def test_superadmin_tambien_puede(self, rbac, nuevo_usuario, olvidadizo):
        nuevo_usuario(rbac.org_a, "dueno", [rbac.emp_a1], [("SUPERADMIN", None)])
        assert restablecer(cliente_de("dueno"), olvidadizo).status_code == 200

    def test_deja_auditoria_sin_la_clave(self, rbac, nuevo_usuario, olvidadizo):
        nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        temporal = restablecer(cliente_de("jefe"), olvidadizo).json()["password_temporal"]
        evento = AuditoriaEvento.objects.get(accion="password.restablecida_admin")
        assert evento.recurso_id == str(olvidadizo.pk)
        assert temporal not in str(evento.__dict__)

    def test_no_se_puede_reutilizar_la_clave_vieja_como_nueva(
        self, rbac, nuevo_usuario, olvidadizo
    ):
        """La temporal entra en el historial: no se puede 'cambiar' a ella otra vez."""
        nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        temporal = restablecer(cliente_de("jefe"), olvidadizo).json()["password_temporal"]
        api = cliente_de_api()
        acceso = iniciar_sesion(api, "olvidadizo", temporal).json()["access"]
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {acceso}")
        r = api.post(
            f"{BASE}/auth/cambiar-password/", {"actual": temporal, "nueva": temporal}, format="json"
        )
        assert r.status_code == 400


class TestRestricciones:
    def test_sin_permiso_no_puede(self, rbac, nuevo_usuario, olvidadizo):
        nuevo_usuario(rbac.org_a, "vendedor2", [rbac.emp_a1], [("VENDEDOR", None)])
        assert restablecer(cliente_de("vendedor2"), olvidadizo).status_code == 403
        olvidadizo.refresh_from_db()
        assert olvidadizo.check_password(PASSWORD)

    def test_editar_usuarios_no_basta_hace_falta_el_permiso_propio(
        self, rbac, nuevo_usuario, olvidadizo
    ):
        jefe = nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        # Quitamos la capacidad al ADMIN de esta organización y comprobamos el rechazo.
        from apps.seguridad.models import Rol, RolPermiso

        admin = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="ADMIN")
        RolPermiso.objects.sin_ambito().filter(
            rol=admin, permiso__codigo=gestion.RESTABLECER_CLAVE
        ).delete()
        from apps.seguridad.services import permisos_engine as motor

        motor.invalidar_usuario(jefe.pk)
        assert restablecer(cliente_de("jefe"), olvidadizo).status_code == 403

    def test_no_sobre_si_mismo(self, rbac, nuevo_usuario):
        jefe = nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        r = restablecer(cliente_de("jefe"), jefe)
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "operacion_sobre_si_mismo")

    def test_admin_no_restablece_a_un_superadmin(self, rbac, nuevo_usuario):
        dueno = nuevo_usuario(rbac.org_a, "dueno", [rbac.emp_a1], [("SUPERADMIN", None)])
        nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        r = restablecer(cliente_de("jefe"), dueno)
        assert (r.status_code, r.json()["error"]["codigo"]) == (
            403,
            "usuario_con_mas_privilegios",
        )
        dueno.refresh_from_db()
        assert dueno.check_password(PASSWORD)

    def test_no_cruza_organizaciones(self, rbac, nuevo_usuario):
        ajeno = nuevo_usuario(rbac.org_b, "ajeno", [rbac.emp_b1], [("VENDEDOR", None)])
        nuevo_usuario(rbac.org_a, "jefe", [rbac.emp_a1], [("ADMIN", None)])
        assert restablecer(cliente_de("jefe"), ajeno).status_code == 404
        assert Usuario.objects.get(pk=ajeno.pk).check_password(PASSWORD)

    def test_exige_autenticacion(self, olvidadizo):
        assert restablecer(cliente_de_api(), olvidadizo).status_code == 401


def cliente_de_api():
    from rest_framework.test import APIClient

    return APIClient()
