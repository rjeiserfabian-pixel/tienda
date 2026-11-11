"""Conciliación bancaria: lectura del extracto, emparejado, partidas, cierre y sus reglas."""

import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.caja import conciliacion, extractos, servicios
from apps.caja.exceptions import ConciliacionInvalida, MovimientoInvalido, MovimientoNoAnulable
from apps.caja.models import EstadoCuenta, LineaEstadoCuenta, MovimientoCaja, Origen
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.importacion import ErrorImportacion
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec

pytestmark = pytest.mark.django_db

HOY = timezone.localdate()


def dia(atras: int):
    return HOY - timedelta(days=atras)


def csv(
    *filas, encabezado="Fecha;Descripción;Nº Operación;Cargo;Abono;Saldo"
) -> SimpleUploadedFile:
    texto = "\n".join([encabezado, *filas]) + "\n"
    return SimpleUploadedFile("extracto.csv", texto.encode("utf-8"), content_type="text/csv")


def f(d):
    return d.strftime("%d/%m/%Y")


@pytest.fixture
def escena(nuevo_usuario, compras, conceptos):
    e = compras.entorno
    usuario = nuevo_usuario(e.e.org_a, "conciliador", [e.e1])
    establecer_contexto(e.e.org_a.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.e1, nombre="BCP soles", tipo="BANCO", moneda="PEN", banco="BCP"
    )
    return type(
        "Escena",
        (),
        {"empresa": e.e1, "banco": banco, "usuario": usuario, "conceptos": conceptos},
    )


def mover(escena, tipo, monto, atras, referencia="", codigo=None):
    codigo = codigo or ("DEPOSITO_RECIBIDO" if tipo == "INGRESO" else "GASTOS_VARIOS")
    return servicios.registrar_movimiento(
        empresa=escena.empresa,
        cuenta=escena.banco,
        tipo=tipo,
        monto=dec(monto),
        concepto=escena.conceptos[codigo],
        fecha=dia(atras),
        referencia=referencia,
    )


def importar(escena, *filas, **extra):
    return conciliacion.importar(
        empresa=escena.empresa,
        cuenta=escena.banco,
        archivo=csv(*filas),
        usuario=escena.usuario,
        **extra,
    )


class TestNumeros:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("1,234.50", "1234.50"),
            ("1.234,50", "1234.50"),
            ("S/ -50.00", "-50.00"),
            ("(50.00)", "-50.00"),
            ("50.00-", "-50.00"),
            ("12,345", "12345"),
            ("1 234,5", "1234.5"),
            ("+7", "7"),
            (50, "50"),
        ],
    )
    def test_formatos_de_importe(self, texto, esperado):
        assert extractos.numero(texto) == dec(esperado)

    @pytest.mark.parametrize("malo", ["", "abc", "1.234567", "99999999999999999"])
    def test_importes_invalidos(self, malo):
        with pytest.raises(ValueError):
            extractos.numero(malo)

    @pytest.mark.parametrize(
        "texto", ["15/10/2026", "15-10-2026", "2026-10-15", "2026-10-15 00:00:00"]
    )
    def test_formatos_de_fecha(self, texto):
        assert str(extractos.fecha(texto)) == "2026-10-15"

    def test_fecha_invalida(self):
        with pytest.raises(ValueError):
            extractos.fecha("ayer")


