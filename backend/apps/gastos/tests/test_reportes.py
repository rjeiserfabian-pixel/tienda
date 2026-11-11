"""Reportes de gastos: por categoría, proveedor, sin comprobante, reparto y Registro de compras."""

import io
from datetime import timedelta

import pytest
from openpyxl import load_workbook

from apps.seguridad.tests.conftest import cliente_de

from .test_api import (  # noqa: F401
    BASE,
    HOY,
    crear,
    cuerpo_factura,
    cuerpo_taxi,
)

pytestmark = pytest.mark.django_db


def rango(escena, **extra):
    return {
        "empresa": escena.empresa.pk,
        "desde": str(HOY - timedelta(days=30)),
        "hasta": str(HOY),
        **extra,
    }


def pedir(usuario, ruta, escena, **extra):
    return cliente_de(usuario).get(f"{BASE}/reportes/{ruta}/", rango(escena, **extra))


def sembrar(escena):
    """Un taxi (15), la luz (118) y el alquiler (500, con otro proveedor sin comprobante de IGV)."""
    taxi = crear("cajero", cuerpo_taxi(escena)).json()
    luz = crear("contador", cuerpo_factura(escena)).json()
    alquiler = crear(
        "contador",
        cuerpo_factura(
            escena,
            categoria=escena.categorias["ALQUILER"].pk,
            descripcion="Alquiler del local",
            comprobante_numero="777",
            base_gravada="0.00",
            igv="0.00",
            no_gravado="500.00",
            tipo_comprobante=escena.factura.pk,
            pagos=[{"medio_pago": escena.efectivo.pk, "cuenta": escena.caja.pk, "monto": "500.00"}],
        ),
    ).json()
    return taxi, luz, alquiler


class TestResumen:
    def test_totales_por_categoria_y_por_mes(self, escena):
        sembrar(escena)
        r = pedir("contador", "resumen", escena)
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["totales"] == [
            {
                "moneda": "PEN",
                "total": "633.00",
                "con_comprobante": "618.00",
                "sin_comprobante": "15.00",
            }
        ]
        assert [(c["categoria"], c["monto"], c["porcentaje"]) for c in d["por_categoria"]] == [
            ("Alquiler", "500.00", "79.00"),
            ("Servicios básicos (luz, agua, internet, teléfono)", "118.00", "18.60"),
            ("Movilidad y transporte", "15.00", "2.40"),
        ]
        assert [(m["periodo"], m["monto"]) for m in d["por_mes"]] == [(f"{HOY:%Y-%m}", "633.00")]

    def test_los_anulados_no_cuentan_y_los_dolares_van_aparte(self, escena):
        taxi, _, _ = sembrar(escena)
        cliente_de("admin").post(f"{BASE}/{taxi['id']}/anular/", {"motivo": "Error"}, format="json")
        crear(
            "admin",
            cuerpo_taxi(
                escena,
                moneda="USD",
                tipo_cambio="3.75",
                no_gravado="30.00",
                pagos=[
                    {
                        "medio_pago": escena.efectivo.pk,
                        "cuenta": escena.compras.caja_usd.pk,
                        "monto": "30.00",
                    }
                ],
            ),
        )
        d = pedir("contador", "resumen", escena).json()
        assert {t["moneda"]: t["total"] for t in d["totales"]} == {"PEN": "618.00", "USD": "30.00"}
        assert all(c["moneda"] == "USD" for c in d["por_categoria"] if c["monto"] == "30.00")

    def test_valida_el_rango(self, escena):
        assert (
            cliente_de("contador")
            .get(f"{BASE}/reportes/resumen/", {"empresa": escena.empresa.pk})
            .status_code
            == 400
        )
        r = pedir("contador", "resumen", escena, desde=str(HOY), hasta=str(HOY - timedelta(days=1)))
        assert r.status_code == 400
        r = pedir("contador", "resumen", escena, desde=str(HOY - timedelta(days=900)))
        assert r.status_code == 400


class TestReparto:
    def partes(self, escena):
        return [
            {"empresa": escena.empresa.pk, "porcentaje": "60.00"},
            {"empresa": escena.otra.pk, "porcentaje": "40.00"},
        ]

    def test_cada_empresa_ve_solo_lo_que_le_toca(self, escena):
        assert (
            crear("contador", cuerpo_factura(escena, reparto=self.partes(escena))).status_code
            == 201
        )
        propia = pedir("admin", "resumen", escena).json()["totales"][0]["total"]
        otra = cliente_de("admin").get(
            f"{BASE}/reportes/resumen/",
            {"empresa": escena.otra.pk, "desde": str(HOY - timedelta(days=30)), "hasta": str(HOY)},
        )
        assert otra.status_code == 200, otra.content
        assert (propia, otra.json()["totales"][0]["total"]) == ("70.80", "47.20")

    def test_un_gasto_sin_reparto_no_aparece_en_la_otra_empresa(self, escena):
        crear("contador", cuerpo_factura(escena))
        otra = cliente_de("admin").get(
            f"{BASE}/reportes/resumen/",
            {"empresa": escena.otra.pk, "desde": str(HOY - timedelta(days=30)), "hasta": str(HOY)},
        )
        assert otra.json()["totales"] == []


