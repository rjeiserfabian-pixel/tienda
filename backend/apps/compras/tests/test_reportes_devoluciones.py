"""Registro de compras con devoluciones (restan) y reporte de devoluciones por proveedor."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

from datetime import timedelta
from io import BytesIO

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento.models import CuentaFinanciera
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)
from .test_api import cuerpo, datos, registrar  # noqa: F401
from .test_api_devoluciones import cuerpo_devolucion, devolver, reembolso

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras"


def comprar(datos, **extra):
    r = registrar(cliente_de("almacenero"), cuerpo(datos, **extra))
    assert r.status_code == 201, r.content
    return r.json()


def rango(datos, **extra):
    hoy = timezone.localdate()
    return {
        "empresa": datos.mundo.e1.pk,
        "desde": (hoy - timedelta(days=10)).isoformat(),
        "hasta": hoy.isoformat(),
        **extra,
    }


def registro(datos, usuario="contador", **extra):
    return cliente_de(usuario).get(
        f"{BASE}/reportes/registro-compras/vista/", rango(datos, **extra)
    )


def reporte(datos, usuario="contador", **extra):
    return cliente_de(usuario).get(f"{BASE}/reportes/devoluciones/vista/", rango(datos, **extra))


def hacer_devolucion(datos, compra, cantidad="4", **extra):
    r = devolver(cliente_de("admin"), cuerpo_devolucion(datos, compra, cantidad, **extra))
    assert r.status_code == 201, r.content
    return r.json()


class TestRegistroConDevoluciones:
    def test_la_devolucion_entra_restando(self, datos):
        compra = comprar(datos, comprobante_numero="501")
        d = hacer_devolucion(datos, compra, comprobante_numero="9001")
        r = registro(datos)
        assert r.status_code == 200, r.content
        j = r.json()
        assert j["total_filas"] == 2
        fila_compra, fila_nota = j["filas"]
        assert fila_compra["origen"] == "COMPRA" and fila_compra["total"] == "118.00"
        assert fila_nota["origen"] == "DEVOLUCION"
        assert [fila_nota[k] for k in ("tipo", "serie", "comprobante")] == ["07", "FC01", "9001"]
        assert [fila_nota[k] for k in ("gravada", "igv", "total", "total_soles")] == [
            "-40.00",
            "-7.20",
            "-47.20",
            "-47.20",
        ]
        assert fila_nota["modifica"] == "01 F001-501"
        assert fila_nota["numero"] == d["numero"]
        assert j["totales"] == {
            "gravada": "60.00",
            "igv": "10.80",
            "exonerada": "0.00",
            "inafecta": "0.00",
            "total": "70.80",
        }

    def test_se_puede_apagar(self, datos):
        compra = comprar(datos)
        hacer_devolucion(datos, compra)
        j = registro(datos, incluir_devoluciones=0).json()
        assert j["total_filas"] == 1 and j["totales"]["total"] == "118.00"

    def test_la_devolucion_anulada_no_entra(self, datos):
        compra = comprar(datos)
        d = hacer_devolucion(datos, compra)
        cliente_de("admin").post(
            f"{BASE}/devoluciones/{d['id']}/anular/", {"motivo": "Error"}, format="json"
        )
        j = registro(datos).json()
        assert j["total_filas"] == 1 and j["totales"]["total"] == "118.00"

    def test_cuenta_en_el_periodo_de_la_nota_no_de_la_compra(self, datos):
        # La compra es de ayer y la nota de hoy: el rango de solo hoy trae únicamente la nota.
        compra = comprar(datos)
        hacer_devolucion(datos, compra)
        hoy = timezone.localdate().isoformat()
        j = registro(datos, desde=hoy, hasta=hoy).json()
        assert [f["origen"] for f in j["filas"]] == ["DEVOLUCION"]
        assert j["totales"]["total"] == "-47.20"

    def test_en_dolares_usa_el_tipo_de_cambio_de_la_compra(self, datos):
        caja_usd = CuentaFinanciera.objects.sin_ambito().create(
            empresa=datos.mundo.e1, nombre="Caja dólares", tipo="CAJA", moneda="USD"
        )
        compra = comprar(
            datos,
            moneda="USD",
            tipo_cambio="3.7500",
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": caja_usd.pk, "monto": "118.00"}],
        )
        hacer_devolucion(datos, compra)
        j = registro(datos).json()
        nota = next(f for f in j["filas"] if f["origen"] == "DEVOLUCION")
        assert (nota["moneda"], nota["total"], nota["total_soles"]) == ("USD", "-47.20", "-177.00")
        assert j["totales"]["total"] == "265.50"

    def test_el_excel_trae_la_nota_con_su_documento_y_el_neto(self, datos):
        compra = comprar(datos, comprobante_numero="502")
        hacer_devolucion(datos, compra, comprobante_numero="9002")
        r = cliente_de("contador").get(f"{BASE}/reportes/registro-compras/", rango(datos))
        assert r.status_code == 200, r.content
        hoja = load_workbook(BytesIO(r.content)).active
        filas = [[c.value for c in fila] for fila in hoja.iter_rows(min_row=7, max_row=10)]
        cabecera = filas[0]
        assert cabecera[18:20] == ["Documento que modifica", "Origen"]
        nota = filas[2]
        assert nota[2:5] == ["07", "FC01", "9002"]
        assert nota[8] == -40 and nota[13] == -47.2 and nota[16] == -47.2
        assert nota[18:20] == ["01 F001-502", "Devolución"]
        assert filas[3][7] == "TOTALES EN SOLES" and filas[3][16] == 70.8


class TestReporteDeDevoluciones:
    def test_resumen_por_proveedor_y_detalle(self, datos):
        c1, c2 = comprar(datos), comprar(datos)
        hacer_devolucion(datos, c1, "4", reembolsos=[reembolso(datos, "20")])
        hacer_devolucion(datos, c2, "10")
        r = reporte(datos)
        assert r.status_code == 200, r.content
        j = r.json()
        assert len(j["resumen"]) == 1
        f = j["resumen"][0]
        assert (f["proveedor"], f["moneda"], f["cantidad"]) == ("Distribuidora Selva", "PEN", 2)
        assert (f["total"], f["igv"]) == ("165.20", "25.20")
        assert (f["aplicado_a_deuda"], f["reembolsado"], f["saldo_a_favor"]) == (
            "0.00",
            "20.00",
            "145.20",
        )
        assert f["costo_soles"] == "140.00"
        assert j["totales"]["PEN"]["total"] == "165.20"
        assert j["costo_soles"] == "140.00"
        assert j["total_filas"] == 2
        d = j["detalle"][0]
        assert d["compra"].startswith("01 F001-")
        assert d["motivo"] in ("Devolución por ítem", "Devolución total")
        assert d["razon"] == "Mercadería dañada"

    def test_soles_y_dolares_no_se_mezclan(self, datos):
        caja_usd = CuentaFinanciera.objects.sin_ambito().create(
            empresa=datos.mundo.e1, nombre="Caja dólares", tipo="CAJA", moneda="USD"
        )
        en_soles = comprar(datos)
        en_dolares = comprar(
            datos,
            moneda="USD",
            tipo_cambio="3.7500",
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": caja_usd.pk, "monto": "118.00"}],
        )
        hacer_devolucion(datos, en_soles, "4")
        hacer_devolucion(datos, en_dolares, "4")
        j = reporte(datos).json()
        assert {f["moneda"] for f in j["resumen"]} == {"PEN", "USD"}
        assert j["totales"]["PEN"]["total"] == "47.20" and j["totales"]["USD"]["total"] == "47.20"
        assert j["costo_soles"] == "190.00"  # 40 (soles) + 40 dólares a 3,75 = 150

    def test_las_anuladas_no_cuentan(self, datos):
        compra = comprar(datos)
        d = hacer_devolucion(datos, compra)
        cliente_de("admin").post(
            f"{BASE}/devoluciones/{d['id']}/anular/", {"motivo": "Error"}, format="json"
        )
        j = reporte(datos).json()
        assert j["total_filas"] == 0 and j["resumen"] == [] and j["totales"] == {}

    def test_permisos_y_aislamiento(self, datos):
        compra = comprar(datos)
        hacer_devolucion(datos, compra)
        assert reporte(datos, "contador").status_code == 200
        assert reporte(datos, "admin").status_code == 200
        for usuario in ("almacenero", "vendedor", "vendedor_a2"):
            assert reporte(datos, usuario).status_code == 403, usuario
        assert reporte(datos, "otra_org").status_code in (400, 403)

    def test_el_rango_es_obligatorio_y_acotado(self, datos):
        api = cliente_de("contador")
        url = f"{BASE}/reportes/devoluciones/vista/"
        base = {"empresa": datos.mundo.e1.pk}
        assert api.get(url, base).status_code == 400
        hoy = timezone.localdate()
        largo = {**base, "desde": (hoy - timedelta(days=400)).isoformat(), "hasta": hoy.isoformat()}
        assert api.get(url, largo).status_code == 400
        futuro = {**base, "desde": hoy.isoformat(), "hasta": (hoy + timedelta(days=1)).isoformat()}
        assert api.get(url, futuro).status_code == 400

    def test_excel_con_resumen_detalle_y_auditoria(self, datos):
        compra = comprar(datos)
        hacer_devolucion(datos, compra, "4", reembolsos=[reembolso(datos, "20")])
        r = cliente_de("contador").get(f"{BASE}/reportes/devoluciones/", rango(datos))
        assert r.status_code == 200, r.content
        assert "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith(
            'attachment; filename="devoluciones-proveedores_'
        )
        libro = load_workbook(BytesIO(r.content))
        assert libro.sheetnames == ["Resumen por proveedor", "Detalle"]
        resumen = [
            [c.value for c in f]
            for f in libro["Resumen por proveedor"].iter_rows(min_row=7, max_row=10)
        ]
        assert resumen[0][2:5] == ["Proveedor", "Moneda", "Devoluciones"]
        assert resumen[1][2:5] == ["Distribuidora Selva", "PEN", 1]
        assert resumen[1][5] == 47.2 and resumen[1][8] == 20 and resumen[1][9] == 27.2
        assert resumen[2][2] == "TOTAL EN PEN" and resumen[2][5] == 47.2
        detalle = [[c.value for c in f] for f in libro["Detalle"].iter_rows(min_row=7, max_row=8)]
        assert detalle[0][5:7] == ["Nota de crédito", "Compra que modifica"]
        assert detalle[1][8] == "Mercadería dañada" and detalle[1][10] == 47.2
        assert AuditoriaEvento.objects.filter(accion="compras.devoluciones_exportadas").exists()

    def test_nombres_con_formula_se_escriben_como_texto(self, datos):
        datos.proveedor.nombre = '=HYPERLINK("http://malo")'
        datos.proveedor.save()
        compra = comprar(datos)
        hacer_devolucion(datos, compra)
        r = cliente_de("contador").get(f"{BASE}/reportes/devoluciones/", rango(datos))
        libro = load_workbook(BytesIO(r.content))
        assert libro["Resumen por proveedor"].cell(row=8, column=3).data_type == "s"
        assert libro["Detalle"].cell(row=8, column=5).data_type == "s"

    def test_excel_sin_permiso(self, datos):
        for usuario in ("almacenero", "vendedor"):
            r = cliente_de(usuario).get(f"{BASE}/reportes/devoluciones/", rango(datos))
            assert r.status_code == 403, usuario
