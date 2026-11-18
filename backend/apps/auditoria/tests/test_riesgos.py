"""Eventos de riesgo, su filtro y la protección de la bitácora en la base de datos."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.auditoria import riesgos
from apps.auditoria.models import AuditoriaEvento
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

RIESGOS = "/api/v1/auditoria/riesgos/"
EVENTOS = "/api/v1/auditoria/eventos/"


@pytest.fixture
def panel(nuevo_usuario, rbac):
    e = rbac
    return {
        "e": e,
        "admin": nuevo_usuario(e.org_a, "admin", [e.emp_a1, e.emp_a2], [("ADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otro_b": nuevo_usuario(e.org_b, "otro_b", [e.emp_b1], [("ADMIN", None)]),
    }


def evento(org, accion, *, usuario=None, hace=None, **extra):
    datos = {
        "accion": accion,
        "organizacion_id": org.pk,
        "usuario_id": usuario.pk if usuario else None,
    }
    if hace is not None:
        datos["creado_en"] = timezone.now() - hace
    return AuditoriaEvento.objects.create(**datos, **extra)


def categoria(datos, clave):
    return next(c for c in datos["categorias"] if c["clave"] == clave)


class TestResumen:
    def test_cuenta_por_categoria_y_enciende_las_alertas(self, panel):
        org = panel["e"].org_a
        for _ in range(10):
            evento(org, "sesion.login_fallido", usuario=panel["vendedor"])
        evento(org, "rol.permisos_modificados", usuario=panel["admin"])
        for _ in range(2):
            evento(org, "ventas.venta_bajo_minimo", usuario=panel["vendedor"])
        evento(org, "cliente.eliminado", usuario=panel["admin"])
        for _ in range(3):
            evento(org, "compras.registro_exportado")
        d = cliente_de("admin").get(RIESGOS).json()
        assert categoria(d, "acceso")["total"] == 10 and categoria(d, "acceso")["alerta"] is True
        assert categoria(d, "permisos")["alerta"] is True
        assert categoria(d, "precios")["total"] == 2 and categoria(d, "precios")["alerta"] is False
        assert categoria(d, "eliminaciones")["total"] == 1
        assert categoria(d, "exportaciones")["total"] == 3
        assert d["alertas"] == 3  # acceso, permisos y eliminaciones
        top = categoria(d, "acceso")["top_usuarios"]
        assert top == [{"usuario_id": str(panel["vendedor"].pk), "nombre": "vendedor", "n": 10}]

    def test_solo_cuenta_lo_del_periodo_y_de_la_propia_organizacion(self, panel):
        org, otra = panel["e"].org_a, panel["e"].org_b
        evento(org, "rol.permisos_modificados", hace=timedelta(days=30))  # fuera de los 7 días
        evento(otra, "rol.permisos_modificados")  # de otra organización
        d = cliente_de("admin").get(RIESGOS).json()
        assert categoria(d, "permisos")["total"] == 0
        d = cliente_de("admin").get(RIESGOS, {"dias": 60}).json()
        assert categoria(d, "permisos")["total"] == 1

    def test_pide_permiso_y_valida_los_dias(self, panel):
        assert cliente_de("vendedor").get(RIESGOS).status_code == 403
        admin = cliente_de("admin")
        assert admin.get(RIESGOS, {"dias": 0}).status_code == 400
        assert admin.get(RIESGOS, {"dias": 91}).status_code == 400
        assert admin.get(RIESGOS, {"dias": "x"}).status_code == 400


class TestFiltroPorRiesgo:
    def test_la_lista_se_filtra_por_categoria(self, panel):
        org = panel["e"].org_a
        evento(org, "rol.permisos_modificados")
        evento(org, "usuario.rol_asignado")
        evento(org, "producto.creado")
        r = cliente_de("admin").get(EVENTOS, {"riesgo": "permisos"})
        assert r.status_code == 200, r.content
        assert sorted(e["accion"] for e in r.json()["results"]) == [
            "rol.permisos_modificados",
            "usuario.rol_asignado",
        ]
        assert cliente_de("admin").get(EVENTOS, {"riesgo": "no-existe"}).json()["results"] == []

    def test_cada_categoria_tiene_nombre_gravedad_y_umbral(self):
        claves = [c.clave for c in riesgos.CATEGORIAS]
        assert len(claves) == len(set(claves))
        assert all(c.gravedad in ("ALTA", "MEDIA") and c.umbral >= 1 for c in riesgos.CATEGORIAS)
        assert all(c.acciones or c.contiene for c in riesgos.CATEGORIAS)


class TestProteccionEnLaBase:
    """El disparador rechaza editar o borrar aunque se salte la aplicación (SQL directo)."""

    def test_un_update_directo_falla(self, panel):
        e = evento(panel["e"].org_a, "prueba.evento")
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as c:
            c.execute(
                "UPDATE auditoria_auditoriaevento SET resumen = 'cambiado' WHERE id = %s", [e.pk]
            )
        assert AuditoriaEvento.objects.get(pk=e.pk).resumen == ""

    def test_un_delete_directo_falla(self, panel):
        e = evento(panel["e"].org_a, "prueba.evento")
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as c:
            c.execute("DELETE FROM auditoria_auditoriaevento WHERE id = %s", [e.pk])
        assert AuditoriaEvento.objects.filter(pk=e.pk).exists()

    def test_la_purga_por_retencion_si_puede_borrar(self, panel):
        viejo = evento(panel["e"].org_a, "prueba.viejo", hace=timedelta(days=900))
        nuevo = evento(panel["e"].org_a, "prueba.nuevo")
        eliminados = AuditoriaEvento.objects.purgar_anteriores(timezone.now() - timedelta(days=730))
        assert eliminados == 1
        assert not AuditoriaEvento.objects.filter(pk=viejo.pk).exists()
        assert AuditoriaEvento.objects.filter(pk=nuevo.pk).exists()
        # Y el aviso de purga no queda abierto: un borrado normal vuelve a fallar.
        with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as c:
            c.execute("DELETE FROM auditoria_auditoriaevento WHERE id = %s", [nuevo.pk])


class TestRecursos:
    def test_el_historial_junta_varios_registros_y_valida_el_formato(self, panel):
        org = panel["e"].org_a
        evento(org, "ventas.venta_registrada", recurso_tipo="venta", recurso_id="12")
        evento(org, "ventas.comprobante_anulado", recurso_tipo="comprobante_venta", recurso_id="30")
        evento(org, "ventas.comprobante_anulado", recurso_tipo="comprobante_venta", recurso_id="31")
        admin = cliente_de("admin")
        r = admin.get(EVENTOS, {"recursos": "venta:12,comprobante_venta:30"})
        assert r.status_code == 200, r.content
        assert sorted(e["recurso_id"] for e in r.json()["results"]) == ["12", "30"]
        assert admin.get(EVENTOS, {"recursos": "venta"}).status_code == 400
        assert (
            admin.get(EVENTOS, {"recursos": ",".join(f"v:{i}" for i in range(11))}).status_code
            == 400
        )