class TestLeer:
    def test_cargos_y_abonos(self):
        lectura = extractos.leer(
            csv(
                "01/10/2026;Depósito;123;;1,000.00;1,000.00",
                "02/10/2026;Comisión;;5.00;;995.00",
            )
        )
        assert [x.monto for x in lectura.lineas] == [dec("1000"), dec("-5")]
        assert lectura.lineas[0].referencia == "123"
        assert lectura.lineas[1].saldo == dec("995")
        assert lectura.total_errores == 0

    def test_una_sola_columna_de_importe_con_signo(self):
        lectura = extractos.leer(
            csv(
                "01/10/2026;Pago;77;-50.00",
                "02/10/2026;Abono;78;120.50",
                encabezado="Fecha;Detalle;Operación;Importe",
            )
        )
        assert [x.monto for x in lectura.lineas] == [dec("-50"), dec("120.50")]

    def test_salta_las_lineas_de_encabezado_del_banco(self):
        archivo = csv(
            "Cuenta: 193-1234567;;;;;",
            ";;;;;",
            "Fecha;Descripción;Nº Operación;Cargo;Abono;Saldo",
            "01/10/2026;Depósito;1;;10.00;10.00",
            encabezado="ESTADO DE CUENTA BCP;;;;;",
        )
        assert len(extractos.leer(archivo).lineas) == 1

    def test_ignora_las_lineas_sin_importe(self):
        lectura = extractos.leer(
            csv("01/10/2026;Saldo anterior;;;;0.00", "02/10/2026;Pago;1;5.00;;")
        )
        assert len(lectura.lineas) == 1
        assert lectura.ignoradas == 1

    def test_informa_las_filas_con_problemas(self):
        lectura = extractos.leer(
            csv("fecha mala;X;1;;5.00;", "03/10/2026;Y;2;;abc;", "04/10/2026;Z;3;1.00;2.00;")
        )
        assert lectura.total_errores == 3
        assert lectura.errores[0].startswith("Fila 2: Fecha")
        assert "Importe" in lectura.errores[1]
        assert "cargo y abono" in lectura.errores[2]

    def test_sin_tabla_de_extracto(self):
        with pytest.raises(ErrorImportacion, match="No se encontró la tabla"):
            extractos.leer(csv("a;b;c", encabezado="Nombre;Edad;Ciudad"))

    def test_solo_excel_o_csv(self):
        with pytest.raises(ErrorImportacion, match="Excel"):
            extractos.leer(SimpleUploadedFile("extracto.pdf", b"%PDF"))

    def test_excel(self):
        from openpyxl import Workbook

        libro = Workbook()
        hoja = libro.active
        hoja.append(["Movimientos de la cuenta"])
        hoja.append(["Fecha", "Descripción", "Referencia", "Monto"])
        hoja.append([dia(2), "Depósito", 55, 300.5])
        hoja.append([dia(1), "Pago", "A-9", -20])
        salida = io.BytesIO()
        libro.save(salida)
        lectura = extractos.leer(SimpleUploadedFile("e.xlsx", salida.getvalue()))
        assert [x.monto for x in lectura.lineas] == [dec("300.5"), dec("-20")]
        assert lectura.lineas[0].referencia == "55"
        assert lectura.lineas[0].fecha == dia(2)

    def test_dos_lineas_identicas_son_distintas(self):
        lectura = extractos.leer(csv("01/10/2026;ITF;;0.50;;", "01/10/2026;ITF;;0.50;;"))
        assert lectura.lineas[0].huella != lectura.lineas[1].huella


class TestImportar:
    def test_crea_el_estado_con_sus_lineas(self, escena):
        e = importar(
            escena,
            f"{f(dia(5))};Depósito;OP1;;1000.00;1000.00",
            f"{f(dia(2))};Pago;OP2;200.00;;800.00",
            saldo_inicial=dec("0"),
            saldo_final=dec("800"),
        )
        assert (e.numero, e.estado, e.desde, e.hasta) == (1, "ABIERTO", dia(5), dia(2))
        assert e.lineas.count() == 2
        assert e.importado_por_nombre == "conciliador"

    def test_un_extracto_traslapado_solo_trae_lo_nuevo(self, escena):
        importar(escena, f"{f(dia(5))};Depósito;OP1;;100.00;")
        e = importar(escena, f"{f(dia(5))};Depósito;OP1;;100.00;", f"{f(dia(4))};Pago;OP2;30.00;;")
        assert e.lineas.count() == 1
        assert e.lineas.get().referencia == "OP2"
        with pytest.raises(ErrorImportacion, match="ya estaban importadas"):
            importar(escena, f"{f(dia(5))};Depósito;OP1;;100.00;")

    def test_los_saldos_deben_cuadrar_con_las_lineas(self, escena):
        with pytest.raises(ErrorImportacion, match="no cuadran"):
            importar(
                escena,
                f"{f(dia(5))};Depósito;OP1;;100.00;",
                saldo_inicial=dec("0"),
                saldo_final=dec("90"),
            )
        assert not EstadoCuenta.objects.exists()

    def test_si_hay_filas_con_error_no_se_importa_nada(self, escena):
        with pytest.raises(ErrorImportacion, match="filas con problemas"):
            importar(escena, f"{f(dia(5))};Depósito;OP1;;100.00;", "mala;X;;;5;")
        assert not LineaEstadoCuenta.objects.exists()

    def test_una_caja_de_efectivo_no_se_concilia(self, escena):
        caja = CuentaFinanciera.objects.sin_ambito().create(
            empresa=escena.empresa, nombre="Caja", tipo="CAJA", moneda="PEN"
        )
        with pytest.raises(ConciliacionInvalida):
            conciliacion.importar(
                empresa=escena.empresa,
                cuenta=caja,
                archivo=csv(f"{f(dia(1))};X;1;;5.00;"),
                usuario=escena.usuario,
            )

    def test_la_previsualizacion_no_guarda_y_avisa_de_repetidas(self, escena):
        importar(escena, f"{f(dia(5))};Depósito;OP1;;100.00;")
        r = conciliacion.previsualizar(
            empresa=escena.empresa,
            cuenta=escena.banco,
            archivo=csv(f"{f(dia(5))};Depósito;OP1;;100.00;", f"{f(dia(4))};Pago;OP2;30.00;;"),
        )
        assert (r["total"], r["nuevas"], r["repetidas"], r["abonos"], r["cargos"]) == (
            2, 1, 1, dec("0"), dec("30"),
        )  # fmt: skip
        assert EstadoCuenta.objects.count() == 1


