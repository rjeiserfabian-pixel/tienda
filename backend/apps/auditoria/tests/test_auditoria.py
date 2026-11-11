"""Auditoría: saneado, inmutabilidad, entrega asíncrona, retención y consulta por API."""

from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento, AuditoriaInmutable
from apps.auditoria.servicios import diferencia, registrar, sanear
from apps.auditoria.tasks import purgar, registrar_evento
from apps.seguridad.tests.conftest import PASSWORD, cliente_de

pytestmark = pytest.mark.django_db

URL = "/api/v1/auditoria/eventos/"


@pytest.fixture
def al_instante(monkeypatch):
    """Los tests corren dentro de una transacción: ``on_commit`` se ejecuta de inmediato."""
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


def evento(**extra):
    datos = {"accion": "prueba.evento", "organizacion_id": 1, **extra}
    return AuditoriaEvento.objects.create(**datos)


# ---------------------------------------------------------------------------
# Saneado y diferencias
# ---------------------------------------------------------------------------
class TestSaneado:
    def test_oculta_secretos_en_cualquier_nivel(self):
        limpio = sanear(
            {"password": "x", "datos": {"token_acceso": "y", "nombre": "ok"}, "codigo_mfa": "1"}
        )
        assert limpio["password"] == "***"
        assert limpio["codigo_mfa"] == "***"
        assert limpio["datos"] == {"token_acceso": "***", "nombre": "ok"}

    def test_acota_tamano_y_profundidad(self):
        profundo = {"a": {"b": {"c": {"d": {"e": 1}}}}}
        assert "…" in str(sanear(profundo))
        assert len(sanear({"t": "x" * 5000})["t"]) == 500
        assert len(sanear(list(range(500)))) == 50

    def test_convierte_tipos_no_json(self):
        import uuid
        from datetime import datetime
        from decimal import Decimal

        u = uuid.uuid4()
        assert sanear({"u": u, "d": Decimal("1.5"), "f": datetime(2026, 1, 2)}) == {
            "u": str(u),
            "d": "1.5",
            "f": "2026-01-02T00:00:00",
        }

    def test_diferencia_solo_incluye_lo_que_cambio(self):
        assert diferencia({"a": 1, "b": 2}, {"a": 1, "b": 3}) == {"b": [2, 3]}


# ---------------------------------------------------------------------------
# Inmutabilidad y retención
# ---------------------------------------------------------------------------
class TestInmutabilidad:
    def test_un_evento_no_se_modifica_ni_se_borra(self):
        e = evento()
        e.resumen = "otro"
        with pytest.raises(AuditoriaInmutable):
            e.save()
        with pytest.raises(AuditoriaInmutable):
            e.delete()
        with pytest.raises(AuditoriaInmutable):
            AuditoriaEvento.objects.all().update(resumen="x")
        with pytest.raises(AuditoriaInmutable):
            AuditoriaEvento.objects.all().delete()
        assert AuditoriaEvento.objects.count() == 1

    def test_la_purga_solo_borra_lo_antiguo(self, settings):
        settings.AUDITORIA_RETENCION_DIAS = 30
        viejo = evento(creado_en=timezone.now() - timedelta(days=31))
        reciente = evento(creado_en=timezone.now() - timedelta(days=5))
        assert purgar() == 1
        assert not AuditoriaEvento.objects.filter(pk=viejo.pk).exists()
        assert AuditoriaEvento.objects.filter(pk=reciente.pk).exists()


