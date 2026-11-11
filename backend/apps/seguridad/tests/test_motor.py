"""Motor de permisos: orden de decisión, vigencias, caché e invalidación."""

import statistics
import time
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.organizacion.models import Estado
from apps.seguridad.exceptions import PermisoDenegado, SeparacionDeFunciones
from apps.seguridad.models import (
    AccesoEmpresa,
    Permiso,
    Rol,
    RolPermiso,
    TipoExcepcion,
    UsuarioPermiso,
    UsuarioRol,
)
from apps.seguridad.services import permisos_engine as motor
from apps.seguridad.services.usuarios import crear_admin_plataforma
from apps.seguridad.tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def excepcion(usuario, codigo, tipo, empresa=None, alcance="EMPRESA", vigente_hasta=None):
    return UsuarioPermiso(
        usuario=usuario,
        permiso=Permiso.objects.get(codigo=codigo),
        empresa=empresa,
        tipo=tipo,
        alcance=alcance,
        vigente_hasta=vigente_hasta,
        motivo="prueba",
    ).save()


class TestOrdenDeDecision:
    def test_sin_roles_no_tiene_nada(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_un_rol_en_una_empresa_no_vale_en_otra(self, rbac, nuevo_usuario):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", rbac.emp_a1)]
        )
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a2.pk)

    def test_un_rol_general_vale_en_todas_sus_empresas(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", None)])
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a2.pk)

    def test_distintos_roles_en_distintas_empresas(self, rbac, nuevo_usuario):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2],
            roles=[("VENDEDOR", rbac.emp_a1), ("CONTADOR", rbac.emp_a2)],
        )  # fmt: skip
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert not motor.tiene_permiso(u, "CONTABILIDAD.VER", rbac.emp_a1.pk)
        assert motor.tiene_permiso(u, "CONTABILIDAD.VER", rbac.emp_a2.pk)
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a2.pk)

    def test_sin_acceso_a_la_empresa_no_sirve_ni_un_rol_general(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a2.pk)  # sin AccesoEmpresa
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_b1.pk)  # de otra organización

    def test_acceso_vencido_o_inactivo_corta_todo(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        acceso = AccesoEmpresa.objects.sin_ambito().get(usuario=u)
        acceso.vigente_hasta = timezone.now() - timedelta(minutes=1)
        acceso.save(update_fields=["vigente_hasta"])
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_empresa_inactiva_corta_todo(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        rbac.emp_a1.estado = Estado.INACTIVO
        rbac.emp_a1.save()
        motor.invalidar_usuario(u.pk)
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_usuario_inactivo(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        u.is_active = False
        u.save()
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_anonimo_y_none(self, rbac):
        from django.contrib.auth.models import AnonymousUser

        assert not motor.tiene_permiso(AnonymousUser(), "VENTAS.VER", rbac.emp_a1.pk)
        assert not motor.tiene_permiso(None, "VENTAS.VER", rbac.emp_a1.pk)

    def test_el_admin_de_plataforma_puede_todo(self, rbac):
        admin = crear_admin_plataforma(username="root", email="root@x.com", password=PASSWORD)
        assert (
            motor.alcance_de(admin, "SEGURIDAD.ORGANIZACION.GESTIONAR", rbac.emp_b1.pk)
            == "ORGANIZACION"
        )

    def test_deny_gana_sobre_el_rol(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        excepcion(u, "VENTAS.VENDER", TipoExcepcion.DENY, rbac.emp_a1)
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)  # lo demás intacto

    def test_deny_gana_incluso_sobre_un_allow_directo(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        excepcion(u, "CAJA.VER", TipoExcepcion.ALLOW, None)
        excepcion(u, "CAJA.VER", TipoExcepcion.DENY, rbac.emp_a1)
        assert not motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)

    def test_deny_de_una_empresa_no_afecta_a_la_otra(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", None)])
        excepcion(u, "VENTAS.VENDER", TipoExcepcion.DENY, rbac.emp_a1)
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a2.pk)

    def test_allow_directo_concede_lo_que_el_rol_no_tiene(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert not motor.tiene_permiso(u, "MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO", rbac.emp_a1.pk)
        excepcion(u, "MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO", TipoExcepcion.ALLOW, rbac.emp_a1)
        assert motor.tiene_permiso(u, "MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO", rbac.emp_a1.pk)

    def test_gana_el_alcance_mas_amplio(self, rbac, nuevo_usuario):
        # El rol da VENTAS.VER a nivel EMPRESA; un ALLOW con PROPIO no lo reduce.
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        excepcion(u, "VENTAS.VER", TipoExcepcion.ALLOW, rbac.emp_a1, alcance="PROPIO")
        assert motor.alcance_de(u, "VENTAS.VER", rbac.emp_a1.pk) == "EMPRESA"
        # Y un ALLOW más amplio sí lo amplía.
        excepcion(u, "INVENTARIO.VER", TipoExcepcion.ALLOW, rbac.emp_a1, alcance="ORGANIZACION")
        assert motor.alcance_de(u, "INVENTARIO.VER", rbac.emp_a1.pk) == "ORGANIZACION"

    def test_dos_roles_se_combinan_con_el_alcance_mas_amplio(self, rbac, nuevo_usuario):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1], roles=[("TECNICO", None), ("VENDEDOR", None)]
        )
        # TECNICO: SERVICIOS.VER = ASIGNADO, VENDEDOR: SERVICIOS.VER = EMPRESA
        assert motor.alcance_de(u, "SERVICIOS.VER", rbac.emp_a1.pk) == "EMPRESA"

    def test_un_rol_eliminado_deja_de_conceder(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="VENDEDOR").delete()
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)


class TestNivelOrganizacion:
    """``empresa_id=None``: datos compartidos (clientes, productos)."""

    def test_el_rol_de_una_sola_empresa_da_acceso_a_datos_de_la_organizacion(
        self, rbac, nuevo_usuario
    ):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", rbac.emp_a1)]
        )
        assert motor.tiene_permiso(u, "MANTENIMIENTO.CLIENTES.VER", None)

    def test_sin_roles_no_hay_acceso_ni_a_nivel_organizacion(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        assert not motor.tiene_permiso(u, "MANTENIMIENTO.CLIENTES.VER", None)

    def test_un_deny_general_bloquea_pero_uno_de_empresa_no(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        excepcion(u, "MANTENIMIENTO.CLIENTES.VER", TipoExcepcion.DENY, rbac.emp_a1)
        assert motor.tiene_permiso(u, "MANTENIMIENTO.CLIENTES.VER", None)
        excepcion(u, "MANTENIMIENTO.PRODUCTOS.VER", TipoExcepcion.DENY, None)
        assert not motor.tiene_permiso(u, "MANTENIMIENTO.PRODUCTOS.VER", None)


class TestVencimientos:
    def test_un_rol_vencido_no_cuenta(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="VENDEDOR")
        UsuarioRol(usuario=u, rol=rol, vigente_hasta=timezone.now() - timedelta(seconds=1)).save()
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)

    def test_una_excepcion_vencida_no_cuenta(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        excepcion(
            u,
            "CAJA.VER",
            TipoExcepcion.ALLOW,
            None,
            vigente_hasta=timezone.now() - timedelta(seconds=1),
        )
        assert not motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)

    def test_un_permiso_temporal_expira_aunque_este_en_cache(self, rbac, nuevo_usuario):
        """El TTL de la entrada en caché se acorta hasta el vencimiento."""
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        excepcion(
            u,
            "CAJA.VER",
            TipoExcepcion.ALLOW,
            None,
            vigente_hasta=timezone.now() + timedelta(seconds=1.5),
        )
        assert motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)  # queda en caché
        assert motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)
        time.sleep(2.2)
        assert not motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)

    def test_un_rol_temporal_futuro_si_cuenta(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="CAJERO")
        UsuarioRol(usuario=u, rol=rol, vigente_hasta=timezone.now() + timedelta(days=1)).save()
        assert motor.tiene_permiso(u, "CAJA.OPERAR", rbac.emp_a1.pk)