class TestAutomatica:
    def test_une_lo_que_tiene_un_solo_candidato(self, escena):
        deposito = mover(escena, "INGRESO", "1000", 5)
        pago = mover(escena, "EGRESO", "200", 3)
        e = importar(
            escena,
            f"{f(dia(4))};Depósito;OP1;;1000.00;",  # un día de diferencia
            f"{f(dia(3))};Pago;OP2;200.00;;",
        )
        assert conciliacion.conciliar_automaticamente(e, escena.usuario) == 2
        unidas = {x.referencia: x for x in e.lineas.all()}
        assert unidas["OP1"].movimiento_id == deposito.pk
        assert unidas["OP2"].movimiento_id == pago.pk
        assert unidas["OP1"].union == "AUTOMATICA"

    def test_el_numero_de_operacion_desempata(self, escena):
        mover(escena, "EGRESO", "50", 3, referencia="AAA")
        buscado = mover(escena, "EGRESO", "50", 3, referencia="BBB")
        e = importar(escena, f"{f(dia(3))};Pago;BBB;50.00;;")
        assert conciliacion.conciliar_automaticamente(e, escena.usuario) == 1
        assert e.lineas.get().movimiento_id == buscado.pk

    def test_si_hay_dudas_no_adivina(self, escena):
        mover(escena, "EGRESO", "50", 3)
        mover(escena, "EGRESO", "50", 3)
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        assert conciliacion.conciliar_automaticamente(e, escena.usuario) == 0

    def test_dos_lineas_que_reclaman_el_mismo_movimiento_quedan_pendientes(self, escena):
        mover(escena, "EGRESO", "50", 3)
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;", f"{f(dia(2))};Pago;;50.00;;")
        assert conciliacion.conciliar_automaticamente(e, escena.usuario) == 0

    def test_no_une_importes_distintos_ni_fechas_lejanas(self, escena):
        mover(escena, "EGRESO", "50", 10)
        mover(escena, "EGRESO", "51", 3)
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        assert conciliacion.conciliar_automaticamente(e, escena.usuario) == 0

    def test_un_movimiento_anulado_no_cuenta(self, escena):
        m = mover(escena, "EGRESO", "50", 3)
        servicios.anular_movimiento(m, motivo="Error")
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        assert conciliacion.conciliar_automaticamente(e, escena.usuario) == 0


