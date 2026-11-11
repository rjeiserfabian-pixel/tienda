"""Filtrado de listados por alcance: ORGANIZACION / EMPRESA / SUCURSAL / ASIGNADO / PROPIO."""

import uuid

import pytest
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.core.tenant import contexto_tenant
from apps.core.tests.app_prueba.models import ItemEmpresa, ItemOrganizacion
from apps.organizacion.models import Sucursal
from apps.seguridad.mixins import ScopedQuerysetMixin, filtrar_por_alcance
from apps.seguridad.models import AccesoEmpresa, AccesoSucursal, Rol, RolPermiso, UsuarioRol
from apps.seguridad.permissions import PermisoRBAC

pytestmark = pytest.mark.django_db

CODIGO = "SERVICIOS.VER"


def rol_con(rbac, codigo_rol, alcance, permiso=CODIGO):
    """Rol propio de la organización A con UN permiso y el alcance indicado."""
    from apps.seguridad.models import Permiso

    rol = Rol(organizacion=rbac.org_a, codigo=codigo_rol, nombre=codigo_rol)
    rol.save()
    RolPermiso(rol=rol, permiso=Permiso.objects.get(codigo=permiso), alcance=alcance).save()
    return rol


def dar(usuario, rol, empresa=None):
    UsuarioRol(usuario=usuario, rol=rol, empresa=empresa).save()


@pytest.fixture
def mundo(rbac, nuevo_usuario):
    """Dos empresas con items de dos personas, un técnico asignado y sucursales."""
    ana = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2])
    beto = nuevo_usuario(rbac.org_a, "beto", [rbac.emp_a1, rbac.emp_a2])
    tecnico = uuid.uuid4()
    s1 = Sucursal.objects.sin_ambito().create(empresa=rbac.emp_a1, nombre="Lima", codigo="L01")
    s2 = Sucursal.objects.sin_ambito().create(empresa=rbac.emp_a1, nombre="Cusco", codigo="C01")

    with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk, rbac.emp_a2.pk], ana.pk):
        ItemEmpresa.objects.create(
            empresa=rbac.emp_a1, nombre="a1-ana", sucursal=s1, asignado_id=tecnico
        )
        ItemEmpresa.objects.create(empresa=rbac.emp_a1, nombre="a1-ana-cusco", sucursal=s2)
        ItemEmpresa.objects.create(empresa=rbac.emp_a2, nombre="a2-ana")
    with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk, rbac.emp_a2.pk], beto.pk):
        ItemEmpresa.objects.create(empresa=rbac.emp_a1, nombre="a1-beto", sucursal=s1)
        ItemEmpresa.objects.create(empresa=rbac.emp_a2, nombre="a2-beto")
    return {"ana": ana, "beto": beto, "tecnico": tecnico, "s1": s1, "s2": s2, "rbac": rbac}


def nombres(mundo, usuario, **campos):
    rbac = mundo["rbac"]
    with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk, rbac.emp_a2.pk], usuario.pk):
        qs = filtrar_por_alcance(ItemEmpresa.objects.all(), usuario, CODIGO, **campos)
        return sorted(qs.values_list("nombre", flat=True))


