"""Reseñas de productos: quién puede opinar, publicación, moderación y correo de petición."""

# ruff: noqa: F811

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.mantenimiento.models import Producto
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import resenas
from apps.tienda.models import (
    AvisoPedido,
    ConfiguracionResenas,
    CuentaCliente,
    HistorialPedido,
    PedidoTienda,
    ResenaProducto,
)

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import contexto, vende  # noqa: F401
from .test_pedidos_admin import estado, hacer_pedido

pytestmark = pytest.mark.django_db

PRODUCTOS = "/api/v1/tienda/productos"
ADMIN_RESENAS = "/api/v1/tienda/admin/resenas"


def slug_de(producto):
    """La dirección web del producto (se vuelve a leer: se asigna al publicarlo)."""
    slug = Producto.objects.sin_ambito().values_list("slug", flat=True).get(pk=producto.pk)
    assert slug
    return slug


def entregado(cobra, cliente, nombre="Mouse"):
    """Un producto que el cliente compró y ya recibió. Devuelve (producto, número de pedido)."""
    p, pedido = hacer_pedido(cobra, cliente, nombre)
    numero = pedido["numero"]
    assert pagar_pedido(cliente, numero).status_code == 200
    admin = cliente_de("admin")
    for nuevo in ("EN_PREPARACION", "ENVIADO", "ENTREGADO"):
        assert estado(admin, numero, nuevo).status_code == 200
    return p, numero


def opinar(cliente, producto, estrellas=5, **extra):
    return cliente.put(
        f"{PRODUCTOS}/{slug_de(producto)}/mi-resena",
        {"estrellas": estrellas, **extra},
        format="json",
    )


def publicas(producto, **params):
    return APIClient().get(f"{PRODUCTOS}/{slug_de(producto)}/resenas", params)


