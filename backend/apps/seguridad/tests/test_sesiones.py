"""Logout simple y global, revocación remota, contexto de tenant y consultas."""

import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from apps.core.tenant import limpiar_contexto, obtener_contexto
from apps.seguridad.authentication import JWTAutenticacion
from apps.seguridad.models import MotivoRevocacion, Sesion
from apps.seguridad.services.usuarios import crear_usuario, desactivar_usuario
from apps.seguridad.tests.conftest import PASSWORD, autenticar, iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


@pytest.fixture
def dos_dispositivos(usuario_a):
    """Dos sesiones del mismo usuario: (cliente_movil, datos_movil, cliente_web, datos_web)."""
    movil, web = APIClient(), APIClient()
    d_movil = iniciar_sesion(movil, plataforma="MOVIL", dispositivo="Pixel").json()
    d_web = iniciar_sesion(web, plataforma="WEB", dispositivo="Chrome").json()
    autenticar(movil, d_movil["access"])
    autenticar(web, d_web["access"])
    return movil, d_movil, web, d_web


class TestLogout:
    def test_logout_cierra_solo_la_sesion_actual(self, dos_dispositivos):
        movil, d_movil, web, d_web = dos_dispositivos
        assert movil.post(f"{BASE}/auth/logout/").status_code == 204
        assert Sesion.objects.get(pk=d_movil["sesion_id"]).revocada
        assert not Sesion.objects.get(pk=d_web["sesion_id"]).revocada
        assert web.get(f"{BASE}/me/").status_code == 200

    def test_logout_global_cierra_todas(self, dos_dispositivos):
        movil, _, web, _ = dos_dispositivos
        assert movil.post(f"{BASE}/auth/logout-global/").status_code == 204
        assert not Sesion.objects.filter(revocada=False).exists()
        assert web.get(f"{BASE}/me/").status_code == 401
        assert Sesion.objects.first().motivo_revocacion == MotivoRevocacion.LOGOUT_GLOBAL

    def test_logout_web_borra_la_cookie(self, dos_dispositivos):
        _, _, web, _ = dos_dispositivos
        r = web.post(f"{BASE}/auth/logout/")
        assert r.cookies["refresh_token"].value == ""

    def test_exige_autenticacion(self, api):
        assert api.post(f"{BASE}/auth/logout/").status_code == 401


class TestRevocacionRemota:
    def test_se_ve_y_se_revoca_una_sesion_de_otro_dispositivo(self, dos_dispositivos):
        movil, d_movil, web, d_web = dos_dispositivos
        lista = web.get(f"{BASE}/sesiones/").json()
        assert len(lista["results"]) == 2
        actual = [s for s in lista["results"] if s["actual"]]
        assert [s["id"] for s in actual] == [d_web["sesion_id"]]

        assert web.delete(f"{BASE}/sesiones/{d_movil['sesion_id']}/").status_code == 204
        assert movil.get(f"{BASE}/me/").status_code == 401  # el access se rechaza al instante
        assert (
            Sesion.objects.get(pk=d_movil["sesion_id"]).motivo_revocacion == MotivoRevocacion.REMOTA
        )
        assert len(web.get(f"{BASE}/sesiones/").json()["results"]) == 1

    def test_cerrar_las_demas_conserva_la_sesion_actual(self, dos_dispositivos):
        movil, d_movil, web, d_web = dos_dispositivos
        r = web.delete(f"{BASE}/sesiones/otras/")
        assert r.status_code == 200
        assert r.json() == {"cerradas": 1}
        assert Sesion.objects.get(pk=d_movil["sesion_id"]).revocada
        assert not Sesion.objects.get(pk=d_web["sesion_id"]).revocada
        assert movil.get(f"{BASE}/me/").status_code == 401
        assert web.get(f"{BASE}/me/").status_code == 200

    def test_el_refresh_de_la_sesion_revocada_ya_no_sirve(self, dos_dispositivos, api):
        _, d_movil, web, _ = dos_dispositivos
        web.delete(f"{BASE}/sesiones/{d_movil['sesion_id']}/")
        r = api.post(f"{BASE}/auth/refresh/", {"refresh": d_movil["refresh"]}, format="json")
        assert r.status_code == 401

    def test_no_se_puede_revocar_la_sesion_de_otro_usuario(self, dos_dispositivos, escenario):
        _, _, web, _ = dos_dispositivos
        crear_usuario(
            organizacion=escenario.org_a,
            username="beto",
            email="b@x.com",
            password=PASSWORD,
            empresa_ids=[escenario.emp_a1.pk],
        )
        ajena = iniciar_sesion(APIClient(), "beto").json()["sesion_id"]
        assert web.delete(f"{BASE}/sesiones/{ajena}/").status_code == 404
        assert Sesion.objects.get(pk=ajena).revocada is False

    def test_sesion_inexistente(self, dos_dispositivos):
        _, _, web, _ = dos_dispositivos
        assert web.delete(f"{BASE}/sesiones/{uuid.uuid4()}/").status_code == 404

    def test_el_listado_solo_muestra_sesiones_propias_y_paginadas(
        self, dos_dispositivos, escenario
    ):
        _, _, web, _ = dos_dispositivos
        crear_usuario(
            organizacion=escenario.org_a,
            username="beto",
            email="b@x.com",
            password=PASSWORD,
            empresa_ids=[escenario.emp_a1.pk],
        )
        iniciar_sesion(APIClient(), "beto")
        cuerpo = web.get(f"{BASE}/sesiones/").json()
        assert {"count", "next", "previous", "results"} <= cuerpo.keys()
        assert (cuerpo["count"], len(cuerpo["results"])) == (2, 2)

    def test_pagina_con_numeros_20_por_defecto(self, usuario_a, dos_dispositivos):
        web = dos_dispositivos[2]
        for _ in range(23):
            iniciar_sesion(APIClient(), "ana")
        primera = web.get(f"{BASE}/sesiones/").json()
        assert (primera["count"], len(primera["results"])) == (25, 20)
        segunda = web.get(f"{BASE}/sesiones/", {"page": 2}).json()
        assert len(segunda["results"]) == 5
        ids = [s["id"] for s in primera["results"] + segunda["results"]]
        assert len(ids) == len(set(ids)) == 25  # sin repetidos ni saltos
        pequena = web.get(f"{BASE}/sesiones/", {"page_size": 10}).json()
        assert len(pequena["results"]) == 10
        fuera_de_catalogo = web.get(f"{BASE}/sesiones/", {"page_size": 7}).json()
        assert len(fuera_de_catalogo["results"]) == 20


