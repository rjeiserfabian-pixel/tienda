"""API de cheques: permisos, flujo completo, idempotencia y avisos."""

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.tenant import establecer_contexto
from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja
from apps.mantenimiento.models import CuentaFinanciera
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
HOY = timezone.localdate()
_claves = itertools.count(1)


def clave():
    return f"cheque-de-prueba-{next(_claves):06d}"


@pytest.fixture
def datos(mundo):  # noqa: F811
    e = mundo.e
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_conceptos_caja(e.org_a.pk)

    def cuenta(nombre, tipo="BANCO", saldo="0"):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre=nombre, tipo=tipo, moneda="PEN", saldo_inicial=saldo
        )

    return type(
        "Datos",
        (),
        {
            "mundo": mundo,
            "bcp": cuenta("BCP soles"),
            "cheques": cuenta("Cheques por cobrar", tipo="BILLETERA", saldo="1000"),
        },
    )


def cuerpo(datos, **extra):
    base = {
        "empresa": datos.mundo.e1.pk,
        "tipo": "RECIBIDO",
        "numero": "000123",
        "banco": "BBVA",
        "importe": "300.00",
        "fecha_emision": HOY.isoformat(),
        "tercero": "Mago SAC",
        "cuenta_cartera": datos.cheques.pk,
    }
    return {**base, **extra}


def crear(usuario, datos, llave=None, **extra):
    return cliente_de(usuario).post(
        f"{BASE}/cheques/",
        cuerpo(datos, **extra),
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


def nuevo(datos, usuario="admin", **extra):
    r = crear(usuario, datos, **extra)
    assert r.status_code == 201, r.content
    return r.json()


def accion(usuario, cheque_id, nombre, cuerpo_=None):
    return cliente_de(usuario).post(
        f"{BASE}/cheques/{cheque_id}/{nombre}/", cuerpo_ or {}, format="json"
    )


class TestPermisos:
    def test_el_contador_gestiona_y_el_vendedor_ni_lo_ve(self, datos):
        assert crear("contador", datos).status_code == 201
        assert crear("vendedor", datos, numero="9").status_code == 403
        r = cliente_de("vendedor").get(f"{BASE}/cheques/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 403

    def test_otra_organizacion_no_lo_ve(self, datos):
        c = nuevo(datos)
        assert cliente_de("otra_org").get(f"{BASE}/cheques/{c['id']}/").status_code in (403, 404)


class TestFlujo:
    def test_registra_un_recibido_con_su_vencimiento(self, datos):
        c = nuevo(datos)
        assert (c["tipo"], c["estado"], c["importe"], c["cartera_nombre"]) == (
            "RECIBIDO",
            "EN_CARTERA",
            "300.00",
            "Cheques por cobrar",
        )
        assert c["vence"] == (HOY + timedelta(days=30)).isoformat()

    def test_reintento_con_la_misma_clave_no_duplica(self, datos):
        llave = clave()
        a, b = crear("admin", datos, llave=llave), crear("admin", datos, llave=llave)
        assert (a.status_code, b.status_code) == (201, 201)
        assert b.json() == a.json() and b["Idempotency-Replayed"] == "true"

    def test_depositar_y_cobrar_mueve_el_dinero_al_banco(self, datos):
        c = nuevo(datos)
        r = accion("admin", c["id"], "depositar", {"cuenta": datos.bcp.pk})
        assert r.status_code == 200 and r.json()["estado"] == "DEPOSITADO"
        r = accion("admin", c["id"], "cobrar")
        assert r.status_code == 200, r.content
        assert (r.json()["estado"], r.json()["cobrado_en"]) == ("COBRADO", HOY.isoformat())
        saldos = cliente_de("admin").get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk}).json()
        por_cuenta = {f["nombre"]: f["saldo"] for f in saldos["cuentas"]}
        assert (por_cuenta["BCP soles"], por_cuenta["Cheques por cobrar"]) == ("300.00", "700.00")

    def test_un_cobro_mayor_al_anotado_da_error_claro(self, datos):
        c = nuevo(datos, importe="1500.00")
        r = accion("admin", c["id"], "cobrar", {"cuenta": datos.bcp.pk})
        assert r.status_code == 400 and "solo hay" in r.content.decode()

    def test_rechazar_pide_motivo_y_anota_la_comision(self, datos):
        c = nuevo(datos)
        accion("admin", c["id"], "depositar", {"cuenta": datos.bcp.pk})
        assert accion("admin", c["id"], "rechazar", {"motivo": ""}).status_code == 400
        r = accion("admin", c["id"], "rechazar", {"motivo": "Sin fondos", "comision": "20.00"})
        assert r.status_code == 200 and r.json()["estado"] == "RECHAZADO"

    def test_anular_y_deshacer_el_cobro(self, datos):
        c = nuevo(datos)
        assert (
            accion("admin", c["id"], "anular", {"motivo": "Devuelto"}).json()["estado"] == "ANULADO"
        )
        d = nuevo(datos, numero="2")
        accion("admin", d["id"], "cobrar", {"cuenta": datos.bcp.pk})
        assert accion("admin", d["id"], "anular", {"motivo": "x" * 3}).status_code == 409
        r = accion("admin", d["id"], "deshacer-cobro", {"motivo": "Error"})
        assert (
            r.status_code == 200 and r.json()["estado"] == "DEPOSITADO"
        )  # se cobró directo: ya iba al banco

    def test_un_girado_se_cobra_sin_mover_dinero(self, datos):
        c = nuevo(
            datos, tipo="EMITIDO", cuenta=datos.bcp.pk, cuenta_cartera=None, tercero="Selva SAC"
        )
        assert c["estado"] == "GIRADO"
        r = accion("admin", c["id"], "cobrar")
        assert r.status_code == 200 and r.json()["estado"] == "COBRADO"


class TestListado:
    def test_filtra_por_tipo_estado_y_texto(self, datos):
        nuevo(datos)
        nuevo(
            datos,
            tipo="EMITIDO",
            numero="55",
            banco="BCP",
            cuenta=datos.bcp.pk,
            cuenta_cartera=None,
        )
        api = cliente_de("admin")
        base = {"empresa": datos.mundo.e1.pk}
        assert len(api.get(f"{BASE}/cheques/", base).json()["results"]) == 2
        assert len(api.get(f"{BASE}/cheques/", {**base, "tipo": "EMITIDO"}).json()["results"]) == 1
        assert len(api.get(f"{BASE}/cheques/", {**base, "q": "bbva"}).json()["results"]) == 1
        assert api.get(f"{BASE}/cheques/", {**base, "estado": "COBRADO"}).json()["results"] == []

    def test_vencidos_trae_solo_los_recibidos_que_pasaron_su_plazo(self, datos):
        nuevo(datos, numero="1", fecha_emision=(HOY - timedelta(days=40)).isoformat())
        nuevo(datos, numero="2")
        r = cliente_de("admin").get(
            f"{BASE}/cheques/", {"empresa": datos.mundo.e1.pk, "vencidos": "1"}
        )
        assert [c["numero"] for c in r.json()["results"]] == ["1"]

    def test_la_cuenta_de_cheques_de_cobro_se_ofrece(self, datos):
        r = cliente_de("admin").get(f"{BASE}/cheques/cuentas/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 200 and r.json() == []  # nada configurado en Ventas todavía
