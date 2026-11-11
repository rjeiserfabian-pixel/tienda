"""Liquidación de tarjetas: el dinero pasa del POS al banco, menos la comisión del procesador."""

import itertools
from decimal import Decimal as D

import pytest

from apps.caja.models import MovimientoCaja, Origen
from apps.caja.servicios import saldo_de
from apps.core.exceptions import DocumentoYaAnulado
from apps.mantenimiento.models import CuentaFinanciera
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import liquidaciones
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import CuentaDeCobro, LiquidacionTarjeta

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


@pytest.fixture
def pos(tienda):
    """La cuenta del POS de A (entra lo cobrado con tarjeta) y su banco, con una venta de 118."""
    cuenta_pos = CuentaFinanciera.objects.sin_ambito().create(
        empresa=tienda.a, nombre="POS Niubiz", tipo="BANCO", banco="Niubiz"
    )
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=tienda.a, nombre="BCP soles", tipo="BANCO", banco="BCP"
    )
    CuentaDeCobro.objects.create(empresa=tienda.a, medio_pago=tienda.tarjeta, cuenta=cuenta_pos)
    producto = tienda.producto()
    tienda.vender(
        [tienda.linea(producto, 1)], [tienda.cobro(tienda.tarjeta, "118.00", referencia="V-1")]
    )
    return type("POS", (), {"pos": cuenta_pos, "banco": banco, "producto": producto})


def liquidar(tienda, pos, **extra):
    datos = {
        "empresa": tienda.a,
        "cuenta_pos": pos.pos,
        "cuenta_destino": pos.banco,
        "bruto": D("118.00"),
        "comision": D("4.50"),
        "referencia": "LOTE-77",
    }
    return liquidaciones.liquidar_tarjeta(**{**datos, **extra})


class TestPendientes:
    def test_lo_cobrado_con_tarjeta_queda_pendiente_en_el_pos(self, tienda, pos):
        (fila,) = liquidaciones.pendientes(tienda.a)
        assert (fila["nombre"], fila["saldo"], fila["moneda"]) == ("POS Niubiz", D("118.00"), "PEN")
        assert saldo_de(pos.banco) == D("0")

    def test_solo_cuentan_las_cuentas_que_cobran_con_tarjeta(self, tienda, pos):
        assert [c.nombre for c in liquidaciones.cuentas_de_tarjeta(tienda.a)] == ["POS Niubiz"]
        assert liquidaciones.cuentas_de_tarjeta(tienda.b) == []


class TestLiquidar:
    def test_el_neto_va_al_banco_y_la_comision_es_un_egreso(self, tienda, pos):
        liq = liquidar(tienda, pos)
        assert (liq.numero, liq.bruto, liq.comision, liq.neto) == (
            1,
            D("118.00"),
            D("4.50"),
            D("113.50"),
        )
        assert saldo_de(pos.banco) == D("113.50")
        assert saldo_de(pos.pos) == D("0.00")  # lo vendido menos lo transferido menos la comisión
        comision = MovimientoCaja.objects.sin_ambito().get(origen_tipo=Origen.COMISION_TARJETA)
        assert (comision.tipo, comision.monto, comision.cuenta_id) == (
            "EGRESO",
            D("4.50"),
            pos.pos.pk,
        )
        assert liq.transferencia is not None and liq.transferencia.monto_origen == D("113.50")

    def test_sin_comision_solo_hay_transferencia(self, tienda, pos):
        liq = liquidar(tienda, pos, comision=D("0"))
        assert saldo_de(pos.banco) == D("118.00") and liq.neto == D("118.00")
        assert (
            not MovimientoCaja.objects.sin_ambito()
            .filter(origen_tipo=Origen.COMISION_TARJETA)
            .exists()
        )

    def test_se_puede_liquidar_por_partes(self, tienda, pos):
        liquidar(tienda, pos, bruto=D("50.00"), comision=D("2.00"))
        assert liquidaciones.pendientes(tienda.a)[0]["saldo"] == D("68.00")
        segunda = liquidar(tienda, pos, bruto=D("68.00"), comision=D("2.50"))
        assert segunda.numero == 2
        assert liquidaciones.pendientes(tienda.a)[0]["saldo"] == D("0.00")

    def test_no_se_liquida_mas_de_lo_que_hay_en_el_pos(self, tienda, pos):
        with pytest.raises(VentaInvalida, match="solo hay 118.00 por liquidar"):
            liquidar(tienda, pos, bruto=D("118.01"))
        assert not LiquidacionTarjeta.objects.sin_ambito().exists()
        assert saldo_de(pos.banco) == D("0")

    @pytest.mark.parametrize(
        ("datos", "mensaje"),
        [
            ({"comision": D("118.00")}, "comisión debe ser menor"),
            ({"comision": D("-1")}, "comisión debe ser menor"),
            ({"bruto": D("0")}, "mayor que cero"),
            ({"bruto": D("10.123")}, "2 decimales"),
        ],
    )
    def test_valida_los_montos(self, tienda, pos, datos, mensaje):
        with pytest.raises(VentaInvalida, match=mensaje):
            liquidar(tienda, pos, **datos)

    def test_el_origen_debe_ser_una_cuenta_de_pos_y_el_destino_un_banco(self, tienda, pos):
        with pytest.raises(VentaInvalida, match="no es una cuenta de cobro con tarjeta"):
            liquidar(tienda, pos, cuenta_pos=pos.banco, cuenta_destino=pos.pos)
        with pytest.raises(VentaInvalida, match="no en una caja"):
            liquidar(tienda, pos, cuenta_destino=tienda.cajas[tienda.a.pk])
        with pytest.raises(VentaInvalida, match="distinto"):
            liquidar(tienda, pos, cuenta_destino=pos.pos)

    def test_el_banco_debe_ser_de_la_misma_moneda(self, tienda, pos):
        dolares = CuentaFinanciera.objects.sin_ambito().create(
            empresa=tienda.a, nombre="BCP dólares", tipo="BANCO", moneda="USD"
        )
        with pytest.raises(VentaInvalida, match="misma moneda"):
            liquidar(tienda, pos, cuenta_destino=dolares)


