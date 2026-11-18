"""Pago por transferencia o depósito: configuración, pedido, comprobante y verificación."""

# ruff: noqa: F811

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.caja.models import MovimientoCaja
from apps.inventario.models import SaldoStock
from apps.mantenimiento.models import CuentaFinanciera
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda.models import AvisoPedido, ConfiguracionPago, PedidoTienda, ReservaStock

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import PEDIDOS, contexto, cuerpo, vende  # noqa: F401
from .test_pedidos_admin import ADMIN, estado

pytestmark = pytest.mark.django_db

PAGOS = "/api/v1/tienda/admin/pagos/"
PUBLICA = "/api/v1/tienda/pagos/configuracion"


def banco(empresa, nombre="BCP soles", **extra):
    datos = {
        "empresa": empresa,
        "nombre": nombre,
        "tipo": CuentaFinanciera.Tipo.BANCO,
        "moneda": CuentaFinanciera.Moneda.PEN,
        "banco": "BCP",
        "numero_cuenta": "194-1234567-0-12",
        "cci": "00219400123456701234",
    }
    datos.update(extra)
    return CuentaFinanciera.objects.sin_ambito().create(**datos)


def activar(cobra, cuenta, **extra):
    contexto(cobra)
    config = ConfiguracionPago.objects.sin_ambito().get(organizacion=cobra.org)
    config.transferencia_activa = True
    for k, v in extra.items():
        setattr(config, k, v)
    config.save()
    config.cuentas_transferencia.set([cuenta])
    return config


def foto(formato="PNG", tam=(300, 200)):
    buffer = io.BytesIO()
    Image.new("RGB", tam, (10, 120, 200)).save(buffer, format=formato)
    return buffer.getvalue()


def archivo(contenido=None, nombre="voucher.png", tipo="image/png"):
    return SimpleUploadedFile(nombre, contenido or foto(), content_type=tipo)


def pedir(cobra, cuenta, cliente=None, **extra):
    contexto(cobra)
    p = cobra.publicar("Mouse", precio=100, stock=10)
    cliente = cliente or registrada()
    from .test_pedidos import con_direccion

    d = con_direccion(cliente)
    r = cliente.post(
        PEDIDOS,
        cuerpo(
            (p, 1), direccion=d, metodo="TRANSFERENCIA", cuenta_transferencia=cuenta.pk, **extra
        ),
        format="json",
    )
    return p, cliente, r


def subir(cliente, numero, **extra):
    return cliente.post(
        f"{PEDIDOS}/{numero}/voucher", {"imagen": archivo(), **extra}, format="multipart"
    )


@pytest.fixture
def con_cuenta(cobra):
    cuenta = banco(cobra.e.e1)
    activar(cobra, cuenta)
    return cobra, cuenta


