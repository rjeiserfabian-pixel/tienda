"""Pago con adelanto (etapa 1): oferta, pedido, cobro del adelanto, caja y reservas."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.caja.models import MovimientoCaja, Origen
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import adelantos
from apps.tienda.models import AvisoPedido, ConfiguracionPago, PedidoTienda, ReservaStock

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import COTIZAR, PEDIDOS, contexto, cuerpo, vende  # noqa: F401
from .test_pedidos_admin import ADMIN, estado

pytestmark = pytest.mark.django_db

ENVIOS = "/api/v1/tienda/admin/envios/"
PAGOS = "/api/v1/tienda/admin/pagos/"


def con_adelanto(cobra, **cambios):
    """Enciende el adelanto (30 % desde S/ 100, 5 días, devolviendo menos la comisión)."""
    datos = {"adelanto_activo": True, "adelanto_minimo": Decimal("100"), **cambios}
    ConfiguracionPago.objects.sin_ambito().filter(organizacion=cobra.org).update(**datos)


def punto_de_recojo():
    return cliente_de("admin").get(ENVIOS).json()["puntos"][0]["id"]


def producto(cobra, precio=100, **extra):
    contexto(cobra)
    return cobra.publicar("Mouse", costo=Decimal("40"), precio=precio, stock=10, **extra)


def cotizar(cobra, cliente, p, modalidad="RECOJO"):
    contexto(cobra)
    cuerpo_cot = {"lineas": [{"producto": p.pk, "cantidad": 1}], "modalidad": modalidad}
    if modalidad == "RECOJO":
        cuerpo_cot["punto"] = punto_de_recojo()
    else:
        from .test_pedidos import con_direccion

        cuerpo_cot["direccion"] = con_direccion(cliente)
    r = cliente.post(COTIZAR, cuerpo_cot, format="json")
    assert r.status_code == 200, r.content
    return r.json()["totales"]


def pedir_recojo(cobra, cliente, p, pago="ADELANTO"):
    contexto(cobra)
    return cliente.post(
        PEDIDOS,
        cuerpo((p, 1), modalidad="RECOJO", punto=punto_de_recojo(), pago=pago),
        format="json",
    )


class TestOferta:
    def test_se_ofrece_solo_al_recoger_en_tienda_y_con_los_importes(self, cobra, culqi_falso):
        con_adelanto(cobra)
        p, c = producto(cobra), registrada()
        t = cotizar(cobra, c, p)
        # 100 + 18 % = 118; el 30 % = 35.40
        assert t["adelanto"]["disponible"] is True
        assert t["adelanto"]["monto"] == "35.40" and t["adelanto"]["saldo"] == "82.60"
        assert t["adelanto"]["dias"] == 5 and t["adelanto"]["porcentaje"] == "30"
        assert (
            "5 días" in t["adelanto"]["condiciones"] and "comisión" in t["adelanto"]["condiciones"]
        )
        assert cotizar(cobra, c, p, "ENVIO")["adelanto"] is None  # un envío se paga completo

    def test_apagado_no_se_menciona(self, cobra, culqi_falso):
        p, c = producto(cobra), registrada()
        assert cotizar(cobra, c, p)["adelanto"] is None

    def test_por_debajo_del_minimo_explica_por_que_no(self, cobra, culqi_falso):
        con_adelanto(cobra, adelanto_minimo=Decimal("500"))
        p, c = producto(cobra), registrada()
        a = cotizar(cobra, c, p)["adelanto"]
        assert a["disponible"] is False and "S/ 500.00" in a["motivo"]

    def test_los_valores_son_editables(self, cobra, culqi_falso):
        con_adelanto(
            cobra,
            adelanto_pct=Decimal("25"),
            adelanto_dias=10,
            adelanto_si_no_recoge="PENALIDAD",
            adelanto_penalidad_pct=Decimal("100"),
        )
        p, c = producto(cobra), registrada()
        a = cotizar(cobra, c, p)["adelanto"]
        assert a["monto"] == "29.50" and a["dias"] == 10 and a["porcentaje"] == "25"
        assert "pierdes tu adelanto" in a["condiciones"]


class TestPedidoYCobro:
    def test_el_pedido_guarda_lo_acordado_y_cobra_solo_el_adelanto(self, cobra, culqi_falso):
        con_adelanto(cobra)
        p, c = producto(cobra), registrada()
        r = pedir_recojo(cobra, c, p)
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["forma_pago"]["modo"] == "ADELANTO" and d["forma_pago"]["cobrado_ahora"] == "35.40"
        assert d["forma_pago"]["saldo"] == "82.60" and d["importes"]["total"] == "118.00"
        # Culqi cobra SOLO el adelanto (en céntimos)
        pagado = pagar_pedido(c, d["numero"])
        assert pagado.status_code == 200, pagado.content
        assert culqi_falso.cobros[0]["amount"] == 3540

    def test_al_pagar_queda_adelanto_pagado_sin_venta_con_caja_y_stock_apartado(
        self, cobra, culqi_falso
    ):
        con_adelanto(cobra)
        p, c = producto(cobra), registrada()
        numero = pedir_recojo(cobra, c, p).json()["numero"]
        n = len(mail.outbox)
        assert pagar_pedido(c, numero).status_code == 200
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "ADELANTO_PAGADO" and pedido.venta_id is None
        # tiene hasta 5 días para recoger
        assert (
            timedelta(days=4, hours=23)
            < pedido.adelanto_vence_en - timezone.now()
            <= timedelta(days=5)
        )
        # el stock sigue apartado (todavía no sale: la venta se hará al entregar)
        reservas = ReservaStock.objects.sin_ambito().filter(pedido=pedido)
        assert reservas.exists() and not reservas.filter(liberada_en__isnull=False).exists()
        # el dinero entró a la cuenta de la empresa que cobra
        mov = MovimientoCaja.objects.sin_ambito().get(origen_tipo=Origen.ADELANTO_TIENDA)
        assert mov.monto == Decimal("35.40") and mov.tipo == "INGRESO"
        assert mov.origen_id == pedido.pk and numero in mov.glosa
        # correo del adelanto (no el de «pago confirmado») y aviso anotado
        assert len(mail.outbox) == n + 1
        correo = mail.outbox[-1]
        assert "Adelanto recibido" in correo.subject and "82.60" in correo.body
        assert "días" in correo.body
        aviso = AvisoPedido.objects.sin_ambito().get(
            pedido=pedido, evento="PEDIDO_ADELANTO", canal="CORREO"
        )
        assert aviso.estado == "ENVIADO"

    def test_lo_acordado_no_cambia_si_el_negocio_edita_la_configuracion(self, cobra, culqi_falso):
        con_adelanto(cobra)
        p, c = producto(cobra), registrada()
        numero = pedir_recojo(cobra, c, p).json()["numero"]
        con_adelanto(cobra, adelanto_pct=Decimal("50"), adelanto_dias=1)
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.adelanto_pct == Decimal("30") and pedido.adelanto_dias == 5
        assert pagar_pedido(c, numero).status_code == 200
        assert culqi_falso.cobros[0]["amount"] == 3540  # sigue siendo el 30 %

    def test_no_se_puede_pedir_adelanto_si_no_corresponde(self, cobra, culqi_falso):
        p, c = producto(cobra), registrada()
        # apagado
        r = pedir_recojo(cobra, c, p)
        assert r.status_code == 400 and "adelanto" in r.json()["error"]["mensaje"].lower()
        # menos del mínimo
        con_adelanto(cobra, adelanto_minimo=Decimal("500"))
        r = pedir_recojo(cobra, c, p)
        assert r.status_code == 400 and "500.00" in r.json()["error"]["mensaje"]
        # un envío no admite adelanto
        con_adelanto(cobra)
        from .test_pedidos import con_direccion

        contexto(cobra)
        r = c.post(
            PEDIDOS,
            cuerpo((p, 1), direccion=con_direccion(c), pago="ADELANTO"),
            format="json",
        )
        assert r.status_code == 400

    def test_pago_completo_sigue_igual(self, cobra, culqi_falso):
        con_adelanto(cobra)
        p, c = producto(cobra), registrada()
        numero = pedir_recojo(cobra, c, p, pago="COMPLETO").json()["numero"]
        assert pagar_pedido(c, numero).status_code == 200
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "PAGADO" and pedido.venta_id is not None
        assert culqi_falso.cobros[0]["amount"] == 11800


class TestAtencion:
    def test_con_saldo_pendiente_no_se_entrega_sin_cobrarlo(self, cobra, culqi_falso):
        con_adelanto(cobra)
        p, c = producto(cobra), registrada()
        numero = pedir_recojo(cobra, c, p).json()["numero"]
        pagar_pedido(c, numero)
        admin = cliente_de("admin")
        assert estado(admin, numero, "EN_PREPARACION").status_code == 200
        assert estado(admin, numero, "LISTO_PARA_RECOJO").status_code == 200
        detalle = admin.get(f"{ADMIN}/{numero}/").json()
        assert detalle["acciones"]["siguientes"] == []  # entregar exige cobrar el saldo
        assert estado(admin, numero, "ENTREGADO").status_code == 409
        assert detalle["forma_pago"]["saldo"] == "82.60"


class TestLiquidacion:
    @pytest.mark.parametrize(
        ("politica", "pct_penalidad", "comision", "fija", "devolver", "retener"),
        [
            ("REEMBOLSO", 0, 4, 0, "33.98", "1.42"),  # 4 % de 35.40
            ("REEMBOLSO", 0, 4, 0.30, "33.68", "1.72"),  # + S/ 0.30 fijos
            ("PENALIDAD", 100, 4, 0, "0.00", "35.40"),  # pierde todo
            ("PENALIDAD", 50, 4, 0, "17.70", "17.70"),  # pierde la mitad
        ],
    )
    def test_que_se_devuelve_y_que_se_retiene(
        self, politica, pct_penalidad, comision, fija, devolver, retener
    ):
        pedido = PedidoTienda(
            adelanto_monto=Decimal("35.40"),
            adelanto_politica=politica,
            adelanto_penalidad_pct=Decimal(str(pct_penalidad)),
            adelanto_comision_pct=Decimal(str(comision)),
            adelanto_comision_fija=Decimal(str(fija)),
        )
        d, r = adelantos.liquidar_no_recogido(pedido)
        assert (format(d, ".2f"), format(r, ".2f")) == (devolver, retener)

    def test_nunca_retiene_mas_de_lo_pagado(self):
        pedido = PedidoTienda(
            adelanto_monto=Decimal("1.00"),
            adelanto_politica="REEMBOLSO",
            adelanto_comision_pct=Decimal("4"),
            adelanto_comision_fija=Decimal("5"),
        )
        d, r = adelantos.liquidar_no_recogido(pedido)
        assert d == Decimal("0.00") and r == Decimal("1.00")


class TestConfiguracionDelPanel:
    def test_se_guarda_y_se_valida(self, tienda, nuevo_usuario):
        nuevo_usuario(tienda.org, "superadmin", [tienda.e.e1], [("SUPERADMIN", None)])
        c = cliente_de("superadmin")
        r = c.patch(
            PAGOS,
            {
                "adelanto_activo": True,
                "adelanto_pct": "25",
                "adelanto_dias": 10,
                "adelanto_minimo": "300",
                "adelanto_si_no_recoge": "PENALIDAD",
                "adelanto_penalidad_pct": "50",
                "comision_pasarela_pct": "3.5",
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        a = r.json()["adelanto"]
        assert a["activo"] is True and a["porcentaje"] == "25.00" and a["dias"] == 10
        assert a["si_no_recoge"] == "PENALIDAD" and a["penalidad_pct"] == "50.00"
        assert a["minimo"] == "300.00" and a["comision_pct"] == "3.50"
        for malo in ({"adelanto_pct": "0"}, {"adelanto_pct": "95"}, {"adelanto_dias": 0}):
            assert c.patch(PAGOS, malo, format="json").status_code == 400, malo
        assert c.patch(PAGOS, {"adelanto_si_no_recoge": "OTRA"}, format="json").status_code == 400


def medio_para_saldo(cobra, *, referencia=False):
    """Un método de pago del mostrador con su cuenta (para cobrar el saldo)."""
    from apps.mantenimiento.models import CuentaFinanciera, MedioPago
    from apps.ventas.models import CuentaDeCobro

    e1 = cobra.e.e1
    medio = MedioPago.objects.sin_ambito().create(
        organizacion=cobra.org,
        nombre="Efectivo mostrador",
        tipo="EFECTIVO",
        requiere_referencia=referencia,
    )
    cuenta = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e1,
        nombre="Caja mostrador",
        tipo=CuentaFinanciera.Tipo.BILLETERA,
        moneda=CuentaFinanciera.Moneda.PEN,
        permite_saldo_negativo=True,
    )
    CuentaDeCobro.objects.sin_ambito().create(empresa=e1, medio_pago=medio, cuenta=cuenta)
    return medio


def con_adelanto_pagado(cobra, culqi_falso):
    con_adelanto(cobra)
    p, c = producto(cobra), registrada()
    numero = pedir_recojo(cobra, c, p).json()["numero"]
    assert pagar_pedido(c, numero).status_code == 200
    return p, c, numero


class TestSaldo:
    def test_cobrar_el_saldo_emite_el_comprobante_por_el_total_y_entrega(self, cobra, culqi_falso):
        from apps.ventas.models import CobroVenta, ComprobanteVenta

        medio = medio_para_saldo(cobra)
        p, c, numero = con_adelanto_pagado(cobra, culqi_falso)
        admin = cliente_de("admin")
        assert estado(admin, numero, "EN_PREPARACION").status_code == 200
        assert estado(admin, numero, "LISTO_PARA_RECOJO").status_code == 200
        info = admin.get(f"{ADMIN}/{numero}/saldo/").json()
        assert info["puede"] is True and info["saldo"] == "82.60" and info["adelanto"] == "35.40"
        assert any(m["id"] == medio.pk for m in info["medios"])
        n = len(mail.outbox)
        r = admin.post(f"{ADMIN}/{numero}/saldo/", {"medio_pago": medio.pk}, format="json")
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "ENTREGADO" and d["acciones"]["cobrar_saldo"] is False
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.venta_id is not None
        # UN comprobante por el TOTAL (118.00); el adelanto de 35.40 ya estaba pagado
        comprobante = ComprobanteVenta.objects.sin_ambito().get(venta_id=pedido.venta_id)
        assert comprobante.total == Decimal("118.00")
        pagos = CobroVenta.objects.sin_ambito().filter(venta_id=pedido.venta_id)
        assert sum(x.monto for x in pagos) == Decimal("118.00")
        # el adelanto NO entra otra vez a caja: solo su ingreso original y el del saldo
        ingresos = MovimientoCaja.objects.sin_ambito().filter(tipo="INGRESO")
        assert ingresos.filter(origen_tipo=Origen.ADELANTO_TIENDA).count() == 1
        assert sum(m.monto for m in ingresos) == Decimal("118.00")
        # el stock salió con la venta y ya no queda apartado
        assert (
            not ReservaStock.objects.sin_ambito()
            .filter(pedido=pedido, liberada_en__isnull=True)
            .exists()
        )
        assert len(mail.outbox) == n + 1 and "entregado" in mail.outbox[-1].subject

    def test_no_se_cobra_dos_veces_ni_un_pedido_pagado_completo(self, cobra, culqi_falso):
        medio = medio_para_saldo(cobra)
        p, c, numero = con_adelanto_pagado(cobra, culqi_falso)
        admin = cliente_de("admin")
        assert (
            admin.post(
                f"{ADMIN}/{numero}/saldo/", {"medio_pago": medio.pk}, format="json"
            ).status_code
            == 200
        )
        assert (
            admin.post(
                f"{ADMIN}/{numero}/saldo/", {"medio_pago": medio.pk}, format="json"
            ).status_code
            == 409
        )
        # un pedido que se pagó completo no tiene saldo
        completo = pedir_recojo(cobra, c, p, pago="COMPLETO").json()["numero"]
        pagar_pedido(c, completo)
        r = admin.post(f"{ADMIN}/{completo}/saldo/", {"medio_pago": medio.pk}, format="json")
        assert r.status_code == 409
        assert admin.get(f"{ADMIN}/{completo}/saldo/").json()["puede"] is False

    def test_pide_el_medio_y_la_referencia_cuando_hace_falta(self, cobra, culqi_falso):
        medio = medio_para_saldo(cobra, referencia=True)
        p, c, numero = con_adelanto_pagado(cobra, culqi_falso)
        admin = cliente_de("admin")
        url = f"{ADMIN}/{numero}/saldo/"
        assert admin.post(url, {"medio_pago": 999999}, format="json").status_code == 400
        sin = admin.post(url, {"medio_pago": medio.pk}, format="json")
        assert sin.status_code == 400 and "número de operación" in sin.json()["error"]["mensaje"]
        assert PedidoTienda.objects.sin_ambito().get(numero=numero).estado == "ADELANTO_PAGADO"
        ok = admin.post(url, {"medio_pago": medio.pk, "referencia": "OP-123"}, format="json")
        assert ok.status_code == 200

    def test_solo_quien_gestiona_pedidos(self, cobra, culqi_falso, nuevo_usuario):
        medio = medio_para_saldo(cobra)
        p, c, numero = con_adelanto_pagado(cobra, culqi_falso)
        nuevo_usuario(cobra.org, "cajero", [cobra.e.e1], [("CAJERO", cobra.e.e1)])
        caj = cliente_de("cajero")
        assert caj.get(f"{ADMIN}/{numero}/saldo/").status_code == 403
        assert (
            caj.post(
                f"{ADMIN}/{numero}/saldo/", {"medio_pago": medio.pk}, format="json"
            ).status_code
            == 403
        )
