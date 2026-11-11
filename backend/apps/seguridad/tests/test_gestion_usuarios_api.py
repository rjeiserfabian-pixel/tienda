"""Panel de usuarios: listado con visibilidad, alta, edición, accesos, roles y excepciones."""

import pytest

from apps.organizacion.models import Sucursal
from apps.seguridad.models import AccesoEmpresa, Rol, Usuario
from apps.seguridad.tests.conftest import PASSWORD, cliente_de, iniciar_sesion

pytestmark = pytest.mark.django_db

BASE = "/api/v1/seguridad"


@pytest.fixture
def panel(nuevo_usuario, rbac):
    e = rbac
    return {
        "e": e,
        "superadmin": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "admin": nuevo_usuario(e.org_a, "admin", [e.emp_a1, e.emp_a2], [("ADMIN", None)]),
        "admin_a1": nuevo_usuario(e.org_a, "admin_a1", [e.emp_a1], [("ADMIN", e.emp_a1)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1, e.emp_a2], [("VENDEDOR", None)]),
        "solo_a2": nuevo_usuario(e.org_a, "solo_a2", [e.emp_a2]),
        "otro_b": nuevo_usuario(e.org_b, "otro_b", [e.emp_b1], [("ADMIN", None)]),
    }


def url(usuario, sufijo=""):
    return f"{BASE}/usuarios/{usuario.pk}/{sufijo}"


def rol_id(organizacion, codigo):
    return Rol.objects.sin_ambito().get(organizacion=organizacion, codigo=codigo).pk


def error(respuesta):
    return respuesta.json()["error"]["codigo"]


# ---------------------------------------------------------------------------
# Listado y visibilidad
# ---------------------------------------------------------------------------
def test_el_listado_solo_trae_la_propia_organizacion(panel):
    api = cliente_de("admin")
    r = api.get(f"{BASE}/usuarios/")
    assert r.status_code == 200
    nombres = {u["username"] for u in r.json()["results"]}
    assert {"super", "admin", "admin_a1", "vendedor", "solo_a2"} <= nombres
    assert "otro_b" not in nombres
    assert r.json()["count"] == len(nombres)


def test_sin_permiso_no_se_lista_ni_se_crea(panel):
    api = cliente_de("vendedor")
    assert api.get(f"{BASE}/usuarios/").status_code == 403
    r = api.post(f"{BASE}/usuarios/", {}, format="json")
    assert r.status_code == 403
    assert error(r) == "permiso_denegado"


def test_un_administrador_acotado_solo_ve_a_quienes_comparten_su_empresa(panel):
    api = cliente_de("admin_a1")
    nombres = {u["username"] for u in api.get(f"{BASE}/usuarios/").json()["results"]}
    assert "solo_a2" not in nombres
    assert "vendedor" in nombres
    assert api.get(url(panel["solo_a2"])).status_code == 404


def test_un_usuario_de_otra_organizacion_no_existe_para_mi(panel):
    api = cliente_de("admin")
    assert api.get(url(panel["otro_b"])).status_code == 404
    assert api.patch(url(panel["otro_b"]), {"nombres": "X"}, format="json").status_code == 404


def test_filtros_de_busqueda_y_estado(panel):
    api = cliente_de("admin")
    r = api.get(f"{BASE}/usuarios/", {"q": "vend"})
    assert [u["username"] for u in r.json()["results"]] == ["vendedor"]
    assert api.get(f"{BASE}/usuarios/", {"activo": "false"}).json()["count"] == 0


def test_el_listado_se_ordena_por_columnas_permitidas(panel):
    api = cliente_de("admin")
    nombres = lambda orden: [  # noqa: E731
        u["username"] for u in api.get(f"{BASE}/usuarios/", {"orden": orden}).json()["results"]
    ]
    ascendente = nombres("username")
    assert ascendente == sorted(ascendente)
    assert nombres("-username") == ascendente[::-1]
    # Quien nunca ingresó (último acceso vacío) queda al final en ambos sentidos.
    assert nombres("ultimo_acceso")[-1] != "admin"  # admin acaba de iniciar sesión
    assert nombres("-ultimo_acceso")[0] == "admin"
    # Un campo no permitido se ignora (no rompe ni expone nada).
    assert nombres("password") == ascendente
    assert nombres("-organizacion__nombre") == ascendente