class TestAnular:
    def test_anular_devuelve_el_dinero_y_la_comision_al_pos(self, tienda, pos):
        liq = liquidar(tienda, pos)
        liquidaciones.anular_liquidacion(liq, motivo="Se registró el lote equivocado")
        assert saldo_de(pos.banco) == D("0.00")
        assert saldo_de(pos.pos) == D("118.00")
        liq.refresh_from_db()
        assert liq.estado == "ANULADO"
        with pytest.raises(DocumentoYaAnulado):
            liquidaciones.anular_liquidacion(liq, motivo="Otra vez")

    def test_despues_de_anular_se_puede_liquidar_de_nuevo(self, tienda, pos):
        liq = liquidar(tienda, pos)
        liquidaciones.anular_liquidacion(liq, motivo="Error")
        nueva = liquidar(tienda, pos, comision=D("3.00"))
        assert nueva.numero == 2 and saldo_de(pos.banco) == D("115.00")


class TestApi:
    def crear(self, usuario, tienda, pos, **extra):
        cuerpo = {
            "empresa": tienda.a.pk,
            "cuenta_pos": pos.pos.pk,
            "cuenta_destino": pos.banco.pk,
            "bruto": "118.00",
            "comision": "4.50",
            "referencia": "LOTE-1",
            **extra,
        }
        return cliente_de(usuario).post(
            f"{BASE}/liquidaciones/",
            cuerpo,
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"liquidacion-{next(_claves):06d}",
        )

    def test_el_administrador_ve_lo_pendiente_y_liquida(self, tienda, pos):
        r = cliente_de("admin").get(f"{BASE}/liquidaciones/pendientes/", {"empresa": tienda.a.pk})
        assert r.json() == [
            {"cuenta": pos.pos.pk, "nombre": "POS Niubiz", "moneda": "PEN", "saldo": "118.00"}
        ]
        r = self.crear("admin", tienda, pos)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["neto"], d["comision"]) == (1, "113.50", "4.50")
        lista = cliente_de("admin").get(f"{BASE}/liquidaciones/", {"empresa": tienda.a.pk}).json()
        assert lista["count"] == 1 and lista["results"][0]["cuenta_destino_nombre"] == "BCP soles"

    def test_el_vendedor_no_liquida_ni_ve_el_historial(self, tienda, pos):
        assert self.crear("vendedor", tienda, pos).status_code == 403
        r = cliente_de("vendedor").get(f"{BASE}/liquidaciones/", {"empresa": tienda.a.pk})
        assert r.status_code == 403
        assert not LiquidacionTarjeta.objects.sin_ambito().exists()

    def test_un_reintento_con_la_misma_clave_no_liquida_dos_veces(self, tienda, pos):
        cuerpo = {
            "empresa": tienda.a.pk,
            "cuenta_pos": pos.pos.pk,
            "cuenta_destino": pos.banco.pk,
            "bruto": "50.00",
        }
        c = cliente_de("admin")
        for _ in range(2):
            r = c.post(
                f"{BASE}/liquidaciones/",
                cuerpo,
                format="json",
                HTTP_IDEMPOTENCY_KEY="liq-clave-001",
            )
            assert r.status_code == 201
        assert LiquidacionTarjeta.objects.sin_ambito().count() == 1

    def test_errores_de_negocio_con_mensaje_claro(self, tienda, pos):
        r = self.crear("admin", tienda, pos, bruto="500.00")
        assert r.status_code == 400 and "por liquidar" in r.json()["error"]["mensaje"]

    def test_anular_pide_motivo_y_devuelve_el_dinero(self, tienda, pos):
        liq = self.crear("admin", tienda, pos).json()
        url = f"{BASE}/liquidaciones/{liq['id']}/anular/"
        assert cliente_de("admin").post(url, {"motivo": ""}, format="json").status_code == 400
        r = cliente_de("admin").post(url, {"motivo": "Lote duplicado"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADO"
        pendiente = cliente_de("admin").get(
            f"{BASE}/liquidaciones/pendientes/", {"empresa": tienda.a.pk}
        )
        assert pendiente.json()[0]["saldo"] == "118.00"
