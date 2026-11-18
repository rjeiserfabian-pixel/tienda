"""Escalas mensuales, metas con bono y avance del mes."""

from decimal import Decimal as D

import pytest

from apps.comisiones import avance, calculo, escalas, servicios
from apps.comisiones.models import (
    BonoGanado,
    ComisionComprobante,
    EscalaComision,
    MovimientoComision,
)
from apps.comisiones.servicios import ReglaInvalida
from apps.seguridad.models import Usuario
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import cuentas_por_cobrar, notas_credito

pytestmark = pytest.mark.django_db

BASE = "/api/v1/comisiones"


def org(tienda):
    return tienda.entorno.e.org_a


def ana():
    return Usuario.objects.get(username="vendedor")


def mes_de(tienda):
    hoy = tienda.entorno.hoy
    return hoy.year, hoy.month


def escala(tienda, tramos=(("0", "2"), ("1000", "4"), ("2000", "5")), **extra):
    return escalas.crear_escala(
        org(tienda).pk,
        {
            "nombre": "Mensual",
            "tramos": [{"desde": d, "porcentaje": p} for d, p in tramos],
            **extra,
        },
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


def ganado_total():
    return sum((m.monto for m in MovimientoComision.objects.sin_ambito().all()), D("0"))


class TestEscalaValida:
    def test_crea_con_sus_tramos_en_orden(self, tienda):
        e = escala(tienda, tramos=(("2000", "5"), ("0", "2"), ("1000", "4")))
        assert [(str(t.desde), str(t.porcentaje)) for t in e.tramos.all()] == [
            ("0.00", "2.00"),
            ("1000.00", "4.00"),
            ("2000.00", "5.00"),
        ]

    @pytest.mark.parametrize(
        ("tramos", "texto"),
        [
            ([], "al menos un tramo"),
            ([("100", "2")], "empezar en 0"),
            ([("0", "2"), ("0", "3")], "mismo monto"),
            ([("0", "120")], "entre 0 y 100"),
            ([("0", "2"), ("x", "3")], "número"),
            ([(str(i * 10), "1") for i in range(11)], "hasta 10"),
        ],
    )
    def test_rechaza_tramos_mal_hechos(self, tienda, tramos, texto):
        with pytest.raises(ReglaInvalida, match=texto):
            escala(tienda, tramos=tramos)

    def test_no_dos_escalas_activas_para_el_mismo_vendedor_y_fechas(self, tienda):
        escala(tienda)
        with pytest.raises(ReglaInvalida, match="una escala activa"):
            escala(tienda)
        escala(tienda, vendedor_id=str(ana().pk))  # otro vendedor: vale

    def test_cambiar_los_tramos_los_reemplaza_y_queda_en_la_auditoria(self, tienda):
        from apps.auditoria.models import AuditoriaEvento

        e = escala(tienda)
        escalas.actualizar_escala(e, {"tramos": [{"desde": "0", "porcentaje": "3"}]})
        assert e.tramos.count() == 1 and e.tramos.get().porcentaje == D("3.00")
        assert AuditoriaEvento.objects.filter(accion="comisiones.escala_editada").exists()
        escalas.eliminar_escala(e)
        assert not EscalaComision.objects.sin_ambito().exists()


class TestMetaValida:
    def meta(self, tienda, **extra):
        datos = {"nombre": "Meta de 1000", "meta": "1000", "bono": "100", **extra}
        return escalas.crear_meta(org(tienda).pk, datos)

    @pytest.mark.parametrize("campo", ["meta", "bono"])
    def test_meta_y_bono_deben_ser_positivos(self, tienda, campo):
        with pytest.raises(ReglaInvalida):
            self.meta(tienda, **{campo: "0"})
        with pytest.raises(ReglaInvalida):
            self.meta(tienda, **{campo: "abc"})

    def test_una_meta_que_ya_otorgo_bonos_no_se_elimina_solo_se_pausa(self, tienda):
        m = self.meta(tienda)
        BonoGanado.objects.sin_ambito().create(
            organizacion_id=org(tienda).pk,
            vendedor_id=ana().pk,
            periodo="2026-10",
            meta=m,
            nombre=m.nombre,
            ventas_mes=D("1200"),
            monto=D("100"),
            fecha=tienda.entorno.hoy,
        )
        with pytest.raises(ReglaInvalida, match="ya otorgó"):
            escalas.eliminar_meta(m)
        escalas.actualizar_meta(m, {"activa": False})


class TestAvance:
    def test_cuenta_lo_vendido_en_el_mes_sin_igv_menos_lo_devuelto(self, tienda):
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        v1 = vender(tienda, p, 6)
        vender(tienda, p, 4)
        año, mes = mes_de(tienda)
        servicios.crear(org(tienda).pk, {"alcance": "GENERAL", "porcentaje": "2"})
        # Las ventas ya existían sin plan (no había regla al crear): ahora sí hay planes nuevos.
        assert avance.ventas_netas_del_mes(org(tienda).pk, ana().pk, año, mes) == D("1000.00")
        comp = v1.comprobantes.get()
        notas_credito.crear_nota_credito(
            comp,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(comp.lineas.get(), D("1"))],
            reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
        )
        assert avance.ventas_netas_del_mes(org(tienda).pk, ana().pk, año, mes) == D("900.00")
        assert avance.ventas_netas_del_mes(org(tienda).pk, ana().pk, año, mes - 1 or 12) == 0

    def test_dice_el_tramo_lo_que_falta_y_las_metas(self, tienda):
        escala(tienda)
        escalas.crear_meta(org(tienda).pk, {"nombre": "Meta 1500", "meta": "1500", "bono": "200"})
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        vender(tienda, p, 6)
        vender(tienda, p, 5)  # 1100 vendidos
        año, mes = mes_de(tienda)
        a = avance.avance(org(tienda).pk, ana().pk, año, mes)
        assert a["ventas"] == "1100.00"
        assert a["escala"]["porcentaje"] == "4.00"
        assert a["escala"]["siguiente"] == {
            "desde": "2000.00",
            "porcentaje": "5.00",
            "falta": "900.00",
        }
        (meta,) = a["metas"]
        assert (meta["cumplida"], meta["falta"], meta["otorgado"]) == (False, "400.00", False)


