"""Libros y reportes en PDF (A4 horizontal) con reportlab.

Los textos de la base se escapan antes de dibujarlos: reportlab interpreta marcas parecidas a
HTML en los párrafos, y un nombre con «<» no debe alterar el documento.
"""

import io
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.inventario.models import TipoMovimiento
from apps.mantenimiento.models import TipoExistencia

from .datos import FilaCostoVenta, FilaSaldo, KardexDatos

_ESTILOS = getSampleStyleSheet()
TITULO = ParagraphStyle("titulo", parent=_ESTILOS["Heading2"], fontSize=12, spaceAfter=2)
NORMAL = ParagraphStyle("normal", parent=_ESTILOS["Normal"], fontSize=8, leading=10)
CELDA = ParagraphStyle("celda", parent=_ESTILOS["Normal"], fontSize=7, leading=8.5)
GRIS = colors.HexColor("#D9DEE8")
GRIS_CLARO = colors.HexColor("#EEF1F6")


def n3(valor: Decimal | None) -> str:
    return "" if valor is None else f"{valor:,.3f}"


def n2(valor: Decimal | None) -> str:
    return "" if valor is None else f"{valor:,.2f}"


def n4(valor: Decimal | None) -> str:
    return "" if valor is None else f"{valor:,.4f}"


