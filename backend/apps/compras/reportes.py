"""Registro de compras y reporte de devoluciones: lo que se compró (y devolvió) en un rango.

El registro trae una fila por comprobante vigente (las anuladas no se incluyen), con la base y el
IGV de cada afectación, el total y su equivalente en soles. Las devoluciones a proveedores entran
como notas de crédito que RESTAN (importes negativos, en el periodo de la fecha de la nota) y dicen
qué comprobante modifican. El reporte de devoluciones las resume por proveedor. Se ven en pantalla
(vista previa) y se descargan en Excel. Los textos que vienen de la base se escriben siempre como
texto, nunca como fórmula.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.organizacion.models import Empresa

from .exceptions import CompraInvalida
from .models import Compra, DevolucionCompra

MAX_DIAS = 366
MAX_FILAS_VISTA = 200
DOS = Decimal("0.01")
CERO = Decimal("0")

TITULOS = [
    "N° interno",
    "Fecha de emisión",
    "Tipo",
    "Serie",
    "Número",
    "Tipo doc.",
    "N° documento",
    "Proveedor",
    "Base gravada",
    "IGV",
    "Exonerada",
    "Inafecta",
    "Redondeo",
    "Total",
    "Moneda",
    "T. cambio",
    "Total en soles",
    "Forma de pago",
    "Documento que modifica",
    "Origen",
]


def _soles(valor: Decimal, tipo_cambio: Decimal) -> Decimal:
    return (valor * tipo_cambio).quantize(DOS, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class Registro:
    filas: list[dict] = field(default_factory=list)
    # Totales en soles (cada comprobante convertido con su tipo de cambio).
    total_gravada: Decimal = CERO
    total_igv: Decimal = CERO
    total_exonerada: Decimal = CERO
    total_inafecta: Decimal = CERO
    total_soles: Decimal = CERO


def validar_rango(desde: date | None, hasta: date | None) -> tuple[date, date]:
    if desde is None or hasta is None:
        raise CompraInvalida("Indique el rango de fechas (desde y hasta).")
    if desde > hasta:
        raise CompraInvalida("La fecha «desde» no puede ser posterior a «hasta».")
    if hasta > timezone.localdate():
        raise CompraInvalida("La fecha «hasta» no puede ser futura.")
    if (hasta - desde).days > MAX_DIAS:
        raise CompraInvalida("El rango no puede pasar de un año.")
    return desde, hasta


def registro_de_compras(
    empresa: Empresa,
    desde: date,
    hasta: date,
    incluir_gastos: bool = True,
    incluir_devoluciones: bool = True,
) -> Registro:
    """Las compras vigentes de la empresa con fecha de emisión entre ``desde`` y ``hasta``.

    Con ``incluir_gastos`` también entran los gastos con comprobante (luz, alquiler…), que son
    comprobantes de compra de servicios. Lo que no detalla IGV va en «inafecta». Con
    ``incluir_devoluciones`` entran las notas de crédito de devoluciones a proveedores, restando.
    """
    compras = (
        Compra.objects.filter(
            empresa=empresa,
            estado=Compra.Estado.EMITIDO,
            fecha_emision__gte=desde,
            fecha_emision__lte=hasta,
        )
        .select_related("proveedor", "tipo_comprobante")
        .order_by("fecha_emision", "numero")
    )
    registro = Registro()
    for c in compras:
        cambio = c.tipo_cambio
        gravada = c.op_gravada + c.op_ivap
        igv = c.igv + c.ivap
        registro.filas.append(
            {
                "numero": c.numero,
                "fecha": c.fecha_emision,
                "tipo": c.tipo_comprobante.codigo,
                "tipo_nombre": c.tipo_comprobante.nombre,
                "serie": c.comprobante_serie,
                "comprobante": c.comprobante_numero,
                "tipo_documento": c.proveedor.tipo_documento,
                "documento": c.proveedor.numero_documento,
                "proveedor": c.proveedor.nombre,
                "gravada": gravada,
                "igv": igv,
                "exonerada": c.op_exonerada,
                "inafecta": c.op_inafecta,
                "redondeo": c.ajuste_redondeo,
                "total": c.total,
                "moneda": c.moneda,
                "tipo_cambio": cambio,
                "total_soles": _soles(c.total, cambio),
                "forma_pago": c.get_forma_pago_display(),
                "modifica": "",
                "origen": "COMPRA",
            }
        )
        registro.total_gravada += _soles(gravada, cambio)
        registro.total_igv += _soles(igv, cambio)
        registro.total_exonerada += _soles(c.op_exonerada, cambio)
        registro.total_inafecta += _soles(c.op_inafecta, cambio)
        registro.total_soles += _soles(c.total, cambio)
    if incluir_gastos:
        _agregar_gastos(registro, empresa, desde, hasta)
    if incluir_devoluciones:
        _agregar_devoluciones(registro, empresa, desde, hasta)
    if incluir_gastos or incluir_devoluciones:
        registro.filas.sort(key=lambda f: (f["fecha"], f["origen"], f["numero"]))
    return registro


def _agregar_devoluciones(registro: Registro, empresa: Empresa, desde: date, hasta: date) -> None:
    """Las notas de crédito de devoluciones vigentes: cada una resta, en el mes de su fecha."""
    devoluciones = (
        DevolucionCompra.objects.filter(
            empresa=empresa,
            estado=DevolucionCompra.Estado.EMITIDO,
            fecha_emision__gte=desde,
            fecha_emision__lte=hasta,
        )
        .select_related("proveedor", "tipo_comprobante", "compra__tipo_comprobante")
        .order_by("fecha_emision", "numero")
    )
    for d in devoluciones:
        cambio = d.tipo_cambio
        gravada = d.op_gravada + d.op_ivap
        igv = d.igv + d.ivap
        compra = d.compra
        registro.filas.append(
            {
                "numero": d.numero,
                "fecha": d.fecha_emision,
                "tipo": d.tipo_comprobante.codigo,
                "tipo_nombre": d.tipo_comprobante.nombre,
                "serie": d.comprobante_serie,
                "comprobante": d.comprobante_numero,
                "tipo_documento": d.proveedor.tipo_documento,
                "documento": d.proveedor.numero_documento,
                "proveedor": d.proveedor.nombre,
                "gravada": -gravada,
                "igv": -igv,
                "exonerada": -d.op_exonerada,
                "inafecta": -d.op_inafecta,
                "redondeo": -d.ajuste_redondeo,
                "total": -d.total,
                "moneda": d.moneda,
                "tipo_cambio": cambio,
                "total_soles": -_soles(d.total, cambio),
                "forma_pago": "Nota de crédito",
                "modifica": f"{compra.tipo_comprobante.codigo} {compra.comprobante}",
                "origen": "DEVOLUCION",
            }
        )
        registro.total_gravada -= _soles(gravada, cambio)
        registro.total_igv -= _soles(igv, cambio)
        registro.total_exonerada -= _soles(d.op_exonerada, cambio)
        registro.total_inafecta -= _soles(d.op_inafecta, cambio)
        registro.total_soles -= _soles(d.total, cambio)


def _agregar_gastos(registro: Registro, empresa: Empresa, desde: date, hasta: date) -> None:
    from apps.gastos.models import Gasto  # compras solo lo necesita para este registro

    gastos = (
        Gasto.objects.filter(
            empresa=empresa,
            estado=Gasto.Estado.EMITIDO,
            con_comprobante=True,
            fecha__gte=desde,
            fecha__lte=hasta,
        )
        .select_related("proveedor", "tipo_comprobante")
        .order_by("fecha", "numero")
    )
    for g in gastos:
        cambio = g.tipo_cambio
        registro.filas.append(
            {
                "numero": g.numero,
                "fecha": g.fecha,
                "tipo": g.tipo_comprobante.codigo,
                "tipo_nombre": g.tipo_comprobante.nombre,
                "serie": g.comprobante_serie,
                "comprobante": g.comprobante_numero,
                "tipo_documento": g.proveedor.tipo_documento if g.proveedor else "",
                "documento": g.proveedor.numero_documento if g.proveedor else "",
                "proveedor": g.proveedor.nombre if g.proveedor else g.descripcion,
                "gravada": g.base_gravada,
                "igv": g.igv,
                "exonerada": CERO,
                "inafecta": g.no_gravado,
                "redondeo": CERO,
                "total": g.total,
                "moneda": g.moneda,
                "tipo_cambio": cambio,
                "total_soles": _soles(g.total, cambio),
                "forma_pago": g.get_forma_pago_display(),
                "modifica": "",
                "origen": "GASTO",
            }
        )
        registro.total_gravada += _soles(g.base_gravada, cambio)
        registro.total_igv += _soles(g.igv, cambio)
        registro.total_inafecta += _soles(g.no_gravado, cambio)
        registro.total_soles += _soles(g.total, cambio)


def vista_previa(registro: Registro) -> dict:
    """Datos para mostrar en pantalla: las primeras filas y los totales en soles."""

    def dinero(valor: Decimal) -> str:
        return f"{valor:.2f}"

    return {
        "total_filas": len(registro.filas),
        "truncado": len(registro.filas) > MAX_FILAS_VISTA,
        "filas": [
            {
                **f,
                "fecha": f["fecha"].isoformat(),
                **{
                    k: dinero(f[k])
                    for k in ("gravada", "igv", "exonerada", "inafecta", "total", "total_soles")
                },
                "tipo_cambio": f"{f['tipo_cambio']:.4f}",
            }
            for f in registro.filas[:MAX_FILAS_VISTA]
        ],
        "totales": {
            "gravada": dinero(registro.total_gravada),
            "igv": dinero(registro.total_igv),
            "exonerada": dinero(registro.total_exonerada),
            "inafecta": dinero(registro.total_inafecta),
            "total": dinero(registro.total_soles),
        },
    }


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
ORIGEN_TEXTO = {"COMPRA": "Compra", "GASTO": "Gasto", "DEVOLUCION": "Devolución"}
DINERO = "#,##0.00"
CAMBIO = "0.0000"
FECHA = "dd/mm/yyyy"
NEGRITA = Font(bold=True)
FONDO_CABECERA = PatternFill("solid", fgColor="D9DEE8")
FONDO_TOTAL = PatternFill("solid", fgColor="EEF1F6")
BORDE = Border(*(Side(style="thin", color="9AA3B2"),) * 4)
CENTRADO = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _poner(ws, fila: int, columna: int, valor, formato: str | None = None, *, negrita=False):
    celda = ws.cell(row=fila, column=columna)
    if isinstance(valor, str):
        celda.value = valor
        celda.data_type = "s"  # texto: un nombre que empiece con «=» no se evalúa como fórmula
    else:
        celda.value = valor
        if formato:
            celda.number_format = formato
    if negrita:
        celda.font = NEGRITA
    return celda


def libro_excel(empresa: Empresa, registro: Registro, desde: date, hasta: date) -> bytes:
    libro = Workbook()
    ws = libro.active
    ws.title = "Registro de compras"
    _poner(ws, 1, 1, "REGISTRO DE COMPRAS").font = Font(bold=True, size=13)
    _poner(ws, 2, 1, f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")
    _poner(ws, 4, 1, "RUC", negrita=True)
    _poner(ws, 4, 3, empresa.ruc)
    _poner(ws, 5, 1, "Razón social", negrita=True)
    _poner(ws, 5, 3, empresa.razon_social)
    cabecera = 7
    for i, titulo in enumerate(TITULOS, start=1):
        celda = _poner(ws, cabecera, i, titulo, negrita=True)
        celda.fill, celda.border, celda.alignment = FONDO_CABECERA, BORDE, CENTRADO

    fila = cabecera + 1
    for f in registro.filas:
        valores = [
            (f["numero"], None),
            (f["fecha"], FECHA),
            (f["tipo"], None),
            (f["serie"], None),
            (f["comprobante"], None),
            (f["tipo_documento"], None),
            (f["documento"], None),
            (f["proveedor"], None),
            (f["gravada"], DINERO),
            (f["igv"], DINERO),
            (f["exonerada"], DINERO),
            (f["inafecta"], DINERO),
            (f["redondeo"], DINERO),
            (f["total"], DINERO),
            (f["moneda"], None),
            (f["tipo_cambio"], CAMBIO),
            (f["total_soles"], DINERO),
            (f["forma_pago"], None),
            (f["modifica"], None),
            (ORIGEN_TEXTO[f["origen"]], None),
        ]
        for columna, (valor, formato) in enumerate(valores, start=1):
            _poner(ws, fila, columna, valor, formato).border = BORDE
        fila += 1

    _poner(ws, fila, 8, "TOTALES EN SOLES", negrita=True)
    for columna, valor in (
        (9, registro.total_gravada),
        (10, registro.total_igv),
        (11, registro.total_exonerada),
        (12, registro.total_inafecta),
        (17, registro.total_soles),
    ):
        celda = _poner(ws, fila, columna, valor, DINERO, negrita=True)
        celda.fill, celda.border = FONDO_TOTAL, BORDE
    anchos = [10, 13, 7, 9, 13, 9, 14, 38, 14, 12, 12, 12, 10, 14, 8, 10, 15, 14, 18, 12]
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.freeze_panes = ws.cell(row=cabecera + 1, column=1)
    ws.page_setup.orientation = "landscape"
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def nombre_archivo(empresa: Empresa, desde: date, hasta: date) -> str:
    """Nombre de archivo seguro: solo letras, números y guiones."""
    limpio = re.sub(
        r"[^A-Za-z0-9_-]", "", f"registro-compras_{empresa.ruc}_{desde:%Y%m%d}_{hasta:%Y%m%d}"
    )
    return f"{limpio}.xlsx"


# ---------------------------------------------------------------------------
# Devoluciones a proveedores
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ReporteDevoluciones:
    # Una fila por proveedor y moneda (soles y dólares nunca se suman entre sí).
    resumen: list[dict] = field(default_factory=list)
    detalle: list[dict] = field(default_factory=list)
    # Totales por moneda y lo que salió del inventario, en soles.
    totales: dict[str, dict] = field(default_factory=dict)
    costo_soles: Decimal = CERO


_CAMPOS_RESUMEN = ("total", "igv", "aplicado_a_deuda", "reembolsado", "saldo_a_favor")


def devoluciones_por_proveedor(empresa: Empresa, desde: date, hasta: date) -> ReporteDevoluciones:
    """Las devoluciones vigentes con fecha de nota entre ``desde`` y ``hasta``, por proveedor."""
    devoluciones = (
        DevolucionCompra.objects.filter(
            empresa=empresa,
            estado=DevolucionCompra.Estado.EMITIDO,
            fecha_emision__gte=desde,
            fecha_emision__lte=hasta,
        )
        .select_related("proveedor", "tipo_comprobante", "compra__tipo_comprobante")
        .order_by("proveedor__nombre", "fecha_emision", "numero")
    )
    reporte = ReporteDevoluciones()
    por_proveedor: dict[tuple[int, str], dict] = {}
    for d in devoluciones:
        igv = d.igv + d.ivap
        reporte.detalle.append(
            {
                "numero": d.numero,
                "fecha": d.fecha_emision,
                "tipo_documento": d.proveedor.tipo_documento,
                "documento": d.proveedor.numero_documento,
                "proveedor": d.proveedor.nombre,
                "serie": d.comprobante_serie,
                "comprobante": d.comprobante_numero,
                "compra": f"{d.compra.tipo_comprobante.codigo} {d.compra.comprobante}",
                "compra_numero": d.compra.numero,
                "motivo": d.get_motivo_display(),
                "razon": d.razon,
                "moneda": d.moneda,
                "total": d.total,
                "igv": igv,
                "costo_soles": d.costo_soles,
                "aplicado_a_deuda": d.aplicado_a_deuda,
                "reembolsado": d.reembolsado,
                "saldo_a_favor": d.saldo_a_favor,
            }
        )
        clave = (d.proveedor_id, d.moneda)
        fila = por_proveedor.setdefault(
            clave,
            {
                "proveedor": d.proveedor.nombre,
                "tipo_documento": d.proveedor.tipo_documento,
                "documento": d.proveedor.numero_documento,
                "moneda": d.moneda,
                "cantidad": 0,
                "costo_soles": CERO,
                **dict.fromkeys(_CAMPOS_RESUMEN, CERO),
            },
        )
        total = reporte.totales.setdefault(
            d.moneda, {"cantidad": 0, **dict.fromkeys(_CAMPOS_RESUMEN, CERO)}
        )
        valores = {
            "total": d.total,
            "igv": igv,
            "aplicado_a_deuda": d.aplicado_a_deuda,
            "reembolsado": d.reembolsado,
            "saldo_a_favor": d.saldo_a_favor,
        }
        for destino in (fila, total):
            destino["cantidad"] += 1
            for k, v in valores.items():
                destino[k] += v
        fila["costo_soles"] += d.costo_soles
        reporte.costo_soles += d.costo_soles
    reporte.resumen = sorted(por_proveedor.values(), key=lambda f: (f["proveedor"], f["moneda"]))
    return reporte


def vista_devoluciones(reporte: ReporteDevoluciones) -> dict:
    """Datos para mostrar en pantalla: el resumen completo y las primeras filas del detalle."""

    def dinero(valor: Decimal) -> str:
        return f"{valor:.2f}"

    def convertir(fila: dict, campos: tuple[str, ...]) -> dict:
        return {**fila, **{k: dinero(fila[k]) for k in campos}}

    return {
        "total_filas": len(reporte.detalle),
        "truncado": len(reporte.detalle) > MAX_FILAS_VISTA,
        "resumen": [convertir(f, (*_CAMPOS_RESUMEN, "costo_soles")) for f in reporte.resumen],
        "detalle": [
            {**convertir(f, (*_CAMPOS_RESUMEN, "costo_soles")), "fecha": f["fecha"].isoformat()}
            for f in reporte.detalle[:MAX_FILAS_VISTA]
        ],
        "totales": {
            moneda: convertir(t, _CAMPOS_RESUMEN) for moneda, t in sorted(reporte.totales.items())
        },
        "costo_soles": dinero(reporte.costo_soles),
    }


def libro_devoluciones(
    empresa: Empresa, reporte: ReporteDevoluciones, desde: date, hasta: date
) -> bytes:
    libro = Workbook()

    def encabezado(ws, titulo: str, columnas: list[str], anchos: list[int]) -> int:
        _poner(ws, 1, 1, titulo).font = Font(bold=True, size=13)
        _poner(ws, 2, 1, f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")
        _poner(ws, 4, 1, "RUC", negrita=True)
        _poner(ws, 4, 3, empresa.ruc)
        _poner(ws, 5, 1, "Razón social", negrita=True)
        _poner(ws, 5, 3, empresa.razon_social)
        for i, texto in enumerate(columnas, start=1):
            celda = _poner(ws, 7, i, texto, negrita=True)
            celda.fill, celda.border, celda.alignment = FONDO_CABECERA, BORDE, CENTRADO
            ws.column_dimensions[get_column_letter(i)].width = anchos[i - 1]
        ws.freeze_panes = ws.cell(row=8, column=1)
        ws.page_setup.orientation = "landscape"
        return 8

    resumen = libro.active
    resumen.title = "Resumen por proveedor"
    fila = encabezado(
        resumen,
        "DEVOLUCIONES A PROVEEDORES · RESUMEN",
        [
            "Tipo doc.",
            "N° documento",
            "Proveedor",
            "Moneda",
            "Devoluciones",
            "Total",
            "IGV",
            "Rebajó la deuda",
            "Dinero devuelto",
            "Saldo a favor",
            "Salió del inventario (S/)",
        ],
        [9, 14, 38, 8, 13, 14, 12, 15, 15, 14, 18],
    )
    for f in reporte.resumen:
        valores = [
            (f["tipo_documento"], None),
            (f["documento"], None),
            (f["proveedor"], None),
            (f["moneda"], None),
            (f["cantidad"], None),
            (f["total"], DINERO),
            (f["igv"], DINERO),
            (f["aplicado_a_deuda"], DINERO),
            (f["reembolsado"], DINERO),
            (f["saldo_a_favor"], DINERO),
            (f["costo_soles"], DINERO),
        ]
        for columna, (valor, formato) in enumerate(valores, start=1):
            _poner(resumen, fila, columna, valor, formato).border = BORDE
        fila += 1
    for moneda, t in sorted(reporte.totales.items()):
        _poner(resumen, fila, 3, f"TOTAL EN {moneda}", negrita=True)
        _poner(resumen, fila, 4, moneda, negrita=True)
        for columna, valor in (
            (5, t["cantidad"]),
            (6, t["total"]),
            (7, t["igv"]),
            (8, t["aplicado_a_deuda"]),
            (9, t["reembolsado"]),
            (10, t["saldo_a_favor"]),
        ):
            celda = _poner(
                resumen, fila, columna, valor, DINERO if columna > 5 else None, negrita=True
            )
            celda.fill, celda.border = FONDO_TOTAL, BORDE
        fila += 1
    celda = _poner(resumen, fila, 11, reporte.costo_soles, DINERO, negrita=True)
    celda.fill, celda.border = FONDO_TOTAL, BORDE
    _poner(resumen, fila, 3, "SALIÓ DEL INVENTARIO (SOLES)", negrita=True)

    detalle = libro.create_sheet("Detalle")
    fila = encabezado(
        detalle,
        "DEVOLUCIONES A PROVEEDORES · DETALLE",
        [
            "N° interno",
            "Fecha",
            "Tipo doc.",
            "N° documento",
            "Proveedor",
            "Nota de crédito",
            "Compra que modifica",
            "Tipo",
            "Motivo",
            "Moneda",
            "Total",
            "IGV",
            "Rebajó la deuda",
            "Dinero devuelto",
            "Saldo a favor",
            "Salió del inventario (S/)",
        ],
        [10, 12, 9, 14, 38, 16, 20, 18, 40, 8, 14, 12, 15, 15, 14, 18],
    )
    for f in reporte.detalle:
        valores = [
            (f["numero"], None),
            (f["fecha"], FECHA),
            (f["tipo_documento"], None),
            (f["documento"], None),
            (f["proveedor"], None),
            (f"{f['serie']}-{f['comprobante']}" if f["serie"] else f["comprobante"], None),
            (f["compra"], None),
            (f["motivo"], None),
            (f["razon"], None),
            (f["moneda"], None),
            (f["total"], DINERO),
            (f["igv"], DINERO),
            (f["aplicado_a_deuda"], DINERO),
            (f["reembolsado"], DINERO),
            (f["saldo_a_favor"], DINERO),
            (f["costo_soles"], DINERO),
        ]
        for columna, (valor, formato) in enumerate(valores, start=1):
            _poner(detalle, fila, columna, valor, formato).border = BORDE
        fila += 1
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def nombre_archivo_devoluciones(empresa: Empresa, desde: date, hasta: date) -> str:
    limpio = re.sub(
        r"[^A-Za-z0-9_-]",
        "",
        f"devoluciones-proveedores_{empresa.ruc}_{desde:%Y%m%d}_{hasta:%Y%m%d}",
    )
    return f"{limpio}.xlsx"