class TestQuienPuedeOpinar:
    def test_quien_no_recibio_el_producto_no_puede(self, cobra, culqi_falso):
        contexto(cobra)
        p = cobra.publicar("Teclado", precio=100, stock=5)
        c = registrada()
        d = c.get(f"{PRODUCTOS}/{slug_de(p)}/mi-resena").json()
        assert d["puede"] is False and d["mia"] is None and "recibas" in d["motivo"]
        r = opinar(c, p)
        assert r.status_code == 400 and r.json()["error"]["codigo"] == "resena_no_permitida"

    def test_un_pedido_pagado_pero_no_entregado_tampoco_cuenta(self, cobra, culqi_falso):
        c = registrada()
        p, pedido = hacer_pedido(cobra, c, "Mouse")
        assert pagar_pedido(c, pedido["numero"]).status_code == 200
        assert opinar(c, p).status_code == 400

    def test_quien_lo_recibio_puede_y_se_publica_sola(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        assert c.get(f"{PRODUCTOS}/{slug_de(p)}/mi-resena").json()["puede"] is True
        r = opinar(c, p, 4, titulo="Muy bueno", comentario="Llegó rápido y funciona perfecto.")
        assert r.status_code == 200, r.content
        mia = r.json()["mia"]
        assert mia["estrellas"] == 4 and mia["visible"] is True
        d = publicas(p).json()
        assert d["count"] == 1 and d["resumen"]["total"] == 1 and d["resumen"]["promedio"] == 4.0
        fila = d["results"][0]
        assert fila["autor"] == "Ana P." or fila["autor"].endswith(".")
        assert fila["comentario"] == "Llegó rápido y funciona perfecto." and fila["verificada"]
        # nunca se publica el correo ni el nombre completo
        assert "ana@ejemplo.pe" not in str(d)

    def test_editarla_no_crea_otra_y_borrarla_permite_volver_a_opinar(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        assert opinar(c, p, 5).status_code == 200
        assert opinar(c, p, 3, comentario="Después de un mes, regular.").status_code == 200
        assert ResenaProducto.objects.sin_ambito().filter(producto=p).count() == 1
        assert ResenaProducto.objects.sin_ambito().get(producto=p).editada_en is not None
        r = c.delete(f"{PRODUCTOS}/{slug_de(p)}/mi-resena")
        assert r.status_code == 200 and r.json()["mia"] is None and r.json()["puede"] is True
        assert opinar(c, p, 2).status_code == 200

    def test_otro_cliente_no_puede_opinar_de_lo_que_no_compro(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        otro = registrada("luis@ejemplo.pe")
        assert opinar(otro, p).status_code == 400

    def test_sin_sesion_no_se_puede(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        r = APIClient().put(
            f"{PRODUCTOS}/{slug_de(p)}/mi-resena",
            {"estrellas": 5},
            format="json",
            HTTP_X_REQUESTED_WITH="tienda",
        )
        assert r.status_code in (401, 403)


class TestValidacion:
    def test_estrellas_de_1_a_5(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        for malo in (0, 6, -1):
            assert opinar(c, p, malo).status_code == 400, malo

    def test_no_se_aceptan_enlaces(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        for texto in ("Compra en www.estafa.pe", "mira http://x.com/y", "escribe a oferta.com ya"):
            r = opinar(c, p, 5, comentario=texto)
            assert r.status_code == 400, texto
        assert opinar(c, p, 5, titulo="Visita mi tienda.com").status_code == 400

    def test_el_texto_se_limpia_y_tiene_limite(self, cobra, culqi_falso):
        c = registrada()
        p, _ = entregado(cobra, c)
        assert opinar(c, p, 5, comentario="x" * 1001).status_code == 400
        r = opinar(c, p, 5, comentario="  Muy    bueno \x07 todo  ")
        assert r.status_code == 200
        assert r.json()["mia"]["comentario"] == "Muy bueno todo"


class TestPublico:
    def test_resumen_y_orden(self, cobra, culqi_falso):
        a = registrada("a@ejemplo.pe")
        contexto(cobra)
        p, pedido = hacer_pedido(cobra, a, "Mouse")
        assert pagar_pedido(a, pedido["numero"]).status_code == 200
        admin = cliente_de("admin")
        for nuevo in ("EN_PREPARACION", "ENVIADO", "ENTREGADO"):
            estado(admin, pedido["numero"], nuevo)
        assert opinar(a, p, 5, comentario="Excelente").status_code == 200
        # un segundo cliente compra el mismo producto
        b = registrada("b@ejemplo.pe")
        contexto(cobra)
        from .test_pedidos import PEDIDOS, con_direccion, cuerpo

        r = b.post(PEDIDOS, cuerpo((p, 1), direccion=con_direccion(b)), format="json")
        assert r.status_code == 201, r.content
        assert pagar_pedido(b, r.json()["numero"]).status_code == 200
        for nuevo in ("EN_PREPARACION", "ENVIADO", "ENTREGADO"):
            estado(admin, r.json()["numero"], nuevo)
        assert opinar(b, p, 2, comentario="Se dañó").status_code == 200
        d = publicas(p, orden="mejores").json()
        assert d["resumen"]["total"] == 2 and d["resumen"]["promedio"] == 3.5
        assert d["resumen"]["distribucion"] == {"5": 1, "4": 0, "3": 0, "2": 1, "1": 0}
        assert [x["estrellas"] for x in d["results"]] == [5, 2]
        assert [x["estrellas"] for x in publicas(p, orden="peores").json()["results"]] == [2, 5]

    def test_un_producto_sin_reseñas_responde_vacio(self, cobra):
        contexto(cobra)
        p = cobra.publicar("Cable", precio=10, stock=5)
        d = publicas(p).json()
        assert d["count"] == 0 and d["resumen"]["promedio"] is None

    def test_un_producto_que_no_existe_da_404(self, cobra):
        assert APIClient().get(f"{PRODUCTOS}/no-existe/resenas").status_code == 404


class TestModeracion:
    def preparar(self, cobra):
        c = registrada()
        p, _ = entregado(cobra, c)
        assert opinar(c, p, 1, comentario="Pésimo").status_code == 200
        return c, p, ResenaProducto.objects.sin_ambito().get(producto=p)

    def test_ocultar_la_saca_del_publico_y_del_promedio(self, cobra, culqi_falso):
        c, p, r = self.preparar(cobra)
        a = cliente_de("admin")
        x = a.post(f"{ADMIN_RESENAS}/{r.pk}/ocultar/", {"motivo": "Insulta"}, format="json")
        assert x.status_code == 200 and x.json()["estado"] == "OCULTA"
        d = publicas(p).json()
        assert d["count"] == 0 and d["resumen"]["promedio"] is None
        mia = c.get(f"{PRODUCTOS}/{slug_de(p)}/mi-resena").json()["mia"]
        assert mia["visible"] is False  # el cliente sabe que no se ve, pero no el motivo interno
        assert "Insulta" not in str(mia)

    def test_editar_una_oculta_no_la_vuelve_publica(self, cobra, culqi_falso):
        c, p, r = self.preparar(cobra)
        cliente_de("admin").post(f"{ADMIN_RESENAS}/{r.pk}/ocultar/", {}, format="json")
        assert opinar(c, p, 1, comentario="Sigo molesto").status_code == 200
        assert publicas(p).json()["count"] == 0

    def test_mostrar_la_publica_de_nuevo(self, cobra, culqi_falso):
        c, p, r = self.preparar(cobra)
        a = cliente_de("admin")
        a.post(f"{ADMIN_RESENAS}/{r.pk}/ocultar/", {}, format="json")
        a.post(f"{ADMIN_RESENAS}/{r.pk}/mostrar/", {}, format="json")
        assert publicas(p).json()["count"] == 1

    def test_responder_se_ve_en_publico_y_vacio_la_quita(self, cobra, culqi_falso):
        c, p, r = self.preparar(cobra)
        a = cliente_de("admin")
        x = a.post(
            f"{ADMIN_RESENAS}/{r.pk}/responder/",
            {"texto": "Lamentamos lo ocurrido."},
            format="json",
        )
        assert x.status_code == 200 and x.json()["respuesta"]
        assert publicas(p).json()["results"][0]["respuesta"] == "Lamentamos lo ocurrido."
        a.post(f"{ADMIN_RESENAS}/{r.pk}/responder/", {"texto": ""}, format="json")
        assert publicas(p).json()["results"][0]["respuesta"] == ""

    def test_la_respuesta_tampoco_lleva_enlaces(self, cobra, culqi_falso):
        _, _, r = self.preparar(cobra)
        x = cliente_de("admin").post(
            f"{ADMIN_RESENAS}/{r.pk}/responder/", {"texto": "ver www.algo.pe"}, format="json"
        )
        assert x.status_code == 400

    def test_el_panel_lista_filtra_y_resume(self, cobra, culqi_falso):
        _, _, r = self.preparar(cobra)
        a = cliente_de("admin")
        d = a.get(f"{ADMIN_RESENAS}/").json()
        assert (
            d["count"] == 1 and d["resumen"]["publicadas"] == 1 and d["resumen"]["promedio"] == 1.0
        )
        assert d["results"][0]["pedido"].startswith("T-")
        assert a.get(f"{ADMIN_RESENAS}/", {"estado": "OCULTA"}).json()["count"] == 0
        assert a.get(f"{ADMIN_RESENAS}/", {"estado": "sin_respuesta"}).json()["count"] == 1
        assert a.get(f"{ADMIN_RESENAS}/", {"estrellas": "5"}).json()["count"] == 0
        assert a.get(f"{ADMIN_RESENAS}/", {"q": "pésimo"}).json()["count"] == 1

    def test_sin_permiso_no_se_modera(self, cobra, culqi_falso):
        _, _, r = self.preparar(cobra)
        c = cliente_de("almacenero")
        assert c.post(f"{ADMIN_RESENAS}/{r.pk}/ocultar/", {}, format="json").status_code == 403
        assert c.get(f"{ADMIN_RESENAS}/").status_code == 403

    def test_configuracion_se_guarda(self, cobra):
        a = cliente_de("admin")
        assert a.get(f"{ADMIN_RESENAS}/configuracion/").json() == {
            "pedir_activo": False,
            "pedir_dias": 3,
        }
        x = a.patch(
            f"{ADMIN_RESENAS}/configuracion/",
            {"pedir_activo": True, "pedir_dias": 5},
            format="json",
        )
        assert x.json() == {"pedir_activo": True, "pedir_dias": 5}
        assert (
            a.patch(
                f"{ADMIN_RESENAS}/configuracion/", {"pedir_dias": 99}, format="json"
            ).status_code
            == 400
        )


class TestPedirPorCorreo:
    def activar(self, cobra, dias=3):
        contexto(cobra)
        ConfiguracionResenas.objects.sin_ambito().create(
            organizacion=cobra.org, pedir_activo=True, pedir_dias=dias
        )

    def retroceder_entrega(self, numero, dias):
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        HistorialPedido.objects.filter(pedido=pedido, estado="ENTREGADO").update(
            creado_en=timezone.now() - timedelta(days=dias)
        )

    def aceptar_ofertas(self, acepta=True):
        CuentaCliente.objects.sin_ambito().update(acepta_ofertas=acepta)

    def test_pide_la_resena_a_quien_acepto_comunicaciones_una_sola_vez(self, cobra, culqi_falso):
        c = registrada()
        p, numero = entregado(cobra, c)
        self.activar(cobra)
        self.aceptar_ofertas()
        self.retroceder_entrega(numero, 4)
        n = len(mail.outbox)
        assert resenas.pedir_resenas() == 1
        assert len(mail.outbox) == n + 1
        cuerpo = mail.outbox[-1].body
        assert f"/producto/{slug_de(p)}#resenas" in cuerpo and "/cuenta/baja?t=" in cuerpo
        assert AvisoPedido.objects.sin_ambito().filter(evento="PEDIDO_RESENA").exists()
        assert resenas.pedir_resenas() == 0  # no se repite
        assert len(mail.outbox) == n + 1

    def test_no_pide_si_no_acepto_si_es_muy_pronto_o_esta_apagado(self, cobra, culqi_falso):
        c = registrada()
        _, numero = entregado(cobra, c)
        self.retroceder_entrega(numero, 4)
        assert resenas.pedir_resenas() == 0  # apagado
        self.activar(cobra)
        self.aceptar_ofertas(False)
        assert resenas.pedir_resenas() == 0  # no aceptó comunicaciones
        self.aceptar_ofertas()
        self.retroceder_entrega(numero, 1)
        assert resenas.pedir_resenas() == 0  # todavía es pronto
        self.retroceder_entrega(numero, 40)
        assert resenas.pedir_resenas() == 0  # ya pasó demasiado

    def test_no_pide_lo_que_ya_opino(self, cobra, culqi_falso):
        c = registrada()
        p, numero = entregado(cobra, c)
        assert opinar(c, p, 5).status_code == 200
        self.activar(cobra)
        self.aceptar_ofertas()
        self.retroceder_entrega(numero, 4)
        n = len(mail.outbox)
        assert resenas.pedir_resenas() == 0
        assert len(mail.outbox) == n
