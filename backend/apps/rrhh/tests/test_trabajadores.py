"""RR.HH. (RH2): ficha laboral, contratos, sueldos, permisos y aislamiento entre empresas."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento.models import Personal
from apps.rrhh import catalogos
from apps.rrhh.models import ContratoLaboral, DatosLaborales, ParametroLaboral, RegimenLaboral
from apps.seguridad.models import RolPermiso
from apps.seguridad.services import permisos_engine
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/rrhh"
CUENTA = "19412345678901"


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
    equipo = {
        "e": e,
        "trabajador": trabajador,
        "regimen": RegimenLaboral.objects.sin_ambito().get(organizacion=e.org_a, codigo="PEQUENA"),
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "rrhh": nuevo_usuario(e.org_a, "rrhh", [e.emp_a1], [("RRHH", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }
    # «rrhh» edita fichas y contratos pero NO tiene sueldos ni cuentas: se los quitamos al rol.
    RolPermiso._base_manager.filter(
        rol__organizacion=e.org_a, rol__codigo="RRHH", permiso__codigo__startswith="RRHH.SUELDOS."
    ).delete()
    permisos_engine.invalidar_organizacion(e.org_a.pk)
    return equipo


def contrato_body(equipo, **extra):
    return {
        "regimen": equipo["regimen"].pk,
        "cargo": "Vendedora",
        "fecha_inicio": "2026-01-02",
        "sueldo": "1500.00",
        **extra,
    }


def crear(api, equipo, **extra):
    t = equipo["trabajador"]
    return api.post(
        f"{BASE}/trabajadores/{t.pk}/contratos/", contrato_body(equipo, **extra), format="json"
    )


def ficha(api, equipo):
    return api.get(f"{BASE}/trabajadores/{equipo['trabajador'].pk}/")


def post(api, url, cuerpo):
    return api.post(url, cuerpo, format="json")


class TestDatosLaborales:
    def url(self, equipo):
        return f"{BASE}/trabajadores/{equipo['trabajador'].pk}/datos-laborales/"

    def test_registra_y_conserva_la_cuenta_cifrada(self, equipo):
        api = cliente_de("super")
        r = api.patch(
            self.url(equipo),
            {
                "sistema_pension": "AFP",
                "afp": "HABITAT",
                "tipo_comision": "MIXTA",
                "cuspp": "abc123def456",
                "banco": "BCP",
                "numero_cuenta": CUENTA,
                "paga_renta_5ta": True,
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()["datos_laborales"]
        assert datos["cuspp"] == "ABC123DEF456"
        assert datos["paga_renta_5ta"] is True
        assert datos["cuenta_final"] == CUENTA[-4:]
        assert CUENTA not in r.content.decode()
        # Enviar la cuenta vacía no la borra.
        r = api.patch(
            self.url(equipo), {"numero_cuenta": "", "asignacion_familiar": True}, format="json"
        )
        assert r.json()["datos_laborales"]["cuenta_puesta"] is True
        assert DatosLaborales.objects.sin_ambito().get().numero_cuenta == CUENTA

    def test_afp_exige_sus_datos_y_salir_de_afp_los_limpia(self, equipo):
        api = cliente_de("super")
        r = api.patch(self.url(equipo), {"sistema_pension": "AFP"}, format="json")
        assert r.status_code == 400
        ok = api.patch(
            self.url(equipo),
            {"sistema_pension": "AFP", "afp": "PRIMA", "tipo_comision": "FLUJO"},
            format="json",
        )
        assert ok.status_code == 200, ok.content
        r = api.patch(self.url(equipo), {"sistema_pension": "ONP"}, format="json")
        assert r.status_code == 200
        assert r.json()["datos_laborales"]["afp"] == ""

    def test_cuspp_y_cuenta_se_validan(self, equipo):
        api = cliente_de("super")
        malo = {"sistema_pension": "AFP", "afp": "PRIMA", "tipo_comision": "FLUJO", "cuspp": "123"}
        assert api.patch(self.url(equipo), malo, format="json").status_code == 400
        r = api.patch(self.url(equipo), {"numero_cuenta": "abc"}, format="json")
        assert r.status_code == 400

    def test_sin_permiso_de_sueldos_no_toca_la_cuenta_ni_la_ve(self, equipo):
        cliente_de("super").patch(
            self.url(equipo), {"banco": "BCP", "numero_cuenta": CUENTA}, format="json"
        )
        sin_sueldos = cliente_de("rrhh")
        r = sin_sueldos.patch(self.url(equipo), {"sexo": "F"}, format="json")
        assert r.status_code == 200, r.content
        assert "cuenta_final" not in r.json()["datos_laborales"]
        r = sin_sueldos.patch(self.url(equipo), {"numero_cuenta": "99999999"}, format="json")
        assert r.status_code in (400, 403)
        assert DatosLaborales.objects.sin_ambito().get().numero_cuenta == CUENTA

    def test_la_auditoria_no_guarda_la_cuenta(self, equipo):
        cliente_de("super").patch(
            self.url(equipo), {"banco": "BCP", "numero_cuenta": CUENTA}, format="json"
        )
        eventos = AuditoriaEvento.objects.filter(accion="rrhh.datos_laborales_editados")
        assert eventos.exists()
        assert all(CUENTA not in str(e.detalle) for e in eventos)


class TestContratos:
    def test_crea_contrato_con_su_sueldo_y_aparece_en_la_ficha(self, equipo):
        r = crear(cliente_de("super"), equipo)
        assert r.status_code == 201, r.content
        cuerpo = r.json()
        assert cuerpo["avisos"] == []
        contrato = cuerpo["contratos"][0]
        assert contrato["estado"] == "VIGENTE"
        assert D(str(contrato["sueldo_actual"])) == D("1500.00")
        assert len(contrato["cambios_sueldo"]) == 1

    def test_solo_un_contrato_vigente_por_trabajador(self, equipo):
        api = cliente_de("super")
        assert crear(api, equipo).status_code == 201
        r = crear(api, equipo, fecha_inicio="2026-03-01")
        assert r.status_code == 400
        assert "vigente" in r.content.decode()

    def test_plazo_fijo_exige_fecha_fin_y_esta_no_precede_al_inicio(self, equipo):
        api = cliente_de("super")
        assert crear(api, equipo, tipo_contrato="PLAZO_FIJO").status_code == 400
        r = crear(api, equipo, tipo_contrato="PLAZO_FIJO", fecha_fin="2025-12-01")
        assert r.status_code == 400

    def test_avisa_si_el_sueldo_es_menor_a_la_rmv_pero_deja_guardar(self, equipo):
        ParametroLaboral.objects.sin_ambito().create(
            organizacion=equipo["e"].org_a,
            codigo="RMV",
            valor=D("1130"),
            vigente_desde=date(2026, 1, 1),
        )
        r = crear(cliente_de("super"), equipo, sueldo="900.00")
        assert r.status_code == 201, r.content
        assert any("mínima" in a for a in r.json()["avisos"])

    def test_el_contrato_exige_el_permiso_de_sueldos(self, equipo):
        assert crear(cliente_de("rrhh"), equipo).status_code == 403

    def test_finalizar_y_volver_a_contratar(self, equipo):
        api = cliente_de("super")
        contrato = crear(api, equipo).json()["contratos"][0]
        url = f"{BASE}/contratos/{contrato['id']}/finalizar/"
        futura = (timezone.localdate() + timedelta(days=3)).isoformat()
        assert post(api, url, {"fecha_cese": futura, "motivo": "Renuncia"}).status_code == 400
        assert post(api, url, {"fecha_cese": "2026-01-10", "motivo": "  "}).status_code == 400
        r = post(api, url, {"fecha_cese": "2026-01-10", "motivo": "Renuncia"})
        assert r.status_code == 200, r.content
        assert r.json()["contratos"][0]["estado"] == "FINALIZADO"
        # Ya no se finaliza dos veces ni se le toca el sueldo…
        assert post(api, url, {"fecha_cese": "2026-01-10", "motivo": "x"}).status_code == 400
        sueldo = {"monto": "1800", "vigente_desde": "2026-02-01"}
        assert post(api, f"{BASE}/contratos/{contrato['id']}/sueldos/", sueldo).status_code == 400
        # …pero se le puede hacer uno nuevo.
        assert crear(api, equipo, fecha_inicio="2026-06-01").status_code == 201
        assert ContratoLaboral.objects.sin_ambito().count() == 2

    def test_corregir_el_cargo_y_no_el_contrato_finalizado(self, equipo):
        api = cliente_de("super")
        contrato = crear(api, equipo).json()["contratos"][0]
        url = f"{BASE}/contratos/{contrato['id']}/"
        r = api.patch(url, {"cargo": "Jefa de ventas"}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["contratos"][0]["cargo"] == "Jefa de ventas"
        post(api, f"{url}finalizar/", {"fecha_cese": "2026-01-10", "motivo": "Fin"})
        assert api.patch(url, {"cargo": "Otro"}, format="json").status_code == 400


class TestSueldos:
    def test_historial_y_sueldo_vigente_por_fecha(self, equipo):
        api = cliente_de("super")
        contrato = crear(api, equipo).json()["contratos"][0]
        url = f"{BASE}/contratos/{contrato['id']}/sueldos/"
        futuro = (timezone.localdate() + timedelta(days=30)).isoformat()
        assert post(api, url, {"monto": "1800", "vigente_desde": "2026-02-01"}).status_code == 200
        assert post(api, url, {"monto": "2500", "vigente_desde": futuro}).status_code == 200
        r = ficha(api, equipo).json()["contratos"][0]
        assert len(r["cambios_sueldo"]) == 3
        assert D(str(r["sueldo_actual"])) == D("1800.00")  # el futuro aún no rige

    def test_misma_fecha_o_antes_del_inicio_se_rechaza(self, equipo):
        api = cliente_de("super")
        contrato = crear(api, equipo).json()["contratos"][0]
        url = f"{BASE}/contratos/{contrato['id']}/sueldos/"
        assert post(api, url, {"monto": "1600", "vigente_desde": "2026-01-02"}).status_code == 400
        assert post(api, url, {"monto": "1600", "vigente_desde": "2025-12-01"}).status_code == 400

    def test_quien_ve_el_contrato_pero_no_los_sueldos_no_los_recibe(self, equipo):
        crear(cliente_de("super"), equipo)
        r = ficha(cliente_de("rrhh"), equipo)
        contrato = r.json()["contratos"][0]
        assert "sueldo_actual" not in contrato and "cambios_sueldo" not in contrato
        assert "1500" not in r.content.decode()

    def test_la_auditoria_no_guarda_el_monto(self, equipo):
        crear(cliente_de("super"), equipo, sueldo="1777.77")
        contrato = ContratoLaboral.objects.sin_ambito().get()
        post(
            cliente_de("super"),
            f"{BASE}/contratos/{contrato.pk}/sueldos/",
            {"monto": "1999.99", "vigente_desde": "2026-02-01"},
        )
        eventos = AuditoriaEvento.objects.filter(accion__startswith="rrhh.")
        assert eventos.exists()
        assert all("1999.99" not in str(e.detalle) for e in eventos)
        assert all("1777.77" not in str(e.detalle) for e in eventos)


class TestListadoYPermisos:
    def lista(self, api, equipo, **filtros):
        params = {"empresa": equipo["e"].emp_a1.pk, **filtros}
        return api.get(f"{BASE}/trabajadores/", params)

    def test_lista_con_contrato_y_faltantes(self, equipo):
        api = cliente_de("super")
        fila = self.lista(api, equipo).json()["results"][0]
        assert fila["contrato"] is None
        assert "Contrato vigente" in fila["faltantes"]
        crear(api, equipo)
        fila = self.lista(api, equipo).json()["results"][0]
        assert fila["contrato"]["cargo"] == "Vendedora"
        assert "Contrato vigente" not in fila["faltantes"]

    def test_filtros_de_contrato(self, equipo):
        api = cliente_de("super")
        assert self.lista(api, equipo, contrato="sin_contrato").json()["count"] == 1
        assert self.lista(api, equipo, contrato="vigente").json()["count"] == 0
        hoy = timezone.localdate()
        crear(
            api,
            equipo,
            tipo_contrato="PLAZO_FIJO",
            fecha_inicio=(hoy - timedelta(days=100)).isoformat(),
            fecha_fin=(hoy + timedelta(days=10)).isoformat(),
        )
        assert self.lista(api, equipo, contrato="vigente").json()["count"] == 1
        assert self.lista(api, equipo, contrato="por_vencer").json()["count"] == 1
        assert self.lista(api, equipo, contrato="vencido").json()["count"] == 0
        assert self.lista(api, equipo, contrato="cualquiera").status_code == 400

    def test_busqueda_por_nombre_o_documento(self, equipo):
        api = cliente_de("super")
        assert self.lista(api, equipo, q="quispe").json()["count"] == 1
        assert self.lista(api, equipo, q="4567").json()["count"] == 1
        assert self.lista(api, equipo, q="zzz").json()["count"] == 0

    def test_sin_permiso_no_se_ve_nada(self, equipo):
        assert self.lista(cliente_de("cajero"), equipo).status_code == 403
        assert ficha(cliente_de("cajero"), equipo).status_code in (403, 404)

    def test_contador_ve_la_lista(self, equipo):
        assert self.lista(cliente_de("contador"), equipo).status_code == 200

    def test_otra_organizacion_no_ve_ni_toca_nada(self, equipo):
        api = cliente_de("otra_org")
        assert ficha(api, equipo).status_code in (403, 404)
        t = equipo["trabajador"]
        r = api.patch(f"{BASE}/trabajadores/{t.pk}/datos-laborales/", {"sexo": "F"}, format="json")
        assert r.status_code in (403, 404)
        assert self.lista(api, equipo).status_code in (403, 404)

    def test_el_regimen_de_otra_organizacion_no_sirve(self, equipo):
        ajeno = RegimenLaboral.objects.sin_ambito().get(
            organizacion=equipo["e"].org_b, codigo="GENERAL"
        )
        r = crear(cliente_de("super"), equipo, regimen=ajeno.pk)
        assert r.status_code == 400
