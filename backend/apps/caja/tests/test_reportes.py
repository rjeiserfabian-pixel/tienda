"""Reportes de caja y bancos: saldos a fecha, libro, flujo, conceptos, PLE y Excel."""

import io
from datetime import date, timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.caja import ple, reportes, servicios, transferencias
from apps.caja.exceptions import MovimientoInvalido
from apps.compras.servicios import CuotasEntrada, LineaEntrada
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec

pytestmark = pytest.mark.django_db

HOY = timezone.localdate()


def mes_atras(n: int, dia: int = 15) -> date:
    indice = HOY.year * 12 + (HOY.month - 1) - n
    return date(indice // 12, indice % 12 + 1, dia)


@pytest.fixture
def escena(nuevo_usuario, compras, conceptos):
    e = compras.entorno
    nuevo_usuario(e.e.org_a, "reportero", [e.e1])
    establecer_contexto(e.e.org_a.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.e1,
        nombre="BCP soles",
        tipo="BANCO",
        moneda="PEN",
        banco="BCP",
        numero_cuenta="1931234567",
        codigo_entidad="02",
    )
    compras.caja.cuenta_contable = "101"
    compras.caja.save()
    return type(
        "Escena",
        (),
        {
            "compras": compras,
            "empresa": e.e1,
            "caja": compras.caja,
            "caja_usd": compras.caja_usd,
            "banco": banco,
            "conceptos": conceptos,
        },
    )


def mover(escena, cuenta, tipo, monto, fecha, codigo=None, **extra):
    codigo = codigo or ("DEPOSITO_RECIBIDO" if tipo == "INGRESO" else "GASTOS_VARIOS")
    return servicios.registrar_movimiento(
        empresa=escena.empresa,
        cuenta=cuenta,
        tipo=tipo,
        monto=dec(monto),
        concepto=escena.conceptos[codigo],
        fecha=fecha,
        **extra,
    )


class TestSaldosAFecha:
    def test_saldo_de_cada_cuenta_en_la_fecha(self, escena):
        mover(escena, escena.caja, "INGRESO", "1000", mes_atras(2))
        mover(escena, escena.caja, "EGRESO", "300", mes_atras(1))
        mover(escena, escena.caja_usd, "INGRESO", "50", mes_atras(1))
        al_cierre = reportes.saldos_a_fecha(escena.empresa, mes_atras(2, 28))
        por_nombre = {c["nombre"]: c["saldo"] for c in al_cierre["cuentas"]}
        assert por_nombre["Caja soles"] == dec("1000")
        assert por_nombre["Caja dólares"] == dec("0")
        hoy = reportes.saldos_a_fecha(escena.empresa, HOY)
        assert {t["moneda"]: t["saldo"] for t in hoy["totales"]} == {
            "PEN": dec("700"),
            "USD": dec("50"),
        }

    def test_lo_anulado_no_cuenta(self, escena):
        m = mover(escena, escena.caja, "INGRESO", "100", mes_atras(1))
        servicios.anular_movimiento(m, motivo="Error")
        assert reportes.saldos_a_fecha(escena.empresa, HOY)["totales"][0]["saldo"] == dec("0")

    def test_el_saldo_inicial_cuenta_desde_su_fecha(self, escena):
        escena.banco.saldo_inicial = dec("500")
        escena.banco.fecha_saldo_inicial = mes_atras(1)
        escena.banco.save()
        antes = reportes.saldos_a_fecha(escena.empresa, mes_atras(2))
        despues = reportes.saldos_a_fecha(escena.empresa, HOY)
        assert {c["nombre"]: c["saldo"] for c in antes["cuentas"]}["BCP soles"] == dec("0")
        assert {c["nombre"]: c["saldo"] for c in despues["cuentas"]}["BCP soles"] == dec("500")


class TestLibro:
    def test_separa_efectivo_y_bancos_con_saldo_corrido(self, escena):
        mover(escena, escena.caja, "INGRESO", "1000", mes_atras(2))  # mes anterior al libro
        mover(escena, escena.caja, "EGRESO", "200", mes_atras(1, 5))
        mover(escena, escena.caja, "INGRESO", "50", mes_atras(1, 20))
        mover(escena, escena.banco, "INGRESO", "300", mes_atras(1, 10), referencia="OP1")
        x = mes_atras(1)
        libro = reportes.libro(escena.empresa, x.year, x.month)
        efectivo = {s["nombre"]: s for s in libro["efectivo"]}["Caja soles"]
        assert efectivo["saldo_inicial"] == dec("1000")
        assert [(m["debe"], m["haber"], m["saldo"]) for m in efectivo["lineas"]] == [
            (dec("0"), dec("200"), dec("800")),
            (dec("50"), dec("0"), dec("850")),
        ]
        assert (efectivo["total_debe"], efectivo["total_haber"], efectivo["saldo_final"]) == (
            dec("50"), dec("200"), dec("850"),
        )  # fmt: skip
        [banco] = libro["bancos"]
        assert (banco["nombre"], banco["saldo_inicial"], banco["saldo_final"]) == (
            "BCP soles", dec("0"), dec("300"),
        )  # fmt: skip
        assert banco["lineas"][0]["referencia"] == "OP1"

    def test_un_saldo_inicial_del_mes_es_la_primera_linea(self, escena):
        x = mes_atras(1)
        escena.banco.saldo_inicial = dec("400")
        escena.banco.fecha_saldo_inicial = date(x.year, x.month, 1)
        escena.banco.save()
        mover(escena, escena.banco, "EGRESO", "100", date(x.year, x.month, 9))
        [banco] = reportes.libro(escena.empresa, x.year, x.month)["bancos"]
        assert banco["saldo_inicial"] == dec("0")
        assert [(m["concepto"], m["saldo"]) for m in banco["lineas"]] == [
            ("Saldo inicial", dec("400")),
            ("Gastos varios", dec("300")),
        ]

    def test_lo_anulado_no_sale_en_el_libro(self, escena):
        m = mover(escena, escena.caja, "INGRESO", "100", mes_atras(1))
        servicios.anular_movimiento(m, motivo="Error")
        x = mes_atras(1)
        libro = reportes.libro(escena.empresa, x.year, x.month)
        assert all(not s["lineas"] for s in libro["efectivo"])

    def test_periodo_invalido(self, escena):
        with pytest.raises(MovimientoInvalido):
            reportes.libro(escena.empresa, 2026, 13)


class TestFlujo:
    def test_agrupa_por_mes_y_moneda_sin_los_pasos_internos(self, escena):
        mover(escena, escena.caja, "INGRESO", "1000", mes_atras(2))
        mover(escena, escena.caja, "EGRESO", "100", mes_atras(1, 3))
        mover(escena, escena.caja_usd, "INGRESO", "20", mes_atras(1, 4))
        transferencias.registrar_transferencia(
            empresa=escena.empresa,
            cuenta_origen=escena.caja,
            cuenta_destino=escena.banco,
            monto=dec("400"),
            fecha=mes_atras(1, 6),
        )
        datos = reportes.flujo_real(escena.empresa, mes_atras(2, 1), HOY)
        por_clave = {(f["periodo"], f["moneda"]): f for f in datos["filas"]}
        assert por_clave[(f"{mes_atras(2):%Y-%m}", "PEN")]["neto"] == dec("1000")
        anterior = por_clave[(f"{mes_atras(1):%Y-%m}", "PEN")]
        assert (anterior["ingresos"], anterior["egresos"]) == (dec("0"), dec("100"))
        assert por_clave[(f"{mes_atras(1):%Y-%m}", "USD")]["ingresos"] == dec("20")
        totales = {t["moneda"]: t for t in datos["totales"]}
        assert totales["PEN"]["neto"] == dec("900")
        # El saldo final sí refleja todo: 1000 - 100 en soles (400 solo cambió de cuenta).
        assert {s["moneda"]: s["saldo"] for s in datos["saldo_final"]}["PEN"] == dec("900")

    def test_por_dia(self, escena):
        mover(escena, escena.caja, "INGRESO", "10", mes_atras(1, 3))
        mover(escena, escena.caja, "INGRESO", "20", mes_atras(1, 4))
        datos = reportes.flujo_real(escena.empresa, mes_atras(1, 1), mes_atras(1, 28), "dia")
        assert [f["periodo"] for f in datos["filas"]] == [
            mes_atras(1, 3).isoformat(), mes_atras(1, 4).isoformat(),
        ]  # fmt: skip

    def test_valida_el_rango(self, escena):
        with pytest.raises(MovimientoInvalido):
            reportes.flujo_real(escena.empresa, HOY, HOY - timedelta(days=1))
        with pytest.raises(MovimientoInvalido):
            reportes.flujo_real(escena.empresa, HOY - timedelta(days=800), HOY)
        with pytest.raises(MovimientoInvalido):
            reportes.flujo_real(escena.empresa, None, HOY)

    def test_la_proyeccion_resta_lo_que_se_debe(self, escena):
        c = escena.compras
        mover(escena, escena.caja, "INGRESO", "1000", mes_atras(1))
        linea = LineaEntrada(c.entorno.producto(), dec(1), dec(100))
        c.comprar([linea], forma_pago="CREDITO", cuotas=CuotasEntrada(2, c.entorno.hoy, c.mensual))
        datos = reportes.flujo_proyectado(escena.empresa, HOY, 3)
        assert {s["moneda"]: s["saldo"] for s in datos["saldo_hoy"]}["PEN"] == dec("1000")
        assert sum(f["por_pagar"] for f in datos["filas"]) == dec("118")
        assert datos["filas"][-1]["saldo_proyectado"] == dec("882")

    def test_la_proyeccion_valida_los_meses(self, escena):
        with pytest.raises(MovimientoInvalido):
            reportes.flujo_proyectado(escena.empresa, HOY, 0)


class TestPorConcepto:
    def test_totales_por_concepto_sin_pasos_internos(self, escena):
        mover(escena, escena.caja, "EGRESO", "30", mes_atras(1, 2), codigo="GASTOS_VARIOS")
        mover(escena, escena.caja, "EGRESO", "20", mes_atras(1, 3), codigo="GASTOS_VARIOS")
        mover(escena, escena.banco, "INGRESO", "90", mes_atras(1, 4), codigo="INTERESES")
        transferencias.registrar_transferencia(
            empresa=escena.empresa,
            cuenta_origen=escena.caja,
            cuenta_destino=escena.banco,
            monto=dec("5"),
            fecha=mes_atras(1, 6),
        )
        datos = reportes.por_concepto(escena.empresa, mes_atras(1, 1), mes_atras(1, 28))
        por_concepto = {f["concepto"]: f["total"] for f in datos["filas"]}
        assert por_concepto == {"Gastos varios": dec("50"), "Intereses ganados": dec("90")}
        assert {(t["tipo"], t["total"]) for t in datos["totales"]} == {
            ("EGRESO", dec("50")), ("INGRESO", dec("90")),
        }  # fmt: skip


class TestPle:
    def libro(self, escena):
        x = mes_atras(1)
        return x, reportes.libro(escena.empresa, x.year, x.month)

    def test_formato_1_1_trae_19_campos(self, escena):
        mover(escena, escena.caja, "INGRESO", "1000.50", mes_atras(1, 5), glosa="Venta | del día")
        x, datos = self.libro(escena)
        r = ple.generar(escena.empresa, datos, "1.1")
        [linea] = r["contenido"].split("\r\n")[:-1]
        campos = linea.split("|")
        assert len(campos) == 20 and campos[-1] == ""  # 19 campos y el cierre
        assert campos[0] == f"{x.year}{x.month:02d}00"
        assert campos[3] == "101"
        assert campos[6] == "PEN"
        assert campos[15:17] == ["1000.50", "0.00"]
        assert campos[13] == "Depósito recibido Venta del día"
        assert r["nombre"] == f"LE{escena.empresa.ruc}{x.year}{x.month:02d}00010100001111.TXT"

    def test_formato_1_2_trae_15_campos(self, escena):
        mover(escena, escena.banco, "EGRESO", "40", mes_atras(1, 5), referencia="OP-7")
        x, datos = self.libro(escena)
        r = ple.generar(escena.empresa, datos, "1.2")
        campos = r["contenido"].split("\r\n")[0].split("|")
        assert len(campos) == 16 and campos[-1] == ""
        assert campos[3:5] == ["02", "1931234567"]
        assert campos[11] == "OP-7"
        assert campos[12:14] == ["0.00", "40.00"]
        assert r["nombre"].endswith("010200001111.TXT")

    def test_pide_los_datos_que_faltan(self, escena):
        escena.caja.cuenta_contable = ""
        escena.caja.save()
        mover(escena, escena.caja, "INGRESO", "10", mes_atras(1))
        _, datos = self.libro(escena)
        with pytest.raises(MovimientoInvalido, match="falta la cuenta contable"):
            ple.generar(escena.empresa, datos, "1.1")

    def test_las_cuentas_en_dolares_no_se_incluyen(self, escena):
        mover(escena, escena.caja, "INGRESO", "10", mes_atras(1))
        mover(escena, escena.caja_usd, "INGRESO", "10", mes_atras(1))
        _, datos = self.libro(escena)
        r = ple.generar(escena.empresa, datos, "1.1")
        assert r["lineas"] == 1
        assert any("dólares" in a for a in r["avisos"])

    def test_sin_movimientos_el_indicador_es_cero(self, escena):
        _, datos = self.libro(escena)
        r = ple.generar(escena.empresa, datos, "1.1")
        assert r["lineas"] == 0 and r["contenido"] == ""
        assert r["nombre"].endswith("010100001011.TXT")  # el indicador de contenido va en 0

    def test_formato_desconocido(self, escena):
        _, datos = self.libro(escena)
        with pytest.raises(MovimientoInvalido):
            ple.generar(escena.empresa, datos, "9.9")


class TestExcel:
    def test_libro_en_dos_hojas_y_los_textos_no_son_formulas(self, escena):
        mover(escena, escena.caja, "INGRESO", "100", mes_atras(1), glosa="=1+1")
        mover(escena, escena.banco, "EGRESO", "30", mes_atras(1))
        x = mes_atras(1)
        datos = reportes.libro(escena.empresa, x.year, x.month)
        libro = load_workbook(io.BytesIO(reportes.libro_excel(escena.empresa, datos)))
        assert libro.sheetnames == ["1.1 Efectivo", "1.2 Bancos"]
        celdas = [c for fila in libro["1.1 Efectivo"].iter_rows() for c in fila if c.value]
        formula = next(c for c in celdas if c.value == "=1+1")
        assert formula.data_type == "s"
        assert any(c.value == escena.empresa.ruc for c in celdas)

    def test_los_demas_reportes_generan_excel(self, escena):
        mover(escena, escena.caja, "INGRESO", "100", mes_atras(1))
        for contenido in (
            reportes.saldos_excel(escena.empresa, reportes.saldos_a_fecha(escena.empresa, HOY)),
            reportes.flujo_excel(
                escena.empresa, reportes.flujo_real(escena.empresa, mes_atras(2), HOY)
            ),
            reportes.conceptos_excel(
                escena.empresa, reportes.por_concepto(escena.empresa, mes_atras(2), HOY)
            ),
        ):
            assert load_workbook(io.BytesIO(contenido)).active.max_row > 6
