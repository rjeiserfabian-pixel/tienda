"""API de anticipos a proveedores: permisos, idempotencia, orden, devolución, anulación y saldos."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

import pytest
from django.utils import timezone

from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)
from .test_api import clave, datos  # noqa: F401
from .test_api_ordenes import accion as accion_orden
from .test_api_ordenes import nueva as nueva_orden

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras"
HOY = timezone.localdate().isoformat()


@pytest.fixture
def fondos(datos):
    """La caja de la prueba arranca con 1 000."""
    datos.caja.saldo_inicial = 1000
    datos.caja.save()
    return datos


def cuerpo(datos, **extra):
    base = {
        "empresa": datos.mundo.e1.pk,
        "proveedor": datos.proveedor.pk,
        "monto": "300.00",
        "cuenta": datos.caja.pk,
        "fecha": HOY,
        "referencia": "OP-77",
    }
    return {**base, **extra}


def crear(datos, usuario="admin", llave=None, **extra):
    return cliente_de(usuario).post(
        f"{BASE}/anticipos/",
        cuerpo(datos, **extra),
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


def nuevo(datos, usuario="admin", **extra):
    r = crear(datos, usuario, **extra)
    assert r.status_code == 201, r.content
    return r.json()


class TestPermisos:
    def test_el_contador_adelanta_pero_el_almacenero_y_el_vendedor_no(self, fondos):
        assert crear(fondos, "contador").status_code == 201
        assert crear(fondos, "almacenero", monto="10.00").status_code == 403
        assert crear(fondos, "vendedor", monto="10.00").status_code == 403

    def test_el_almacenero_lo_ve_pero_no_lo_anula(self, fondos):
        a = nuevo(fondos)
        api = cliente_de("almacenero")
        assert api.get(f"{BASE}/anticipos/{a['id']}/").status_code == 200
        r = api.post(f"{BASE}/anticipos/{a['id']}/anular/", {"motivo": "Error"}, format="json")
        assert r.status_code == 403

    def test_otra_organizacion_no_lo_ve(self, fondos):
        a = nuevo(fondos)
        assert cliente_de("otra_org").get(f"{BASE}/anticipos/{a['id']}/").status_code in (403, 404)


class TestFlujo:
    def test_crea_y_deja_saldo_a_favor(self, fondos):
        a = nuevo(fondos)
        assert (a["codigo"], a["estado"], a["monto"], a["disponible"], a["devuelto"]) == (
            "ANT-000001",
            "EMITIDO",
            "300.00",
            "300.00",
            "0.00",
        )
        creditos = cliente_de("admin").get(f"{BASE}/creditos/", {"empresa": fondos.mundo.e1.pk})
        fila = creditos.json()["results"][0]
        assert (fila["origen"], fila["anticipo_codigo"], fila["disponible"]) == (
            "ANTICIPO",
            "ANT-000001",
            "300.00",
        )
        assert fila["devolucion"] is None

    def test_reintento_con_la_misma_clave_no_duplica(self, fondos):
        llave = clave()
        a, b = crear(fondos, llave=llave), crear(fondos, llave=llave)
        assert (a.status_code, b.status_code) == (201, 201)
        assert b.json() == a.json() and b["Idempotency-Replayed"] == "true"
        lista = cliente_de("admin").get(f"{BASE}/anticipos/", {"empresa": fondos.mundo.e1.pk})
        assert len(lista.json()["results"]) == 1

    def test_devolver_baja_el_saldo_y_anular_pide_saldo_intacto(self, fondos):
        a = nuevo(fondos)
        api = cliente_de("admin")
        r = api.post(
            f"{BASE}/anticipos/{a['id']}/devolver/",
            {"monto": "100.00", "cuenta": fondos.caja.pk},
            format="json",
            HTTP_IDEMPOTENCY_KEY=clave(),
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["devuelto"], d["disponible"], d["aplicado"]) == ("100.00", "200.00", "0.00")
        r = api.post(f"{BASE}/anticipos/{a['id']}/anular/", {"motivo": "Error"}, format="json")
        assert r.status_code == 400

    def test_se_anula_con_motivo_si_esta_intacto(self, fondos):
        a = nuevo(fondos)
        api = cliente_de("admin")
        assert (
            api.post(
                f"{BASE}/anticipos/{a['id']}/anular/", {"motivo": ""}, format="json"
            ).status_code
            == 400
        )
        r = api.post(
            f"{BASE}/anticipos/{a['id']}/anular/", {"motivo": "Proveedor equivocado"}, format="json"
        )
        assert r.status_code == 200 and r.json()["estado"] == "ANULADO"

    def test_validaciones_dan_400(self, fondos):
        assert crear(fondos, monto="0").status_code == 400
        assert crear(fondos, cuenta=99999999).status_code == 400
        assert crear(fondos, proveedor=99999999).status_code == 400

    def test_filtros_del_listado(self, fondos):
        nuevo(fondos)
        api = cliente_de("admin")
        base = {"empresa": fondos.mundo.e1.pk}
        assert (
            len(api.get(f"{BASE}/anticipos/", {**base, "q": "ANT-000001"}).json()["results"]) == 1
        )
        assert api.get(f"{BASE}/anticipos/", {**base, "estado": "ANULADO"}).json()["results"] == []
        assert (
            len(
                api.get(f"{BASE}/anticipos/", {**base, "proveedor": fondos.proveedor.pk}).json()[
                    "results"
                ]
            )
            == 1
        )


class TestOrden:
    def test_la_orden_muestra_sus_anticipos(self, fondos):
        orden = nueva_orden(fondos, "admin")
        assert accion_orden("admin", orden["id"], "emitir").status_code == 200
        a = nuevo(fondos, orden=orden["id"], monto="50.00")
        assert a["orden_codigo"] == orden["codigo"]
        detalle = cliente_de("admin").get(f"{BASE}/ordenes/{orden['id']}/").json()
        assert [(x["codigo"], x["monto"], x["estado"]) for x in detalle["anticipos"]] == [
            ("ANT-000001", "50.00", "EMITIDO")
        ]

    def test_una_orden_en_borrador_no_admite_anticipo(self, fondos):
        orden = nueva_orden(fondos, "admin")
        assert crear(fondos, orden=orden["id"], monto="50.00").status_code == 400

    def test_no_pasa_del_total_de_la_orden(self, fondos):
        orden = nueva_orden(fondos, "admin")  # total 118
        accion_orden("admin", orden["id"], "emitir")
        assert crear(fondos, orden=orden["id"], monto="200.00").status_code == 400
