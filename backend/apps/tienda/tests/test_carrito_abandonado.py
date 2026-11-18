"""Carrito abandonado: recordatorios a las 2 y a las 24 horas, baja fácil y lo recuperado."""

# ruff: noqa: F811

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import carrito_abandonado
from apps.tienda.models import (
    CarritoCuenta,
    ConfiguracionCarritoAbandonado,
    CuentaCliente,
    Cupon,
    RecordatorioCarrito,
)

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import PEDIDOS, con_direccion, contexto, cuerpo, vende  # noqa: F401

pytestmark = pytest.mark.django_db

CARRITO = "/api/v1/tienda/cuenta/carrito"
BAJA = "/api/v1/tienda/cuenta/baja-promociones"
ADMIN = "/api/v1/tienda/admin/carrito-abandonado/"


def encender(tienda, **extra):
    return ConfiguracionCarritoAbandonado.objects.sin_ambito().create(
        organizacion_id=tienda.org.pk, activo=True, **extra
    )


def cliente_con_carrito(vende, *, acepta=True, nombre="Mouse", cantidad=2):
    """Un cliente confirmado con un producto en su carrito guardado."""
    contexto(vende)
    producto = vende.publicar(nombre, costo=Decimal("40"), precio=100, stock=10)
    c = registrada("ana@ejemplo.pe")
    CuentaCliente.objects.sin_ambito().update(acepta_ofertas=acepta)
    r = c.put(CARRITO, {"lineas": [{"producto": producto.pk, "cantidad": cantidad}]}, format="json")
    assert r.status_code == 200, r.content
    return producto, c


def hace(horas):
    """Pone el carrito como dejado hace ``horas`` (sin pasar por ``save``)."""
    CarritoCuenta.objects.sin_ambito().update(
        actualizado_en=timezone.now() - timedelta(hours=horas)
    )


class TestPrimerRecordatorio:
    def test_no_hace_nada_mientras_este_apagado(self, vende):
        cliente_con_carrito(vende)
        hace(5)
        assert carrito_abandonado.recordar_carritos() == 0
        assert not mail.outbox or "carrito" not in mail.outbox[-1].subject.lower()

    def test_a_las_dos_horas_llega_el_primero_con_el_detalle_y_la_baja(self, vende):
        encender(vende)
        producto, c = cliente_con_carrito(vende)
        hace(1)
        assert carrito_abandonado.recordar_carritos() == 0  # todavía no pasan 2 horas
        hace(3)
        n = len(mail.outbox)
        assert carrito_abandonado.recordar_carritos() == 1
        assert len(mail.outbox) == n + 1
        correo = mail.outbox[-1]
        assert "ana@ejemplo.pe" in correo.to and "carrito" in correo.subject.lower()
        assert "2 x Mouse" in correo.body and "236.00" in correo.body
        assert "/carrito" in correo.body and "/cuenta/baja?t=" in correo.body
        assert "aceptaste recibir ofertas" in correo.body
        fila = CarritoCuenta.objects.sin_ambito().get()
        assert fila.recordatorios_enviados == 1 and fila.ultimo_recordatorio_en
        assert RecordatorioCarrito.objects.sin_ambito().get().numero == 1
        # no se repite en la siguiente revisión
        assert carrito_abandonado.recordar_carritos() == 0
        assert len(mail.outbox) == n + 1

    def test_solo_a_quien_acepto_ofertas_y_tiene_el_correo_confirmado(self, vende):
        encender(vende)
        cliente_con_carrito(vende, acepta=False)
        hace(5)
        assert carrito_abandonado.recordar_carritos() == 0
        CuentaCliente.objects.sin_ambito().update(acepta_ofertas=True, correo_verificado_en=None)
        assert carrito_abandonado.recordar_carritos() == 0

    def test_no_recuerda_carritos_viejos_ni_vacios(self, vende):
        encender(vende)
        producto, c = cliente_con_carrito(vende)
        hace(24 * 4)  # lo dejó hace 4 días: ya no
        assert carrito_abandonado.recordar_carritos() == 0
        hace(5)
        c.put(CARRITO, {"lineas": []}, format="json")
        hace(5)
        assert carrito_abandonado.recordar_carritos() == 0

    def test_no_recuerda_si_ya_compro_despues(self, vende):
        encender(vende)
        producto, c = cliente_con_carrito(vende)
        hace(5)
        contexto(vende)
        r = c.post(PEDIDOS, cuerpo((producto, 1), direccion=con_direccion(c)), format="json")
        assert r.status_code == 201, r.content
        assert carrito_abandonado.recordar_carritos() == 0

    def test_si_el_producto_ya_no_se_vende_no_se_recuerda(self, vende):
        from apps.mantenimiento.models import Producto

        encender(vende)
        producto, c = cliente_con_carrito(vende)
        Producto.objects.sin_ambito().filter(pk=producto.pk).update(publicado_web=False)
        hace(5)
        assert carrito_abandonado.recordar_carritos() == 0


