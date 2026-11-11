"""RR.HH. (RH7): saldo y registro de vacaciones, y cálculo y depósito de la CTS.

Reutiliza el equipo de las pruebas de planilla (una trabajadora desde el 2 de enero de 2026, sueldo
de 1,500, régimen de pequeña empresa). Los valores legales son DATOS DE PRUEBA.
"""

import itertools
from datetime import date
from decimal import Decimal as D

import pytest

from apps.core.tenant import establecer_contexto, limpiar_contexto
from apps.mantenimiento.models import CuentaFinanciera
from apps.rrhh import vacaciones as servicio_vacaciones
from apps.rrhh.models import AsistenciaDia
from apps.rrhh.tests.test_planilla import (  # noqa: F401
    BASE,
    completar_marzo,
    completar_mes,
    preparar,
    saldo_caja,
)
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

_claves = itertools.count(1)


# ---------------------------------------------------------------------------
# Vacaciones
# ---------------------------------------------------------------------------
def registrar(api, equipo, desde, hasta, **extra):
    return api.post(
        f"{BASE}/vacaciones/",
        {
            "empresa": equipo["e"].emp_a1.pk,
            "personal": equipo["trabajador"].pk,
            "desde": desde,
            "hasta": hasta,
            **extra,
        },
        format="json",
    )


def marcas_v(equipo) -> int:
    return (
        AsistenciaDia.objects.sin_ambito()
        .filter(personal=equipo["trabajador"], tipo__categoria="VACACIONES")
        .count()
    )