class TestDesactivacion:
    def test_desactivar_cierra_todas_las_sesiones_y_conserva_el_historial(
        self, usuario_a, dos_dispositivos
    ):
        movil, _, _, _ = dos_dispositivos
        assert desactivar_usuario(usuario_a) == 2
        assert Sesion.objects.filter(usuario=usuario_a).count() == 2  # no se borra nada
        assert not Sesion.objects.filter(revocada=False).exists()
        assert movil.get(f"{BASE}/me/").status_code == 401

    def test_desactivar_por_cualquier_via_tambien_revoca(self, usuario_a, dos_dispositivos):
        usuario_a.is_active = False
        usuario_a.save()  # p. ej. desde el admin o un shell
        assert not Sesion.objects.filter(revocada=False).exists()


class TestContextoDeTenant:
    def _autenticar_request(self, access):
        peticion = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {access}")
        return JWTAutenticacion().authenticate(Request(peticion))

    def test_el_access_activa_organizacion_y_empresas_del_contexto(
        self, usuario_a, escenario, login
    ):
        access = login(plataforma="MOVIL").json()["access"]
        self._autenticar_request(access)
        contexto = obtener_contexto()
        assert contexto.organizacion_id == escenario.org_a.pk
        assert contexto.empresa_ids == {escenario.emp_a1.pk, escenario.emp_a2.pk}
        assert contexto.usuario_id == usuario_a.pk
        limpiar_contexto()

    def test_el_contexto_no_sobrevive_a_la_peticion(self, usuario_a, api, login):
        autenticar(api, login(plataforma="MOVIL").json()["access"])
        api.get(f"{BASE}/me/")
        assert obtener_contexto() is None

    def test_un_token_con_organizacion_distinta_a_la_del_usuario_se_rechaza(
        self, usuario_a, escenario
    ):
        from rest_framework.exceptions import AuthenticationFailed

        from apps.seguridad.models import Sesion
        from apps.seguridad.services import sesiones, tokens

        sesion = sesiones.crear_sesion(
            usuario_a, plataforma="MOVIL", dispositivo="", user_agent="", ip=None, push_token=""
        )
        # Token falsificado en contenido: dice pertenecer a la organización B.
        usuario_a.organizacion_id = escenario.org_b.pk
        access, _ = tokens.emitir_tokens(
            usuario=usuario_a,
            sesion_id=sesion.pk,
            jti=sesion.jti_actual,
            empresa_ids=[escenario.emp_b1.pk],
        )
        usuario_a.organizacion_id = escenario.org_a.pk
        with pytest.raises(AuthenticationFailed):
            self._autenticar_request(access)
        assert obtener_contexto() is None
        assert Sesion.objects.count() == 1

    def test_un_token_sin_sesion_se_rechaza(self, usuario_a, api):
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken()
        token["user_id"] = str(usuario_a.pk)
        token["org_id"] = usuario_a.organizacion_id
        token["empresas"] = []
        autenticar(api, str(token))
        assert api.get(f"{BASE}/me/").status_code == 401

    def test_un_token_manipulado_se_rechaza(self, usuario_a, api, login):
        access = login(plataforma="MOVIL").json()["access"]
        cabeza, cuerpo, firma = access.split(".")
        autenticar(api, f"{cabeza}.{cuerpo}.{firma[::-1]}")
        assert api.get(f"{BASE}/me/").status_code == 401


class TestRendimiento:
    def test_me_no_hace_consultas_en_exceso(self, usuario_a, api, login):
        autenticar(api, login(plataforma="MOVIL").json()["access"])
        with CaptureQueriesContext(connection) as consultas:
            assert api.get(f"{BASE}/me/").status_code == 200
        assert len(consultas) <= 6

    def test_el_costo_no_crece_con_el_numero_de_empresas(self, escenario, api):
        from apps.organizacion.models import Empresa
        from apps.seguridad.tests.conftest import iniciar_sesion as entrar
        from conftest import ruc_valido

        extra = [
            Empresa.objects.sin_ambito()
            .create(
                organizacion=escenario.org_a,
                razon_social=f"E{i}",
                ruc=ruc_valido(f"20200000{i:02d}"),
            )
            .pk
            for i in range(10)
        ]
        crear_usuario(
            organizacion=escenario.org_a,
            username="multi",
            email="m@x.com",
            password=PASSWORD,
            empresa_ids=[escenario.emp_a1.pk, *extra],
        )
        crear_usuario(
            organizacion=escenario.org_a,
            username="solo",
            email="s@x.com",
            password=PASSWORD,
            empresa_ids=[escenario.emp_a1.pk],
        )

        def consultas_de_login(usuario):
            with CaptureQueriesContext(connection) as c:
                entrar(APIClient(), usuario)
            return len(c)

        consultas_de_login(
            "solo"
        )  # calentamiento: cargas de una sola vez (p. ej. la tarea de auditoría)
        assert consultas_de_login("multi") == consultas_de_login("solo")
