"""API de caja y bancos: permisos, idempotencia, filtros, saldo corrido, saldos y anulación."""

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.caja.models import MovimientoCaja
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja
from apps.mantenimiento.models import ConceptoCaja, CuentaFinanciera
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/caja"
_claves = itertools.count(1)


def clave():
    return f"caja-de-prueba-{next(_claves):06d}"


@pytest.fixture
def datos(mundo, nuevo_usuario):  # noqa: F811
    e = mundo.e
    nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", e.emp_a1)])
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_conceptos_caja(e.org_a.pk)
    caja = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1, nombre="Caja soles", tipo="CAJA", moneda="PEN"
    )
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1, nombre="BCP soles", tipo="BANCO", moneda="PEN", banco="BCP"
    )
    conceptos = {
        c.codigo: c for c in ConceptoCaja.objects.sin_ambito().filter(organizacion=e.org_a)
    }
    return type("Datos", (), {"mundo": mundo, "caja": caja, "banco": banco, "conceptos": conceptos})


def cuerpo(datos, **extra):
    base = {
        "empresa": datos.mundo.e1.pk,
        "cuenta": datos.caja.pk,
        "tipo": "INGRESO",
        "concepto": datos.conceptos["APORTE_CAPITAL"].pk,
        "monto": "500.00",
        "glosa": "Aporte inicial",
    }
    return {**base, **extra}


def registrar(usuario, datos_enviados, llave=None):
    return cliente_de(usuario).post(
        f"{BASE}/movimientos/", datos_enviados, format="json", HTTP_IDEMPOTENCY_KEY=llave or clave()
    )


