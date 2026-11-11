"""Cobro de pedidos con Culqi (simulado) y paso a venta real."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.inventario.models import SaldoStock
from apps.tienda import culqi
from apps.tienda.models import (
    ConfiguracionPago,
    DeudaCobroTienda,
    IntentoPago,
    PedidoTienda,
    ReservaStock,
)
from apps.ventas.models import CobroVenta, ComprobanteVenta, Venta

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import nuevo_cliente, registrada
from .test_pedidos import (
    PEDIDOS,
    con_direccion,
    contexto,
    cuerpo,
    pedido_de_prueba,
    vende,  # noqa: F401
)

pytestmark = pytest.mark.django_db

PK, SK = "pk_test_abc", "sk_test_secreto_largo_123"
TOKEN = "tkn_test_abcdef123456"


class CulqiFalso:
    """Reemplaza a ``culqi.llamar``: nunca sale a internet."""

    def __init__(self):
        self.modo = "aprueba"  # aprueba | rechaza | cae
        self.cobros: list[dict] = []
        self.guardados: dict[str, dict] = {}
        self.idempotencias: list[str] = []

    def __call__(self, metodo, ruta, llave, cuerpo=None, idempotencia=""):
        assert llave == SK
        if metodo == "POST" and ruta == "charges":
            if self.modo == "cae":
                raise culqi.ErrorCulqi("No pudimos conectar con Culqi.")
            if self.modo == "rechaza":
                return culqi.RespuestaCulqi(
                    400,
                    {
                        "object": "error",
                        "type": "card_error",
                        "user_message": "La tarjeta no tiene fondos suficientes.",
                        "merchant_message": "detalle técnico que no debe verse",
                    },
                )
            self.cobros.append(cuerpo)
            self.idempotencias.append(idempotencia)
            cargo = self.nuevo_cargo(cuerpo["amount"], cuerpo["metadata"]["pedido"])
            return culqi.RespuestaCulqi(201, cargo)
        if metodo == "GET" and ruta.startswith("charges/"):
            cargo = self.guardados.get(ruta.split("/")[1])
            return culqi.RespuestaCulqi(200 if cargo else 404, cargo or {})
        raise AssertionError(f"llamada inesperada {metodo} {ruta}")

    def nuevo_cargo(self, centimos, pedido, *, tipo="card"):
        cargo = {
            "id": f"chr_test_{len(self.guardados) + 1}",
            "object": "charge",
            "amount": centimos,
            "outcome": {"type": "venta_exitosa"},
            "metadata": {"pedido": pedido},
            "source": {"type": tipo},
        }
        self.guardados[cargo["id"]] = cargo
        return cargo


@pytest.fixture
def culqi_falso(monkeypatch):
    falso = CulqiFalso()
    monkeypatch.setattr(culqi, "llamar", falso)
    return falso


@pytest.fixture
def cobra(vende):
    """La tienda con Culqi activo y la empresa principal como quien recibe los pagos."""
    ConfiguracionPago.objects.sin_ambito().create(
        organizacion=vende.org,
        culqi_activo=True,
        culqi_llave_publica=PK,
        culqi_llave_secreta=SK,
        empresa_cobra=vende.e.e1,
    )
    contexto(vende)
    return vende


def pagar_pedido(cliente, numero="T-000001", **extra):
    return cliente.post(f"{PEDIDOS}/{numero}/pagar", {"token": TOKEN, **extra}, format="json")


class TestPagoExitoso:
    def test_crea_la_venta_descuenta_el_stock_y_cobra_el_total(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5, cantidad=2)
        total = Decimal(r.json()["importes"]["total"])  # 2 × 118 + envío 11.80
        n = len(mail.outbox)
        r = pagar_pedido(c)
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "PAGADO" and d["requiere_atencion"] is False
        # Culqi recibió el total en CÉNTIMOS y una clave de idempotencia propia del intento
        assert culqi_falso.cobros[0]["amount"] == int(total * 100)
        assert culqi_falso.cobros[0]["currency_code"] == "PEN"
        assert culqi_falso.idempotencias[0].startswith("tienda-")
        # una venta con UN comprobante (boleta) por el total, sin tarjeta ni token guardados
        venta = Venta.objects.sin_ambito().get()
        comprobantes = ComprobanteVenta.objects.sin_ambito().filter(venta=venta)
        assert comprobantes.count() == 1 and comprobantes[0].total == total
        assert d["comprobantes"][0]["numero"] == comprobantes[0].numero_completo
        cobro = CobroVenta.objects.sin_ambito().get()
        assert cobro.monto == total and cobro.cuenta.nombre == "Culqi (tienda virtual)"
        assert cobro.medio_pago.nombre == "Tarjeta (Culqi)"
        # el stock salió y la reserva ya no cuenta
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 3
        assert not ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()
        # el pedido quedó enlazado y el cliente real, creado y vinculado a la cuenta
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.venta_id == venta.pk and pedido.culqi_cargo_id == "chr_test_1"
        assert pedido.cuenta.cliente_id is not None
        # correo de confirmación sin datos de tarjeta
        assert len(mail.outbox) == n + 1
        cuerpo_correo = mail.outbox[-1].body
        assert "T-000001" in cuerpo_correo and TOKEN not in cuerpo_correo
        assert not IntentoPago.objects.sin_ambito().filter(estado="EN_CURSO").exists()

    def test_yape_usa_su_propio_metodo_de_pago(self, cobra, culqi_falso, monkeypatch):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        original = culqi_falso.nuevo_cargo
        monkeypatch.setattr(
            culqi_falso, "nuevo_cargo", lambda a, ped, **k: original(a, ped, tipo="yape")
        )
        assert pagar_pedido(c).status_code == 200
        assert CobroVenta.objects.sin_ambito().get().medio_pago.nombre == "Yape (Culqi)"

    def test_con_documento_la_factura_sale_al_ruc(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(
            cobra,
            stock=5,
            comprobante={
                "tipo": "01",
                "documento_tipo": "RUC",
                "documento_numero": "20123456786",
                "nombre": "Empresa SAC",
                "direccion_fiscal": "Av. X 1",
            },
        )
        assert r.status_code == 201, r.content
        assert pagar_pedido(c).status_code == 200
        comprobante = ComprobanteVenta.objects.sin_ambito().get()
        assert comprobante.numero_completo.startswith("F")
        assert (
            PedidoTienda.objects.sin_ambito().get().cuenta.cliente.numero_documento == "20123456786"
        )


class TestRechazoYReintento:
    def test_un_rechazo_deja_el_pedido_para_reintentar(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        culqi_falso.modo = "rechaza"
        r = pagar_pedido(c)
        assert r.status_code == 402
        assert "fondos" in r.json()["error"]["mensaje"]
        assert "técnico" not in r.content.decode()  # nunca el mensaje interno de Culqi
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.estado == "PENDIENTE_PAGO"
        assert ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()
        assert IntentoPago.objects.sin_ambito().get().estado == "RECHAZADO"
        culqi_falso.modo = "aprueba"
        assert pagar_pedido(c).status_code == 200
        assert IntentoPago.objects.sin_ambito().count() == 2

    def test_culqi_que_no_responde_bloquea_otro_cobro_hasta_confirmar(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        culqi_falso.modo = "cae"
        assert pagar_pedido(c).status_code == 409  # pago en proceso: no sabemos si cobró
        culqi_falso.modo = "aprueba"
        r = pagar_pedido(c)
        assert r.status_code == 409 and not culqi_falso.cobros  # no se cobró de nuevo
        assert PedidoTienda.objects.sin_ambito().get().estado == "PENDIENTE_PAGO"
        # sin cancelar ni vencer mientras tanto
        assert c.post(f"{PEDIDOS}/T-000001/cancelar", {}, format="json").status_code == 409

    def test_el_webhook_termina_un_pago_incierto(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        culqi_falso.modo = "cae"
        pagar_pedido(c)
        total = PedidoTienda.objects.sin_ambito().get().total
        cargo = culqi_falso.nuevo_cargo(int(total * 100), "T-000001")  # Culqi sí cobró
        r = APIClient().post(
            "/api/v1/tienda/pagos/webhook", {"data": f'{{"id": "{cargo["id"]}"}}'}, format="json"
        )
        assert r.status_code == 200 and r.json()["resultado"] == "confirmado"
        assert PedidoTienda.objects.sin_ambito().get().estado == "PAGADO"


class TestDobleClic:
    def test_un_intento_en_curso_impide_cobrar_otra_vez(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        pedido = PedidoTienda.objects.sin_ambito().get()
        IntentoPago.objects.sin_ambito().create(
            organizacion=cobra.org, pedido=pedido, monto=pedido.total
        )
        r = pagar_pedido(c)
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "pago_en_proceso"
        assert culqi_falso.cobros == []

    def test_un_pedido_pagado_no_se_cobra_dos_veces(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        assert pagar_pedido(c).status_code == 200
        assert pagar_pedido(c).status_code == 409
        assert len(culqi_falso.cobros) == 1 and Venta.objects.sin_ambito().count() == 1


class TestSeguridad:
    def test_el_monto_no_lo_manda_el_navegador(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        total = PedidoTienda.objects.sin_ambito().get().total
        r = pagar_pedido(c, monto="0.01", amount=1, total="0.01")
        assert r.status_code == 200
        assert culqi_falso.cobros[0]["amount"] == int(total * 100)

    def test_un_pedido_ajeno_no_se_toca(self, cobra, culqi_falso):
        pedido_de_prueba(cobra, stock=5)
        otro = registrada(correo="luis@ejemplo.pe")
        assert pagar_pedido(otro).status_code == 404
        assert culqi_falso.cobros == []
        assert (
            nuevo_cliente()
            .post(f"{PEDIDOS}/T-000001/pagar", {"token": TOKEN}, format="json")
            .status_code
            == 401
        )

    def test_pide_la_cabecera_y_un_token_valido(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        assert (
            APIClient()
            .post(f"{PEDIDOS}/T-000001/pagar", {"token": TOKEN}, format="json")
            .status_code
            == 403
        )
        assert pagar_pedido(c, token="x;drop table").status_code in (400, 402)
        assert pagar_pedido(c, token="").status_code == 400
        assert culqi_falso.cobros == []

    def test_correo_sin_confirmar_no_paga(self, cobra, culqi_falso):
        pedido_de_prueba(cobra, stock=5)
        from apps.tienda.models import CuentaCliente

        CuentaCliente.objects.sin_ambito().update(correo_verificado_en=None)
        c = nuevo_cliente()
        c.post(
            "/api/v1/tienda/cuenta/ingresar",
            {"correo": "ana@ejemplo.pe", "password": "Clave-segura-9"},
            format="json",
        )
        assert pagar_pedido(c).status_code == 403 and culqi_falso.cobros == []

    def test_sin_configuracion_activa_responde_503(self, vende, culqi_falso):
        p, c, r = pedido_de_prueba(vende, stock=5)
        assert pagar_pedido(c).status_code == 503
        ConfiguracionPago.objects.sin_ambito().create(
            organizacion=vende.org, culqi_activo=False, culqi_llave_secreta=SK
        )
        assert pagar_pedido(c).status_code == 503 and culqi_falso.cobros == []

    def test_un_pedido_vencido_no_se_cobra(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(minutes=1))
        r = pagar_pedido(c)
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "pedido_vencido"
        assert culqi_falso.cobros == []

    def test_el_secreto_no_se_filtra_en_las_respuestas(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        r = pagar_pedido(c)
        assert SK not in r.content.decode() and TOKEN not in r.content.decode()


class TestPedidoMixto:
    def _mixto(self, cobra):
        from apps.inventario.tests.conftest import comprar as comprar_stock

        e = cobra.e
        contexto(cobra)
        a = cobra.publicar("Mouse", precio=100, stock=5, peso_kg=Decimal("0.5"))  # empresa 1
        b = cobra.publicar("Cable", precio=50, stock=0, peso_kg=Decimal("0.2"))
        comprar_stock(e, b, 5, 1, empresa=e.e2, almacen=e.alm2)  # solo la empresa 2 lo tiene
        c = registrada()
        d = con_direccion(c)
        contexto(cobra)
        r = c.post(PEDIDOS, cuerpo((a, 1), (b, 2), direccion=d), format="json")
        assert r.status_code == 201, r.content
        return a, b, c, r.json()

    def test_un_comprobante_por_empresa_y_deuda_a_la_otra(self, cobra, culqi_falso):
        a, b, c, pedido = self._mixto(cobra)
        r = pagar_pedido(c)
        assert r.status_code == 200, r.content
        assert ComprobanteVenta.objects.sin_ambito().count() == 2
        e = cobra.e
        cobros = {x.empresa_id: x for x in CobroVenta.objects.sin_ambito().all()}
        assert set(cobros) == {e.e1.pk, e.e2.pk}
        assert cobros[e.e1.pk].cuenta.nombre == "Culqi (tienda virtual)"
        assert cobros[e.e2.pk].cuenta.nombre == "Culqi (cobrado por otra empresa)"
        assert sum(x.monto for x in cobros.values()) == Decimal(pedido["importes"]["total"])
        deuda = DeudaCobroTienda.objects.sin_ambito().get()
        assert deuda.deudora_id == e.e1.pk and deuda.acreedora_id == e.e2.pk
        assert deuda.monto == cobros[e.e2.pk].monto  # sin comisión
        assert len(culqi_falso.cobros) == 1  # un solo cobro a Culqi


class TestFallaTrasCobrar:
    def test_queda_pagado_sin_comprobante_y_el_reintento_lo_repara(
        self, cobra, culqi_falso, monkeypatch
    ):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        from apps.ventas import servicios as ventas

        real = ventas.registrar_venta
        monkeypatch.setattr(
            ventas, "registrar_venta", lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        r = pagar_pedido(c)
        assert r.status_code == 200 and r.json()["estado"] == "PAGADO_SIN_COMPROBANTE"
        assert r.json()["requiere_atencion"] is True
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.culqi_cargo_id == "chr_test_1" and pedido.pagado_en is not None
        assert Venta.objects.sin_ambito().count() == 0
        # la reserva se conserva: el stock sigue apartado
        assert ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()
        assert "boom" not in pedido.motivo_atencion  # nada técnico en el motivo
        # el vencimiento NO lo toca aunque pase el plazo
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(hours=1))
        from apps.tienda import pedidos

        assert pedidos.expirar_vencidos() == 0
        # el servicio se recupera: la tarea reintenta SIN cobrar de nuevo
        monkeypatch.setattr(ventas, "registrar_venta", real)
        from apps.tienda.tasks import reintentar_comprobantes

        assert reintentar_comprobantes() == 1
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.estado == "PAGADO" and pedido.venta_id is not None
        assert len(culqi_falso.cobros) == 1  # nunca se vuelve a cobrar
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 4

    def test_pago_llega_cuando_el_pedido_ya_vencio(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        pedido = PedidoTienda.objects.sin_ambito().get()
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(minutes=1))
        assert pedidos_vencidos() == 1
        cargo = culqi_falso.nuevo_cargo(int(pedido.total * 100), pedido.numero)
        r = APIClient().post(
            "/api/v1/tienda/pagos/webhook", {"data": {"id": cargo["id"]}}, format="json"
        )
        assert r.json()["resultado"] == "confirmado"
        pedido.refresh_from_db()
        assert pedido.estado == "PAGADO_FUERA_DE_PLAZO" and pedido.motivo_atencion
        assert Venta.objects.sin_ambito().count() == 0  # no se vende sin stock reservado


def pedidos_vencidos():
    from apps.tienda import pedidos

    return pedidos.expirar_vencidos()


class TestWebhook:
    def test_es_idempotente_y_no_confia_en_el_aviso(self, cobra, culqi_falso):
        p, c, r = pedido_de_prueba(cobra, stock=5)
        pedido = PedidoTienda.objects.sin_ambito().get()
        # un cargo que Culqi NO conoce: el aviso solo no confirma nada
        falso = APIClient().post(
            "/api/v1/tienda/pagos/webhook",
            {"data": '{"id": "chr_test_inventado", "amount": 1}', "pedido": pedido.numero},
            format="json",
        )
        assert falso.status_code == 503
        assert PedidoTienda.objects.sin_ambito().get().estado == "PENDIENTE_PAGO"
        # un cargo real por otro monto no confirma el pedido
        raro = culqi_falso.nuevo_cargo(100, pedido.numero)
        r = APIClient().post(
            "/api/v1/tienda/pagos/webhook", {"data": {"id": raro["id"]}}, format="json"
        )
        assert r.json()["resultado"] == "monto_distinto"
        assert PedidoTienda.objects.sin_ambito().get().estado == "PENDIENTE_PAGO"
        # el cargo correcto sí; repetirlo no duplica la venta
        bueno = culqi_falso.nuevo_cargo(int(pedido.total * 100), pedido.numero)
        cuerpo_aviso = {"data": {"id": bueno["id"]}}
        for esperado in ("confirmado", "ya_confirmado"):
            r = APIClient().post("/api/v1/tienda/pagos/webhook", cuerpo_aviso, format="json")
            assert r.status_code == 200 and r.json()["resultado"] == esperado
        assert Venta.objects.sin_ambito().count() == 1 and len(mail.outbox) >= 1

    def test_ignora_avisos_raros_y_cuerpos_enormes(self, cobra, culqi_falso):
        cliente = APIClient()
        assert (
            cliente.post("/api/v1/tienda/pagos/webhook", {"x": 1}, format="json").json()[
                "resultado"
            ]
            == "ignorado"
        )
        assert (
            cliente.post(
                "/api/v1/tienda/pagos/webhook", {"data": "no json"}, format="json"
            ).status_code
            == 200
        )
        grande = {"data": "a" * 25_000}
        assert (
            cliente.post("/api/v1/tienda/pagos/webhook", grande, format="json").status_code == 413
        )
