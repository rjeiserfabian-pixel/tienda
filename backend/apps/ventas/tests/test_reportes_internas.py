"""Reportes de la venta interna: lo que pasó entre las empresas y el consolidado sin duplicar."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import liquidacion_interna, notas_credito, reportes, reportes_internas
from apps.ventas.servicios import anular_venta

from .test_venta_interna import vender_interna

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas/reportes"


def rango(tienda):
    return tienda.entorno.hoy - timedelta(days=1), tienda.entorno.hoy


def hacer(tienda, mixto, *, facturar_por=None):
    de_a, de_b = mixto
    return vender_interna(
        tienda,
        [tienda.linea(de_a, 1), tienda.linea(de_b, 2, empresa=tienda.b)],
        [tienda.cobro(tienda.efectivo, "354.00")],
        facturar_por=facturar_por or tienda.a,
    )


def informe(tienda, empresa, **extra):
    desde, hasta = rango(tienda)
    return reportes_internas.ventas_internas(empresa, desde, hasta, **extra)


def devolver_uno(tienda, venta, producto):
    comprobante = venta.comprobantes.get()
    return notas_credito.crear_nota_credito(
        comprobante,
        motivo="07",
        devueltas=[notas_credito.LineaDevuelta(comprobante.lineas.get(producto=producto), D("1"))],
        reembolsos=[tienda.cobro(tienda.efectivo, "118.00")],
    )


class TestVentasInternas:
    def test_cada_empresa_ve_lo_suyo_desde_su_lado(self, tienda, mixto):
        hacer(tienda, mixto)

        de_a = informe(tienda, tienda.a, con_utilidad=True)
        de_b = informe(tienda, tienda.b, con_utilidad=True)

        # A facturó: recibió mercadería. B la entregó.
        assert (
            de_a["totales"]["recibido"]["cantidad"],
            de_a["totales"]["entregado"]["cantidad"],
        ) == (1, 0)
        assert de_a["totales"]["recibido"]["costo"] == D("60.00")
        assert (
            de_b["totales"]["entregado"]["cantidad"],
            de_b["totales"]["recibido"]["cantidad"],
        ) == (1, 0)
        (fila,) = de_a["filas"]
        assert (
            fila["rol"] == "RECIBE"
            and informe(tienda, tienda.b, con_utilidad=True)["filas"][0]["rol"] == "ENTREGA"
        )
        assert fila["numero"] == "000001" and fila["comprobante"] == "N001-00000001"
        assert fila["documento"] == "Documento interno"
        assert (fila["devolucion"], fila["liquidacion"]) == ("NINGUNA", "Pendiente")
        assert (fila["costo"], fila["devuelto"]) == (D("60.00"), D("0"))

    def test_cuanto_se_vendio_con_mercaderia_de_la_otra_empresa_y_su_utilidad(self, tienda, mixto):
        hacer(tienda, mixto)

        ajena = informe(tienda, tienda.a, con_utilidad=True)["con_mercaderia_de_la_otra"]

        # 2 cargadores a 100 sin IGV; costaron 30 cada uno: toda la utilidad queda en quien facturó.
        assert (ajena["lineas"], ajena["vendido"], ajena["costo"], ajena["utilidad"]) == (
            1,
            D("200.00"),
            D("60.00"),
            D("140.00"),
        )
        assert (
            informe(tienda, tienda.b, con_utilidad=True)["con_mercaderia_de_la_otra"]["lineas"] == 0
        )

    def test_una_devolucion_resta_y_se_ve_cuanto_volvio(self, tienda, mixto):
        _, de_b = mixto
        venta = hacer(tienda, mixto)
        devolver_uno(tienda, venta, de_b)

        datos = informe(tienda, tienda.a, con_utilidad=True)

        (fila,) = datos["filas"]
        assert (fila["devolucion"], fila["devuelto"]) == ("PARCIAL", D("30.00"))
        assert datos["totales"]["recibido"]["neto"] == D("30.00")
        ajena = datos["con_mercaderia_de_la_otra"]
        assert (ajena["devuelto"], ajena["neto"], ajena["costo"], ajena["utilidad"]) == (
            D("100.00"),
            D("100.00"),
            D("30.00"),
            D("70.00"),
        )

    def test_dice_si_ya_se_liquido_y_en_cual(self, tienda, mixto):
        hacer(tienda, mixto)
        liquidacion_interna.liquidar(pagadora=tienda.a, receptora=tienda.b, local="")

        assert (
            informe(tienda, tienda.a, con_utilidad=True)["filas"][0]["liquidacion"]
            == "Liquidada N° 000001"
        )
        assert informe(tienda, tienda.a, con_utilidad=True)["por_liquidar"] == []

    def test_lo_pendiente_se_ve_con_su_monto(self, tienda, mixto):
        hacer(tienda, mixto)

        (pendiente,) = informe(tienda, tienda.a, con_utilidad=True)["por_liquidar"]

        assert pendiente["monto"] == D("60.00")

    def test_las_anuladas_van_aparte_y_no_suman(self, tienda, mixto):
        venta = hacer(tienda, mixto)
        anular_venta(venta, motivo="Error")

        datos = informe(tienda, tienda.a, con_utilidad=True)

        assert datos["totales"]["recibido"]["cantidad"] == 0
        assert (
            datos["totales"]["anuladas"]["cantidad"],
            datos["totales"]["anuladas"]["costo"],
        ) == (1, D("60.00"))
        assert datos["filas"][0]["estado"] == "ANULADO" and datos["filas"][0]["liquidacion"] == ""
        assert datos["con_mercaderia_de_la_otra"]["lineas"] == 0

    def test_sin_permiso_de_costos_no_salen_importes(self, tienda, mixto):
        hacer(tienda, mixto)

        datos = informe(tienda, tienda.a, con_utilidad=False)

        assert datos["totales"]["recibido"] == {"cantidad": 1}
        assert "costo" not in datos["filas"][0] and "por_liquidar" not in datos
        ajena = datos["con_mercaderia_de_la_otra"]
        assert "costo" not in ajena and "utilidad" not in ajena and ajena["vendido"] == D("200.00")

    def test_el_excel_se_genera(self, tienda, mixto):
        hacer(tienda, mixto)
        for con in (True, False):
            contenido = reportes_internas.ventas_internas_excel(
                tienda.a, informe(tienda, tienda.a, con_utilidad=con, limite=None)
            )
            assert contenido[:2] == b"PK"  # un .xlsx es un zip


class TestConsolidado:
    def test_suma_lo_vendido_a_clientes_de_las_dos_y_no_la_venta_interna(self, tienda, mixto):
        hacer(tienda, mixto)  # A vende 354 al cliente; B le pasó 60 de costo
        tienda.vender(  # B vende por su cuenta 118 a otro cliente
            [tienda.linea(mixto[1], 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        desde, hasta = rango(tienda)

        datos = reportes_internas.consolidado(tienda.a, desde, hasta, con_utilidad=True)

        por_nombre = {e["empresa"]: e["totales"][0] for e in datos["empresas"]}
        assert por_nombre[tienda.a.pk]["neto"] == D("354.00")
        assert por_nombre[tienda.b.pk]["neto"] == D("118.00")
        (total,) = datos["totales"]
        assert (total["moneda"], total["cantidad"], total["neto"]) == ("PEN", 2, D("472.00"))
        # La venta interna no suma: solo se informa aparte.
        assert datos["ventas_internas"] == {"cantidad": 1, "costo": D("60.00")}

    def test_la_utilidad_del_total_es_la_de_las_dos_juntas(self, tienda, mixto):
        hacer(tienda, mixto)
        desde, hasta = rango(tienda)

        datos = reportes_internas.consolidado(tienda.a, desde, hasta, con_utilidad=True)
        de_a = reportes.resumen(tienda.a, desde, hasta, con_utilidad=True)["totales"][0]

        (total,) = datos["totales"]
        # Todo el margen queda en A (la que facturó); B no gana nada en el traslado, al costo.
        assert total["utilidad"] == de_a["utilidad"] == D("190.00")  # 50 + 140

    def test_sin_permiso_de_costos_no_hay_costo_ni_utilidad(self, tienda, mixto):
        hacer(tienda, mixto)
        desde, hasta = rango(tienda)

        datos = reportes_internas.consolidado(tienda.a, desde, hasta)

        assert "utilidad" not in datos["totales"][0] and datos["ventas_internas"] == {"cantidad": 1}

    def test_el_excel_se_genera(self, tienda, mixto):
        hacer(tienda, mixto)
        desde, hasta = rango(tienda)
        for con in (True, False):
            datos = reportes_internas.consolidado(tienda.a, desde, hasta, con_utilidad=con)
            assert reportes_internas.consolidado_excel(tienda.a, datos)[:2] == b"PK"


class TestApi:
    def parametros(self, tienda):
        desde, hasta = rango(tienda)
        return {"empresa": tienda.a.pk, "desde": str(desde), "hasta": str(hasta)}

    def test_ventas_internas_por_la_api(self, tienda, mixto, nuevo_usuario):
        nuevo_usuario(tienda.a.organizacion, "dueno", [tienda.a, tienda.b], [("SUPERADMIN", None)])
        hacer(tienda, mixto)

        r = cliente_de("dueno").get(f"{BASE}/ventas-internas/", self.parametros(tienda))

        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["con_utilidad"] is True and datos["total_filas"] == 1
        assert datos["con_mercaderia_de_la_otra"]["utilidad"] == "140.00"

    def test_quien_no_ve_costos_recibe_el_informe_sin_importes(self, tienda, mixto):
        hacer(tienda, mixto)

        r = cliente_de("vendedor").get(f"{BASE}/ventas-internas/", self.parametros(tienda))

        assert r.status_code == 200, r.content
        assert r.json()["con_utilidad"] is False
        assert "costo" not in r.json()["filas"][0]

    def test_el_consolidado_pide_el_permiso_de_las_dos_empresas(self, tienda, mixto, nuevo_usuario):
        nuevo_usuario(tienda.a.organizacion, "dueno", [tienda.a, tienda.b], [("SUPERADMIN", None)])
        nuevo_usuario(
            tienda.a.organizacion, "jefe_de_a", [tienda.a, tienda.b], [("SUPERADMIN", tienda.a)]
        )
        hacer(tienda, mixto)
        parametros = self.parametros(tienda)

        ok = cliente_de("dueno").get(f"{BASE}/consolidado/", parametros)
        assert ok.status_code == 200, ok.content
        assert [e["nombre"] for e in ok.json()["empresas"]] and ok.json()["ventas_internas"][
            "cantidad"
        ] == 1
        for usuario in ("vendedor", "jefe_de_a"):
            assert cliente_de(usuario).get(f"{BASE}/consolidado/", parametros).status_code == 403

    def test_los_excel_se_descargan(self, tienda, mixto, nuevo_usuario):
        nuevo_usuario(tienda.a.organizacion, "dueno", [tienda.a, tienda.b], [("SUPERADMIN", None)])
        hacer(tienda, mixto)

        for ruta in ("ventas-internas", "consolidado"):
            r = cliente_de("dueno").get(f"{BASE}/{ruta}/excel/", self.parametros(tienda))
            assert r.status_code == 200, (ruta, r.content)
            assert "spreadsheetml" in r["Content-Type"]
