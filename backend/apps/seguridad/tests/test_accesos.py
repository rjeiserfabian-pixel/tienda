"""Aislamiento y consistencia de los accesos por empresa y sucursal."""

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from apps.core.exceptions import ViolacionAmbito
from apps.core.tenant import contexto_tenant
from apps.organizacion.models import Sucursal
from apps.seguridad.models import AccesoEmpresa, AccesoSucursal, Usuario
from apps.seguridad.services.usuarios import crear_admin_plataforma, crear_usuario
from apps.seguridad.tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


class TestAccesoEmpresa:
    def test_la_organizacion_se_deriva_de_la_empresa(self, usuario_a, escenario):
        acceso = AccesoEmpresa.objects.sin_ambito().filter(usuario=usuario_a).first()
        assert acceso.organizacion_id == escenario.org_a.pk

    def test_no_se_puede_dar_acceso_a_una_empresa_de_otra_organizacion(self, usuario_a, escenario):
        with pytest.raises(ViolacionAmbito):
            AccesoEmpresa(usuario=usuario_a, empresa=escenario.emp_b1).save()

    def test_no_se_puede_dar_acceso_a_un_usuario_de_otra_organizacion(self, usuario_a, escenario):
        with pytest.raises(ViolacionAmbito):
            AccesoEmpresa(
                usuario=usuario_a, empresa=escenario.emp_b1, organizacion=escenario.org_b
            ).save()

    def test_un_solo_acceso_por_usuario_y_empresa(self, usuario_a, escenario):
        with pytest.raises(IntegrityError), transaction.atomic():
            AccesoEmpresa(usuario=usuario_a, empresa=escenario.emp_a1).save()

    def test_los_accesos_respetan_el_aislamiento_por_organizacion(self, usuario_a, escenario):
        with contexto_tenant(escenario.org_b.pk, [escenario.emp_b1.pk]):
            assert AccesoEmpresa.objects.count() == 0
        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk]):
            assert AccesoEmpresa.objects.count() == 2


class TestAccesoSucursal:
    def _sucursal(self, empresa, codigo):
        return Sucursal.objects.sin_ambito().create(
            empresa=empresa, nombre=f"S{codigo}", codigo=codigo
        )

    def test_asigna_sucursales_de_la_misma_empresa(self, usuario_a, escenario):
        acceso = AccesoEmpresa.objects.sin_ambito().get(usuario=usuario_a, empresa=escenario.emp_a1)
        sucursal = self._sucursal(escenario.emp_a1, "010")
        AccesoSucursal(acceso_empresa=acceso, sucursal=sucursal).save()
        assert AccesoSucursal.objects.sin_ambito().filter(acceso_empresa=acceso).count() == 1

    def test_rechaza_una_sucursal_de_otra_empresa(self, usuario_a, escenario):
        acceso = AccesoEmpresa.objects.sin_ambito().get(usuario=usuario_a, empresa=escenario.emp_a1)
        ajena = self._sucursal(escenario.emp_a2, "020")
        with pytest.raises(ViolacionAmbito):
            AccesoSucursal(acceso_empresa=acceso, sucursal=ajena).save()

    def test_el_login_lista_solo_las_sucursales_asignadas(self, usuario_a, escenario, login):
        acceso = AccesoEmpresa.objects.sin_ambito().get(usuario=usuario_a, empresa=escenario.emp_a1)
        AccesoSucursal(
            acceso_empresa=acceso, sucursal=self._sucursal(escenario.emp_a1, "010")
        ).save()
        self._sucursal(escenario.emp_a1, "011")  # existe, pero no está asignada
        empresas = {e["id"]: e for e in login().json()["empresas"]}
        assert [s["codigo"] for s in empresas[escenario.emp_a1.pk]["sucursales"]] == ["010"]
        assert empresas[escenario.emp_a2.pk]["sucursales"] == []


class TestUsuarios:
    def test_el_correo_es_unico_sin_distinguir_mayusculas(self, usuario_a, escenario):
        with pytest.raises(ValidationError):
            crear_usuario(
                organizacion=escenario.org_a,
                username="otro",
                email="ANA@EJEMPLO.COM",
                password=PASSWORD,
                empresa_ids=[escenario.emp_a1.pk],
            )

    def test_el_username_no_admite_arroba(self, escenario):
        with pytest.raises(ValidationError):
            crear_usuario(
                organizacion=escenario.org_a,
                username="a@b",
                email="x@x.com",
                password=PASSWORD,
                empresa_ids=[escenario.emp_a1.pk],
            )

    def test_no_se_crea_con_una_empresa_de_otra_organizacion(self, escenario):
        with pytest.raises(ViolacionAmbito):
            crear_usuario(
                organizacion=escenario.org_a,
                username="x",
                email="x@x.com",
                password=PASSWORD,
                empresa_ids=[escenario.emp_b1.pk],
            )
        assert not Usuario.objects.filter(username="x").exists()  # todo o nada

    def test_la_clave_debe_ser_fuerte(self, escenario):
        with pytest.raises(ValidationError):
            crear_usuario(
                organizacion=escenario.org_a,
                username="x",
                email="x@x.com",
                password="123",
                empresa_ids=[escenario.emp_a1.pk],
            )

    def test_el_hasher_preferido_es_argon2(self):
        from config.settings import base

        assert base.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")

    def test_solo_un_admin_de_plataforma_puede_no_tener_organizacion(self, db):
        with pytest.raises(IntegrityError), transaction.atomic():
            Usuario.objects.create(username="huerfano", email="h@x.com")
        assert (
            crear_admin_plataforma(username="root", email="r@x.com", password=PASSWORD).organizacion
            is None
        )


class TestComandos:
    def test_crear_usuario(self, escenario, monkeypatch):
        monkeypatch.setenv("USUARIO_PASSWORD", PASSWORD)
        call_command(
            "crear_usuario",
            organizacion_id=escenario.org_a.pk,
            username="cmd",
            email="cmd@x.com",
            empresa_id=[escenario.emp_a1.pk],
        )
        assert AccesoEmpresa.objects.sin_ambito().filter(usuario__username="cmd").count() == 1

    def test_crear_usuario_con_organizacion_inexistente(self, monkeypatch):
        monkeypatch.setenv("USUARIO_PASSWORD", PASSWORD)
        with pytest.raises(CommandError):
            call_command("crear_usuario", organizacion_id=999999, username="x", email="x@x.com")

    def test_crear_admin_plataforma(self, db, monkeypatch):
        monkeypatch.setenv("USUARIO_PASSWORD", PASSWORD)
        call_command("crear_admin_plataforma", username="root", email="root@x.com")
        assert Usuario.objects.get(username="root").es_admin_plataforma
