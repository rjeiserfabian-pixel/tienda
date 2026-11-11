"""Organización, empresas y sucursales: gestión por API."""

import pytest

from apps.organizacion.models import Empresa, Sucursal
from apps.seguridad.models import AccesoEmpresa
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

pytestmark = pytest.mark.django_db

BASE = "/api/v1/organizacion"
RUC_NUEVO = ruc_valido("2010000009")


@pytest.fixture
def panel(nuevo_usuario, rbac):
    e = rbac
    return {
        "e": e,
        "superadmin": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "admin": nuevo_usuario(e.org_a, "admin", [e.emp_a1, e.emp_a2], [("ADMIN", None)]),
        "admin_a1": nuevo_usuario(e.org_a, "admin_a1", [e.emp_a1], [("ADMIN", e.emp_a1)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
    }


def error(respuesta):
    return respuesta.json()["error"]["codigo"]


# ---------------------------------------------------------------------------
# Organización
# ---------------------------------------------------------------------------
def test_cualquiera_ve_su_organizacion_pero_solo_quien_gestiona_la_edita(panel):
    assert cliente_de("vendedor").get(f"{BASE}/").json()["nombre"] == "Organización A"
    nuevo = {"nombre": "Grupo Nuevo"}
    # ADMIN no tiene SEGURIDAD.ORGANIZACION.GESTIONAR (solo SUPERADMIN).
    assert cliente_de("admin").patch(f"{BASE}/", nuevo, format="json").status_code == 403
    r = cliente_de("super").patch(f"{BASE}/", nuevo, format="json")
    assert r.status_code == 200
    assert r.json()["nombre"] == "Grupo Nuevo"


def test_el_nombre_de_la_organizacion_no_se_repite(panel):
    r = cliente_de("super").patch(f"{BASE}/", {"nombre": "Organización B"}, format="json")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------
def test_el_listado_trae_solo_las_empresas_con_acceso(panel):
    e = panel["e"]
    todas = cliente_de("admin").get(f"{BASE}/empresas/").json()["results"]
    assert {x["id"] for x in todas} == {e.emp_a1.pk, e.emp_a2.pk}
    propias = cliente_de("admin_a1").get(f"{BASE}/empresas/").json()["results"]
    assert [x["id"] for x in propias] == [e.emp_a1.pk]
    assert cliente_de("admin").get(f"{BASE}/empresas/", {"q": "A2"}).json()["count"] == 1


def test_alta_de_empresa_con_sucursal_principal_y_acceso_del_creador(panel):
    api = cliente_de("admin")
    r = api.post(
        f"{BASE}/empresas/", {"ruc": RUC_NUEVO, "razon_social": "Nueva SAC"}, format="json"
    )
    assert r.status_code == 201, r.content
    empresa = Empresa.objects.sin_ambito().get(pk=r.json()["id"])
    assert Sucursal.objects.sin_ambito().filter(empresa=empresa, codigo="001").exists()
    assert (
        AccesoEmpresa.objects.sin_ambito().filter(empresa=empresa, usuario=panel["admin"]).exists()
    )
    assert api.get(f"{BASE}/empresas/{empresa.pk}/").status_code == 200


def test_la_empresa_nueva_hereda_el_cargo_del_creador(panel):
    from apps.seguridad.services.accesos import empresas_habilitadas

    e, admin = panel["e"], panel["admin"]
    AccesoEmpresa.objects.sin_ambito().filter(usuario=admin).update(cargo="Gerente general")
    r = cliente_de("admin").post(
        f"{BASE}/empresas/", {"ruc": RUC_NUEVO, "razon_social": "Nueva SAC"}, format="json"
    )
    assert r.status_code == 201, r.content
    acceso = AccesoEmpresa.objects.sin_ambito().get(empresa_id=r.json()["id"], usuario=admin)
    assert acceso.cargo == "Gerente general"
    # Y una empresa sin cargo propio muestra el que la persona tiene en otra.
    AccesoEmpresa.objects.sin_ambito().filter(usuario=admin, empresa=e.emp_a2).update(cargo="")
    cargos = {x.id: x.cargo for x in empresas_habilitadas(admin)}
    assert cargos[e.emp_a2.pk] == "Gerente general"


def test_ruc_invalido_o_repetido_se_rechaza(panel):
    api, e = cliente_de("admin"), panel["e"]
    assert (
        api.post(
            f"{BASE}/empresas/", {"ruc": "123", "razon_social": "X"}, format="json"
        ).status_code
        == 400
    )
    repetido = api.post(
        f"{BASE}/empresas/", {"ruc": e.emp_a1.ruc, "razon_social": "X"}, format="json"
    )
    assert repetido.status_code == 400
    de_otra_org = api.post(
        f"{BASE}/empresas/", {"ruc": e.emp_b1.ruc, "razon_social": "X"}, format="json"
    )
    assert de_otra_org.status_code == 400  # el RUC es único en todo el sistema


def test_sin_permiso_no_se_crean_ni_editan_empresas(panel):
    e = panel["e"]
    vendedor = cliente_de("vendedor")
    assert (
        vendedor.post(
            f"{BASE}/empresas/", {"ruc": RUC_NUEVO, "razon_social": "X"}, format="json"
        ).status_code
        == 403
    )
    assert (
        vendedor.patch(
            f"{BASE}/empresas/{e.emp_a1.pk}/", {"razon_social": "Y"}, format="json"
        ).status_code
        == 403
    )


def test_un_administrador_acotado_no_edita_otra_empresa(panel):
    e = panel["e"]
    api = cliente_de("admin_a1")
    assert (
        api.patch(
            f"{BASE}/empresas/{e.emp_a1.pk}/", {"razon_social": "Renombrada"}, format="json"
        ).status_code
        == 200
    )
    assert (
        api.patch(
            f"{BASE}/empresas/{e.emp_a2.pk}/", {"razon_social": "Ajena"}, format="json"
        ).status_code
        == 404
    )


def test_solo_quien_gestiona_la_organizacion_cambia_el_ruc(panel, monkeypatch):
    from apps.auditoria import servicios

    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())
    e = panel["e"]
    url = f"{BASE}/empresas/{e.emp_a1.pk}/"
    # Un administrador edita la ficha, pero el RUC no es suyo: se rechaza y no cambia nada.
    admin = cliente_de("admin")
    r = admin.patch(url, {"razon_social": "Nueva razón", "ruc": RUC_NUEVO}, format="json")
    assert r.status_code == 403
    assert Empresa.objects.sin_ambito().get(pk=e.emp_a1.pk).ruc == e.emp_a1.ruc
    # Reenviar el mismo RUC no cuenta como cambiarlo.
    r = admin.patch(url, {"razon_social": "Nueva razón", "ruc": e.emp_a1.ruc}, format="json")
    assert r.status_code == 200
    # El superadministrador sí, y queda auditado con el valor anterior y el nuevo.
    r = cliente_de("super").patch(url, {"ruc": RUC_NUEVO}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["ruc"] == RUC_NUEVO
    from apps.auditoria.models import AuditoriaEvento

    evento = AuditoriaEvento.objects.get(accion="empresa.ruc_cambiado")
    assert evento.detalle == {"ruc_anterior": e.emp_a1.ruc, "ruc_nuevo": RUC_NUEVO}


def test_el_ruc_nuevo_debe_ser_valido_y_no_estar_en_uso(panel):
    e = panel["e"]
    api = cliente_de("super")
    url = f"{BASE}/empresas/{e.emp_a1.pk}/"
    assert api.patch(url, {"ruc": "123"}, format="json").status_code == 400
    assert api.patch(url, {"ruc": "20100000018"}, format="json").status_code == 400  # verificador
    assert api.patch(url, {"ruc": e.emp_a2.ruc}, format="json").status_code == 400  # en uso
    assert api.patch(url, {"ruc": e.emp_b1.ruc}, format="json").status_code == 400  # otra org
    assert Empresa.objects.sin_ambito().get(pk=e.emp_a1.pk).ruc == e.emp_a1.ruc


def test_el_ruc_se_bloquea_cuando_la_empresa_emitio_documentos(panel, monkeypatch):
    from apps.organizacion.services import gestion

    e = panel["e"]
    url = f"{BASE}/empresas/{e.emp_a1.pk}/"
    monkeypatch.setattr(gestion, "tiene_documentos_emitidos", lambda empresa: True)
    r = cliente_de("super").patch(url, {"ruc": RUC_NUEVO}, format="json")
    assert (r.status_code, error(r)) == (409, "ruc_bloqueado")
    # Lo demás de la ficha sigue editable.
    ok = cliente_de("super").patch(url, {"nombre_comercial": "Otro"}, format="json")
    assert ok.status_code == 200


def test_inactivar_y_reactivar_una_empresa(panel):
    api, e = cliente_de("admin"), panel["e"]
    r = api.patch(f"{BASE}/empresas/{e.emp_a2.pk}/", {"estado": "INACTIVO"}, format="json")
    assert r.status_code == 200, r.content
    inactivas = api.get(f"{BASE}/empresas/", {"estado": "INACTIVO"}).json()["results"]
    assert [x["id"] for x in inactivas] == [e.emp_a2.pk]
    r = api.patch(f"{BASE}/empresas/{e.emp_a2.pk}/", {"estado": "ACTIVO"}, format="json")
    assert r.status_code == 200
    assert r.json()["estado"] == "ACTIVO"


def test_la_organizacion_conserva_una_empresa_activa(panel):
    api, e = cliente_de("admin"), panel["e"]
    assert (
        api.patch(
            f"{BASE}/empresas/{e.emp_a2.pk}/", {"estado": "INACTIVO"}, format="json"
        ).status_code
        == 200
    )
    r = api.patch(f"{BASE}/empresas/{e.emp_a1.pk}/", {"estado": "INACTIVO"}, format="json")
    assert (r.status_code, error(r)) == (409, "ultima_empresa_activa")


def test_las_empresas_de_otra_organizacion_no_existen(panel):
    e = panel["e"]
    api = cliente_de("admin")
    assert api.get(f"{BASE}/empresas/{e.emp_b1.pk}/").status_code == 404
    assert (
        api.patch(
            f"{BASE}/empresas/{e.emp_b1.pk}/", {"razon_social": "X"}, format="json"
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Sucursales
# ---------------------------------------------------------------------------
def nueva_sucursal(api, empresa, **extra):
    datos = {"empresa": empresa.pk, "nombre": "Centro", "codigo": "c1", **extra}
    return api.post(f"{BASE}/sucursales/", datos, format="json")


def test_alta_listado_y_edicion_de_sucursales(panel):
    api, e = cliente_de("admin"), panel["e"]
    r = nueva_sucursal(api, e.emp_a1, direccion="Av. Lima 123")
    assert r.status_code == 201, r.content
    assert r.json()["codigo"] == "C1"  # el código se normaliza
    nueva_sucursal(api, e.emp_a1, nombre="Otra", codigo="o1")  # para poder desactivar la primera
    lista = api.get(f"{BASE}/sucursales/", {"empresa": e.emp_a1.pk}).json()
    assert lista["count"] == 2
    r = api.patch(
        f"{BASE}/sucursales/{r.json()['id']}/",
        {"estado": "INACTIVO", "nombre": "Centro 2"},
        format="json",
    )
    assert r.status_code == 200
    assert (r.json()["estado"], r.json()["nombre"], r.json()["codigo"]) == (
        "INACTIVO",
        "Centro 2",
        "C1",
    )


def test_no_se_desactiva_la_ultima_sucursal_activa_de_una_empresa(panel):
    api, e = cliente_de("admin"), panel["e"]
    unica = nueva_sucursal(api, e.emp_a1, codigo="u1").json()
    r = api.patch(f"{BASE}/sucursales/{unica['id']}/", {"estado": "INACTIVO"}, format="json")
    assert (r.status_code, error(r)) == (409, "ultima_sucursal_activa")
    assert Sucursal.objects.sin_ambito().get(pk=unica["id"]).estado == "ACTIVO"
    # Con otra activa sí se puede; y la que queda ya no se puede desactivar.
    otra = nueva_sucursal(api, e.emp_a1, codigo="u2").json()
    assert (
        api.patch(
            f"{BASE}/sucursales/{unica['id']}/", {"estado": "INACTIVO"}, format="json"
        ).status_code
        == 200
    )
    r = api.patch(f"{BASE}/sucursales/{otra['id']}/", {"estado": "INACTIVO"}, format="json")
    assert (r.status_code, error(r)) == (409, "ultima_sucursal_activa")
    # Reactivar y editar otros datos de la última activa siguen permitidos.
    assert (
        api.patch(
            f"{BASE}/sucursales/{otra['id']}/", {"nombre": "Nueva"}, format="json"
        ).status_code
        == 200
    )
    assert (
        api.patch(
            f"{BASE}/sucursales/{unica['id']}/", {"estado": "ACTIVO"}, format="json"
        ).status_code
        == 200
    )


def test_la_lista_de_sucursales_se_busca_por_texto_y_estado(panel):
    api, e = cliente_de("admin"), panel["e"]
    nueva_sucursal(api, e.emp_a1, nombre="Centro Lima", codigo="c1", direccion="Av. Arequipa 10")
    nueva_sucursal(api, e.emp_a1, nombre="Norte", codigo="n1")
    url = f"{BASE}/sucursales/"
    por = lambda **filtros: {  # noqa: E731
        x["codigo"] for x in api.get(url, {"empresa": e.emp_a1.pk, **filtros}).json()["results"]
    }
    assert por(q="lima") == {"C1"}
    assert por(q="arequipa") == {"C1"}
    assert por(q="N1") == {"N1"}
    assert por(q="no-existe") == set()
    assert "N1" in por(estado="ACTIVO")


def test_codigo_de_sucursal_repetido_en_la_empresa(panel):
    api, e = cliente_de("admin"), panel["e"]
    assert nueva_sucursal(api, e.emp_a1).status_code == 201
    assert nueva_sucursal(api, e.emp_a1).status_code == 400
    assert nueva_sucursal(api, e.emp_a2).status_code == 201  # en otra empresa sí puede repetirse


def test_la_empresa_es_obligatoria_y_se_valida_el_permiso_en_ella(panel):
    e = panel["e"]
    assert (
        cliente_de("admin")
        .post(f"{BASE}/sucursales/", {"nombre": "X", "codigo": "X"}, format="json")
        .status_code
        == 400
    )
    assert nueva_sucursal(cliente_de("admin_a1"), e.emp_a2).status_code == 403
    assert nueva_sucursal(cliente_de("vendedor"), e.emp_a1).status_code == 403
    assert nueva_sucursal(cliente_de("admin"), e.emp_b1).status_code == 403


def test_una_empresa_nueva_acepta_sucursales_tras_renovar_la_sesion(panel):
    api = cliente_de("admin")
    r = api.post(
        f"{BASE}/empresas/", {"ruc": RUC_NUEVO, "razon_social": "Nueva SAC"}, format="json"
    )
    nueva = Empresa.objects.sin_ambito().get(pk=r.json()["id"])
    # El token aún no lista la empresa nueva: se pide renovarlo (el front lo hace solo).
    assert nueva_sucursal(api, nueva).status_code == 403
    assert nueva_sucursal(cliente_de("admin"), nueva).status_code == 201


def test_sucursales_de_otra_empresa_o_organizacion_no_se_tocan(panel):
    e = panel["e"]
    ajena = Sucursal.objects.sin_ambito().create(empresa=e.emp_b1, nombre="B", codigo="B1")
    api = cliente_de("admin")
    assert (
        api.patch(
            f"{BASE}/sucursales/{ajena.pk}/", {"nombre": "X", "estado": "ACTIVO"}, format="json"
        ).status_code
        == 404
    )
    assert api.get(f"{BASE}/sucursales/{ajena.pk}/").status_code == 404
