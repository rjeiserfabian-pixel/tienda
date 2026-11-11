"""RR.HH. (RH5): planilla mensual por conceptos, cierre, reapertura y bloqueo del mes.

Los valores legales de estas pruebas (RMV, UIT, tasas…) son DATOS DE PRUEBA, no los vigentes.
Marzo de 2026 tiene 31 días y cinco domingos (1, 8, 15, 22 y 29).
"""

import itertools
from datetime import date
from decimal import Decimal as D
from urllib.parse import unquote

import pytest
from django.utils import timezone

from apps.mantenimiento.models import CuentaFinanciera, Personal
from apps.rrhh import planilla as servicio
from apps.rrhh.models import (
    ConceptoPlanilla,
    CuotaAdelanto,
    ParametroLaboral,
    RegimenLaboral,
    TasaAfp,
    TipoAsistencia,
    TramoRenta5,
)
from apps.rrhh.tests.fixtures_rrhh import TRAMOS
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/rrhh"
_claves = itertools.count(1)


# ---------------------------------------------------------------------------
# Ayudas
# ---------------------------------------------------------------------------
def tipo_id(equipo, codigo: str) -> int:
    return TipoAsistencia.objects.sin_ambito().get(organizacion=equipo["e"].org_a, codigo=codigo).pk


def marcar(api, equipo, dia: str, codigo: str, horas_extra="0"):
    r = api.post(
        f"{BASE}/asistencia/dia/",
        {
            "empresa": equipo["e"].emp_a1.pk,
            "personal": equipo["trabajador"].pk,
            "fecha": dia,
            "tipo": tipo_id(equipo, codigo),
            "horas_extra": horas_extra,
        },
        format="json",
    )
    assert r.status_code in (200, 201), r.content
    return r