class TestSegundoRecordatorio:
    def test_a_las_24_horas_del_primero_con_el_cupon_y_nunca_un_tercero(self, vende):
        cupon = Cupon.objects.sin_ambito().create(
            organizacion_id=vende.org.pk, codigo="VUELVE10", tipo="PORCENTAJE", valor=Decimal("10")
        )
        encender(vende, cupon=cupon)
        producto, c = cliente_con_carrito(vende)
        hace(30)
        assert carrito_abandonado.recordar_carritos() == 1
        assert "VUELVE10" not in mail.outbox[-1].body  # el primero va sin cupón
        # pasan 23 horas desde el primero: todavía no
        CarritoCuenta.objects.sin_ambito().update(
            ultimo_recordatorio_en=timezone.now() - timedelta(hours=23)
        )
        assert carrito_abandonado.recordar_carritos() == 0
        CarritoCuenta.objects.sin_ambito().update(
            ultimo_recordatorio_en=timezone.now() - timedelta(hours=25)
        )
        n = len(mail.outbox)
        assert carrito_abandonado.recordar_carritos() == 1
        correo = mail.outbox[-1]
        assert len(mail.outbox) == n + 1 and "VUELVE10" in correo.body and "10 %" in correo.body
        assert RecordatorioCarrito.objects.sin_ambito().filter(numero=2, cupon_codigo="VUELVE10")
        # tercero: nunca
        CarritoCuenta.objects.sin_ambito().update(
            ultimo_recordatorio_en=timezone.now() - timedelta(days=2)
        )
        assert carrito_abandonado.recordar_carritos() == 0

    def test_si_el_cliente_cambia_su_carrito_se_empieza_de_cero(self, vende):
        encender(vende)
        producto, c = cliente_con_carrito(vende)
        hace(5)
        assert carrito_abandonado.recordar_carritos() == 1
        # volver a guardar lo mismo (el navegador lo hace al abrir) NO reinicia nada
        c.put(CARRITO, {"lineas": [{"producto": producto.pk, "cantidad": 2}]}, format="json")
        assert CarritoCuenta.objects.sin_ambito().get().recordatorios_enviados == 1
        # cambiar la cantidad sí: es otra compra
        c.put(CARRITO, {"lineas": [{"producto": producto.pk, "cantidad": 3}]}, format="json")
        fila = CarritoCuenta.objects.sin_ambito().get()
        assert fila.recordatorios_enviados == 0 and fila.ultimo_recordatorio_en is None


class TestBaja:
    def test_el_enlace_de_baja_quita_el_permiso_y_corta_los_recordatorios(self, vende):
        encender(vende)
        producto, c = cliente_con_carrito(vende)
        hace(5)
        carrito_abandonado.recordar_carritos()
        token = re.search(r"/cuenta/baja\?t=(\S+)", mail.outbox[-1].body).group(1)
        anonimo = APIClient(HTTP_X_REQUESTED_WITH="tienda")
        r = anonimo.post(BAJA, {"token": token}, format="json")
        assert r.status_code == 200, r.content
        assert CuentaCliente.objects.sin_ambito().get().acepta_ofertas is False
        CarritoCuenta.objects.sin_ambito().update(
            recordatorios_enviados=0, ultimo_recordatorio_en=None
        )
        hace(5)
        n = len(mail.outbox)
        assert carrito_abandonado.recordar_carritos() == 0
        assert len(mail.outbox) == n

    def test_un_enlace_falso_no_sirve(self, vende):
        cliente_con_carrito(vende)
        anonimo = APIClient(HTTP_X_REQUESTED_WITH="tienda")
        assert anonimo.post(BAJA, {"token": "x.y.z"}, format="json").status_code == 400
        assert CuentaCliente.objects.sin_ambito().get().acepta_ofertas is True


class TestRecuperado:
    def test_un_pago_despues_del_recordatorio_cuenta_como_recuperado(self, cobra, culqi_falso):
        encender(cobra)
        producto, c = cliente_con_carrito(cobra)
        hace(5)
        assert carrito_abandonado.recordar_carritos() == 1
        contexto(cobra)
        numero = c.post(
            PEDIDOS, cuerpo((producto, 1), direccion=con_direccion(c)), format="json"
        ).json()["numero"]
        assert carrito_abandonado.estadisticas(cobra.org.pk)["recuperados"] == 0
        assert pagar_pedido(c, numero).status_code == 200
        r = RecordatorioCarrito.objects.sin_ambito().get()
        assert r.recuperado_en is not None and r.pedido.numero == numero
        est = carrito_abandonado.estadisticas(cobra.org.pk)
        assert est["recordatorios"] == 1 and est["clientes"] == 1 and est["recuperados"] == 1
        assert Decimal(est["vendido"]) > 0


class TestPanel:
    def test_se_configura_y_muestra_resultados(self, vende):
        cupon = Cupon.objects.sin_ambito().create(
            organizacion_id=vende.org.pk, codigo="VUELVE10", tipo="PORCENTAJE", valor=Decimal("10")
        )
        admin = cliente_de("admin")
        base = admin.get(ADMIN).json()
        assert (
            base["activo"] is False and base["horas_primero"] == 2 and base["horas_segundo"] == 24
        )
        assert any(x["id"] == cupon.pk for x in base["cupones"])
        r = admin.patch(
            ADMIN,
            {"activo": True, "horas_primero": 3, "horas_segundo": 48, "cupon": cupon.pk},
            format="json",
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["activo"] and d["horas_primero"] == 3 and d["horas_segundo"] == 48
        assert d["cupon"] == cupon.pk and d["estadisticas"]["recordatorios"] == 0
        assert admin.patch(ADMIN, {"cupon": None}, format="json").json()["cupon"] is None

    @pytest.mark.parametrize(
        "malo", [{"horas_primero": 0}, {"horas_segundo": 500}, {"cupon": 999999}]
    )
    def test_valida(self, vende, malo):
        assert cliente_de("admin").patch(ADMIN, malo, format="json").status_code in (400, 404)

    def test_solo_quien_gestiona_ofertas(self, vende):
        assert cliente_de("vendedor").get(ADMIN).status_code == 403
        assert (
            cliente_de("vendedor").patch(ADMIN, {"activo": True}, format="json").status_code == 403
        )
        assert APIClient().get(ADMIN).status_code == 401