class TestAlcancePorEmpresa:
    def test_sin_permiso_no_ve_nada(self, mundo):
        assert nombres(mundo, mundo["ana"]) == []

    def test_alcance_empresa_ve_toda_la_empresa(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_EMP", "EMPRESA"), rbac.emp_a1)
        assert nombres(mundo, mundo["ana"]) == ["a1-ana", "a1-ana-cusco", "a1-beto"]  # nada de A2

    def test_alcance_organizacion_en_un_recurso_de_empresa_cubre_las_habilitadas(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_ORG", "ORGANIZACION"))
        assert len(nombres(mundo, mundo["ana"])) == 5

    def test_alcance_propio(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_PROP", "PROPIO"))
        assert nombres(mundo, mundo["ana"]) == ["a1-ana", "a1-ana-cusco", "a2-ana"]
        assert nombres(mundo, mundo["beto"]) == []

    def test_alcance_asignado(self, mundo):
        rbac = mundo["rbac"]
        tecnico = mundo["ana"].__class__.objects.get(pk=mundo["ana"].pk)  # ana actúa como técnica
        dar(tecnico, rol_con(rbac, "R_ASIG", "ASIGNADO"))
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk], tecnico.pk):
            ItemEmpresa.objects.filter(nombre="a1-beto").update(asignado_id=tecnico.pk)
        assert nombres(mundo, tecnico, campo_asignado="asignado_id") == ["a1-beto"]

    def test_asignado_sin_campo_declarado_falla_cerrado(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_ASIG", "ASIGNADO"))
        assert nombres(mundo, mundo["ana"]) == []  # la vista no declaró campo_asignado

    def test_alcance_sucursal_usa_las_sucursales_asignadas(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_SUC", "SUCURSAL"), rbac.emp_a1)
        acceso = AccesoEmpresa.objects.sin_ambito().get(usuario=mundo["ana"], empresa=rbac.emp_a1)
        AccesoSucursal(acceso_empresa=acceso, sucursal=mundo["s1"]).save()  # solo Lima
        assert nombres(mundo, mundo["ana"], campo_sucursal="sucursal_id") == ["a1-ana", "a1-beto"]

    def test_sucursal_sin_sucursales_asignadas_no_concede_nada(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_SUC", "SUCURSAL"), rbac.emp_a1)
        assert nombres(mundo, mundo["ana"], campo_sucursal="sucursal_id") == []

    def test_alcances_distintos_por_empresa_se_combinan(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_EMP", "EMPRESA"), rbac.emp_a1)
        dar(mundo["ana"], rol_con(rbac, "R_PROP", "PROPIO"), rbac.emp_a2)
        assert nombres(mundo, mundo["ana"]) == ["a1-ana", "a1-ana-cusco", "a1-beto", "a2-ana"]

    def test_el_admin_de_plataforma_no_se_filtra(self, mundo):
        from apps.seguridad.services.usuarios import crear_admin_plataforma
        from apps.seguridad.tests.conftest import PASSWORD

        admin = crear_admin_plataforma(username="root", email="r@x.com", password=PASSWORD)
        rbac = mundo["rbac"]
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk, rbac.emp_a2.pk]):
            assert filtrar_por_alcance(ItemEmpresa.objects.all(), admin, CODIGO).count() == 5


class TestRecursoDeOrganizacion:
    def _items(self, rbac, ana, tecnico):
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk], ana.pk):
            ItemOrganizacion.objects.create(nombre="de-ana")
            ItemOrganizacion.objects.create(nombre="asignado", asignado_id=tecnico)
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk]):
            ItemOrganizacion.objects.create(nombre="de-otro")

    def _ver(self, rbac, usuario, **campos):
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk], usuario.pk):
            qs = filtrar_por_alcance(
                ItemOrganizacion.objects.all(),
                usuario,
                "MANTENIMIENTO.CLIENTES.VER",
                campo_empresa=None,
                **campos,
            )
            return sorted(qs.values_list("nombre", flat=True))

    def test_empresa_u_organizacion_ven_todo_lo_de_la_organizacion(self, rbac, nuevo_usuario):
        ana = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)]
        )  # MANTENIMIENTO.CLIENTES.VER=ORG
        self._items(rbac, ana, uuid.uuid4())
        assert self._ver(rbac, ana) == ["asignado", "de-ana", "de-otro"]

    def test_propio(self, rbac, nuevo_usuario):
        from apps.seguridad.models import Permiso

        ana = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        rol = rol_con(rbac, "R_C", "PROPIO", permiso="MANTENIMIENTO.CLIENTES.VER")
        dar(ana, rol)
        self._items(rbac, ana, uuid.uuid4())
        assert self._ver(rbac, ana) == ["asignado", "de-ana"]
        assert Permiso.objects.filter(codigo="MANTENIMIENTO.CLIENTES.VER").exists()

    def test_sin_permiso_no_ve_nada(self, rbac, nuevo_usuario):
        ana = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        self._items(rbac, ana, uuid.uuid4())
        assert self._ver(rbac, ana) == []


class TestMixinEnUnaVista:
    def test_el_mixin_aplica_permiso_y_alcance_de_la_vista(self, mundo):
        rbac = mundo["rbac"]
        dar(mundo["ana"], rol_con(rbac, "R_PROP", "PROPIO"))

        class VistaPrueba(ScopedQuerysetMixin, ListAPIView):
            modelo = ItemEmpresa
            permission_classes = [PermisoRBAC]
            permiso_requerido = CODIGO
            pagination_class = None

            def get_serializer_class(self):
                from rest_framework import serializers

                class S(serializers.Serializer):
                    nombre = serializers.CharField()

                return S

        peticion = APIRequestFactory().get("/")
        force_authenticate(peticion, user=mundo["ana"])
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk, rbac.emp_a2.pk], mundo["ana"].pk):
            respuesta = VistaPrueba.as_view()(peticion)
        assert sorted(f["nombre"] for f in respuesta.data) == ["a1-ana", "a1-ana-cusco", "a2-ana"]

    def test_una_vista_sin_permiso_declarado_no_devuelve_nada(self, mundo):
        class SinPermiso(ScopedQuerysetMixin, ListAPIView):
            modelo = ItemEmpresa

        vista = SinPermiso()
        vista.request = Request(APIRequestFactory().get("/"))
        vista.request.user = mundo["ana"]
        rbac = mundo["rbac"]
        with contexto_tenant(rbac.org_a.pk, [rbac.emp_a1.pk]):
            assert vista.get_queryset().count() == 0
