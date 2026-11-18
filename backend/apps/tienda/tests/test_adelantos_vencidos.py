"""Adelantos no recogidos: devolver o retener, stock, caja, avisos y recordatorio."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.caja.models import MovimientoCaja, Origen
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import adelantos_vencidos
from apps.tienda.models import AvisoPedido, PedidoTienda, ReembolsoPedido, ReservaStock

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_adelantos import con_adelanto, pedir_recojo, producto
from .test_cuentas import registrada
from .test_pagar import cobra, pagar_pedido  # noqa: F401
from .test_pedidos import vende  # noqa: F401
from .test_pedidos_admin import ADMIN, estado
from .test_reembolsos import culqi_falso, culqi_r  # noqa: F401

pytestmark = pytest.mark.django_db


def adelanto_pagado(cobra, **config):
    con_adelanto(cobra, **config)
    p, c = producto(cobra), registrada()
    numero = pedir_recojo(cobra, c, p).json()["numero"]
    assert pagar_pedido(c, numero).status_code == 200
    return p, c, numero


def vencer(numero, horas=1):
    PedidoTienda.objects.sin_ambito().filter(numero=numero).update(
        adelanto_vence_en=timezone.now() - timedelta(hours=horas)
    )


class TestReembolsoPorNoRecoger:
    def test_devuelve_el_adelanto_menos_la_comision_suelta_el_stock_y_avisa(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(cobra)  # 30 % = 35.40; comisión 4 % = 1.42
        vencer(numero)
        n = len(mail.outbox)
        assert adelantos_vencidos.vencer_adelantos() == 1
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "NO_RECOGIDO"
        assert pedido.adelanto_devuelto == Decimal("33.98")
        assert pedido.adelanto_retenido == Decimal("1.42")
        # Culqi devolvió SOLO lo que corresponde (en céntimos), con clave de idempotencia
        assert culqi_r.reembolsos[0]["amount"] == 3398
        reembolso = ReembolsoPedido.objects.sin_ambito().get(pedido=pedido)
        assert reembolso.estado == "APROBADO" and reembolso.motivo_tipo == "NO_RECOGIDO"
        # el stock vuelve a estar disponible
        assert (
            not ReservaStock.objects.sin_ambito()
            .filter(pedido=pedido, liberada_en__isnull=True)
            .exists()
        )
        # la devolución sale de la cuenta donde entró el adelanto
        egreso = MovimientoCaja.objects.sin_ambito().get(
            origen_tipo=Origen.ADELANTO_TIENDA, tipo="EGRESO"
        )
        assert egreso.monto == Decimal("33.98")
        # el cliente es avisado
        assert len(mail.outbox) == n + 1 and "no se recogió" in mail.outbox[-1].subject
        assert "33.98" in mail.outbox[-1].body
        assert (
            AvisoPedido.objects.sin_ambito()
            .filter(pedido=pedido, evento="PEDIDO_NO_RECOGIDO", canal="CORREO", estado="ENVIADO")
            .exists()
        )

    def test_se_resuelve_una_sola_vez(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(cobra)
        vencer(numero)
        assert adelantos_vencidos.vencer_adelantos() == 1
        assert adelantos_vencidos.vencer_adelantos() == 0
        assert len(culqi_r.reembolsos) == 1

    def test_no_toca_lo_que_aun_no_vence_ni_lo_ya_entregado(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(cobra)
        assert adelantos_vencidos.vencer_adelantos() == 0  # le quedan días
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "ADELANTO_PAGADO" and not culqi_r.reembolsos

    def test_con_penalidad_total_no_se_devuelve_nada(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(
            cobra, adelanto_si_no_recoge="PENALIDAD", adelanto_penalidad_pct=Decimal("100")
        )
        vencer(numero)
        assert adelantos_vencidos.vencer_adelantos() == 1
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "NO_RECOGIDO"
        assert pedido.adelanto_devuelto == 0 and pedido.adelanto_retenido == Decimal("35.40")
        assert not culqi_r.reembolsos  # Culqi no devuelve nada
        assert not MovimientoCaja.objects.sin_ambito().filter(tipo="EGRESO").exists()
        assert (
            not ReservaStock.objects.sin_ambito()
            .filter(pedido=pedido, liberada_en__isnull=True)
            .exists()
        )
        assert "no se devuelve" in mail.outbox[-1].body

    def test_con_penalidad_parcial_devuelve_el_resto(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(
            cobra, adelanto_si_no_recoge="PENALIDAD", adelanto_penalidad_pct=Decimal("50")
        )
        vencer(numero)
        adelantos_vencidos.vencer_adelantos()
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.adelanto_devuelto == Decimal("17.70") and pedido.adelanto_retenido == Decimal(
            "17.70"
        )
        assert culqi_r.reembolsos[0]["amount"] == 1770

    def test_lo_acordado_al_pagar_manda_aunque_el_negocio_cambie_la_regla(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(cobra)  # acordó: devolver menos comisión
        con_adelanto(
            cobra, adelanto_si_no_recoge="PENALIDAD", adelanto_penalidad_pct=Decimal("100")
        )
        vencer(numero)
        adelantos_vencidos.vencer_adelantos()
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.adelanto_devuelto == Decimal("33.98")  # y no 0

    def test_si_culqi_cae_el_reembolso_queda_pendiente_y_se_reintenta(self, cobra, culqi_r):
        from apps.tienda import reembolsos

        p, c, numero = adelanto_pagado(cobra)
        vencer(numero)
        culqi_r.modo_reembolso = "cae"
        adelantos_vencidos.vencer_adelantos()
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "REEMBOLSO_PENDIENTE"  # el stock ya se soltó; falta el dinero
        assert not MovimientoCaja.objects.sin_ambito().filter(tipo="EGRESO").exists()
        culqi_r.modo_reembolso = "aprueba"  # Culqi vuelve
        assert reembolsos.reintentar_pendientes() == 1
        pedido.refresh_from_db()
        assert pedido.estado == "NO_RECOGIDO" and pedido.adelanto_devuelto == Decimal("33.98")
        assert MovimientoCaja.objects.sin_ambito().filter(tipo="EGRESO").count() == 1


class TestReembolsoManual:
    def test_el_negocio_puede_devolver_todo_el_adelanto_a_pedido(self, cobra, culqi_r):
        from django.contrib.auth import get_user_model

        from apps.tienda import reembolsos

        p, c, numero = adelanto_pagado(cobra)
        r = reembolsos.reembolsar(
            cobra.org.pk,
            numero,
            motivo_tipo=ReembolsoPedido.Motivo.SOLICITUD_CLIENTE,
            motivo="Ya no lo quiere",
            usuario=get_user_model().objects.get(username="admin"),
        )
        assert r.estado == "APROBADO" and r.monto == Decimal("35.40")
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "REEMBOLSADO"
        assert culqi_r.reembolsos[0]["amount"] == 3540
        assert MovimientoCaja.objects.sin_ambito().filter(tipo="EGRESO").count() == 1
        assert (
            not ReservaStock.objects.sin_ambito()
            .filter(pedido=pedido, liberada_en__isnull=True)
            .exists()
        )


class TestRecordatorio:
    def test_avisa_una_sola_vez_cuando_falta_un_dia_o_menos(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(cobra)
        assert adelantos_vencidos.recordar_adelantos() == 0  # faltan 5 días
        PedidoTienda.objects.sin_ambito().filter(numero=numero).update(
            adelanto_vence_en=timezone.now() + timedelta(hours=10)
        )
        n = len(mail.outbox)
        assert adelantos_vencidos.recordar_adelantos() == 1
        assert len(mail.outbox) == n + 1 and "Recuerda" in mail.outbox[-1].subject
        assert "82.60" in mail.outbox[-1].body
        assert adelantos_vencidos.recordar_adelantos() == 0  # ya se le recordó
        assert len(mail.outbox) == n + 1


class TestPanel:
    def test_la_pestana_de_no_recogidos_y_el_detalle(self, cobra, culqi_r):
        p, c, numero = adelanto_pagado(cobra)
        vencer(numero)
        adelantos_vencidos.vencer_adelantos()
        admin = cliente_de("admin")
        lista = admin.get(f"{ADMIN}/", {"grupo": "no_recogidos"}).json()
        assert [x["numero"] for x in lista["results"]] == [numero]
        d = admin.get(f"{ADMIN}/{numero}/").json()
        assert d["estado"] == "NO_RECOGIDO" and d["forma_pago"]["devuelto"] == "33.98"
        assert d["forma_pago"]["retenido"] == "1.42"
        assert d["acciones"]["siguientes"] == [] and d["acciones"]["cobrar_saldo"] is False
        assert estado(admin, numero, "ENTREGADO").status_code == 409
