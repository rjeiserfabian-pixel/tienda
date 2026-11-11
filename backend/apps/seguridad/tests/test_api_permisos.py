"""PermisoRBAC en vistas (incluida la operación con líneas de varias empresas) y endpoints RBAC."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from apps.core.tenant import contexto_tenant
from apps.core.tests.app_prueba.models import ItemEmpresa
from apps.seguridad import permisos_catalogo as cat
from apps.seguridad.permissions import PermisoRBAC
from apps.seguridad.tests.conftest import autenticar, iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


def cliente_de(usuario_nombre):
    api = APIClient()
    r = iniciar_sesion(api, usuario_nombre, plataforma="MOVIL")
    assert r.status_code == 200, r.content
    autenticar(api, r.json()["access"])
    return api


class VentaMixta(APIView):
    """Simula un cobro con líneas de varias empresas: guarda UN item por línea."""

    permission_classes = [IsAuthenticated, PermisoRBAC]
    permiso_requerido = "VENTAS.VENDER"

    def empresas_de_la_operacion(self, request):
        return [linea["empresa"] for linea in request.data["lineas"]]

    def post(self, request):
        for linea in request.data["lineas"]:
            ItemEmpresa.objects.create(empresa_id=linea["empresa"], nombre=linea["nombre"])
        return Response(status=status.HTTP_201_CREATED)


class VentaUnaEmpresa(APIView):
    permission_classes = [IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {"post": "VENTAS.VENDER", "get": "VENTAS.VER"}
    requiere_empresa = True

    def get(self, request):
        return Response({"alcances": request.alcances_permiso})

    def post(self, request):
        return Response(status=status.HTTP_201_CREATED)


class SinPermisoDeclarado(APIView):
    permission_classes = [IsAuthenticated, PermisoRBAC]

    def get(self, request):  # pragma: no cover - no debe alcanzarse
        return Response("secreto")


def invocar(vista, usuario, metodo="post", datos=None, query="", rbac=None, empresas=()):
    fabrica = APIRequestFactory()
    peticion = getattr(fabrica, metodo)(f"/{query}", datos, format="json")
    force_authenticate(peticion, user=usuario)
    # La autenticación JWT real activa el tenant; con force_authenticate se hace a mano.
    with contexto_tenant(
        usuario.organizacion_id, empresas or [e.pk for e in (rbac.emp_a1, rbac.emp_a2)], usuario.pk
    ):
        return vista.as_view()(peticion)


class TestOperacionMixta:
    def test_con_permiso_en_ambas_empresas_se_guardan_todas_las_lineas(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", None)])
        datos = {
            "lineas": [
                {"empresa": rbac.emp_a1.pk, "nombre": "x1"},
                {"empresa": rbac.emp_a2.pk, "nombre": "x2"},
            ]
        }
        assert invocar(VentaMixta, u, datos=datos, rbac=rbac).status_code == 201
        assert ItemEmpresa.objects.sin_ambito().count() == 2

    def test_si_falta_el_permiso_en_una_empresa_se_rechaza_todo_y_no_se_guarda_nada(
        self, rbac, nuevo_usuario
    ):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", rbac.emp_a1)]
        )  # vende en A1, pero no en A2
        datos = {
            "lineas": [
                {"empresa": rbac.emp_a1.pk, "nombre": "x1"},
                {"empresa": rbac.emp_a2.pk, "nombre": "x2"},
            ]
        }
        r = invocar(VentaMixta, u, datos=datos, rbac=rbac)
        assert r.status_code == 403
        assert r.data["error"]["codigo"] == "permiso_denegado"
        assert r.data["error"]["detalle"]["empresas"] == [rbac.emp_a2.pk]
        assert ItemEmpresa.objects.sin_ambito().count() == 0  # ni siquiera la línea de A1

    def test_una_empresa_sin_acceso_hace_fallar_toda_la_operacion(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        datos = {
            "lineas": [
                {"empresa": rbac.emp_a1.pk, "nombre": "x"},
                {"empresa": rbac.emp_a2.pk, "nombre": "y"},
            ]
        }
        assert invocar(VentaMixta, u, datos=datos, rbac=rbac).status_code == 403
        assert ItemEmpresa.objects.sin_ambito().count() == 0


class TestPermisoRBAC:
    def test_la_empresa_debe_declararse(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        r = invocar(VentaUnaEmpresa, u, "post", {}, rbac=rbac)
        assert r.status_code == 400 and r.data["error"]["codigo"] == "validacion"

    def test_empresa_invalida(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert invocar(VentaUnaEmpresa, u, "post", {"empresa": "abc"}, rbac=rbac).status_code == 400

    def test_el_permiso_depende_del_metodo_y_se_expone_el_alcance(self, rbac, nuevo_usuario):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1], roles=[("CONTADOR", None)]
        )  # VENTAS.VER sí, VENDER no
        empresa = rbac.emp_a1.pk
        assert (
            invocar(VentaUnaEmpresa, u, "post", {"empresa": empresa}, rbac=rbac).status_code == 403
        )
        r = invocar(VentaUnaEmpresa, u, "get", query=f"?empresa={empresa}", rbac=rbac)
        assert r.status_code == 200 and r.data["alcances"] == {empresa: "EMPRESA"}

    def test_sin_permiso_declarado_se_deniega(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("SUPERADMIN", None)])
        assert invocar(SinPermisoDeclarado, u, "get", rbac=rbac).status_code == 403

    def test_sin_autenticar(self, rbac):
        r = APIRequestFactory().get("/")
        assert SinPermisoDeclarado.as_view()(r).status_code in (401, 403)

    def test_un_usuario_sin_roles_no_pasa_en_ninguna_empresa(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        assert (
            invocar(VentaUnaEmpresa, u, "post", {"empresa": rbac.emp_a1.pk}, rbac=rbac).status_code
            == 403
        )


class TestMisPermisos:
    def test_por_empresa(self, rbac, nuevo_usuario):
        nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", rbac.emp_a1)]
        )
        api = cliente_de("ana")
        r = api.get(f"{BASE}/permisos/mios/?empresa={rbac.emp_a1.pk}")
        assert r.status_code == 200
        assert r.json()["permisos"]["VENTAS.VENDER"] == "EMPRESA"
        assert (
            api.get(f"{BASE}/permisos/mios/?empresa={rbac.emp_a2.pk}")
            .json()["permisos"]
            .get("VENTAS.VENDER")
            is None
        )

    def test_a_nivel_organizacion(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        r = cliente_de("ana").get(f"{BASE}/permisos/mios/")
        assert r.json()["empresa"] is None and "MANTENIMIENTO.CLIENTES.VER" in r.json()["permisos"]

    def test_una_empresa_sin_acceso_se_rechaza(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        api = cliente_de("ana")
        assert api.get(f"{BASE}/permisos/mios/?empresa={rbac.emp_a2.pk}").status_code == 403
        assert api.get(f"{BASE}/permisos/mios/?empresa={rbac.emp_b1.pk}").status_code == 403

    def test_exige_autenticacion(self, rbac):
        assert APIClient().get(f"{BASE}/permisos/mios/").status_code == 401


class TestMenu:
    def _rutas(self, nodos):
        for n in nodos:
            yield n["ruta"]
            yield from self._rutas(n["hijos"])

    def test_cada_rol_ve_su_menu(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "vende", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        nuevo_usuario(rbac.org_a, "admin", [rbac.emp_a1], roles=[("ADMIN", None)])
        vendedor = set(self._rutas(cliente_de("vende").get(f"{BASE}/menu/").json()))
        admin = set(self._rutas(cliente_de("admin").get(f"{BASE}/menu/").json()))
        assert {"/ventas/pos", "/ventas/clientes", "/seguridad/sesiones"} <= vendedor
        assert "/seguridad/usuarios" not in vendedor and "/reportes/rrhh" not in vendedor
        assert {"/seguridad/usuarios", "/seguridad/roles", "/reportes/rrhh"} <= admin

    def test_el_menu_de_transporte_lo_ven_quienes_pueden_verlo(self, rbac, nuevo_usuario):
        transporte = {
            "/mantenimiento/transporte/empresas",
            "/mantenimiento/transporte/conductores",
            "/mantenimiento/transporte/vehiculos",
        }
        for usuario, rol in (("vende", "VENDEDOR"), ("almacen", "ALMACENERO"), ("admin", "ADMIN")):
            nuevo_usuario(rbac.org_a, usuario, [rbac.emp_a1], roles=[(rol, None)])
            assert transporte <= set(self._rutas(cliente_de(usuario).get(f"{BASE}/menu/").json()))
        nuevo_usuario(rbac.org_a, "caja", [rbac.emp_a1], roles=[("CAJERO", None)])
        assert not transporte & set(self._rutas(cliente_de("caja").get(f"{BASE}/menu/").json()))

    def test_un_usuario_sin_roles_solo_ve_sus_entradas_personales(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "nadie", [rbac.emp_a1])
        menu = cliente_de("nadie").get(f"{BASE}/menu/").json()
        assert list(self._rutas(menu)) == [
            "",
            "/seguridad/sesiones",
            "/cuenta/seguridad",
        ]  # padre "Seguridad" + sus entradas personales (sesiones y seguridad de la cuenta)

    def test_no_hay_padres_vacios(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "caja", [rbac.emp_a1], roles=[("CAJERO", None)])
        menu = cliente_de("caja").get(f"{BASE}/menu/").json()

        def revisar(nodos):
            for n in nodos:
                assert n["ruta"] or n["hijos"], n["codigo"]
                revisar(n["hijos"])

        revisar(menu)
        assert "ventas" in {n["codigo"] for n in menu}

    def test_el_menu_cambia_al_instante_cuando_cambian_los_roles(self, rbac, nuevo_usuario):
        from apps.seguridad.services.roles import asignar_rol_de_sistema

        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        api = cliente_de("ana")
        assert "/caja/cuentas" not in set(self._rutas(api.get(f"{BASE}/menu/").json()))
        asignar_rol_de_sistema(u, "CAJERO")
        assert "/caja/cuentas" in set(self._rutas(api.get(f"{BASE}/menu/").json()))

    def test_un_rol_solo_en_la_segunda_empresa_basta_para_ver_el_modulo(self, rbac, nuevo_usuario):
        nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("CAJERO", rbac.emp_a2)]
        )
        assert "/caja/cuentas" in set(self._rutas(cliente_de("ana").get(f"{BASE}/menu/").json()))

    def test_consultas_acotadas(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("ADMIN", None)])
        api = cliente_de("ana")
        api.get(f"{BASE}/menu/")  # calienta la caché
        with CaptureQueriesContext(connection) as consultas:
            assert api.get(f"{BASE}/menu/").status_code == 200
        assert len(consultas) <= 4


class TestCatalogoEndpoint:
    def test_requiere_el_permiso_de_ver_roles(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "vende", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert cliente_de("vende").get(f"{BASE}/permisos/catalogo/").status_code == 403

    def test_devuelve_el_catalogo_completo_sin_paginar(self, rbac, nuevo_usuario):
        nuevo_usuario(rbac.org_a, "admin", [rbac.emp_a1], roles=[("ADMIN", None)])
        r = cliente_de("admin").get(f"{BASE}/permisos/catalogo/")
        assert r.status_code == 200
        cuerpo = r.json()
        assert (
            isinstance(cuerpo, list) and len(cuerpo) == len(cat.PERMISOS) > 25
        )  # más que una página
        assert {"codigo", "modulo", "accion", "descripcion", "es_critico"} == set(cuerpo[0])
