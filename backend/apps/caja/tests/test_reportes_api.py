"""API de los reportes de caja: permisos, vistas, descargas y errores."""

import io
from datetime import date

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.core.tenant import establecer_contexto
from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja
from apps.mantenimiento.models import ConceptoCaja, CuentaFinanciera
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/caja/reportes"
HOY = timezone.localdate()
ANTERIOR = date(HOY.year - 1, 12, 1) if HOY.month == 1 else date(HOY.year, HOY.month - 1, 1)


@pytest.fixture
def datos(mundo, nuevo_usuario):  # noqa: F811
    e = mundo.e
    nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", e.emp_a1)])
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_conceptos_caja(e.org_a.pk)
    caja = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1, nombre="Caja soles", tipo="CAJA", moneda="PEN", cuenta_contable="101"
    )
    conceptos = {
        c.codigo: c for c in ConceptoCaja.objects.sin_ambito().filter(organizacion=e.org_a)
    }
    cliente_de("admin").post(
        "/api/v1/caja/movimientos/",
        {
            "empresa": e.emp_a1.pk,
            "cuenta": caja.pk,
            "tipo": "INGRESO",
            "concepto": conceptos["APORTE_CAPITAL"].pk,
            "monto": "250.00",
            "fecha": str(ANTERIOR.replace(day=10)),
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="reporte-de-prueba-000001",
    )
    return type("Datos", (), {"mundo": mundo, "caja": caja})


def pedir(usuario, datos, ruta, **extra):
    parametros = {"empresa": datos.mundo.e1.pk, **extra}
    return cliente_de(usuario).get(f"{BASE}/{ruta}/", parametros)


class TestPermisos:
    @pytest.mark.parametrize("ruta", ["saldos", "libro", "flujo", "proyeccion", "conceptos"])
    def test_un_cajero_no_ve_los_reportes(self, datos, ruta):
        assert pedir("cajero", datos, ruta).status_code == 403

    @pytest.mark.parametrize("ruta", ["saldos/excel", "libro/excel", "libro/ple"])
    def test_ni_los_descarga(self, datos, ruta):
        assert pedir("cajero", datos, ruta, formato="1.1").status_code == 403

    def test_la_empresa_es_obligatoria(self, datos):
        assert cliente_de("contador").get(f"{BASE}/saldos/").status_code == 400


class TestVistas:
    def test_saldos(self, datos):
        r = pedir("contador", datos, "saldos", fecha=str(HOY))
        assert r.status_code == 200, r.content
        assert r.json()["totales"] == [{"moneda": "PEN", "saldo": "250.00"}]

    def test_libro(self, datos):
        r = pedir("contador", datos, "libro", anio=ANTERIOR.year, mes=ANTERIOR.month)
        assert r.status_code == 200
        [caja] = r.json()["efectivo"]
        assert (caja["nombre"], caja["saldo_final"]) == ("Caja soles", "250.00")
        assert caja["lineas"][0]["debe"] == "250.00"

    def test_flujo_y_conceptos(self, datos):
        rango = {"desde": str(ANTERIOR), "hasta": str(HOY)}
        flujo = pedir("contador", datos, "flujo", **rango).json()
        assert flujo["totales"][0]["ingresos"] == "250.00"
        conceptos = pedir("contador", datos, "conceptos", **rango).json()
        assert conceptos["filas"][0]["concepto"] == "Aporte de capital"

    def test_el_flujo_pide_el_rango(self, datos):
        assert pedir("contador", datos, "flujo").status_code == 400
        assert (
            pedir("contador", datos, "flujo", desde=str(HOY), hasta="2000-01-01").status_code == 400
        )

    def test_proyeccion(self, datos):
        r = pedir("contador", datos, "proyeccion", meses=2)
        assert r.status_code == 200
        assert r.json()["saldo_hoy"][0]["saldo"] == "250.00"
        assert pedir("contador", datos, "proyeccion", meses=40).status_code == 400


class TestDescargas:
    def test_libro_en_excel(self, datos):
        r = pedir("contador", datos, "libro/excel", anio=ANTERIOR.year, mes=ANTERIOR.month)
        assert r.status_code == 200
        assert "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith('attachment; filename="libro-caja-bancos_')
        assert load_workbook(io.BytesIO(r.content)).sheetnames == ["1.1 Efectivo", "1.2 Bancos"]
        assert r["Cache-Control"] == "no-store"

    def test_otros_excel(self, datos):
        rango = {"desde": str(ANTERIOR), "hasta": str(HOY)}
        for ruta, extra in (
            ("saldos/excel", {}),
            ("flujo/excel", rango),
            ("conceptos/excel", rango),
        ):
            r = pedir("contador", datos, ruta, **extra)
            assert r.status_code == 200, (ruta, r.content)

    def test_ple_en_txt(self, datos):
        r = pedir(
            "contador", datos, "libro/ple", anio=ANTERIOR.year, mes=ANTERIOR.month, formato="1.1"
        )
        assert r.status_code == 200, r.content
        assert r["Content-Disposition"].endswith('010100001111.TXT"')
        assert r.content.decode().count("\r\n") == 1

    def test_ple_pide_el_formato_y_los_datos_de_las_cuentas(self, datos):
        assert pedir("contador", datos, "libro/ple").status_code == 400
        datos.caja.cuenta_contable = ""
        datos.caja.save()
        r = pedir(
            "contador", datos, "libro/ple", anio=ANTERIOR.year, mes=ANTERIOR.month, formato="1.1"
        )
        assert r.status_code == 400
        assert "cuenta contable" in r.content.decode()