class TestRegistrar:
    def test_el_contador_registra_un_ingreso(self, datos):
        r = registrar("contador", cuerpo(datos))
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["tipo"], d["monto"], d["estado"]) == (
            1,
            "INGRESO",
            "500.00",
            "EMITIDO",
        )
        assert (d["cuenta_nombre"], d["concepto_nombre"], d["moneda"]) == (
            "Caja soles",
            "Aporte de capital",
            "PEN",
        )
        assert d["puede_anularse"] is True

    def test_reintento_con_la_misma_clave_no_duplica(self, datos):
        llave = clave()
        primera = registrar("contador", cuerpo(datos), llave)
        segunda = registrar("contador", cuerpo(datos), llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda.json() == primera.json()
        assert MovimientoCaja.objects.sin_ambito().count() == 1

    def test_sin_clave_no_registra(self, datos):
        r = cliente_de("contador").post(f"{BASE}/movimientos/", cuerpo(datos), format="json")
        assert r.status_code == 400
        assert MovimientoCaja.objects.sin_ambito().count() == 0

    def test_errores_de_negocio_y_de_referencias(self, datos):
        assert registrar("contador", cuerpo(datos, monto="0")).status_code == 400
        assert registrar("contador", cuerpo(datos, cuenta=999_999)).status_code == 400
        assert registrar("contador", cuerpo(datos, concepto=999_999)).status_code == 400
        # El concepto de un egreso no sirve para un ingreso.
        egreso = datos.conceptos["GASTOS_VARIOS"].pk
        r = registrar("contador", cuerpo(datos, concepto=egreso))
        assert r.status_code == 400
        assert r.json()["error"]["codigo"] == "movimiento_caja_invalido"

    def test_los_conceptos_del_sistema_no_se_usan_a_mano(self, datos):
        r = registrar(
            "contador", cuerpo(datos, tipo="EGRESO", concepto=datos.conceptos["PAGO_PROVEEDOR"].pk)
        )
        assert r.status_code == 400

    def test_quien_no_puede_registrar(self, datos):
        for usuario in ("cajero", "almacenero", "vendedor"):
            assert registrar(usuario, cuerpo(datos)).status_code == 403, usuario
        assert registrar("vendedor_a2", cuerpo(datos)).status_code == 403
        assert MovimientoCaja.objects.sin_ambito().count() == 0


class TestConsulta:
    def _crear(self, datos, **extra):
        r = registrar("contador", cuerpo(datos, **extra))
        assert r.status_code == 201, r.content
        return r.json()

    def test_listado_filtros_y_saldo_corrido(self, datos):
        hoy = timezone.localdate()
        self._crear(datos, monto="500.00", fecha=(hoy - timedelta(days=2)).isoformat())
        egreso = datos.conceptos["GASTOS_VARIOS"].pk
        self._crear(datos, tipo="EGRESO", concepto=egreso, monto="120.50", glosa="Útiles")
        self._crear(datos, cuenta=datos.banco.pk, monto="1000.00", glosa="Depósito inicial")
        api = cliente_de("contador")
        base = {"empresa": datos.mundo.e1.pk}
        assert api.get(f"{BASE}/movimientos/", base).json()["count"] == 3
        solo_caja = api.get(f"{BASE}/movimientos/", {**base, "cuenta": datos.caja.pk}).json()
        assert [(m["numero"], m["saldo_despues"]) for m in solo_caja["results"]] == [
            (2, "379.50"),
            (1, "500.00"),
        ]
        assert api.get(f"{BASE}/movimientos/", {**base, "tipo": "EGRESO"}).json()["count"] == 1
        assert api.get(f"{BASE}/movimientos/", {**base, "q": "útiles"}).json()["count"] == 1
        assert api.get(f"{BASE}/movimientos/", {**base, "q": "2"}).json()["count"] >= 1
        assert (
            api.get(f"{BASE}/movimientos/", {**base, "origen": "automatico"}).json()["count"] == 0
        )
        assert (
            api.get(f"{BASE}/movimientos/", {**base, "desde": hoy.isoformat()}).json()["count"] == 2
        )

    def test_el_saldo_corrido_no_cuenta_las_anuladas(self, datos):
        uno = self._crear(datos, monto="100.00")
        self._crear(datos, monto="50.00")
        cliente_de("admin").post(
            f"{BASE}/movimientos/{uno['id']}/anular/", {"motivo": "Error"}, format="json"
        )
        filas = (
            cliente_de("contador")
            .get(f"{BASE}/movimientos/", {"empresa": datos.mundo.e1.pk, "cuenta": datos.caja.pk})
            .json()["results"]
        )
        assert [(m["numero"], m["saldo_despues"], m["estado"]) for m in filas] == [
            (2, "50.00", "EMITIDO"),
            (1, None, "ANULADO"),
        ]

    def test_detalle_empresa_obligatoria_y_permisos(self, datos):
        creado = self._crear(datos)
        assert cliente_de("contador").get(f"{BASE}/movimientos/{creado['id']}/").status_code == 200
        assert cliente_de("contador").get(f"{BASE}/movimientos/").status_code == 400
        assert (
            cliente_de("vendedor")
            .get(f"{BASE}/movimientos/", {"empresa": datos.mundo.e1.pk})
            .status_code
            == 403
        )
        assert cliente_de("vendedor_a2").get(f"{BASE}/movimientos/{creado['id']}/").status_code in (
            403,
            404,
        )
        assert cliente_de("otra_org").get(f"{BASE}/movimientos/{creado['id']}/").status_code in (
            403,
            404,
        )


class TestSaldos:
    def test_saldo_de_cada_caja_y_total_por_moneda(self, datos):
        registrar("contador", cuerpo(datos, monto="500.00"))
        registrar("contador", cuerpo(datos, cuenta=datos.banco.pk, monto="1000.00"))
        egreso = datos.conceptos["GASTOS_VARIOS"].pk
        registrar("contador", cuerpo(datos, tipo="EGRESO", concepto=egreso, monto="100.00"))
        r = cliente_de("contador").get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 200, r.content
        d = r.json()
        por_nombre = {c["nombre"]: c for c in d["cuentas"]}
        assert (por_nombre["Caja soles"]["saldo"], por_nombre["Caja soles"]["egresos"]) == (
            "400.00",
            "100.00",
        )
        assert por_nombre["BCP soles"]["saldo"] == "1000.00"
        assert d["totales"] == [{"moneda": "PEN", "saldo": "1400.00"}]

    def test_permisos(self, datos):
        assert (
            cliente_de("cajero").get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk}).status_code
            == 200
        )
        assert (
            cliente_de("vendedor")
            .get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk})
            .status_code
            == 403
        )
        assert cliente_de("contador").get(f"{BASE}/saldos/").status_code == 400


class TestAnular:
    def test_solo_el_administrador_anula(self, datos):
        creado = registrar("contador", cuerpo(datos)).json()
        url = f"{BASE}/movimientos/{creado['id']}/anular/"
        assert (
            cliente_de("contador").post(url, {"motivo": "Error"}, format="json").status_code == 403
        )
        r = cliente_de("admin").post(url, {"motivo": "Se registró por error"}, format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["estado"], r.json()["motivo_anulacion"]) == (
            "ANULADO",
            "Se registró por error",
        )
        assert (
            cliente_de("admin").post(url, {"motivo": "Otra vez"}, format="json").status_code == 409
        )
        assert cliente_de("admin").post(url, {}, format="json").status_code == 400