class TestAplicarEscala:
    def escenario(self, tienda):
        """Regla general 2 %, una regla fija del 10 % para Cable, y 1 000 vendidos en el mes."""
        servicios.crear(org(tienda).pk, {"alcance": "GENERAL", "porcentaje": "2"})
        cable = tienda.producto("Cable", precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        mouse = tienda.producto("Mouse", precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        servicios.crear(
            org(tienda).pk, {"alcance": "PRODUCTO", "porcentaje": "10", "producto": cable.pk}
        )
        vender(tienda, cable, 2)  # 200 al 10 % fijo = 20,00
        vender(tienda, mouse, 8)  # 800 generales al 2 % = 16,00
        return cable, mouse

    def test_el_tramo_alcanzado_sube_todo_lo_general_y_no_toca_lo_fijo(self, tienda):
        self.escenario(tienda)
        assert ganado_total() == D("36.00")
        escala(tienda)  # 0→2 %, 1 000→4 % (se vendió 1 000)
        año, mes = mes_de(tienda)
        assert avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes) == 1  # solo Mouse
        # Cable sigue en 20,00; Mouse pasa de 2 % a 4 % sobre 800 = 32,00.
        assert ganado_total() == D("52.00")
        planes = {
            p.detalle[0]["producto"]: p for p in ComisionComprobante.objects.sin_ambito().all()
        }
        assert planes["Cable"].comision_total == D("20.00") and planes["Cable"].escala_pct is None
        assert planes["Mouse"].comision_total == D("32.00") and planes["Mouse"].escala_pct == D("4")

    def test_aplicar_dos_veces_no_duplica(self, tienda):
        self.escenario(tienda)
        escala(tienda)
        año, mes = mes_de(tienda)
        avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes)
        antes = MovimientoComision.objects.sin_ambito().count()
        assert avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes) == 0
        assert MovimientoComision.objects.sin_ambito().count() == antes

    def test_si_la_escala_ya_no_rige_vuelve_al_porcentaje_de_la_regla(self, tienda):
        self.escenario(tienda)
        e = escala(tienda)
        año, mes = mes_de(tienda)
        avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes)
        escalas.actualizar_escala(e, {"activa": False})
        avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes)
        assert ganado_total() == D("36.00")

    def test_la_fecha_de_los_ajustes_es_la_que_se_indica(self, tienda):
        self.escenario(tienda)
        escala(tienda)
        año, mes = mes_de(tienda)
        fin = avance.rango_del_mes(año, mes)[1]
        avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes)
        ajustes = MovimientoComision.objects.sin_ambito().filter(monto__gt=0).order_by("-id")[:1]
        assert ajustes[0].fecha == fin

    def test_un_comprobante_a_credito_gana_el_nuevo_porcentaje_a_medida_que_se_cobra(self, tienda):
        servicios.crear(org(tienda).pk, {"alcance": "GENERAL", "porcentaje": "2"})
        p = tienda.producto(precios={"PUBLICO": "100", "CREDITO": "120"}, stock={tienda.a: 20})
        venta = tienda.credito(
            [tienda.linea(p, 9)], cliente=tienda.cliente("5000"), vendedor_id=ana().pk
        )
        comp = venta.comprobantes.get()
        escala(tienda, tramos=(("0", "2"), ("500", "10")))
        año, mes = mes_de(tienda)
        avance.aplicar_escala_del_mes(org(tienda).pk, ana().pk, año, mes)
        plan = ComisionComprobante.objects.sin_ambito().get(comprobante=comp)
        assert plan.escala_pct == D("10") and calculo.ganado_por(comp) == 0  # nada cobrado
        cuentas_por_cobrar.registrar_abonos(
            comp, abonos=[tienda.cobro(tienda.efectivo, str(comp.total))]
        )
        assert calculo.ganado_por(comp) == plan.comision_total  # todo cobrado, al 10 %
        assert plan.comision_total == (plan.base_neta * D("0.10")).quantize(D("0.01"))


