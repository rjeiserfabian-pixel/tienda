"""Reportes de ventas: lo vendido menos las notas de crédito; la utilidad, solo con permiso."""

from datetime import timedelta
from decimal import Decimal as D
from io import BytesIO

import pytest
from openpyxl import load_workbook

from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import notas_credito, reportes
from apps.ventas.exceptions import VentaInvalida

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas/reportes"


@pytest.fixture
def ventas(tienda):
    """Laptop: 4 a 100 (costo 50) al contado = 472; Mouse: 2 a 50 (costo 20) = 118."""
    laptop = tienda.producto("Laptop", costo="50", precios={"PUBLICO": "100"})
    mouse = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"})
    v1 = tienda.vender([tienda.linea(laptop, 4)], [tienda.cobro(tienda.efectivo, "472.00")])
    v2 = tienda.vender([tienda.linea(mouse, 2)], [tienda.cobro(tienda.efectivo, "118.00")])
    return type("V", (), {"v1": v1, "v2": v2, "laptop": laptop, "mouse": mouse})


def rango(tienda):
    hoy = tienda.entorno.hoy
    return hoy - timedelta(days=5), hoy + timedelta(days=1)


class TestCalculo:
    def test_resumen_suma_lo_vendido_y_separa_contado_de_credito(self, tienda, ventas):
        d = reportes.resumen(tienda.a, *rango(tienda), con_utilidad=True)
        (t,) = d["totales"]
        assert (t["moneda"], t["cantidad"]) == ("PEN", 2)
        assert (t["valor"], t["igv"], t["total"]) == (D("500.00"), D("90.00"), D("590.00"))
        assert (t["contado"], t["credito"], t["notas"], t["neto"]) == (
            D("590.00"),
            D("0"),
            D("0"),
            D("590.00"),
        )
        # utilidad = 500 − (4×50 + 2×20)
        assert (t["costo"], t["utilidad"]) == (D("240.00"), D("260.00"))
        assert len(d["por_mes"]) == 1

    def test_las_notas_de_credito_restan_venta_costo_y_unidades(self, tienda, ventas):
        comp = ventas.v1.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        d = reportes.resumen(tienda.a, *rango(tienda), con_utilidad=True)
        (t,) = d["totales"]
        assert (t["total"], t["notas"], t["neto"]) == (D("590.00"), D("118.00"), D("472.00"))
        assert (t["costo"], t["utilidad"]) == (D("190.00"), D("210.00"))
        p = {f["producto"]: f for f in reportes.por_producto(tienda.a, *rango(tienda))["filas"]}
        assert (p["Laptop"]["unidades"], p["Laptop"]["valor"]) == (D("3.000"), D("300.00"))

    def test_sin_permiso_de_utilidad_no_hay_costo(self, tienda, ventas):
        d = reportes.resumen(tienda.a, *rango(tienda))
        assert "costo" not in d["totales"][0] and "utilidad" not in d["por_mes"][0]
        assert "costo" not in reportes.por_producto(tienda.a, *rango(tienda))["filas"][0]
        assert "costo" not in reportes.registro(tienda.a, *rango(tienda))["filas"][0]

    def test_por_vendedor_cliente_y_producto(self, tienda, ventas):
        d = reportes.por_vendedor(tienda.a, *rango(tienda))
        (f,) = d["filas"]
        assert (f["vendedor"], f["cantidad"], f["neto"]) == ("Rosa Pérez", 2, D("590.00"))
        (c,) = reportes.por_cliente(tienda.a, *rango(tienda))["filas"]
        assert (c["cliente"], c["total"]) == ("CLIENTES VARIOS", D("590.00"))
        productos = reportes.por_producto(tienda.a, *rango(tienda), con_utilidad=True)["filas"]
        assert [p["producto"] for p in productos] == ["Laptop", "Mouse"]
        assert (productos[0]["utilidad"], productos[0]["margen"]) == (D("200.00"), D("50.0"))

    def test_por_metodo_cuenta_cobros_y_devoluciones(self, tienda, ventas):
        comp = ventas.v2.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "59.00")],
        )
        (f,) = reportes.por_metodo(tienda.a, *rango(tienda))["filas"]
        assert (f["ventas"], f["cuotas"], f["devuelto"], f["neto"]) == (
            D("590.00"),
            D("0"),
            D("59.00"),
            D("531.00"),
        )

    def test_el_registro_trae_notas_en_negativo_y_respeta_el_limite(self, tienda, ventas):
        comp = ventas.v1.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        d = reportes.registro(tienda.a, *rango(tienda))
        assert d["total_filas"] == 3 and sum(f["total"] for f in d["filas"]) == D("472.00")
        corto = reportes.registro(tienda.a, *rango(tienda), limite=2)
        assert corto["truncado"] and len(corto["filas"]) == 2

    def test_una_empresa_no_ve_lo_de_la_otra(self, tienda, ventas):
        assert reportes.resumen(tienda.b, *rango(tienda))["totales"] == []

    def test_los_comprobantes_anulados_no_cuentan(self, tienda, ventas):
        from apps.ventas import servicios

        servicios.anular_comprobante(ventas.v2.comprobantes.get(), motivo="Error de venta")
        (t,) = reportes.resumen(tienda.a, *rango(tienda))["totales"]
        assert (t["cantidad"], t["total"]) == (1, D("472.00"))

    def test_valida_el_rango(self, tienda):
        hoy = tienda.entorno.hoy
        with pytest.raises(VentaInvalida, match="rango"):
            reportes.resumen(tienda.a, None, hoy)
        with pytest.raises(VentaInvalida, match="posterior"):
            reportes.resumen(tienda.a, hoy, hoy - timedelta(days=1))
        with pytest.raises(VentaInvalida, match="dos años"):
            reportes.resumen(tienda.a, hoy - timedelta(days=800), hoy)