# ---------------------------------------------------------------------------
# Entrega: espera al COMMIT, no rompe la operación y no se pierde
# ---------------------------------------------------------------------------
class TestEntrega:
    def test_lo_que_se_revierte_no_deja_evento(self, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            try:
                with transaction.atomic():
                    registrar("prueba.revertida", organizacion_id=1)
                    raise RuntimeError("falla la operación")
            except RuntimeError:
                pass
        assert not AuditoriaEvento.objects.filter(accion="prueba.revertida").exists()

    def test_lo_confirmado_deja_evento(self, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                registrar("prueba.confirmada", organizacion_id=1, detalle={"clave": "no"})
        e = AuditoriaEvento.objects.get(accion="prueba.confirmada")
        assert e.detalle == {"clave": "***"}

    def test_si_el_broker_falla_se_inserta_en_el_acto(self, monkeypatch, al_instante):
        def broker_caido(*a, **k):
            raise ConnectionError("broker caído")

        monkeypatch.setattr(registrar_evento, "delay", broker_caido)
        registrar("prueba.respaldo", organizacion_id=1)
        assert AuditoriaEvento.objects.filter(accion="prueba.respaldo").exists()

    def test_si_todo_falla_no_rompe_la_operacion(self, monkeypatch, al_instante, caplog):
        def caido(*a, **k):
            raise ConnectionError("caído")

        monkeypatch.setattr(registrar_evento, "delay", caido)
        monkeypatch.setattr(servicios, "_insertar", caido)
        registrar("prueba.perdida", organizacion_id=1)  # no lanza
        assert "auditoria_perdida" in caplog.text


# ---------------------------------------------------------------------------
# Qué se audita (de punta a punta, por la API)
# ---------------------------------------------------------------------------
@pytest.fixture
def panel(nuevo_usuario, rbac, al_instante):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "admin": nuevo_usuario(e.org_a, "admin", [e.emp_a1, e.emp_a2], [("ADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otro_b": nuevo_usuario(e.org_b, "otro_b", [e.emp_b1], [("ADMIN", None)]),
    }


def acciones(organizacion_id):
    return list(
        AuditoriaEvento.objects.filter(organizacion_id=organizacion_id)
        .order_by("id")
        .values_list("accion", flat=True)
    )


class TestRegistroDeOperaciones:
    def test_login_exitoso_y_fallido(self, panel, api):
        e = panel["e"]
        assert (
            api.post(
                "/api/v1/seguridad/auth/login/",
                {"identificador": "vendedor", "password": "mala-clave-1"},
                format="json",
            ).status_code
            == 401
        )
        cliente_de("vendedor")
        eventos = AuditoriaEvento.objects.filter(organizacion_id=e.org_a.pk)
        fallido = eventos.get(accion="sesion.login_fallido")
        assert fallido.exito is False
        assert "mala-clave" not in str(fallido.detalle)
        assert eventos.filter(accion="sesion.login_ok").exists()

    def test_login_de_usuario_inexistente_queda_sin_organizacion(self, panel, api):
        api.post(
            "/api/v1/seguridad/auth/login/",
            {"identificador": "fantasma", "password": PASSWORD},
            format="json",
        )
        e = AuditoriaEvento.objects.get(accion="sesion.login_fallido", organizacion_id=None)
        assert e.detalle["motivo"] == "usuario_inexistente"
        assert "fantasma" not in str(e.detalle)  # solo una referencia, no el texto escrito

    def test_gestion_de_usuarios_y_roles_deja_rastro_con_actor_e_ip(self, panel):
        e, admin = panel["e"], cliente_de("admin")
        r = admin.post(
            "/api/v1/seguridad/usuarios/",
            {
                "username": "nuevo",
                "email": "n@x.com",
                "password": PASSWORD,
                "empresa_ids": [e.emp_a1.pk],
            },
            format="json",
        )
        assert r.status_code == 201
        admin.patch(
            f"/api/v1/seguridad/usuarios/{r.json()['id']}/",
            {"nombres": "Nuevo"},
            format="json",
        )
        admin.post(
            "/api/v1/seguridad/roles/", {"codigo": "NUEVO_ROL", "nombre": "Nuevo"}, format="json"
        )
        usuario = AuditoriaEvento.objects.get(accion="usuario.creado")
        assert str(usuario.usuario_id) == str(panel["admin"].pk)
        assert usuario.recurso_id == r.json()["id"]
        assert usuario.request_id
        assert PASSWORD not in str(usuario.detalle)
        editado = AuditoriaEvento.objects.get(accion="usuario.editado")
        assert editado.detalle == {"first_name": ["", "Nuevo"]}
        assert "rol.creado" in acciones(e.org_a.pk)

    def test_cambio_de_permisos_de_un_rol_registra_la_diferencia(self, panel):
        admin = cliente_de("admin")
        rol = admin.post(
            "/api/v1/seguridad/roles/",
            {"codigo": "R1", "nombre": "R1", "permisos": {"VENTAS.VER": "EMPRESA"}},
            format="json",
        ).json()["id"]
        admin.put(
            f"/api/v1/seguridad/roles/{rol}/permisos/",
            {"permisos": {"VENTAS.VER": "ORGANIZACION", "MANTENIMIENTO.CLIENTES.VER": "EMPRESA"}},
            format="json",
        )
        ultimo = AuditoriaEvento.objects.filter(accion="rol.permisos_modificados").latest("id")
        assert ultimo.detalle["agregados"] == {"MANTENIMIENTO.CLIENTES.VER": "EMPRESA"}
        assert ultimo.detalle["cambiados"] == {"VENTAS.VER": ["EMPRESA", "ORGANIZACION"]}

    def test_un_cambio_de_contrasena_no_guarda_la_clave(self, panel):
        api = cliente_de("vendedor")
        r = api.post(
            "/api/v1/seguridad/auth/cambiar-password/",
            {"actual": PASSWORD, "nueva": "Otra-Clave-Larga-2027!"},
            format="json",
        )
        assert r.status_code == 204
        e = AuditoriaEvento.objects.get(accion="password.cambiada")
        assert "Otra-Clave" not in str(e.detalle) and PASSWORD not in str(e.detalle)


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
class TestConsulta:
    def test_requiere_permiso(self, panel):
        assert cliente_de("vendedor").get(URL).status_code == 403

    def test_solo_eventos_de_la_propia_organizacion(self, panel):
        e = panel["e"]
        evento(organizacion_id=e.org_a.pk, accion="a.propio")
        evento(organizacion_id=e.org_b.pk, accion="b.ajeno")
        r = cliente_de("admin").get(URL)
        assert r.status_code == 200
        acciones_vistas = {x["accion"] for x in r.json()["results"]}
        assert "a.propio" in acciones_vistas
        assert "b.ajeno" not in acciones_vistas

    def test_filtros_y_nombre_del_usuario(self, panel):
        e = panel["e"]
        evento(organizacion_id=e.org_a.pk, accion="usuario.creado", usuario_id=panel["admin"].pk)
        evento(organizacion_id=e.org_a.pk, accion="sesion.login_ok", exito=True)
        evento(organizacion_id=e.org_a.pk, accion="sesion.login_fallido", exito=False)
        api = cliente_de("admin")
        por_prefijo = api.get(URL, {"accion": "sesion."}).json()["results"]
        assert {x["accion"] for x in por_prefijo} >= {"sesion.login_fallido"}
        assert all(x["accion"].startswith("sesion.") for x in por_prefijo)
        fallidos = api.get(URL, {"exito": "false", "accion": "sesion."}).json()["results"]
        assert {x["accion"] for x in fallidos} == {"sesion.login_fallido"}
        creados = api.get(URL, {"usuario": str(panel["admin"].pk), "accion": "usuario."}).json()
        assert creados["results"][0]["usuario"] == "admin"

    def test_filtro_de_fechas_y_valores_invalidos(self, panel):
        e = panel["e"]
        evento(
            organizacion_id=e.org_a.pk,
            accion="x.viejo",
            creado_en=timezone.now() - timedelta(days=40),
        )
        api = cliente_de("admin")
        desde = (timezone.now() - timedelta(days=10)).date().isoformat()
        assert "x.viejo" not in {
            x["accion"] for x in api.get(URL, {"desde": desde}).json()["results"]
        }
        assert api.get(URL, {"desde": "ayer"}).status_code == 400
        assert api.get(URL, {"usuario": "no-es-uuid"}).status_code == 400

    def test_pagina_por_numero_con_20_filas_por_defecto(self, panel):
        e = panel["e"]
        for i in range(45):
            evento(organizacion_id=e.org_a.pk, accion=f"carga.{i:02d}")
        api = cliente_de("admin")
        primera = api.get(URL, {"accion": "carga."}).json()
        assert (primera["count"], len(primera["results"])) == (45, 20)
        assert primera["next"] and primera["previous"] is None
        # El orden es del más reciente al más antiguo y estable entre páginas.
        segunda = api.get(URL, {"accion": "carga.", "page": 2}).json()
        tercera = api.get(URL, {"accion": "carga.", "page": 3}).json()
        assert len(segunda["results"]) == 20 and len(tercera["results"]) == 5
        ids = [x["id"] for p in (primera, segunda, tercera) for x in p["results"]]
        assert len(ids) == len(set(ids)) == 45
        assert ids == sorted(ids, reverse=True)

    @pytest.mark.parametrize(("pedido", "esperado"), [(10, 10), (50, 45), (25, 20), (500, 45)])
    def test_tamanos_de_pagina_permitidos(self, panel, pedido, esperado):
        e = panel["e"]
        for i in range(45):
            evento(organizacion_id=e.org_a.pk, accion=f"carga.{i:02d}")
        r = cliente_de("admin").get(URL, {"accion": "carga.", "page_size": pedido}).json()
        assert (
            len(r["results"]) == esperado
        )  # 25 no está en el catálogo: vuelve a 20; 500 se limita al máximo (100)
