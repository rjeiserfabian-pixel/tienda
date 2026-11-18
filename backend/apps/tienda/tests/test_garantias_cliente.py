"""Las garantías en la cuenta del cliente de la tienda y cuando el almacén cambia la serie."""

# ruff: noqa: F811

import pytest

from apps.garantias.models import EstadoGarantia, Garantia
from apps.mantenimiento.models import Producto
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import series_pedido
from apps.tienda.models import LineaPedido, PedidoTienda

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import PEDIDOS, contexto, vende  # noqa: F401
from .test_series import ADMIN, estado, ingresar, laptop, pedir

pytestmark = pytest.mark.django_db

GARANTIAS = "/api/v1/tienda/cuenta/garantias"


def laptop_con_garantia(tienda, meses=12):
    p = laptop(tienda)
    Producto.objects.sin_ambito().filter(pk=p.pk).update(garantia_meses=meses)
    p.refresh_from_db()
    return p


def pagado(cobra, series=("S-VIEJA", "S-OTRA"), meses=12):
    p = laptop_con_garantia(cobra, meses)
    ingresar(cobra, p, [series[0]], dias=50)
    ingresar(cobra, p, [series[1]], dias=5)
    c, ped = pedir(cobra, p)
    assert pagar_pedido(c, ped["numero"]).status_code == 200
    return p, c, ped["numero"]


def detalle(c, numero):
    return c.get(f"{PEDIDOS}/{numero}").json()


class TestEnElPedido:
    def test_la_serie_y_el_enlace_aparecen_cuando_el_equipo_va_hacia_el_cliente(
        self, cobra, culqi_falso
    ):
        _, c, numero = pagado(cobra)
        antes = detalle(c, numero)["garantias"]
        assert len(antes) == 1
        assert (antes[0]["numero_serie"], antes[0]["enlace"]) == ("", "")  # aún puede cambiar
        assert antes[0]["meses"] == 12 and antes[0]["vigente"] is True
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        (g,) = detalle(c, numero)["garantias"]
        token = Garantia.objects.sin_ambito().get().token_publico
        assert g["numero_serie"] == "S-VIEJA" and g["enlace"] == f"/garantia/{token}"

    def test_sin_meses_de_garantia_no_hay_nada(self, cobra, culqi_falso):
        _, c, numero = pagado(cobra, meses=None)
        assert detalle(c, numero)["garantias"] == []
        assert not Garantia.objects.sin_ambito().exists()


class TestCambioDeSerie:
    def cambiar(self, numero, producto, anterior, nueva):
        linea = LineaPedido.objects.sin_ambito().get(pedido__numero=numero, producto=producto).pk
        datos = {"linea": linea, "anterior": anterior, "nueva": nueva, "motivo": "Unidad dañada"}
        r = cliente_de("admin").post(f"{ADMIN}/{numero}/serie/", datos, format="json")
        assert r.status_code == 200, r.content

    def test_la_garantia_sigue_a_la_unidad_que_se_entrega(self, cobra, culqi_falso):
        p, c, numero = pagado(cobra)
        self.cambiar(numero, p, "S-VIEJA", "S-OTRA")
        assert Garantia.objects.sin_ambito().get().numero_serie == "S-OTRA"
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        assert detalle(c, numero)["garantias"][0]["numero_serie"] == "S-OTRA"

    def test_se_vuelve_a_cambiar_y_la_garantia_regresa(self, cobra, culqi_falso):
        p, c, numero = pagado(cobra)
        self.cambiar(numero, p, "S-VIEJA", "S-OTRA")
        self.cambiar(numero, p, "S-OTRA", "S-VIEJA")
        assert Garantia.objects.sin_ambito().get().numero_serie == "S-VIEJA"

    def test_al_deshacer_los_cambios_vuelve_a_la_serie_del_comprobante(self, cobra, culqi_falso):
        p, c, numero = pagado(cobra)
        self.cambiar(numero, p, "S-VIEJA", "S-OTRA")
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        contexto(cobra)  # en la vida real esto corre dentro de una operación con sesión
        assert series_pedido.deshacer_cambios(pedido) == 1
        assert Garantia.objects.sin_ambito().get().numero_serie == "S-VIEJA"


class TestMisGarantias:
    def test_aparecen_cuando_el_equipo_ya_va_hacia_el_cliente(self, cobra, culqi_falso):
        _, c, numero = pagado(cobra)
        assert c.get(GARANTIAS).json() == {"results": []}  # pagado, todavía en el almacén
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        r = c.get(GARANTIAS)
        assert r.status_code == 200, r.content
        (g,) = r.json()["results"]
        assert g["pedido"] == numero and g["numero_serie"] == "S-VIEJA"
        assert g["situacion"] == "VIGENTE" and g["enlace"].startswith("/garantia/")

    def test_cada_cliente_ve_solo_las_suyas(self, cobra, culqi_falso):
        from .test_cuentas import registrada

        _, c, numero = pagado(cobra)
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        otro = registrada("otra@ejemplo.pe")
        assert otro.get(GARANTIAS).json() == {"results": []}

    def test_una_garantia_anulada_lo_dice(self, cobra, culqi_falso):
        _, c, numero = pagado(cobra)
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        Garantia.objects.sin_ambito().update(estado=EstadoGarantia.ANULADA)
        (g,) = c.get(GARANTIAS).json()["results"]
        assert g["situacion"] == "ANULADA" and g["vigente"] is False

    def test_exige_sesion(self, tienda):
        from rest_framework.test import APIClient

        assert APIClient().get(GARANTIAS).status_code in (401, 403)
