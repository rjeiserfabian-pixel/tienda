"""La tienda donde se vende decide la serie y la cuenta de cobro de cada empresa."""

import itertools
from decimal import Decimal as D

import pytest

from apps.caja.servicios import saldo_de
from apps.mantenimiento.models import CuentaFinanciera, SerieComprobante
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import servicios
from apps.ventas.exceptions import CuentaDeCobroNoConfigurada, VentaInvalida
from apps.ventas.models import CuentaDeCobro

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


@pytest.fixture
def locales(tienda):
    """Una tienda de Tarapoto compartida (una sucursal por empresa) y otra de Lima solo de A."""
    a = tienda.almacen(tienda.a).sucursal
    b = tienda.almacen(tienda.b).sucursal
    Sucursal.objects.sin_ambito().filter(pk__in=[a.pk, b.pk]).update(local_fisico="TARAPOTO")
    a.refresh_from_db()
    b.refresh_from_db()
    lima = Sucursal.objects.sin_ambito().create(
        empresa=tienda.a, nombre="Lima", codigo="002", local_fisico="LIMA"
    )
    return type("Locales", (), {"a": a, "b": b, "lima": lima})


def cuenta(tienda, empresa, nombre, tipo="BILLETERA"):
    return CuentaFinanciera.objects.sin_ambito().create(empresa=empresa, nombre=nombre, tipo=tipo)


class TestSucursalEquivalente:
    def test_la_misma_tienda_en_la_otra_empresa(self, tienda, locales):
        assert servicios.sucursal_equivalente(tienda.a, locales.a) == locales.a
        assert servicios.sucursal_equivalente(tienda.b, locales.a) == locales.b
        assert servicios.sucursal_equivalente(tienda.a, locales.b) == locales.a

    def test_sin_local_fisico_o_sin_hermana_no_hay_equivalente(self, tienda, locales):
        assert servicios.sucursal_equivalente(tienda.b, locales.lima) is None
        assert servicios.sucursal_equivalente(tienda.a, None) is None
        Sucursal.objects.sin_ambito().filter(pk=locales.a.pk).update(local_fisico="")
        locales.a.refresh_from_db()
        assert servicios.sucursal_equivalente(tienda.b, locales.a) is None


