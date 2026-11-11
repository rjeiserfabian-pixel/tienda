"""Reembolsos de pedidos pagados: anular, devolver con nota de crédito y devolver el dinero."""

# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.auditoria.models import AuditoriaEvento
from apps.caja.servicios import saldo_de
from apps.inventario.models import SaldoStock
from apps.inventario.series import EstadoSerie
from apps.mantenimiento.models import CuentaFinanciera, SerieComprobante, TipoComprobante
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import culqi, deuda_web, reembolsos
from apps.tienda.models import (
    HistorialPedido,
    LineaPedido,
    PedidoTienda,
    ReembolsoPedido,
    ReservaStock,
)
from apps.ventas import liquidacion_interna
from apps.ventas.cuentas_web import CUENTA_COBRA, CUENTA_PUENTE, LOCAL_WEB
from apps.ventas.models import ComprobanteVenta, LineaVenta, NotaCredito, Venta

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_deuda_web import mixto_pagado  # noqa: F401
from .test_pagar import (  # noqa: F401
    SK,
    CulqiFalso,
    cobra,
    pagar_pedido,
)
from .test_pedidos import contexto, vende  # noqa: F401
from .test_pedidos_admin import ADMIN, estado, hacer_pedido, pagado
from .test_series import ingresar, laptop, pedir, serie

pytestmark = pytest.mark.django_db


class CulqiConReembolsos(CulqiFalso):
    """Culqi simulado que también devuelve dinero (nunca sale a internet)."""

    def __init__(self):
        super().__init__()
        self.modo_reembolso = "aprueba"  # aprueba | rechaza | cae | corta
        self.reembolsos: list[dict] = []
        self.claves: list[str] = []

    def __call__(self, metodo, ruta, llave, cuerpo=None, idempotencia=""):
        if metodo == "POST" and ruta == "refunds":
            assert llave == SK
            if self.modo_reembolso == "cae":
                raise culqi.ErrorCulqi("No pudimos conectar con Culqi.")
            if self.modo_reembolso == "rechaza":
                return culqi.RespuestaCulqi(
                    400, {"object": "error", "merchant_message": "El cargo ya no se puede devolver"}
                )
            cargo = self.guardados[cuerpo["charge_id"]]
            self.reembolsos.append(cuerpo)
            self.claves.append(idempotencia)
            cargo["amount_refunded"] = cargo.get("amount_refunded", 0) + cuerpo["amount"]
            if self.modo_reembolso == "corta":
                # Culqi lo procesó pero la respuesta nunca llegó.
                self.modo_reembolso = "aprueba"
                raise culqi.ErrorCulqi("Culqi tardó demasiado en responder.")
            return culqi.RespuestaCulqi(
                201,
                {
                    "id": f"ref_test_{len(self.reembolsos)}",
                    "object": "refund",
                    "amount": cuerpo["amount"],
                },
            )
        return super().__call__(metodo, ruta, llave, cuerpo, idempotencia)


@pytest.fixture
def culqi_r(monkeypatch):
    falso = CulqiConReembolsos()
    monkeypatch.setattr(culqi, "llamar", falso)
    return falso


@pytest.fixture
def culqi_falso(culqi_r):
    """Las fixtures de otros módulos de prueba piden ``culqi_falso``: es este mismo Culqi."""
    return culqi_r


@pytest.fixture
def jefe(cobra, nuevo_usuario):  # noqa: F811
    """El reembolso es un permiso crítico: lo trae el superadministrador."""
    nuevo_usuario(cobra.org, "jefe", [cobra.e.e1], [("SUPERADMIN", None)])
    return cliente_de("jefe")


def url(numero, accion=""):
    return f"{ADMIN}/{numero}/reembolso/{accion}"


def datos(**extra):
    return {"motivo_tipo": "SOLICITUD_CLIENTE", "motivo": "El cliente se arrepintió", **extra}


def series_de_nota(tienda):
    """La serie de las notas de crédito (BC01 sobre boleta) para las dos empresas."""
    tipo = TipoComprobante.objects.sin_ambito().get(organizacion=tienda.org, codigo="07")
    for empresa in (tienda.e.e1, tienda.e.e2):
        SerieComprobante.objects.sin_ambito().get_or_create(
            empresa=empresa,
            tipo_comprobante=tipo,
            serie="BC01",
            defaults={"es_electronica": True},
        )


