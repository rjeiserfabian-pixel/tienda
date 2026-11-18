"""Llevar las comisiones liquidadas a la planilla de RR.HH. como el ingreso «Comisiones»."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.comisiones import a_planilla
from apps.comisiones.cierre import CierreInvalido
from apps.comisiones.models import LineaLiquidacion, LiquidacionComision
from apps.core.tenant import establecer_contexto
from apps.rrhh.models import PlanillaConcepto
from apps.rrhh.tests.test_planilla import montos, planilla_completa, trabajador_de

pytestmark = pytest.mark.django_db


def _linea(equipo, monto="300.00", con_ficha=True):
    e = equipo["e"]
    org = e.org_a
    liq = LiquidacionComision.objects.sin_ambito().create(
        organizacion=org, periodo="2026-02", cerrada_en=timezone.now(), total_a_pagar=D(monto)
    )
    trabajador = equipo["trabajador"]
    return LineaLiquidacion.objects.sin_ambito().create(
        organizacion=org,
        liquidacion=liq,
        clave=f"P:{trabajador.pk}" if con_ficha else "U:00000000-0000-0000-0000-000000000009",
        personal=trabajador if con_ficha else None,
        nombre="Rosa Quispe",
        comisiones_ventas=D(monto),
        total=D(monto),
        a_pagar=D(monto),
        detalle={},
    )


def _contexto(equipo):
    e = equipo["e"]
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk], e.usuario_id)


def test_la_comision_entra_a_la_planilla_y_cuenta_como_ingreso(equipo):
    api, planilla, _ = planilla_completa(equipo)
    _contexto(equipo)
    linea = _linea(equipo)
    hecha = a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))
    assert hecha.estado == "EN_PLANILLA" and hecha.planilla_id == planilla["id"]
    assert hecha.planilla_concepto_id is not None and hecha.enviada_en is not None
    renglon = PlanillaConcepto.objects.sin_ambito().get(pk=hecha.planilla_concepto_id)
    assert (renglon.codigo, renglon.monto, renglon.manual) == ("COMISIONES", D("300.00"), True)
    assert "Comisiones de 2026-02" in renglon.explicacion
    # La planilla la cuenta como ingreso (y sobre ella se calculan los descuentos).
    detalle = trabajador_de(api, planilla)
    assert montos(detalle)["COMISIONES"] == D("300.00")


def test_no_se_envia_dos_veces_pero_si_se_quito_de_la_planilla_se_puede_reenviar(equipo):
    api, planilla, _ = planilla_completa(equipo)
    _contexto(equipo)
    linea = _linea(equipo)
    a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))
    with pytest.raises(CierreInvalido, match="ya está en la planilla"):
        a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))
    linea.refresh_from_db()
    r = api.delete(f"/api/v1/rrhh/planillas/{planilla['id']}/ajustes/{linea.planilla_concepto_id}/")
    assert r.status_code == 200, r.content
    _contexto(equipo)
    a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))


def test_sin_planilla_o_con_la_planilla_cerrada_no_se_puede(equipo):
    _contexto(equipo)
    linea = _linea(equipo)
    with pytest.raises(CierreInvalido, match="No existe la planilla"):
        a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))
    api, planilla, detalle = planilla_completa(equipo)
    r = api.post(
        f"/api/v1/rrhh/planillas/{planilla['id']}/cerrar/",
        {"neto_visto": detalle["neto"]},
        format="json",
    )
    assert r.status_code == 200, r.content
    _contexto(equipo)
    with pytest.raises(CierreInvalido, match="cerrada"):
        a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))


def test_quien_no_tiene_ficha_de_personal_se_paga_aparte(equipo):
    _contexto(equipo)
    linea = _linea(equipo, con_ficha=False)
    with pytest.raises(CierreInvalido, match="ficha de personal"):
        a_planilla.llevar_a_planilla(linea.pk, date(2026, 3, 1))
    hecha = a_planilla.marcar_pagada_aparte(linea.pk, "Efectivo el 20/12")
    assert hecha.estado == "PAGADA_APARTE" and hecha.pagada_nota == "Efectivo el 20/12"