class TestCacheEInvalidacion:
    def test_la_segunda_consulta_no_toca_la_base(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        with CaptureQueriesContext(connection) as consultas:
            for _ in range(20):
                assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        assert len(consultas) == 0

    def test_asignar_un_rol_surte_efecto_de_inmediato(self, rbac, nuevo_usuario):
        from apps.seguridad.services.roles import asignar_rol_de_sistema

        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)  # queda cacheado
        asignar_rol_de_sistema(u, "VENDEDOR")
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_cambiar_los_permisos_de_un_rol_afecta_a_todos_sus_usuarios(self, rbac, nuevo_usuario):
        a = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        b = nuevo_usuario(rbac.org_a, "beto", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert motor.tiene_permiso(a, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert motor.tiene_permiso(b, "VENTAS.VENDER", rbac.emp_a1.pk)
        fila = RolPermiso.objects.sin_ambito().get(
            rol__codigo="VENDEDOR", rol__organizacion=rbac.org_a, permiso__codigo="VENTAS.VENDER"
        )
        fila.delete()
        assert not motor.tiene_permiso(a, "VENTAS.VENDER", rbac.emp_a1.pk)
        assert not motor.tiene_permiso(b, "VENTAS.VENDER", rbac.emp_a1.pk)

    def test_un_cambio_en_una_organizacion_no_invalida_a_la_otra(self, rbac, nuevo_usuario):
        otra = nuevo_usuario(rbac.org_b, "zoe", [rbac.emp_b1], roles=[("VENDEDOR", None)])
        motor.tiene_permiso(otra, "VENTAS.VER", rbac.emp_b1.pk)
        motor.invalidar_organizacion(rbac.org_a.pk)
        with CaptureQueriesContext(connection) as consultas:
            motor.tiene_permiso(otra, "VENTAS.VER", rbac.emp_b1.pk)
        assert len(consultas) == 0

    def test_quitar_un_acceso_invalida_los_permisos(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        AccesoEmpresa.objects.sin_ambito().get(usuario=u).delete()
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_el_aislamiento_de_cache_entre_usuarios(self, rbac, nuevo_usuario):
        a = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        b = nuevo_usuario(rbac.org_a, "beto", [rbac.emp_a1])
        assert motor.tiene_permiso(a, "VENTAS.ANULAR", rbac.emp_a1.pk)
        assert not motor.tiene_permiso(b, "VENTAS.ANULAR", rbac.emp_a1.pk)

    def test_resuelve_en_menos_de_5_ms_desde_la_cache(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("ADMIN", None)])
        motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)  # calienta
        tiempos = []
        for _ in range(500):
            inicio = time.perf_counter()
            motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
            tiempos.append((time.perf_counter() - inicio) * 1000)
        assert statistics.mean(tiempos) < 5, f"media {statistics.mean(tiempos):.3f} ms"
        assert max(tiempos) < 50


class TestOperacionesMixtas:
    def test_se_verifica_cada_empresa_distinta(self, rbac, nuevo_usuario):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", rbac.emp_a1)]
        )
        with pytest.raises(PermisoDenegado) as error:
            motor.exigir_permiso_en_empresas(
                u, "VENTAS.VENDER", [rbac.emp_a1.pk, rbac.emp_a2.pk, rbac.emp_a1.pk]
            )
        assert error.value.detalle["empresas"] == [rbac.emp_a2.pk]

    def test_si_tiene_todas_devuelve_el_alcance_por_empresa(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("VENDEDOR", None)])
        alcances = motor.exigir_permiso_en_empresas(
            u, "VENTAS.VENDER", [rbac.emp_a1.pk, rbac.emp_a2.pk]
        )
        assert alcances == {rbac.emp_a1.pk: "EMPRESA", rbac.emp_a2.pk: "EMPRESA"}

    def test_el_consolidado_exige_el_permiso_en_todas_las_empresas_incluidas(
        self, rbac, nuevo_usuario
    ):
        u = nuevo_usuario(
            rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2], roles=[("ADMIN", rbac.emp_a1)]
        )
        assert motor.tiene_permiso(u, "REPORTES.CONSOLIDADO.VER", rbac.emp_a1.pk)
        with pytest.raises(PermisoDenegado):
            motor.exigir_permiso_en_empresas(
                u, "REPORTES.CONSOLIDADO.VER", [rbac.emp_a1.pk, rbac.emp_a2.pk]
            )

    def test_exigir_permiso_devuelve_el_alcance(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert motor.exigir_permiso(u, "VENTAS.VER", rbac.emp_a1.pk) == "EMPRESA"
        with pytest.raises(PermisoDenegado):
            motor.exigir_permiso(u, "VENTAS.ANULAR", rbac.emp_a1.pk)


def test_separacion_de_funciones(rbac, nuevo_usuario):
    a = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
    b = nuevo_usuario(rbac.org_a, "beto", [rbac.emp_a1])
    motor.exigir_separacion_de_funciones(b.pk, a.pk)  # personas distintas: correcto
    motor.exigir_separacion_de_funciones(b.pk, None)  # el otro paso aún no ocurre
    with pytest.raises(SeparacionDeFunciones):
        motor.exigir_separacion_de_funciones(a.pk, a.pk)


def test_alcance_cubre():
    assert motor.alcance_cubre("ORGANIZACION", "EMPRESA")
    assert motor.alcance_cubre("EMPRESA", "EMPRESA")
    assert not motor.alcance_cubre("PROPIO", "EMPRESA")
    assert not motor.alcance_cubre(None, None)
    assert motor.alcance_cubre("PROPIO", None)


def test_modelo_usuariorol_unicidad(rbac, nuevo_usuario):
    from django.db import IntegrityError, transaction

    u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
    rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="VENDEDOR")
    with pytest.raises(IntegrityError), transaction.atomic():
        UsuarioRol(usuario=u, rol=rol).save()  # misma asignación general dos veces
    assert UsuarioRol.objects.sin_ambito().filter(usuario=u).count() == 1
