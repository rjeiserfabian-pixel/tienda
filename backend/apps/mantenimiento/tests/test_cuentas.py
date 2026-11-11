"""Cajas y cuentas (efectivo, banco, billetera) de cada empresa."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.mantenimiento.models import CuentaFinanciera
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento/cuentas"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", e.emp_a1)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", e.emp_a1)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", e.emp_a1)]),
        "almacenero": nuevo_usuario(e.org_a, "almacenero", [e.emp_a1], [("ALMACENERO", e.emp_a1)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
        "tienda1": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre="Tienda 1", codigo="001"
        ),
        "tienda2": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre="Tienda 2", codigo="002"
        ),
        "otra_tienda": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a2, nombre="Sucursal B", codigo="001"
        ),
    }


def _crear(api, equipo, *, nombre="Caja efectivo", tipo="CAJA", empresa=1, **extra):
    emp = equipo["e"].emp_a1 if empresa == 1 else equipo["e"].emp_a2
    return api.post(
        f"{BASE}/", {"empresa": emp.pk, "nombre": nombre, "tipo": tipo, **extra}, format="json"
    )


def _ok(respuesta):
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()


CCI = "00219300123456789012"


# ---------------------------------------------------------------------------
# Alta
# ---------------------------------------------------------------------------
class TestAlta:
    def test_no_hay_cuentas_de_fabrica(self, equipo):
        assert CuentaFinanciera.objects.sin_ambito().count() == 0

    def test_caja_de_efectivo_en_soles_por_defecto(self, equipo):
        c = _ok(_crear(cliente_de("super"), equipo))
        assert (c["tipo_nombre"], c["moneda"], c["saldo_inicial"], c["estado"]) == (
            "Caja de efectivo",
            "PEN",
            "0.00",
            "ACTIVO",
        )
        assert (c["sucursal"], c["banco"], c["numero_cuenta"]) == (None, "", "")

    def test_cuenta_de_banco_en_dolares(self, equipo):
        c = _ok(
            _crear(
                cliente_de("super"),
                equipo,
                nombre="BBVA dólares",
                tipo="BANCO",
                moneda="USD",
                banco="BBVA",
                numero_cuenta="0011-0123-45",
                cci=CCI,
            )
        )
        assert (c["moneda"], c["moneda_nombre"], c["banco"], c["cci"]) == (
            "USD",
            "Dólares",
            "BBVA",
            CCI,
        )

    def test_billetera_digital(self, equipo):
        c = _ok(
            _crear(
                cliente_de("super"),
                equipo,
                nombre="Yape de la tienda",
                tipo="BILLETERA",
                numero_cuenta="987654321",
            )
        )
        assert c["tipo_nombre"] == "Billetera digital"

    def test_una_caja_por_tienda(self, equipo):
        api = cliente_de("super")
        uno = _ok(_crear(api, equipo, nombre="Caja tienda 1", sucursal=equipo["tienda1"].pk))
        dos = _ok(_crear(api, equipo, nombre="Caja tienda 2", sucursal=equipo["tienda2"].pk))
        general = _ok(_crear(api, equipo, nombre="BCP soles", tipo="BANCO", banco="BCP"))
        assert (uno["sucursal_nombre"], dos["sucursal_nombre"], general["sucursal"]) == (
            "Tienda 1",
            "Tienda 2",
            None,
        )
        e = equipo["e"]
        de_tienda_1 = api.get(
            f"{BASE}/", {"empresa": e.emp_a1.pk, "sucursal": equipo["tienda1"].pk}
        ).json()["results"]
        assert [c["nombre"] for c in de_tienda_1] == ["Caja tienda 1"]

    def test_el_saldo_inicial_pide_su_fecha(self, equipo):
        api = cliente_de("super")
        assert _crear(api, equipo, saldo_inicial="500.00").status_code == 400
        c = _ok(
            _crear(
                api,
                equipo,
                saldo_inicial="500.00",
                fecha_saldo_inicial=timezone.localdate().isoformat(),
            )
        )
        assert c["saldo_inicial"] == "500.00"

    def test_el_nombre_no_se_repite_en_la_empresa_pero_si_entre_empresas(self, equipo):
        api = cliente_de("super")
        _ok(_crear(api, equipo, nombre="Caja efectivo"))
        repetido = _crear(api, equipo, nombre="CAJA EFECTIVO")
        assert repetido.status_code == 400 and "nombre" in str(repetido.json()).lower()
        _ok(_crear(api, equipo, nombre="Caja efectivo", empresa=2))  # otra empresa: otro dinero

    def test_normaliza_los_textos(self, equipo):
        c = _ok(
            _crear(
                cliente_de("super"),
                equipo,
                nombre="  Cuenta   BCP ",
                tipo="BANCO",
                banco="  BCP   Perú ",
                numero_cuenta="193 - 123456 - 0",
            )
        )
        assert (c["nombre"], c["banco"], c["numero_cuenta"]) == (
            "Cuenta BCP",
            "BCP Perú",
            "193-123456-0",
        )

    @pytest.mark.parametrize(
        "malo",
        [
            {"tipo": "CAJA", "banco": "BCP"},  # una caja no lleva datos de banco
            {"tipo": "CAJA", "numero_cuenta": "123456"},
            {"tipo": "BANCO"},  # el banco es obligatorio
            {"tipo": "BANCO", "banco": "BCP", "numero_cuenta": "abc"},
            {"tipo": "BANCO", "banco": "BCP", "cci": "123"},  # el CCI son 20 números
            {"tipo": "BILLETERA", "cci": CCI},
            {"moneda": "EUR"},
            {"saldo_inicial": "-5"},
            {"saldo_inicial": "1.234"},
            {"nombre": ""},
            {"sucursal": 99999},
        ],
    )
    def test_datos_invalidos(self, equipo, malo):
        assert _crear(cliente_de("super"), equipo, **malo).status_code == 400

    def test_la_fecha_del_saldo_no_es_futura(self, equipo):
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = _crear(cliente_de("super"), equipo, saldo_inicial="10", fecha_saldo_inicial=manana)
        assert r.status_code == 400

    def test_la_sucursal_debe_ser_de_la_empresa(self, equipo):
        r = _crear(cliente_de("super"), equipo, sucursal=equipo["otra_tienda"].pk)
        assert r.status_code == 400 and "sucursal" in str(r.json()).lower()

    def test_el_tipo_es_obligatorio(self, equipo):
        e = equipo["e"]
        r = cliente_de("super").post(
            f"{BASE}/", {"empresa": e.emp_a1.pk, "nombre": "X"}, format="json"
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Edición y baja
# ---------------------------------------------------------------------------
class TestEdicion:
    def _banco(self, equipo):
        return _ok(
            _crear(
                cliente_de("super"),
                equipo,
                nombre="BCP soles",
                tipo="BANCO",
                banco="BCP",
                numero_cuenta="193123456789",
            )
        )

    def _patch(self, cuenta_id, datos, usuario="super"):
        return cliente_de(usuario).patch(f"{BASE}/{cuenta_id}/", datos, format="json")

    def test_la_moneda_no_cambia(self, equipo):
        c = self._banco(equipo)
        assert self._patch(c["id"], {"moneda": "USD"}).status_code == 400
        assert self._patch(c["id"], {"tipo": "BANCO", "moneda": "PEN"}).status_code == 200

    def test_un_banco_pasa_a_billetera_y_a_caja(self, equipo):
        c = self._banco(equipo)
        r = self._patch(c["id"], {"tipo": "BILLETERA", "cci": ""})
        assert r.status_code == 200, r.content
        assert r.json()["tipo"] == "BILLETERA"
        r = self._patch(c["id"], {"tipo": "CAJA", "rol_caja": "MOSTRADOR", "exige_sesion": True})
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["tipo"], d["rol_caja"], d["banco"], d["numero_cuenta"]) == (
            "CAJA",
            "MOSTRADOR",
            "",
            "",
        )

    def test_una_caja_pasa_a_billetera_si_no_tuvo_sesiones(self, equipo):
        c = _ok(_crear(cliente_de("super"), equipo, rol_caja="MOSTRADOR", exige_sesion=True))
        r = self._patch(c["id"], {"tipo": "BILLETERA", "banco": "Yape"})
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["tipo"], d["rol_caja"], d["exige_sesion"]) == ("BILLETERA", "", False)

    def test_una_caja_con_sesiones_sigue_siendo_caja(self, equipo):
        from apps.caja.models import SesionCaja

        c = _ok(_crear(cliente_de("super"), equipo, rol_caja="MOSTRADOR", exige_sesion=True))
        cuenta = CuentaFinanciera.objects.sin_ambito().get(pk=c["id"])
        SesionCaja.objects.sin_ambito().create(
            empresa=cuenta.empresa,
            cuenta=cuenta,
            numero=1,
            estado="ABIERTA",
            responsable_id=equipo["super"].pk,
            abierta_en=timezone.now(),
        )
        r = self._patch(c["id"], {"tipo": "BILLETERA"})
        assert r.status_code == 400 and "sesiones" in json.dumps(r.json())

    def test_se_edita_el_resto(self, equipo):
        c = self._banco(equipo)
        r = self._patch(
            c["id"],
            {
                "nombre": "BCP principal",
                "sucursal": equipo["tienda1"].pk,
                "saldo_inicial": "250.50",
                "fecha_saldo_inicial": timezone.localdate().isoformat(),
            },
        )
        assert r.status_code == 200, r.content
        assert (r.json()["nombre"], r.json()["sucursal_nombre"], r.json()["saldo_inicial"]) == (
            "BCP principal",
            "Tienda 1",
            "250.50",
        )

    def test_se_quita_la_sucursal(self, equipo):
        c = _ok(_crear(cliente_de("super"), equipo, sucursal=equipo["tienda1"].pk))
        assert self._patch(c["id"], {"sucursal": None}).json()["sucursal"] is None

    def test_se_desactiva_y_reactiva(self, equipo):
        c = self._banco(equipo)
        assert self._patch(c["id"], {"estado": "INACTIVO"}).json()["estado"] == "INACTIVO"
        assert self._patch(c["id"], {"estado": "ACTIVO"}).json()["estado"] == "ACTIVO"

    def test_la_empresa_no_cambia(self, equipo):
        c = self._banco(equipo)
        assert self._patch(c["id"], {"empresa": equipo["e"].emp_a2.pk}).status_code == 400

    def test_no_se_pasa_una_caja_a_banco_editando_sus_datos(self, equipo):
        c = _ok(_crear(cliente_de("super"), equipo))
        assert (
            self._patch(c["id"], {"banco": "BCP"}).status_code == 400
        )  # sigue siendo una caja de efectivo

    def test_el_cambio_queda_auditado_sin_el_numero_de_cuenta(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        c = self._banco(equipo)
        self._patch(c["id"], {"numero_cuenta": "999888777666"})
        detalle = AuditoriaEvento.objects.get(accion="cuenta_financiera.editado").detalle
        assert detalle["numero_cuenta"] == "modificado"
        assert "999888777666" not in str(detalle)

    def test_el_borrado_es_logico(self, equipo):
        c = _ok(_crear(cliente_de("super"), equipo))
        assert cliente_de("super").delete(f"{BASE}/{c['id']}/").status_code == 204
        assert CuentaFinanciera.objects.sin_ambito().count() == 0
        # El nombre queda libre para una caja nueva.
        _ok(_crear(cliente_de("super"), equipo))


# ---------------------------------------------------------------------------
# Datos sensibles, permisos y aislamiento
# ---------------------------------------------------------------------------
class TestPermisos:
    def _banco(self, equipo):
        return _ok(
            _crear(
                cliente_de("super"),
                equipo,
                nombre="BCP soles",
                tipo="BANCO",
                banco="BCP",
                numero_cuenta="193123456789",
                cci=CCI,
            )
        )

    def test_quien_edita_ve_los_datos_completos(self, equipo):
        self._banco(equipo)
        e = equipo["e"]
        fila = cliente_de("contador").get(f"{BASE}/", {"empresa": e.emp_a1.pk}).json()["results"][0]
        assert (fila["numero_cuenta"], fila["cci"]) == ("193123456789", CCI)

    def test_los_demas_ven_solo_los_ultimos_4_digitos(self, equipo):
        self._banco(equipo)
        e = equipo["e"]
        for usuario in ("cajero", "vendedor"):
            fila = (
                cliente_de(usuario).get(f"{BASE}/", {"empresa": e.emp_a1.pk}).json()["results"][0]
            )
            assert fila["numero_cuenta"] == "••••6789", usuario
            assert fila["cci"] == ""
            assert fila["banco"] == "BCP"  # el banco no es secreto: sirve para elegir la cuenta

    def test_cajero_y_vendedor_ven_pero_no_cambian(self, equipo):
        c = self._banco(equipo)
        for usuario in ("cajero", "vendedor"):
            api = cliente_de(usuario)
            assert (
                api.post(
                    f"{BASE}/",
                    {"empresa": equipo["e"].emp_a1.pk, "nombre": "X", "tipo": "CAJA"},
                    format="json",
                ).status_code
                == 403
            )
            assert (
                api.patch(f"{BASE}/{c['id']}/", {"nombre": "Y"}, format="json").status_code == 403
            )
            assert api.delete(f"{BASE}/{c['id']}/").status_code == 403

    def test_el_almacenero_no_las_ve(self, equipo):
        e = equipo["e"]
        assert cliente_de("almacenero").get(f"{BASE}/", {"empresa": e.emp_a1.pk}).status_code == 403

    def test_el_contador_crea_y_edita_pero_no_elimina(self, equipo):
        api = cliente_de("contador")
        c = _ok(_crear(api, equipo, nombre="Caja contador"))
        assert (
            api.patch(f"{BASE}/{c['id']}/", {"nombre": "Caja 2"}, format="json").status_code == 200
        )
        assert api.delete(f"{BASE}/{c['id']}/").status_code == 403

    def test_no_se_toca_una_empresa_sin_acceso(self, equipo):
        # El contador solo tiene acceso a la empresa 1.
        assert _crear(cliente_de("contador"), equipo, empresa=2).status_code == 403

    def test_cada_empresa_ve_las_suyas(self, equipo):
        api = cliente_de("super")
        _ok(_crear(api, equipo, nombre="Caja A1", empresa=1))
        _ok(_crear(api, equipo, nombre="Caja A2", empresa=2))
        e = equipo["e"]
        a1 = api.get(f"{BASE}/", {"empresa": e.emp_a1.pk}).json()["results"]
        assert [c["nombre"] for c in a1] == ["Caja A1"]

    def test_otra_organizacion_no_ve_nada(self, equipo):
        c = self._banco(equipo)
        otra = cliente_de("otra_org")
        assert otra.get(f"{BASE}/{c['id']}/").status_code == 404
        e = equipo["e"]
        assert otra.get(f"{BASE}/", {"empresa": e.emp_b1.pk}).json()["count"] == 0


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
class TestListado:
    def test_filtra_y_busca(self, equipo):
        api = cliente_de("super")
        _ok(_crear(api, equipo, nombre="Caja efectivo"))
        _ok(_crear(api, equipo, nombre="BCP soles", tipo="BANCO", banco="BCP"))
        _ok(_crear(api, equipo, nombre="BBVA dólares", tipo="BANCO", banco="BBVA", moneda="USD"))
        e = equipo["e"]

        def lista(**params):
            return sorted(
                c["nombre"]
                for c in api.get(f"{BASE}/", {"empresa": e.emp_a1.pk, **params}).json()["results"]
            )

        assert lista(tipo="BANCO") == ["BBVA dólares", "BCP soles"]
        assert lista(moneda="USD") == ["BBVA dólares"]
        assert lista(q="bcp") == ["BCP soles"]
        assert len(lista()) == 3

    def test_el_saldo_inicial_viaja_como_texto_sin_perder_decimales(self, equipo):
        api = cliente_de("super")
        c = _ok(
            _crear(
                api,
                equipo,
                saldo_inicial="1234567.89",
                fecha_saldo_inicial=timezone.localdate().isoformat(),
            )
        )
        assert Decimal(c["saldo_inicial"]) == Decimal("1234567.89")