class TestCuentaPorTienda:
    def test_cada_tienda_tiene_su_yape(self, tienda, locales):
        yape_a_lima = cuenta(tienda, tienda.a, "Yape Lima")
        yape_a_tarapoto = cuenta(tienda, tienda.a, "Yape Tarapoto A")
        yape_b_tarapoto = cuenta(tienda, tienda.b, "Yape Tarapoto B")
        CuentaDeCobro.objects.create(
            empresa=tienda.a, medio_pago=tienda.yape, sucursal=locales.lima, cuenta=yape_a_lima
        )
        CuentaDeCobro.objects.create(
            empresa=tienda.a, medio_pago=tienda.yape, sucursal=locales.a, cuenta=yape_a_tarapoto
        )
        CuentaDeCobro.objects.create(
            empresa=tienda.b, medio_pago=tienda.yape, sucursal=locales.b, cuenta=yape_b_tarapoto
        )
        resolver = servicios.resolver_cuenta
        assert resolver(tienda.a, tienda.yape, locales.lima, "PEN") == yape_a_lima
        assert resolver(tienda.a, tienda.yape, locales.a, "PEN") == yape_a_tarapoto
        # B se entera de la tienda por el local físico.
        assert resolver(tienda.b, tienda.yape, locales.a, "PEN") == yape_b_tarapoto
        # Sin tienda cae a la cuenta general de la empresa (la de la configuración base).
        assert resolver(tienda.a, tienda.yape, None, "PEN") == tienda.billeteras[tienda.a.pk]

    def test_una_tienda_sin_cuenta_propia_usa_la_general(self, tienda, locales):
        assert (
            servicios.resolver_cuenta(tienda.b, tienda.yape, locales.lima, "PEN")
            == tienda.billeteras[tienda.b.pk]
        )

    def test_la_venta_manda_el_cobro_a_la_cuenta_de_la_tienda_de_cada_empresa(
        self, tienda, locales
    ):
        yape_a = cuenta(tienda, tienda.a, "Yape Tarapoto A")
        yape_b = cuenta(tienda, tienda.b, "Yape Tarapoto B")
        CuentaDeCobro.objects.create(
            empresa=tienda.a, medio_pago=tienda.yape, sucursal=locales.a, cuenta=yape_a
        )
        CuentaDeCobro.objects.create(
            empresa=tienda.b, medio_pago=tienda.yape, sucursal=locales.b, cuenta=yape_b
        )
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        venta = tienda.vender(
            [tienda.linea(pa, 2), tienda.linea(pb, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.yape, "129.80", referencia="OP-1")],
            sucursal=locales.a,
        )
        assert venta.sucursal == locales.a
        assert saldo_de(yape_a) == D("70.80") and saldo_de(yape_b) == D("59.00")
        assert saldo_de(tienda.billeteras[tienda.a.pk]) == D("0")

    def test_el_efectivo_cae_en_el_mostrador_de_la_tienda(self, tienda, locales):
        caja_lima = CuentaFinanciera.objects.sin_ambito().create(
            empresa=tienda.a,
            nombre="Mostrador Lima",
            tipo="CAJA",
            rol_caja="MOSTRADOR",
            sucursal=locales.lima,
        )
        caja_tarapoto = CuentaFinanciera.objects.sin_ambito().create(
            empresa=tienda.a,
            nombre="Mostrador Tarapoto",
            tipo="CAJA",
            rol_caja="MOSTRADOR",
            sucursal=locales.a,
        )
        resolver = servicios.resolver_cuenta
        assert resolver(tienda.a, tienda.efectivo, locales.lima, "PEN") == caja_lima
        assert resolver(tienda.a, tienda.efectivo, locales.a, "PEN") == caja_tarapoto
        # Sin saber la tienda hay dos mostradores y no se adivina.
        with pytest.raises(CuentaDeCobroNoConfigurada):
            resolver(tienda.a, tienda.efectivo, None, "PEN")

    def test_la_serie_es_la_de_la_tienda_en_cada_empresa(self, tienda, locales):
        tipo = tienda.tipo("NV")
        serie_b_tarapoto = SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.b,
            tipo_comprobante=tipo,
            serie="N0T2",
            sucursal=locales.b,
            es_electronica=False,
        )
        serie_b_otra = SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.b,
            tipo_comprobante=tipo,
            serie="N0X2",
            sucursal=None,
            es_electronica=False,
        )
        # La serie general N002 de B y la de otra tienda no compiten con la de la tienda.
        assert servicios._serie_de(tienda.b, tipo, locales.a, None) == serie_b_tarapoto
        # Lima no existe en B: se usan las series generales, y hay dos, así que no se adivina.
        with pytest.raises(VentaInvalida, match="varias series"):
            servicios._serie_de(tienda.b, tipo, locales.lima, None)
        assert serie_b_otra.pk


