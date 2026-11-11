"""Personal, clientes y proveedores: alta, edición, baja lógica, permisos y aislamiento."""

import pytest

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento.models import Cliente, Personal
from apps.mantenimiento.validators import normalizar_documento, validar_documento
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"
RUC = ruc_valido("2060308400")


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "almacen": nuevo_usuario(e.org_a, "almacen", [e.emp_a1], [("ALMACENERO", None)]),
        "admin_a1": nuevo_usuario(e.org_a, "admin_a1", [e.emp_a1], [("ADMIN", e.emp_a1)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def cliente_json(**extra):
    return {"tipo_documento": "DNI", "numero_documento": "45871236", "nombre": "Ana Ruiz", **extra}


def personal_json(empresa, **extra):
    return {
        "empresa": empresa.pk,
        "tipo_documento": "DNI",
        "numero_documento": "71234567",
        "nombres": "Luis",
        "apellidos": "Ramos Soto",
        "area": "TECNICO",
        **extra,
    }


# ---------------------------------------------------------------------------
# Validación de documentos
# ---------------------------------------------------------------------------
class TestDocumentos:
    def test_normaliza_espacios_guiones_y_mayusculas(self):
        assert normalizar_documento(" 20-1000 abc ") == "201000ABC"

    @pytest.mark.parametrize(
        ("tipo", "numero"),
        [("DNI", "45871236"), ("RUC", RUC), ("CE", "001234567"), ("PASAPORTE", "AB123456")],
    )
    def test_documentos_validos(self, tipo, numero):
        validar_documento(tipo, numero)

    @pytest.mark.parametrize(
        ("tipo", "numero"),
        [
            ("DNI", "1234567"),
            ("DNI", "1234567A"),
            ("RUC", "20100000018"),
            ("CE", "123"),
            ("PASAPORTE", "AB"),
            ("OTRO", "x"),
            ("DNI", ""),
        ],
    )
    def test_documentos_invalidos(self, tipo, numero):
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            validar_documento(tipo, numero)


# ---------------------------------------------------------------------------
# Clientes (organización)
# ---------------------------------------------------------------------------
class TestClientes:
    def test_alta_edicion_y_baja_con_auditoria(self, equipo):
        api = cliente_de("super")
        r = api.post(f"{BASE}/clientes/", cliente_json(numero_documento="4587-1236"), format="json")
        assert r.status_code == 201, r.content
        cliente = r.json()
        assert cliente["numero_documento"] == "45871236"  # normalizado
        assert cliente["estado"] == "ACTIVO"

        r = api.patch(
            f"{BASE}/clientes/{cliente['id']}/",
            {"telefono": "987654321", "estado": "INACTIVO"},
            format="json",
        )
        assert r.status_code == 200 and r.json()["estado"] == "INACTIVO"

        assert api.delete(f"{BASE}/clientes/{cliente['id']}/").status_code == 204
        assert api.get(f"{BASE}/clientes/{cliente['id']}/").status_code == 404
        # Borrado lógico: la fila sigue en la base y el documento queda libre.
        assert Cliente.objects.sin_ambito(incluir_eliminados=True).filter(pk=cliente["id"]).exists()
        assert api.post(f"{BASE}/clientes/", cliente_json(), format="json").status_code == 201
        acciones = set(AuditoriaEvento.objects.values_list("accion", flat=True))
        assert {"cliente.creado", "cliente.editado", "cliente.eliminado"} <= acciones

    def test_documento_invalido_o_repetido_se_rechaza(self, equipo):
        api = cliente_de("super")
        assert (
            api.post(
                f"{BASE}/clientes/", cliente_json(numero_documento="123"), format="json"
            ).status_code
            == 400
        )
        ruc_malo = cliente_json(tipo_documento="RUC", numero_documento="20100000018")
        assert api.post(f"{BASE}/clientes/", ruc_malo, format="json").status_code == 400
        assert api.post(f"{BASE}/clientes/", cliente_json(), format="json").status_code == 201
        repetido = api.post(f"{BASE}/clientes/", cliente_json(nombre="Otra"), format="json")
        assert repetido.status_code == 400
        assert "documento" in str(repetido.json()).lower()
        # El mismo número con otro tipo de documento es otra persona.
        distinto = cliente_json(tipo_documento="OTRO", numero_documento="45871236")
        assert api.post(f"{BASE}/clientes/", distinto, format="json").status_code == 201

    def test_vendedor_crea_y_edita_pero_no_elimina(self, equipo):
        api = cliente_de("vendedor")
        r = api.post(f"{BASE}/clientes/", cliente_json(), format="json")
        assert r.status_code == 201
        assert (
            api.patch(
                f"{BASE}/clientes/{r.json()['id']}/", {"nombre": "X"}, format="json"
            ).status_code
            == 200
        )
        assert api.delete(f"{BASE}/clientes/{r.json()['id']}/").status_code == 403

    def test_cajero_solo_consulta(self, equipo):
        cliente_de("super").post(f"{BASE}/clientes/", cliente_json(), format="json")
        api = cliente_de("cajero")
        assert api.get(f"{BASE}/clientes/").json()["count"] == 1
        assert (
            api.post(
                f"{BASE}/clientes/", cliente_json(numero_documento="11111111"), format="json"
            ).status_code
            == 403
        )

    def test_sin_permiso_no_ve_ni_lista(self, equipo):
        assert cliente_de("almacen").get(f"{BASE}/clientes/").status_code == 403

    def test_busqueda_filtro_orden_y_paginacion(self, equipo):
        api = cliente_de("super")
        for i, nombre in enumerate(["Zeta SAC", "Alfa SAC", "Beta Perú"]):
            api.post(
                f"{BASE}/clientes/",
                cliente_json(nombre=nombre, numero_documento=f"4000000{i}"),
                format="json",
            )
        lista = api.get(f"{BASE}/clientes/").json()
        assert [c["nombre"] for c in lista["results"]] == ["Alfa SAC", "Beta Perú", "Zeta SAC"]
        assert [
            c["nombre"] for c in api.get(f"{BASE}/clientes/", {"q": "sac"}).json()["results"]
        ] == ["Alfa SAC", "Zeta SAC"]
        assert api.get(f"{BASE}/clientes/", {"q": "40000001"}).json()["count"] == 1
        assert api.get(f"{BASE}/clientes/", {"estado": "INACTIVO"}).json()["count"] == 0
        assert [
            c["nombre"]
            for c in api.get(f"{BASE}/clientes/", {"orden": "-nombre"}).json()["results"]
        ][0] == "Zeta SAC"
        pagina = api.get(f"{BASE}/clientes/", {"page_size": 10}).json()
        assert {"count", "next", "previous", "results"} <= pagina.keys()

    def test_otra_organizacion_no_los_ve_ni_los_toca(self, equipo):
        creado = cliente_de("super").post(f"{BASE}/clientes/", cliente_json(), format="json").json()
        ajeno = cliente_de("otra_org")
        assert ajeno.get(f"{BASE}/clientes/").json()["count"] == 0
        assert ajeno.get(f"{BASE}/clientes/{creado['id']}/").status_code == 404
        assert (
            ajeno.patch(
                f"{BASE}/clientes/{creado['id']}/", {"nombre": "x"}, format="json"
            ).status_code
            == 404
        )
        assert ajeno.delete(f"{BASE}/clientes/{creado['id']}/").status_code == 404
        # El mismo documento puede existir en otra organización.
        assert ajeno.post(f"{BASE}/clientes/", cliente_json(), format="json").status_code == 201


# ---------------------------------------------------------------------------
# Proveedores (organización)
# ---------------------------------------------------------------------------
class TestProveedores:
    def datos(self, **extra):
        return {
            "tipo_documento": "RUC",
            "numero_documento": RUC,
            "nombre": "Distribuidora Andina SAC",
            "contacto": "Marta Silva",
            **extra,
        }

    def test_alta_con_contacto(self, equipo):
        r = cliente_de("super").post(f"{BASE}/proveedores/", self.datos(), format="json")
        assert r.status_code == 201, r.content
        assert r.json()["contacto"] == "Marta Silva"
        assert AuditoriaEvento.objects.filter(accion="proveedor.creado").exists()

    def test_el_almacenero_consulta_pero_no_crea(self, equipo):
        cliente_de("super").post(f"{BASE}/proveedores/", self.datos(), format="json")
        api = cliente_de("almacen")
        assert api.get(f"{BASE}/proveedores/").json()["count"] == 1
        assert api.post(f"{BASE}/proveedores/", self.datos(), format="json").status_code == 403
        assert api.get(f"{BASE}/proveedores/", {"q": "marta"}).json()["count"] == 1

    def test_ciudad_se_guarda_sin_espacios_de_mas_y_se_busca(self, equipo):
        api = cliente_de("super")
        r = api.post(f"{BASE}/proveedores/", self.datos(ciudad="  Lima   Cercado "), format="json")
        assert r.status_code == 201, r.content
        assert r.json()["ciudad"] == "Lima Cercado"
        assert api.get(f"{BASE}/proveedores/", {"q": "cercado"}).json()["count"] == 1
        assert api.get(f"{BASE}/proveedores/", {"q": "arequipa"}).json()["count"] == 0
        r = api.patch(
            f"{BASE}/proveedores/{r.json()['id']}/", {"ciudad": "Arequipa"}, format="json"
        )
        assert r.json()["ciudad"] == "Arequipa"


# ---------------------------------------------------------------------------
# Personal (por empresa)
# ---------------------------------------------------------------------------
class TestPersonal:
    def test_alta_exige_empresa_y_la_valida(self, equipo):
        e = equipo["e"]
        api = cliente_de("super")
        sin_empresa = personal_json(e.emp_a1)
        sin_empresa.pop("empresa")
        assert api.post(f"{BASE}/personal/", sin_empresa, format="json").status_code == 400
        r = api.post(f"{BASE}/personal/", personal_json(e.emp_a1), format="json")
        assert r.status_code == 201, r.content
        assert (r.json()["nombre_completo"], r.json()["area"]) == ("Luis Ramos Soto", "TECNICO")
        # Empresa de otra organización: no existe para este usuario.
        assert api.post(
            f"{BASE}/personal/", personal_json(e.emp_b1), format="json"
        ).status_code in (400, 403)

    def test_el_documento_es_unico_por_empresa(self, equipo):
        e = equipo["e"]
        api = cliente_de("super")
        assert (
            api.post(f"{BASE}/personal/", personal_json(e.emp_a1), format="json").status_code == 201
        )
        assert (
            api.post(f"{BASE}/personal/", personal_json(e.emp_a1), format="json").status_code == 400
        )
        assert (
            api.post(f"{BASE}/personal/", personal_json(e.emp_a2), format="json").status_code == 201
        )

    def test_el_alcance_por_empresa_se_respeta(self, equipo):
        e = equipo["e"]
        cliente_de("super").post(
            f"{BASE}/personal/", personal_json(e.emp_a2, numero_documento="70000002"), format="json"
        )
        cliente_de("super").post(f"{BASE}/personal/", personal_json(e.emp_a1), format="json")
        api = cliente_de("admin_a1")
        assert (
            api.post(
                f"{BASE}/personal/",
                personal_json(e.emp_a2, numero_documento="70000003"),
                format="json",
            ).status_code
            == 403
        )
        assert (
            api.post(
                f"{BASE}/personal/",
                personal_json(e.emp_a1, numero_documento="70000004"),
                format="json",
            ).status_code
            == 201
        )
        lista = api.get(f"{BASE}/personal/").json()
        assert {p["empresa"] for p in lista["results"]} == {e.emp_a1.pk}

    def test_edicion_filtros_y_baja(self, equipo):
        e = equipo["e"]
        api = cliente_de("super")
        creado = api.post(
            f"{BASE}/personal/", personal_json(e.emp_a1, fecha_ingreso="2025-03-01"), format="json"
        ).json()
        assert creado["fecha_ingreso"] == "2025-03-01"
        url = f"{BASE}/personal/{creado['id']}/"
        assert (
            api.patch(
                url, {"cargo": "Jefe de taller", "area": "ADMINISTRACION"}, format="json"
            ).status_code
            == 200
        )
        # No se cambia de empresa.
        assert api.patch(url, {"empresa": e.emp_a2.pk}, format="json").status_code == 400
        assert api.get(f"{BASE}/personal/", {"area": "ADMINISTRACION"}).json()["count"] == 1
        assert api.get(f"{BASE}/personal/", {"area": "VENTAS"}).json()["count"] == 0
        assert api.get(f"{BASE}/personal/", {"q": "jefe"}).json()["count"] == 1
        assert api.delete(url).status_code == 204
        assert api.get(url).status_code == 404
        assert Personal.objects.sin_ambito(incluir_eliminados=True).filter(pk=creado["id"]).exists()

    def test_sin_permiso_de_personal_no_entra(self, equipo):
        assert cliente_de("vendedor").get(f"{BASE}/personal/").status_code == 403

    def test_fecha_de_nacimiento_se_guarda_y_se_valida(self, equipo):
        e = equipo["e"]
        api = cliente_de("super")
        r = api.post(
            f"{BASE}/personal/",
            personal_json(e.emp_a1, fecha_nacimiento="1990-05-17"),
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["fecha_nacimiento"] == "1990-05-17"
        url = f"{BASE}/personal/{r.json()['id']}/"
        assert api.patch(url, {"fecha_nacimiento": "2999-01-01"}, format="json").status_code == 400
        assert api.patch(url, {"fecha_nacimiento": "1850-01-01"}, format="json").status_code == 400
        # El ingreso no puede ser anterior al nacimiento.
        assert api.patch(url, {"fecha_ingreso": "1980-01-01"}, format="json").status_code == 400
        assert api.patch(url, {"fecha_nacimiento": None}, format="json").status_code == 200


# ---------------------------------------------------------------------------
# Asesor del cliente
# ---------------------------------------------------------------------------
class TestAsesor:
    def test_quien_registra_queda_como_asesor_aunque_envie_otro(self, equipo):
        super_id = str(equipo["super"].pk)
        api = cliente_de("vendedor")
        r = api.post(f"{BASE}/clientes/", cliente_json(asesor=super_id), format="json")
        assert r.status_code == 201, r.content
        assert r.json()["asesor"] == str(equipo["vendedor"].pk)
        assert r.json()["asesor_nombre"] == "vendedor"  # sin nombres: se muestra el usuario

    def test_quien_puede_asignar_elige_al_asesor_o_queda_el_mismo(self, equipo):
        api = cliente_de("super")
        vendedor_id = str(equipo["vendedor"].pk)
        elegido = api.post(f"{BASE}/clientes/", cliente_json(asesor=vendedor_id), format="json")
        assert elegido.json()["asesor"] == vendedor_id
        por_defecto = api.post(
            f"{BASE}/clientes/", cliente_json(numero_documento="45871237"), format="json"
        )
        assert por_defecto.json()["asesor"] == str(equipo["super"].pk)

    def test_el_asesor_debe_ser_un_usuario_activo_de_la_organizacion(self, equipo):
        api = cliente_de("super")
        for asesor in (str(equipo["otra_org"].pk), "00000000-0000-0000-0000-000000000000"):
            r = api.post(f"{BASE}/clientes/", cliente_json(asesor=asesor), format="json")
            assert r.status_code == 400
        inactivo = equipo["cajero"]
        inactivo.is_active = False
        inactivo.save()
        assert (
            api.post(
                f"{BASE}/clientes/", cliente_json(asesor=str(inactivo.pk)), format="json"
            ).status_code
            == 400
        )

    def test_solo_quien_puede_asignar_cambia_el_asesor_y_queda_en_auditoria(self, equipo):
        creado = (
            cliente_de("vendedor").post(f"{BASE}/clientes/", cliente_json(), format="json").json()
        )
        url = f"{BASE}/clientes/{creado['id']}/"
        # El vendedor edita otros datos; su intento de reasignar se ignora.
        r = cliente_de("vendedor").patch(
            url, {"telefono": "999", "asesor": str(equipo["super"].pk)}, format="json"
        )
        assert r.status_code == 200 and r.json()["asesor"] == str(equipo["vendedor"].pk)
        # El superadmin sí reasigna.
        r = cliente_de("super").patch(url, {"asesor": str(equipo["super"].pk)}, format="json")
        assert r.status_code == 200 and r.json()["asesor"] == str(equipo["super"].pk)
        evento = AuditoriaEvento.objects.filter(accion="cliente.editado").latest("id")
        assert evento.detalle["asesor"] == [str(equipo["vendedor"].pk), str(equipo["super"].pk)]

    def test_se_filtra_por_asesor_y_los_proveedores_no_lo_tienen(self, equipo):
        cliente_de("vendedor").post(f"{BASE}/clientes/", cliente_json(), format="json")
        cliente_de("super").post(
            f"{BASE}/clientes/", cliente_json(numero_documento="45871237"), format="json"
        )
        api = cliente_de("super")
        mios = api.get(f"{BASE}/clientes/", {"asesor": str(equipo["vendedor"].pk)}).json()
        assert mios["count"] == 1 and mios["results"][0]["asesor_nombre"] == "vendedor"
        assert api.get(f"{BASE}/clientes/", {"asesor": "no-es-uuid"}).status_code == 400
        proveedor = api.post(
            f"{BASE}/proveedores/",
            {"tipo_documento": "RUC", "numero_documento": RUC, "nombre": "Andina SAC"},
            format="json",
        )
        assert proveedor.status_code == 201 and "asesor" not in proveedor.json()

    def test_el_permiso_de_asignar_lo_tienen_superadmin_y_administrador(self):
        from apps.seguridad import permisos_catalogo as cat

        codigo = "MANTENIMIENTO.CLIENTES.ASIGNAR_ASESOR"
        por_rol = {r.codigo: r.permisos for r in cat.ROLES_PLANTILLA}
        assert codigo in por_rol["SUPERADMIN"] and codigo in por_rol["ADMIN"]
        assert not any(
            codigo in permisos
            for r, permisos in por_rol.items()
            if r not in ("SUPERADMIN", "ADMIN")
        )


# ---------------------------------------------------------------------------
# Datos de pago y productos del proveedor
# ---------------------------------------------------------------------------
class TestProveedorCuentaYProductos:
    def datos(self, **extra):
        return {
            "tipo_documento": "RUC",
            "numero_documento": RUC,
            "nombre": "Distribuidora Andina SAC",
            **extra,
        }

    def test_se_guardan_la_cuenta_y_los_productos_de_referencia(self, equipo):
        api = cliente_de("super")
        r = api.post(
            f"{BASE}/proveedores/",
            self.datos(
                banco="BCP",
                cuenta_bancaria="193-12345678-0-12",
                productos_referencia="Baterías, aceites y filtros para motos",
            ),
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["cuenta_bancaria"] == "193-12345678-0-12"
        assert "aceites" in r.json()["productos_referencia"]
        # Se encuentra al proveedor por lo que vende.
        assert api.get(f"{BASE}/proveedores/", {"q": "filtros"}).json()["count"] == 1
        assert api.get(f"{BASE}/proveedores/", {"q": "zapatos"}).json()["count"] == 0

    def test_la_cuenta_se_valida_y_se_normaliza(self, equipo):
        api = cliente_de("super")
        for mala in ("12", "cuenta@banco", "x" * 31):
            r = api.post(
                f"{BASE}/proveedores/", self.datos(banco="BCP", cuenta_bancaria=mala), format="json"
            )
            assert r.status_code == 400, mala
        ok = api.post(
            f"{BASE}/proveedores/",
            self.datos(banco="BCP", cuenta_bancaria="  193   12345678  "),
            format="json",
        )
        assert ok.status_code == 201 and ok.json()["cuenta_bancaria"] == "193 12345678"

    def test_los_productos_tienen_un_tope_de_largo(self, equipo):
        r = cliente_de("super").post(
            f"{BASE}/proveedores/", self.datos(productos_referencia="x" * 1001), format="json"
        )
        assert r.status_code == 400

    def test_la_auditoria_no_guarda_el_numero_de_cuenta(self, equipo):
        api = cliente_de("super")
        creado = api.post(
            f"{BASE}/proveedores/",
            self.datos(banco="BCP", cuenta_bancaria="193-11111111-0-11"),
            format="json",
        ).json()
        api.patch(
            f"{BASE}/proveedores/{creado['id']}/",
            {"cuenta_bancaria": "193-22222222-0-22", "contacto": "Marta"},
            format="json",
        )
        evento = AuditoriaEvento.objects.filter(accion="proveedor.editado").latest("id")
        assert evento.detalle["cuenta_bancaria"] == "modificado"
        assert "contacto" in evento.detalle
        assert "22222222" not in str(
            AuditoriaEvento.objects.values_list("detalle", flat=True).all()
        )

    def test_la_cuenta_solo_la_ve_quien_puede_editar_proveedores(self, equipo):
        creado = cliente_de("super").post(
            f"{BASE}/proveedores/",
            self.datos(banco="BCP", cuenta_bancaria="193-12345678-0-12"),
            format="json",
        )
        assert creado.json()["cuenta_bancaria"] == "193-12345678-0-12"
        # El almacenero consulta proveedores (VER) pero no edita: la cuenta no le llega.
        api = cliente_de("almacen")
        assert api.get(f"{BASE}/proveedores/").json()["results"][0]["cuenta_bancaria"] is None
        detalle = api.get(f"{BASE}/proveedores/{creado.json()['id']}/").json()
        assert detalle["cuenta_bancaria"] is None and detalle["nombre"]
        assert "193-12345678" not in api.get(f"{BASE}/proveedores/").content.decode()

    def test_toda_cuenta_lleva_su_banco_y_el_banco_debe_ser_de_la_lista(self, equipo):
        api = cliente_de("super")
        sin_banco = api.post(
            f"{BASE}/proveedores/", self.datos(cuenta_bancaria="193-12345678-0-12"), format="json"
        )
        assert sin_banco.status_code == 400 and "banco" in str(sin_banco.json()).lower()
        raro = api.post(
            f"{BASE}/proveedores/",
            self.datos(banco="BANCO_INVENTADO", cuenta_bancaria="193-1234"),
            format="json",
        )
        assert raro.status_code == 400
        ok = api.post(
            f"{BASE}/proveedores/",
            self.datos(banco="BANCO_NACION", cuenta_bancaria="00-123-456789"),
            format="json",
        )
        assert ok.status_code == 201 and ok.json()["banco"] == "BANCO_NACION"
        # El banco, como la cuenta, no le llega a quien solo consulta.
        assert (
            cliente_de("almacen").get(f"{BASE}/proveedores/{ok.json()['id']}/").json()["banco"]
            == ""
        )