class TestApi:
    def params(self, tienda):
        d, h = rango(tienda)
        return {"empresa": tienda.a.pk, "desde": str(d), "hasta": str(h)}

    @pytest.mark.parametrize(
        "ruta", ["resumen", "vendedores", "productos", "clientes", "metodos", "registro"]
    )
    def test_cada_reporte_responde_y_se_descarga(self, tienda, ventas, ruta):
        c = cliente_de("admin")
        r = c.get(f"{BASE}/{ruta}/", self.params(tienda))
        assert r.status_code == 200, r.content
        assert r["Cache-Control"] == "no-store"
        x = c.get(f"{BASE}/{ruta}/excel/", self.params(tienda))
        assert x.status_code == 200 and "spreadsheetml" in x["Content-Type"]
        assert load_workbook(BytesIO(x.content)).active.max_row >= 4

    def test_la_utilidad_depende_del_permiso(self, tienda, ventas):
        con = cliente_de("admin").get(f"{BASE}/resumen/", self.params(tienda)).json()
        assert con["con_utilidad"] is True and "utilidad" in con["totales"][0]
        sin = cliente_de("vendedor").get(f"{BASE}/resumen/", self.params(tienda)).json()
        assert sin["con_utilidad"] is False and "utilidad" not in sin["totales"][0]

    def test_descargar_exige_permiso_y_el_contador_puede(self, tienda, ventas):
        assert (
            cliente_de("vendedor").get(f"{BASE}/resumen/excel/", self.params(tienda)).status_code
            == 403
        )
        assert (
            cliente_de("contador").get(f"{BASE}/resumen/excel/", self.params(tienda)).status_code
            == 200
        )

    def test_pide_rango_y_empresa(self, tienda):
        c = cliente_de("admin")
        assert c.get(f"{BASE}/resumen/", {"empresa": tienda.a.pk}).status_code == 400
        assert c.get(f"{BASE}/resumen/").status_code in (400, 403)