class TestConfiguracion:
    def test_publica_muestra_las_cuentas_sin_culqi_y_sin_datos_internos(self, cobra):
        cuenta = banco(cobra.e.e1)
        activar(cobra, cuenta, transferencia_instrucciones="Envía el voucher.")
        ConfiguracionPago.objects.sin_ambito().update(culqi_activo=False)
        d = APIClient().get(PUBLICA).json()
        assert d["activo"] is False and d["transferencia"]["activa"] is True
        c = d["transferencia"]["cuentas"][0]
        assert c["numero"] == "194-1234567-0-12" and c["titular"] == cobra.e.e1.razon_social
        assert d["transferencia"]["horas"] == 24
        assert set(c) == {"id", "nombre", "tipo", "banco", "titular", "ruc", "numero", "cci"}

    def test_apagada_o_sin_cuentas_no_se_ofrece(self, cobra):
        assert APIClient().get(PUBLICA).json()["transferencia"] == {"activa": False}
        contexto(cobra)
        activar(cobra, banco(cobra.e.e1))
        ConfiguracionPago.objects.sin_ambito().update(transferencia_activa=False)
        assert APIClient().get(PUBLICA).json()["transferencia"]["activa"] is False

    def test_el_panel_guarda_y_exige_una_cuenta_para_activar(self, cobra):
        c = cliente_de("admin")
        cuenta = banco(cobra.e.e1)
        r = c.patch(PAGOS, {"transferencia_activa": True}, format="json")
        assert r.status_code == 400
        r = c.patch(
            PAGOS,
            {
                "transferencia_activa": True,
                "cuentas_transferencia": [cuenta.pk],
                "transferencia_horas": 48,
                "transferencia_instrucciones": "  Pon tu\n pedido  ",
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        t = r.json()["transferencia"]
        assert t == {
            "activa": True,
            "horas": 48,
            "instrucciones": "Pon tu pedido",
            "cuentas": [cuenta.pk],
        }
        assert any(x["id"] == cuenta.pk for x in r.json()["opciones"]["cuentas"])

    def test_solo_cuentas_de_banco_o_billetera_en_soles(self, cobra):
        c = cliente_de("admin")
        dolares = banco(cobra.e.e1, "USD", moneda=CuentaFinanciera.Moneda.USD)
        caja = banco(cobra.e.e1, "Caja", tipo=CuentaFinanciera.Tipo.CAJA)
        for malo in (dolares, caja):
            r = c.patch(PAGOS, {"cuentas_transferencia": [malo.pk]}, format="json")
            assert r.status_code == 400, malo.nombre

    def test_sin_permiso_no_se_configura(self, cobra):
        r = cliente_de("almacenero").patch(PAGOS, {"transferencia_horas": 5}, format="json")
        assert r.status_code == 403


class TestPedido:
    def test_crea_el_pedido_con_mas_tiempo_y_stock_apartado(self, con_cuenta):
        cobra, cuenta = con_cuenta
        p, _, r = pedir(cobra, cuenta)
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["estado"] == "PENDIENTE_PAGO" and d["pago_metodo"] == "TRANSFERENCIA"
        assert d["transferencia"]["cuenta"]["numero"] == "194-1234567-0-12"
        assert d["transferencia"]["tiene_voucher"] is False
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert timedelta(hours=23) < pedido.expira_en - timezone.now() <= timedelta(hours=24)
        assert ReservaStock.objects.sin_ambito().filter(pedido=pedido, liberada_en=None).exists()

    def test_no_se_puede_si_la_transferencia_no_esta_activa(self, cobra):
        cuenta = banco(cobra.e.e1)
        _, _, r = pedir(cobra, cuenta)
        assert r.status_code == 400

    def test_cuenta_ajena_o_no_ofrecida_se_rechaza(self, con_cuenta):
        cobra, _ = con_cuenta
        otra = banco(cobra.e.e1, "Otra")
        _, _, r = pedir(cobra, otra)
        assert r.status_code == 400

    def test_con_productos_de_otra_empresa_hay_que_pagar_con_tarjeta(self, cobra):
        cuenta = banco(cobra.e.e2, "BBVA empresa 2")
        activar(cobra, cuenta)
        _, _, r = pedir(cobra, cuenta)  # el producto sale de la empresa 1
        assert r.status_code == 400 and "más de una empresa" in r.json()["error"]["mensaje"]

    def test_no_se_combina_con_adelanto(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, _, r = pedir(cobra, cuenta, pago="ADELANTO")
        assert r.status_code == 400

    def test_culqi_no_cobra_un_pedido_por_transferencia(self, con_cuenta, culqi_falso):
        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        r = pagar_pedido(c, r.json()["numero"])
        assert r.status_code == 400 and not culqi_falso.cobros


class TestVoucher:
    def test_el_cliente_sube_su_comprobante_y_queda_por_verificar(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        numero = r.json()["numero"]
        n = len(mail.outbox)
        r = subir(c, numero, operacion="  OP 99 887 ")
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "POR_VERIFICAR" and d["transferencia"]["tiene_voucher"] is True
        assert d["transferencia"]["operacion"] == "OP 99 887"
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.voucher.name.endswith(".webp") and pedido.voucher_subido_en
        assert len(mail.outbox) == n + 1 and numero in mail.outbox[-1].subject
        assert AvisoPedido.objects.sin_ambito().filter(evento="PEDIDO_VOUCHER").exists()

    def test_se_guarda_reencodificado_y_sin_metadatos(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        assert subir(c, r.json()["numero"]).status_code == 200
        pedido = PedidoTienda.objects.sin_ambito().get()
        with pedido.voucher.open("rb") as f:
            assert Image.open(f).format == "WEBP"

    def test_rechaza_lo_que_no_es_imagen(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        malo = SimpleUploadedFile("x.png", b"%PDF-1.4 no soy una foto", content_type="image/png")
        r2 = c.post(f"{PEDIDOS}/{r.json()['numero']}/voucher", {"imagen": malo}, format="multipart")
        assert r2.status_code == 400
        assert PedidoTienda.objects.sin_ambito().get().estado == "PENDIENTE_PAGO"

    def test_solo_el_dueno_del_pedido_puede_subirlo(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, _, r = pedir(cobra, cuenta)
        otro = registrada("otro@correo.com")
        assert subir(otro, r.json()["numero"]).status_code == 404

    def test_un_pedido_vencido_no_acepta_comprobante(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(minutes=1))
        assert subir(c, r.json()["numero"]).status_code in (400, 409, 410)

    def test_el_comprobante_no_tiene_direccion_publica(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        subir(c, r.json()["numero"])
        assert "voucher" not in str(c.get(f"{PEDIDOS}/{r.json()['numero']}").json()).replace(
            "tiene_voucher", ""
        )

    def test_el_vencimiento_no_toca_un_pedido_con_comprobante_por_verificar(self, con_cuenta):
        from apps.tienda import pedidos

        cobra, cuenta = con_cuenta
        _, c, r = pedir(cobra, cuenta)
        subir(c, r.json()["numero"])
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(hours=1))
        assert pedidos.expirar_vencidos() == 0
        assert PedidoTienda.objects.sin_ambito().get().estado == "POR_VERIFICAR"


class TestVerificar:
    def listo(self, con_cuenta):
        cobra, cuenta = con_cuenta
        p, c, r = pedir(cobra, cuenta)
        numero = r.json()["numero"]
        assert subir(c, numero).status_code == 200
        return cobra, cuenta, p, c, numero

    def test_el_personal_ve_el_comprobante(self, con_cuenta):
        _, _, _, _, numero = self.listo(con_cuenta)
        r = cliente_de("admin").get(f"{ADMIN}/{numero}/voucher/")
        assert r.status_code == 200 and r["Content-Type"] == "image/webp"
        assert Image.open(io.BytesIO(r.content)).format == "WEBP"

    def test_sin_sesion_o_sin_permiso_no_se_ve(self, con_cuenta):
        _, _, _, c, numero = self.listo(con_cuenta)
        assert c.get(f"{ADMIN}/{numero}/voucher/").status_code in (401, 403)

    def test_confirmar_emite_la_venta_y_el_dinero_entra_a_la_cuenta_elegida(self, con_cuenta):
        cobra, cuenta, p, _, numero = self.listo(con_cuenta)
        n = len(mail.outbox)
        r = cliente_de("admin").post(
            f"{ADMIN}/{numero}/transferencia/confirmar/", {"referencia": "OP-77"}, format="json"
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "PAGADO" and len(d["comprobantes"]) == 1
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.venta_id and pedido.pagado_en
        mov = MovimientoCaja.objects.sin_ambito().get(cuenta=cuenta)
        assert mov.monto == pedido.total and mov.tipo == "INGRESO"
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 9
        assert not ReservaStock.objects.sin_ambito().filter(liberada_en=None).exists()
        assert len(mail.outbox) > n  # confirmación de pago
        assert pedido.voucher_operacion == "OP-77"

    def test_no_se_confirma_dos_veces(self, con_cuenta):
        _, _, _, _, numero = self.listo(con_cuenta)
        a = cliente_de("admin")
        assert (
            a.post(f"{ADMIN}/{numero}/transferencia/confirmar/", {}, format="json").status_code
            == 200
        )
        assert (
            a.post(f"{ADMIN}/{numero}/transferencia/confirmar/", {}, format="json").status_code
            == 409
        )
        assert MovimientoCaja.objects.sin_ambito().filter(tipo="INGRESO").count() >= 1

    def test_confirmar_sin_comprobante_subido_no_se_puede(self, con_cuenta):
        cobra, cuenta = con_cuenta
        _, _, r = pedir(cobra, cuenta)
        r2 = cliente_de("admin").post(
            f"{ADMIN}/{r.json()['numero']}/transferencia/confirmar/", {}, format="json"
        )
        assert r2.status_code == 409

    def test_rechazar_devuelve_el_pedido_a_pendiente_con_el_motivo_y_mas_plazo(self, con_cuenta):
        _, _, _, c, numero = self.listo(con_cuenta)
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() + timedelta(minutes=5))
        n = len(mail.outbox)
        r = cliente_de("admin").post(
            f"{ADMIN}/{numero}/transferencia/rechazar/",
            {"motivo": "El monto no coincide"},
            format="json",
        )
        assert r.status_code == 200, r.content
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.estado == "PENDIENTE_PAGO" and not pedido.voucher
        assert pedido.transferencia_rechazo == "El monto no coincide"
        assert pedido.expira_en - timezone.now() > timedelta(hours=23)
        assert len(mail.outbox) == n + 1 and "El monto no coincide" in mail.outbox[-1].body
        # el cliente ve el motivo y puede subir otro comprobante
        assert c.get(f"{PEDIDOS}/{numero}").json()["transferencia"]["rechazo"]
        assert subir(c, numero).status_code == 200
        assert PedidoTienda.objects.sin_ambito().get().transferencia_rechazo == ""

    def test_rechazos_repetidos_avisan_cada_vez(self, con_cuenta):
        _, _, _, c, numero = self.listo(con_cuenta)
        a = cliente_de("admin")
        for veces in (1, 2):
            r = a.post(
                f"{ADMIN}/{numero}/transferencia/rechazar/",
                {"motivo": f"Intento {veces} malo"},
                format="json",
            )
            assert r.status_code == 200
            if veces == 1:
                assert subir(c, numero).status_code == 200
        eventos = (
            AvisoPedido.objects.sin_ambito().filter(canal="CORREO").values_list("evento", flat=True)
        )
        assert {"PEDIDO_PAGO_RECHAZADO_1", "PEDIDO_PAGO_RECHAZADO_2"} <= set(eventos)

    def test_rechazar_pide_un_motivo(self, con_cuenta):
        _, _, _, _, numero = self.listo(con_cuenta)
        r = cliente_de("admin").post(
            f"{ADMIN}/{numero}/transferencia/rechazar/", {"motivo": "no"}, format="json"
        )
        assert r.status_code == 400

    def test_cancelar_un_pedido_por_verificar_suelta_el_stock_y_borra_el_comprobante(
        self, con_cuenta
    ):
        _, _, _, _, numero = self.listo(con_cuenta)
        r = estado(cliente_de("admin"), numero, "CANCELADO")
        assert r.status_code == 200, r.content
        pedido = PedidoTienda.objects.sin_ambito().get()
        assert pedido.estado == "CANCELADO"
        assert not ReservaStock.objects.sin_ambito().filter(liberada_en=None).exists()

    def test_aparece_en_la_pestana_y_el_conteo_del_panel(self, con_cuenta):
        self.listo(con_cuenta)
        a = cliente_de("admin")
        assert a.get(f"{ADMIN}/resumen/").json()["grupos"]["por_verificar"] == 1
        r = a.get(f"{ADMIN}/", {"grupo": "por_verificar"}).json()
        assert r["count"] == 1
        d = a.get(f"{ADMIN}/{r['results'][0]['numero']}/").json()
        assert d["acciones"]["verificar_transferencia"] is True
        assert d["pago"]["metodo"] == "TRANSFERENCIA"
        assert Decimal(d["total"]) > 0