class TestTransferencias:
    def _mover(self, datos, usuario="contador", llave=None, **extra):
        cuerpo_transferencia = {
            "empresa": datos.mundo.e1.pk,
            "cuenta_origen": datos.caja.pk,
            "cuenta_destino": datos.banco.pk,
            "monto": "300.00",
            **extra,
        }
        return cliente_de(usuario).post(
            f"{BASE}/transferencias/",
            cuerpo_transferencia,
            format="json",
            HTTP_IDEMPOTENCY_KEY=llave or clave(),
        )

    def test_el_contador_deposita_al_banco(self, datos):
        r = self._mover(datos, referencia="OP-77", comision="2.00")
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["clase"], d["clase_nombre"], d["numero"], d["estado"]) == (
            "DEPOSITO",
            "Depósito",
            1,
            "EMITIDO",
        )
        assert (d["origen_nombre"], d["destino_nombre"], d["monto_destino"], d["comision"]) == (
            "Caja soles", "BCP soles", "300.00", "2.00",
        )  # fmt: skip
        assert d["entre_empresas"] is False
        saldos = {
            c["nombre"]: c["saldo"]
            for c in cliente_de("contador")
            .get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk})
            .json()["cuentas"]
        }
        assert saldos == {"Caja soles": "-302.00", "BCP soles": "300.00"}

    def test_reintento_no_transfiere_dos_veces(self, datos):
        llave = clave()
        primera, segunda = self._mover(datos, llave=llave), self._mover(datos, llave=llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda.json() == primera.json()
        assert MovimientoCaja.objects.sin_ambito().count() == 2

    def test_errores_de_negocio(self, datos):
        assert self._mover(datos, cuenta_destino=datos.caja.pk).status_code == 400
        assert self._mover(datos, monto="0").status_code == 400
        assert self._mover(datos, cuenta_destino=999_999).status_code == 400
        assert self._mover(datos, cuenta_origen=999_999).status_code == 400
        assert self._mover(datos, tipo_cambio="3.75").status_code == 400  # misma moneda
        assert MovimientoCaja.objects.sin_ambito().count() == 0

    def test_sin_clave_de_idempotencia(self, datos):
        r = cliente_de("contador").post(
            f"{BASE}/transferencias/",
            {
                "empresa": datos.mundo.e1.pk,
                "cuenta_origen": datos.caja.pk,
                "cuenta_destino": datos.banco.pk,
                "monto": "5",
            },
            format="json",
        )
        assert r.status_code == 400

    def test_quien_no_puede_transferir(self, datos):
        for usuario in ("cajero", "almacenero", "vendedor"):
            assert self._mover(datos, usuario=usuario).status_code == 403, usuario

    def test_entre_empresas_pide_permiso_especial(self, datos):
        e = datos.mundo.e
        destino = CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.emp_a2, nombre="Caja A2", tipo="CAJA", moneda="PEN"
        )
        # El contador tiene acceso solo a la empresa A1: no puede ni ver la cuenta de A2.
        assert self._mover(datos, cuenta_destino=destino.pk).status_code in (400, 403)
        r = self._mover(datos, usuario="super", cuenta_destino=destino.pk)
        assert r.status_code == 201, r.content
        assert r.json()["entre_empresas"] is True
        assert r.json()["empresa_destino"] == e.emp_a2.pk

    def test_listado_filtros_y_detalle(self, datos):
        uno = self._mover(datos, glosa="Cierre del lunes").json()
        self._mover(
            datos, cuenta_origen=datos.banco.pk, cuenta_destino=datos.caja.pk, monto="50.00"
        )
        api = cliente_de("contador")
        base = {"empresa": datos.mundo.e1.pk}
        assert api.get(f"{BASE}/transferencias/", base).json()["count"] == 2
        assert api.get(f"{BASE}/transferencias/", {**base, "clase": "RETIRO"}).json()["count"] == 1
        assert api.get(f"{BASE}/transferencias/", {**base, "q": "lunes"}).json()["count"] == 1
        assert (
            api.get(f"{BASE}/transferencias/", {**base, "cuenta": datos.banco.pk}).json()["count"]
            == 2
        )
        assert api.get(f"{BASE}/transferencias/{uno['id']}/").status_code == 200
        assert api.get(f"{BASE}/transferencias/").status_code == 400
        assert cliente_de("vendedor").get(f"{BASE}/transferencias/", base).status_code == 403
        assert cliente_de("otra_org").get(f"{BASE}/transferencias/{uno['id']}/").status_code in (
            403,
            404,
        )

    def test_solo_el_administrador_anula(self, datos):
        t = self._mover(datos, comision="1.00").json()
        url = f"{BASE}/transferencias/{t['id']}/anular/"
        assert (
            cliente_de("contador").post(url, {"motivo": "Error"}, format="json").status_code == 403
        )
        r = cliente_de("admin").post(url, {"motivo": "Cuenta equivocada"}, format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["estado"], r.json()["motivo_anulacion"]) == (
            "ANULADO",
            "Cuenta equivocada",
        )
        assert (
            cliente_de("admin").post(url, {"motivo": "Otra vez"}, format="json").status_code == 409
        )
        assert cliente_de("admin").post(url, {}, format="json").status_code == 400
        saldos = {
            c["nombre"]: c["saldo"]
            for c in cliente_de("contador")
            .get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk})
            .json()["cuentas"]
        }
        assert saldos == {"Caja soles": "0.00", "BCP soles": "0.00"}