class TestManual:
    def test_candidatos_con_margen_de_dias(self, escena):
        cerca = mover(escena, "EGRESO", "50", 5)
        mover(escena, "EGRESO", "50", 20)
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        linea = e.lineas.get()
        assert [m.pk for m in conciliacion.candidatos(linea, dias=5)] == [cerca.pk]
        assert len(conciliacion.candidatos(linea, dias=31)) == 2

    def test_conciliar_valida_el_importe_y_el_tipo(self, escena):
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        linea = e.lineas.get()
        with pytest.raises(ConciliacionInvalida, match="importe"):
            conciliacion.conciliar(linea, mover(escena, "EGRESO", "51", 3), escena.usuario)
        with pytest.raises(ConciliacionInvalida, match="importe"):
            conciliacion.conciliar(linea, mover(escena, "INGRESO", "50", 3), escena.usuario)
        buena = mover(escena, "EGRESO", "50", 3)
        assert conciliacion.conciliar(linea, buena, escena.usuario).union == "MANUAL"

    def test_un_movimiento_no_se_une_dos_veces(self, escena):
        e = importar(escena, f"{f(dia(3))};Pago;A;50.00;;", f"{f(dia(3))};Pago;B;50.00;;")
        m = mover(escena, "EGRESO", "50", 3)
        primera, segunda = e.lineas.order_by("orden")
        conciliacion.conciliar(primera, m, escena.usuario)
        with pytest.raises(ConciliacionInvalida):
            conciliacion.conciliar(segunda, m, escena.usuario)

    def test_no_une_movimientos_de_otra_cuenta(self, escena):
        otra = CuentaFinanciera.objects.sin_ambito().create(
            empresa=escena.empresa, nombre="BBVA", tipo="BANCO", moneda="PEN", banco="BBVA"
        )
        ajeno = servicios.registrar_movimiento(
            empresa=escena.empresa,
            cuenta=otra,
            tipo="EGRESO",
            monto=dec("50"),
            concepto=escena.conceptos["GASTOS_VARIOS"],
            fecha=dia(3),
        )
        linea = importar(escena, f"{f(dia(3))};Pago;;50.00;;").lineas.get()
        with pytest.raises(ConciliacionInvalida, match="otra cuenta"):
            conciliacion.conciliar(linea, ajeno, escena.usuario)

    def test_un_movimiento_conciliado_no_se_anula(self, escena):
        m = mover(escena, "EGRESO", "50", 3)
        linea = importar(escena, f"{f(dia(3))};Pago;;50.00;;").lineas.get()
        conciliacion.conciliar(linea, m, escena.usuario)
        with pytest.raises(MovimientoNoAnulable, match="conciliado"):
            servicios.anular_movimiento(m, motivo="Error")
        conciliacion.desconciliar(linea, escena.usuario)
        servicios.anular_movimiento(m, motivo="Error")  # ya libre


class TestPartidas:
    def test_lo_que_el_banco_cobro_se_registra_y_queda_conciliado(self, escena):
        linea = importar(escena, f"{f(dia(2))};Comisión mantenimiento;OP9;5.00;;").lineas.get()
        hecha = conciliacion.registrar_partida(
            linea, concepto=escena.conceptos["COMISION_BANCARIA"], usuario=escena.usuario
        )
        m = hecha.movimiento
        assert (m.tipo, m.monto, m.fecha, m.referencia, m.origen_tipo) == (
            "EGRESO", dec("5"), dia(2), "OP9", Origen.EXTRACTO,
        )  # fmt: skip
        assert (m.origen_id, m.glosa) == (linea.pk, "Comisión mantenimiento")
        assert hecha.union == "REGISTRADA"
        assert servicios.saldo_de(escena.banco) == dec("-5")

    def test_el_concepto_debe_ser_del_tipo_de_la_linea(self, escena):
        linea = importar(escena, f"{f(dia(2))};Comisión;;5.00;;").lineas.get()
        with pytest.raises(MovimientoInvalido):
            conciliacion.registrar_partida(
                linea, concepto=escena.conceptos["INTERESES"], usuario=escena.usuario
            )
        assert not MovimientoCaja.objects.exists()

    def test_deshacer_una_partida_anula_su_movimiento(self, escena):
        linea = importar(escena, f"{f(dia(2))};Comisión;;5.00;;").lineas.get()
        hecha = conciliacion.registrar_partida(
            linea, concepto=escena.conceptos["COMISION_BANCARIA"], usuario=escena.usuario
        )
        movimiento = hecha.movimiento
        conciliacion.desconciliar(hecha, escena.usuario)
        movimiento.refresh_from_db()
        assert movimiento.estado == "ANULADO"
        assert servicios.saldo_de(escena.banco) == dec("0")
        linea.refresh_from_db()
        assert linea.movimiento_id is None

    def test_deshacer_una_union_manual_conserva_el_movimiento(self, escena):
        m = mover(escena, "EGRESO", "50", 3)
        linea = importar(escena, f"{f(dia(3))};Pago;;50.00;;").lineas.get()
        conciliacion.conciliar(linea, m, escena.usuario)
        conciliacion.desconciliar(linea, escena.usuario)
        m.refresh_from_db()
        assert m.estado == "EMITIDO"

    def test_una_linea_libre_no_se_deshace(self, escena):
        linea = importar(escena, f"{f(dia(3))};Pago;;50.00;;").lineas.get()
        with pytest.raises(ConciliacionInvalida, match="no está conciliada"):
            conciliacion.desconciliar(linea, escena.usuario)


