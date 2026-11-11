"""Informe de una toma de inventario físico: resumen y diferencias valorizadas AL COSTO.

Lleva el stock del sistema y las diferencias, así que solo lo pide quien puede aprobar la toma.
En Excel van tres hojas (resumen, diferencias y todo lo contado); en PDF el resumen y las
diferencias. Los textos de la base se escriben siempre como texto (ver ``excel._poner``) y se
escapan en el PDF (ver ``pdf._p``).
"""

import io
import re
from dataclasses import dataclass
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils import timezone
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.inventario import tomas
from apps.inventario.models import DetalleToma, ResultadoToma, TomaInventario

from . import excel, pdf
from .datos import _con_tope

CERO = Decimal("0")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"


@dataclass(frozen=True, slots=True)
class InformeToma:
    toma: TomaInventario
    resumen: dict
    detalles: list[DetalleToma]

    @property
    def diferencias(self) -> list[DetalleToma]:
        """Faltantes y sobrantes, del mayor faltante (al costo) al mayor sobrante."""
        con_diferencia = [
            d
            for d in self.detalles
            if d.resultado in (ResultadoToma.FALTANTE, ResultadoToma.SOBRANTE)
        ]
        return sorted(con_diferencia, key=lambda d: (d.importe_diferencia or CERO, d.pk))

    @property
    def sin_contar(self) -> int:
        return sum(1 for d in self.detalles if d.cantidad_contada is None)


def reunir(toma: TomaInventario) -> InformeToma:
    detalles = _con_tope(
        DetalleToma.objects.filter(toma=toma)
        .select_related("producto__unidad", "producto__categoria")
        .order_by("producto__categoria__nombre", "producto__nombre", "id")
    )
    return InformeToma(toma=toma, resumen=tomas.avance(toma), detalles=detalles)


def _fecha_hora(valor) -> str:
    return "" if valor is None else timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")


def _pares(informe: InformeToma) -> list[tuple[str, str]]:
    toma, empresa = informe.toma, informe.toma.empresa
    alcance = (
        "Todo el almacén"
        if toma.alcance == "TODO"
        else "Categorías: " + ", ".join(sorted(c.nombre for c in toma.categorias.all()))
    )
    return [
        ("RUC", empresa.ruc),
        ("EMPRESA", empresa.razon_social),
        ("ALMACÉN", toma.almacen.nombre),
        ("TOMA", f"N° {toma.numero:06d} ({toma.get_estado_display()})"),
        ("ALCANCE", alcance),
        ("STOCK AL CORTE", _fecha_hora(toma.fecha_corte)),
        ("CIERRE DEL CONTEO", _fecha_hora(toma.cerrada_en)),
        ("APROBACIÓN", _fecha_hora(toma.aprobada_en)),
        ("VALORIZACIÓN", "Costo promedio ponderado a la fecha de corte"),
    ]


_COLUMNAS = [
    "CÓDIGO",
    "PRODUCTO",
    "CATEGORÍA",
    "UNIDAD",
    "STOCK SISTEMA",
    "COSTO UNITARIO",
    "CONTADO",
    "DIFERENCIA",
    "IMPORTE (AL COSTO)",
    "RESULTADO",
    "ESTADO FÍSICO",
    "CONTEOS",
    "NOTA",
]


def _fila_excel(ws, fila: int, d: DetalleToma) -> None:
    p = d.producto
    excel._poner(ws, fila, 1, p.codigo)
    excel._poner(ws, fila, 2, p.nombre)
    excel._poner(ws, fila, 3, p.categoria.nombre)
    excel._poner(ws, fila, 4, p.unidad.abreviatura)
    excel._poner(ws, fila, 5, d.stock_sistema, excel.CANTIDAD)
    excel._poner(ws, fila, 6, d.costo_unitario, excel.UNITARIO)
    excel._poner(ws, fila, 7, d.cantidad_contada, excel.CANTIDAD)
    excel._poner(ws, fila, 8, d.diferencia, excel.CANTIDAD)
    excel._poner(ws, fila, 9, d.importe_diferencia, excel.DINERO)
    excel._poner(ws, fila, 10, d.get_resultado_display())
    excel._poner(ws, fila, 11, d.get_estado_fisico_display())
    excel._poner(ws, fila, 12, d.numero_conteos, "0")
    excel._poner(ws, fila, 13, d.nota)


def _hoja_tabla(libro: Workbook, titulo: str, subtitulo: str, informe: InformeToma, filas) -> None:
    ws = libro.create_sheet(titulo)
    fila = excel._bloque_encabezado(
        ws, f"TOMA DE INVENTARIO FÍSICO · {titulo.upper()}", subtitulo, _pares(informe)
    )
    excel._cabecera_de_tabla(ws, fila, _COLUMNAS)
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    total = CERO
    for d in filas:
        fila += 1
        _fila_excel(ws, fila, d)
        total += d.importe_diferencia or CERO
    fila += 1
    excel._poner(ws, fila, 8, "TOTAL", negrita=True)
    excel._poner(ws, fila, 9, total, excel.DINERO, negrita=True)
    excel._anchos(ws, [12, 44, 20, 10, 14, 16, 14, 14, 18, 12, 14, 10, 40])
    excel._hoja_horizontal(ws)


