"""Cierre mensual de comisiones: liquidación por persona, orden de los meses, arrastre y API."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from apps.comisiones import avance, cierre, escalas, periodos, servicios
from apps.comisiones.models import (
    LineaLiquidacion,
    LiquidacionComision,
    MovimientoComision,
)
from apps.seguridad.models import Usuario
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import notas_credito

pytestmark = pytest.mark.django_db

BASE = "/api/v1/comisiones"


def org(tienda):
    return tienda.entorno.e.org_a


def ana():
    return Usuario.objects.get(username="vendedor")


def mes_de(tienda):
    hoy = tienda.entorno.hoy
    return hoy.year, hoy.month


def despues_del_mes(año, mes, dias=2):
    """Un día cualquiera del mes siguiente: para poder cerrar el mes (ya terminó)."""
    return periodos.fin_de_periodo(avance.periodo_de(año, mes)) + timedelta(days=dias)


def regla(tienda, porcentaje="3", **extra):
    return servicios.crear(
        org(tienda).pk, {"alcance": "GENERAL", "porcentaje": porcentaje, **extra}
    )


def vender(tienda, producto, cantidad=1, **extra):
    return tienda.vender(
        [tienda.linea(producto, cantidad)],
        [tienda.cobro(tienda.efectivo, f"{118 * cantidad}.00")],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
        vendedor_id=ana().pk,
        **extra,
    )


def producto(tienda):
    return tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 30})


def cerrar(tienda, año=None, mes=None, hoy=None):
    año, mes = (año, mes) if año else mes_de(tienda)
    return cierre.cerrar_mes(org(tienda).pk, año, mes, hoy=hoy or despues_del_mes(año, mes))


class TestCerrar:
    def test_liquida_lo_ganado_con_su_detalle(self, tienda):
        regla(tienda, "3")
        venta = vender(tienda, producto(tienda), 2)  # 200 netos al 3 % = 6,00
        liq = cerrar(tienda)
        linea = liq.lineas.get()
        assert (linea.comisiones_ventas, linea.a_pagar, linea.estado) == (
            D("6.00"),
            D("6.00"),
            "PENDIENTE",
        )
        assert linea.vendedor_id == ana().pk and linea.clave == f"U:{ana().pk}"
        (detalle,) = linea.detalle["ventas"]
        assert detalle["comprobante"] == venta.comprobantes.get().numero_completo
        assert detalle["monto"] == "6.00"
        assert liq.total_a_pagar == D("6.00") and liq.periodo == avance.periodo_de(*mes_de(tienda))

    def test_el_cierre_aplica_la_escala_y_otorga_los_bonos(self, tienda):
        regla(tienda, "2")
        escalas.crear_escala(
            org(tienda).pk,
            {
                "nombre": "Mensual",
                "tramos": [
                    {"desde": "0", "porcentaje": "2"},
                    {"desde": "1000", "porcentaje": "4"},
                ],
            },
        )
        escalas.crear_meta(org(tienda).pk, {"nombre": "Meta 1000", "meta": "1000", "bono": "100"})
        vender(tienda, producto(tienda), 10)  # 1 000 vendidos: tramo del 4 % y meta cumplida
        linea = cerrar(tienda).lineas.get()
        assert linea.comisiones_ventas == D("40.00")  # 4 % de 1 000, no 2 %
        assert linea.bonos == D("100.00")
        assert (linea.total, linea.a_pagar) == (D("140.00"), D("140.00"))
        assert linea.detalle["bonos"][0]["nombre"] == "Meta 1000"

    def test_solo_se_cierra_un_mes_terminado(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda))
        año, mes = mes_de(tienda)
        fin = periodos.fin_de_periodo(avance.periodo_de(año, mes))
        with pytest.raises(cierre.CierreInvalido, match="todavía no termina"):
            cerrar(tienda, hoy=fin)

    def test_no_se_cierra_dos_veces_ni_se_salta_un_mes(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda))
        año, mes = mes_de(tienda)
        cerrar(tienda)
        with pytest.raises(cierre.CierreInvalido, match="ya está cerrado"):
            cerrar(tienda)
        siguiente = periodos.fin_de_periodo(avance.periodo_de(año, mes)) + timedelta(days=1)
        saltado = siguiente + timedelta(days=32)
        with pytest.raises(cierre.CierreInvalido, match="Primero cierra"):
            cerrar(tienda, saltado.year, saltado.month, hoy=saltado + timedelta(days=40))

    def test_dice_cual_es_el_proximo_mes_por_cerrar(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda))
        año, mes = mes_de(tienda)
        hoy = despues_del_mes(año, mes)
        assert cierre.mes_por_cerrar(org(tienda).pk, hoy=hoy) == avance.periodo_de(año, mes)
        assert cierre.mes_por_cerrar(org(tienda).pk, hoy=tienda.entorno.hoy) is None


class TestMesCerradoNoSeMueve:
    def test_una_devolucion_tarde_cae_en_el_mes_siguiente_y_se_arrastra(self, tienda):
        regla(tienda, "3")
        venta = vender(tienda, producto(tienda), 2)  # gana 6,00 en el mes
        año, mes = mes_de(tienda)
        primero = cerrar(tienda)
        assert primero.lineas.get().a_pagar == D("6.00")

        comp = venta.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="01",  # se devuelve todo
            reembolsos=[tienda.cobro(tienda.efectivo, "236.00")],
        )
        # El movimiento de ajuste cayó DESPUÉS del cierre, no dentro del mes ya liquidado.
        ajuste = MovimientoComision.objects.sin_ambito().order_by("-id").first()
        assert ajuste.monto == D("-6.00")
        assert ajuste.fecha == periodos.fin_de_periodo(primero.periodo) + timedelta(days=1)
        assert primero.lineas.get().a_pagar == D("6.00")  # lo cerrado no cambia

        sig = periodos.fin_de_periodo(primero.periodo) + timedelta(days=1)
        segundo = cerrar(tienda, sig.year, sig.month, hoy=despues_del_mes(sig.year, sig.month))
        linea = segundo.lineas.get()
        # Ganó −6,00 este mes: no se le cobra, queda debiendo y se arrastra.
        assert (linea.total, linea.a_pagar, linea.arrastre_nuevo) == (
            D("-6.00"),
            D("0"),
            D("-6.00"),
        )
        assert linea.estado == "SIN_MONTO" and segundo.total_a_pagar == 0

        sig2 = periodos.fin_de_periodo(segundo.periodo) + timedelta(days=1)
        tercero = cerrar(tienda, sig2.year, sig2.month, hoy=despues_del_mes(sig2.year, sig2.month))
        linea = tercero.lineas.get()  # sin actividad, pero conserva lo que debe
        assert (linea.arrastre_anterior, linea.total, linea.arrastre_nuevo) == (
            D("-6.00"),
            D("0"),
            D("-6.00"),
        )

    def test_la_escala_y_los_bonos_no_se_tocan_en_un_mes_cerrado(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda))
        año, mes = mes_de(tienda)
        cerrar(tienda)
        with pytest.raises(servicios.ReglaInvalida, match="ya está cerrado"):
            avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes)
        with pytest.raises(servicios.ReglaInvalida, match="ya está cerrado"):
            avance.otorgar_bonos_del_mes(org(tienda).pk, ana().pk, año, mes)


class TestApi:
    def test_el_administrador_cierra_y_ve_la_liquidacion(self, tienda):
        regla(tienda, "3")
        vender(tienda, producto(tienda), 2)
        año, mes = mes_de(tienda)
        liq = cerrar(tienda)  # antes de la API: cada llamada a la API limpia el contexto
        admin = cliente_de("admin")
        # Ya cerrado (o, si no, todavía en curso): la API responde que no se puede.
        r = admin.post(f"{BASE}/liquidaciones/", {"mes": f"{año}-{mes:02d}"}, format="json")
        assert r.status_code == 409, r.content
        assert (
            admin.post(f"{BASE}/liquidaciones/", {"mes": "marzo"}, format="json").status_code == 400
        )
        lista = admin.get(f"{BASE}/liquidaciones/").json()
        assert [f["periodo"] for f in lista["results"]] == [liq.periodo]
        assert lista["results"][0]["total_a_pagar"] == "6.00"
        detalle = admin.get(f"{BASE}/liquidaciones/{liq.pk}/").json()
        (linea,) = detalle["lineas"]
        assert (linea["nombre"], linea["a_pagar"], linea["estado"]) == (
            "vendedor",
            "6.00",
            "PENDIENTE",
        )
        assert linea["detalle"]["ventas"][0]["monto"] == "6.00"

    def test_el_vendedor_no_cierra_ni_ve_las_liquidaciones_de_todos(self, tienda):
        v = cliente_de("vendedor")
        assert v.get(f"{BASE}/liquidaciones/").status_code == 403
        assert (
            v.post(f"{BASE}/liquidaciones/", {"mes": "2026-01"}, format="json").status_code == 403
        )

    def test_marcar_pagada_aparte_pide_una_nota_y_solo_si_esta_por_pagar(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda), 2)
        linea = cerrar(tienda).lineas.get()
        admin = cliente_de("admin")
        url = f"{BASE}/liquidaciones/lineas/{linea.pk}/pagada/"
        assert admin.post(url, {"nota": "ok"}, format="json").status_code == 409
        r = admin.post(url, {"nota": "Transferencia del 15/12"}, format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["estado"], r.json()["pagada_nota"]) == (
            "PAGADA_APARTE",
            "Transferencia del 15/12",
        )
        assert admin.post(url, {"nota": "Otra vez"}, format="json").status_code == 409

    def test_sin_ficha_de_personal_no_va_a_la_planilla(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda), 2)
        linea = cerrar(tienda).lineas.get()
        r = cliente_de("admin").post(
            f"{BASE}/liquidaciones/lineas/{linea.pk}/planilla/", {"mes": "2026-12"}, format="json"
        )
        assert r.status_code == 409 and "ficha de personal" in r.json()["error"]["mensaje"]

    def test_mis_comisiones_solo_muestra_lo_mio_y_el_ranking_no_trae_comisiones(self, tienda):
        regla(tienda, "3")
        vender(tienda, producto(tienda), 2)
        año, mes = mes_de(tienda)
        r = cliente_de("vendedor").get(
            f"{BASE}/mias/", {"empresa": tienda.a.pk, "mes": f"{año}-{mes:02d}"}
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["ganado_hasta_hoy"]["ventas"] == "6.00"
        assert d["avance"]["ventas"] == "200.00"
        assert d["ranking"]["posicion"] == 1 and d["ranking"]["top"][0]["soy_yo"] is True
        assert "comision" not in str(d["ranking"]).lower()
        # Otro vendedor no ve lo mío.
        otro = cliente_de("cajero").get(
            f"{BASE}/mias/", {"empresa": tienda.a.pk, "mes": f"{año}-{mes:02d}"}
        )
        assert otro.status_code == 403  # el cajero no tiene el permiso de «mis comisiones»

    def test_las_lineas_de_otra_persona_no_aparecen_en_mis_comisiones(self, tienda):
        regla(tienda)
        vender(tienda, producto(tienda), 2)
        cerrar(tienda)
        r = cliente_de("vendedor").get(f"{BASE}/mias/", {"empresa": tienda.a.pk})
        assert r.status_code == 200
        assert [f["nombre"] for f in r.json()["liquidaciones"]] == ["vendedor"]
        assert LiquidacionComision.objects.sin_ambito().count() == 1
        assert LineaLiquidacion.objects.sin_ambito().count() == 1


def test_fechas_de_ayuda():
    assert periodos.fin_de_periodo("2026-12") == date(2026, 12, 31)
    assert periodos.fin_de_periodo("2026-02") == date(2026, 2, 28)