def _dia(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def _p(texto, estilo=CELDA) -> Paragraph:
    return Paragraph(escape(str(texto or "")), estilo)


def _documento(
    titulo: str,
    lineas: list[str],
    encabezados: list[list[str]],
    filas: list[list],
    anchos_mm: list[float],
    *,
    derecha_desde: int,
    spans: list[tuple[int, int, int]] | None = None,
    totales: list | None = None,
) -> bytes:
    """Arma el PDF: título, datos de la empresa y una tabla con encabezado repetido por página.

    ``derecha_desde`` es la primera columna numérica (se alinea a la derecha). ``spans`` agrupa
    celdas del primer encabezado: ``(fila_encabezado, desde_columna, hasta_columna)``.
    """
    salida = io.BytesIO()
    doc = SimpleDocTemplate(
        salida,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=titulo[:120],
    )
    partes = [Paragraph(escape(titulo), TITULO)]
    partes += [Paragraph(escape(linea), NORMAL) for linea in lineas]
    partes.append(Spacer(1, 4 * mm))
    datos = [*encabezados, *filas]
    if totales:
        datos.append(totales)
    tabla = Table(datos, colWidths=[a * mm for a in anchos_mm], repeatRows=len(encabezados))
    estilo = [
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9AA3B2")),
        ("BACKGROUND", (0, 0), (-1, len(encabezados) - 1), GRIS),
        ("FONTNAME", (0, 0), (-1, len(encabezados) - 1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, len(encabezados) - 1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (derecha_desde, len(encabezados)), (-1, -1), "RIGHT"),
    ]
    for fila, desde, hasta in spans or []:
        estilo.append(("SPAN", (desde, fila), (hasta, fila)))
    if totales:
        estilo += [
            ("BACKGROUND", (0, -1), (-1, -1), GRIS_CLARO),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]
    tabla.setStyle(TableStyle(estilo))
    partes.append(tabla)
    doc.build(partes)
    return salida.getvalue()


def _datos_kardex(datos: KardexDatos) -> list[str]:
    e, a, p = datos.empresa, datos.almacen, datos.producto
    return [
        f"PERIODO: {_dia(datos.desde)} al {_dia(datos.hasta)}    RUC: {e.ruc}",
        f"RAZÓN SOCIAL: {e.razon_social}",
        f"ESTABLECIMIENTO: {a.sucursal.codigo} - {a.sucursal.nombre} (almacén {a.nombre})",
        f"CÓDIGO DE LA EXISTENCIA: {p.codigo}    TIPO (TABLA 5): {p.tipo_existencia} - "
        f"{TipoExistencia(p.tipo_existencia).label}",
        f"DESCRIPCIÓN: {p.nombre}    UNIDAD: {p.unidad.nombre} "
        f"({p.unidad.codigo_sunat or p.unidad.abreviatura})",
        "MÉTODO DE VALUACIÓN: Promedio ponderado",
    ]


def libro_12_1(datos: KardexDatos) -> bytes:
    filas = [
        [_dia(datos.desde), "", "", "SALDO INICIAL", "16", "", "", n3(datos.saldo_inicial.cantidad)]
    ]
    entradas = salidas = Decimal("0")
    saldo = datos.saldo_inicial.cantidad
    for ln in datos.lineas:
        m = ln.movimiento
        es_entrada = ln.tipo == TipoMovimiento.ENTRADA
        entradas += ln.cantidad if es_entrada else 0
        salidas += 0 if es_entrada else ln.cantidad
        saldo = ln.saldo_cantidad
        filas.append(
            [
                _dia(ln.fecha),
                m.comprobante_tipo,
                _p(m.comprobante_serie),
                _p(m.comprobante_numero),
                m.tipo_operacion,
                n3(ln.cantidad) if es_entrada else "",
                "" if es_entrada else n3(ln.cantidad),
                n3(ln.saldo_cantidad),
            ]
        )
    return _documento(
        "FORMATO 12.1: REGISTRO DE INVENTARIO PERMANENTE EN UNIDADES FÍSICAS",
        _datos_kardex(datos),
        [
            [
                "FECHA",
                "TIPO\n(T.10)",
                "SERIE",
                "NÚMERO",
                "TIPO DE\nOPERACIÓN (T.12)",
                "ENTRADAS",
                "SALIDAS",
                "SALDO FINAL",
            ]
        ],
        filas,
        [24, 18, 24, 34, 36, 36, 36, 36],
        derecha_desde=5,
        totales=["", "", "", "", "TOTALES", n3(entradas), n3(salidas), n3(saldo)],
    )


def libro_13_1(datos: KardexDatos) -> bytes:
    ini = datos.saldo_inicial
    filas = [
        [
            _dia(datos.desde),
            "",
            "",
            "SALDO INICIAL",
            "16",
            "",
            "",
            "",
            "",
            "",
            "",
            n3(ini.cantidad),
            n4(ini.costo_unitario),
            n2(ini.costo_total),
        ]
    ]
    ent_c = ent_v = sal_c = sal_v = Decimal("0")
    saldo_c, saldo_v = ini.cantidad, ini.costo_total
    for ln in datos.lineas:
        m = ln.movimiento
        es_entrada = ln.tipo == TipoMovimiento.ENTRADA
        bloque = [n3(ln.cantidad), n4(ln.costo_unitario), n2(ln.costo_total)]
        vacio = ["", "", ""]
        if es_entrada:
            ent_c, ent_v = ent_c + ln.cantidad, ent_v + ln.costo_total
        else:
            sal_c, sal_v = sal_c + ln.cantidad, sal_v + ln.costo_total
        saldo_c, saldo_v = ln.saldo_cantidad, ln.saldo_costo_total
        filas.append(
            [
                _dia(ln.fecha),
                m.comprobante_tipo,
                _p(m.comprobante_serie),
                _p(m.comprobante_numero),
                m.tipo_operacion,
                *(bloque if es_entrada else vacio),
                *(vacio if es_entrada else bloque),
                n3(ln.saldo_cantidad),
                n4(ln.saldo_costo_unitario),
                n2(ln.saldo_costo_total),
            ]
        )
    return _documento(
        "FORMATO 13.1: REGISTRO DE INVENTARIO PERMANENTE VALORIZADO",
        _datos_kardex(datos),
        [
            [
                "COMPROBANTE O DOCUMENTO",
                "",
                "",
                "",
                "",
                "ENTRADAS",
                "",
                "",
                "SALIDAS",
                "",
                "",
                "SALDO FINAL",
                "",
                "",
            ],
            [
                "FECHA",
                "TIPO",
                "SERIE",
                "NÚMERO",
                "T.12",
                "CANT.",
                "C. UNIT.",
                "C. TOTAL",
                "CANT.",
                "C. UNIT.",
                "C. TOTAL",
                "CANT.",
                "C. UNIT.",
                "C. TOTAL",
            ],
        ],
        filas,
        [19, 11, 17, 24, 11, 19, 21, 22, 19, 21, 22, 19, 21, 22],
        derecha_desde=5,
        spans=[(0, 0, 4), (0, 5, 7), (0, 8, 10), (0, 11, 13)],
        totales=[
            "",
            "",
            "",
            "",
            "TOTALES",
            n3(ent_c),
            "",
            n2(ent_v),
            n3(sal_c),
            "",
            n2(sal_v),
            n3(saldo_c),
            "",
            n2(saldo_v),
        ],
    )


def saldos_pdf(empresa, fecha: date, almacen, filas: list[FilaSaldo]) -> bytes:
    total = sum((f.costo_total for f in filas), Decimal("0"))
    return _documento(
        "SALDOS DE INVENTARIO VALORIZADO",
        [
            f"AL: {_dia(fecha)}    RUC: {empresa.ruc}",
            f"EMPRESA: {empresa.razon_social}",
            f"ALMACÉN: {almacen.nombre if almacen else 'Todos'}    MÉTODO: Promedio ponderado",
        ],
        [["ALMACÉN", "CÓDIGO", "PRODUCTO", "UNIDAD", "CANTIDAD", "COSTO UNITARIO", "VALOR"]],
        [
            [
                _p(f.almacen.nombre),
                _p(f.producto.codigo),
                _p(f.producto.nombre),
                _p(f.producto.unidad.abreviatura),
                n3(f.cantidad),
                n4(f.costo_unitario),
                n2(f.costo_total),
            ]
            for f in filas
        ],
        [40, 24, 100, 18, 30, 32, 33],
        derecha_desde=4,
        totales=["", "", "", "", "", "TOTAL", n2(total)],
    )


def costo_venta_pdf(
    empresa, desde: date, hasta: date, almacen, filas: list[FilaCostoVenta]
) -> bytes:
    suma = [Decimal("0")] * 5
    cuerpo = []
    for f in filas:
        cuerpo.append(
            [
                _p(f.almacen.nombre),
                _p(f.producto.nombre),
                n3(f.inicial_cantidad),
                n2(f.inicial_valor),
                n3(f.entradas_cantidad),
                n2(f.entradas_valor),
                n3(f.salidas_cantidad),
                n2(f.salidas_valor),
                n3(f.final_cantidad),
                n2(f.final_valor),
                n2(f.costo_de_venta),
            ]
        )
        for k, valor in enumerate(
            [f.inicial_valor, f.entradas_valor, f.salidas_valor, f.final_valor, f.costo_de_venta]
        ):
            suma[k] += valor
    return _documento(
        "COSTO DE VENTA POR PRODUCTO",
        [
            f"DEL {_dia(desde)} AL {_dia(hasta)}    RUC: {empresa.ruc}",
            f"EMPRESA: {empresa.razon_social}",
            f"ALMACÉN: {almacen.nombre if almacen else 'Todos'}    MÉTODO: Promedio ponderado",
        ],
        [
            ["", "", "INV. INICIAL", "", "ENTRADAS", "", "SALIDAS", "", "INV. FINAL", "", ""],
            [
                "ALMACÉN",
                "PRODUCTO",
                "CANT.",
                "VALOR",
                "CANT.",
                "VALOR",
                "CANT.",
                "VALOR",
                "CANT.",
                "VALOR",
                "COSTO DE VENTA",
            ],
        ],
        cuerpo,
        [26, 56, 18, 22, 18, 22, 18, 22, 18, 22, 25],
        derecha_desde=2,
        spans=[(0, 2, 3), (0, 4, 5), (0, 6, 7), (0, 8, 9)],
        totales=[
            "",
            "TOTALES",
            "",
            n2(suma[0]),
            "",
            n2(suma[1]),
            "",
            n2(suma[2]),
            "",
            n2(suma[3]),
            n2(suma[4]),
        ],
    )
