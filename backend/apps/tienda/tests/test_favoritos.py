"""Favoritos del cliente y «avísame cuando llegue»."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.inventario.models import SaldoStock
from apps.tienda import favoritos
from apps.tienda.models import AvisoDisponibilidad, CuentaCliente, Favorito

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pedidos import contexto, vende  # noqa: F401

pytestmark = pytest.mark.django_db

FAVORITOS = "/api/v1/tienda/cuenta/favoritos"
AVISOS = "/api/v1/tienda/cuenta/avisos-stock"


def publicar(vende, nombre="Mouse", stock=5):
    contexto(vende)
    return vende.publicar(nombre, precio=100, stock=stock)


def poner(cliente, producto):
    return cliente.put(f"{FAVORITOS}/{producto.pk}", {}, format="json")


class TestFavoritos:
    def test_guardar_ver_y_quitar(self, vende):
        p, q = publicar(vende, "Mouse"), publicar(vende, "Teclado")
        c = registrada()
        assert c.get(FAVORITOS).json() == {"ids": [], "avisos": []}
        assert poner(c, p).json() == {"ids": [p.pk]}
        assert poner(c, q).json()["ids"] == [q.pk, p.pk]  # el más nuevo primero
        assert poner(c, p).json()["ids"] == [q.pk, p.pk]  # repetir no duplica
        assert Favorito.objects.sin_ambito().count() == 2
        d = c.get(FAVORITOS, {"productos": "1"}).json()
        assert [x["nombre"] for x in d["productos"]] == ["Teclado", "Mouse"]
        assert c.delete(f"{FAVORITOS}/{p.pk}").json() == {"ids": [q.pk]}
        assert c.delete(f"{FAVORITOS}/{p.pk}").json() == {"ids": [q.pk]}  # quitar de nuevo no falla

    def test_cada_cliente_ve_solo_los_suyos(self, vende):
        p = publicar(vende)
        a, b = registrada("a@ejemplo.pe"), registrada("b@ejemplo.pe")
        poner(a, p)
        assert b.get(FAVORITOS).json()["ids"] == []

    def test_sin_sesion_no_se_puede(self, vende):
        p = publicar(vende)
        r = APIClient().put(
            f"{FAVORITOS}/{p.pk}", {}, format="json", HTTP_X_REQUESTED_WITH="tienda"
        )
        assert r.status_code in (401, 403)

    def test_un_producto_que_no_existe_o_no_esta_publicado(self, vende):
        c = registrada()
        assert c.put(f"{FAVORITOS}/999999", {}, format="json").status_code == 404
        p = publicar(vende)
        from apps.mantenimiento.models import Producto

        Producto.objects.sin_ambito().filter(pk=p.pk).update(publicado_web=False)
        assert poner(c, p).status_code == 404

    def test_un_favorito_que_se_despublica_no_se_muestra(self, vende):
        p = publicar(vende)
        c = registrada()
        poner(c, p)
        from apps.mantenimiento.models import Producto

        Producto.objects.sin_ambito().filter(pk=p.pk).update(publicado_web=False)
        assert c.get(FAVORITOS, {"productos": "1"}).json()["productos"] == []

    def test_tiene_un_tope(self, vende, monkeypatch):
        monkeypatch.setattr(favoritos, "MAX_FAVORITOS", 2)
        c = registrada()
        productos = [publicar(vende, f"P{i}") for i in range(3)]
        assert poner(c, productos[0]).status_code == 200
        assert poner(c, productos[1]).status_code == 200
        assert poner(c, productos[2]).status_code == 400


def agotar(producto):
    SaldoStock.objects.sin_ambito().filter(producto=producto).update(cantidad=Decimal("0"))


def reponer(producto, cantidad=5):
    SaldoStock.objects.sin_ambito().filter(producto=producto).update(cantidad=Decimal(cantidad))


class TestAvisame:
    def test_solo_se_pide_de_un_producto_agotado(self, vende):
        p = publicar(vende)
        c = registrada()
        r = c.put(f"{AVISOS}/{p.pk}", {}, format="json")
        assert r.status_code == 400 and "disponible" in r.json()["error"]["mensaje"]
        agotar(p)
        assert c.put(f"{AVISOS}/{p.pk}", {}, format="json").json() == {"avisos": [p.pk]}
        assert c.put(f"{AVISOS}/{p.pk}", {}, format="json").json() == {
            "avisos": [p.pk]
        }  # no duplica
        assert AvisoDisponibilidad.objects.sin_ambito().count() == 1
        assert c.get(FAVORITOS).json()["avisos"] == [p.pk]
        assert c.delete(f"{AVISOS}/{p.pk}").json() == {"avisos": []}

    def test_cuando_llega_stock_se_avisa_una_sola_vez(self, vende):
        p = publicar(vende, "Cámara")
        c = registrada()
        agotar(p)
        c.put(f"{AVISOS}/{p.pk}", {}, format="json")
        assert favoritos.avisar_disponibles() == 0  # sigue agotado
        reponer(p)
        n = len(mail.outbox)
        assert favoritos.avisar_disponibles() == 1
        assert len(mail.outbox) == n + 1
        correo = mail.outbox[-1]
        assert "Cámara" in correo.subject and "ana@ejemplo.pe" in correo.to
        assert f"/producto/{p.slug}" in correo.body or "/producto/" in correo.body
        assert favoritos.avisar_disponibles() == 0  # ya se avisó
        assert len(mail.outbox) == n + 1
        # después de avisar puede pedir otro aviso (si vuelve a agotarse)
        agotar(p)
        assert c.put(f"{AVISOS}/{p.pk}", {}, format="json").status_code == 200

    def test_dos_clientes_reciben_su_aviso(self, vende):
        p = publicar(vende)
        a, b = registrada("a@ejemplo.pe"), registrada("b@ejemplo.pe")
        agotar(p)
        a.put(f"{AVISOS}/{p.pk}", {}, format="json")
        b.put(f"{AVISOS}/{p.pk}", {}, format="json")
        reponer(p)
        assert favoritos.avisar_disponibles() == 2

    def test_no_se_avisa_a_una_cuenta_desactivada(self, vende):
        p = publicar(vende)
        c = registrada()
        agotar(p)
        c.put(f"{AVISOS}/{p.pk}", {}, format="json")
        CuentaCliente.objects.sin_ambito().update(activa=False)
        reponer(p)
        assert favoritos.avisar_disponibles() == 0

    def test_un_pedido_de_aviso_viejo_vence(self, vende):
        p = publicar(vende)
        c = registrada()
        agotar(p)
        c.put(f"{AVISOS}/{p.pk}", {}, format="json")
        AvisoDisponibilidad.objects.sin_ambito().update(
            creado_en=timezone.now() - timedelta(days=91)
        )
        reponer(p)
        assert favoritos.avisar_disponibles() == 0
        assert not AvisoDisponibilidad.objects.sin_ambito().exists()