def test_el_listado_pagina_y_consulta_pocas_veces(panel, django_assert_max_num_queries):
    api = cliente_de("admin")
    r = api.get(f"{BASE}/usuarios/", {"page_size": 10})
    assert set(r.json()) >= {"count", "next", "previous", "results"}
    with django_assert_max_num_queries(25):  # sin N+1: no crece con la cantidad de usuarios
        assert api.get(f"{BASE}/usuarios/").status_code == 200


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
def alta(api, e, **extra):
    datos = {
        "username": "nuevo",
        "email": "Nuevo@Ejemplo.com",
        "password": PASSWORD,
        "nombres": "Nuevo",
        "empresa_ids": [e.emp_a1.pk],
        **extra,
    }
    return api.post(f"{BASE}/usuarios/", datos, format="json")


def test_alta_de_usuario_con_clave_temporal(panel):
    e = panel["e"]
    r = alta(cliente_de("admin"), e)
    assert r.status_code == 201, r.content
    cuerpo = r.json()
    assert cuerpo["email"] == "nuevo@ejemplo.com"
    assert cuerpo["debe_cambiar_password"] is True
    assert [a["empresa"] for a in cuerpo["accesos"]] == [e.emp_a1.pk]
    assert iniciar_sesion(cliente_de("admin"), "nuevo").status_code == 200


def test_alta_con_todos_los_datos_del_formulario(panel):
    """Teléfono, documento, estado y rol viajan en la misma creación."""
    api, e = cliente_de("admin"), panel["e"]
    r = alta(
        api,
        e,
        telefono="987 654 321",
        documento_numero="12345678",
        activo=False,
        rol=rol_id(e.org_a, "CAJERO"),
        cargo="Cajera",
    )
    assert r.status_code == 201, r.content
    cuerpo = r.json()
    assert (cuerpo["telefono"], cuerpo["documento_numero"]) == ("987 654 321", "12345678")
    assert cuerpo["activo"] is False
    assert cuerpo["roles"] == ["CAJERO"]
    assert cuerpo["accesos"][0]["cargo"] == "Cajera"


def test_alta_valida_telefono_documento_y_rol(panel):
    api, e = cliente_de("admin"), panel["e"]
    assert alta(api, e, telefono="abc").status_code == 400
    assert alta(api, e, documento_numero="12").status_code == 400
    r = alta(api, e, rol=rol_id(e.org_b, "CAJERO"))  # rol de otra organización
    assert (r.status_code, r.json()["error"]["detalle"]) == (400, {"rol": "No existe."})
    assert not Usuario.objects.filter(username="nuevo").exists()


def test_si_no_puede_otorgar_el_rol_no_se_crea_el_usuario(panel, nuevo_usuario):
    """Crear con rol es atómico y respeta la anti-escalada."""
    e, admin = panel["e"], cliente_de("admin")
    rol = admin.post(
        f"{BASE}/roles/",
        {
            "codigo": "SOLO_ALTAS",
            "nombre": "Solo altas",
            "permisos": {
                "SEGURIDAD.USUARIOS.VER": "EMPRESA",
                "SEGURIDAD.USUARIOS.CREAR": "EMPRESA",
            },
        },
        format="json",
    ).json()["id"]
    gestor = nuevo_usuario(e.org_a, "gestor", [e.emp_a1, e.emp_a2])
    admin.post(url(gestor, "roles/"), {"rol": rol, "empresa": None}, format="json")

    r = alta(cliente_de("gestor"), e, rol=rol_id(e.org_a, "ADMIN"))
    assert (r.status_code, error(r)) == (403, "permiso_denegado")
    assert not Usuario.objects.filter(username="nuevo").exists()
    assert alta(cliente_de("gestor"), e).status_code == 201  # sin rol sí puede


def test_alta_con_clave_debil_o_repetida_se_rechaza(panel):
    api, e = cliente_de("admin"), panel["e"]
    assert alta(api, e, password="123").status_code == 400
    assert alta(api, e, username="otro", email="ana@x.com").status_code == 201
    assert alta(api, e, username="otro2", email="ana@x.com").status_code == 400  # correo repetido


