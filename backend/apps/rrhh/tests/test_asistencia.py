"""RR.HH. (RH3): asistencia diaria, rangos, completar el mes, totales y permisos."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.auditoria import servicios
from apps.mantenimiento.models import Personal
from apps.rrhh import catalogos
from apps.rrhh.models import (
    AsistenciaDia,
    Feriado,
    ParametroLaboral,
    RegimenLaboral,
    TipoAsistencia,
)
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/rrhh"
# Marzo de 2026: el 1 es domingo. El contrato empieza el martes 10 → 22 días cubiertos,
# con domingos 15, 22 y 29 y el feriado del jueves 19 → 18 días de trabajo.
INICIO = "2026-03-10"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    for org in (e.org_a, e.org_b):
        catalogos.sembrar_catalogos_rrhh(org.pk)
    trabajador = Personal.objects.sin_ambito().create(
        empresa=e.emp_a1,
        tipo_documento="DNI",
        numero_documento="45678912",
        nombres="Rosa",
        apellidos="Quispe",
        area="VENTAS",
    )
    regimen = RegimenLaboral.objects.sin_ambito().get(organizacion=e.org_a, codigo="PEQUENA")
    Feriado.objects.sin_ambito().create(
        organizacion=e.org_a, fecha=date(2026, 3, 19), nombre="San José"
    )
    equipo = {
        "e": e,
        "trabajador": trabajador,
        "regimen": regimen,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "rrhh": nuevo_usuario(e.org_a, "rrhh", [e.emp_a1], [("RRHH", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }
    return equipo


def contratar(equipo, inicio=INICIO):
    cliente_de("super").post(
        f"{BASE}/trabajadores/{equipo['trabajador'].pk}/contratos/",
        {
            "regimen": equipo["regimen"].pk,
            "cargo": "Vendedora",
            "fecha_inicio": inicio,
            "sueldo": "1500.00",
        },
        format="json",
    )


def tipo(equipo, codigo):
    return TipoAsistencia.objects.sin_ambito().get(organizacion=equipo["e"].org_a, codigo=codigo).pk


def grilla(api, equipo, mes=3, **extra):
    return api.get(
        f"{BASE}/asistencia/",
        {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": mes, **extra},
    )


def marcar(api, equipo, fecha, codigo="A", **extra):
    cuerpo = {
        "empresa": equipo["e"].emp_a1.pk,
        "personal": equipo["trabajador"].pk,
        "fecha": fecha,
        "tipo": None if codigo is None else tipo(equipo, codigo),
        **extra,
    }
    return api.post(f"{BASE}/asistencia/dia/", cuerpo, format="json")


def rango(api, equipo, desde, hasta, codigo="V", **extra):
    return api.post(
        f"{BASE}/asistencia/rango/",
        {
            "empresa": equipo["e"].emp_a1.pk,
            "personal": equipo["trabajador"].pk,
            "desde": desde,
            "hasta": hasta,
            "tipo": tipo(equipo, codigo),
            **extra,
        },
        format="json",
    )


def completar(api, equipo, descanso="DOMINGO", mes=3):
    return api.post(
        f"{BASE}/asistencia/completar/",
        {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": mes, "descanso": descanso},
        format="json",
    )


def fila(api, equipo, **extra):
    return grilla(api, equipo, **extra).json()["trabajadores"][0]


class TestGrilla:
    def test_muestra_el_mes_con_feriados_y_tipos(self, equipo):
        contratar(equipo)
        r = grilla(cliente_de("super"), equipo)
        assert r.status_code == 200, r.content
        cuerpo = r.json()
        assert len(cuerpo["dias"]) == 31
        assert cuerpo["dias"][18]["feriado"] == "San José"
        assert cuerpo["dias"][0]["semana"] == "dom"
        assert {t["codigo"] for t in cuerpo["tipos"]} >= {"A", "F", "DS", "V", "FER"}

    def test_solo_aparecen_trabajadores_con_contrato_ese_mes(self, equipo):
        assert grilla(cliente_de("super"), equipo).json()["trabajadores"] == []
        contratar(equipo)
        assert len(grilla(cliente_de("super"), equipo).json()["trabajadores"]) == 1
        assert grilla(cliente_de("super"), equipo, mes=2).json()["trabajadores"] == []

    def test_cuenta_los_dias_sin_marcar(self, equipo):
        contratar(equipo)
        f = fila(cliente_de("super"), equipo)
        assert f["totales"]["sin_marcar"] == 22
        assert len(f["cubiertos"]) == 22
        assert f["cubiertos"][0] == INICIO

    def test_mes_invalido(self, equipo):
        assert grilla(cliente_de("super"), equipo, mes=13).status_code == 400
        assert grilla(cliente_de("super"), equipo, mes="x").status_code == 400


class TestMarcarDia:
    def test_marca_cambia_y_borra(self, equipo):
        contratar(equipo)
        api = cliente_de("super")
        assert marcar(api, equipo, "2026-03-11", "A").status_code == 200
        assert fila(api, equipo)["dias"]["2026-03-11"]["tipo"] == "A"
        assert marcar(api, equipo, "2026-03-11", "F").status_code == 200
        f = fila(api, equipo)
        assert f["dias"]["2026-03-11"]["tipo"] == "F"
        assert f["totales"]["faltas"] == 1 and f["totales"]["sin_marcar"] == 21
        assert marcar(api, equipo, "2026-03-11", None).status_code == 200
        assert "2026-03-11" not in fila(api, equipo)["dias"]
        assert AsistenciaDia.objects.sin_ambito().count() == 0

    def test_no_se_marca_un_dia_sin_contrato(self, equipo):
        contratar(equipo)
        r = marcar(cliente_de("super"), equipo, "2026-03-05")
        assert r.status_code == 400
        assert "contrato" in r.content.decode()

    def test_horas_extra_solo_en_dias_trabajados(self, equipo):
        contratar(equipo)
        api = cliente_de("super")
        assert marcar(api, equipo, "2026-03-11", "A", horas_extra="2.5").status_code == 200
        f = fila(api, equipo)
        assert D(str(f["totales"]["horas_extra"])) == D("2.5")
        assert marcar(api, equipo, "2026-03-12", "F", horas_extra="1").status_code == 400
        assert marcar(api, equipo, "2026-03-12", "A", horas_extra="13").status_code == 400

    def test_el_tipo_debe_ser_de_la_organizacion(self, equipo):
        contratar(equipo)
        ajeno = TipoAsistencia.objects.sin_ambito().get(organizacion=equipo["e"].org_b, codigo="A")
        r = cliente_de("super").post(
            f"{BASE}/asistencia/dia/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "personal": equipo["trabajador"].pk,
                "fecha": "2026-03-11",
                "tipo": ajeno.pk,
            },
            format="json",
        )
        assert r.status_code == 400

    def test_un_trabajador_de_otra_empresa_no_se_marca(self, equipo):
        contratar(equipo)
        r = cliente_de("super").post(
            f"{BASE}/asistencia/dia/",
            {
                "empresa": equipo["e"].emp_a2.pk,
                "personal": equipo["trabajador"].pk,
                "fecha": "2026-03-11",
                "tipo": tipo(equipo, "A"),
            },
            format="json",
        )
        assert r.status_code == 400

    def test_horas_trabajadas_usan_la_jornada_del_parametro(self, equipo):
        ParametroLaboral.objects.sin_ambito().create(
            organizacion=equipo["e"].org_a,
            codigo="HORAS_JORNADA",
            valor=D("8"),
            vigente_desde=date(2026, 1, 1),
        )
        contratar(equipo)
        api = cliente_de("super")
        marcar(api, equipo, "2026-03-11", "A")
        marcar(api, equipo, "2026-03-12", "A")
        f = fila(api, equipo)
        assert f["totales"]["laborados"] == 2
        assert D(str(f["totales"]["horas_trabajadas"])) == D("16")


class TestRango:
    def test_marca_vacaciones_solo_en_dias_con_contrato(self, equipo):
        contratar(equipo)
        r = rango(cliente_de("super"), equipo, "2026-03-08", "2026-03-12")
        assert r.status_code == 200, r.content
        assert r.json()["marcados"] == 3  # 10, 11 y 12
        assert fila(cliente_de("super"), equipo)["totales"]["vacaciones"] == 3

    def test_no_pisa_lo_marcado_salvo_que_se_pida(self, equipo):
        contratar(equipo)
        api = cliente_de("super")
        marcar(api, equipo, "2026-03-11", "F")
        assert rango(api, equipo, "2026-03-10", "2026-03-12").json()["marcados"] == 2
        assert fila(api, equipo)["dias"]["2026-03-11"]["tipo"] == "F"
        r = rango(api, equipo, "2026-03-10", "2026-03-12", sobrescribir=True)
        assert r.json()["marcados"] == 3
        assert fila(api, equipo)["dias"]["2026-03-11"]["tipo"] == "V"

    def test_rango_invalido(self, equipo):
        contratar(equipo)
        api = cliente_de("super")
        assert rango(api, equipo, "2026-03-12", "2026-03-10").status_code == 400
        assert rango(api, equipo, "2026-03-10", "2026-08-10").status_code == 400
        assert rango(api, equipo, "2026-03-01", "2026-03-05").status_code == 400  # sin contrato


class TestCompletarMes:
    def test_rellena_asistencia_descanso_y_feriado(self, equipo):
        contratar(equipo)
        r = completar(cliente_de("super"), equipo)
        assert r.status_code == 200, r.content
        assert r.json() == {"trabajadores": 1, "dias": 22}
        f = fila(cliente_de("super"), equipo)
        assert f["totales"]["laborados"] == 18
        assert f["totales"]["descansos"] == 3
        assert f["totales"]["feriados"] == 1
        assert f["totales"]["sin_marcar"] == 0
        assert f["dias"]["2026-03-19"]["tipo"] == "FER"
        assert f["dias"]["2026-03-15"]["tipo"] == "DS"

    def test_sabado_y_domingo_como_descanso(self, equipo):
        contratar(equipo)
        completar(cliente_de("super"), equipo, descanso="SABADO_DOMINGO")
        f = fila(cliente_de("super"), equipo)
        # Sábados 14, 21 y 28 más domingos 15, 22 y 29.
        assert f["totales"]["descansos"] == 6

    def test_no_pisa_lo_ya_marcado_y_repetirlo_no_duplica(self, equipo):
        contratar(equipo)
        api = cliente_de("super")
        marcar(api, equipo, "2026-03-11", "F")
        assert completar(api, equipo).json()["dias"] == 21
        assert fila(api, equipo)["dias"]["2026-03-11"]["tipo"] == "F"
        assert completar(api, equipo).json()["dias"] == 0
        assert AsistenciaDia.objects.sin_ambito().count() == 22

    def test_sin_trabajadores_o_con_descanso_invalido(self, equipo):
        api = cliente_de("super")
        assert completar(api, equipo).status_code == 400
        contratar(equipo)
        assert completar(api, equipo, descanso="LUNES").status_code == 400

    def test_si_falta_un_tipo_activo_avisa(self, equipo):
        contratar(equipo)
        TipoAsistencia.objects.sin_ambito().filter(
            organizacion=equipo["e"].org_a, codigo="FER"
        ).update(estado="INACTIVO")
        r = completar(cliente_de("super"), equipo)
        assert r.status_code == 400
        assert "FER" in r.content.decode()


class TestPermisos:
    def test_el_rol_rrhh_carga_y_el_contador_solo_ve(self, equipo):
        contratar(equipo)
        assert marcar(cliente_de("rrhh"), equipo, "2026-03-11").status_code == 200
        assert grilla(cliente_de("contador"), equipo).status_code == 200
        assert marcar(cliente_de("contador"), equipo, "2026-03-12").status_code == 403
        assert completar(cliente_de("contador"), equipo).status_code == 403

    def test_sin_permiso_no_se_ve_nada(self, equipo):
        contratar(equipo)
        assert grilla(cliente_de("cajero"), equipo).status_code == 403
        assert marcar(cliente_de("cajero"), equipo, "2026-03-11").status_code == 403

    def test_otra_organizacion_no_ve_ni_toca(self, equipo):
        contratar(equipo)
        api = cliente_de("otra_org")
        assert grilla(api, equipo).status_code in (400, 403, 404)
        assert marcar(api, equipo, "2026-03-11").status_code in (400, 403, 404)
        assert AsistenciaDia.objects.sin_ambito().count() == 0

    def test_la_grilla_no_trae_sueldos(self, equipo):
        contratar(equipo)
        assert "1500" not in grilla(cliente_de("rrhh"), equipo).content.decode()
