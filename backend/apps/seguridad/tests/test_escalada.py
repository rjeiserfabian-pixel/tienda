"""Anti-escalada de privilegios, roles de sistema, último administrador y aislamiento."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.exceptions import ViolacionAmbito
from apps.seguridad.exceptions import (
    EscaladaDePrivilegios,
    MotivoRequerido,
    PermisoDenegado,
    RolDeSistemaIntocable,
    RolEnUso,
    UltimoAdministrador,
)
from apps.seguridad.models import (
    Permiso,
    Rol,
    RolPermiso,
    TipoExcepcion,
    UsuarioPermiso,
    UsuarioRol,
)
from apps.seguridad.services import permisos_engine as motor
from apps.seguridad.services import roles as svc
from apps.seguridad.services.usuarios import crear_admin_plataforma, desactivar_usuario
from apps.seguridad.tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def rol(rbac, codigo, org=None):
    return Rol.objects.sin_ambito().get(organizacion=org or rbac.org_a, codigo=codigo)


def rol_propio(rbac, codigo, permisos, org=None):
    """Crea un rol editable de la organización con la matriz indicada (alta directa de prueba)."""
    r = Rol(organizacion=org or rbac.org_a, codigo=codigo, nombre=codigo)
    r.save()
    for permiso, alcance in permisos.items():
        RolPermiso(rol=r, permiso=Permiso.objects.get(codigo=permiso), alcance=alcance).save()
    return r


def codigos_de(r):
    """Permisos de un rol (los gestores con ámbito exigen tenant: se consulta sin ámbito)."""
    return set(
        RolPermiso.objects.sin_ambito().filter(rol=r).values_list("permiso__codigo", flat=True)
    )


@pytest.fixture
def admin(rbac, nuevo_usuario):
    return nuevo_usuario(
        rbac.org_a, "admin", [rbac.emp_a1, rbac.emp_a2], roles=[("SUPERADMIN", None)]
    )


@pytest.fixture
def gerente(rbac, nuevo_usuario):
    """Puede asignar roles, pero solo posee VENTAS.VER (EMPRESA) y las gestiones de seguridad."""
    g = nuevo_usuario(rbac.org_a, "gerente", [rbac.emp_a1, rbac.emp_a2])
    r = rol_propio(
        rbac,
        "GERENTE",
        {
            "SEGURIDAD.USUARIOS.ASIGNAR_ROL": "EMPRESA",
            "SEGURIDAD.USUARIOS.EXCEPCIONES": "EMPRESA",
            "SEGURIDAD.ROLES.GESTIONAR": "EMPRESA",
            "VENTAS.VER": "EMPRESA",
        },
    )
    UsuarioRol(usuario=g, rol=r).save()
    return g


class TestAsignarRoles:
    def test_el_superadmin_asigna_cualquier_rol(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        svc.asignar_rol(admin, usuario=u, rol=rol(rbac, "ADMIN"))
        assert motor.tiene_permiso(u, "VENTAS.ANULAR", rbac.emp_a1.pk)

    def test_sin_el_permiso_de_asignar_se_rechaza(self, rbac, nuevo_usuario):
        vendedor = nuevo_usuario(rbac.org_a, "vende", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(PermisoDenegado):
            svc.asignar_rol(vendedor, usuario=u, rol=rol(rbac, "CAJERO"))

    def test_no_se_puede_asignar_un_rol_con_permisos_que_uno_no_tiene(
        self, rbac, gerente, nuevo_usuario
    ):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(EscaladaDePrivilegios) as error:
            svc.asignar_rol(gerente, usuario=u, rol=rol(rbac, "VENDEDOR"))  # incluye VENTAS.VENDER
        assert error.value.detalle["permiso"] in codigos_de(rol(rbac, "VENDEDOR"))
        assert not UsuarioRol.objects.sin_ambito().filter(usuario=u).exists()  # nada se guardó

    def test_si_el_rol_cabe_dentro_de_lo_que_uno_posee_se_permite(
        self, rbac, gerente, nuevo_usuario
    ):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        solo_ver = rol_propio(rbac, "SOLO_VER", {"VENTAS.VER": "EMPRESA"})
        svc.asignar_rol(gerente, usuario=u, rol=solo_ver)
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_no_se_puede_otorgar_un_alcance_mayor_al_propio(self, rbac, nuevo_usuario):
        g = nuevo_usuario(rbac.org_a, "g", [rbac.emp_a1])
        UsuarioRol(
            usuario=g,
            rol=rol_propio(
                rbac, "G", {"SEGURIDAD.USUARIOS.ASIGNAR_ROL": "EMPRESA", "VENTAS.VER": "PROPIO"}
            ),
        ).save()
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        amplio = rol_propio(rbac, "AMPLIO", {"VENTAS.VER": "EMPRESA"})
        with pytest.raises(EscaladaDePrivilegios):
            svc.asignar_rol(g, usuario=u, rol=amplio)

    def test_nadie_se_auto_asigna_mas_de_lo_que_tiene(self, rbac, gerente):
        with pytest.raises(EscaladaDePrivilegios):
            svc.asignar_rol(gerente, usuario=gerente, rol=rol(rbac, "ADMIN"))

    def test_el_actor_debe_poder_asignar_en_la_empresa_destino(self, rbac, nuevo_usuario):
        g = nuevo_usuario(rbac.org_a, "g", [rbac.emp_a1, rbac.emp_a2])
        UsuarioRol(
            usuario=g,
            rol=rol_propio(rbac, "G", {"SEGURIDAD.USUARIOS.ASIGNAR_ROL": "EMPRESA"}),
            empresa=rbac.emp_a1,
        ).save()  # solo en A1
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1, rbac.emp_a2])
        vacio = rol_propio(rbac, "VACIO", {})
        svc.asignar_rol(g, usuario=u, rol=vacio, empresa=rbac.emp_a1)
        with pytest.raises(PermisoDenegado):
            svc.asignar_rol(g, usuario=u, rol=vacio, empresa=rbac.emp_a2)
        with pytest.raises(PermisoDenegado):  # "todas sus empresas" incluye A2
            svc.asignar_rol(g, usuario=u, rol=vacio)

    def test_no_se_asigna_en_una_empresa_donde_el_usuario_no_tiene_acceso(
        self, rbac, admin, nuevo_usuario
    ):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(ViolacionAmbito):
            svc.asignar_rol(admin, usuario=u, rol=rol(rbac, "VENDEDOR"), empresa=rbac.emp_a2)

    def test_el_vencimiento_debe_ser_futuro(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(ValidationError):
            svc.asignar_rol(
                admin,
                usuario=u,
                rol=rol(rbac, "VENDEDOR"),
                vigente_hasta=timezone.now() - timedelta(days=1),
            )

    def test_reasignar_actualiza_el_vencimiento_sin_duplicar(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        vendedor = rol(rbac, "VENDEDOR")
        svc.asignar_rol(admin, usuario=u, rol=vendedor)
        svc.asignar_rol(
            admin, usuario=u, rol=vendedor, vigente_hasta=timezone.now() + timedelta(days=3)
        )
        asignaciones = UsuarioRol.objects.sin_ambito().filter(usuario=u, rol=vendedor)
        assert asignaciones.count() == 1 and asignaciones.get().vigente_hasta is not None

    def test_un_rol_temporal_deja_de_valer_al_vencer(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        a = svc.asignar_rol(
            admin,
            usuario=u,
            rol=rol(rbac, "VENDEDOR"),
            vigente_hasta=timezone.now() + timedelta(days=1),
        )
        assert motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)
        UsuarioRol.objects.sin_ambito().filter(pk=a.pk).update(
            vigente_hasta=timezone.now() - timedelta(seconds=1)
        )
        motor.invalidar_usuario(u.pk)
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)


class TestExcepciones:
    def test_allow_pasa_por_la_anti_escalada(self, rbac, gerente, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(EscaladaDePrivilegios):
            svc.otorgar_excepcion(
                gerente,
                usuario=u,
                codigo="MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO",
                tipo="ALLOW",
                motivo="x",
            )
        svc.otorgar_excepcion(gerente, usuario=u, codigo="VENTAS.VER", tipo="ALLOW", motivo="apoyo")
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_deny_no_exige_poseer_el_permiso(self, rbac, gerente, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        svc.otorgar_excepcion(
            gerente, usuario=u, codigo="VENTAS.VENDER", tipo="DENY", motivo="suspendido"
        )
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)

    @pytest.mark.parametrize("motivo", ["", "   "])
    def test_el_motivo_es_obligatorio(self, rbac, admin, nuevo_usuario, motivo):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(MotivoRequerido):
            svc.otorgar_excepcion(admin, usuario=u, codigo="CAJA.VER", tipo="ALLOW", motivo=motivo)

    def test_el_modelo_tambien_exige_motivo(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(MotivoRequerido):
            UsuarioPermiso(
                usuario=u, permiso=Permiso.objects.get(codigo="CAJA.VER"), tipo="ALLOW", motivo=""
            ).save()

    def test_validaciones_de_entrada(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(ValidationError):
            svc.otorgar_excepcion(admin, usuario=u, codigo="NO.EXISTE", tipo="ALLOW", motivo="x")
        with pytest.raises(ValidationError):
            svc.otorgar_excepcion(admin, usuario=u, codigo="CAJA.VER", tipo="TAL", motivo="x")
        with pytest.raises(ValidationError):
            svc.otorgar_excepcion(
                admin, usuario=u, codigo="CAJA.VER", tipo="ALLOW", motivo="x", alcance="TODO"
            )

    def test_revocar(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        e = svc.otorgar_excepcion(
            admin, usuario=u, codigo="CAJA.VER", tipo=TipoExcepcion.ALLOW, motivo="m"
        )
        assert motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)
        svc.revocar_excepcion(admin, e)
        assert not motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)

    def test_otorgar_dos_veces_actualiza_en_vez_de_duplicar(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        svc.otorgar_excepcion(admin, usuario=u, codigo="CAJA.VER", tipo="ALLOW", motivo="uno")
        svc.otorgar_excepcion(admin, usuario=u, codigo="CAJA.VER", tipo="DENY", motivo="dos")
        assert UsuarioPermiso.objects.sin_ambito().filter(usuario=u).count() == 1
        assert not motor.tiene_permiso(u, "CAJA.VER", rbac.emp_a1.pk)


class TestGestionDeRoles:
    def test_crear_rol_exige_el_permiso(self, rbac, nuevo_usuario):
        vendedor = nuevo_usuario(rbac.org_a, "v", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        with pytest.raises(PermisoDenegado):
            svc.crear_rol(vendedor, organizacion=rbac.org_a, codigo="NUEVO", nombre="Nuevo")

    def test_crear_rol_con_permisos_dentro_de_los_propios(self, rbac, gerente):
        r = svc.crear_rol(
            gerente,
            organizacion=rbac.org_a,
            codigo="LECTOR",
            nombre="Lector",
            permisos={"VENTAS.VER": "EMPRESA"},
        )
        assert r.es_sistema is False
        assert codigos_de(r) == {"VENTAS.VER"}

    def test_no_se_agregan_a_un_rol_permisos_que_el_editor_no_tiene(self, rbac, gerente):
        r = svc.crear_rol(gerente, organizacion=rbac.org_a, codigo="LECTOR", nombre="Lector")
        with pytest.raises(EscaladaDePrivilegios):
            svc.establecer_permisos_de_rol(gerente, r, {"VENTAS.ANULAR": "EMPRESA"})
        with pytest.raises(EscaladaDePrivilegios):  # tampoco con mayor alcance
            svc.establecer_permisos_de_rol(gerente, r, {"VENTAS.VER": "ORGANIZACION"})
        assert codigos_de(r) == set()

    def test_si_se_puede_quitar_lo_que_uno_no_posee(self, rbac, gerente, admin):
        r = svc.crear_rol(
            admin,
            organizacion=rbac.org_a,
            codigo="MIXTO",
            nombre="Mixto",
            permisos={"VENTAS.VER": "EMPRESA", "VENTAS.ANULAR": "EMPRESA"},
        )
        svc.establecer_permisos_de_rol(gerente, r, {"VENTAS.VER": "EMPRESA"})  # quita ANULAR
        assert codigos_de(r) == {"VENTAS.VER"}

    def test_un_rol_critico_solo_lo_crea_quien_tiene_control_total(self, rbac, gerente, admin):
        with pytest.raises(EscaladaDePrivilegios):
            svc.crear_rol(
                gerente, organizacion=rbac.org_a, codigo="JEFE", nombre="Jefe", es_critico=True
            )
        assert svc.crear_rol(
            admin, organizacion=rbac.org_a, codigo="JEFE", nombre="Jefe", es_critico=True
        ).es_critico

    def test_codigo_invalido(self, rbac, admin):
        with pytest.raises(ValidationError):
            svc.crear_rol(admin, organizacion=rbac.org_a, codigo="con espacios", nombre="x")

    def test_permiso_desconocido_en_la_matriz(self, rbac, admin):
        r = svc.crear_rol(admin, organizacion=rbac.org_a, codigo="X1", nombre="x")
        with pytest.raises(ValidationError):
            svc.establecer_permisos_de_rol(admin, r, {"INVENTADO.ALGO": "EMPRESA"})

    def test_un_cambio_de_matriz_se_refleja_en_los_usuarios(self, rbac, admin, nuevo_usuario):
        r = svc.crear_rol(admin, organizacion=rbac.org_a, codigo="LECTOR", nombre="Lector")
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        svc.asignar_rol(admin, usuario=u, rol=r)
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        svc.establecer_permisos_de_rol(admin, r, {"VENTAS.VER": "EMPRESA"})
        assert motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)
        svc.establecer_permisos_de_rol(admin, r, {})
        assert not motor.tiene_permiso(u, "VENTAS.VER", rbac.emp_a1.pk)

    def test_eliminar_un_rol_en_uso_se_rechaza(self, rbac, admin, nuevo_usuario):
        r = svc.crear_rol(admin, organizacion=rbac.org_a, codigo="LECTOR", nombre="Lector")
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        svc.asignar_rol(admin, usuario=u, rol=r)
        with pytest.raises(RolEnUso):
            svc.eliminar_rol(admin, r)
        svc.quitar_rol(admin, UsuarioRol.objects.sin_ambito().get(usuario=u, rol=r))
        svc.eliminar_rol(admin, r)
        assert not Rol.objects.sin_ambito().filter(pk=r.pk).exists()

    def test_actualizar_rol(self, rbac, admin):
        r = svc.crear_rol(admin, organizacion=rbac.org_a, codigo="LECTOR", nombre="Lector")
        svc.actualizar_rol(admin, r, nombre="Lector de ventas", descripcion="Solo lectura")
        r.refresh_from_db()
        assert r.nombre == "Lector de ventas"


class TestRolesDeSistema:
    def test_los_servicios_rechazan_tocar_un_rol_de_sistema(self, rbac, admin):
        r = rol(rbac, "SUPERADMIN")
        with pytest.raises(RolDeSistemaIntocable):
            svc.actualizar_rol(admin, r, nombre="Hackeado")
        with pytest.raises(RolDeSistemaIntocable):
            svc.eliminar_rol(admin, r)
        with pytest.raises(RolDeSistemaIntocable):
            svc.establecer_permisos_de_rol(admin, r, {})
        assert RolPermiso.objects.sin_ambito().filter(rol=r).count() > 0


class TestUltimoAdministrador:
    def test_no_se_puede_quitar_el_unico_rol_administrador(self, rbac, admin):
        asignacion = UsuarioRol.objects.sin_ambito().get(usuario=admin)
        with pytest.raises(UltimoAdministrador):
            svc.quitar_rol(admin, asignacion)
        assert motor.tiene_permiso(admin, "SEGURIDAD.ROLES.GESTIONAR", rbac.emp_a1.pk)

    def test_no_se_puede_desactivar_al_unico_administrador(self, rbac, admin):
        with pytest.raises(UltimoAdministrador):
            desactivar_usuario(admin)
        admin.refresh_from_db()
        assert admin.is_active

    def test_con_un_segundo_administrador_si_se_puede(self, rbac, admin, nuevo_usuario):
        otro = nuevo_usuario(
            rbac.org_a, "otro", [rbac.emp_a1, rbac.emp_a2], roles=[("ADMIN", None)]
        )  # ADMIN también es crítico
        svc.quitar_rol(otro, UsuarioRol.objects.sin_ambito().get(usuario=admin))
        assert not motor.tiene_permiso(admin, "SEGURIDAD.ROLES.GESTIONAR", rbac.emp_a1.pk)

    def test_un_administrador_desactivado_no_cuenta(self, rbac, admin, nuevo_usuario):
        otro = nuevo_usuario(rbac.org_a, "otro", [rbac.emp_a1], roles=[("ADMIN", None)])
        otro.is_active = False
        otro.save()
        with pytest.raises(UltimoAdministrador):
            svc.quitar_rol(admin, UsuarioRol.objects.sin_ambito().get(usuario=admin))

    def test_un_administrador_con_rol_vencido_no_cuenta(self, rbac, admin, nuevo_usuario):
        otro = nuevo_usuario(rbac.org_a, "otro", [rbac.emp_a1], roles=[("ADMIN", None)])
        UsuarioRol.objects.sin_ambito().filter(usuario=otro).update(
            vigente_hasta=timezone.now() - timedelta(days=1)
        )
        with pytest.raises(UltimoAdministrador):
            desactivar_usuario(admin)

    def test_quitar_un_rol_no_critico_no_esta_restringido(self, rbac, admin, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        svc.quitar_rol(admin, UsuarioRol.objects.sin_ambito().get(usuario=u))
        assert not motor.tiene_permiso(u, "VENTAS.VENDER", rbac.emp_a1.pk)

    def test_el_conteo_es_por_organizacion(self, rbac, admin, nuevo_usuario):
        # Un administrador de OTRA organización no sirve de respaldo.
        nuevo_usuario(rbac.org_b, "zoe", [rbac.emp_b1], roles=[("SUPERADMIN", None)])
        with pytest.raises(UltimoAdministrador):
            desactivar_usuario(admin)


class TestAislamientoEntreOrganizaciones:
    def test_un_actor_no_gestiona_roles_de_otra_organizacion(self, rbac, admin, nuevo_usuario):
        zoe = nuevo_usuario(rbac.org_b, "zoe", [rbac.emp_b1])
        with pytest.raises(ViolacionAmbito):
            svc.asignar_rol(admin, usuario=zoe, rol=rol(rbac, "VENDEDOR", rbac.org_b))
        with pytest.raises(ViolacionAmbito):
            svc.crear_rol(admin, organizacion=rbac.org_b, codigo="NUEVO", nombre="x")

    def test_no_se_asigna_un_rol_de_otra_organizacion_a_un_usuario_propio(
        self, rbac, admin, nuevo_usuario
    ):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(ViolacionAmbito):
            svc.asignar_rol(admin, usuario=u, rol=rol(rbac, "VENDEDOR", rbac.org_b))

    def test_el_modelo_impide_cruzar_organizaciones(self, rbac, nuevo_usuario):
        u = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1])
        with pytest.raises(ViolacionAmbito):
            UsuarioRol(usuario=u, rol=rol(rbac, "VENDEDOR", rbac.org_b)).save()
        with pytest.raises(ViolacionAmbito):
            UsuarioRol(usuario=u, rol=rol(rbac, "VENDEDOR"), empresa=rbac.emp_b1).save()
        with pytest.raises(ViolacionAmbito):
            RolPermiso(
                organizacion=rbac.org_a, rol=rol_propio(rbac, "Z", {}, rbac.org_b),
                permiso=Permiso.objects.get(codigo="CAJA.VER"),
            ).save()  # fmt: skip

    def test_el_admin_de_plataforma_gestiona_cualquier_organizacion(self, rbac, nuevo_usuario):
        root = crear_admin_plataforma(username="root", email="root@x.com", password=PASSWORD)
        zoe = nuevo_usuario(rbac.org_b, "zoe", [rbac.emp_b1])
        svc.asignar_rol(root, usuario=zoe, rol=rol(rbac, "VENDEDOR", rbac.org_b))
        assert motor.tiene_permiso(zoe, "VENTAS.VENDER", rbac.emp_b1.pk)