def test_no_se_da_acceso_a_empresas_donde_no_se_tiene_permiso(panel):
    api, e = cliente_de("admin_a1"), panel["e"]
    r = alta(api, e, empresa_ids=[e.emp_a2.pk])
    assert r.status_code == 403
    assert error(r) == "permiso_denegado"
    assert alta(api, e, empresa_ids=[e.emp_b1.pk]).status_code == 403
    assert alta(api, e, empresa_ids=[]).status_code == 400


def test_edicion_de_datos_personales(panel):
    api = cliente_de("admin")
    r = api.patch(
        url(panel["vendedor"]), {"nombres": "Nuevo nombre", "telefono": "999"}, format="json"
    )
    assert r.status_code == 200
    assert r.json()["nombres"] == "Nuevo nombre"
    # Reenviar el mismo nombre de usuario no es cambiarlo (y no exige el permiso de cambiarlo).
    assert (
        api.patch(url(panel["vendedor"]), {"username": "vendedor"}, format="json").status_code
        == 200
    )


def test_el_administrador_cambia_el_nombre_de_usuario_y_queda_auditado(panel, monkeypatch):
    from apps.auditoria import servicios
    from apps.auditoria.models import AuditoriaEvento

    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())
    api = cliente_de("admin")
    r = api.patch(url(panel["vendedor"]), {"username": "ventas.lima"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["username"] == "ventas.lima"
    evento = AuditoriaEvento.objects.get(accion="usuario.username_cambiado")
    assert evento.detalle == {"anterior": "vendedor", "nuevo": "ventas.lima"}
    # Ahora entra con el nombre nuevo y el viejo ya no existe.
    assert iniciar_sesion(cliente_de("super"), "ventas.lima").status_code == 200
    assert iniciar_sesion(cliente_de("super"), "vendedor").status_code == 401


def test_el_nombre_de_usuario_nuevo_debe_ser_valido_y_libre(panel):
    api = cliente_de("admin")
    objetivo = url(panel["vendedor"])
    for invalido in ("con espacio", "con@arroba", "ADMIN", "Super"):  # formato o repetido
        r = api.patch(objetivo, {"username": invalido}, format="json")
        assert r.status_code == 400, invalido
    # Solo cambiar mayúsculas de su propio nombre es válido.
    assert api.patch(objetivo, {"username": "Vendedor"}, format="json").status_code == 200
    panel["vendedor"].refresh_from_db()
    assert panel["vendedor"].username == "Vendedor"


def test_el_nombre_de_usuario_no_se_cambia_a_uno_mismo_ni_a_quien_tiene_mas_privilegios(panel):
    api = cliente_de("admin")
    propio = api.patch(url(panel["admin"]), {"username": "otro_admin"}, format="json")
    assert (propio.status_code, error(propio)) == (409, "operacion_sobre_si_mismo")
    mayor = api.patch(url(panel["superadmin"]), {"username": "jefe"}, format="json")
    assert (mayor.status_code, error(mayor)) == (403, "usuario_con_mas_privilegios")


def test_hace_falta_el_permiso_de_cambiar_el_nombre_de_usuario(panel):
    from apps.seguridad.models import Permiso, UsuarioPermiso
    from apps.seguridad.services import permisos_engine as motor

    e = panel["e"]
    UsuarioPermiso.objects.sin_ambito().create(
        organizacion=e.org_a,
        usuario=panel["admin"],
        permiso=Permiso.objects.get(codigo="SEGURIDAD.USUARIOS.CAMBIAR_USUARIO"),
        tipo="DENY",
        alcance="ORGANIZACION",
        motivo="Prueba: sin permiso de renombrar",
    )
    motor.invalidar_usuario(panel["admin"].pk)
    api = cliente_de("admin")
    r = api.patch(url(panel["vendedor"]), {"username": "nuevo"}, format="json")
    assert (r.status_code, error(r)) == (403, "permiso_denegado")
    # Editar otros datos del mismo usuario sigue permitido.
    assert api.patch(url(panel["vendedor"]), {"nombres": "Ana"}, format="json").status_code == 200


def test_no_se_cambia_el_correo_de_alguien_con_mas_privilegios(panel):
    api = cliente_de("admin")
    r = api.patch(url(panel["superadmin"]), {"email": "robado@x.com"}, format="json")
    assert r.status_code == 403
    assert error(r) == "usuario_con_mas_privilegios"
    # Los datos no sensibles sí se pueden editar.
    assert (
        api.patch(url(panel["superadmin"]), {"nombres": "Super"}, format="json").status_code == 200
    )


def test_el_correo_no_puede_duplicarse(panel):
    api = cliente_de("admin")
    r = api.patch(url(panel["vendedor"]), {"email": "admin@ejemplo.com"}, format="json")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Desactivar y reactivar
# ---------------------------------------------------------------------------
def test_desactivar_cierra_sesiones_y_reactivar_devuelve_el_acceso(panel):
    api, vendedor = cliente_de("admin"), cliente_de("vendedor")
    assert vendedor.get(f"{BASE}/me/").status_code == 200
    r = api.post(url(panel["vendedor"], "desactivar/"))
    assert r.status_code == 200
    assert r.json()["activo"] is False
    assert vendedor.get(f"{BASE}/me/").status_code == 401
    assert iniciar_sesion(cliente_de("admin"), "vendedor").status_code == 401

    assert api.post(url(panel["vendedor"], "reactivar/")).json()["activo"] is True
    assert iniciar_sesion(cliente_de("admin"), "vendedor").status_code == 200


def test_no_se_desactiva_a_si_mismo_ni_a_un_superior(panel):
    api = cliente_de("admin")
    r = api.post(url(panel["admin"], "desactivar/"))
    assert (r.status_code, error(r)) == (409, "operacion_sobre_si_mismo")
    r = api.post(url(panel["superadmin"], "desactivar/"))
    assert (r.status_code, error(r)) == (403, "usuario_con_mas_privilegios")


def test_quien_no_tiene_el_permiso_no_desactiva(panel):
    assert cliente_de("vendedor").post(url(panel["admin"], "desactivar/")).status_code == 403


# ---------------------------------------------------------------------------
# Accesos a empresas y sucursales
# ---------------------------------------------------------------------------
def acceso_url(usuario, empresa):
    return url(usuario, f"accesos/{empresa.pk}/")


def test_establecer_y_quitar_acceso_con_sucursales(panel):
    api, e = cliente_de("admin"), panel["e"]
    sucursal = Sucursal.objects.sin_ambito().create(empresa=e.emp_a1, nombre="Tienda", codigo="T1")
    r = api.put(
        acceso_url(panel["solo_a2"], e.emp_a1),
        {"cargo": "Jefe", "sucursales": [sucursal.pk]},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.json()["cargo"] == "Jefe"
    assert r.json()["sucursales"] == [sucursal.pk]

    r = api.put(acceso_url(panel["solo_a2"], e.emp_a1), {"cargo": "Jefe"}, format="json")
    assert r.json()["sucursales"] == []  # el conjunto de sucursales se reemplaza

    assert api.delete(acceso_url(panel["solo_a2"], e.emp_a1)).status_code == 204
    detalle = api.get(url(panel["solo_a2"])).json()
    assert [a["empresa"] for a in detalle["accesos"]] == [e.emp_a2.pk]


def test_una_sucursal_de_otra_empresa_no_vale(panel):
    api, e = cliente_de("admin"), panel["e"]
    ajena = Sucursal.objects.sin_ambito().create(empresa=e.emp_a2, nombre="Otra", codigo="O1")
    r = api.put(acceso_url(panel["solo_a2"], e.emp_a1), {"sucursales": [ajena.pk]}, format="json")
    assert r.status_code == 400


def test_no_se_gestiona_el_propio_acceso_ni_empresas_ajenas(panel):
    e = panel["e"]
    api = cliente_de("admin")
    r = api.put(acceso_url(panel["admin"], e.emp_a1), {}, format="json")
    assert (r.status_code, error(r)) == (409, "operacion_sobre_si_mismo")
    # admin_a1 solo administra la empresa A1.
    r = cliente_de("admin_a1").put(acceso_url(panel["vendedor"], e.emp_a2), {}, format="json")
    assert r.status_code == 403


def test_dar_acceso_no_sirve_para_ampliar_permisos(panel, nuevo_usuario):
    """Los roles globales del destinatario rigen en la empresa nueva: hay que poseerlos."""
    e = panel["e"]
    admin = cliente_de("admin")
    rol = admin.post(
        f"{BASE}/roles/",
        {
            "codigo": "GESTOR",
            "nombre": "Gestor de usuarios",
            "permisos": {
                "SEGURIDAD.USUARIOS.VER": "EMPRESA",
                "SEGURIDAD.USUARIOS.EDITAR": "EMPRESA",
            },
        },
        format="json",
    )
    assert rol.status_code == 201, rol.content
    gestor = nuevo_usuario(e.org_a, "gestor", [e.emp_a1, e.emp_a2])
    r = admin.post(url(gestor, "roles/"), {"rol": rol.json()["id"], "empresa": None}, format="json")
    assert r.status_code == 201, r.content
    poderoso = nuevo_usuario(e.org_a, "poderoso", [e.emp_a1], [("ADMIN", None)])

    r = cliente_de("gestor").put(acceso_url(poderoso, e.emp_a2), {}, format="json")
    assert r.status_code == 403
    assert error(r) == "escalada_de_privilegios"
    assert (
        not AccesoEmpresa.objects.sin_ambito().filter(usuario=poderoso, empresa=e.emp_a2).exists()
    )


# ---------------------------------------------------------------------------
# Roles y excepciones del usuario
# ---------------------------------------------------------------------------
def test_asignar_y_quitar_un_rol(panel):
    api, e = cliente_de("admin"), panel["e"]
    cuerpo = {"rol": rol_id(e.org_a, "CAJERO"), "empresa": e.emp_a1.pk}
    r = api.post(url(panel["vendedor"], "roles/"), cuerpo, format="json")
    assert r.status_code == 201, r.content
    asignacion = r.json()["id"]
    roles = api.get(url(panel["vendedor"])).json()["roles"]
    assert roles == ["CAJERO", "VENDEDOR"]

    assert api.delete(url(panel["vendedor"], f"roles/{asignacion}/")).status_code == 204
    assert api.delete(url(panel["vendedor"], f"roles/{asignacion}/")).status_code == 404


def test_no_se_asigna_un_rol_de_otra_organizacion_ni_sin_permiso(panel):
    e = panel["e"]
    admin = cliente_de("admin")
    ajeno = {"rol": rol_id(e.org_b, "CAJERO"), "empresa": None}
    assert admin.post(url(panel["vendedor"], "roles/"), ajeno, format="json").status_code == 400
    propio = {"rol": rol_id(e.org_a, "CAJERO"), "empresa": None}
    assert (
        cliente_de("vendedor")
        .post(url(panel["admin"], "roles/"), propio, format="json")
        .status_code
        == 403
    )


def test_excepcion_individual_exige_motivo(panel):
    api, e = cliente_de("admin"), panel["e"]
    cuerpo = {
        "codigo": "VENTAS.VENDER",
        "tipo": "DENY",
        "empresa": e.emp_a1.pk,
        "motivo": "Auditoría en curso",
    }
    assert (
        api.post(
            url(panel["vendedor"], "excepciones/"), {**cuerpo, "motivo": ""}, format="json"
        ).status_code
        == 400
    )
    r = api.post(url(panel["vendedor"], "excepciones/"), cuerpo, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["codigo"] == "VENTAS.VENDER"
    assert [x["tipo"] for x in api.get(url(panel["vendedor"])).json()["excepciones"]] == ["DENY"]
    assert api.delete(url(panel["vendedor"], f"excepciones/{r.json()['id']}/")).status_code == 204


def test_la_excepcion_deniega_de_inmediato(panel):
    api, e = cliente_de("admin"), panel["e"]
    vendedor = cliente_de("vendedor")
    assert (
        vendedor.get(f"{BASE}/permisos/mios/", {"empresa": e.emp_a1.pk})
        .json()["permisos"]
        .get("VENTAS.VENDER")
    )
    cuerpo = {"codigo": "VENTAS.VENDER", "tipo": "DENY", "empresa": e.emp_a1.pk, "motivo": "Prueba"}
    assert (
        api.post(url(panel["vendedor"], "excepciones/"), cuerpo, format="json").status_code == 201
    )
    mios = vendedor.get(f"{BASE}/permisos/mios/", {"empresa": e.emp_a1.pk}).json()["permisos"]
    assert "VENTAS.VENDER" not in mios
