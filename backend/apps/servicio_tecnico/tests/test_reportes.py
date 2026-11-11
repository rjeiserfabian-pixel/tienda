"""Tablero, reportes, utilidad por servicio y comisiones de los técnicos."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.mantenimiento.models import Personal
from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import reportes
from apps.servicio_tecnico.models import ComisionTecnico, EstadoOrden
from apps.servicio_tecnico.tests.test_garantia import _entregar, _terminada
from apps.servicio_tecnico.tests.test_presupuesto import BASE, _con_tecnico
from apps.ventas.servicios import anular_venta

pytestmark = pytest.mark.django_db

E = EstadoOrden


def _tecnico(banco, documento="40123456", comision=None):
    personal = Personal.objects.create(
        empresa=banco.empresa,
        tipo_documento="DNI",
        numero_documento=documento,
        nombres="Mario",
        apellidos="Quispe",
        area="TECNICO",
    )
    if comision is not None:
        reportes.fijar_comision(personal, Decimal(comision))
    return personal


def _periodo():
    hoy = timezone.localdate()
    return reportes.Periodo(hoy - timedelta(days=1), hoy)


class TestComisionAlEntregar:
    def test_se_calcula_sobre_la_mano_de_obra_cobrada(self, banco):
        tecnico = _tecnico(banco, comision="10")
        orden = _terminada(banco, (banco.servicio, 1), (banco.ram, 2), tecnico=tecnico)
        _entregar(banco, orden, "295.00")
        orden.refresh_from_db()
        assert (orden.comision_base, orden.comision_porcentaje, orden.comision_monto) == (
            Decimal("50.00"),  # solo el servicio, sin IGV; los repuestos no comisionan
            Decimal("10.00"),
            Decimal("5.00"),
        )

    def test_conserva_el_porcentaje_de_ese_dia(self, banco):
        tecnico = _tecnico(banco, comision="10")
        orden = _terminada(banco, (banco.servicio, 1), tecnico=tecnico)
        _entregar(banco, orden, "59.00")
        reportes.fijar_comision(tecnico, Decimal("25"))
        orden.refresh_from_db()
        assert orden.comision_porcentaje == Decimal("10.00")

    def test_sin_porcentaje_o_sin_tecnico_no_hay_comision(self, banco):
        sin_porcentaje = _terminada(banco, (banco.servicio, 1), tecnico=_tecnico(banco))
        _entregar(banco, sin_porcentaje, "59.00")
        sin_porcentaje.refresh_from_db()
        assert sin_porcentaje.comision_monto == Decimal("0.00")
        sin_tecnico = _terminada(banco, (banco.servicio, 1))
        _entregar(banco, sin_tecnico, "59.00")
        sin_tecnico.refresh_from_db()
        assert sin_tecnico.comision_monto is None

    def test_el_porcentaje_se_valida(self, banco):
        tecnico = _tecnico(banco)
        for malo in ("-1", "101"):
            with pytest.raises(ValueError, match="0 a 100"):
                reportes.fijar_comision(tecnico, Decimal(malo))
        administrativo = Personal.objects.create(
            empresa=banco.empresa,
            tipo_documento="DNI",
            numero_documento="41234567",
            nombres="Eva",
            apellidos="Ríos",
            area="ADMINISTRACION",
        )
        with pytest.raises(ValueError, match="área técnica"):
            reportes.fijar_comision(administrativo, Decimal("5"))
        assert ComisionTecnico.objects.count() == 0


class TestResumen:
    def test_cuenta_lo_que_entra_sale_y_sigue_abierto(self, banco):
        entregada = _terminada(banco, (banco.ram, 1))
        _entregar(banco, entregada, "118.00")
        atrasada = banco.orden(fecha_promesa=timezone.localdate() - timedelta(days=2))
        banco.orden()
        r = reportes.resumen(banco.empresa.pk, _periodo())
        assert r["entregadas"] == 1
        assert r["ingresadas"] == 3
        assert r["abiertas"] == 2
        assert r["atrasadas"] == 1
        assert r["ciclo_promedio_dias"] is not None
        assert {f["estado"]: f["cantidad"] for f in r["por_estado"]} == {"EN_DIAGNOSTICO": 2}
        assert atrasada.pk

    def test_los_reingresos_por_garantia_se_miden_contra_lo_entregado(self, banco):
        from apps.servicio_tecnico import garantia

        original = _terminada(banco, (banco.ram, 1))
        _entregar(banco, original, "118.00")
        garantia.reingreso_por_garantia(original, falla_reportada="Vuelve a fallar")
        r = reportes.resumen(banco.empresa.pk, _periodo())
        assert r["reingresos_garantia"] == 1
        assert r["reingresos_sobre_entregadas"] == 100.0

    def test_tiempos_por_estado(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        t = reportes.tiempos_por_estado(banco.empresa.pk, _periodo())
        estados = {f["estado"]: f for f in t["estados"]}
        assert {
            "PENDIENTE_APROBACION",
            "APROBADO",
            "EN_REPARACION",
            "EN_PRUEBAS",
            "TERMINADO",
        } <= set(estados)
        assert "LISTO_ENTREGA" not in estados  # sigue abierto: aún no tiene duración
        assert all(f["veces"] >= 1 for f in estados.values()) and t["truncado"] is False
        assert orden.estado == E.LISTO_ENTREGA

    def test_el_periodo_se_valida(self):
        hoy = timezone.localdate()
        with pytest.raises(ValueError, match="posterior"):
            reportes.Periodo.validar(hoy, hoy - timedelta(days=1))
        with pytest.raises(ValueError, match="366"):
            reportes.Periodo.validar(hoy - timedelta(days=400), hoy)
        assert reportes.Periodo.validar(None, None).hasta == hoy


class TestTecnicosYUtilidad:
    def test_el_tecnico_rinde_y_gana(self, banco):
        tecnico = _tecnico(banco, comision="10")
        orden = _terminada(banco, (banco.servicio, 1), (banco.ram, 2), tecnico=tecnico)
        _entregar(banco, orden, "295.00")
        pendiente = banco.orden(tecnico=tecnico)
        assert pendiente.tecnico_id == tecnico.pk
        con = reportes.tecnicos(banco.empresa.pk, _periodo(), con_importes=True)[0]
        assert (con["abiertas"], con["entregadas"], con["porcentaje"]) == (1, 1, "10.00")
        assert (con["mano_obra"], con["comision"]) == ("50.00", "5.00")
        sin = reportes.tecnicos(banco.empresa.pk, _periodo(), con_importes=False)[0]
        assert "comision" not in sin and "mano_obra" not in sin and sin["entregadas"] == 1

    def test_la_utilidad_descuenta_repuestos_y_comision(self, banco):
        tecnico = _tecnico(banco, comision="10")
        orden = _terminada(banco, (banco.servicio, 1), (banco.ram, 2), tecnico=tecnico)
        _entregar(banco, orden, "295.00")
        total = reportes.utilidad_resumen(banco.empresa.pk, _periodo())["totales"]
        assert total == {
            "servicios": "1",
            "ingreso": "250.00",  # 50 de mano de obra + 2 × 100, sin IGV
            "costo": "100.00",  # lo que costaron las 2 memorias al salir del stock
            "comision": "5.00",
            "utilidad": "145.00",
        }
        fila = reportes.utilidad_ordenes(banco.empresa.pk, _periodo()).get()
        assert (fila.ingreso, fila.costo_repuestos, fila.utilidad) == (
            Decimal("250.00"),
            Decimal("100.00"),
            Decimal("145.00"),
        )

    def test_lo_no_cobrado_o_anulado_no_suma(self, banco):
        from apps.servicio_tecnico import entrega

        sin_cobro = _terminada(banco, (banco.ram, 1))
        entrega.entregar_equipo(
            sin_cobro, vendedor_nombre="Rosa", sin_cobro=True, motivo_sin_cobro="Cortesía"
        )
        anulada = _terminada(banco, (banco.ram, 1))
        _, venta = _entregar(banco, anulada, "118.00")
        anular_venta(venta, motivo="Error al emitir el comprobante")
        assert (
            reportes.utilidad_resumen(banco.empresa.pk, _periodo())["totales"]["servicios"] == "0"
        )

    def test_agrupa_por_tipo_de_servicio(self, banco):
        a = _terminada(banco, (banco.ram, 1))
        b = _terminada(banco, (banco.ram, 1), codigo="CAMBIO_PANTALLA")
        c = _terminada(banco, (banco.ram, 1))
        for orden in (a, b, c):
            _entregar(banco, orden, "118.00")
        tipos = reportes.utilidad_resumen(banco.empresa.pk, _periodo())["por_tipo_servicio"]
        assert {t["nombre"]: t["servicios"] for t in tipos} == {
            "Reparación de hardware": 2,
            "Cambio de pantalla": 1,
        }


class TestEquiposRepetidos:
    def test_lista_los_que_vuelven(self, banco):
        banco.orden()
        banco.orden()
        r = reportes.equipos_mas_reparados(banco.empresa.pk, _periodo())
        assert [f["ingresos"] for f in r["equipos"]] == [2]
        assert r["equipos"][0]["marca"] == "HP"
        assert r["modelos"][0]["ingresos"] == 2


class TestApi:
    def test_resumen_con_importes_para_quien_ve_la_utilidad(self, banco):
        tecnico = _tecnico(banco, comision="10")
        orden = _terminada(banco, (banco.servicio, 1), (banco.ram, 2), tecnico=tecnico)
        _entregar(banco, orden, "295.00")
        r = cliente_de("admin").get(f"{BASE}/reportes/resumen/", {"empresa": banco.empresa.pk})
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["con_importes"] is True
        assert datos["resumen"]["entregadas"] == 1
        assert datos["utilidad"]["totales"]["utilidad"] == "145.00"
        assert datos["tecnicos"][0]["comision"] == "5.00"

    def test_utilidad_paginada(self, banco):
        for _ in range(3):
            orden = _terminada(banco, (banco.ram, 1))
            _entregar(banco, orden, "118.00")
        r = cliente_de("admin").get(
            f"{BASE}/reportes/utilidad/", {"empresa": banco.empresa.pk, "page_size": 10}
        )
        assert r.status_code == 200, r.content
        assert r.json()["count"] == 3 and r.json()["results"][0]["utilidad"] == "50.00"

    def test_solo_quien_tiene_el_permiso(self, banco):
        for usuario in ("tecnico", "vendedor"):
            api = cliente_de(usuario)
            for ruta in ("reportes/resumen/", "reportes/utilidad/", "comisiones/"):
                r = api.get(f"{BASE}/{ruta}", {"empresa": banco.empresa.pk})
                assert r.status_code == 403, (usuario, ruta)

    def test_el_periodo_invalido_se_rechaza(self, banco):
        api = cliente_de("admin")
        base = {"empresa": banco.empresa.pk}
        assert api.get(f"{BASE}/reportes/resumen/", {**base, "desde": "ayer"}).status_code == 400
        malo = {**base, "desde": "2026-12-31", "hasta": "2026-01-01"}
        assert api.get(f"{BASE}/reportes/resumen/", malo).status_code == 400

    def test_comisiones_se_listan_y_se_fijan(self, banco):
        tecnico = _tecnico(banco)
        api = cliente_de("admin")
        base = {"empresa": banco.empresa.pk}
        lista = api.get(f"{BASE}/comisiones/", base).json()["tecnicos"]
        assert [(t["id"], t["porcentaje"]) for t in lista] == [(tecnico.pk, "0.00")]
        r = api.put(
            f"{BASE}/comisiones/{tecnico.pk}/?empresa={banco.empresa.pk}",
            {"porcentaje": "12.5"},
            format="json",
        )
        assert (r.status_code, r.json()["porcentaje"]) == (200, "12.50")
        assert api.get(f"{BASE}/comisiones/", base).json()["tecnicos"][0]["porcentaje"] == "12.50"

    def test_comision_invalida(self, banco):
        tecnico = _tecnico(banco)
        api = cliente_de("admin")
        url = f"{BASE}/comisiones/{tecnico.pk}/?empresa={banco.empresa.pk}"
        assert api.put(url, {"porcentaje": "101"}, format="json").status_code == 400
        assert api.put(url, {"porcentaje": "-1"}, format="json").status_code == 400
        inexistente = f"{BASE}/comisiones/99999/?empresa={banco.empresa.pk}"
        assert api.put(inexistente, {"porcentaje": "5"}, format="json").status_code == 404

    def test_tablero_cuenta_y_muestra_las_primeras_tarjetas(self, banco):
        banco.orden(estado=E.EN_DIAGNOSTICO)
        banco.orden(estado=E.EN_DIAGNOSTICO, prioridad="URGENTE")
        banco.orden(estado=E.LISTO_ENTREGA)
        banco.orden(estado=E.ENTREGADO)
        r = cliente_de("admin").get(f"{BASE}/tablero/", {"empresa": banco.empresa.pk})
        assert r.status_code == 200, r.content
        columnas = {c["estado"]: c for c in r.json()["columnas"]}
        assert "ENTREGADO" not in columnas
        assert columnas["EN_DIAGNOSTICO"]["cantidad"] == 2
        assert columnas["EN_DIAGNOSTICO"]["tarjetas"][0]["prioridad"] == "URGENTE"
        assert columnas["LISTO_ENTREGA"]["cantidad"] == 1
        assert columnas["RECIBIDO"]["cantidad"] == 0

    def test_tablero_del_tecnico_solo_trae_lo_suyo(self, banco):
        suya = banco.orden()
        _con_tecnico(banco, suya)
        banco.orden()
        r = cliente_de("tecnico").get(f"{BASE}/tablero/", {"empresa": banco.empresa.pk})
        assert r.status_code == 200
        total = sum(c["cantidad"] for c in r.json()["columnas"])
        assert total == 1

    def test_tablero_marca_atrasadas_y_filtra(self, banco):
        tecnico = _tecnico(banco)
        banco.orden(fecha_promesa=timezone.localdate() - timedelta(days=3), tecnico=tecnico)
        banco.orden()
        api = cliente_de("admin")
        r = api.get(f"{BASE}/tablero/", {"empresa": banco.empresa.pk, "tecnico": tecnico.pk})
        diag = {c["estado"]: c for c in r.json()["columnas"]}["EN_DIAGNOSTICO"]
        assert diag["cantidad"] == 1 and diag["tarjetas"][0]["atrasada"] is True
        assert (
            api.get(f"{BASE}/tablero/", {"empresa": banco.empresa.pk, "tecnico": "x"}).status_code
            == 400
        )
