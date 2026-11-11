"""Catálogo único en código, sincronización idempotente y roles plantilla."""

import re

import pytest
from django.core.management import call_command

from apps.organizacion.models import Organizacion
from apps.seguridad import permisos_catalogo as cat
from apps.seguridad.exceptions import RolDeSistemaIntocable
from apps.seguridad.models import Modulo, Permiso, Rol, RolPermiso
from apps.seguridad.services import permisos_engine as motor
from apps.seguridad.services.catalogo import sembrar_roles_plantilla, sincronizar_catalogo

pytestmark = pytest.mark.django_db


class TestCoherenciaDelCatalogo:
    """Falla en CI si alguien rompe el catálogo en código."""

    def test_codigos_unicos_y_bien_formados(self):
        codigos = [p.codigo for p in cat.PERMISOS]
        assert len(codigos) == len(set(codigos))
        for codigo in codigos:
            assert re.fullmatch(r"[A-Z_]+(\.[A-Z_]+){1,2}", codigo), codigo

    def test_las_plantillas_solo_usan_permisos_y_alcances_validos(self):
        alcances = {"PROPIO", "ASIGNADO", "SUCURSAL", "EMPRESA", "ORGANIZACION"}
        for rol in cat.ROLES_PLANTILLA:
            assert set(rol.permisos) <= cat.CODIGOS, rol.codigo
            assert set(rol.permisos.values()) <= alcances, rol.codigo

    def test_el_menu_solo_referencia_permisos_existentes(self):
        def recorrer(nodos):
            for nodo in nodos:
                if nodo.permiso_ver:
                    assert nodo.permiso_ver in cat.CODIGOS, nodo.codigo
                yield nodo.codigo
                yield from recorrer(nodo.hijos)

        codigos = list(recorrer(cat.MODULOS))
        assert len(codigos) == len(set(codigos))

    def test_estan_los_permisos_de_dominio_previstos_en_el_plan(self):
        previstos = {
            "VENTAS.VENDER_STOCK_OTRA_EMPRESA",
            "INVENTARIO.STOCK_OTRA_EMPRESA.VER",
            "COMPRAS.ELEGIR_EMPRESA",
            "CAJA.OPERAR",
            "CAJA.TRASLADAR_ENTRE_EMPRESAS",
            "TRANSFERENCIAS.AUTORIZAR",
            "TRANSFERENCIAS.ENVIAR",
            "TRANSFERENCIAS.RECIBIR",
            "GASTOS.ASIGNAR_EMPRESA",
            "REPORTES.CONSOLIDADO.VER",
            "MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO",
        }
        assert previstos <= cat.CODIGOS

    def test_estan_los_roles_plantilla_del_plan(self):
        assert {r.codigo for r in cat.ROLES_PLANTILLA} == {
            "SUPERADMIN",
            "ADMIN",
            "VENDEDOR",
            "CAJERO",
            "ALMACENERO",
            "TECNICO",
            "MARKETING",
            "CONTADOR",
            "RRHH",
            "TRABAJADOR",
        }


class TestSincronizacion:
    def test_crea_los_permisos_y_el_menu(self):
        r = sincronizar_catalogo()
        assert r.permisos_creados == len(cat.PERMISOS)
        assert Permiso.objects.filter(activo=True).count() == len(cat.PERMISOS)
        assert Modulo.objects.filter(activo=True).count() > 0

    def test_los_permisos_renombrados_conservan_roles_y_se_dividen_en_crear_y_editar(self):
        """Base anterior a Mantenimiento: CLIENTES.GESTIONAR pasa a CREAR + EDITAR."""
        sincronizar_catalogo()
        org = Organizacion.objects.create(nombre="Org vieja")
        sembrar_roles_plantilla(org)
        # Se vuelve al estado antiguo: nombres viejos y sin el permiso CREAR.
        crear = Permiso.objects.get(codigo="MANTENIMIENTO.CLIENTES.CREAR")
        RolPermiso._base_manager.filter(permiso=crear).delete()  # borrado físico del test
        crear.delete()
        Permiso.objects.filter(codigo="MANTENIMIENTO.CLIENTES.EDITAR").update(
            codigo="CLIENTES.GESTIONAR", modulo="CLIENTES", accion="GESTIONAR"
        )
        Permiso.objects.filter(codigo="MANTENIMIENTO.CLIENTES.VER").update(
            codigo="CLIENTES.VER", modulo="CLIENTES", accion="VER"
        )

        resumen = sincronizar_catalogo()

        assert resumen.permisos_desactivados == 0
        assert not Permiso.objects.filter(
            codigo__in=["CLIENTES.GESTIONAR", "CLIENTES.VER"]
        ).exists()
        vendedor = Rol.objects.sin_ambito().get(organizacion=org, codigo="VENDEDOR")
        alcances = {
            f.permiso.codigo: f.alcance
            for f in RolPermiso.objects.sin_ambito().filter(rol=vendedor).select_related("permiso")
            if f.permiso.codigo.startswith("MANTENIMIENTO.CLIENTES.")
        }
        assert alcances == {
            "MANTENIMIENTO.CLIENTES.VER": "ORGANIZACION",
            "MANTENIMIENTO.CLIENTES.EDITAR": "ORGANIZACION",
            "MANTENIMIENTO.CLIENTES.CREAR": "ORGANIZACION",  # heredado de «gestionar»
        }
        # Y volver a sincronizar no cambia nada.
        otra = sincronizar_catalogo()
        assert (otra.permisos_creados, otra.permisos_actualizados, otra.permisos_desactivados) == (
            0,
            0,
            0,
        )

    def test_es_idempotente(self):
        sincronizar_catalogo()
        segunda = sincronizar_catalogo()
        assert (
            segunda.permisos_creados,
            segunda.permisos_actualizados,
            segunda.permisos_desactivados,
        ) == (0, 0, 0)
        assert Permiso.objects.count() == len(cat.PERMISOS)

    def test_un_permiso_que_sale_del_catalogo_se_desactiva_y_ya_no_concede(
        self, nuevo_usuario, rbac, monkeypatch
    ):
        usuario = nuevo_usuario(rbac.org_a, "ana", [rbac.emp_a1], roles=[("VENDEDOR", None)])
        assert motor.tiene_permiso(usuario, "VENTAS.VENDER", rbac.emp_a1.pk)

        reducido = tuple(p for p in cat.PERMISOS if p.codigo != "VENTAS.VENDER")
        monkeypatch.setattr(cat, "PERMISOS", reducido)
        monkeypatch.setattr(cat, "CODIGOS", frozenset(p.codigo for p in reducido))
        assert sincronizar_catalogo().permisos_desactivados == 1

        assert Permiso.objects.get(codigo="VENTAS.VENDER").activo is False
        assert not motor.tiene_permiso(usuario, "VENTAS.VENDER", rbac.emp_a1.pk)

    def test_el_comando(self, rbac, capsys):
        call_command("sync_permisos")
        assert "Catálogo sincronizado" in capsys.readouterr().out


