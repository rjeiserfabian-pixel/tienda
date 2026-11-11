"""Toma de inventario físico (entrega 4): informe en Excel y PDF, y la operación 28 en el libro."""

import io
import time
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from apps.inventario import tomas
from apps.inventario.reportes import toma as informe_toma
from apps.inventario.reportes.generar import generar

from .conftest import comprar

pytestmark = pytest.mark.django_db

D = Decimal


def _pausa():
    time.sleep(0.02)


def _toma_cerrada(entorno, cantidades: dict):
    """Una toma cerrada donde cada producto se contó con la cantidad indicada."""
    toma = tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk)
    toma = tomas.abrir_toma(toma.pk)
    _pausa()
    for producto, cantidad in cantidades.items():
        tomas.registrar_conteo(
            toma_id=toma.pk, producto_id=producto.pk, cantidad=D(str(cantidad)), confirmar_cero=True
        )
        _pausa()
    marcados = list(tomas.DetalleToma.objects.filter(toma=toma, requiere_reconteo=True))
    if marcados:
        tomas.iniciar_reconteo(toma.pk)
        for d in marcados:
            tomas.registrar_conteo(
                toma_id=toma.pk,
                producto_id=d.producto_id,
                cantidad=d.cantidad_contada,
                nota="Verificado",
                confirmar_cero=True,
            )
    return tomas.cerrar_toma(toma.pk, confirmar_pendientes=True)


class TestInforme:
    def test_excel_con_resumen_diferencias_y_detalle(self, entorno):
        falta, sobra, bien = (
            entorno.producto("Falta"),
            entorno.producto("Sobra"),
            entorno.producto("Bien"),
        )
        for producto in (falta, sobra, bien):
            comprar(entorno, producto, 10, 20)
        toma = _toma_cerrada(entorno, {falta: 8, sobra: 11, bien: 10})
        resultado = informe_toma.generar(toma, "xlsx")
        assert resultado.nombre == f"toma-inventario_{entorno.e1.ruc}_{toma.numero:06d}.xlsx"
        libro = load_workbook(io.BytesIO(resultado.contenido))
        assert libro.sheetnames == ["Resumen", "Diferencias", "Detalle"]
        diferencias = list(libro["Diferencias"].iter_rows(values_only=True))
        nombres = [f[1] for f in diferencias if f[1] in ("Falta", "Sobra", "Bien")]
        assert nombres == ["Falta", "Sobra"]  # el mayor faltante primero; lo conforme no va
        detalle = [f[1] for f in libro["Detalle"].iter_rows(values_only=True)]
        assert {"Falta", "Sobra", "Bien"} <= set(detalle)
        resumen = {f[0]: f[2] for f in libro["Resumen"].iter_rows(values_only=True) if f[0]}
        assert resumen["Faltantes (productos)"] == 1 and resumen["Sobrantes (productos)"] == 1
        assert resumen["Diferencia neta (S/, al costo)"] == -20  # -40 + 20, al costo

    def test_un_nombre_que_parece_formula_se_escribe_como_texto(self, entorno):
        raro = entorno.producto('=HYPERLINK("http://x.test","clic")')
        comprar(entorno, raro, 10, 20)
        toma = _toma_cerrada(entorno, {raro: 8})
        libro = load_workbook(io.BytesIO(informe_toma.generar(toma, "xlsx").contenido))
        celdas = [
            c for fila in libro["Diferencias"].iter_rows() for c in fila if c.value == raro.nombre
        ]
        assert celdas and all(c.data_type == "s" for c in celdas)

    def test_pdf_valido_y_sin_diferencias(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _toma_cerrada(entorno, {cemento: 10})
        assert informe_toma.generar(toma, "pdf").contenido.startswith(b"%PDF")
        con_dif = informe_toma.reunir(toma)
        assert con_dif.diferencias == []

    def test_los_pendientes_se_cuentan_aparte(self, entorno):
        contado, sin_contar = entorno.producto("A"), entorno.producto("B")
        comprar(entorno, contado, 10, 20)
        comprar(entorno, sin_contar, 10, 20)
        toma = _toma_cerrada(entorno, {contado: 10})
        assert informe_toma.reunir(toma).sin_contar == 1


class TestLibro:
    def test_el_ajuste_aparece_en_el_libro_valorizado_con_la_operacion_28(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _toma_cerrada(entorno, {cemento: 9})
        tomas.aprobar_toma(toma.pk)
        resultado = generar(
            "kardex-valorizado",
            "xlsx",
            empresa=entorno.e1,
            almacen=entorno.alm1,
            producto=cemento,
            desde=entorno.hace(10),
            hasta=entorno.hoy,
            fecha=None,
        )
        hoja = load_workbook(io.BytesIO(resultado.contenido)).active
        operaciones = [fila[4] for fila in hoja.iter_rows(values_only=True)]
        assert "28" in operaciones  # tipo de operación (tabla 12) del ajuste
        # el ajuste salió por 1 unidad al costo promedio de 20
        salidas = [fila for fila in hoja.iter_rows(values_only=True) if fila[4] == "28"]
        assert salidas[0][8] == 1 and salidas[0][10] == 20
