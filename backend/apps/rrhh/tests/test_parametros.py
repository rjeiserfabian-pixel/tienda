"""RR.HH. (RH1): valores base, parámetros con vigencia, tasas de AFP, regímenes y permisos."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.auditoria import servicios
from apps.rrhh import catalogos
from apps.rrhh.models import (
    DETALLE_PARAMETROS,
    ConceptoPlanilla,
    ParametroLaboral,
    RegimenLaboral,
    TipoAsistencia,
)
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/rrhh"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    for org in (e.org_a, e.org_b):
        catalogos.sembrar_catalogos_rrhh(org.pk)
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1], [("SUPERADMIN", None)]),
        "admin": nuevo_usuario(e.org_a, "admin", [e.emp_a1], [("ADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def parametro(api, codigo="RMV", valor="1130", desde="2026-01-01", **extra):
    return api.post(
        f"{BASE}/parametros/",
        {"codigo": codigo, "valor": valor, "vigente_desde": desde, **extra},
        format="json",
    )


class TestSiembra:
    def test_carga_los_valores_base_de_cada_organizacion(self, equipo):
        org = equipo["e"].org_a
        assert RegimenLaboral.objects.sin_ambito().filter(organizacion=org).count() == 2
        assert TipoAsistencia.objects.sin_ambito().filter(organizacion=org).count() == 9
        assert ConceptoPlanilla.objects.sin_ambito().filter(organizacion=org).count() >= 20
        # Cada organización tiene lo suyo.
        assert (
            RegimenLaboral.objects.sin_ambito().filter(organizacion=equipo["e"].org_b).count() == 2
        )

    def test_pequena_empresa_y_general_traen_sus_reglas(self, equipo):
        org = equipo["e"].org_a.pk
        general = RegimenLaboral.objects.sin_ambito().get(organizacion_id=org, codigo="GENERAL")
        pequena = RegimenLaboral.objects.sin_ambito().get(organizacion_id=org, codigo="PEQUENA")
        assert (general.dias_vacaciones, general.factor_gratificacion, general.factor_cts) == (
            30,
            D("1.00"),
            D("1.00"),
        )
        assert (pequena.dias_vacaciones, pequena.factor_gratificacion, pequena.factor_cts) == (
            15,
            D("0.50"),
            D("0.50"),
        )
        assert general.tasa_essalud == pequena.tasa_essalud == D("9.00")

    def test_repetirla_no_duplica_ni_pisa_lo_editado_ni_revive_lo_eliminado(self, equipo):
        org = equipo["e"].org_a.pk
        regimen = RegimenLaboral.objects.sin_ambito().get(organizacion_id=org, codigo="GENERAL")
        regimen.nombre = "General de la empresa"
        regimen.save()
        TipoAsistencia.objects.sin_ambito().get(organizacion_id=org, codigo="PR").delete()
        assert catalogos.sembrar_catalogos_rrhh(org) == {
            "regimenes": 0,
            "tipos_asistencia": 0,
            "conceptos": 0,
        }
        assert RegimenLaboral.objects.sin_ambito().get(
            organizacion_id=org, codigo="GENERAL"
        ).nombre == ("General de la empresa")
        assert (
            not TipoAsistencia.objects.sin_ambito()
            .filter(organizacion_id=org, codigo="PR")
            .exists()
        )

    def test_no_se_siembran_valores_legales_ni_codigos_plame(self, equipo):
        org = equipo["e"].org_a
        assert not ParametroLaboral.objects.sin_ambito().filter(organizacion=org).exists()
        assert (
            not ConceptoPlanilla.objects.sin_ambito()
            .filter(organizacion=org)
            .exclude(codigo_plame="")
            .exists()
        )

    def test_los_tipos_de_asistencia_son_los_de_la_hoja(self, equipo):
        tipos = {
            t.codigo: t
            for t in TipoAsistencia.objects.sin_ambito().filter(organizacion=equipo["e"].org_a)
        }
        assert set(tipos) == {"A", "DS", "F", "PR", "DP", "DM", "V", "FER", "TF"}
        assert (tipos["A"].categoria, tipos["A"].cuenta_dia_laborado) == ("LABORADO", True)
        assert (tipos["F"].categoria, tipos["F"].se_paga) == ("FALTA", False)
        assert tipos["TF"].cuenta_dia_laborado is True and tipos["V"].cuenta_dia_laborado is False


class TestVigencia:
    def test_el_valor_vigente_es_el_ultimo_anterior_a_la_fecha(self, equipo):
        api = cliente_de("contador")
        for desde, valor in (
            ("2025-01-01", "1025"),
            ("2026-01-01", "1130"),
            ("2026-10-01", "1230"),
        ):
            assert parametro(api, valor=valor, desde=desde).status_code == 201
        org = equipo["e"].org_a.pk
        assert catalogos.valor_vigente(org, "RMV", date(2025, 6, 1)) == D("1025")
        assert catalogos.valor_vigente(org, "RMV", date(2026, 9, 30)) == D("1130")
        assert catalogos.valor_vigente(org, "RMV", date(2026, 10, 1)) == D("1230")
        assert catalogos.valor_vigente(org, "RMV", date(2024, 12, 31)) is None  # antes de todo

    def test_un_parametro_inactivo_no_cuenta(self, equipo):
        api = cliente_de("contador")
        creado = parametro(api).json()
        r = api.patch(f"{BASE}/parametros/{creado['id']}/", {"estado": "INACTIVO"}, format="json")
        assert r.status_code == 200
        assert catalogos.valor_vigente(equipo["e"].org_a.pk, "RMV", date(2026, 6, 1)) is None

    def test_cada_organizacion_tiene_sus_valores(self, equipo):
        parametro(cliente_de("contador"))
        assert catalogos.valor_vigente(equipo["e"].org_b.pk, "RMV", date(2026, 6, 1)) is None

    def test_el_resumen_dice_cuales_faltan(self, equipo):
        api = cliente_de("contador")
        parametro(api)
        r = api.get(f"{BASE}/parametros/resumen/", {"fecha": "2026-06-01"})
        assert r.status_code == 200
        datos = r.json()
        assert datos["faltan"] == len(DETALLE_PARAMETROS) - 1
        rmv = next(p for p in datos["parametros"] if p["codigo"] == "RMV")
        assert (rmv["valor"], rmv["falta"], rmv["unidad"]) == ("1130.0000", False, "SOLES")
        uit = next(p for p in datos["parametros"] if p["codigo"] == "UIT")
        assert uit["valor"] is None and uit["falta"] is True
        assert api.get(f"{BASE}/parametros/resumen/", {"fecha": "mal"}).status_code == 400
        # En una fecha anterior al valor cargado, también falta.
        assert api.get(f"{BASE}/parametros/resumen/", {"fecha": "2025-01-01"}).json()[
            "faltan"
        ] == len(DETALLE_PARAMETROS)

    def test_las_tasas_de_afp_tambien_tienen_vigencia(self, equipo):
        api = cliente_de("contador")
        tasas = {
            "afp": "HABITAT",
            "aporte_obligatorio": "10.00",
            "prima_seguro": "1.37",
            "comision_flujo": "1.47",
            "comision_mixta": "1.25",
            "remuneracion_maxima_asegurable": "12672.65",
        }
        for desde, prima in (("2026-01-01", "1.37"), ("2026-07-01", "1.40")):
            r = api.post(
                f"{BASE}/tasas-afp/",
                {**tasas, "prima_seguro": prima, "vigente_desde": desde},
                format="json",
            )
            assert r.status_code == 201, r.content
        org = equipo["e"].org_a.pk
        assert catalogos.tasa_afp_vigente(org, "HABITAT", date(2026, 3, 1)).prima_seguro == D(
            "1.37"
        )
        assert catalogos.tasa_afp_vigente(org, "HABITAT", date(2026, 8, 1)).prima_seguro == D(
            "1.40"
        )
        assert catalogos.tasa_afp_vigente(org, "INTEGRA", date(2026, 8, 1)) is None
        repetida = api.post(
            f"{BASE}/tasas-afp/", {**tasas, "vigente_desde": "2026-01-01"}, format="json"
        )
        assert repetida.status_code == 400 or repetida.status_code == 409

    def test_los_valores_se_validan(self, equipo):
        api = cliente_de("contador")
        assert parametro(api, codigo="ONP", valor="130").status_code == 400  # más de 100 %
        assert parametro(api, codigo="DIAS_MES", valor="45").status_code == 400
        assert parametro(api, codigo="HORAS_JORNADA", valor="30").status_code == 400
        assert parametro(api, codigo="RMV", valor="-5").status_code == 400
        assert parametro(api, codigo="NO_EXISTE").status_code == 400
        assert parametro(api, valor="1130", desde="2026-01-01").status_code == 201
        assert parametro(api, valor="1200", desde="2026-01-01").status_code in (
            400,
            409,
        )  # misma fecha

    def test_el_parametro_no_cambia_de_tipo(self, equipo):
        api = cliente_de("contador")
        creado = parametro(api).json()
        r = api.patch(f"{BASE}/parametros/{creado['id']}/", {"codigo": "UIT"}, format="json")
        assert r.status_code == 400
        r = api.patch(f"{BASE}/parametros/{creado['id']}/", {"valor": "1150"}, format="json")
        assert r.status_code == 200 and r.json()["valor"] == "1150.0000"


class TestPermisos:
    def test_el_contador_y_el_administrador_mantienen_los_valores(self, equipo):
        assert parametro(cliente_de("contador")).status_code == 201
        assert parametro(cliente_de("admin"), codigo="UIT", valor="5500").status_code == 201
        assert parametro(cliente_de("super"), codigo="ONP", valor="13").status_code == 201

    def test_el_resto_no_los_ve_ni_los_cambia(self, equipo):
        cajero = cliente_de("cajero")
        assert cajero.get(f"{BASE}/parametros/").status_code == 403
        assert parametro(cajero).status_code == 403
        assert cajero.get(f"{BASE}/regimenes/").status_code == 403

    def test_el_contador_no_elimina(self, equipo):
        creado = parametro(cliente_de("contador")).json()
        assert (
            cliente_de("contador").delete(f"{BASE}/parametros/{creado['id']}/").status_code == 403
        )
        assert cliente_de("admin").delete(f"{BASE}/parametros/{creado['id']}/").status_code == 204

    def test_otra_organizacion_no_ve_lo_ajeno(self, equipo):
        creado = parametro(cliente_de("contador")).json()
        ajeno = cliente_de("otra_org")
        assert ajeno.get(f"{BASE}/parametros/").json()["count"] == 0
        assert (
            ajeno.patch(
                f"{BASE}/parametros/{creado['id']}/", {"valor": "1"}, format="json"
            ).status_code
            == 404
        )


class TestCatalogos:
    def test_regimen_nuevo_se_valida(self, equipo):
        api = cliente_de("contador")
        cuerpo = {
            "codigo": "micro",
            "nombre": "Microempresa",
            "tasa_essalud": "0",
            "dias_vacaciones": 15,
            "factor_gratificacion": "0",
            "factor_cts": "0",
        }
        r = api.post(f"{BASE}/regimenes/", cuerpo, format="json")
        assert r.status_code == 201 and r.json()["codigo"] == "MICRO"  # se normaliza
        assert api.post(f"{BASE}/regimenes/", cuerpo, format="json").status_code in (400, 409)
        malo = {**cuerpo, "codigo": "X", "tasa_essalud": "120"}
        assert api.post(f"{BASE}/regimenes/", malo, format="json").status_code == 400
        assert (
            api.post(
                f"{BASE}/regimenes/",
                {**malo, "tasa_essalud": "9", "dias_vacaciones": 90},
                format="json",
            ).status_code
            == 400
        )

    def test_los_conceptos_del_sistema_estan_protegidos(self, equipo):
        api = cliente_de("contador")
        sueldo = ConceptoPlanilla.objects.sin_ambito().get(
            organizacion=equipo["e"].org_a, codigo="SUELDO_BASICO"
        )
        assert sueldo.es_del_sistema is True
        url = f"{BASE}/conceptos/{sueldo.pk}/"
        assert api.patch(url, {"codigo": "OTRO"}, format="json").status_code == 400
        assert api.patch(url, {"tipo": "DESCUENTO"}, format="json").status_code == 400
        assert api.patch(url, {"estado": "INACTIVO"}, format="json").status_code == 400
        # Lo que el contador sí puede ajustar: el código PLAME y a qué está afecto.
        r = api.patch(url, {"codigo_plame": "0121", "afecto_renta5": False}, format="json")
        assert r.status_code == 200 and r.json()["codigo_plame"] == "0121"
        assert cliente_de("admin").delete(url).status_code == 400

    def test_un_concepto_propio_si_se_puede_crear_y_eliminar(self, equipo):
        api = cliente_de("contador")
        r = api.post(
            f"{BASE}/conceptos/",
            {"codigo": "bono_puntualidad", "nombre": "Bono de puntualidad", "tipo": "INGRESO"},
            format="json",
        )
        assert r.status_code == 201 and r.json()["es_del_sistema"] is False
        assert r.json()["codigo"] == "BONO_PUNTUALIDAD"
        assert cliente_de("admin").delete(f"{BASE}/conceptos/{r.json()['id']}/").status_code == 204

    def test_feriados_por_anio_y_sin_repetir_fecha(self, equipo):
        api = cliente_de("contador")
        for fecha, nombre in (
            ("2026-07-28", "Fiestas Patrias"),
            ("2026-12-25", "Navidad"),
            ("2027-01-01", "Año Nuevo"),
        ):
            assert (
                api.post(
                    f"{BASE}/feriados/", {"fecha": fecha, "nombre": nombre}, format="json"
                ).status_code
                == 201
            )
        assert api.get(f"{BASE}/feriados/", {"anio": 2026}).json()["count"] == 2
        assert api.get(f"{BASE}/feriados/", {"anio": "x"}).status_code == 400
        repetido = api.post(
            f"{BASE}/feriados/", {"fecha": "2026-12-25", "nombre": "Otro"}, format="json"
        )
        assert repetido.status_code in (400, 409)

    def test_los_tipos_de_asistencia_se_pueden_ampliar(self, equipo):
        api = cliente_de("contador")
        r = api.post(
            f"{BASE}/tipos-asistencia/",
            {
                "codigo": "lic",
                "nombre": "Licencia con goce",
                "categoria": "DESCANSO_PAGADO",
                "se_paga": True,
            },
            format="json",
        )
        assert r.status_code == 201 and r.json()["codigo"] == "LIC"
        lista = api.get(f"{BASE}/tipos-asistencia/", {"categoria": "FALTA"}).json()
        assert sorted(t["codigo"] for t in lista["results"]) == ["F", "PR"]

    def test_la_siembra_desde_la_api_es_idempotente(self, equipo):
        api = cliente_de("contador")
        for ruta in ("regimenes", "tipos-asistencia", "conceptos"):
            r = api.post(f"{BASE}/{ruta}/sembrar/")
            assert r.status_code == 200 and r.json() == {"creadas": 0}
        TipoAsistencia.objects.sin_ambito().filter(
            organizacion=equipo["e"].org_a, codigo="DM"
        ).update(eliminado_en=None)  # (no se elimina: sigue completo)
        assert cliente_de("cajero").post(f"{BASE}/regimenes/sembrar/").status_code == 403