class TestCierre:
    def conciliado_por_completo(self, escena):
        mover(escena, "INGRESO", "1000", 5, referencia="OP1")
        mover(escena, "EGRESO", "200", 3)
        e = importar(
            escena,
            f"{f(dia(5))};Depósito;OP1;;1000.00;",
            f"{f(dia(3))};Pago;OP2;200.00;;",
            f"{f(dia(2))};Comisión;OP3;5.00;;",
            saldo_inicial=dec("0"),
            saldo_final=dec("795"),
        )
        conciliacion.conciliar_automaticamente(e, escena.usuario)
        pendiente = e.lineas.get(movimiento__isnull=True)
        conciliacion.registrar_partida(
            pendiente, concepto=escena.conceptos["COMISION_BANCARIA"], usuario=escena.usuario
        )
        return e

    def test_resumen_de_un_extracto_que_cuadra(self, escena):
        e = self.conciliado_por_completo(escena)
        r = conciliacion.resumen(e)
        assert (r["lineas"], r["conciliadas"], r["pendientes"]) == (3, 3, 0)
        assert (r["saldo_libros"], r["saldo_banco"], r["diferencia"]) == (
            dec("795"), dec("795"), dec("0"),
        )  # fmt: skip
        assert (r["banco_sin_libro"], r["libro_sin_banco"]) == (dec("0"), dec("0"))

    def test_los_movimientos_en_transito_no_impiden_cerrar(self, escena):
        e = self.conciliado_por_completo(escena)
        mover(escena, "INGRESO", "300", 2)  # depósito que el banco aún no muestra
        r = conciliacion.resumen(e)
        assert (r["libro_sin_banco"], r["libro_sin_banco_cantidad"], r["diferencia"]) == (
            dec("300"), 1, dec("0"),
        )  # fmt: skip
        cerrado = conciliacion.cerrar(e, usuario=escena.usuario)
        assert (cerrado.estado, cerrado.cerrado_por_nombre) == ("CERRADO", "conciliador")

    def test_no_cierra_con_lineas_sin_conciliar(self, escena):
        e = importar(escena, f"{f(dia(2))};Comisión;OP3;5.00;;")
        with pytest.raises(ConciliacionInvalida, match="1 líneas del banco sin conciliar"):
            conciliacion.cerrar(e, usuario=escena.usuario)

    def test_una_diferencia_pide_explicacion(self, escena):
        mover(escena, "INGRESO", "100", 3)
        e = importar(
            escena,
            f"{f(dia(3))};Depósito;;;100.00;",
            saldo_inicial=dec("10"),
            saldo_final=dec("110"),
        )
        conciliacion.conciliar_automaticamente(e, escena.usuario)
        with pytest.raises(MovimientoInvalido, match="no cuadran"):
            conciliacion.cerrar(e, usuario=escena.usuario)
        assert (
            conciliacion.cerrar(e, usuario=escena.usuario, nota="Saldo previo sin registrar").estado
            == "CERRADO"
        )

    def test_cerrado_no_admite_cambios(self, escena):
        e = self.conciliado_por_completo(escena)
        conciliacion.cerrar(e, usuario=escena.usuario)
        linea = e.lineas.first()
        with pytest.raises(ConciliacionInvalida, match="cerrado"):
            conciliacion.desconciliar(linea, escena.usuario)
        with pytest.raises(ConciliacionInvalida, match="cerrado"):
            conciliacion.conciliar_automaticamente(e, escena.usuario)
        with pytest.raises(ConciliacionInvalida, match="cerrado"):
            conciliacion.descartar(e, escena.usuario)

    def test_reabrir_pide_motivo_y_devuelve_el_control(self, escena):
        e = self.conciliado_por_completo(escena)
        conciliacion.cerrar(e, usuario=escena.usuario)
        with pytest.raises(MovimientoInvalido, match="motivo"):
            conciliacion.reabrir(e, motivo=" ", usuario=escena.usuario)
        abierto = conciliacion.reabrir(e, motivo="Faltaba una comisión", usuario=escena.usuario)
        assert (abierto.estado, abierto.reaperturas, abierto.cerrado_en) == ("ABIERTO", 1, None)
        conciliacion.desconciliar(e.lineas.first(), escena.usuario)

    def test_descartar_un_extracto_equivocado(self, escena):
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        conciliacion.descartar(e, escena.usuario)
        assert not EstadoCuenta.objects.exists()
        # Se puede volver a importar el mismo archivo.
        assert importar(escena, f"{f(dia(3))};Pago;;50.00;;").lineas.count() == 1

    def test_no_se_descarta_con_lineas_conciliadas(self, escena):
        m = mover(escena, "EGRESO", "50", 3)
        e = importar(escena, f"{f(dia(3))};Pago;;50.00;;")
        conciliacion.conciliar(e.lineas.get(), m, escena.usuario)
        with pytest.raises(ConciliacionInvalida, match="conciliadas"):
            conciliacion.descartar(e, escena.usuario)
