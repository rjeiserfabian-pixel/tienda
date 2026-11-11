"""RR.HH. (RH8): reportes para el contador y acceso del propio trabajador a lo suyo.

Reutiliza el equipo de las pruebas de planilla (una trabajadora desde el 2 de enero de 2026, sueldo
de 1,500, ONP). Los valores legales son DATOS DE PRUEBA.
"""

import io
import itertools
from decimal import Decimal as D

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.mantenimiento.models import Personal
from apps.rrhh.models import ConceptoPlanilla
from apps.rrhh.tests.test_planilla import (
    BASE,
    cerrada,
    completar_marzo,
    pagar,
    preparar,
)
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

_claves = itertools.count(1)


def reporte(api, equipo, tipo, formato="", **params):
    parametros = {"empresa": equipo["e"].emp_a1.pk, **params}
    consulta = "&".join(f"{k}={v}" for k, v in parametros.items())
    return api.get(f"{BASE}/reportes/{tipo}/{formato}?{consulta}")


def libro(respuesta):
    return load_workbook(io.BytesIO(respuesta.content))


# ---------------------------------------------------------------------------
class TestReportes:
    def test_planilla_del_mes_con_una_columna_por_concepto(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        preparar(api, equipo)
        r = reporte(api, equipo, "planilla", periodo="2026-03")
        assert r.status_code == 200, r.content
        tabla = r.json()["tablas"][0]
        titulos = [c["titulo"] for c in tabla["columnas"]]
        assert "Sueldo básico (+)" in titulos and "ONP (-)" in titulos
        fila = dict(zip(titulos, tabla["filas"][0], strict=True))
        assert fila["Sueldo básico (+)"] == "1500.00" and fila["Neto a pagar"] == "1305.00"
        assert dict(zip(titulos, tabla["totales"], strict=True))["Neto a pagar"] == "1305.00"
        assert any("no está cerrada" in a for a in r.json()["avisos"])

    def test_excel_con_el_nombre_como_texto(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        preparar(api, equipo)
        Personal.objects.sin_ambito().filter(pk=equipo["trabajador"].pk).update(nombres="=1+1")
        r = reporte(api, equipo, "planilla", "excel/", periodo="2026-03")
        assert r.status_code == 200
        assert "spreadsheetml" in r["Content-Type"] and "planilla-" in r["Content-Disposition"]
        hoja = libro(r)["Planilla"]
        textos = [str(c.value) for fila in hoja.iter_rows() for c in fila if c.value is not None]
        nombre = next(t for t in textos if "=1+1" in t)
        celda = next(c for fila in hoja.iter_rows() for c in fila if str(c.value) == nombre)
        assert celda.data_type == "s"  # texto, nunca una fórmula

    def test_plame_pide_la_planilla_cerrada_y_avisa_los_codigos_faltantes(self, equipo):
        api = cliente_de("super")
        completar_marzo(api, equipo)
        preparar(api, equipo)
        assert reporte(api, equipo, "plame", periodo="2026-03").status_code == 400
        api, planilla, _ = cerrada_marzo(api, equipo)
        r = reporte(api, equipo, "plame", periodo="2026-03")
        assert r.status_code == 200, r.content
        cuerpo = r.json()
        assert [t["hoja"] for t in cuerpo["tablas"]] == ["Conceptos", "Jornada"]
        filas = {f[4]: f for f in cuerpo["tablas"][0]["filas"]}
        assert filas["Sueldo básico"][3] == "SIN CÓDIGO" and filas["Sueldo básico"][6] == "1500.00"
        assert any("Sueldo básico" in a and "sin código" in a.lower() for a in cuerpo["avisos"])
        assert any("no es el archivo oficial" in a for a in cuerpo["avisos"])
        # El contador completa el código en el catálogo y el reporte lo usa.
        ConceptoPlanilla.objects.sin_ambito().filter(
            organizacion=equipo["e"].org_a, codigo="SUELDO_BASICO"
        ).update(codigo_plame="0121")
        filas = {
            f[4]: f
            for f in reporte(api, equipo, "plame", periodo="2026-03").json()["tablas"][0]["filas"]
        }
        assert filas["Sueldo básico"][3] == "0121"

    def test_t_registro_no_lleva_sueldos_ni_cuentas(self, equipo):
        api = cliente_de("super")
        r = reporte(api, equipo, "t-registro")
        assert r.status_code == 200, r.content
        tabla = r.json()["tablas"][0]
        titulos = " ".join(c["titulo"] for c in tabla["columnas"]).lower()
        assert "sueldo" not in titulos and "cuenta" not in titulos and "cci" not in titulos
        fila = dict(zip([c["titulo"] for c in tabla["columnas"]], tabla["filas"][0], strict=True))
        assert fila["Documento"] == "45678912" and fila["Régimen laboral"].startswith("Pequeña")

    def test_resumen_anual(self, equipo):
        api, _, _ = cerrada(equipo)
        r = reporte(api, equipo, "anual", anio=2026)
        assert r.status_code == 200, r.content
        tabla = r.json()["tablas"][0]
        titulos = [c["titulo"] for c in tabla["columnas"]]
        fila = dict(zip(titulos, tabla["filas"][0], strict=True))
        assert fila["Mar"] == "1305.00" and fila["Total neto"] == "1305.00"
        assert fila["Total descuentos"] == "195.00" and fila["Renta de 5.ª retenida"] == "0.00"
        assert reporte(api, equipo, "anual", anio=2025).status_code == 400

    def test_pedidos_invalidos(self, equipo):
        api = cliente_de("super")
        assert reporte(api, equipo, "inexistente").status_code == 400
        assert reporte(api, equipo, "planilla", periodo="marzo").status_code == 400
        assert reporte(api, equipo, "planilla", periodo="2026-03").status_code == 400  # no hay

    def test_permisos_y_auditoria_sin_datos(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        api, _, _ = cerrada(equipo)
        assert (
            reporte(cliente_de("contador"), equipo, "anual", "excel/", anio=2026).status_code == 200
        )
        assert reporte(cliente_de("rrhh"), equipo, "t-registro").status_code == 200
        assert reporte(cliente_de("cajero"), equipo, "t-registro").status_code == 403
        assert reporte(cliente_de("cajero"), equipo, "t-registro", "excel/").status_code == 403
        assert reporte(cliente_de("otra_org"), equipo, "t-registro").status_code in (403, 404)
        eventos = AuditoriaEvento.objects.filter(accion="rrhh.reporte_exportado")
        assert eventos.count() == 1
        assert "1305" not in str([(e.resumen, e.detalle) for e in eventos])


def cerrada_marzo(api, equipo):
    r = api.get(f"{BASE}/planillas/?empresa={equipo['e'].emp_a1.pk}").json()["results"][0]
    c = api.post(f"{BASE}/planillas/{r['id']}/cerrar/", {}, format="json")
    assert c.status_code == 200, c.content
    return api, c.json(), r["id"]


# ---------------------------------------------------------------------------
@pytest.fixture
def con_usuario(equipo, nuevo_usuario):
    """La trabajadora del equipo con su propio usuario (rol Trabajador) y otro usuario sin ficha."""
    e = equipo["e"]
    usuario = nuevo_usuario(e.org_a, "mi_trabajadora", [e.emp_a1], [("TRABAJADOR", None)])
    Personal.objects.sin_ambito().filter(pk=equipo["trabajador"].pk).update(usuario=usuario)
    ajeno = Personal.objects.sin_ambito().create(
        empresa=e.emp_a1,
        tipo_documento="DNI",
        numero_documento="70000002",
        nombres="Luis",
        apellidos="Rojas",
        area="VENTAS",
    )
    otro = nuevo_usuario(e.org_a, "mi_colega", [e.emp_a1], [("TRABAJADOR", None)])
    Personal.objects.sin_ambito().filter(pk=ajeno.pk).update(usuario=otro)
    nuevo_usuario(e.org_a, "sin_ficha", [e.emp_a1], [("TRABAJADOR", None)])
    return equipo


def mi(api, equipo, ruta):
    return api.get(f"{BASE}/mi/{ruta}?empresa={equipo['e'].emp_a1.pk}")


class TestAutoservicio:
    def test_solo_ve_sus_boletas_de_planillas_cerradas(self, con_usuario):
        equipo = con_usuario
        yo = cliente_de("mi_trabajadora")
        admin = cliente_de("super")
        completar_marzo(admin, equipo)
        planilla = preparar(admin, equipo).json()
        # En revisión todavía no se ve.
        assert mi(yo, equipo, "resumen/").json()["boletas"] == []
        assert mi(yo, equipo, f"boletas/{planilla['id']}/").status_code == 404
        admin.post(f"{BASE}/planillas/{planilla['id']}/cerrar/", {}, format="json")
        resumen = mi(yo, equipo, "resumen/").json()
        assert resumen["nombre_completo"].startswith("Rosa")
        assert [b["neto"] for b in resumen["boletas"]] == ["1305.00"]
        assert resumen["boletas"][0]["fecha_pago"] is None
        boleta = mi(yo, equipo, f"boletas/{planilla['id']}/").json()
        assert boleta["trabajador"]["numero_documento"] == "45678912"
        assert boleta["neto"] == "1305.00" and boleta["es_borrador"] is False

    def test_aparece_si_ya_le_pagaron(self, con_usuario):
        equipo = con_usuario
        admin, planilla, detalle = cerrada(equipo)
        pagar(admin, equipo, planilla, detalle)
        boletas = mi(cliente_de("mi_trabajadora"), equipo, "resumen/").json()["boletas"]
        assert boletas[0]["fecha_pago"] == "2026-04-02"

    def test_ve_su_saldo_de_vacaciones_y_lo_que_debe(self, con_usuario):
        equipo = con_usuario
        admin = cliente_de("super")
        r = admin.post(
            f"{BASE}/adelantos/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "personal": equipo["trabajador"].pk,
                "tipo": "ADELANTO",
                "fecha": timezone.localdate().isoformat(),
                "monto": "300.00",
                "cuenta": equipo["caja"].pk,
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"mi-adel-{next(_claves):06d}",
        )
        assert r.status_code == 201, r.content
        resumen = mi(cliente_de("mi_trabajadora"), equipo, "resumen/").json()
        assert D(resumen["vacaciones"]["saldo"]) > 0 and resumen["vacaciones"]["tomados"] == 0
        assert [a["pendiente"] for a in resumen["adelantos"]] == ["300.00"]

    def test_no_ve_lo_de_otro_trabajador(self, con_usuario):
        equipo = con_usuario
        admin, planilla, _ = cerrada(equipo)
        colega = cliente_de("mi_colega")
        # Mismo id de planilla, pero la boleta de ella no es del colega.
        assert mi(colega, equipo, f"boletas/{planilla['id']}/").status_code == 404
        assert mi(colega, equipo, "resumen/").json()["boletas"] == []

    def test_sin_ficha_o_sin_permiso_no_entra(self, con_usuario):
        equipo = con_usuario
        r = mi(cliente_de("sin_ficha"), equipo, "resumen/")
        assert r.status_code == 403 and "no está vinculado" in r.content.decode()
        assert mi(cliente_de("cajero"), equipo, "resumen/").status_code == 403
        assert mi(cliente_de("contador"), equipo, "resumen/").status_code == 403

    def test_el_trabajador_no_ve_planillas_ni_reportes(self, con_usuario):
        equipo = con_usuario
        yo = cliente_de("mi_trabajadora")
        empresa = equipo["e"].emp_a1.pk
        assert yo.get(f"{BASE}/planillas/?empresa={empresa}").status_code == 403
        assert reporte(yo, equipo, "t-registro").status_code == 403
        assert yo.get(f"{BASE}/trabajadores/?empresa={empresa}").status_code == 403