def completar_marzo(api, equipo):
    r = api.post(
        f"{BASE}/asistencia/completar/",
        {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": 3, "descanso": "DOMINGO"},
        format="json",
    )
    assert r.status_code == 200, r.content


def preparar(api, equipo, mes=3, clave=None):
    return api.post(
        f"{BASE}/planillas/",
        {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": mes},
        format="json",
        HTTP_IDEMPOTENCY_KEY=clave or f"plan-{next(_claves):08d}",
    )


def trabajador_de(api, planilla_json):
    fila = planilla_json["trabajadores"][0]
    r = api.get(f"{BASE}/planillas/{planilla_json['id']}/trabajadores/{fila['id']}/")
    assert r.status_code == 200, r.content
    return r.json()


def montos(det) -> dict:
    return {c["codigo"]: D(c["monto"]) for c in det["conceptos"]}


def planilla_completa(equipo, **datos):
    """Marzo completo y planilla preparada; devuelve (cliente, planilla, detalle)."""
    api = cliente_de("super")
    if datos:
        r = api.patch(
            f"{BASE}/trabajadores/{equipo['trabajador'].pk}/datos-laborales/", datos, format="json"
        )
        assert r.status_code == 200, r.content
    completar_marzo(api, equipo)
    r = preparar(api, equipo)
    assert r.status_code == 201, r.content
    return api, r.json(), trabajador_de(api, r.json())


# ---------------------------------------------------------------------------
class TestCalculo:
    def test_mes_completo_con_onp(self, equipo):
        _, planilla, det = planilla_completa(equipo)
        m = montos(det)
        assert m["SUELDO_BASICO"] == D("1500.00")
        assert m["ONP"] == D("195.00")  # 13 % de 1,500
        assert m["ESSALUD"] == D("135.00")  # 9 % del empleador
        assert D(det["neto"]) == D("1305.00")
        assert det["dias_laborados"] == 26 and det["dias_contrato"] == 31
        assert D(det["horas_trabajadas"]) == D("208.00")
        assert D(planilla["total_neto"]) == D("1305.00")
        assert D(planilla["total_aportes"]) == D("135.00")
        assert planilla["num_errores"] == 0 and planilla["puede_cerrar"] is True

    def test_una_falta_descuenta_un_dia_y_baja_la_base_de_pension(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        marcar(api, equipo, "2026-03-10", "F")
        planilla = preparar(api, equipo).json()
        m = montos(trabajador_de(api, planilla))
        assert m["DESCUENTO_FALTAS"] == D("50.00")  # 1,500 ÷ 30
        assert m["ONP"] == D("188.50")  # 13 % de 1,450
        assert D(planilla["total_neto"]) == D("1261.50")

    def test_asignacion_familiar_horas_extra_y_trabajo_en_feriado(self, equipo):
        api = cliente_de("super")
        api.patch(
            f"{BASE}/trabajadores/{equipo['trabajador'].pk}/datos-laborales/",
            {"asignacion_familiar": True},
            format="json",
        )
        completar_marzo(api, equipo)
        marcar(api, equipo, "2026-03-11", "A", horas_extra="3")
        marcar(api, equipo, "2026-03-12", "TF")
        det = trabajador_de(api, preparar(api, equipo).json())
        m = montos(det)
        assert m["ASIGNACION_FAMILIAR"] == D("113.00")  # 10 % de la RMV
        # Valor de la hora 50 ÷ 8 = 6.25: 2 h con +25 % y 1 h con +35 %.
        assert m["HORAS_EXTRA_PRIMERAS"] == D("15.63")
        assert m["HORAS_EXTRA_SIGUIENTES"] == D("8.44")
        assert m["TRABAJO_FERIADO"] == D("50.00")  # un valor del día × 100 %
        assert D(det["horas_extra"]) == D("3.00")

    def test_afp_con_comision_sobre_flujo(self, equipo):
        _, _, det = planilla_completa(
            equipo,
            sistema_pension="AFP",
            afp="HABITAT",
            tipo_comision="FLUJO",
            cuspp="123456ABCDEF",
        )
        m = montos(det)
        assert m["AFP_APORTE"] == D("150.00")
        assert m["AFP_PRIMA"] == D("22.35")
        assert m["AFP_COMISION"] == D("22.05")
        assert "ONP" not in m
        assert D(det["neto"]) == D("1305.60")

    def test_sin_tasas_de_afp_hay_error_y_no_se_cierra(self, equipo):
        TasaAfp.objects.sin_ambito().all().delete()
        _, planilla, _ = planilla_completa(
            equipo, sistema_pension="AFP", afp="HABITAT", tipo_comision="FLUJO"
        )
        assert planilla["num_errores"] >= 1 and planilla["puede_cerrar"] is False
        assert any("tasas" in a["texto"] for a in planilla["avisos"])

    def test_renta_de_quinta_por_tramos(self, equipo):
        _, _, det = planilla_completa(equipo, paga_renta_5ta=True)
        # 10 meses × 1,500 + 2 gratificaciones de medio sueldo = 16,500; menos 7 UIT = 9,500.
        # Impuesto: 5,000 × 8 % + 4,500 × 14 % = 1,030; en marzo se reparte entre 12 meses.
        assert montos(det)["RENTA_5TA"] == D("85.83")

    def test_el_impuesto_aplica_cada_tasa_solo_a_su_tramo(self):
        tramos = [
            TramoRenta5(orden=i, hasta_uit=None if h is None else D(h), tasa=D(t))
            for i, h, t in TRAMOS
        ]
        assert servicio._impuesto_anual(D("0"), D("1000"), tramos) == D("0")
        assert servicio._impuesto_anual(D("5000"), D("1000"), tramos) == D("400")
        assert servicio._impuesto_anual(D("9500"), D("1000"), tramos) == D("1030")
        # 50 UIT: 400 + 2,100 + 2,550 + 2,000 + 1,500 = 8,550
        assert servicio._impuesto_anual(D("50000"), D("1000"), tramos) == D("8550")

    def test_sin_valor_legal_no_se_inventa(self, equipo):
        ParametroLaboral.objects.sin_ambito().filter(codigo="DIAS_MES").delete()
        _, planilla, det = planilla_completa(equipo)
        assert planilla["puede_cerrar"] is False
        assert any("Días del mes" in a["texto"] for a in planilla["avisos"])
        assert "SUELDO_BASICO" not in montos(det)

    def test_dias_sin_marcar_son_error(self, equipo):
        api = cliente_de("super")
        planilla = preparar(api, equipo).json()
        det = trabajador_de(api, planilla)
        assert any(a["nivel"] == "ERROR" and "Faltan marcar" in a["texto"] for a in det["avisos"])
        assert planilla["puede_cerrar"] is False

    def test_contrato_que_empieza_a_mitad_de_mes_paga_los_dias_con_contrato(self, equipo):
        e = equipo["e"]
        nuevo = Personal.objects.sin_ambito().create(
            empresa=e.emp_a1,
            tipo_documento="DNI",
            numero_documento="70000001",
            nombres="Ana",
            apellidos="Zamora",
            area="VENTAS",
        )
        regimen = RegimenLaboral.objects.sin_ambito().get(organizacion=e.org_a, codigo="PEQUENA")
        api = cliente_de("super")
        api.post(
            f"{BASE}/trabajadores/{nuevo.pk}/contratos/",
            {
                "regimen": regimen.pk,
                "cargo": "Cajera",
                "fecha_inicio": "2026-03-21",
                "sueldo": "1500.00",
            },
            format="json",
        )
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        fila = next(f for f in planilla["trabajadores"] if "Zamora" in f["nombre_completo"])
        det = api.get(f"{BASE}/planillas/{planilla['id']}/trabajadores/{fila['id']}/").json()
        assert det["dias_contrato"] == 11  # del 21 al 31
        # 11 días de 30 × 1,500 = 550
        assert montos(det)["SUELDO_BASICO"] == D("550.00")


# ---------------------------------------------------------------------------
class TestAdelantosYAjustes:
    def entregar(self, api, equipo, monto="500.00"):
        r = api.post(
            f"{BASE}/adelantos/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "personal": equipo["trabajador"].pk,
                "tipo": "ADELANTO",
                "fecha": "2026-03-05",
                "monto": monto,
                "cuenta": equipo["caja"].pk,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"adel-{next(_claves):08d}",
        )
        assert r.status_code == 201, r.content
        return r.json()

    def test_la_cuota_del_mes_se_descuenta(self, equipo):
        api = cliente_de("super")
        self.entregar(api, equipo)
        completar_marzo(api, equipo)
        det = trabajador_de(api, preparar(api, equipo).json())
        m = montos(det)
        assert m["ADELANTOS"] == D("500.00")
        assert D(det["neto"]) == D("805.00")  # 1,500 − 195 de ONP − 500

    def test_neto_negativo_es_error_y_diferir_la_cuota_lo_arregla(self, equipo):
        api = cliente_de("super")
        self.entregar(api, equipo, monto="1400.00")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        det = trabajador_de(api, planilla)
        assert D(det["neto"]) < 0
        assert planilla["puede_cerrar"] is False
        linea = next(c for c in det["conceptos"] if c["codigo"] == "ADELANTOS")
        assert linea["se_puede_diferir"] is True
        r = api.post(
            f"{BASE}/planillas/{planilla['id']}/diferir/", {"linea": linea["id"]}, format="json"
        )
        assert r.status_code == 200, r.content
        assert r.json()["puede_cerrar"] is True
        assert "ADELANTOS" not in montos(trabajador_de(api, r.json()))
        cuota = CuotaAdelanto.objects.sin_ambito().get()
        assert cuota.periodo == date(2026, 4, 1)

    def test_ajuste_a_mano_entra_en_las_bases_y_se_conserva_al_recalcular(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        fila = planilla["trabajadores"][0]
        opciones = api.get(f"{BASE}/planillas/opciones/?empresa={equipo['e'].emp_a1.pk}").json()
        codigos = {c["codigo"] for c in opciones["conceptos"]}
        assert "COMISIONES" in codigos and "SUELDO_BASICO" not in codigos
        comision = next(c for c in opciones["conceptos"] if c["codigo"] == "COMISIONES")
        r = api.post(
            f"{BASE}/planillas/{planilla['id']}/ajustes/",
            {"detalle": fila["id"], "concepto": comision["id"], "monto": "200.00"},
            format="json",
        )
        assert r.status_code == 200, r.content
        det = trabajador_de(api, r.json())
        m = montos(det)
        assert m["COMISIONES"] == D("200.00") and m["ONP"] == D("221.00")  # 13 % de 1,700
        r = api.post(f"{BASE}/planillas/{planilla['id']}/recalcular/")
        assert montos(trabajador_de(api, r.json()))["COMISIONES"] == D("200.00")
        linea = next(c for c in det["conceptos"] if c["codigo"] == "COMISIONES")
        assert linea["se_puede_quitar"] is True
        r = api.delete(f"{BASE}/planillas/{planilla['id']}/ajustes/{linea['id']}/")
        assert r.status_code == 200, r.content
        assert "COMISIONES" not in montos(trabajador_de(api, r.json()))

    def test_los_conceptos_calculados_no_se_agregan_a_mano(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        sueldo = ConceptoPlanilla.objects.sin_ambito().get(
            organizacion=equipo["e"].org_a, codigo="SUELDO_BASICO"
        )
        r = api.post(
            f"{BASE}/planillas/{planilla['id']}/ajustes/",
            {"detalle": planilla["trabajadores"][0]["id"], "concepto": sueldo.pk, "monto": "10"},
            format="json",
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
class TestCierre:
    def test_cerrar_descuenta_las_cuotas_y_bloquea_el_mes(self, equipo):
        api = cliente_de("super")
        TestAdelantosYAjustes().entregar(api, equipo)
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        r = api.post(
            f"{BASE}/planillas/{planilla['id']}/cerrar/",
            {"total_neto": planilla["total_neto"]},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "CERRADA" and r.json()["cerrada_en"]
        cuota = CuotaAdelanto.objects.sin_ambito().get()
        assert cuota.estado == "DESCONTADA" and cuota.descontada_en is not None
        # La asistencia del mes ya no se toca…
        r = api.post(
            f"{BASE}/asistencia/dia/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "personal": equipo["trabajador"].pk,
                "fecha": "2026-03-10",
                "tipo": tipo_id(equipo, "F"),
            },
            format="json",
        )
        assert r.status_code == 400 and "cerrada" in r.content.decode()
        assert (
            api.get(f"{BASE}/asistencia/?empresa={equipo['e'].emp_a1.pk}&anio=2026&mes=3").json()[
                "cerrado"
            ]
            is True
        )
        # …ni se puede recalcular o descartar la planilla.
        assert api.post(f"{BASE}/planillas/{planilla['id']}/recalcular/").status_code == 400
        assert api.delete(f"{BASE}/planillas/{planilla['id']}/").status_code == 400

    def test_no_se_cierra_con_errores(self, equipo):
        api = cliente_de("super")
        planilla = preparar(api, equipo).json()  # sin asistencia: días sin marcar
        r = api.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json")
        assert r.status_code == 400 and "error" in r.content.decode().lower()

    def test_si_la_planilla_cambio_no_cierra(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        marcar(api, equipo, "2026-03-10", "F")  # cambia después de que se calculó
        r = api.post(
            f"{BASE}/planillas/{planilla['id']}/cerrar/",
            {"total_neto": planilla["total_neto"]},
            format="json",
        )
        assert r.status_code == 400 and "cambió" in r.content.decode()
        assert api.get(f"{BASE}/planillas/{planilla['id']}/").json()["estado"] == "BORRADOR"

    def test_reabrir_libera_el_mes_y_las_cuotas(self, equipo):
        api = cliente_de("super")
        TestAdelantosYAjustes().entregar(api, equipo)
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        api.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json")
        r = api.post(f"{BASE}/planillas/{planilla['id']}/reabrir/", {}, format="json")
        assert r.status_code == 400  # el motivo es obligatorio
        r = api.post(
            f"{BASE}/planillas/{planilla['id']}/reabrir/",
            {"motivo": "Faltó una falta"},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "BORRADOR"
        cuota = CuotaAdelanto.objects.sin_ambito().get()
        assert cuota.estado == "PENDIENTE" and cuota.descontada_en is None
        marcar(api, equipo, "2026-03-10", "F")  # el mes volvió a estar abierto

    def test_no_se_reabre_si_hay_un_mes_posterior_cerrado(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        marzo = preparar(api, equipo).json()
        api.post(f"{BASE}/planillas/{marzo['id']}/cerrar/", {}, format="json")
        r = api.post(
            f"{BASE}/asistencia/completar/",
            {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": 4, "descanso": "DOMINGO"},
            format="json",
        )
        assert r.status_code == 200, r.content
        abril = preparar(api, equipo, mes=4).json()
        r = api.post(f"{BASE}/planillas/{abril['id']}/cerrar/", {}, format="json")
        assert r.status_code == 200, r.content
        r = api.post(f"{BASE}/planillas/{marzo['id']}/reabrir/", {"motivo": "x"}, format="json")
        assert r.status_code == 400 and "04/2026" in r.content.decode()

    def test_una_cuota_no_se_programa_en_un_mes_cerrado(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        api.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json")
        r = api.post(
            f"{BASE}/adelantos/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "personal": equipo["trabajador"].pk,
                "tipo": "ADELANTO",
                "fecha": "2026-03-20",
                "monto": "100.00",
                "cuenta": equipo["caja"].pk,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="cerrado-0001",
        )
        assert r.status_code == 400 and "cerrada" in r.content.decode()

    def test_renta_de_quinta_usa_lo_ya_cerrado_del_anio(self, equipo):
        api = cliente_de("super")
        api.patch(
            f"{BASE}/trabajadores/{equipo['trabajador'].pk}/datos-laborales/",
            {"paga_renta_5ta": True},
            format="json",
        )
        completar_marzo(api, equipo)
        marzo = preparar(api, equipo).json()
        api.post(f"{BASE}/planillas/{marzo['id']}/cerrar/", {}, format="json")
        api.post(
            f"{BASE}/asistencia/completar/",
            {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": 4, "descanso": "DOMINGO"},
            format="json",
        )
        abril = preparar(api, equipo, mes=4).json()
        m = montos(trabajador_de(api, abril))
        # Proyección: 1,500 (marzo) + 9 × 1,500 + 1,500 de gratificaciones = 16,500 → mismo
        # impuesto (1,030). Abril: (1,030 − 85.83 ya retenido) ÷ 9 = 104.91.
        assert m["RENTA_5TA"] == D("104.91")


# ---------------------------------------------------------------------------
class TestApi:
    def test_preparar_es_idempotente_y_no_duplica_el_mes(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        primera = preparar(api, equipo, clave="misma-clave-001")
        repetida = preparar(api, equipo, clave="misma-clave-001")
        assert primera.status_code == 201 and repetida.status_code == 201
        assert repetida["Idempotency-Replayed"] == "true"
        otra = preparar(api, equipo)
        assert otra.status_code == 400 and "Ya existe" in otra.content.decode()

    def test_no_se_prepara_un_mes_que_no_empezo(self, equipo):
        futuro = timezone.localdate().replace(day=1)
        anio, mes = (futuro.year + 1, futuro.month)
        r = cliente_de("super").post(
            f"{BASE}/planillas/",
            {"empresa": equipo["e"].emp_a1.pk, "anio": anio, "mes": mes},
            format="json",
            HTTP_IDEMPOTENCY_KEY="futuro-0001",
        )
        assert r.status_code == 400

    def test_descartar_una_planilla_en_revision(self, equipo):
        api = cliente_de("super")
        planilla = preparar(api, equipo).json()
        assert api.delete(f"{BASE}/planillas/{planilla['id']}/").status_code == 204
        assert api.get(f"{BASE}/planillas/?empresa={equipo['e'].emp_a1.pk}").json()["count"] == 0
        # Y se puede volver a preparar el mismo mes.
        assert preparar(api, equipo).status_code == 201

    def test_listado_y_permisos(self, equipo):
        super_ = cliente_de("super")
        completar_marzo(super_, equipo)
        planilla = preparar(super_, equipo).json()
        empresa = equipo["e"].emp_a1.pk
        lista = f"{BASE}/planillas/?empresa={empresa}"
        assert super_.get(lista).json()["count"] == 1
        # El cajero no ve planillas.
        assert cliente_de("cajero").get(lista).status_code == 403
        # El contador las ve pero no las prepara ni las cierra.
        contador = cliente_de("contador")
        assert contador.get(lista).status_code == 200
        assert contador.get(f"{BASE}/planillas/{planilla['id']}/").status_code == 200
        assert preparar(contador, equipo, mes=2).status_code == 403
        assert (
            contador.post(
                f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json"
            ).status_code
            == 403
        )
        # RR.HH. prepara y cierra, pero reabrir es un permiso aparte.
        rrhh = cliente_de("rrhh")
        assert (
            rrhh.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json").status_code
            == 200
        )
        r = rrhh.post(
            f"{BASE}/planillas/{planilla['id']}/reabrir/", {"motivo": "prueba"}, format="json"
        )
        assert r.status_code == 403

    def test_otra_organizacion_no_ve_la_planilla(self, equipo):
        super_ = cliente_de("super")
        completar_marzo(super_, equipo)
        planilla = preparar(super_, equipo).json()
        ajena = cliente_de("otra_org")
        assert ajena.get(f"{BASE}/planillas/{planilla['id']}/").status_code in (403, 404)
        assert ajena.get(f"{BASE}/planillas/?empresa={equipo['e'].emp_a1.pk}").status_code in (
            403,
            404,
        )

    def test_la_auditoria_no_guarda_montos(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        api.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json")
        eventos = AuditoriaEvento.objects.filter(accion__startswith="rrhh.planilla_")
        assert {e.accion for e in eventos} >= {"rrhh.planilla_creada", "rrhh.planilla_cerrada"}
        assert "1305" not in str([e.detalle for e in eventos])


class TestTramos:
    def test_el_contador_carga_la_escala(self, equipo):
        api = cliente_de("contador")
        r = api.post(
            f"{BASE}/tramos-renta5/",
            {"vigente_desde": "2027-01-01", "orden": 1, "hasta_uit": "5", "tasa": "8"},
            format="json",
        )
        assert r.status_code == 201, r.content
        repetido = api.post(
            f"{BASE}/tramos-renta5/",
            {"vigente_desde": "2027-01-01", "orden": 1, "hasta_uit": "9", "tasa": "9"},
            format="json",
        )
        assert repetido.status_code in (400, 409)
        assert api.get(f"{BASE}/tramos-renta5/").json()["count"] == 6

    def test_la_escala_mal_cargada_se_avisa(self, equipo):
        TramoRenta5.objects.sin_ambito().filter(orden=5).delete()  # sin el tramo sin tope
        _, planilla, _ = planilla_completa(equipo, paga_renta_5ta=True)
        assert any("mal cargada" in a["texto"] for a in planilla["avisos"])
        assert planilla["puede_cerrar"] is False


# ---------------------------------------------------------------------------
# RH6: pago de la planilla, boleta y archivo del banco
# ---------------------------------------------------------------------------
def saldo_caja(equipo, cuenta=None):
    from apps.caja import servicios as caja
    from apps.core.tenant import establecer_contexto, limpiar_contexto

    e = equipo["e"]
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], None)
    try:
        return caja.saldo_de(cuenta or equipo["caja"])
    finally:
        limpiar_contexto()


def cerrada(equipo):
    """Marzo cerrado (neto de 1,305.00); devuelve (cliente, planilla, id del trabajador en ella)."""
    api, planilla, det = planilla_completa(equipo)
    r = api.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json")
    assert r.status_code == 200, r.content
    return api, r.json(), det["id"]


def pagar(api, equipo, planilla, detalle, clave=None, cuenta=None, **extra):
    return api.post(
        f"{BASE}/planillas/{planilla['id']}/pagar/",
        {
            "detalles": [detalle],
            "fecha": "2026-04-02",
            "cuenta": cuenta or equipo["caja"].pk,
            **extra,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=clave or f"pago-{next(_claves):08d}",
    )


class TestPagos:
    def test_pagar_saca_el_neto_de_la_caja(self, equipo):
        api, planilla, detalle = cerrada(equipo)
        r = pagar(api, equipo, planilla, detalle, referencia="Op 123")
        assert r.status_code == 200, r.content
        fila = r.json()["trabajadores"][0]
        assert fila["pago"]["referencia"] == "Op 123"
        assert r.json()["num_pagados"] == 1 and D(r.json()["total_pagado"]) == D("1305.00")
        assert saldo_caja(equipo) == D("3695.00")  # 5,000 − 1,305
        # Un segundo pago del mismo trabajador no se acepta.
        r = pagar(api, equipo, planilla, detalle)
        assert r.status_code == 400 and "ya tiene" in r.content.decode()
        assert saldo_caja(equipo) == D("3695.00")

    def test_el_reintento_no_paga_dos_veces(self, equipo):
        api, planilla, detalle = cerrada(equipo)
        primera = pagar(api, equipo, planilla, detalle, clave="pago-repetido-1")
        repetida = pagar(api, equipo, planilla, detalle, clave="pago-repetido-1")
        assert primera.status_code == 200 and repetida.status_code == 200
        assert repetida["Idempotency-Replayed"] == "true"
        assert saldo_caja(equipo) == D("3695.00")

    def test_no_se_paga_una_planilla_en_revision(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        r = pagar(api, equipo, planilla, planilla["trabajadores"][0]["id"])
        assert r.status_code == 400 and "Cierre la planilla" in r.content.decode()

    def test_sin_saldo_no_se_guarda_ningun_pago(self, equipo, settings):
        settings.CAJA_BLOQUEA_SALDO_NEGATIVO = True
        api, planilla, detalle = cerrada(equipo)
        pobre = CuentaFinanciera.objects.sin_ambito().create(
            empresa=equipo["e"].emp_a1,
            nombre="Caja pobre",
            tipo="CAJA",
            moneda="PEN",
            saldo_inicial=D("100"),
            fecha_saldo_inicial=date(2026, 1, 1),
        )
        r = pagar(api, equipo, planilla, detalle, cuenta=pobre.pk)
        assert r.status_code in (400, 409), r.content
        assert api.get(f"{BASE}/planillas/{planilla['id']}/").json()["num_pagados"] == 0
        assert saldo_caja(equipo, pobre) == D("100.00")

    def test_con_pagos_no_se_reabre_y_anular_devuelve_el_dinero(self, equipo):
        api, planilla, detalle = cerrada(equipo)
        pago = pagar(api, equipo, planilla, detalle).json()["trabajadores"][0]["pago"]
        reabrir = f"{BASE}/planillas/{planilla['id']}/reabrir/"
        r = api.post(reabrir, {"motivo": "x"}, format="json")
        assert r.status_code == 400 and "pagados" in r.content.decode()
        url = f"{BASE}/planillas/{planilla['id']}/pagos/{pago['id']}/anular/"
        assert api.post(url, {}, format="json").status_code == 400  # el motivo es obligatorio
        r = api.post(url, {"motivo": "Cuenta equivocada"}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["num_pagados"] == 0 and saldo_caja(equipo) == D("5000.00")
        # El mismo pago no se anula dos veces.
        assert api.post(url, {"motivo": "otra vez"}, format="json").status_code == 400
        # Con el trabajador otra vez por pagar, ya se puede reabrir.
        assert api.post(reabrir, {"motivo": "Corregir"}, format="json").status_code == 200

    def test_permisos_de_pago(self, equipo):
        api, planilla, detalle = cerrada(equipo)
        assert pagar(cliente_de("contador"), equipo, planilla, detalle).status_code == 403
        assert pagar(cliente_de("cajero"), equipo, planilla, detalle).status_code == 403
        assert pagar(cliente_de("rrhh"), equipo, planilla, detalle).status_code == 200


class TestBoleta:
    def test_la_boleta_trae_ingresos_descuentos_y_el_pago(self, equipo):
        api, planilla, detalle = cerrada(equipo)
        url = f"{BASE}/planillas/{planilla['id']}/trabajadores/{detalle}/boleta/"
        b = api.get(url).json()
        assert b["es_borrador"] is False and b["pago"] is None
        assert b["emisor"]["ruc"] and b["trabajador"]["numero_documento"] == "45678912"
        assert [i["nombre"] for i in b["ingresos"]] == ["Sueldo básico"]
        assert [d["nombre"] for d in b["descuentos"]] == ["ONP"]
        assert D(b["neto"]) == D("1305.00") and D(b["total_descuentos"]) == D("195.00")
        pagar(api, equipo, planilla, detalle, referencia="Op 9")
        assert api.get(url).json()["pago"]["referencia"] == "Op 9"

    def test_antes_de_cerrar_se_marca_como_borrador(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        planilla = preparar(api, equipo).json()
        fila = planilla["trabajadores"][0]["id"]
        b = api.get(f"{BASE}/planillas/{planilla['id']}/trabajadores/{fila}/boleta/").json()
        assert b["es_borrador"] is True


class TestArchivoBanco:
    def con_cuenta(self, equipo, **datos):
        r = cliente_de("super").patch(
            f"{BASE}/trabajadores/{equipo['trabajador'].pk}/datos-laborales/",
            {"metodo_pago": "TRANSFERENCIA", **datos},
            format="json",
        )
        assert r.status_code == 200, r.content

    def test_el_archivo_lista_las_transferencias_por_hacer(self, equipo):
        self.con_cuenta(equipo, banco="BCP", numero_cuenta="19412345678901")
        api, planilla, detalle = cerrada(equipo)
        url = f"{BASE}/planillas/{planilla['id']}/archivo-banco/"
        r = cliente_de("rrhh").get(url)
        assert r.status_code == 200, r.content
        assert "transferencias-2026-03.csv" in r["Content-Disposition"]
        lineas = r.content.decode().splitlines()
        assert lineas[0].startswith("tipo_documento,")
        assert "19412345678901" in lineas[1] and "1305.00" in lineas[1]
        # Ya pagado: no vuelve a salir en el archivo.
        pagar(api, equipo, planilla, detalle)
        assert len(cliente_de("rrhh").get(url).content.decode().splitlines()) == 1

    def test_quien_no_tiene_cuenta_se_informa_aparte(self, equipo):
        self.con_cuenta(equipo)
        _, planilla, _ = cerrada(equipo)
        r = cliente_de("rrhh").get(f"{BASE}/planillas/{planilla['id']}/archivo-banco/")
        assert r.status_code == 200 and "Quispe" in unquote(r["X-Omitidos"])
        assert len(r.content.decode().splitlines()) == 1

    def test_el_contador_no_baja_el_archivo_y_la_auditoria_no_guarda_cuentas(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        self.con_cuenta(equipo, banco="BCP", numero_cuenta="19412345678901")
        _, planilla, _ = cerrada(equipo)
        url = f"{BASE}/planillas/{planilla['id']}/archivo-banco/"
        assert cliente_de("contador").get(url).status_code == 403
        assert cliente_de("super").get(url).status_code == 200
        eventos = AuditoriaEvento.objects.filter(accion="rrhh.archivo_banco_generado")
        assert eventos.count() == 1
        assert "19412345678901" not in str([(e.resumen, e.detalle) for e in eventos])


# ---------------------------------------------------------------------------
# RH7: gratificaciones de julio y diciembre dentro de la planilla
# ---------------------------------------------------------------------------
def completar_mes(api, equipo, mes):
    r = api.post(
        f"{BASE}/asistencia/completar/",
        {"empresa": equipo["e"].emp_a1.pk, "anio": 2026, "mes": mes, "descanso": "DOMINGO"},
        format="json",
    )
    assert r.status_code == 200, r.content


class TestGratificacion:
    def test_julio_trae_gratificacion_y_bonificacion(self, equipo):
        api = cliente_de("super")
        completar_mes(api, equipo, 7)
        planilla = preparar(api, equipo, mes=7).json()
        det = trabajador_de(api, planilla)
        m = montos(det)
        # Contrato desde el 2 de enero: enero no está completo, quedan 5 meses de 6.
        # Pequeña empresa: medio sueldo. 1,500 × 5 ÷ 6 × 0.5 = 625.00; bonificación 9 %.
        assert m["GRATIFICACION"] == D("625.00")
        assert m["BONIF_EXTRAORDINARIA"] == D("56.25")
        # No están afectas a pensión: la ONP sigue siendo el 13 % del sueldo.
        assert m["ONP"] == D("195.00")
        assert D(det["neto"]) == D("1986.25")

    def test_las_faltas_del_semestre_restan_un_ciento_ochentavo(self, equipo):
        api = cliente_de("super")
        marcar(api, equipo, "2026-03-10", "F")
        completar_mes(api, equipo, 7)
        m = montos(trabajador_de(api, preparar(api, equipo, mes=7).json()))
        # (1,500 × 5 ÷ 6 − 1,500 ÷ 180) × 0.5 = 620.83
        assert m["GRATIFICACION"] == D("620.83")
        assert m["BONIF_EXTRAORDINARIA"] == D("55.87")

    def test_los_demas_meses_no_llevan_gratificacion(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        m = montos(trabajador_de(api, preparar(api, equipo).json()))
        assert "GRATIFICACION" not in m and "BONIF_EXTRAORDINARIA" not in m

    def test_sin_el_porcentaje_de_bonificacion_no_se_cierra(self, equipo):
        ParametroLaboral.objects.sin_ambito().filter(codigo="BONIF_EXTRAORDINARIA").delete()
        api = cliente_de("super")
        completar_mes(api, equipo, 7)
        planilla = preparar(api, equipo, mes=7).json()
        assert planilla["puede_cerrar"] is False
        assert any("extraordinaria" in a["texto"] for a in planilla["avisos"])