class TestVacaciones:
    def test_los_dias_ganados_crecen_mes_a_mes(self, equipo):
        pk = equipo["trabajador"].pk
        e = equipo["e"]
        establecer_contexto(e.org_a.pk, [e.emp_a1.pk], None)
        try:
            # Desde el 2 de enero: al 2 de julio son 6 meses completos de 12; 15 días al año.
            s = servicio_vacaciones.saldos_de([pk], hoy=date(2026, 7, 2))[pk]
            assert s["meses_servicio"] == 6 and s["ganados"] == D("7.50")
            assert s["saldo"] == D("7.50")
            # Un día antes todavía son 5 meses.
            s = servicio_vacaciones.saldos_de([pk], hoy=date(2026, 7, 1))[pk]
            assert s["meses_servicio"] == 5 and s["ganados"] == D("6.25")
        finally:
            limpiar_contexto()

    def test_registrar_descuenta_del_saldo_y_marca_la_asistencia(self, equipo):
        api = cliente_de("super")
        r = registrar(api, equipo, "2026-03-02", "2026-03-06", observacion="Descanso")
        assert r.status_code == 201, r.content
        assert r.json()["dias"] == 5 and r.json()["marco_asistencia"] is True
        assert marcas_v(equipo) == 5
        fila = api.get(f"{BASE}/vacaciones/saldos/?empresa={equipo['e'].emp_a1.pk}").json()
        s = fila["results"][0]
        assert s["tomados"] == 5 and D(s["saldo"]) == D(s["ganados"]) - 5

    def test_sin_marcar_asistencia_solo_cuenta_los_dias(self, equipo):
        api = cliente_de("super")
        r = registrar(api, equipo, "2026-03-02", "2026-03-04", marcar_asistencia=False)
        assert r.status_code == 201, r.content
        assert marcas_v(equipo) == 0
        listado = api.get(f"{BASE}/vacaciones/?empresa={equipo['e'].emp_a1.pk}").json()
        assert listado["count"] == 1 and listado["results"][0]["dias"] == 3

    def test_no_se_pide_mas_que_el_saldo_ni_se_cruzan(self, equipo):
        api = cliente_de("super")
        r = registrar(api, equipo, "2026-02-01", "2026-04-01")  # 60 días
        assert r.status_code == 400 and "de saldo" in r.content.decode()
        assert registrar(api, equipo, "2026-03-02", "2026-03-06").status_code == 201
        r = registrar(api, equipo, "2026-03-05", "2026-03-08")
        assert r.status_code == 400 and "cruza" in r.content.decode()
        r = registrar(api, equipo, "2026-03-10", "2026-03-09")
        assert r.status_code == 400
        r = registrar(api, equipo, "2025-12-01", "2025-12-03")  # antes de su servicio
        assert r.status_code == 400 and "inicio de su servicio" in r.content.decode()

    def test_anular_devuelve_los_dias_y_quita_las_marcas(self, equipo):
        api = cliente_de("super")
        vacacion = registrar(api, equipo, "2026-03-02", "2026-03-06").json()
        url = f"{BASE}/vacaciones/{vacacion['id']}/anular/"
        assert api.post(url, {}, format="json").status_code == 400  # el motivo es obligatorio
        r = api.post(url, {"motivo": "Se postergó"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADA"
        assert marcas_v(equipo) == 0
        assert api.post(url, {"motivo": "otra vez"}, format="json").status_code == 400
        s = api.get(f"{BASE}/vacaciones/saldos/?empresa={equipo['e'].emp_a1.pk}").json()
        assert s["results"][0]["tomados"] == 0

    def test_con_la_planilla_cerrada_no_se_anula(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        vacacion = registrar(api, equipo, "2026-03-02", "2026-03-06").json()
        planilla = preparar(api, equipo).json()
        # Las vacaciones se pagan con el sueldo normal: el neto no cambia.
        assert D(planilla["total_neto"]) == D("1305.00")
        assert (
            api.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json").status_code
            == 200
        )
        r = api.post(f"{BASE}/vacaciones/{vacacion['id']}/anular/", {"motivo": "x"}, format="json")
        assert r.status_code == 400 and "cerrada" in r.content.decode()
        assert marcas_v(equipo) == 5

    def test_permisos(self, equipo):
        empresa = equipo["e"].emp_a1.pk
        saldos = f"{BASE}/vacaciones/saldos/?empresa={empresa}"
        assert cliente_de("contador").get(saldos).status_code == 200
        assert cliente_de("cajero").get(saldos).status_code == 403
        assert (
            registrar(cliente_de("contador"), equipo, "2026-03-02", "2026-03-03").status_code == 403
        )
        assert registrar(cliente_de("rrhh"), equipo, "2026-03-02", "2026-03-03").status_code == 201


# ---------------------------------------------------------------------------
# CTS
# ---------------------------------------------------------------------------
def calcular_cts(api, equipo, anio, periodo):
    return api.post(
        f"{BASE}/cts/",
        {"empresa": equipo["e"].emp_a1.pk, "anio": anio, "periodo": periodo},
        format="json",
    )


def depositar(api, equipo, cts, clave=None, cuenta=None, **extra):
    return api.post(
        f"{BASE}/cts/{cts['id']}/depositar/",
        {"fecha": "2026-05-15", "cuenta": cuenta or equipo["caja"].pk, **extra},
        format="json",
        HTTP_IDEMPOTENCY_KEY=clave or f"cts-{next(_claves):08d}",
    )


class TestCts:
    def test_calculo_de_mayo(self, equipo):
        api = cliente_de("super")
        r = calcular_cts(api, equipo, 2026, "MAYO")
        assert r.status_code == 201, r.content
        cts = r.json()
        fila = cts["trabajadores"][0]
        # Del 2 de enero al 30 de abril: febrero, marzo y abril completos (3 meses) y 30 días de
        # enero. No había gratificación de diciembre (aún no trabajaba).
        assert fila["meses"] == 3 and fila["dias"] == 30
        assert D(fila["sexto_gratificacion"]) == D("0")
        # 1,500 ÷ 12 × 3 + 1,500 ÷ 360 × 30 = 500; pequeña empresa: la mitad.
        assert D(fila["monto"]) == D("250.00") and D(cts["total"]) == D("250.00")
        assert cts["puede_depositar"] is True

    def test_sexto_de_la_gratificacion_real_de_julio(self, equipo):
        api = cliente_de("super")
        completar_mes(api, equipo, 7)
        julio = preparar(api, equipo, mes=7).json()
        assert (
            api.post(f"{BASE}/planillas/{julio['id']}/cerrar/", {}, format="json").status_code
            == 200
        )
        fila = calcular_cts(api, equipo, 2026, "NOVIEMBRE").json()["trabajadores"][0]
        # Gratificación de julio 625.00 ÷ 6 = 104.17; (1,604.17 ÷ 12 × 6) × 0.5 = 401.04.
        assert D(fila["sexto_gratificacion"]) == D("104.17")
        assert D(fila["monto"]) == D("401.04")
        assert not any("estimó" in a["texto"] for a in fila["avisos"])

    def test_sin_planilla_de_julio_se_estima_y_se_avisa(self, equipo):
        fila = calcular_cts(cliente_de("super"), equipo, 2026, "NOVIEMBRE").json()["trabajadores"][
            0
        ]
        # Estimada: 1,500 × 0.5 ÷ 6 = 125.00; (1,625 ÷ 12 × 6) × 0.5 = 406.25.
        assert D(fila["sexto_gratificacion"]) == D("125.00") and D(fila["monto"]) == D("406.25")
        assert any("estimó" in a["texto"] for a in fila["avisos"])

    def test_no_se_calcula_un_semestre_que_no_termino_ni_se_repite(self, equipo):
        api = cliente_de("super")
        assert calcular_cts(api, equipo, 2099, "MAYO").status_code == 400
        assert calcular_cts(api, equipo, 2026, "MAYO").status_code == 201
        r = calcular_cts(api, equipo, 2026, "MAYO")
        assert r.status_code == 400 and "Ya existe" in r.content.decode()

    def test_depositar_anular_y_reintento(self, equipo):
        api = cliente_de("super")
        cts = calcular_cts(api, equipo, 2026, "MAYO").json()
        primera = depositar(
            api, equipo, cts, clave="cts-repetida-1", total="250.00", referencia="Op 5"
        )
        repetida = depositar(
            api, equipo, cts, clave="cts-repetida-1", total="250.00", referencia="Op 5"
        )
        assert primera.status_code == 200, primera.content
        assert primera.json()["estado"] == "DEPOSITADO"
        assert repetida["Idempotency-Replayed"] == "true"
        assert saldo_caja(equipo) == D("4750.00")
        # Depositada: ya no se recalcula, descarta ni deposita otra vez.
        assert api.post(f"{BASE}/cts/{cts['id']}/recalcular/").status_code == 400
        assert api.delete(f"{BASE}/cts/{cts['id']}/").status_code == 400
        assert depositar(api, equipo, cts).status_code == 400
        url = f"{BASE}/cts/{cts['id']}/anular-deposito/"
        assert api.post(url, {}, format="json").status_code == 400  # el motivo es obligatorio
        r = api.post(url, {"motivo": "Cuenta equivocada"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "CALCULADO"
        assert saldo_caja(equipo) == D("5000.00")

    def test_si_la_cts_cambio_no_deposita(self, equipo):
        api = cliente_de("super")
        cts = calcular_cts(api, equipo, 2026, "MAYO").json()
        r = depositar(api, equipo, cts, total="999.00")
        assert r.status_code == 400 and "cambió" in r.content.decode()
        assert saldo_caja(equipo) == D("5000.00")

    def test_sin_saldo_no_se_deposita(self, equipo, settings):
        settings.CAJA_BLOQUEA_SALDO_NEGATIVO = True
        api = cliente_de("super")
        cts = calcular_cts(api, equipo, 2026, "MAYO").json()
        pobre = CuentaFinanciera.objects.sin_ambito().create(
            empresa=equipo["e"].emp_a1,
            nombre="Caja pobre",
            tipo="CAJA",
            moneda="PEN",
            saldo_inicial=D("10"),
            fecha_saldo_inicial=date(2026, 1, 1),
        )
        r = depositar(api, equipo, cts, cuenta=pobre.pk)
        assert r.status_code in (400, 409), r.content
        assert api.get(f"{BASE}/cts/{cts['id']}/").json()["estado"] == "CALCULADO"

    def test_descartar_y_permisos(self, equipo):
        api = cliente_de("super")
        cts = calcular_cts(api, equipo, 2026, "MAYO").json()
        assert cliente_de("contador").get(f"{BASE}/cts/{cts['id']}/").status_code == 200
        assert depositar(cliente_de("contador"), equipo, cts).status_code == 403
        assert calcular_cts(cliente_de("contador"), equipo, 2026, "NOVIEMBRE").status_code == 403
        assert (
            cliente_de("cajero").get(f"{BASE}/cts/?empresa={equipo['e'].emp_a1.pk}").status_code
            == 403
        )
        assert api.delete(f"{BASE}/cts/{cts['id']}/").status_code == 204
        assert calcular_cts(api, equipo, 2026, "MAYO").status_code == 201
