"""API de ventas a crédito: configuración, vista previa, registro, cartera y abonos."""

import itertools
import json
from datetime import timedelta

import pytest

from apps.mantenimiento.models import Cliente
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas.models import AbonoVenta, Venta

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


def llave():
    return f"credito-de-prueba-{next(_claves):06d}"


def linea(tienda, producto, cantidad=1, empresa=None, **extra):
    empresa = empresa or tienda.a
    return {
        "producto": producto.pk,
        "cantidad": str(cantidad),
        "empresa": empresa.pk,
        "almacen": tienda.almacen(empresa).pk,
        **extra,
    }


def cuerpo(tienda, producto, cliente, **extra):
    base = {
        "empresa": tienda.a.pk,
        "tipo_comprobante": "NV",
        "forma_pago": "CREDITO",
        "cliente": cliente.pk,
        "lineas": [linea(tienda, producto)],
        "cuotas": {
            "cantidad": 3,
            "primera_fecha": str(tienda.entorno.hoy + timedelta(days=30)),
            "periodicidad": tienda.compras.mensual.pk,
        },
    }
    return {**base, **extra}


def vender(usuario, datos):
    return cliente_de(usuario).post(f"{BASE}/", datos, format="json", HTTP_IDEMPOTENCY_KEY=llave())


@pytest.fixture
def producto(tienda):
    return tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})


@pytest.fixture
def cliente(tienda):
    return tienda.cliente("1000")