def entregado(cobra, cliente, nombre="Mouse", cantidad=1):
    """Un pedido pagado y entregado."""
    numero = pagado(cobra, cliente, nombre, cantidad=cantidad)
    admin = cliente_de("admin")
    for nuevo in ("EN_PREPARACION", "ENVIADO", "ENTREGADO"):
        estado(admin, numero, nuevo)
    return numero


def pedido(numero) -> PedidoTienda:
    return PedidoTienda.objects.sin_ambito().get(numero=numero)


def saldo_culqi(cobra, empresa=None, nombre=CUENTA_COBRA):
    contexto(cobra)
    cuenta = CuentaFinanciera.objects.sin_ambito().get(empresa=empresa or cobra.e.e1, nombre=nombre)
    return saldo_de(cuenta)


class TestAnulacionAntesDeEntregar:
    def test_anula_la_venta_devuelve_el_stock_y_el_dinero_exacto(self, cobra, culqi_r, jefe):
        cliente = registrada()
        numero = pagado(cobra, cliente, cantidad=2)
        total = pedido(numero).total
        p = LineaPedido.objects.sin_ambito().get(pedido__numero=numero, es_envio=False).producto
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 8
        assert saldo_culqi(cobra) == total
        n = len(mail.outbox)

        r = jefe.post(url(numero), datos(), format="json")

        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "REEMBOLSADO" and d["monto_reembolsado"] == format(total, "f")
        # Culqi recibió el monto exacto en céntimos, el motivo y una clave estable
        (pedida,) = culqi_r.reembolsos
        assert pedida["amount"] == int(total * 100) and pedida["reason"] == "solicitud_comprador"
        assert pedida["charge_id"] == "chr_test_1" and culqi_r.claves[0].startswith("rf-T-000001-1")
        # lo interno quedó deshecho: comprobante anulado, stock y cobro revertidos
        assert ComprobanteVenta.objects.sin_ambito().get().estado == "ANULADO"
        assert Venta.objects.sin_ambito().get().estado == "ANULADO"
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 10
        assert saldo_culqi(cobra) == 0
        r = ReembolsoPedido.objects.sin_ambito().get()
        assert (
            r.estado == "APROBADO"
            and r.tipo == "ANULACION"
            and r.culqi_reembolso_id == "ref_test_1"
        )
        assert r.venta_anulada and r.usuario_nombre and r.monto == total
        # historial, auditoría y correo al cliente sin datos de tarjeta
        assert any(h["estado"] == "REEMBOLSADO" for h in d["historial"])
        assert AuditoriaEvento.objects.filter(accion="tienda.reembolso_aprobado").exists()
        assert len(mail.outbox) == n + 1 and "Te devolvimos" in mail.outbox[-1].body
        assert "tarjeta" not in mail.outbox[-1].body.lower().replace("tu banco", "")

    def test_se_puede_anular_en_cualquier_paso_hasta_enviado(self, cobra, culqi_r, jefe):
        for i, paso in enumerate(["EN_PREPARACION", "ENVIADO"], start=1):
            cliente = registrada(f"cli{i}@ejemplo.pe")
            numero = pagado(cobra, cliente, f"Mouse {i}")
            admin = cliente_de("admin")
            estado(admin, numero, "EN_PREPARACION")
            if paso == "ENVIADO":
                estado(admin, numero, "ENVIADO")
            assert jefe.post(url(numero), datos(), format="json").json()["estado"] == "REEMBOLSADO"

    def test_el_plan_explica_que_pasara_sin_cambiar_nada(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        r = jefe.get(url(numero, "plan/")).json()
        assert r["ruta"] == "ANULACION" and r["monto"] == format(pedido(numero).total, "f")
        assert any("anula" in p for p in r["pasos"]) and r["permite_parcial"] is False
        assert culqi_r.reembolsos == [] and pedido(numero).estado == "PAGADO"

    def test_con_series_cambiadas_por_el_almacen_quedan_las_dos_en_stock(
        self, cobra, culqi_r, jefe
    ):
        p = laptop(cobra)
        ingresar(cobra, p, ["S-VIEJA"], dias=50)
        ingresar(cobra, p, ["S-OTRA"], dias=5)
        c, ped = pedir(cobra, p)
        assert pagar_pedido(c, ped["numero"]).status_code == 200
        numero = ped["numero"]
        linea = LineaPedido.objects.sin_ambito().get(pedido__numero=numero, producto=p).pk
        admin = cliente_de("admin")
        cambio = admin.post(
            f"{ADMIN}/{numero}/serie/",
            {"linea": linea, "anterior": "S-VIEJA", "nueva": "S-OTRA", "motivo": "Estaba dañada"},
            format="json",
        )
        assert cambio.status_code == 200
        assert jefe.post(url(numero), datos(), format="json").json()["estado"] == "REEMBOLSADO"
        assert serie(p, "S-VIEJA").estado == EstadoSerie.EN_STOCK
        assert serie(p, "S-OTRA").estado == EstadoSerie.EN_STOCK
        assert LineaPedido.objects.sin_ambito().get(pk=linea).series_fisicas == []


class TestPedidoMixto:
    def test_revierte_la_deuda_antes_de_liquidar(self, jefe, mixto_pagado, culqi_r):
        cobra, deuda, banco = mixto_pagado
        total = pedido("T-000001").total
        r = jefe.post(url("T-000001"), datos(), format="json").json()
        assert r["estado"] == "REEMBOLSADO"
        assert culqi_r.reembolsos[0]["amount"] == int(total * 100)
        assert {c.estado for c in ComprobanteVenta.objects.sin_ambito().all()} == {"ANULADO"}
        contexto(cobra)
        deuda.refresh_from_db()
        assert deuda_web.estado_de(deuda)["estado"] == deuda_web.ANULADA
        assert liquidacion_interna.pendientes(cobra.org.pk) == []
        # ni la cuenta puente ni la de Culqi quedan con saldo virtual
        assert saldo_culqi(cobra, cobra.e.e2, CUENTA_PUENTE) == 0
        assert saldo_culqi(cobra) == 0

    def test_con_la_deuda_ya_liquidada_queda_una_devolucion_por_liquidar(
        self, jefe, mixto_pagado, culqi_r
    ):
        cobra, deuda, banco = mixto_pagado
        e = cobra.e
        liquidacion_interna.liquidar(
            pagadora=e.e1, receptora=e.e2, local=LOCAL_WEB, cuenta_destino=banco
        )
        r = jefe.post(url("T-000001"), datos(), format="json")
        assert r.status_code == 200, r.content
        contexto(cobra)
        deuda.refresh_from_db()
        assert deuda_web.estado_de(deuda)["estado"] == deuda_web.REVERSA_PENDIENTE
        assert r.json()["deudas_entre_empresas"][0]["estado"] == "REVERSA_PENDIENTE"
        # la otra empresa le debe ahora a la que cobró: queda en «Liquidación entre empresas»
        (grupo,) = liquidacion_interna.pendientes(cobra.org.pk)
        assert (grupo.pagadora.pk, grupo.receptora.pk) == (e.e2.pk, e.e1.pk)
        assert grupo.monto == deuda.monto and len(culqi_r.reembolsos) == 1


class TestDespuesDeEntregar:
    def test_total_con_nota_de_credito_reingresa_el_stock_y_devuelve_el_dinero(
        self, cobra, culqi_r, jefe
    ):
        series_de_nota(cobra)
        cliente = registrada()
        numero = entregado(cobra, cliente, cantidad=2)
        p = LineaPedido.objects.sin_ambito().get(pedido__numero=numero, es_envio=False).producto
        total = pedido(numero).total
        assert jefe.get(url(numero, "plan/")).json()["ruta"] == "NOTA_CREDITO"

        r = jefe.post(url(numero), datos(reingresa_stock=True), format="json")

        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "REEMBOLSADO"
        notas = NotaCredito.objects.sin_ambito().all()
        assert notas.count() == 1 and notas[0].total == total
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 10
        assert culqi_r.reembolsos[0]["amount"] == int(total * 100)
        rb = ReembolsoPedido.objects.sin_ambito().get()
        assert rb.tipo == "NOTA_CREDITO" and rb.notas_credito == [notas[0].pk]
        assert saldo_culqi(cobra) == 0  # el reembolso de la nota salió de la cuenta Culqi

    def test_sin_confirmar_que_el_equipo_volvio_no_reingresa_el_stock(self, cobra, culqi_r, jefe):
        series_de_nota(cobra)
        numero = entregado(cobra, registrada())
        p = LineaPedido.objects.sin_ambito().get(pedido__numero=numero, es_envio=False).producto
        jefe.post(url(numero), datos(reingresa_stock=False), format="json")
        assert SaldoStock.objects.sin_ambito().get(producto=p).cantidad == 9
        assert pedido(numero).estado == "REEMBOLSADO"

    def test_devolucion_parcial_y_luego_el_resto(self, cobra, culqi_r, jefe):
        series_de_nota(cobra)
        numero = entregado(cobra, registrada(), cantidad=2)
        total = pedido(numero).total
        linea = LineaPedido.objects.sin_ambito().get(pedido__numero=numero, es_envio=False)
        assert jefe.get(url(numero, "plan/")).json()["permite_parcial"] is True

        r = jefe.post(
            url(numero), datos(lineas=[{"linea": linea.pk, "cantidad": "1"}]), format="json"
        )

        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "REEMBOLSADO_PARCIAL"
        primera = culqi_r.reembolsos[0]["amount"]
        assert primera == int(linea.precio_unitario * 100)  # una unidad
        assert pedido(numero).monto_reembolsado == Decimal(primera) / 100
        # lo que falta se devuelve con la devolución total: nunca más de lo cobrado
        r = jefe.post(url(numero), datos(), format="json")
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "REEMBOLSADO"
        assert pedido(numero).monto_reembolsado == total
        assert sum(x["amount"] for x in culqi_r.reembolsos) == int(total * 100)
        assert culqi_r.reembolsos[1]["charge_id"] == "chr_test_1"

    def test_un_pedido_mixto_solo_se_devuelve_completo(self, jefe, mixto_pagado, culqi_r):
        cobra, _, _ = mixto_pagado
        series_de_nota(cobra)
        admin = cliente_de("admin")
        for nuevo in ("EN_PREPARACION", "ENVIADO", "ENTREGADO"):
            estado(admin, "T-000001", nuevo)
        linea = LineaPedido.objects.sin_ambito().filter(pedido__numero="T-000001", es_envio=False)[
            0
        ]
        assert jefe.get(url("T-000001", "plan/")).json()["permite_parcial"] is False
        r = jefe.post(
            url("T-000001"), datos(lineas=[{"linea": linea.pk, "cantidad": "1"}]), format="json"
        )
        assert r.status_code == 409 and culqi_r.reembolsos == []
        assert pedido("T-000001").estado == "ENTREGADO"  # nada cambió
        r = jefe.post(url("T-000001"), datos(), format="json")
        assert r.status_code == 200 and r.json()["estado"] == "REEMBOLSADO"
        assert NotaCredito.objects.sin_ambito().count() == 2


class TestSoloDinero:
    def test_pagado_sin_comprobante_devuelve_el_cargo_y_libera_el_stock(
        self, cobra, culqi_r, jefe, monkeypatch
    ):
        from apps.ventas import servicios as ventas

        monkeypatch.setattr(
            ventas, "registrar_venta", lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        cliente = registrada()
        _, ped = hacer_pedido(cobra, cliente, "Mouse")
        assert pagar_pedido(cliente, ped["numero"]).json()["estado"] == "PAGADO_SIN_COMPROBANTE"
        numero = ped["numero"]
        assert ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()

        r = jefe.post(url(numero), datos(motivo_tipo="SIN_STOCK"), format="json")

        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "REEMBOLSADO"
        assert not ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()
        assert Venta.objects.sin_ambito().count() == 0
        assert ReembolsoPedido.objects.sin_ambito().get().tipo == "SOLO_DINERO"
        assert culqi_r.reembolsos[0]["amount"] == int(pedido(numero).total * 100)
        # el reintento automático del comprobante ya no lo toca
        from apps.tienda.tasks import reintentar_comprobantes

        assert reintentar_comprobantes() == 0

    def test_pago_fuera_de_plazo(self, cobra, culqi_r, jefe):
        from datetime import timedelta

        from django.utils import timezone

        from apps.tienda import pedidos

        cliente = registrada()
        _, ped = hacer_pedido(cobra, cliente, "Mouse")
        pe = pedido(ped["numero"])
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(minutes=1))
        assert pedidos.expirar_vencidos() == 1
        cargo = culqi_r.nuevo_cargo(int(pe.total * 100), pe.numero)
        r = APIClient().post(
            "/api/v1/tienda/pagos/webhook", {"data": {"id": cargo["id"]}}, format="json"
        )
        assert r.json()["resultado"] == "confirmado"
        assert pedido(ped["numero"]).estado == "PAGADO_FUERA_DE_PLAZO"
        r = jefe.post(
            url(ped["numero"]), datos(motivo_tipo="OTRO", motivo="Pagó tarde"), format="json"
        )
        assert r.status_code == 200 and r.json()["estado"] == "REEMBOLSADO"
        assert culqi_r.reembolsos[0]["charge_id"] == cargo["id"]


class TestSeguridadDelDinero:
    def test_dos_clics_no_devuelven_dos_veces(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        assert jefe.post(url(numero), datos(), format="json").status_code == 200
        segundo = jefe.post(url(numero), datos(), format="json")
        assert segundo.status_code == 409 and "ya se reembolsó" in str(segundo.json())
        assert len(culqi_r.reembolsos) == 1
        # repetir el cierre tampoco vuelve a pedir nada a Culqi
        rb = ReembolsoPedido.objects.sin_ambito().get()
        assert reembolsos.completar(rb.pk).estado == "APROBADO" and len(culqi_r.reembolsos) == 1
        assert jefe.post(url(numero, "reintentar/"), {}, format="json").status_code == 409

    def test_si_culqi_falla_lo_interno_queda_hecho_y_el_reintento_devuelve_el_dinero(
        self, cobra, culqi_r, jefe
    ):
        numero = pagado(cobra, registrada())
        culqi_r.modo_reembolso = "cae"

        r = jefe.post(url(numero), datos(), format="json")

        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "REEMBOLSO_PENDIENTE" and d["requiere_atencion"] is True
        assert (
            d["acciones"]["reintentar_reembolso"] is True and d["acciones"]["reembolsar"] is False
        )
        assert Venta.objects.sin_ambito().get().estado == "ANULADO"  # lo interno ya se deshizo
        rb = ReembolsoPedido.objects.sin_ambito().get()
        assert rb.estado == "SOLICITADO" and "conectar" in rb.mensaje
        assert AuditoriaEvento.objects.filter(accion="tienda.reembolso_requiere_atencion").exists()
        assert pedido(numero).monto_reembolsado == 0
        # no se puede pedir otro reembolso encima mientras tanto
        assert jefe.post(url(numero), datos(), format="json").status_code == 409
        # Culqi se recupera: la tarea periódica devuelve el dinero UNA vez
        culqi_r.modo_reembolso = "aprueba"
        assert reembolsos.reintentar_pendientes() == 1
        assert pedido(numero).estado == "REEMBOLSADO" and len(culqi_r.reembolsos) == 1
        assert reembolsos.reintentar_pendientes() == 0

    def test_el_boton_reintentar_del_panel(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        culqi_r.modo_reembolso = "rechaza"
        d = jefe.post(url(numero), datos(), format="json").json()
        assert d["estado"] == "REEMBOLSO_PENDIENTE"
        assert "ya no se puede devolver" in d["reembolsos"][0]["mensaje"]
        culqi_r.modo_reembolso = "aprueba"
        r = jefe.post(url(numero, "reintentar/"), {}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "REEMBOLSADO"

    def test_si_culqi_lo_devolvio_pero_la_respuesta_se_perdio_no_se_devuelve_otra_vez(
        self, cobra, culqi_r, jefe
    ):
        numero = pagado(cobra, registrada())
        culqi_r.modo_reembolso = "corta"
        d = jefe.post(url(numero), datos(), format="json").json()
        assert d["estado"] == "REEMBOLSO_PENDIENTE" and len(culqi_r.reembolsos) == 1
        r = jefe.post(url(numero, "reintentar/"), {}, format="json")
        assert r.json()["estado"] == "REEMBOLSADO"
        assert len(culqi_r.reembolsos) == 1  # se consultó el cargo y se dio por hecho
        assert pedido(numero).monto_reembolsado == pedido(numero).total

    def test_nunca_supera_lo_cobrado_y_si_algo_falla_nada_cambia(self, cobra, culqi_r, jefe):
        series_de_nota(cobra)
        numero = entregado(cobra, registrada())
        PedidoTienda.objects.sin_ambito().update(monto_reembolsado=Decimal("5.00"))
        r = jefe.post(url(numero), datos(), format="json")
        assert r.status_code == 409 and "supera" in str(r.json())
        assert NotaCredito.objects.sin_ambito().count() == 0  # la transacción se deshizo
        assert culqi_r.reembolsos == [] and pedido(numero).estado == "ENTREGADO"

    def test_sin_comprobantes_validos_no_se_anula_a_medias(self, cobra, culqi_r, jefe):
        numero = entregado(cobra, registrada())  # sin serie de nota de crédito: no se puede
        r = jefe.post(url(numero), datos(), format="json")
        assert r.status_code == 400 and "nota de crédito" in str(r.json())
        assert pedido(numero).estado == "ENTREGADO" and culqi_r.reembolsos == []
        assert ReembolsoPedido.objects.sin_ambito().count() == 0

    def test_un_cargo_con_reembolsos_desconocidos_no_se_toca(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        culqi_r.guardados["chr_test_1"]["amount_refunded"] = 500  # alguien devolvió en Culqi
        d = jefe.post(url(numero), datos(), format="json").json()
        assert d["estado"] == "REEMBOLSO_PENDIENTE" and culqi_r.reembolsos == []
        assert "no están en el sistema" in d["reembolsos"][0]["mensaje"]


class TestPermisosYAlcance:
    def test_solo_con_el_permiso_critico(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        for quien in ("vendedor", "almacenero"):  # el administrador sí lo trae
            c = cliente_de(quien)
            assert c.post(url(numero), datos(), format="json").status_code == 403, quien
            assert c.get(url(numero, "plan/")).status_code == 403, quien
        assert APIClient().post(url(numero), datos(), format="json").status_code == 401
        assert culqi_r.reembolsos == [] and pedido(numero).estado == "PAGADO"

    def test_el_detalle_ofrece_reembolsar_solo_cuando_corresponde(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        assert (
            cliente_de("admin").get(f"{ADMIN}/{numero}/").json()["acciones"]["reembolsar"] is True
        )
        _, ped = hacer_pedido(cobra, registrada("otro@ejemplo.pe"), "Cable")
        sin_pagar = cliente_de("admin").get(f"{ADMIN}/{ped['numero']}/").json()
        assert sin_pagar["acciones"]["reembolsar"] is False

    def test_otra_organizacion_no_ve_ni_reembolsa(self, cobra, culqi_r, jefe, nuevo_usuario):
        numero = pagado(cobra, registrada())
        nuevo_usuario(cobra.e.e.org_b, "jefe_b", [cobra.e.eb], [("SUPERADMIN", None)])
        ajeno = cliente_de("jefe_b")
        assert ajeno.post(url(numero), datos(), format="json").status_code == 404
        assert ajeno.get(url(numero, "plan/")).status_code == 404

    @pytest.mark.parametrize(
        "cambio",
        [
            {"motivo": ""},
            {"motivo": "  "},
            {"motivo_tipo": "INVENTADO"},
            {"motivo": "x" * 300},
        ],
    )
    def test_exige_el_motivo(self, cobra, culqi_r, jefe, cambio):
        numero = pagado(cobra, registrada())
        r = jefe.post(url(numero), datos(**cambio), format="json")
        assert r.status_code == 400
        assert pedido(numero).estado == "PAGADO" and culqi_r.reembolsos == []

    def test_un_pedido_sin_pagar_no_se_reembolsa(self, cobra, culqi_r, jefe):
        _, ped = hacer_pedido(cobra, registrada(), "Mouse")
        assert jefe.post(url(ped["numero"]), datos(), format="json").status_code == 409

    def test_el_cliente_ve_cuanto_se_le_devolvio_sin_datos_internos(self, cobra, culqi_r, jefe):
        cliente = registrada()
        numero = pagado(cobra, cliente)
        jefe.post(url(numero), datos(), format="json")
        d = cliente.get(f"/api/v1/tienda/pedidos/{numero}").json()
        assert d["estado"] == "REEMBOLSADO"
        assert d["reembolsos"][0]["monto"] == format(pedido(numero).total, "f")
        assert "motivo" not in str(d["reembolsos"]) and "usuario" not in str(d["reembolsos"])

    def test_un_aviso_tardio_del_cargo_no_vuelve_a_vender_un_pedido_reembolsado(
        self, cobra, culqi_r, jefe
    ):
        numero = pagado(cobra, registrada())
        jefe.post(url(numero), datos(), format="json")
        ventas_antes = Venta.objects.sin_ambito().count()
        r = APIClient().post(
            "/api/v1/tienda/pagos/webhook", {"data": {"id": "chr_test_1"}}, format="json"
        )
        assert r.json()["resultado"] == "ya_confirmado"
        assert Venta.objects.sin_ambito().count() == ventas_antes
        assert pedido(numero).estado == "REEMBOLSADO"

    def test_historial_y_lista_por_grupo(self, cobra, culqi_r, jefe):
        numero = pagado(cobra, registrada())
        jefe.post(url(numero), datos(), format="json")
        admin = cliente_de("admin")
        assert admin.get(f"{ADMIN}/?grupo=reembolsados").json()["count"] == 1
        assert HistorialPedido.objects.filter(pedido__numero=numero, estado="REEMBOLSADO").exists()
        assert LineaVenta.objects.sin_ambito().exists()