def excel_informe(informe: InformeToma) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = "Resumen"
    r = informe.resumen
    fila = excel._bloque_encabezado(
        ws,
        "TOMA DE INVENTARIO FÍSICO · RESUMEN",
        f"Toma N° {informe.toma.numero:06d}",
        _pares(informe),
    )
    for etiqueta, valor, formato in [
        ("Productos en la toma", r["total"], "0"),
        ("Productos contados", r["contados"], "0"),
        ("Productos sin contar", r["por_contar"], "0"),
        ("Avance (%)", r["porcentaje_avance"], "0.0"),
        ("Conformes", r["resultado"]["conformes"], "0"),
        ("Faltantes (productos)", r["resultado"]["faltantes"], "0"),
        ("Sobrantes (productos)", r["resultado"]["sobrantes"], "0"),
        ("Unidades faltantes", r["resultado"]["unidades_faltantes"], excel.CANTIDAD),
        ("Unidades sobrantes", r["resultado"]["unidades_sobrantes"], excel.CANTIDAD),
        ("Importe faltante (S/, al costo)", r["resultado"]["importe_faltante"], excel.DINERO),
        ("Importe sobrante (S/, al costo)", r["resultado"]["importe_sobrante"], excel.DINERO),
        ("Diferencia neta (S/, al costo)", r["resultado"]["importe_neto"], excel.DINERO),
    ]:
        excel._poner(ws, fila, 1, etiqueta, negrita=True)
        excel._poner(ws, fila, 3, valor, formato)
        fila += 1
    excel._anchos(ws, [36, 4, 22])
    _hoja_tabla(libro, "Diferencias", "Faltantes y sobrantes", informe, informe.diferencias)
    _hoja_tabla(libro, "Detalle", "Todos los productos de la toma", informe, informe.detalles)
    return excel._a_bytes(libro)


def pdf_informe(informe: InformeToma) -> bytes:
    toma, r = informe.toma, informe.resumen
    res = r["resultado"]
    filas = [
        [
            pdf._p(d.producto.codigo),
            pdf._p(d.producto.nombre),
            pdf._p(d.producto.unidad.abreviatura),
            pdf.n3(d.stock_sistema),
            pdf.n4(d.costo_unitario),
            pdf.n3(d.cantidad_contada),
            pdf.n3(d.diferencia),
            pdf.n2(d.importe_diferencia),
            pdf._p(d.get_resultado_display()),
            pdf._p(d.nota),
        ]
        for d in informe.diferencias
    ]
    salida = io.BytesIO()
    doc = SimpleDocTemplate(
        salida,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"Toma de inventario {toma.numero:06d}",
    )
    partes = [Paragraph(escape(f"TOMA DE INVENTARIO FÍSICO N° {toma.numero:06d}"), pdf.TITULO)]
    for etiqueta, valor in _pares(informe):
        partes.append(Paragraph(escape(f"{etiqueta}: {valor}"), pdf.NORMAL))
    partes.append(Spacer(1, 3 * mm))
    resumen = (
        f"Contados {r['contados']} de {r['total']} ({r['porcentaje_avance']} %) · "
        f"Conformes {res['conformes']} · Faltantes {res['faltantes']} "
        f"(S/ {pdf.n2(res['importe_faltante'])}) · Sobrantes {res['sobrantes']} "
        f"(S/ {pdf.n2(res['importe_sobrante'])}) · Diferencia neta S/ {pdf.n2(res['importe_neto'])}"
    )
    partes.append(Paragraph(escape(resumen), pdf.NORMAL))
    if informe.sin_contar:
        partes.append(
            Paragraph(escape(f"{informe.sin_contar} productos quedaron sin contar."), pdf.NORMAL)
        )
    partes.append(Spacer(1, 3 * mm))
    if not filas:
        partes.append(Paragraph("No hay diferencias que informar.", pdf.NORMAL))
    else:
        encabezado = [
            "CÓDIGO",
            "PRODUCTO",
            "UNID.",
            "SISTEMA",
            "COSTO UNIT.",
            "CONTADO",
            "DIFERENCIA",
            "IMPORTE",
            "RESULTADO",
            "NOTA",
        ]
        total = ["", "", "", "", "", "", "TOTAL", pdf.n2(res["importe_neto"]), "", ""]
        tabla = Table(
            [encabezado, *filas, total],
            colWidths=[a * mm for a in [20, 78, 14, 22, 24, 22, 24, 26, 22, 45]],
            repeatRows=1,
        )
        tabla.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, pdf.colors.HexColor("#9AA3B2")),
                    ("BACKGROUND", (0, 0), (-1, 0), pdf.GRIS),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("BACKGROUND", (0, -1), (-1, -1), pdf.GRIS_CLARO),
                    ("ALIGN", (3, 1), (7, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        partes.append(tabla)
    doc.build(partes)
    return salida.getvalue()


@dataclass(frozen=True, slots=True)
class ResultadoInforme:
    contenido: bytes
    nombre: str
    mime: str
    filas: int


def generar(toma: TomaInventario, formato: str) -> ResultadoInforme:
    informe = reunir(toma)
    extension = "pdf" if formato == "pdf" else "xlsx"
    contenido = pdf_informe(informe) if formato == "pdf" else excel_informe(informe)
    nombre = re.sub(r"[^A-Za-z0-9_-]", "", f"toma-inventario_{toma.empresa.ruc}_{toma.numero:06d}")
    return ResultadoInforme(
        contenido=contenido,
        nombre=f"{nombre}.{extension}",
        mime=PDF if formato == "pdf" else XLSX,
        filas=len(informe.detalles),
    )
