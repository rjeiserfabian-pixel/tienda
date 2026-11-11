"""API de devoluciones y del saldo a favor: permisos, idempotencia, errores y aislamiento."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.compras.models import Compra, CreditoProveedor, DevolucionCompra
from apps.core.tenant import establecer_contexto
from apps.inventario.models import (
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import Producto
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)
from .test_api import clave, cuerpo, datos, registrar  # noqa: F401

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras"
_notas = itertools.count(1)


def comprar(datos, **extra):
    """Compra de 10 unidades a 10 + IGV (118,00), registrada por la API."""
    r = registrar(cliente_de("almacenero"), cuerpo(datos, **extra))
    assert r.status_code == 201, r.content
    return r.json()


def a_credito(datos):
    return comprar(
        datos,
        forma_pago="CREDITO",
        pagos=[],
        cuotas={
            "cantidad": 2,
            "primera_fecha": timezone.localdate().isoformat(),
            "periodicidad": datos.mensual.pk,
        },
    )


def cuerpo_devolucion(datos, origen, cantidad="4", **extra):
    base = {
        "empresa": datos.mundo.e1.pk,
        "compra": origen["id"],
        "comprobante_serie": "FC01",
        "comprobante_numero": str(next(_notas)),
        "fecha_emision": timezone.localdate().isoformat(),
        "razon": "Mercadería dañada",
        "lineas": [{"linea": origen["lineas"][0]["id"], "cantidad": cantidad}],
    }
    return {**base, **extra}


def devolver(api, cuerpo_, llave=None):
    return api.post(
        f"{BASE}/devoluciones/", cuerpo_, format="json", HTTP_IDEMPOTENCY_KEY=llave or clave()
    )


def reembolso(datos, monto):
    return {"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": monto}


class TestRegistrar:
    def test_devuelve_y_responde_el_detalle(self, datos):
        compra = comprar(datos)
        c = cuerpo_devolucion(datos, compra, reembolsos=[reembolso(datos, "47.20")])
        r = devolver(cliente_de("admin"), c)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["estado"], d["motivo"], d["total"]) == (
            1,
            "EMITIDO",
            "POR_ITEM",
            "47.20",
        )
        assert (d["op_gravada"], d["igv"], d["costo_soles"]) == ("40.00", "7.20", "40.00")
        assert (d["aplicado_a_deuda"], d["reembolsado"], d["saldo_a_favor"]) == (
            "0.00",
            "47.20",
            "0.00",
        )
        assert d["comprobante"] == "FC01-" + c["comprobante_numero"]
        assert d["reembolsos"][0]["cuenta_nombre"] == "Caja soles"
        assert d["lineas"][0]["cantidad"] == "4.000"
        assert d["credito"] is None
        assert SaldoStock.objects.sin_ambito().get().cantidad == 6

    def test_sin_reembolso_queda_saldo_a_favor(self, datos):
        compra = comprar(datos)
        d = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra)).json()
        assert (d["reembolsado"], d["saldo_a_favor"]) == ("0.00", "47.20")
        assert d["credito"]["disponible"] == "47.20"

    def test_compra_a_credito_baja_la_deuda(self, datos):
        compra = a_credito(datos)
        d = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra)).json()
        assert (d["aplicado_a_deuda"], d["saldo_a_favor"]) == ("47.20", "0.00")
        assert d["aplicaciones"][0]["cuota_numero"] == 1
        detalle = cliente_de("admin").get(f"{BASE}/{compra['id']}/").json()
        assert [q["monto"] for q in detalle["cuotas"]] == ["11.80", "59.00"]

    def test_reintento_con_la_misma_clave_no_duplica(self, datos):
        compra = comprar(datos)
        api, llave = cliente_de("admin"), clave()
        c = cuerpo_devolucion(datos, compra)
        primera = devolver(api, c, llave)
        segunda = devolver(api, c, llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda.json() == primera.json()
        assert segunda["Idempotency-Replayed"] == "true"
        assert DevolucionCompra.objects.sin_ambito().count() == 1
        assert SaldoStock.objects.sin_ambito().get().cantidad == 6

    def test_sin_clave_no_registra(self, datos):
        compra = comprar(datos)
        r = cliente_de("admin").post(
            f"{BASE}/devoluciones/", cuerpo_devolucion(datos, compra), format="json"
        )
        assert r.status_code == 400
        assert DevolucionCompra.objects.sin_ambito().count() == 0

    def test_errores_de_negocio(self, datos):
        compra = comprar(datos)
        api = cliente_de("admin")
        r = devolver(api, cuerpo_devolucion(datos, compra, cantidad="11"))
        assert r.status_code == 400 and "Solo se puede devolver 10" in r.content.decode()
        r = devolver(api, cuerpo_devolucion(datos, compra, reembolsos=[reembolso(datos, "99")]))
        assert r.status_code == 400 and "no puede pasar de" in r.content.decode()
        r = devolver(api, cuerpo_devolucion(datos, compra, razon=" "))
        assert r.status_code == 400
        assert DevolucionCompra.objects.sin_ambito().count() == 0
        assert MovimientoInventario.objects.sin_ambito().count() == 1  # solo la entrada

    def test_nota_repetida_responde_conflicto(self, datos):
        compra = comprar(datos)
        api = cliente_de("admin")
        c = cuerpo_devolucion(datos, compra, cantidad="1", comprobante_numero="777")
        assert devolver(api, c).status_code == 201
        assert devolver(api, c).status_code == 409
        assert DevolucionCompra.objects.sin_ambito().count() == 1

    def test_stock_insuficiente_responde_conflicto(self, datos):
        compra = comprar(datos)
        # Se vende casi todo: ya no queda lo que se quiere devolver.
        e = datos.mundo.e
        establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
        registrar_movimiento(
            empresa=datos.mundo.e1,
            almacen=datos.mundo.alm[1],
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.VENTA,
            fecha=timezone.localdate(),
            lineas=[
                LineaNueva(Producto.objects.get(pk=compra["lineas"][0]["producto"]), Decimal(9))
            ],
        )
        r = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra))
        assert r.status_code == 409

    def test_referencias_inexistentes_son_400(self, datos):
        compra = comprar(datos)
        api = cliente_de("admin")
        for campo, valor in [("compra", 999_999), ("empresa", 999_999)]:
            r = devolver(api, cuerpo_devolucion(datos, compra, **{campo: valor}))
            assert r.status_code in (400, 403), campo
        r = devolver(
            api, cuerpo_devolucion(datos, compra, lineas=[{"linea": 999_999, "cantidad": "1"}])
        )
        assert r.status_code == 400
        malo = cuerpo_devolucion(
            datos, compra, reembolsos=[{**reembolso(datos, "10"), "cuenta": 999_999}]
        )
        assert devolver(api, malo).status_code == 400

    def test_cuerpo_incompleto(self, datos):
        r = devolver(cliente_de("admin"), {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 400

    def test_quien_tiene_el_permiso(self, datos):
        compra = comprar(datos)
        for usuario, esperado in (("almacenero", 403), ("vendedor", 403), ("contador", 201)):
            r = devolver(
                cliente_de(usuario),
                cuerpo_devolucion(datos, compra, cantidad="1"),
            )
            assert r.status_code == esperado, usuario

    def test_otra_empresa_u_organizacion_no_devuelve(self, datos):
        compra = comprar(datos)
        c = cuerpo_devolucion(datos, compra)
        assert devolver(cliente_de("vendedor_a2"), c).status_code == 403
        assert devolver(cliente_de("otra_org"), c).status_code in (400, 403)
        assert DevolucionCompra.objects.sin_ambito().count() == 0

    def test_la_compra_debe_ser_de_la_empresa_declarada(self, datos):
        compra = comprar(datos)
        c = cuerpo_devolucion(datos, compra, empresa=datos.mundo.e2.pk)
        r = devolver(cliente_de("super"), c)
        assert r.status_code == 400


class TestConsultar:
    def test_listado_filtros_y_detalle(self, datos):
        c1, c2 = comprar(datos), comprar(datos)
        api = cliente_de("admin")
        d1 = devolver(api, cuerpo_devolucion(datos, c1, cantidad="1")).json()
        devolver(api, cuerpo_devolucion(datos, c2, cantidad="2"))
        lista = api.get(f"{BASE}/devoluciones/?empresa={datos.mundo.e1.pk}").json()
        assert lista["count"] == 2
        assert lista["results"][0]["compra_numero"] == c2["numero"]
        filtrada = api.get(
            f"{BASE}/devoluciones/?empresa={datos.mundo.e1.pk}&compra={c1['id']}"
        ).json()
        assert [x["id"] for x in filtrada["results"]] == [d1["id"]]
        ninguna = api.get(f"{BASE}/devoluciones/?empresa={datos.mundo.e1.pk}&estado=ANULADO").json()
        assert ninguna["count"] == 0
        por_texto = api.get(f"{BASE}/devoluciones/?empresa={datos.mundo.e1.pk}&q=dañada").json()
        assert por_texto["count"] == 2
        detalle = api.get(f"{BASE}/devoluciones/{d1['id']}/").json()
        assert detalle["id"] == d1["id"] and len(detalle["lineas"]) == 1

    def test_el_listado_pide_empresa(self, datos):
        assert cliente_de("admin").get(f"{BASE}/devoluciones/").status_code == 400

    def test_aislamiento(self, datos):
        compra = comprar(datos)
        d = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra)).json()
        assert cliente_de("vendedor_a2").get(f"{BASE}/devoluciones/{d['id']}/").status_code in (
            403,
            404,
        )
        assert cliente_de("otra_org").get(f"{BASE}/devoluciones/{d['id']}/").status_code in (
            403,
            404,
        )
        r = cliente_de("vendedor_a2").get(f"{BASE}/devoluciones/?empresa={datos.mundo.e1.pk}")
        assert r.status_code == 403

    def test_por_devolver(self, datos):
        compra = a_credito(datos)
        api = cliente_de("admin")
        d = api.get(f"{BASE}/{compra['id']}/por-devolver/").json()
        assert (d["forma_pago"], d["deuda_pendiente"]) == ("CREDITO", "118.00")
        assert d["lineas"][0]["pendiente"] == "10.000"
        devolver(api, cuerpo_devolucion(datos, compra, cantidad="4"))
        d = api.get(f"{BASE}/{compra['id']}/por-devolver/").json()
        assert (d["lineas"][0]["devuelto"], d["lineas"][0]["pendiente"]) == ("4.000", "6.000")
        assert d["deuda_pendiente"] == "70.80"
        assert (
            cliente_de("almacenero").get(f"{BASE}/{compra['id']}/por-devolver/").status_code == 403
        )


class TestAnular:
    def test_anula_y_deshace(self, datos):
        compra = comprar(datos)
        api = cliente_de("admin")
        d = devolver(
            api, cuerpo_devolucion(datos, compra, reembolsos=[reembolso(datos, "20")])
        ).json()
        r = api.post(f"{BASE}/devoluciones/{d['id']}/anular/", {"motivo": "Error"}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "ANULADO"
        assert r.json()["reembolsos"][0]["anulado"] is True
        assert SaldoStock.objects.sin_ambito().get().cantidad == 10
        assert CreditoProveedor.objects.sin_ambito().get().anulado is True

    def test_motivo_obligatorio_y_una_sola_vez(self, datos):
        compra = comprar(datos)
        api = cliente_de("admin")
        d = devolver(api, cuerpo_devolucion(datos, compra)).json()
        assert (
            api.post(f"{BASE}/devoluciones/{d['id']}/anular/", {}, format="json").status_code == 400
        )
        assert (
            api.post(
                f"{BASE}/devoluciones/{d['id']}/anular/", {"motivo": "x"}, format="json"
            ).status_code
            == 200
        )
        assert (
            api.post(
                f"{BASE}/devoluciones/{d['id']}/anular/", {"motivo": "x"}, format="json"
            ).status_code
            == 409
        )

    def test_solo_con_el_permiso(self, datos):
        compra = comprar(datos)
        d = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra)).json()
        for usuario in ("contador", "almacenero", "vendedor"):
            r = cliente_de(usuario).post(
                f"{BASE}/devoluciones/{d['id']}/anular/", {"motivo": "x"}, format="json"
            )
            assert r.status_code == 403, usuario
        assert DevolucionCompra.objects.sin_ambito().get().estado == "EMITIDO"

    def test_la_compra_con_devolucion_no_se_anula(self, datos):
        compra = comprar(datos)
        devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra))
        r = cliente_de("admin").post(
            f"{BASE}/{compra['id']}/anular/", {"motivo": "x"}, format="json"
        )
        assert r.status_code == 409
        assert Compra.objects.sin_ambito().get().estado == "EMITIDO"


def aplicar(api, credito_id, cuerpo_, llave=None):
    return api.post(
        f"{BASE}/creditos/{credito_id}/aplicar/",
        cuerpo_,
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


@pytest.fixture
def con_saldo(datos):
    compra = comprar(datos)
    d = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra)).json()
    return d["credito"]["id"]


class TestSaldoAFavor:
    def test_listado(self, datos, con_saldo):
        api = cliente_de("contador")
        lista = api.get(f"{BASE}/creditos/?empresa={datos.mundo.e1.pk}").json()
        assert lista["count"] == 1
        c = lista["results"][0]
        assert (c["monto"], c["disponible"], c["moneda"], c["proveedor_nombre"]) == (
            "47.20",
            "47.20",
            "PEN",
            "Distribuidora Selva",
        )
        solo = api.get(f"{BASE}/creditos/?empresa={datos.mundo.e1.pk}&disponibles=1").json()
        assert solo["count"] == 1
        otro = api.get(f"{BASE}/creditos/?empresa={datos.mundo.e1.pk}&moneda=USD").json()
        assert otro["count"] == 0
        assert api.get(f"{BASE}/creditos/{con_saldo}/").status_code == 200

    def test_aplicar_y_reintento(self, datos, con_saldo):
        destino = a_credito(datos)
        api, llave = cliente_de("contador"), clave()
        c = {"compra": destino["id"], "monto": "30.00"}
        primera = aplicar(api, con_saldo, c, llave)
        segunda = aplicar(api, con_saldo, c, llave)
        assert (primera.status_code, segunda.status_code) == (201, 201), primera.content
        assert segunda["Idempotency-Replayed"] == "true"
        assert primera.json()["usado"] == "30.00" and primera.json()["disponible"] == "17.20"
        assert primera.json()["aplicaciones"][0]["cuotas"][0]["monto"] == "30.00"
        detalle = api.get(f"{BASE}/{destino['id']}/").json()
        assert [q["pagado"] for q in detalle["cuotas"]] == ["30.00", "0.00"]

    def test_errores(self, datos, con_saldo):
        destino = a_credito(datos)
        api = cliente_de("contador")
        r = aplicar(api, con_saldo, {"compra": destino["id"], "monto": "99.00"})
        assert r.status_code == 400 and "disponible 47.20" in r.content.decode()
        assert aplicar(api, con_saldo, {"compra": 999_999, "monto": "1"}).status_code == 400
        assert aplicar(api, con_saldo, {"compra": destino["id"], "monto": "0"}).status_code == 400
        al_contado = comprar(datos)
        assert (
            aplicar(api, con_saldo, {"compra": al_contado["id"], "monto": "1"}).status_code == 400
        )
        futura = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = aplicar(api, con_saldo, {"compra": destino["id"], "monto": "1", "fecha": futura})
        assert r.status_code == 400

    def test_permisos(self, datos, con_saldo):
        destino = a_credito(datos)
        c = {"compra": destino["id"], "monto": "10.00"}
        for usuario in ("almacenero", "vendedor", "vendedor_a2"):
            assert aplicar(cliente_de(usuario), con_saldo, c).status_code in (403, 404), usuario
        assert cliente_de("vendedor_a2").get(f"{BASE}/creditos/{con_saldo}/").status_code in (
            403,
            404,
        )
        assert CreditoProveedor.objects.sin_ambito().get().usado == 0

    def test_deshacer(self, datos, con_saldo):
        destino = a_credito(datos)
        api = cliente_de("contador")
        lista = aplicar(api, con_saldo, {"compra": destino["id"], "monto": "30"}).json()
        aplicacion = lista["aplicaciones"][0]["id"]
        url = f"{BASE}/creditos/{con_saldo}/aplicaciones/{aplicacion}/deshacer/"
        assert api.post(url, {}, format="json").status_code == 400
        r = api.post(url, {"motivo": "Compra equivocada"}, format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["usado"], r.json()["disponible"]) == ("0.00", "47.20")
        assert api.post(url, {"motivo": "otra vez"}, format="json").status_code == 409
        assert cliente_de("almacenero").post(url, {"motivo": "x"}, format="json").status_code == 403
        inexistente = f"{BASE}/creditos/{con_saldo}/aplicaciones/999999/deshacer/"
        assert api.post(inexistente, {"motivo": "x"}, format="json").status_code == 404

    def test_la_devolucion_con_saldo_usado_no_se_anula(self, datos, con_saldo):
        destino = a_credito(datos)
        aplicar(cliente_de("contador"), con_saldo, {"compra": destino["id"], "monto": "10"})
        devolucion = DevolucionCompra.objects.sin_ambito().get()
        r = cliente_de("admin").post(
            f"{BASE}/devoluciones/{devolucion.pk}/anular/", {"motivo": "x"}, format="json"
        )
        assert r.status_code == 409


class TestCalcular:
    def test_vista_previa_igual_a_lo_que_se_registra(self, datos):
        compra = a_credito(datos)
        api = cliente_de("admin")
        cuerpo_ = {
            "empresa": datos.mundo.e1.pk,
            "compra": compra["id"],
            "lineas": [{"linea": compra["lineas"][0]["id"], "cantidad": "4"}],
        }
        r = api.post(f"{BASE}/devoluciones/calcular/", cuerpo_, format="json")
        assert r.status_code == 200, r.content
        p = r.json()
        assert (p["total"], p["igv"], p["op_gravada"], p["costo_soles"]) == (
            "47.20",
            "7.20",
            "40.00",
            "40.00",
        )
        assert (p["aplicado_a_deuda"], p["por_recuperar"], p["motivo"]) == (
            "47.20",
            "0.00",
            "POR_ITEM",
        )
        assert p["lineas"][0]["total"] == "47.20"
        assert DevolucionCompra.objects.sin_ambito().count() == 0
        real = devolver(api, cuerpo_devolucion(datos, compra)).json()
        assert (real["total"], real["aplicado_a_deuda"]) == (p["total"], p["aplicado_a_deuda"])

    def test_total_y_por_recuperar_en_compra_al_contado(self, datos):
        compra = comprar(datos)
        r = cliente_de("admin").post(
            f"{BASE}/devoluciones/calcular/",
            {
                "empresa": datos.mundo.e1.pk,
                "compra": compra["id"],
                "lineas": [{"linea": compra["lineas"][0]["id"], "cantidad": "10"}],
            },
            format="json",
        )
        p = r.json()
        assert (p["motivo"], p["total"], p["por_recuperar"]) == ("TOTAL", "118.00", "118.00")

    def test_errores_y_permisos(self, datos):
        compra = comprar(datos)
        linea = compra["lineas"][0]["id"]
        base = {"empresa": datos.mundo.e1.pk, "compra": compra["id"]}
        api = cliente_de("admin")
        malo = api.post(
            f"{BASE}/devoluciones/calcular/",
            {**base, "lineas": [{"linea": linea, "cantidad": "11"}]},
            format="json",
        )
        assert malo.status_code == 400
        sin_lineas = api.post(
            f"{BASE}/devoluciones/calcular/", {**base, "lineas": []}, format="json"
        )
        assert sin_lineas.status_code == 400
        for usuario in ("almacenero", "vendedor"):
            r = cliente_de(usuario).post(
                f"{BASE}/devoluciones/calcular/",
                {**base, "lineas": [{"linea": linea, "cantidad": "1"}]},
                format="json",
            )
            assert r.status_code == 403, usuario


def test_la_devolucion_a_proveedor_ya_no_se_registra_a_mano():
    from apps.inventario.api.v1.serializers import ORIGENES_MANUALES

    assert OrigenMovimiento.DEVOLUCION_PROVEEDOR not in ORIGENES_MANUALES
