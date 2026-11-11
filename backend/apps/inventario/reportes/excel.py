"""Libros y reportes en Excel (.xlsx) con openpyxl.

Seguridad: los textos que vienen de la base (nombres de productos, proveedores, observaciones)
se escriben SIEMPRE como texto. Si no, un nombre que empiece con «=» o «@» se evaluaría como
fórmula al abrir el archivo (inyección de fórmulas).
"""

import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.inventario.models import MovimientoInventario, TipoMovimiento
from apps.mantenimiento.models import TipoExistencia

from .datos import FilaCostoVenta, FilaSaldo, KardexDatos, MovimientosDatos

CANTIDAD = "#,##0.000"
DINERO = "#,##0.00"
UNITARIO = "#,##0.0000"
FECHA = "dd/mm/yyyy"

NEGRITA = Font(bold=True)
TITULO = Font(bold=True, size=13)
FONDO_CABECERA = PatternFill("solid", fgColor="D9DEE8")
FONDO_TOTAL = PatternFill("solid", fgColor="EEF1F6")
BORDE = Border(*(Side(style="thin", color="9AA3B2"),) * 4)
CENTRADO = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _poner(ws, fila: int, columna: int, valor, formato: str | None = None, *, negrita=False):
    """Escribe una celda. Los textos nunca se interpretan como fórmula."""
    celda = ws.cell(row=fila, column=columna)
    if isinstance(valor, str):
        celda.value = valor
        celda.data_type = "s"
    else:
        celda.value = valor
        if formato:
            celda.number_format = formato
    if negrita:
        celda.font = NEGRITA
    return celda


def _cabecera_de_tabla(ws, fila: int, titulos: list[str]) -> None:
    for i, titulo in enumerate(titulos, start=1):
        celda = _poner(ws, fila, i, titulo, negrita=True)
        celda.fill, celda.border, celda.alignment = FONDO_CABECERA, BORDE, CENTRADO


def _bloque_encabezado(ws, titulo: str, subtitulo: str, pares: list[tuple[str, str]]) -> int:
    """Título y datos de la empresa; devuelve la siguiente fila libre."""
    _poner(ws, 1, 1, titulo).font = TITULO
    _poner(ws, 2, 1, subtitulo)
    fila = 4
    for etiqueta, valor in pares:
        _poner(ws, fila, 1, etiqueta, negrita=True)
        _poner(ws, fila, 3, valor)
        fila += 1
    return fila + 1


def _anchos(ws, anchos: list[float]) -> None:
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho


def _a_bytes(libro: Workbook) -> bytes:
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _hoja_horizontal(ws) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _dia(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def _pares_kardex(datos: KardexDatos) -> list[tuple[str, str]]:
    empresa, almacen, producto = datos.empresa, datos.almacen, datos.producto
    unidad = producto.unidad
    return [
        ("PERIODO", f"{_dia(datos.desde)} al {_dia(datos.hasta)}"),
        ("RUC", empresa.ruc),
        ("APELLIDOS Y NOMBRES, DENOMINACIÓN O RAZÓN SOCIAL", empresa.razon_social),
        (
            "ESTABLECIMIENTO",
            f"{almacen.sucursal.codigo} - {almacen.sucursal.nombre} (almacén {almacen.nombre})",
        ),
        ("CÓDIGO DE LA EXISTENCIA", producto.codigo),
        (
            "TIPO DE EXISTENCIA (TABLA 5)",
            f"{producto.tipo_existencia} - {TipoExistencia(producto.tipo_existencia).label}",
        ),
        ("DESCRIPCIÓN", producto.nombre),
        ("UNIDAD DE MEDIDA", f"{unidad.nombre} ({unidad.codigo_sunat or unidad.abreviatura})"),
        ("MÉTODO DE VALUACIÓN", "Promedio ponderado"),
    ]


# ---------------------------------------------------------------------------
# Formato 12.1: inventario permanente en unidades físicas
# ---------------------------------------------------------------------------
def libro_12_1(datos: KardexDatos) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = "Formato 12.1"
    fila = _bloque_encabezado(
        ws,
        "FORMATO 12.1: REGISTRO DE INVENTARIO PERMANENTE EN UNIDADES FÍSICAS",
        "Detalle del inventario permanente en unidades físicas",
        _pares_kardex(datos),
    )
    _cabecera_de_tabla(
        ws,
        fila,
        [
            "FECHA",
            "TIPO (T.10)",
            "SERIE",
            "NÚMERO",
            "TIPO DE OPERACIÓN (T.12)",
            "ENTRADAS",
            "SALIDAS",
            "SALDO FINAL",
        ],
    )
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    fila += 1
    _poner(ws, fila, 1, datos.desde, FECHA)
    _poner(ws, fila, 5, "16")
    _poner(ws, fila, 8, datos.saldo_inicial.cantidad, CANTIDAD)
    _poner(ws, fila, 4, "SALDO INICIAL", negrita=True)
    total_entradas = total_salidas = Decimal("0")
    saldo_final = datos.saldo_inicial.cantidad
    for linea in datos.lineas:
        fila += 1
        m = linea.movimiento
        _poner(ws, fila, 1, linea.fecha, FECHA)
        _poner(ws, fila, 2, m.comprobante_tipo)
        _poner(ws, fila, 3, m.comprobante_serie)
        _poner(ws, fila, 4, m.comprobante_numero)
        _poner(ws, fila, 5, m.tipo_operacion)
        if linea.tipo == TipoMovimiento.ENTRADA:
            _poner(ws, fila, 6, linea.cantidad, CANTIDAD)
            total_entradas += linea.cantidad
        else:
            _poner(ws, fila, 7, linea.cantidad, CANTIDAD)
            total_salidas += linea.cantidad
        _poner(ws, fila, 8, linea.saldo_cantidad, CANTIDAD)
        saldo_final = linea.saldo_cantidad
    fila += 1
    _poner(ws, fila, 5, "TOTALES", negrita=True)
    _poner(ws, fila, 6, total_entradas, CANTIDAD, negrita=True)
    _poner(ws, fila, 7, total_salidas, CANTIDAD, negrita=True)
    _poner(ws, fila, 8, saldo_final, CANTIDAD, negrita=True)
    _anchos(ws, [13, 12, 10, 16, 24, 14, 14, 14])
    _hoja_horizontal(ws)
    return _a_bytes(libro)


# ---------------------------------------------------------------------------
# Formato 13.1: inventario permanente valorizado
# ---------------------------------------------------------------------------
def libro_13_1(datos: KardexDatos) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = "Formato 13.1"
    fila = _bloque_encabezado(
        ws,
        "FORMATO 13.1: REGISTRO DE INVENTARIO PERMANENTE VALORIZADO",
        "Detalle del inventario valorizado",
        _pares_kardex(datos),
    )
    grupos = [
        (1, 5, "DOCUMENTO DE TRASLADO, COMPROBANTE DE PAGO, DOCUMENTO INTERNO O SIMILAR"),
        (6, 8, "ENTRADAS"),
        (9, 11, "SALIDAS"),
        (12, 14, "SALDO FINAL"),
    ]
    for desde, hasta, texto in grupos:
        ws.merge_cells(start_row=fila, start_column=desde, end_row=fila, end_column=hasta)
        celda = _poner(ws, fila, desde, texto, negrita=True)
        celda.fill, celda.border, celda.alignment = FONDO_CABECERA, BORDE, CENTRADO
    fila += 1
    _cabecera_de_tabla(
        ws,
        fila,
        ["FECHA", "TIPO (T.10)", "SERIE", "NÚMERO", "TIPO DE OPERACIÓN (T.12)"]
        + ["CANTIDAD", "COSTO UNITARIO", "COSTO TOTAL"] * 3,
    )
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    fila += 1
    inicial = datos.saldo_inicial
    _poner(ws, fila, 1, datos.desde, FECHA)
    _poner(ws, fila, 4, "SALDO INICIAL", negrita=True)
    _poner(ws, fila, 5, "16")
    _poner(ws, fila, 12, inicial.cantidad, CANTIDAD)
    _poner(ws, fila, 13, inicial.costo_unitario, UNITARIO)
    _poner(ws, fila, 14, inicial.costo_total, DINERO)
    ent_cant = ent_val = sal_cant = sal_val = Decimal("0")
    saldo_cantidad, saldo_total = inicial.cantidad, inicial.costo_total
    for linea in datos.lineas:
        fila += 1
        m = linea.movimiento
        _poner(ws, fila, 1, linea.fecha, FECHA)
        _poner(ws, fila, 2, m.comprobante_tipo)
        _poner(ws, fila, 3, m.comprobante_serie)
        _poner(ws, fila, 4, m.comprobante_numero)
        _poner(ws, fila, 5, m.tipo_operacion)
        base = 6 if linea.tipo == TipoMovimiento.ENTRADA else 9
        _poner(ws, fila, base, linea.cantidad, CANTIDAD)
        _poner(ws, fila, base + 1, linea.costo_unitario, UNITARIO)
        _poner(ws, fila, base + 2, linea.costo_total, DINERO)
        if linea.tipo == TipoMovimiento.ENTRADA:
            ent_cant, ent_val = ent_cant + linea.cantidad, ent_val + linea.costo_total
        else:
            sal_cant, sal_val = sal_cant + linea.cantidad, sal_val + linea.costo_total
        _poner(ws, fila, 12, linea.saldo_cantidad, CANTIDAD)
        _poner(ws, fila, 13, linea.saldo_costo_unitario, UNITARIO)
        _poner(ws, fila, 14, linea.saldo_costo_total, DINERO)
        saldo_cantidad, saldo_total = linea.saldo_cantidad, linea.saldo_costo_total
    fila += 1
    _poner(ws, fila, 5, "TOTALES", negrita=True)
    _poner(ws, fila, 6, ent_cant, CANTIDAD, negrita=True)
    _poner(ws, fila, 8, ent_val, DINERO, negrita=True)
    _poner(ws, fila, 9, sal_cant, CANTIDAD, negrita=True)
    _poner(ws, fila, 11, sal_val, DINERO, negrita=True)
    _poner(ws, fila, 12, saldo_cantidad, CANTIDAD, negrita=True)
    _poner(ws, fila, 14, saldo_total, DINERO, negrita=True)
    _anchos(ws, [13, 11, 9, 15, 20, 12, 14, 14, 12, 14, 14, 12, 14, 14])
    _hoja_horizontal(ws)
    return _a_bytes(libro)


# ---------------------------------------------------------------------------
# Saldos a una fecha y costo de venta
# ---------------------------------------------------------------------------
def _pares_empresa(empresa, extra: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [
        ("RUC", empresa.ruc),
        ("EMPRESA", empresa.razon_social),
        *extra,
        ("MÉTODO DE VALUACIÓN", "Promedio ponderado"),
    ]


def saldos_xlsx(empresa, fecha: date, almacen, filas: list[FilaSaldo]) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = "Saldos"
    fila = _bloque_encabezado(
        ws,
        "SALDOS DE INVENTARIO VALORIZADO",
        f"Al {_dia(fecha)}",
        _pares_empresa(empresa, [("ALMACÉN", almacen.nombre if almacen else "Todos")]),
    )
    _cabecera_de_tabla(
        ws, fila, ["ALMACÉN", "CÓDIGO", "PRODUCTO", "UNIDAD", "CANTIDAD", "COSTO UNITARIO", "VALOR"]
    )
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    total = Decimal("0")
    for f in filas:
        fila += 1
        _poner(ws, fila, 1, f.almacen.nombre)
        _poner(ws, fila, 2, f.producto.codigo)
        _poner(ws, fila, 3, f.producto.nombre)
        _poner(ws, fila, 4, f.producto.unidad.abreviatura)
        _poner(ws, fila, 5, f.cantidad, CANTIDAD)
        _poner(ws, fila, 6, f.costo_unitario, UNITARIO)
        _poner(ws, fila, 7, f.costo_total, DINERO)
        total += f.costo_total
    fila += 1
    _poner(ws, fila, 6, "TOTAL", negrita=True)
    _poner(ws, fila, 7, total, DINERO, negrita=True)
    _anchos(ws, [22, 12, 44, 10, 14, 16, 16])
    _hoja_horizontal(ws)
    return _a_bytes(libro)


def costo_venta_xlsx(
    empresa, desde: date, hasta: date, almacen, filas: list[FilaCostoVenta]
) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = "Costo de venta"
    fila = _bloque_encabezado(
        ws,
        "COSTO DE VENTA POR PRODUCTO",
        f"Del {_dia(desde)} al {_dia(hasta)}",
        _pares_empresa(empresa, [("ALMACÉN", almacen.nombre if almacen else "Todos")]),
    )
    for inicio, fin, texto in [
        (5, 6, "INVENTARIO INICIAL"),
        (7, 8, "ENTRADAS"),
        (9, 10, "SALIDAS"),
        (11, 12, "INVENTARIO FINAL"),
    ]:
        ws.merge_cells(start_row=fila, start_column=inicio, end_row=fila, end_column=fin)
        celda = _poner(ws, fila, inicio, texto, negrita=True)
        celda.fill, celda.border, celda.alignment = FONDO_CABECERA, BORDE, CENTRADO
    fila += 1
    _cabecera_de_tabla(
        ws,
        fila,
        ["ALMACÉN", "CÓDIGO", "PRODUCTO", "UNIDAD"]
        + ["CANTIDAD", "VALOR"] * 4
        + ["COSTO DE VENTA"],
    )
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    totales = [Decimal("0")] * 5
    for f in filas:
        fila += 1
        _poner(ws, fila, 1, f.almacen.nombre)
        _poner(ws, fila, 2, f.producto.codigo)
        _poner(ws, fila, 3, f.producto.nombre)
        _poner(ws, fila, 4, f.producto.unidad.abreviatura)
        valores = [
            (f.inicial_cantidad, CANTIDAD),
            (f.inicial_valor, DINERO),
            (f.entradas_cantidad, CANTIDAD),
            (f.entradas_valor, DINERO),
            (f.salidas_cantidad, CANTIDAD),
            (f.salidas_valor, DINERO),
            (f.final_cantidad, CANTIDAD),
            (f.final_valor, DINERO),
            (f.costo_de_venta, DINERO),
        ]
        for i, (valor, formato) in enumerate(valores, start=5):
            _poner(ws, fila, i, valor, formato)
        for k, valor in enumerate(
            [f.inicial_valor, f.entradas_valor, f.salidas_valor, f.final_valor, f.costo_de_venta]
        ):
            totales[k] += valor
    fila += 1
    _poner(ws, fila, 4, "TOTALES", negrita=True)
    for columna, valor in zip([6, 8, 10, 12, 13], totales, strict=True):
        _poner(ws, fila, columna, valor, DINERO, negrita=True)
    _anchos(ws, [20, 11, 40, 9, 12, 14, 12, 14, 12, 14, 12, 14, 16])
    _hoja_horizontal(ws)
    return _a_bytes(libro)


# ---------------------------------------------------------------------------
# Libro de movimientos: cabecera (Dcab) y detalle (Ddet), como el Kardex 2.0 del contador
# ---------------------------------------------------------------------------
_COLUMNAS_DCAB = [
    "ID",
    "DCTIPMOV",
    "DCTOCOD",
    "DCCPCOD",
    "FECHA",
    "PERIODO",
    "DCMON",
    "SERIE",
    "NUMERO",
    "RUC O DOCUMENTO",
    "PROVEEDOR O CLIENTE",
    "SUBTOTAL",
    "IGV",
    "TOTAL",
    "DCSIGV",
    "DCEST",
    "N° INTERNO",
    "ALMACEN",
    "ORIGEN",
    "TIPO DE CAMBIO",
    "OBSERVACION",
    "ID DEL MOVIMIENTO QUE ANULA",
]
_COLUMNAS_DDET = [
    "ID",
    "ORDEN",
    "CODIGO",
    "PRODUCTO",
    "UNIDAD",
    "CANTIDAD",
    "PRECIO UNITARIO",
    "COSTO UNITARIO (S/)",
    "COSTO TOTAL (S/)",
    "SALDO CANTIDAD",
    "SALDO COSTO UNITARIO (S/)",
    "SALDO COSTO TOTAL (S/)",
    "SERIES O IMEI",
]


def _series_de_linea(linea) -> list[str]:
    """Series o IMEI que entraron (o salieron) con la línea, ordenadas."""
    origen = linea.series_entrada if linea.tipo == TipoMovimiento.ENTRADA else linea.series_salida
    return sorted(s.numero for s in origen.all())


def movimientos_xlsx(datos: MovimientosDatos) -> bytes:
    libro = Workbook()
    leeme = libro.active
    leeme.title = "Léeme"
    textos = [
        "Libro de movimientos de inventario — "
        f"{datos.empresa.razon_social} (RUC {datos.empresa.ruc})",
        f"Del {_dia(datos.desde)} al {_dia(datos.hasta)}. "
        "Costos en soles, sin IGV, al promedio ponderado.",
        "Hoja Dcab: un renglón por movimiento. Hoja Ddet: un renglón por producto; "
        "la columna ID la une con Dcab.",
        "DCTIPMOV: D = entrada, H = salida. DCTOCOD: tipo de operación (tabla 12 SUNAT). "
        "DCCPCOD: tipo de comprobante (tabla 10).",
        "DCSIGV: S si los precios del comprobante incluyen IGV, N si no. "
        "DCEST: 1 = vigente, 2 = anulado.",
        "La columna ID es única y estable: al importar este archivo en otro sistema "
        "sirve para no duplicar movimientos.",
        "Los importes de Dcab están en la moneda del comprobante (columna DCMON); "
        "los de Ddet marcados (S/) están en soles.",
    ]
    for i, texto in enumerate(textos, start=1):
        _poner(leeme, i, 1, texto, negrita=(i == 1))
    leeme.column_dimensions["A"].width = 120

    dcab = libro.create_sheet("Dcab")
    ddet = libro.create_sheet("Ddet")
    _cabecera_de_tabla(dcab, 1, _COLUMNAS_DCAB)
    _cabecera_de_tabla(ddet, 1, _COLUMNAS_DDET)
    dcab.freeze_panes = "A2"
    ddet.freeze_panes = "A2"
    fila_c = fila_d = 1
    for m in datos.movimientos:
        fila_c += 1
        tercero = m.proveedor or m.cliente
        valores = [
            (m.pk, None),
            ("D" if m.tipo == TipoMovimiento.ENTRADA else "H", None),
            (m.tipo_operacion, None),
            (m.comprobante_tipo, None),
            (m.fecha, FECHA),
            (m.periodo, None),
            (m.moneda, None),
            (m.comprobante_serie, None),
            (m.comprobante_numero, None),
            (tercero.numero_documento if tercero else "", None),
            (tercero.nombre if tercero else "", None),
            (m.subtotal, DINERO),
            (m.igv, DINERO),
            (m.total, DINERO),
            ("S" if m.precios_incluyen_igv else "N", None),
            (2 if m.estado == MovimientoInventario.Estado.ANULADO else 1, None),
            (m.numero, None),
            (m.almacen.nombre, None),
            (m.origen, None),
            (m.tipo_cambio, UNITARIO),
            (m.observacion, None),
            (m.extorna_id, None),
        ]
        for columna, (valor, formato) in enumerate(valores, start=1):
            _poner(dcab, fila_c, columna, valor if valor is not None else "", formato)
        for linea in m.lineas.all():
            fila_d += 1
            valores_d = [
                (m.pk, None),
                (linea.orden + 1, None),
                (linea.producto.codigo, None),
                (linea.producto.nombre, None),
                (linea.producto.unidad.abreviatura, None),
                (linea.cantidad, CANTIDAD),
                (linea.precio_unitario, UNITARIO),
                (linea.costo_unitario, UNITARIO),
                (linea.costo_total, DINERO),
                (linea.saldo_cantidad, CANTIDAD),
                (linea.saldo_costo_unitario, UNITARIO),
                (linea.saldo_costo_total, DINERO),
                ("; ".join(_series_de_linea(linea)), None),
            ]
            for columna, (valor, formato) in enumerate(valores_d, start=1):
                _poner(ddet, fila_d, columna, valor if valor is not None else "", formato)
    _anchos(dcab, [9, 10, 9, 9, 12, 9, 7, 9, 14, 16, 34, 13, 11, 13, 8, 7, 10, 20, 20, 11, 30, 14])
    _anchos(ddet, [9, 7, 11, 40, 9, 12, 14, 14, 14, 13, 16, 16, 40])
    return _a_bytes(libro)


def antiguedad_xlsx(empresa, almacen, datos) -> bytes:
    """Antigüedad del stock: unidades por tramo de días y lo que ya pasó del umbral."""
    libro = Workbook()
    ws = libro.active
    ws.title = "Antigüedad"
    fila = _bloque_encabezado(
        ws,
        "ANTIGÜEDAD DEL STOCK",
        f"Al {_dia(datos.hoy)} · se considera antiguo lo que lleva más de {datos.umbral} días",
        _pares_empresa(empresa, [("ALMACÉN", almacen.nombre if almacen else "Todos")]),
    )
    _cabecera_de_tabla(
        ws,
        fila,
        [
            "ALMACÉN", "CÓDIGO", "PRODUCTO", "UNIDAD", "STOCK", "0-30 DÍAS", "31-60 DÍAS",
            "61-90 DÍAS", "91-180 DÍAS", "MÁS DE 180", "INGRESO MÁS ANTIGUO", "DÍAS",
            "UNIDADES ANTIGUAS", "VALOR ANTIGUO (COSTO PROM.)", "SIN FECHA",
        ],
    )  # fmt: skip
    ws.freeze_panes = ws.cell(row=fila + 1, column=1)
    total_unidades = total_valor = Decimal("0")
    for f in datos.filas:
        fila += 1
        _poner(ws, fila, 1, f.almacen.nombre)
        _poner(ws, fila, 2, f.producto.codigo)
        _poner(ws, fila, 3, f.producto.nombre)
        _poner(ws, fila, 4, f.producto.unidad.abreviatura)
        _poner(ws, fila, 5, f.saldo, CANTIDAD)
        for i, tramo in enumerate(f.tramos):
            _poner(ws, fila, 6 + i, tramo, CANTIDAD)
        _poner(ws, fila, 11, _dia(f.mas_antigua) if f.mas_antigua else "")
        _poner(ws, fila, 12, f.dias if f.dias is not None else "")
        _poner(ws, fila, 13, f.unidades_antiguas, CANTIDAD)
        _poner(ws, fila, 14, f.valor_antiguo, DINERO)
        _poner(ws, fila, 15, f.sin_fecha, CANTIDAD)
        total_unidades += f.unidades_antiguas
        total_valor += f.valor_antiguo
    fila += 1
    _poner(ws, fila, 12, "TOTAL", negrita=True)
    _poner(ws, fila, 13, total_unidades, CANTIDAD, negrita=True)
    _poner(ws, fila, 14, total_valor, DINERO, negrita=True)
    _anchos(ws, [20, 12, 40, 9, 11, 11, 11, 11, 12, 12, 16, 8, 14, 20, 11])
    _hoja_horizontal(ws)
    return _a_bytes(libro)