class TestProveedoresYSinComprobante:
    def test_por_proveedor(self, escena):
        sembrar(escena)
        d = pedir("contador", "proveedores", escena).json()
        assert [(f["proveedor"], f["monto"], f["cantidad"]) for f in d["filas"]] == [
            (escena.proveedor.nombre, "618.00", 2),
            ("Sin proveedor", "15.00", 1),
        ]

    def test_sin_comprobante_dice_quien_y_cuanto(self, escena):
        sembrar(escena)
        crear(
            "cajero",
            cuerpo_taxi(
                escena,
                descripcion="Taxi de vuelta",
                gastado_por="Rosa Quispe",
                no_gravado="20.00",
                pagos=[
                    {"medio_pago": escena.efectivo.pk, "cuenta": escena.caja.pk, "monto": "20.00"}
                ],
            ),
        )
        d = pedir("contador", "sin-comprobante", escena).json()
        assert d["total_filas"] == 2
        assert [(p["persona"], p["monto"], p["cantidad"]) for p in d["por_persona"]] == [
            ("Rosa Quispe", "35.00", 2)
        ]
        assert {f["descripcion"] for f in d["filas"]} == {"Taxi a SUNAT", "Taxi de vuelta"}
        assert all(f["gastado_por"] == "Rosa Quispe" for f in d["filas"])


class TestExcel:
    @pytest.mark.parametrize("ruta", ["resumen", "proveedores", "sin-comprobante"])
    def test_descarga_para_quien_puede_exportar(self, escena, ruta):
        sembrar(escena)
        r = pedir("contador", f"{ruta}/excel", escena)
        assert r.status_code == 200, r.content
        assert "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith('attachment; filename="gastos-')
        assert load_workbook(io.BytesIO(r.content)).active.max_row > 6

    def test_el_cajero_ve_pero_no_descarga(self, escena):
        sembrar(escena)
        assert pedir("cajero", "resumen", escena).status_code == 200
        assert pedir("cajero", "resumen/excel", escena).status_code == 403

    def test_un_vendedor_no_ve_los_reportes(self, escena):
        assert pedir("vendedor", "resumen", escena).status_code == 403

    def test_un_texto_con_formula_queda_como_texto(self, escena):
        crear("admin", cuerpo_taxi(escena, descripcion="=1+1", gastado_por="=HYPERLINK(1)"))
        libro = load_workbook(io.BytesIO(pedir("admin", "sin-comprobante/excel", escena).content))
        celdas = [
            c
            for fila in libro.active.iter_rows()
            for c in fila
            if c.value in ("=1+1", "=HYPERLINK(1)")
        ]
        assert len(celdas) == 2 and all(c.data_type == "s" for c in celdas)


class TestRegistroDeCompras:
    def registro(self, escena, **extra):
        return cliente_de("contador").get(
            "/api/v1/compras/reportes/registro-compras/vista/", rango(escena, **extra)
        )

    def test_los_gastos_con_comprobante_entran_y_se_pueden_apagar(self, escena):
        escena.compras.comprar()
        crear("contador", cuerpo_factura(escena))  # con comprobante: entra
        crear("cajero", cuerpo_taxi(escena))  # sin comprobante: no entra
        d = self.registro(escena).json()
        assert d["total_filas"] == 2
        assert sorted(f["origen"] for f in d["filas"]) == ["COMPRA", "GASTO"]
        gasto = next(f for f in d["filas"] if f["origen"] == "GASTO")
        assert (gasto["gravada"], gasto["igv"], gasto["total"], gasto["serie"]) == (
            "100.00", "18.00", "118.00", "F001",
        )  # fmt: skip
        assert d["totales"]["total"] == "236.00"
        solo = self.registro(escena, incluir_gastos="0").json()
        assert [f["origen"] for f in solo["filas"]] == ["COMPRA"]
        assert solo["totales"]["total"] == "118.00"

    def test_un_gasto_anulado_no_entra(self, escena):
        g = crear("contador", cuerpo_factura(escena)).json()
        cliente_de("admin").post(f"{BASE}/{g['id']}/anular/", {"motivo": "Error"}, format="json")
        assert self.registro(escena).json()["total_filas"] == 0

    def test_el_excel_trae_la_columna_de_origen(self, escena):
        crear("contador", cuerpo_factura(escena))
        r = cliente_de("contador").get("/api/v1/compras/reportes/registro-compras/", rango(escena))
        assert r.status_code == 200, r.content
        hoja = load_workbook(io.BytesIO(r.content)).active
        titulos = [c.value for c in hoja[7]]
        assert titulos[-1] == "Origen"
        assert hoja.cell(row=8, column=len(titulos)).value == "Gasto"