class TestBonos:
    def test_otorga_el_bono_de_las_metas_cumplidas_una_sola_vez(self, tienda):
        escalas.crear_meta(org(tienda).pk, {"nombre": "Meta 1000", "meta": "1000", "bono": "100"})
        escalas.crear_meta(org(tienda).pk, {"nombre": "Meta 5000", "meta": "5000", "bono": "500"})
        servicios.crear(org(tienda).pk, {"alcance": "GENERAL", "porcentaje": "2"})
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        vender(tienda, p, 10)  # 1 000 vendidos
        año, mes = mes_de(tienda)
        nuevos = avance.otorgar_bonos_del_mes(org(tienda).pk, ana().pk, año, mes)
        assert [(b.nombre, b.monto) for b in nuevos] == [("Meta 1000", D("100.00"))]
        assert avance.otorgar_bonos_del_mes(org(tienda).pk, ana().pk, año, mes) == []
        assert BonoGanado.objects.sin_ambito().count() == 1
        a = avance.avance(org(tienda).pk, ana().pk, año, mes)
        assert [(m["nombre"], m["otorgado"]) for m in a["metas"]] == [
            ("Meta 1000", True),
            ("Meta 5000", False),
        ]

    def test_una_meta_de_otro_vendedor_no_le_toca(self, tienda):
        otro = Usuario.objects.get(username="cajero")
        escalas.crear_meta(
            org(tienda).pk,
            {"nombre": "Solo cajero", "meta": "100", "bono": "50", "vendedor_id": str(otro.pk)},
        )
        servicios.crear(org(tienda).pk, {"alcance": "GENERAL", "porcentaje": "2"})
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        vender(tienda, p, 5)
        año, mes = mes_de(tienda)
        assert avance.otorgar_bonos_del_mes(org(tienda).pk, ana().pk, año, mes) == []


class TestApi:
    def test_el_administrador_maneja_escalas_y_metas_y_el_vendedor_no(self, tienda):
        admin, vend = cliente_de("admin"), cliente_de("vendedor")
        cuerpo = {
            "nombre": "Mensual",
            "tramos": [{"desde": "0", "porcentaje": "2"}, {"desde": "1000", "porcentaje": "4"}],
        }
        r = admin.post(f"{BASE}/escalas/", cuerpo, format="json")
        assert r.status_code == 201, r.content
        pk = r.json()["id"]
        assert [t["porcentaje"] for t in r.json()["tramos"]] == ["2.00", "4.00"]
        assert vend.get(f"{BASE}/escalas/").status_code == 403
        assert vend.post(f"{BASE}/escalas/", cuerpo, format="json").status_code == 403
        r = admin.patch(f"{BASE}/escalas/{pk}/", {"activa": False}, format="json")
        assert r.status_code == 200 and r.json()["activa"] is False
        assert admin.delete(f"{BASE}/escalas/{pk}/").status_code == 204
        r = admin.post(
            f"{BASE}/metas/", {"nombre": "Meta", "meta": "1000", "bono": "100"}, format="json"
        )
        assert r.status_code == 201, r.content
        assert admin.get(f"{BASE}/metas/").json()["results"][0]["bono"] == "100.00"

    def test_una_escala_mal_hecha_responde_400(self, tienda):
        r = cliente_de("admin").post(
            f"{BASE}/escalas/",
            {"nombre": "X", "tramos": [{"desde": "50", "porcentaje": "2"}]},
            format="json",
        )
        assert r.status_code == 400

    def test_el_avance_lista_a_los_vendedores(self, tienda):
        p = tienda.producto(precios={"PUBLICO": "100"}, stock={tienda.a: 20})
        servicios.crear(org(tienda).pk, {"alcance": "GENERAL", "porcentaje": "2"})
        vender(tienda, p, 3)
        año, mes = mes_de(tienda)
        r = cliente_de("admin").get(f"{BASE}/avance/", {"mes": f"{año}-{mes:02d}"})
        assert r.status_code == 200, r.content
        filas = {f["vendedor_nombre"]: f for f in r.json()["results"]}
        assert filas["vendedor"]["ventas"] == "300.00"

    def test_el_mes_debe_tener_formato(self, tienda):
        assert cliente_de("admin").get(f"{BASE}/avance/", {"mes": "noviembre"}).status_code == 400
