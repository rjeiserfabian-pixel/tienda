"""Reportes de órdenes de compra: qué falta recibir, cómo cumple cada proveedor y qué cambió.

* **Pendientes de recibir** (hoy): cada línea de las órdenes emitidas que aún espera mercadería,
  con los días de atraso y su valor aproximado (sin IGV).
* **Cumplimiento por proveedor** (por fecha de la orden): cuánto de lo pedido llegó (en valor), en
  cuántos días y cuántas entregas fueron a tiempo. Soles y dólares nunca se suman.
* **Diferencias de precio** (por fecha de la compra): líneas recibidas contra una orden cuyo precio
  sin IGV difiere del pactado, con el efecto en dinero.

Se ven en pantalla (vista previa) y se descargan en Excel. Los textos que vienen de la base se
escriben siempre como texto, nunca como fórmula.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Max, Prefetch
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from apps.organizacion.models import Empresa

from .models import Compra, LineaCompra, LineaOrdenCompra, OrdenCompra
from .recepcion import RECIBE
from .reportes import (
    BORDE,
    CENTRADO,
    DINERO,
    FECHA,
    FONDO_CABECERA,
    FONDO_TOTAL,
    MAX_FILAS_VISTA,
    _poner,
)

CERO = Decimal("0")
CIEN = Decimal("100")
DOS = Decimal("0.01")
CUATRO = Decimal("0.0001")
Estado = OrdenCompra.Estado
CON_ENTREGA = (Estado.EMITIDA, Estado.PARCIAL, Estado.RECIBIDA, Estado.CERRADA)


def _neto(precio: Decimal, tasa: Decimal, incluye_igv: bool) -> Decimal:
    return precio / (Decimal(1) + tasa / CIEN) if incluye_igv else precio


@dataclass(slots=True)
class ReporteOrdenes:
    pendientes: list[dict] = field(default_factory=list)
    atrasadas: int = 0  # órdenes (no líneas) con la entrega vencida
    valor_pendiente: dict[str, Decimal] = field(default_factory=dict)
    cumplimiento: list[dict] = field(default_factory=list)
    diferencias: list[dict] = field(default_factory=list)
    lineas_comparadas: int = 0
    impacto: dict[str, Decimal] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cada reporte
# ---------------------------------------------------------------------------
def _pendientes(empresa: Empresa, hoy: date, reporte: ReporteOrdenes) -> None:
    ordenes = (
        OrdenCompra.objects.filter(empresa=empresa, estado__in=RECIBE)
        .select_related("proveedor", "almacen")
        .prefetch_related(
            Prefetch("lineas", queryset=LineaOrdenCompra.objects.select_related("producto"))
        )
    )
    atrasadas: set[int] = set()
    for orden in ordenes:
        atraso = (
            (hoy - orden.fecha_entrega).days
            if orden.fecha_entrega and orden.fecha_entrega < hoy
            else 0
        )
        if atraso:
            atrasadas.add(orden.pk)
        for ln in orden.lineas.all():
            if ln.pendiente <= 0:
                continue
            valor = (
                ln.pendiente * _neto(ln.precio_unitario, ln.tasa, orden.precios_incluyen_igv)
            ).quantize(DOS)
            reporte.pendientes.append(
                {
                    "orden": orden.pk,
                    "codigo": orden.codigo,
                    "fecha": orden.fecha_emision,
                    "entrega": orden.fecha_entrega,
                    "dias_atraso": atraso,
                    "proveedor": orden.proveedor.nombre,
                    "almacen": orden.almacen.nombre,
                    "producto_codigo": ln.producto.codigo,
                    "producto": ln.producto.nombre,
                    "unidad": ln.unidad,
                    "pedido": ln.cantidad,
                    "recibido": ln.cantidad_recibida,
                    "pendiente": ln.pendiente,
                    "moneda": orden.moneda,
                    "valor": valor,
                }
            )
            reporte.valor_pendiente[orden.moneda] = (
                reporte.valor_pendiente.get(orden.moneda, CERO) + valor
            )
    reporte.atrasadas = len(atrasadas)
    # Primero lo más atrasado; a igual atraso, lo que se espera antes.
    reporte.pendientes.sort(
        key=lambda f: (-f["dias_atraso"], f["entrega"] or date.max, f["codigo"], f["producto"])
    )


def _cumplimiento(empresa: Empresa, desde: date, hasta: date, reporte: ReporteOrdenes) -> None:
    ordenes = list(
        OrdenCompra.objects.filter(
            empresa=empresa,
            estado__in=CON_ENTREGA,
            fecha_emision__gte=desde,
            fecha_emision__lte=hasta,
        )
        .select_related("proveedor")
        .prefetch_related("lineas")
    )
    ultimas = dict(
        Compra.objects.filter(orden__in=[o.pk for o in ordenes], estado=Compra.Estado.EMITIDO)
        .values_list("orden_id")
        .annotate(ultima=Max("fecha_emision"))
    )
    filas: dict[tuple[int, str], dict] = {}
    for orden in ordenes:
        f = filas.setdefault(
            (orden.proveedor_id, orden.moneda),
            {
                "proveedor": orden.proveedor.nombre,
                "tipo_documento": orden.proveedor.tipo_documento,
                "documento": orden.proveedor.numero_documento,
                "moneda": orden.moneda,
                "ordenes": 0,
                "sin_recibir": 0,
                "parciales": 0,
                "recibidas": 0,
                "cerradas": 0,
                "pedido": CERO,
                "recibido": CERO,
                "_dias": [],
                "a_tiempo": 0,
                "con_fecha": 0,
            },
        )
        f["ordenes"] += 1
        f[
            {
                Estado.EMITIDA: "sin_recibir",
                Estado.PARCIAL: "parciales",
                Estado.RECIBIDA: "recibidas",
                Estado.CERRADA: "cerradas",
            }[orden.estado]
        ] += 1
        for ln in orden.lineas.all():
            precio = _neto(ln.precio_unitario, ln.tasa, orden.precios_incluyen_igv)
            f["pedido"] += ln.cantidad * precio
            f["recibido"] += min(ln.cantidad_recibida, ln.cantidad) * precio
        ultima = ultimas.get(orden.pk)
        if ultima is not None:
            f["_dias"].append((ultima - orden.fecha_emision).days)
        if orden.estado == Estado.RECIBIDA and orden.fecha_entrega and ultima is not None:
            f["con_fecha"] += 1
            f["a_tiempo"] += int(ultima <= orden.fecha_entrega)
    for f in filas.values():
        f["pedido"] = f["pedido"].quantize(DOS)
        f["recibido"] = f["recibido"].quantize(DOS)
        f["cumplimiento"] = (
            (f["recibido"] / f["pedido"] * CIEN).quantize(DOS) if f["pedido"] else CERO
        )
        dias = f.pop("_dias")
        f["dias_promedio"] = (
            (Decimal(sum(dias)) / len(dias)).quantize(Decimal("0.1")) if dias else None
        )
    reporte.cumplimiento = sorted(filas.values(), key=lambda f: (f["proveedor"], f["moneda"]))


def _diferencias(empresa: Empresa, desde: date, hasta: date, reporte: ReporteOrdenes) -> None:
    lineas = (
        LineaCompra.objects.filter(
            compra__empresa=empresa,
            compra__estado=Compra.Estado.EMITIDO,
            compra__fecha_emision__gte=desde,
            compra__fecha_emision__lte=hasta,
            linea_orden__isnull=False,
        )
        .select_related("compra__proveedor", "compra__orden", "linea_orden", "producto")
        .order_by("compra__fecha_emision", "compra__numero", "orden")
    )
    for ln in lineas:
        reporte.lineas_comparadas += 1
        compra, orden = ln.compra, ln.compra.orden
        facturado = _neto(ln.precio_unitario, ln.tasa, compra.precios_incluyen_igv)
        pactado = _neto(
            ln.linea_orden.precio_unitario, ln.linea_orden.tasa, orden.precios_incluyen_igv
        )
        diferencia = (facturado - pactado).quantize(CUATRO)
        if diferencia == 0:
            continue
        impacto = (diferencia * ln.cantidad).quantize(DOS)
        reporte.diferencias.append(
            {
                "fecha": compra.fecha_emision,
                "compra": compra.numero,
                "comprobante": compra.comprobante,
                "orden": orden.pk,
                "codigo": orden.codigo,
                "proveedor": compra.proveedor.nombre,
                "producto_codigo": ln.producto.codigo,
                "producto": ln.producto.nombre,
                "cantidad": ln.cantidad,
                "moneda": compra.moneda,
                "precio_pactado": pactado.quantize(CUATRO),
                "precio_facturado": facturado.quantize(CUATRO),
                "diferencia": diferencia,
                "porcentaje": (diferencia / pactado * CIEN).quantize(DOS) if pactado else None,
                "impacto": impacto,
            }
        )
        reporte.impacto[compra.moneda] = reporte.impacto.get(compra.moneda, CERO) + impacto


def reporte_de_ordenes(empresa: Empresa, desde: date, hasta: date) -> ReporteOrdenes:
    reporte = ReporteOrdenes()
    _pendientes(empresa, timezone.localdate(), reporte)
    _cumplimiento(empresa, desde, hasta, reporte)
    _diferencias(empresa, desde, hasta, reporte)
    return reporte


# ---------------------------------------------------------------------------
# Vista previa
# ---------------------------------------------------------------------------
def _texto(fila: dict, campos: tuple[str, ...], formato: str = "{:.2f}") -> dict:
    return {**fila, **{k: (None if fila[k] is None else formato.format(fila[k])) for k in campos}}


def vista_ordenes(reporte: ReporteOrdenes) -> dict:
    """Datos para mostrar en pantalla: el cumplimiento completo y las primeras filas del resto."""

    def fecha(f: dict, *campos: str) -> dict:
        return {**f, **{c: f[c].isoformat() if f[c] else None for c in campos}}

    return {
        "pendientes": {
            "total_filas": len(reporte.pendientes),
            "truncado": len(reporte.pendientes) > MAX_FILAS_VISTA,
            "atrasadas": reporte.atrasadas,
            "valor": {m: f"{v:.2f}" for m, v in sorted(reporte.valor_pendiente.items())},
            "filas": [
                fecha(_texto(f, ("valor",)), "fecha", "entrega")
                | {k: f"{f[k]:.3f}" for k in ("pedido", "recibido", "pendiente")}
                for f in reporte.pendientes[:MAX_FILAS_VISTA]
            ],
        },
        "cumplimiento": [
            _texto(f, ("pedido", "recibido", "cumplimiento"))
            | {"dias_promedio": None if f["dias_promedio"] is None else f"{f['dias_promedio']:.1f}"}
            for f in reporte.cumplimiento
        ],
        "diferencias": {
            "total_filas": len(reporte.diferencias),
            "truncado": len(reporte.diferencias) > MAX_FILAS_VISTA,
            "lineas_comparadas": reporte.lineas_comparadas,
            "impacto": {m: f"{v:.2f}" for m, v in sorted(reporte.impacto.items())},
            "filas": [
                fecha(_texto(f, ("impacto", "porcentaje")), "fecha")
                | {k: f"{f[k]:f}" for k in ("precio_pactado", "precio_facturado", "diferencia")}
                | {"cantidad": f"{f['cantidad']:.3f}"}
                for f in reporte.diferencias[:MAX_FILAS_VISTA]
            ],
        },
    }


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def libro_ordenes(empresa: Empresa, reporte: ReporteOrdenes, desde: date, hasta: date) -> bytes:
    libro = Workbook()

    def hoja(ws, titulo: str, subtitulo: str, columnas: list[str], anchos: list[int]) -> int:
        _poner(ws, 1, 1, titulo).font = Font(bold=True, size=13)
        _poner(ws, 2, 1, subtitulo)
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

    def filas(ws, desde_fila: int, datos: list[list[tuple]]) -> int:
        fila = desde_fila
        for valores in datos:
            for columna, (valor, formato) in enumerate(valores, start=1):
                _poner(ws, fila, columna, valor, formato).border = BORDE
            fila += 1
        return fila

    def total(
        ws, fila: int, texto: str, columna_texto: int, columna_valor: int, valor: Decimal
    ) -> None:
        _poner(ws, fila, columna_texto, texto, negrita=True)
        celda = _poner(ws, fila, columna_valor, valor, DINERO, negrita=True)
        celda.fill, celda.border = FONDO_TOTAL, BORDE

    hoy = timezone.localdate()
    ws = libro.active
    ws.title = "Pendientes de recibir"
    fila = filas(
        ws,
        hoja(
            ws,
            "ÓRDENES DE COMPRA · PENDIENTES DE RECIBIR",
            f"Al {hoy:%d/%m/%Y}",
            [
                "Orden",
                "Fecha",
                "Entrega esperada",
                "Días de atraso",
                "Proveedor",
                "Almacén",
                "Código",
                "Producto",
                "Unidad",
                "Pedido",
                "Recibido",
                "Falta",
                "Moneda",
                "Valor sin IGV",
            ],
            [12, 12, 14, 10, 36, 18, 10, 36, 10, 11, 11, 11, 8, 14],
        ),
        [
            [
                (f["codigo"], None),
                (f["fecha"], FECHA),
                (f["entrega"], FECHA),
                (f["dias_atraso"], None),
                (f["proveedor"], None),
                (f["almacen"], None),
                (f["producto_codigo"], None),
                (f["producto"], None),
                (f["unidad"], None),
                (f["pedido"], "#,##0.###"),
                (f["recibido"], "#,##0.###"),
                (f["pendiente"], "#,##0.###"),
                (f["moneda"], None),
                (f["valor"], DINERO),
            ]
            for f in reporte.pendientes
        ],
    )
    for moneda, valor in sorted(reporte.valor_pendiente.items()):
        total(ws, fila, f"VALOR PENDIENTE EN {moneda}", 8, 14, valor)
        fila += 1

    ws = libro.create_sheet("Cumplimiento por proveedor")
    filas(
        ws,
        hoja(
            ws,
            "ÓRDENES DE COMPRA · CUMPLIMIENTO POR PROVEEDOR",
            f"Órdenes del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
            [
                "Tipo doc.",
                "N° documento",
                "Proveedor",
                "Moneda",
                "Órdenes",
                "Sin recibir",
                "Recibidas en parte",
                "Recibidas",
                "Cerradas con faltante",
                "Pedido sin IGV",
                "Recibido sin IGV",
                "% recibido",
                "Días promedio de entrega",
                "Entregas a tiempo",
                "Con fecha pactada",
            ],
            [9, 14, 36, 8, 9, 10, 12, 10, 13, 15, 15, 10, 13, 11, 11],
        ),
        [
            [
                (f["tipo_documento"], None),
                (f["documento"], None),
                (f["proveedor"], None),
                (f["moneda"], None),
                (f["ordenes"], None),
                (f["sin_recibir"], None),
                (f["parciales"], None),
                (f["recibidas"], None),
                (f["cerradas"], None),
                (f["pedido"], DINERO),
                (f["recibido"], DINERO),
                (f["cumplimiento"], DINERO),
                (f["dias_promedio"], "0.0"),
                (f["a_tiempo"], None),
                (f["con_fecha"], None),
            ]
            for f in reporte.cumplimiento
        ],
    )

    ws = libro.create_sheet("Diferencias de precio")
    fila = filas(
        ws,
        hoja(
            ws,
            "ÓRDENES DE COMPRA · DIFERENCIAS DE PRECIO",
            (
                f"Compras del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} "
                f"· {reporte.lineas_comparadas} líneas comparadas"
            ),
            [
                "Fecha",
                "Compra",
                "Comprobante",
                "Orden",
                "Proveedor",
                "Código",
                "Producto",
                "Cantidad",
                "Moneda",
                "Precio pactado",
                "Precio facturado",
                "Diferencia (sin IGV)",
                "% diferencia",
                "Efecto",
            ],
            [12, 10, 16, 12, 36, 10, 36, 11, 8, 14, 14, 14, 11, 14],
        ),
        [
            [
                (f["fecha"], FECHA),
                (f["compra"], None),
                (f["comprobante"], None),
                (f["codigo"], None),
                (f["proveedor"], None),
                (f["producto_codigo"], None),
                (f["producto"], None),
                (f["cantidad"], "#,##0.###"),
                (f["moneda"], None),
                (f["precio_pactado"], "#,##0.0000"),
                (f["precio_facturado"], "#,##0.0000"),
                (f["diferencia"], "#,##0.0000"),
                (f["porcentaje"], DINERO),
                (f["impacto"], DINERO),
            ]
            for f in reporte.diferencias
        ],
    )
    for moneda, valor in sorted(reporte.impacto.items()):
        total(ws, fila, f"EFECTO TOTAL EN {moneda}", 7, 14, valor)
        fila += 1

    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def nombre_archivo_ordenes(empresa: Empresa, desde: date, hasta: date) -> str:
    limpio = re.sub(
        r"[^A-Za-z0-9_-]", "", f"ordenes-compra_{empresa.ruc}_{desde:%Y%m%d}_{hasta:%Y%m%d}"
    )
    return f"{limpio}.xlsx"