class TestConfiguracionYVistaPrevia:
    def test_la_configuracion_trae_lo_necesario_para_vender_a_credito(self, tienda):
        c = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        assert c["permisos"]["credito"] is True and c["permisos"]["credito_exceder"] is False
        assert c["credito"]["cuotas_maximas"] == 60
        assert c["credito"]["lista"] == tienda.listas["CREDITO"].pk
        assert tienda.compras.mensual.pk in [p["id"] for p in c["credito"]["periodicidades"]]
        v = cliente_de("vendedor").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        assert v["permisos"]["credito"] is False

    def test_la_vista_previa_trae_el_cronograma_y_la_situacion_del_cliente(
        self, tienda, producto, cliente
    ):
        r = cliente_de("admin").post(
            f"{BASE}/previsualizar/",
            cuerpo(tienda, producto, cliente, inicial="41.60"),
            format="json",
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["forma_pago"] == "CREDITO" and d["total"] == "141.60" and d["avisos"] == []
        (c,) = d["comprobantes"]
        assert c["credito"] == "100.00"
        assert [q["monto"] for q in c["cuotas"]] == ["33.34", "33.33", "33.33"]
        assert d["cliente_credito"] == {
            "limite": "1000.00",
            "sin_limite": False,
            "deuda": "0.00",
            "disponible": "1000.00",
        }
        assert d["lista"] == tienda.listas["CREDITO"].pk
        assert not Venta.objects.sin_ambito().exists()

    def test_avisa_en_vez_de_fallar_lo_que_falta(self, tienda, producto, cliente):
        sin_cuotas = cuerpo(tienda, producto, cliente)
        sin_cuotas.pop("cuotas")
        d = cliente_de("admin").post(f"{BASE}/previsualizar/", sin_cuotas, format="json").json()
        assert any("cuotas" in a for a in d["avisos"])
        sin_credito = tienda.cliente("0", numero="20100000025")
        d = (
            cliente_de("admin")
            .post(f"{BASE}/previsualizar/", cuerpo(tienda, producto, sin_credito), format="json")
            .json()
        )
        assert any("no tiene crédito autorizado" in a for a in d["avisos"])

    def test_el_vendedor_sin_permiso_no_puede_ni_calcular_a_credito(
        self, tienda, producto, cliente
    ):
        r = cliente_de("vendedor").post(
            f"{BASE}/previsualizar/", cuerpo(tienda, producto, cliente), format="json"
        )
        assert r.status_code == 403


class TestRegistrar:
    def test_registra_la_venta_a_credito_con_sus_cuotas(self, tienda, producto, cliente):
        r = vender("admin", cuerpo(tienda, producto, cliente))
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["forma_pago"] == "CREDITO" and d["total"] == "141.60"
        (c,) = d["comprobantes"]
        assert [q["monto"] for q in c["cuotas"]] == ["47.20"] * 3
        assert c["saldo"] == "141.60" and c["cobros"] == [] and c["abonos"] == []

    def test_el_pago_inicial_va_como_cobro(self, tienda, producto, cliente):
        datos = cuerpo(
            tienda,
            producto,
            cliente,
            cobros=[{"medio_pago": tienda.efectivo.pk, "monto": "41.60"}],
        )
        d = vender("admin", datos).json()
        assert d["comprobantes"][0]["saldo"] == "100.00"
        assert d["comprobantes"][0]["cobros"][0]["monto"] == "41.60"

    def test_el_vendedor_sin_el_permiso_no_vende_a_credito(self, tienda, producto, cliente):
        assert vender("vendedor", cuerpo(tienda, producto, cliente)).status_code == 403
        assert not Venta.objects.sin_ambito().exists()

    def test_el_limite_se_respeta_y_el_administrador_no_lo_pasa_sin_permiso_especial(
        self, tienda, producto
    ):
        chico = tienda.cliente("100", numero="20100000033")
        r = vender("admin", cuerpo(tienda, producto, chico))
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "limite_de_credito_excedido"
        assert not Venta.objects.sin_ambito().exists()

    def test_la_situacion_de_un_cliente_sin_tope(self, tienda, producto):
        libre = tienda.cliente("0", numero="20100000052")
        libre.credito_sin_limite = True
        libre.save()
        assert vender("admin", cuerpo(tienda, producto, libre)).status_code == 201
        r = cliente_de("vendedor").get(
            f"{BASE}/clientes/{libre.pk}/credito/", {"empresa": tienda.a.pk}
        )
        assert r.json() == {
            "limite": None,
            "sin_limite": True,
            "deuda": "141.60",
            "disponible": None,
        }

    def test_la_situacion_del_cliente(self, tienda, producto, cliente):
        vender("admin", cuerpo(tienda, producto, cliente))
        r = cliente_de("vendedor").get(
            f"{BASE}/clientes/{cliente.pk}/credito/", {"empresa": tienda.a.pk}
        )
        assert r.json() == {
            "limite": "1000.00",
            "sin_limite": False,
            "deuda": "141.60",
            "disponible": "858.40",
        }

    def test_un_reintento_con_la_misma_clave_no_vende_dos_veces(self, tienda, producto, cliente):
        datos = cuerpo(tienda, producto, cliente)
        c = cliente_de("admin")
        for _ in range(2):
            r = c.post(f"{BASE}/", datos, format="json", HTTP_IDEMPOTENCY_KEY="clave-credito-001")
            assert r.status_code == 201
        assert Venta.objects.sin_ambito().count() == 1


class TestCartera:
    @pytest.fixture
    def venta(self, tienda, producto, cliente):
        return vender("admin", cuerpo(tienda, producto, cliente)).json()

    def test_resumen_y_clientes_con_deuda(self, tienda, venta):
        c = cliente_de("vendedor")
        resumen = c.get(f"{BASE}/por-cobrar/resumen/", {"empresa": tienda.a.pk}).json()
        assert resumen == [
            {
                "moneda": "PEN",
                "saldo": "141.60",
                "vencido": "0.00",
                "por_vencer_7_dias": "0.00",
                "comprobantes": 1,
                "clientes": 1,
            }
        ]
        filas = c.get(f"{BASE}/por-cobrar/clientes/", {"empresa": tienda.a.pk}).json()
        assert filas["count"] == 1
        fila = filas["results"][0]
        assert fila["cliente_nombre"] == "Ferretería El Sol" and fila["dias_atraso"] == 0
        assert fila["montos"][0]["saldo"] == "141.60"
        assert (
            c.get(f"{BASE}/por-cobrar/clientes/", {"empresa": tienda.a.pk, "q": "zzz"}).json()[
                "count"
            ]
            == 0
        )

    def test_vista_por_comprobante(self, tienda, venta):
        c = cliente_de("vendedor")
        r = c.get(f"{BASE}/por-cobrar/comprobantes/", {"empresa": tienda.a.pk})
        assert r.status_code == 200, r.content
        assert r.json()["count"] == 1
        fila = r.json()["results"][0]
        assert fila["saldo"] == "141.60" and len(fila["cuotas"]) == 3
        assert fila["cliente_nombre"] == "Ferretería El Sol" and fila["dias_atraso"] == 0
        for q, esperado in (("sol", 1), ("zzz", 0), (fila["numero_completo"][:4], 1)):
            r = c.get(f"{BASE}/por-cobrar/comprobantes/", {"empresa": tienda.a.pk, "q": q})
            assert r.json()["count"] == esperado, q
        vencidas = c.get(
            f"{BASE}/por-cobrar/comprobantes/", {"empresa": tienda.a.pk, "vencimiento": "vencidas"}
        )
        assert vencidas.json()["count"] == 0
        ajena = cliente_de("admin").get(
            f"{BASE}/por-cobrar/comprobantes/", {"empresa": tienda.b.pk}
        )
        assert ajena.json()["count"] == 0

    def test_otra_empresa_no_ve_la_deuda_ajena(self, tienda, venta):
        filas = cliente_de("admin").get(f"{BASE}/por-cobrar/clientes/", {"empresa": tienda.b.pk})
        assert filas.json()["count"] == 0

    def test_deuda_de_un_cliente_con_sus_cuotas(self, tienda, venta, cliente):
        d = (
            cliente_de("vendedor")
            .get(f"{BASE}/por-cobrar/clientes/{cliente.pk}/", {"empresa": tienda.a.pk})
            .json()
        )
        assert d["cliente"]["credito"]["deuda"] == "141.60"
        (c,) = d["comprobantes"]
        assert c["saldo"] == "141.60" and len(c["cuotas"]) == 3 and c["moneda"] == "PEN"
        assert c["cuotas"][0]["vencida"] is False

    def test_las_cuotas_vencidas_se_marcan_y_ordenan_primero(self, tienda, venta, cliente):
        from apps.ventas.models import CuotaVenta

        CuotaVenta.objects.sin_ambito().filter(numero=1).update(
            fecha_vencimiento=tienda.entorno.hoy - timedelta(days=5)
        )
        c = cliente_de("vendedor")
        fila = c.get(f"{BASE}/por-cobrar/clientes/", {"empresa": tienda.a.pk}).json()["results"][0]
        assert fila["dias_atraso"] == 5 and fila["montos"][0]["vencido"] == "47.20"
        solo_vencidas = c.get(
            f"{BASE}/por-cobrar/clientes/", {"empresa": tienda.a.pk, "vencimiento": "vencidas"}
        ).json()
        assert solo_vencidas["count"] == 1
        por_vencer = c.get(
            f"{BASE}/por-cobrar/clientes/", {"empresa": tienda.a.pk, "vencimiento": "por_vencer"}
        ).json()
        assert por_vencer["count"] == 0

    def abonar(self, usuario, comprobante_id, abonos, **extra):
        return cliente_de(usuario).post(
            f"{BASE}/comprobantes/{comprobante_id}/abonar/",
            {"abonos": abonos, **extra},
            format="json",
            HTTP_IDEMPOTENCY_KEY=llave(),
        )

    def test_el_cajero_cobra_y_el_comprobante_queda_con_su_abono(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        r = self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "60.00"}]
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["saldo"] == "81.60"
        assert d["abonos"][0]["monto"] == "60.00" and d["abonos"][0]["cuotas"] == [1, 2]
        assert [q["pagado"] for q in d["cuotas"]] == ["47.20", "12.80", "0.00"]

    def test_cada_cobro_entrega_un_recibo_con_la_serie_de_su_empresa(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        r = self.abonar(
            "cajero",
            comprobante["id"],
            [
                {"medio_pago": tienda.efectivo.pk, "monto": "30.00"},
                {"medio_pago": tienda.yape.pk, "monto": "10.00", "referencia": "OP-1"},
            ],
        )
        assert r.status_code == 201, r.content
        d = r.json()
        # Un solo recibo para el cobro, aunque se pague con dos métodos.
        assert len({a["recibo_numero"] for a in d["abonos"]}) == 1
        assert d["abonos"][0]["recibo_numero"] == "RI01-00000001"
        segundo = self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "5.00"}]
        ).json()
        assert segundo["abonos"][-1]["recibo_numero"] == "RI01-00000002"

    def test_el_recibo_trae_lo_que_se_imprime(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        r = self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "60.00"}]
        )
        recibo = r.json()["recibo"]
        d = cliente_de("cajero").get(f"{BASE}/recibos/{recibo}/").json()
        assert d["numero_completo"] == "RI01-00000001" and d["anulado"] is False
        assert d["emisor"]["ruc"] == tienda.a.ruc and d["total"] == "60.00"
        assert d["cliente"]["nombre"] and d["cajero"]
        assert [(c["numero"], c["aplicado"], c["pagada"]) for c in d["cuotas"]] == [
            (1, "47.20", True),
            (2, "12.80", False),
        ]
        assert d["saldo_credito"] == "81.60"
        # La columna de saldo del recibo es lo que queda del CRÉDITO tras cada cuota.
        assert [c["saldo_credito"] for c in d["cuotas"]] == ["94.40", "81.60"]
        assert d["pagos"] == [
            {"medio": "Efectivo", "monto": "60.00", "referencia": "", "anulado": False}
        ]

    def test_sin_serie_de_recibos_no_se_cobra(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante__codigo="RI"
        ).delete()
        comprobante = venta["comprobantes"][0]
        r = self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "10.00"}]
        )
        assert r.status_code == 400 and "serie de recibos de cobranza" in json.dumps(r.json())
        assert not AbonoVenta.objects.sin_ambito().exists()

    def test_la_otra_empresa_numera_con_su_propia_serie(self, tienda):
        pb = tienda.producto(
            "Mouse", costo="20", precios={"PUBLICO": "50", "CREDITO": "60"}, stock={tienda.b: 10}
        )
        cliente = tienda.cliente("2000")
        r = vender(
            "admin",
            cuerpo(
                tienda,
                pb,
                cliente,
                lineas=[linea(tienda, pb, empresa=tienda.b)],
            ),
        )
        assert r.status_code == 201, r.content
        comprobante = r.json()["comprobantes"][0]
        d = self.abonar(
            "admin", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "10.00"}]
        ).json()
        assert d["abonos"][0]["recibo_numero"] == "RI02-00000001"

    def test_el_vendedor_no_cobra_cuotas(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        r = self.abonar(
            "vendedor", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "10"}]
        )
        assert r.status_code == 403 and not AbonoVenta.objects.sin_ambito().exists()

    def test_no_se_cobra_mas_de_lo_que_se_debe(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        r = self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "500"}]
        )
        assert r.status_code == 400 and "más de lo que se debe" in r.json()["error"]["mensaje"]

    def test_un_abono_con_la_misma_clave_no_cobra_dos_veces(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        c = cliente_de("cajero")
        datos = {"abonos": [{"medio_pago": tienda.efectivo.pk, "monto": "20.00"}]}
        for _ in range(2):
            r = c.post(
                f"{BASE}/comprobantes/{comprobante['id']}/abonar/",
                datos,
                format="json",
                HTTP_IDEMPOTENCY_KEY="abono-clave-001",
            )
            assert r.status_code == 201
        assert AbonoVenta.objects.sin_ambito().count() == 1

    def test_anular_un_abono_requiere_el_permiso_y_devuelve_la_deuda(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        abono = self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "60.00"}]
        ).json()["abonos"][0]
        url = f"{BASE}/abonos/{abono['id']}/anular/"
        assert cliente_de("cajero").post(url, {"motivo": "Error"}, format="json").status_code == 403
        r = cliente_de("admin").post(url, {"motivo": "Error de digitación"}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["saldo"] == "141.60" and r.json()["abonos"][0]["anulado"] is True

    def test_el_detalle_de_la_venta_trae_cuotas_y_abonos(self, tienda, venta):
        comprobante = venta["comprobantes"][0]
        self.abonar(
            "cajero", comprobante["id"], [{"medio_pago": tienda.efectivo.pk, "monto": "47.20"}]
        )
        d = cliente_de("vendedor").get(f"{BASE}/{venta['id']}/").json()
        assert d["forma_pago"] == "CREDITO" and d["comprobantes"][0]["saldo"] == "94.40"
        lista = cliente_de("vendedor").get(f"{BASE}/", {"empresa": tienda.a.pk}).json()
        assert lista["results"][0]["forma_pago"] == "CREDITO"
        assert json.dumps(d).count("costo") == 0


class TestLimiteDeCreditoDelCliente:
    def test_un_cliente_nuevo_tiene_credito_sin_tope(self, tienda):
        r = cliente_de("admin").post(
            "/api/v1/mantenimiento/clientes/",
            {"tipo_documento": "DNI", "numero_documento": "45678912", "nombre": "Ana Ruiz"},
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["credito_sin_limite"] is True and r.json()["limite_credito"] == "0.00"

    def test_solo_quien_tiene_el_permiso_fija_el_limite(self, tienda):
        cliente = tienda.cliente("0", numero="20100000041")
        url = f"/api/v1/mantenimiento/clientes/{cliente.pk}/"
        datos = {"nombre": "Ferretería El Sol", "limite_credito": "5000.00"}
        r = cliente_de("vendedor").patch(url, datos, format="json")
        assert r.status_code == 200, r.content
        assert Cliente.objects.sin_ambito().get(pk=cliente.pk).limite_credito == 0
        r = cliente_de("admin").patch(url, datos, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["limite_credito"] == "5000.00"
        assert Cliente.objects.sin_ambito().get(pk=cliente.pk).limite_credito == 5000
        r = cliente_de("vendedor").patch(url, {**datos, "credito_sin_limite": True}, format="json")
        assert Cliente.objects.sin_ambito().get(pk=cliente.pk).credito_sin_limite is False
        r = cliente_de("admin").patch(url, {**datos, "credito_sin_limite": True}, format="json")
        assert r.json()["credito_sin_limite"] is True
