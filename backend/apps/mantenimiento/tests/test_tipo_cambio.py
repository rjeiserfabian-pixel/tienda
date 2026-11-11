"""Tipo de cambio: sincronización con SUNAT y SBS (simulados), consulta por fecha y carga manual."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
import requests
from django.utils import timezone

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento import tipo_cambio
from apps.mantenimiento.models import TipoCambio
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento/tipo-cambio"
TODAS = {"fuentes": ["SUNAT", "SBS", "SBS_CONTABLE"], "forzar": True}


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


def hoy() -> date:
    return timezone.localdate()


class Respuesta:
    def __init__(self, cuerpo, estado=200):
        self.status_code = estado
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


@pytest.fixture
def servicio(monkeypatch, settings):
    """Simula Decolecta. ``respuestas[ruta]`` puede ser una Respuesta o una excepción."""
    settings.DECOLECTA_TOKEN = "token-de-prueba"
    settings.DECOLECTA_URL = "https://proveedor.example"
    ayer = (hoy() - timedelta(days=1)).isoformat()
    respuestas = {
        "/v1/tipo-cambio/sunat": Respuesta(
            {"buy_price": "3.446", "sell_price": "3.452", "date": hoy().isoformat()}
        ),
        # La SBS publica con un día de retraso: devuelve la fecha de ayer.
        "/v1/tipo-cambio/sbs/average": Respuesta(
            {"buy_price": "3.440", "sell_price": "3.450", "date": ayer}
        ),
        "/v1/tipo-cambio/sbs/accounting": Respuesta({"price": "3.449000", "date": ayer}),
    }
    llamadas = []

    def falso_get(url, params=None, headers=None, timeout=None):
        ruta = url.replace("https://proveedor.example", "")
        llamadas.append({"ruta": ruta, "params": params, "headers": headers, "timeout": timeout})
        respuesta = respuestas[ruta]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(tipo_cambio.requests, "get", falso_get)
    return type("Servicio", (), {"llamadas": llamadas, "respuestas": respuestas})


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "org": e.org_a,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "almacen": nuevo_usuario(e.org_a, "almacen", [e.emp_a1], [("ALMACENERO", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


# ---------------------------------------------------------------------------
# Sincronización
# ---------------------------------------------------------------------------
class TestActualizar:
    def test_trae_las_tres_fuentes_con_la_fecha_que_devuelve_el_servicio(self, equipo, servicio):
        r = cliente_de("super").post(f"{BASE}/actualizar/", TODAS, format="json")
        assert r.status_code == 200, r.content
        por_fuente = {x["fuente"]: x for x in r.json()["resultados"]}
        assert {x["estado"] for x in por_fuente.values()} == {"nuevo"}
        assert por_fuente["SUNAT"]["fecha"] == hoy().isoformat()
        assert por_fuente["SBS"]["fecha"] == (hoy() - timedelta(days=1)).isoformat()
        sbs_contable = TipoCambio.objects.sin_ambito().get(fuente="SBS_CONTABLE")
        assert (sbs_contable.compra, sbs_contable.venta) == (Decimal("3.4490"), Decimal("3.4490"))
        assert TipoCambio.objects.sin_ambito().count() == 3
        llamada = servicio.llamadas[0]
        assert llamada["headers"]["Authorization"] == "Bearer token-de-prueba"
        assert llamada["timeout"] > 0
        assert AuditoriaEvento.objects.filter(accion="tipo_cambio.actualizado").exists()

    def test_repetir_no_duplica_y_corrige_si_la_tasa_cambio(self, equipo, servicio):
        api = cliente_de("super")
        api.post(f"{BASE}/actualizar/", TODAS, format="json")
        segunda = api.post(f"{BASE}/actualizar/", TODAS, format="json").json()["resultados"]
        assert {x["estado"] for x in segunda} == {"sin_cambios"}
        servicio.respuestas["/v1/tipo-cambio/sunat"] = Respuesta(
            {"buy_price": "3.460", "sell_price": "3.470", "date": hoy().isoformat()}
        )
        tercera = api.post(
            f"{BASE}/actualizar/", {"fuentes": ["SUNAT"], "forzar": True}, format="json"
        ).json()
        assert tercera["resultados"][0]["estado"] == "actualizado"
        assert TipoCambio.objects.sin_ambito().count() == 3
        assert TipoCambio.objects.sin_ambito().get(fuente="SUNAT").venta == Decimal("3.4700")

    def test_una_fuente_que_falla_no_impide_las_demas(self, equipo, servicio):
        servicio.respuestas["/v1/tipo-cambio/sbs/average"] = requests.Timeout("lento")
        servicio.respuestas["/v1/tipo-cambio/sbs/accounting"] = Respuesta({}, 500)
        r = cliente_de("super").post(f"{BASE}/actualizar/", TODAS, format="json")
        estados = {x["fuente"]: x["estado"] for x in r.json()["resultados"]}
        assert estados == {"SUNAT": "nuevo", "SBS": "error", "SBS_CONTABLE": "error"}
        assert TipoCambio.objects.sin_ambito().count() == 1

    def test_respuestas_raras_se_tratan_como_error(self, equipo, servicio):
        for basura in (
            {"buy_price": "abc", "sell_price": "3.4", "date": "2026-01-01"},
            {"x": 1},
            {"buy_price": "0", "sell_price": "0", "date": "2026-01-01"},
        ):
            servicio.respuestas["/v1/tipo-cambio/sunat"] = Respuesta(basura)
            r = cliente_de("super").post(
                f"{BASE}/actualizar/", {"fuentes": ["SUNAT"]}, format="json"
            )
            assert r.json()["resultados"][0]["estado"] == "error"
        assert TipoCambio.objects.sin_ambito().count() == 0

    def test_sin_token_avisa_sin_llamar(self, equipo, servicio, settings):
        settings.DECOLECTA_TOKEN = ""
        r = cliente_de("super").post(f"{BASE}/actualizar/", TODAS, format="json")
        assert all(x["estado"] == "error" for x in r.json()["resultados"])
        assert servicio.llamadas == []

    def test_pide_una_fecha_concreta_y_valida_la_entrada(self, equipo, servicio):
        api = cliente_de("super")
        api.post(
            f"{BASE}/actualizar/", {"fecha": "2026-10-20", "fuentes": ["SUNAT"]}, format="json"
        )
        assert servicio.llamadas[0]["params"] == {"date": "2026-10-20"}
        assert (
            api.post(f"{BASE}/actualizar/", {"fuentes": ["OTRA"]}, format="json").status_code == 400
        )
        assert api.post(f"{BASE}/actualizar/", {"fecha": "ayer"}, format="json").status_code == 400

    def test_cada_organizacion_guarda_lo_suyo(self, equipo, servicio):
        cliente_de("super").post(f"{BASE}/actualizar/", TODAS, format="json")
        ajena = cliente_de("otra_org")
        assert ajena.get(f"{BASE}/").json()["count"] == 0
        ajena.post(f"{BASE}/actualizar/", {"fuentes": ["SUNAT"]}, format="json")
        assert TipoCambio.objects.sin_ambito().count() == 4

    def test_la_tarea_programada_actualiza_a_todas_las_organizaciones(self, equipo, servicio):
        from apps.mantenimiento.tasks import actualizar_tipo_cambio

        assert actualizar_tipo_cambio() == 2  # las dos organizaciones de la prueba
        organizaciones = set(
            TipoCambio.objects.sin_ambito().values_list("organizacion_id", flat=True)
        )
        assert len(organizaciones) == 2

    def test_actualizar_exige_permiso(self, equipo, servicio):
        assert (
            cliente_de("vendedor").post(f"{BASE}/actualizar/", TODAS, format="json").status_code
            == 403
        )
        assert servicio.llamadas == []


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
class TestConsulta:
    def test_resumen_trae_lo_mas_reciente_de_cada_fuente(self, equipo, servicio):
        api = cliente_de("super")
        api.post(f"{BASE}/actualizar/", TODAS, format="json")
        r = api.get(f"{BASE}/resumen/")
        assert r.status_code == 200
        assert {f["fuente"] for f in r.json()["fuentes"]} == {"SUNAT", "SBS", "SBS_CONTABLE"}

    def test_vigente_usa_la_fecha_o_la_anterior(self, equipo, servicio):
        cliente_de("super").post(f"{BASE}/actualizar/", {"fuentes": ["SUNAT"]}, format="json")
        org = equipo["org"].pk
        fila = tipo_cambio.vigente(org, hoy())
        assert fila.fecha == hoy()
        # Un fin de semana o feriado sin tasa propia usa la última publicada.
        assert tipo_cambio.vigente(org, hoy() + timedelta(days=2)).fecha == hoy()
        assert tipo_cambio.vigente(org, hoy() - timedelta(days=5)) is None
        assert tipo_cambio.vigente(org, hoy(), "SBS") is None

    def test_listado_filtrado_y_paginado(self, equipo, servicio):
        api = cliente_de("super")
        api.post(f"{BASE}/actualizar/", TODAS, format="json")
        lista = api.get(f"{BASE}/").json()
        assert lista["count"] == 3 and {"next", "previous", "results"} <= lista.keys()
        assert api.get(f"{BASE}/", {"fuente": "SUNAT"}).json()["count"] == 1
        assert api.get(f"{BASE}/", {"desde": hoy().isoformat()}).json()["count"] == 1
        assert api.get(f"{BASE}/", {"hasta": "2000-01-01"}).json()["count"] == 0
        assert api.get(f"{BASE}/", {"desde": "mañana"}).status_code == 400

    def test_quien_solo_consulta_ve_pero_no_modifica(self, equipo, servicio):
        cliente_de("super").post(f"{BASE}/actualizar/", TODAS, format="json")
        for usuario in ("vendedor", "almacen"):
            api = cliente_de(usuario)
            assert api.get(f"{BASE}/").json()["count"] == 3
            manual = {"fecha": hoy().isoformat(), "compra": "3.4", "venta": "3.5"}
            assert api.post(f"{BASE}/", manual, format="json").status_code == 403


# ---------------------------------------------------------------------------
# Carga manual
# ---------------------------------------------------------------------------
class TestManual:
    def datos(self, **extra):
        return {"fecha": hoy().isoformat(), "compra": "3.4000", "venta": "3.5000", **extra}

    def test_alta_edicion_y_baja_de_una_tasa_manual(self, equipo):
        api = cliente_de("super")
        r = api.post(f"{BASE}/", self.datos(), format="json")
        assert r.status_code == 201, r.content
        fila = r.json()
        assert (fila["fuente"], fila["es_manual"], fila["moneda"]) == ("MANUAL", True, "USD")
        url = f"{BASE}/{fila['id']}/"
        assert api.patch(url, {"venta": "3.5200"}, format="json").json()["venta"] == "3.5200"
        assert api.delete(url).status_code == 204
        assert api.post(f"{BASE}/", self.datos(), format="json").status_code == 201  # fecha libre

    def test_las_oficiales_no_se_editan_ni_se_borran(self, equipo, servicio):
        api = cliente_de("super")
        api.post(f"{BASE}/actualizar/", {"fuentes": ["SUNAT"]}, format="json")
        oficial = TipoCambio.objects.sin_ambito().get(fuente="SUNAT")
        url = f"{BASE}/{oficial.pk}/"
        r = api.patch(url, {"venta": "9.0"}, format="json")
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "tipo_cambio_oficial")
        assert api.delete(url).status_code == 409
        assert TipoCambio.objects.sin_ambito().get(pk=oficial.pk).venta == Decimal("3.4520")

    def test_validaciones(self, equipo):
        api = cliente_de("super")
        casos = [
            self.datos(compra="0"),
            self.datos(venta="3.3"),  # venta menor que compra
            self.datos(venta="9.9"),  # venta muy distinta de la compra
            self.datos(fecha=(hoy() + timedelta(days=1)).isoformat()),  # futura
            self.datos(compra="abc"),
        ]
        for caso in casos:
            assert api.post(f"{BASE}/", caso, format="json").status_code == 400, caso
        api.post(f"{BASE}/", self.datos(), format="json")
        repetido = api.post(f"{BASE}/", self.datos(compra="3.41"), format="json")
        assert repetido.status_code == 400 and "fecha" in str(repetido.json()).lower()


# ---------------------------------------------------------------------------
# Cuota del proveedor (el plan gratuito trae 100 consultas al mes)
# ---------------------------------------------------------------------------
class TestCuota:
    def test_por_defecto_solo_trae_sunat_y_gasta_una_consulta(self, equipo, servicio):
        r = cliente_de("super").post(f"{BASE}/actualizar/", {}, format="json")
        assert [x["fuente"] for x in r.json()["resultados"]] == ["SUNAT"]
        assert len(servicio.llamadas) == 1
        assert r.json()["uso"]["usadas"] == 1

    def test_no_repite_lo_que_ya_tiene_ni_lo_consultado_hace_poco(self, equipo, servicio):
        api = cliente_de("super")
        api.post(f"{BASE}/actualizar/", {}, format="json")
        segunda = api.post(f"{BASE}/actualizar/", {}, format="json").json()
        assert segunda["resultados"][0]["estado"] == "al_dia"
        assert (len(servicio.llamadas), segunda["uso"]["usadas"]) == (1, 1)  # no gastó cuota
        # La SBS publica con un día de retraso: aun sin fila de hoy, no se repite en 6 horas.
        api.post(f"{BASE}/actualizar/", {"fuentes": ["SBS"]}, format="json")
        api.post(f"{BASE}/actualizar/", {"fuentes": ["SBS"]}, format="json")
        assert len(servicio.llamadas) == 2
        api.post(f"{BASE}/actualizar/", {"fuentes": ["SUNAT"], "forzar": True}, format="json")
        assert len(servicio.llamadas) == 3

    def test_las_consultas_de_dni_y_ruc_tambien_cuentan(self, equipo, servicio, monkeypatch):
        from apps.mantenimiento import consultas, cuota

        monkeypatch.setattr(
            consultas.requests,
            "get",
            lambda *a, **k: Respuesta(
                {"first_name": "ANA", "first_last_name": "RUIZ", "second_last_name": "SOTO"}
            ),
        )
        r = cliente_de("vendedor").get("/api/v1/mantenimiento/consultas/dni/45871236/")
        assert r.status_code == 200
        assert cuota.usadas() == 1

    def test_con_la_cuota_agotada_no_se_llama_al_proveedor(self, equipo, servicio, settings):
        from apps.mantenimiento import cuota

        settings.DECOLECTA_LIMITE_MENSUAL = 2
        cuota.fijar(2)
        r = cliente_de("super").post(f"{BASE}/actualizar/", {}, format="json")
        assert r.json()["resultados"][0]["estado"] == "error"
        assert "cuota" in r.json()["resultados"][0]["mensaje"].lower()
        dni = cliente_de("vendedor").get("/api/v1/mantenimiento/consultas/dni/45871236/")
        assert (dni.status_code, dni.json()["error"]["codigo"]) == (429, "cuota_agotada")
        assert servicio.llamadas == []

    def test_lo_automatico_se_detiene_antes_de_gastar_toda_la_cuota(
        self, equipo, servicio, settings
    ):
        from apps.mantenimiento import cuota
        from apps.mantenimiento.tasks import actualizar_tipo_cambio

        settings.DECOLECTA_LIMITE_MENSUAL = 100
        settings.TIPO_CAMBIO_UMBRAL_AUTOMATICO = 0.6
        settings.TIPO_CAMBIO_FUENTES_AUTOMATICAS = ["SUNAT"]
        cuota.fijar(61)
        assert actualizar_tipo_cambio() == 0
        assert servicio.llamadas == []
        cuota.fijar(10)
        assert actualizar_tipo_cambio() == 2
        assert len(servicio.llamadas) == 2  # una consulta (SUNAT) por organización

    def test_la_actualizacion_diaria_viene_apagada(self):
        from django.conf import settings as ajustes

        assert ajustes.TIPO_CAMBIO_AUTOMATICO is False
        assert "actualizar-tipo-cambio" not in ajustes.CELERY_BEAT_SCHEDULE

    def test_se_ve_el_uso_del_mes(self, equipo, servicio):
        cliente_de("super").post(f"{BASE}/actualizar/", {}, format="json")
        resumen = cliente_de("super").get(f"{BASE}/resumen/").json()
        assert resumen["uso"]["usadas"] == 1 and resumen["uso"]["limite"] == 100
        uso = cliente_de("vendedor").get("/api/v1/mantenimiento/consultas/uso/")
        assert uso.status_code == 200 and uso.json()["restantes"] == 99
        assert cliente_de("almacen").get("/api/v1/mantenimiento/consultas/uso/").status_code == 403

    def test_el_comando_muestra_y_calibra_el_contador(self, db):
        from io import StringIO

        from django.core.management import call_command

        from apps.mantenimiento import cuota

        salida = StringIO()
        call_command("consumo_decolecta", "--fijar", "12", stdout=salida)
        assert cuota.usadas() == 12 and "12 de 100" in salida.getvalue()