class TestApiCuentasDeCobro:
    def crear(self, usuario, **datos):
        return cliente_de(usuario).post(f"{BASE}/cuentas-de-cobro/", datos, format="json")

    def test_el_administrador_configura_y_lista(self, tienda, locales):
        yape = cuenta(tienda, tienda.a, "Yape Tarapoto A")
        r = self.crear(
            "admin",
            empresa=tienda.a.pk,
            medio_pago=tienda.yape.pk,
            sucursal=locales.a.pk,
            cuenta=yape.pk,
        )
        assert r.status_code == 201, r.content
        assert r.json()["sucursal_nombre"] == locales.a.nombre
        lista = cliente_de("vendedor").get(f"{BASE}/cuentas-de-cobro/", {"empresa": tienda.a.pk})
        assert lista.status_code == 200
        assert sorted(f["cuenta_nombre"] for f in lista.json()["results"]) == [
            "Yape",
            "Yape Tarapoto A",
        ]

    def test_el_vendedor_no_configura(self, tienda, locales):
        yape = cuenta(tienda, tienda.a, "Otra")
        r = self.crear("vendedor", empresa=tienda.a.pk, medio_pago=tienda.yape.pk, cuenta=yape.pk)
        assert r.status_code == 403

    def test_no_se_repite_el_metodo_en_la_misma_tienda(self, tienda, locales):
        yape = cuenta(tienda, tienda.a, "Yape Tarapoto A")
        datos = {
            "empresa": tienda.a.pk,
            "medio_pago": tienda.yape.pk,
            "sucursal": locales.a.pk,
            "cuenta": yape.pk,
        }
        assert self.crear("admin", **datos).status_code == 201
        r = self.crear("admin", **datos)
        assert r.status_code == 400 and "ya tiene una cuenta" in json_texto(r)

    def test_el_efectivo_va_a_una_caja_y_lo_demas_a_una_cuenta(self, tienda, locales):
        billetera = cuenta(tienda, tienda.a, "Yape X")
        caja = tienda.cajas[tienda.a.pk]
        malo = self.crear(
            "admin", empresa=tienda.a.pk, medio_pago=tienda.efectivo.pk, cuenta=billetera.pk
        )
        assert malo.status_code == 400
        malo = self.crear("admin", empresa=tienda.a.pk, medio_pago=tienda.yape.pk, cuenta=caja.pk)
        assert malo.status_code == 400

    def test_no_acepta_cuentas_o_tiendas_de_otra_empresa(self, tienda, locales):
        ajena = cuenta(tienda, tienda.b, "Yape de B")
        r = self.crear("admin", empresa=tienda.a.pk, medio_pago=tienda.yape.pk, cuenta=ajena.pk)
        assert r.status_code == 400
        propia = cuenta(tienda, tienda.a, "Yape A2")
        r = self.crear(
            "admin",
            empresa=tienda.a.pk,
            medio_pago=tienda.yape.pk,
            cuenta=propia.pk,
            sucursal=locales.b.pk,
        )
        assert r.status_code == 400

    def test_se_elimina_y_el_metodo_vuelve_a_la_cuenta_general(self, tienda, locales):
        yape = cuenta(tienda, tienda.a, "Yape Tarapoto A")
        creada = self.crear(
            "admin",
            empresa=tienda.a.pk,
            medio_pago=tienda.yape.pk,
            sucursal=locales.a.pk,
            cuenta=yape.pk,
        ).json()
        assert servicios.resolver_cuenta(tienda.a, tienda.yape, locales.a, "PEN") == yape
        r = cliente_de("admin").delete(f"{BASE}/cuentas-de-cobro/{creada['id']}/")
        assert r.status_code == 204
        assert (
            servicios.resolver_cuenta(tienda.a, tienda.yape, locales.a, "PEN")
            == tienda.billeteras[tienda.a.pk]
        )

    def test_la_configuracion_de_la_venta_trae_las_tiendas(self, tienda, locales):
        r = cliente_de("vendedor").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk})
        nombres = [s["nombre"] for s in r.json()["sucursales"]]
        assert locales.a.nombre in nombres and "Lima" in nombres

    def test_la_disponibilidad_del_cobro_depende_de_la_tienda(self, tienda, locales):
        # Dos mostradores: sin tienda el efectivo es ambiguo; con tienda sí se sabe.
        for sucursal, nombre in ((locales.lima, "Lima"), (locales.a, "Tarapoto")):
            CuentaFinanciera.objects.sin_ambito().create(
                empresa=tienda.a,
                nombre=f"Mostrador {nombre}",
                tipo="CAJA",
                rol_caja="MOSTRADOR",
                sucursal=sucursal,
            )
        c = cliente_de("admin")
        medio, empresa = str(tienda.efectivo.pk), str(tienda.a.pk)
        sin = c.get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        assert sin["cobros"]["PEN"][empresa][medio]["ok"] is False
        con = c.get(
            f"{BASE}/configuracion/", {"empresa": tienda.a.pk, "sucursal": locales.lima.pk}
        ).json()
        assert con["cobros"]["PEN"][empresa][medio]["ok"] is True


def json_texto(respuesta) -> str:
    return str(respuesta.json())
