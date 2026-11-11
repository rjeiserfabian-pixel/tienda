"""Fixtures compartidas de las pruebas de planilla, vacaciones y CTS.

Los valores legales son DATOS DE PRUEBA, no los vigentes.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.auditoria import servicios
from apps.mantenimiento.models import CuentaFinanciera, Personal
from apps.mantenimiento.pagos import sembrar_catalogos_pago
from apps.rrhh import catalogos
from apps.rrhh.models import ParametroLaboral, RegimenLaboral, TasaAfp, TramoRenta5
from apps.seguridad.tests.conftest import cliente_de

BASE = "/api/v1/rrhh"

DESDE = date(2026, 1, 1)

PARAMETROS = {
    "RMV": "1130",
    "UIT": "1000",  # chica a propósito: así la renta de 5.ª se nota en las pruebas
    "ASIGNACION_FAMILIAR": "10",
    "ONP": "13",
    "DIAS_MES": "30",
    "HORAS_JORNADA": "8",
    "HORAS_HE_PRIMERAS": "2",
    "SOBRETASA_HE_PRIMERAS": "25",
    "SOBRETASA_HE_SIGUIENTES": "35",
    "SOBRETASA_FERIADO": "100",
    "DEDUCCION_RENTA5_UIT": "7",
    "BONIF_EXTRAORDINARIA": "9",
}
TRAMOS = ((1, "5", "8"), (2, "20", "14"), (3, "35", "17"), (4, "45", "20"), (5, None, "30"))


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    for org in (e.org_a, e.org_b):
        catalogos.sembrar_catalogos_rrhh(org.pk)
    sembrar_catalogos_pago(e.org_a.pk)
    for codigo, valor in PARAMETROS.items():
        ParametroLaboral.objects.sin_ambito().create(
            organizacion=e.org_a, codigo=codigo, valor=D(valor), vigente_desde=DESDE
        )
    for orden, hasta, tasa in TRAMOS:
        TramoRenta5.objects.sin_ambito().create(
            organizacion=e.org_a,
            vigente_desde=DESDE,
            orden=orden,
            hasta_uit=None if hasta is None else D(hasta),
            tasa=D(tasa),
        )
    TasaAfp.objects.sin_ambito().create(
        organizacion=e.org_a,
        afp="HABITAT",
        vigente_desde=DESDE,
        aporte_obligatorio=D("10"),
        prima_seguro=D("1.49"),
        comision_flujo=D("1.47"),
        comision_mixta=D("0.47"),
        remuneracion_maxima_asegurable=D("12000"),
    )
    trabajador = Personal.objects.sin_ambito().create(
        empresa=e.emp_a1,
        tipo_documento="DNI",
        numero_documento="45678912",
        nombres="Rosa",
        apellidos="Quispe",
        area="VENTAS",
    )
    regimen = RegimenLaboral.objects.sin_ambito().get(organizacion=e.org_a, codigo="PEQUENA")
    equipo = {
        "e": e,
        "trabajador": trabajador,
        "caja": CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.emp_a1,
            nombre="Caja soles",
            tipo="CAJA",
            moneda="PEN",
            saldo_inicial=D("5000"),
            fecha_saldo_inicial=date(2026, 1, 1),
        ),
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "rrhh": nuevo_usuario(e.org_a, "rrhh", [e.emp_a1], [("RRHH", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }
    api = cliente_de("super")
    api.post(
        f"{BASE}/trabajadores/{trabajador.pk}/contratos/",
        {
            "regimen": regimen.pk,
            "cargo": "Vendedora",
            "fecha_inicio": "2026-01-02",
            "sueldo": "1500.00",
        },
        format="json",
    )
    api.patch(
        f"{BASE}/trabajadores/{trabajador.pk}/datos-laborales/",
        {"sistema_pension": "ONP", "metodo_pago": "EFECTIVO"},
        format="json",
    )
    return equipo