class TestRolesPlantilla:
    def test_cada_organizacion_tiene_sus_propios_roles(self, rbac):
        codigos = {r.codigo for r in cat.ROLES_PLANTILLA}
        for org in (rbac.org_a, rbac.org_b):
            assert (
                set(
                    Rol.objects.sin_ambito()
                    .filter(organizacion=org)
                    .values_list("codigo", flat=True)
                )
                == codigos
            )
        a = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="ADMIN")
        b = Rol.objects.sin_ambito().get(organizacion=rbac.org_b, codigo="ADMIN")
        assert a.pk != b.pk

    def test_superadmin_es_de_sistema_critico_y_tiene_todo(self, rbac):
        rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="SUPERADMIN")
        assert rol.es_sistema and rol.es_critico
        permisos = dict(
            RolPermiso.objects.sin_ambito()
            .filter(rol=rol)
            .values_list("permiso__codigo", "alcance")
        )
        assert set(permisos) == cat.CODIGOS
        assert set(permisos.values()) == {"ORGANIZACION"}

    def test_sembrar_dos_veces_no_duplica(self, rbac):
        antes = RolPermiso.objects.sin_ambito().count()
        estado = sembrar_roles_plantilla(rbac.org_a)
        assert RolPermiso.objects.sin_ambito().count() == antes
        assert estado["SUPERADMIN"] == "sincronizado"
        assert estado["VENDEDOR"] == "intacto"

    def test_un_rol_personalizado_no_se_pisa_al_volver_a_sembrar(self, rbac):
        rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="VENDEDOR")
        RolPermiso.objects.sin_ambito().filter(rol=rol).delete()  # la organización lo vació
        sembrar_roles_plantilla(rbac.org_a)
        assert not RolPermiso.objects.sin_ambito().filter(rol=rol).exists()

    def test_superadmin_se_restaura_si_alguien_lo_altera(self, rbac):
        rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="SUPERADMIN")
        RolPermiso.objects.sin_ambito().filter(rol=rol, permiso__codigo="VENTAS.ANULAR").delete()
        RolPermiso.objects.sin_ambito().filter(rol=rol, permiso__codigo="CAJA.VER").update(
            alcance="PROPIO"
        )
        sembrar_roles_plantilla(rbac.org_a)
        permisos = dict(
            RolPermiso.objects.sin_ambito()
            .filter(rol=rol)
            .values_list("permiso__codigo", "alcance")
        )
        assert permisos["VENTAS.ANULAR"] == "ORGANIZACION"
        assert permisos["CAJA.VER"] == "ORGANIZACION"

    def test_el_alta_de_una_organizacion_siembra_sus_roles(self, db):
        from apps.organizacion.services.creacion import crear_organizacion_con_empresa
        from conftest import ruc_valido

        creada = crear_organizacion_con_empresa(
            nombre_organizacion="Nueva", razon_social="N SAC", ruc=ruc_valido("2077777777")
        )
        assert Rol.objects.sin_ambito().filter(organizacion=creada.organizacion).count() == len(
            cat.ROLES_PLANTILLA
        )

    def test_los_roles_de_sistema_son_intocables_en_el_modelo(self, rbac):
        rol = Rol.objects.sin_ambito().get(organizacion=rbac.org_a, codigo="SUPERADMIN")
        rol.nombre = "Otro nombre"
        with pytest.raises(RolDeSistemaIntocable):
            rol.save()
        with pytest.raises(RolDeSistemaIntocable):
            rol.delete()
        permiso = Permiso.objects.get(codigo="CAJA.VER")
        with pytest.raises(RolDeSistemaIntocable):
            RolPermiso(rol=rol, permiso=permiso, alcance="EMPRESA").save()
        assert Rol.objects.sin_ambito().filter(pk=rol.pk, eliminado_en__isnull=True).exists()

    def test_sembrar_no_toca_organizaciones_ajenas(self, rbac):
        otra = Organizacion.objects.create(nombre="Sin roles")
        sembrar_roles_plantilla(otra)
        assert Rol.objects.sin_ambito().filter(organizacion=otra).count() == len(
            cat.ROLES_PLANTILLA
        )
        assert Rol.objects.sin_ambito().filter(organizacion=rbac.org_a).count() == len(
            cat.ROLES_PLANTILLA
        )
