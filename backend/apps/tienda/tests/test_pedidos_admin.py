"""Panel: lista, detalle y atención de los pedidos de la tienda."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import AuditoriaEvento
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import pagar
from apps.tienda.models import HistorialPedido, PedidoTienda, ReservaStock

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import PEDIDOS, con_direccion, contexto, cuerpo, vende  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/pedidos"
ENVIOS = "/api/v1/tienda/admin/envios/"


def hacer_pedido(vende, cliente, nombre, *, modalidad="ENVIO", cantidad=1):
    """Crea un pedido de un producto nuevo para ese cliente y devuelve (producto, respuesta)."""
    contexto(vende)
    p = vende.publicar(nombre, precio=100, stock=10, peso_kg=Decimal("0.5"))
    contexto(vende)
    if modalidad == "ENVIO":
        extra = {"direccion": con_direccion(cliente)}
    else:
        punto = cliente_de("admin").get(ENVIOS).json()["puntos"][0]["id"]
        extra = {"punto": punto}
    r = cliente.post(PEDIDOS, cuerpo((p, cantidad), modalidad=modalidad, **extra), format="json")
    assert r.status_code == 201, r.content
    return p, r.json()


def pagado(cobra, cliente, nombre="Mouse", **kw):
    _, pedido = hacer_pedido(cobra, cliente, nombre, **kw)
    assert pagar_pedido(cliente, pedido["numero"]).status_code == 200
    return pedido["numero"]


def estado(admin, numero, nuevo, **extra):
    return admin.post(f"{ADMIN}/{numero}/estado/", {"estado": nuevo, **extra}, format="json")


class TestPermisos:
    def test_ver_y_gestionar(self, cobra, culqi_falso, nuevo_usuario):
        e = cobra.e
        nuevo_usuario(cobra.org, "cajero", [e.e1], [("CAJERO", e.e1)])
        numero = pagado(cobra, registrada())
        for quien in ("admin", "vendedor", "almacenero"):
            c = cliente_de(quien)
            assert c.get(ADMIN + "/").status_code == 200, quien
            assert estado(c, numero, "EN_PREPARACION").status_code in (200, 409), quien
        caj = cliente_de("cajero")
        assert caj.get(ADMIN + "/").status_code == 403
        assert caj.get(f"{ADMIN}/{numero}/").status_code == 403
        assert estado(caj, numero, "ENTREGADO").status_code == 403
        assert APIClient().get(ADMIN + "/").status_code == 401

    def test_los_permisos_existen_y_el_menu_los_usa(self, tienda):
        from apps.seguridad.permisos_catalogo import CODIGOS, MODULOS

        assert {"TIENDA.PEDIDOS.VER", "TIENDA.PEDIDOS.GESTIONAR"} <= set(CODIGOS)
        tienda_menu = next(m for m in MODULOS if m.codigo == "tienda")
        pedidos = next(h for h in tienda_menu.hijos if h.codigo == "tienda-pedidos")
        assert pedidos.permiso_ver == "TIENDA.PEDIDOS.VER"

    def test_otra_organizacion_no_ve_estos_pedidos(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada())
        otra = cliente_de("otra_org")
        assert otra.get(ADMIN + "/").json()["count"] == 0
        assert otra.get(f"{ADMIN}/{numero}/").status_code == 404
        assert estado(otra, numero, "EN_PREPARACION").status_code == 404


class TestLista:
    @pytest.fixture
    def surtido(self, cobra, culqi_falso):
        ana = registrada("ana@ejemplo.pe")
        luis = registrada("luis@ejemplo.pe")
        a = pagado(cobra, ana, "Mouse A")  # T-000001 pagado, envío
        _, pendiente = hacer_pedido(cobra, luis, "Mouse B")  # T-000002 sin pagar
        r = pagado(cobra, luis, "Mouse C", modalidad="RECOJO")  # T-000003 pagado, recojo
        return cobra, a, pendiente["numero"], r

    def test_pestanas_y_filtros(self, surtido):
        _, a, pendiente, recojo = surtido
        admin = cliente_de("admin")
        todo = admin.get(ADMIN + "/").json()
        assert todo["count"] == 3 and [f["numero"] for f in todo["results"]] == [
            recojo,
            pendiente,
            a,
        ]
        por_atender = admin.get(ADMIN + "/?grupo=por_atender").json()
        assert {f["numero"] for f in por_atender["results"]} == {a, recojo}
        assert admin.get(ADMIN + "/?grupo=sin_pagar").json()["count"] == 1
        assert admin.get(ADMIN + "/?estado=PENDIENTE_PAGO,CANCELADO").json()["count"] == 1
        assert admin.get(ADMIN + "/?modalidad=RECOJO").json()["count"] == 1
        assert admin.get(ADMIN + "/?estado=NOEXISTE").json()["count"] == 3  # se ignora

    def test_busqueda_por_numero_correo_y_nombre(self, surtido):
        admin = cliente_de("admin")
        assert admin.get(ADMIN + "/?q=T-000002").json()["count"] == 1
        assert admin.get(ADMIN + "/?q=ana@ejemplo").json()["count"] == 1
        assert admin.get(ADMIN + "/?q=luis@").json()["count"] == 2
        assert admin.get(ADMIN + "/?q=nadie").json()["count"] == 0

    def test_fechas_y_paginacion(self, surtido):
        admin = cliente_de("admin")
        hoy = timezone.localdate()
        assert admin.get(f"{ADMIN}/?desde={hoy}&hasta={hoy}").json()["count"] == 3
        ayer = hoy - timedelta(days=1)
        assert admin.get(f"{ADMIN}/?hasta={ayer}").json()["count"] == 0
        assert admin.get(ADMIN + "/?desde=mañana").status_code == 400
        pagina = admin.get(ADMIN + "/?page_size=2&page=2").json()
        assert pagina["count"] == 3 and pagina["paginas"] == 2 and len(pagina["results"]) == 1

    def test_requieren_atencion_y_resumen(self, surtido):
        _, a, _, _ = surtido
        PedidoTienda.objects.sin_ambito().filter(numero=a).update(
            estado="PAGADO_SIN_COMPROBANTE", motivo_atencion="Falta la serie"
        )
        admin = cliente_de("admin")
        r = admin.get(ADMIN + "/?requiere_atencion=1").json()
        assert [f["numero"] for f in r["results"]] == [a]
        assert r["results"][0]["motivo_atencion"] == "Falta la serie"
        res = admin.get(ADMIN + "/resumen/").json()
        assert res["requieren_atencion"] == 1
        assert res["por_estado"]["PAGADO"] == 1 and res["por_estado"]["PENDIENTE_PAGO"] == 1
        assert res["grupos"]["por_atender"] == 1 and res["grupos"]["atencion"] == 1


class TestDetalle:
    def test_trae_todo_lo_que_el_negocio_necesita(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"))
        d = cliente_de("admin").get(f"{ADMIN}/{numero}/").json()
        assert d["cliente"]["correo"] == "ana@ejemplo.pe" and d["cliente"]["correo_verificado"]
        assert d["comprobante"]["tipo"] == "03" and d["importes"]["igv_exonerado"] is False
        assert d["lineas"][0]["empresa"] and d["lineas"][0]["almacen"]
        assert d["comprobantes"][0]["numero"].startswith("B") and d["comprobantes"][0]["id"]
        assert d["venta_id"] and d["pago"]["medio"] == "tarjeta"
        assert d["pago"]["cargo"].startswith("chr_test_")
        assert d["intentos"][0]["estado"] == "APROBADO"
        assert d["acciones"]["siguientes"] == [
            {"estado": "EN_PREPARACION", "texto": "En preparación"}
        ]
        assert d["entrega"]["direccion"] == "Av. Sol 100"

    def test_pedido_inexistente(self, cobra):
        assert cliente_de("admin").get(f"{ADMIN}/T-999999/").status_code == 404


class TestEstados:
    def test_envio_a_domicilio_de_punta_a_punta_con_aviso(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"))
        admin = cliente_de("admin")
        assert estado(admin, numero, "EN_PREPARACION", nota="Lo armamos hoy").status_code == 200
        n = len(mail.outbox)
        r = estado(admin, numero, "ENVIADO", seguimiento="Olva 123456", nota="Sale mañana")
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["estado"] == "ENVIADO" and d["seguimiento"] == "Olva 123456"
        assert d["acciones"]["siguientes"][0]["estado"] == "ENTREGADO"
        assert len(mail.outbox) == n + 1
        correo = mail.outbox[-1]
        assert "ana@ejemplo.pe" in correo.to and numero in correo.subject
        assert "Olva 123456" in correo.body and "Sale mañana" in correo.body
        assert "Av. Sol 100" in correo.body
        assert estado(admin, numero, "ENTREGADO").json()["estado"] == "ENTREGADO"
        # historial con quién y cuándo
        h = admin.get(f"{ADMIN}/{numero}/").json()["historial"]
        assert [x["estado"] for x in h] == ["EN_PREPARACION", "ENVIADO", "ENTREGADO"]
        assert h[1]["texto"] == "Olva 123456 · Sale mañana" and h[0]["usuario"]
        assert AuditoriaEvento.objects.filter(accion="tienda.pedido_estado").count() == 3

    def test_recojo_en_tienda_avisa_con_el_horario(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada("ana@ejemplo.pe"), "Mouse R", modalidad="RECOJO")
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        n = len(mail.outbox)
        r = estado(admin, numero, "LISTO_PARA_RECOJO")
        assert r.status_code == 200 and len(mail.outbox) == n + 1
        assert "Centro" in mail.outbox[-1].body and "Av. 1" in mail.outbox[-1].body
        assert estado(admin, numero, "ENTREGADO").status_code == 200

    @pytest.mark.parametrize(
        ("modalidad", "paso", "malo"),
        [
            ("ENVIO", None, "ENTREGADO"),  # no se salta la preparación
            ("ENVIO", "EN_PREPARACION", "LISTO_PARA_RECOJO"),  # un envío no se «recoge»
            ("RECOJO", "EN_PREPARACION", "ENVIADO"),  # un recojo no «sale»
            ("ENVIO", "EN_PREPARACION", "PAGADO"),  # no se retrocede
            ("ENVIO", None, "CANCELADO"),  # lo pagado no se cancela aquí
            ("ENVIO", None, "INVENTADO"),
        ],
    )
    def test_transiciones_invalidas(self, cobra, culqi_falso, modalidad, paso, malo):
        numero = pagado(cobra, registrada(), "Mouse X", modalidad=modalidad)
        admin = cliente_de("admin")
        if paso:
            assert estado(admin, numero, paso).status_code == 200
        antes = len(mail.outbox)
        assert estado(admin, numero, malo).status_code == 409
        assert PedidoTienda.objects.sin_ambito().get(numero=numero).estado != malo
        assert len(mail.outbox) == antes

    def test_cancelar_un_pedido_sin_pagar_libera_el_stock(self, vende):
        cliente = registrada()
        _, p = hacer_pedido(vende, cliente, "Mouse P")
        assert ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()
        r = estado(cliente_de("admin"), p["numero"], "CANCELADO", nota="Pidió cancelar")
        assert r.status_code == 200 and r.json()["estado"] == "CANCELADO"
        assert not ReservaStock.objects.sin_ambito().filter(liberada_en__isnull=True).exists()

    def test_no_cancela_si_el_cliente_esta_pagando(self, cobra, culqi_falso):
        from apps.tienda.models import IntentoPago

        cliente = registrada()
        _, p = hacer_pedido(cobra, cliente, "Mouse Q")
        pedido = PedidoTienda.objects.sin_ambito().get(numero=p["numero"])
        IntentoPago.objects.sin_ambito().create(
            organizacion=cobra.org, pedido=pedido, monto=pedido.total
        )
        assert estado(cliente_de("admin"), p["numero"], "CANCELADO").status_code == 409
        assert PedidoTienda.objects.sin_ambito().get().estado == "PENDIENTE_PAGO"

    def test_textos_demasiado_largos(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada())
        admin = cliente_de("admin")
        assert estado(admin, numero, "EN_PREPARACION", seguimiento="x" * 201).status_code == 400
        assert estado(admin, numero, "EN_PREPARACION", nota="x" * 501).status_code == 400


class TestNotas:
    def test_agrega_una_nota_interna_al_historial(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada())
        admin = cliente_de("admin")
        r = admin.post(
            f"{ADMIN}/{numero}/nota/", {"texto": "  Cliente pidió factura   "}, format="json"
        )
        assert r.status_code == 200
        h = r.json()["historial"]
        assert h[-1]["tipo"] == "NOTA" and h[-1]["texto"] == "Cliente pidió factura"
        assert PedidoTienda.objects.sin_ambito().get().estado == "PAGADO"
        vacia = admin.post(f"{ADMIN}/{numero}/nota/", {"texto": "   "}, format="json")
        assert vacia.status_code == 400
        assert HistorialPedido.objects.count() == 1


class TestReintentarComprobante:
    def test_repara_un_pedido_cobrado_sin_comprobante(self, cobra, culqi_falso, monkeypatch):
        original = pagar._registrar_venta
        fallos = {"n": 1}

        def falla_una_vez(*args, **kwargs):
            if fallos["n"]:
                fallos["n"] -= 1
                raise RuntimeError("serie sin configurar")
            return original(*args, **kwargs)

        monkeypatch.setattr(pagar, "_registrar_venta", falla_una_vez)
        cliente = registrada()
        _, p = hacer_pedido(cobra, cliente, "Mouse F")
        assert pagar_pedido(cliente, p["numero"]).json()["requiere_atencion"] is True
        admin = cliente_de("admin")
        d = admin.get(f"{ADMIN}/{p['numero']}/").json()
        assert d["estado"] == "PAGADO_SIN_COMPROBANTE" and d["acciones"]["reintentar_comprobante"]
        assert d["motivo_atencion"]
        r = admin.post(f"{ADMIN}/{p['numero']}/reintentar-comprobante/", {}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "PAGADO" and r.json()["comprobantes"]
        assert len(culqi_falso.cobros) == 1  # nunca se vuelve a cobrar
        assert r.json()["historial"][-1]["tipo"] == "NOTA"

    def test_solo_aplica_a_pedidos_sin_comprobante(self, cobra, culqi_falso):
        numero = pagado(cobra, registrada())
        r = cliente_de("admin").post(f"{ADMIN}/{numero}/reintentar-comprobante/", {}, format="json")
        assert r.status_code == 409
