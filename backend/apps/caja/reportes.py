"""Reportes de caja y bancos: libro, saldos a una fecha, flujo de caja y resumen por concepto.

Todo sale del libro de movimientos (solo los vigentes: lo anulado no cuenta). Soles y dólares
nunca se suman: cada cuenta y cada total lleva su moneda. Los textos que vienen de la base se
escriben siempre como texto en el Excel, nunca como fórmula.
"""

import calendar
import io
import re
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Case, CharField, Count, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa

from .exceptions import MovimientoInvalido
from .models import MovimientoCaja, TipoMovimiento

CERO = Decimal("0")
MAX_DIAS_FLUJO = 732
MAX_MESES_PROYECCION = 12
_DINERO = DecimalField(max_digits=16, decimal_places=2)
# Pasar plata de una cuenta propia a otra no es entrar ni salir dinero de la empresa.
INTERNOS = ("TRANSFERENCIA_SALIDA", "TRANSFERENCIA_ENTRADA")


def _firmado():
    return Case(
        When(tipo=TipoMovimiento.INGRESO, then=F("monto")),
        default=-F("monto"),
        output_field=_DINERO,
    )


def _vigentes(empresa: Empresa):
    return MovimientoCaja.objects.filter(empresa=empresa, estado=MovimientoCaja.Estado.EMITIDO)


def _cuentas(empresa: Empresa, tipos=None):
    cuentas = CuentaFinanciera.objects.filter(empresa=empresa).select_related("sucursal")
    if tipos is not None:
        cuentas = cuentas.filter(tipo__in=tipos)
    return cuentas.order_by("tipo", "nombre")


def periodo(anio: int, mes: int) -> tuple[date, date]:
    if not (2000 <= anio <= 2100) or not (1 <= mes <= 12):
        raise MovimientoInvalido("Indique un año y un mes válidos.")
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def validar_rango(desde: date | None, hasta: date | None) -> tuple[date, date]:
    if desde is None or hasta is None:
        raise MovimientoInvalido("Indique el rango de fechas (desde y hasta).")
    if desde > hasta:
        raise MovimientoInvalido("La fecha «desde» no puede ser posterior a «hasta».")
    if (hasta - desde).days > MAX_DIAS_FLUJO:
        raise MovimientoInvalido("El rango no puede pasar de dos años.")
    return desde, hasta


# ---------------------------------------------------------------------------
# Saldos a una fecha
# ---------------------------------------------------------------------------
def saldos_a_fecha(empresa: Empresa, fecha: date) -> dict:
    """Cuánto había en cada caja y cuenta al cierre de ``fecha`` y el total por moneda."""
    netos = {
        f["cuenta_id"]: f["neto"] or CERO
        for f in _vigentes(empresa)
        .filter(fecha__lte=fecha)
        .values("cuenta_id")
        .annotate(neto=Sum(_firmado()))
    }
    filas, totales = [], {}
    for cuenta in _cuentas(empresa):
        # El saldo con que se abrió la cuenta cuenta desde su fecha, no antes.
        inicial = (
            cuenta.saldo_inicial
            if cuenta.fecha_saldo_inicial is None or cuenta.fecha_saldo_inicial <= fecha
            else CERO
        )
        saldo = inicial + netos.get(cuenta.pk, CERO)
        if cuenta.estado != EstadoRegistro.ACTIVO and saldo == 0 and cuenta.pk not in netos:
            continue
        filas.append(
            {
                "cuenta": cuenta.pk,
                "nombre": cuenta.nombre,
                "tipo": cuenta.tipo,
                "tipo_nombre": cuenta.get_tipo_display(),
                "moneda": cuenta.moneda,
                "sucursal": cuenta.sucursal.nombre if cuenta.sucursal else "",
                "estado": cuenta.estado,
                "saldo": saldo,
            }
        )
        totales[cuenta.moneda] = totales.get(cuenta.moneda, CERO) + saldo
    return {
        "fecha": fecha,
        "cuentas": filas,
        "totales": [{"moneda": m, "saldo": s} for m, s in sorted(totales.items())],
    }


# ---------------------------------------------------------------------------
# Libro Caja y Bancos
# ---------------------------------------------------------------------------
def libro(empresa: Empresa, anio: int, mes: int) -> dict:
    """El Libro Caja y Bancos del mes: efectivo (formato 1.1) y cuentas de banco (formato 1.2)."""
    inicio, fin = periodo(anio, mes)
    previos = {
        f["cuenta_id"]: f["neto"] or CERO
        for f in _vigentes(empresa)
        .filter(fecha__lt=inicio)
        .values("cuenta_id")
        .annotate(neto=Sum(_firmado()))
    }
    del_mes: dict[int, list[MovimientoCaja]] = {}
    movimientos = (
        _vigentes(empresa)
        .filter(fecha__gte=inicio, fecha__lte=fin)
        .select_related("concepto")
        .order_by("fecha", "numero")
    )
    for m in movimientos:
        del_mes.setdefault(m.cuenta_id, []).append(m)

    secciones = {"efectivo": [], "bancos": []}
    for cuenta in _cuentas(empresa):
        filas_cuenta = del_mes.get(cuenta.pk, [])
        inicial = (
            cuenta.saldo_inicial
            if cuenta.fecha_saldo_inicial is None or cuenta.fecha_saldo_inicial < inicio
            else CERO
        ) + previos.get(cuenta.pk, CERO)
        if not filas_cuenta and inicial == 0 and cuenta.estado != EstadoRegistro.ACTIVO:
            continue
        saldo = inicial
        # Un saldo inicial con fecha dentro del mes se asienta como primera línea del libro.
        apertura = (
            cuenta.fecha_saldo_inicial
            if cuenta.saldo_inicial
            and cuenta.fecha_saldo_inicial
            and inicio <= cuenta.fecha_saldo_inicial <= fin
            else None
        )
        lineas = []
        if apertura:
            saldo += cuenta.saldo_inicial
            lineas.append(
                {
                    "numero": None,
                    "fecha": apertura,
                    "concepto": "Saldo inicial",
                    "glosa": "",
                    "referencia": "",
                    "origen": "APERTURA",
                    "debe": cuenta.saldo_inicial,
                    "haber": CERO,
                    "saldo": saldo,
                }
            )
        for m in filas_cuenta:
            saldo += m.monto if m.tipo == TipoMovimiento.INGRESO else -m.monto
            lineas.append(
                {
                    "numero": m.numero,
                    "fecha": m.fecha,
                    "concepto": m.concepto.nombre,
                    "glosa": m.glosa,
                    "referencia": m.referencia,
                    "origen": m.origen_tipo,
                    "debe": m.monto if m.tipo == TipoMovimiento.INGRESO else CERO,
                    "haber": m.monto if m.tipo == TipoMovimiento.EGRESO else CERO,
                    "saldo": saldo,
                    "movimiento": m.pk,
                }
            )
        seccion = {
            "cuenta": cuenta.pk,
            "nombre": cuenta.nombre,
            "tipo": cuenta.tipo,
            "tipo_nombre": cuenta.get_tipo_display(),
            "moneda": cuenta.moneda,
            "banco": cuenta.banco,
            "numero_cuenta": cuenta.numero_cuenta,
            "cuenta_contable": cuenta.cuenta_contable,
            "codigo_entidad": cuenta.codigo_entidad,
            "saldo_inicial": inicial,
            "lineas": lineas,
            "total_debe": sum((x["debe"] for x in lineas), CERO),
            "total_haber": sum((x["haber"] for x in lineas), CERO),
            "saldo_final": saldo,
        }
        clave = "efectivo" if cuenta.tipo == CuentaFinanciera.Tipo.CAJA else "bancos"
        secciones[clave].append(seccion)
    return {
        "anio": anio,
        "mes": mes,
        "desde": inicio,
        "hasta": fin,
        "efectivo": secciones["efectivo"],
        "bancos": secciones["bancos"],
    }


# ---------------------------------------------------------------------------
# Flujo de caja
# ---------------------------------------------------------------------------
def _clave_periodo(fecha: date, agrupar: str) -> str:
    return f"{fecha:%Y-%m}" if agrupar == "mes" else fecha.isoformat()


def flujo_real(empresa: Empresa, desde: date, hasta: date, agrupar: str = "mes") -> dict:
    """Lo que entró y salió de la empresa en el rango, por periodo y moneda.

    No incluye los pasos entre cuentas propias (transferencias, depósitos, retiros): mover plata de
    un bolsillo a otro no es entrar ni salir dinero. Se muestran aparte.
    """
    if agrupar not in ("mes", "dia"):
        raise MovimientoInvalido("Agrupe por mes o por día.")
    desde, hasta = validar_rango(desde, hasta)
    base = _vigentes(empresa).filter(fecha__gte=desde, fecha__lte=hasta)
    externos = base.exclude(concepto__codigo__in=INTERNOS).select_related("cuenta")
    por_periodo: dict[tuple[str, str], dict] = {}
    for m in externos.only("fecha", "tipo", "monto", "cuenta__moneda"):
        fila = por_periodo.setdefault(
            (_clave_periodo(m.fecha, agrupar), m.cuenta.moneda),
            {"ingresos": CERO, "egresos": CERO},
        )
        fila["ingresos" if m.tipo == TipoMovimiento.INGRESO else "egresos"] += m.monto
    filas = [
        {
            "periodo": p,
            "moneda": moneda,
            "ingresos": v["ingresos"],
            "egresos": v["egresos"],
            "neto": v["ingresos"] - v["egresos"],
        }
        for (p, moneda), v in sorted(por_periodo.items())
    ]
    totales: dict[str, dict] = {}
    for f in filas:
        t = totales.setdefault(
            f["moneda"], {"moneda": f["moneda"], "ingresos": CERO, "egresos": CERO}
        )
        t["ingresos"] += f["ingresos"]
        t["egresos"] += f["egresos"]
    for t in totales.values():
        t["neto"] = t["ingresos"] - t["egresos"]
    return {
        "desde": desde,
        "hasta": hasta,
        "agrupar": agrupar,
        "filas": filas,
        "totales": sorted(totales.values(), key=lambda t: t["moneda"]),
        "saldo_inicial": [
            {"moneda": s["moneda"], "saldo": s["saldo"]}
            for s in saldos_a_fecha(empresa, desde - timedelta(days=1))["totales"]
        ],
        "saldo_final": [
            {"moneda": s["moneda"], "saldo": s["saldo"]}
            for s in saldos_a_fecha(empresa, hasta)["totales"]
        ],
    }


def flujo_proyectado(empresa: Empresa, hoy: date, meses: int = 3) -> dict:
    """Lo que hay que pagar en los próximos meses, frente al dinero de hoy.

    Se toman las cuotas pendientes de compras a crédito y los gastos por pagar (y lo vencido
    aparte). Todavía no hay cuentas por cobrar: cuando existan, sus cobros se sumarán aquí.
    """
    # caja no depende de compras ni de gastos salvo aquí, para proyectar lo que se debe
    from apps.compras.models import CuotaCompra
    from apps.gastos.consultas import por_pagar

    if not (1 <= meses <= MAX_MESES_PROYECCION):
        raise MovimientoInvalido(f"Proyecte de 1 a {MAX_MESES_PROYECCION} meses.")
    limite = _sumar_meses(hoy.replace(day=1), meses + 1) - timedelta(days=1)
    cuotas = CuotaCompra.objects.filter(
        empresa=empresa,
        compra__estado="EMITIDO",
        pagado__lt=F("monto"),
        fecha_vencimiento__lte=limite,
    ).select_related("compra")
    por_periodo: dict[tuple[str, str], Decimal] = {}
    de_gastos: dict[tuple[str, str], Decimal] = {}

    def etiqueta_de(fecha: date) -> str:
        return "vencido" if fecha < hoy else f"{fecha:%Y-%m}"

    for c in cuotas:
        clave = (etiqueta_de(c.fecha_vencimiento), c.compra.moneda)
        por_periodo[clave] = por_periodo.get(clave, CERO) + (c.monto - c.pagado)
    for g in por_pagar(empresa, limite):
        clave = (etiqueta_de(g.fecha_vencimiento), g.moneda)
        saldo = g.total - g.pagado_calc
        por_periodo[clave] = por_periodo.get(clave, CERO) + saldo
        de_gastos[clave] = de_gastos.get(clave, CERO) + saldo
    filas = [
        {
            "periodo": p,
            "moneda": moneda,
            "por_pagar": monto,
            "de_gastos": de_gastos.get((p, moneda), CERO),
        }
        for (p, moneda), monto in sorted(
            por_periodo.items(), key=lambda x: (x[0][0] != "vencido", x)
        )
    ]
    hoy_saldos = saldos_a_fecha(empresa, hoy)["totales"]
    acumulado = {t["moneda"]: t["saldo"] for t in hoy_saldos}
    proyeccion = []
    for fila in filas:
        acumulado[fila["moneda"]] = acumulado.get(fila["moneda"], CERO) - fila["por_pagar"]
        proyeccion.append({**fila, "saldo_proyectado": acumulado[fila["moneda"]]})
    return {
        "hoy": hoy,
        "meses": meses,
        "saldo_hoy": [{"moneda": t["moneda"], "saldo": t["saldo"]} for t in hoy_saldos],
        "filas": proyeccion,
    }


def _sumar_meses(inicio: date, meses: int) -> date:
    indice = inicio.year * 12 + (inicio.month - 1) + meses
    return date(indice // 12, indice % 12 + 1, 1)


# ---------------------------------------------------------------------------
# Resumen por concepto
# ---------------------------------------------------------------------------
def por_concepto(empresa: Empresa, desde: date, hasta: date) -> dict:
    """Cuánto entró y salió por cada concepto en el rango (sin los pasos entre cuentas propias)."""
    desde, hasta = validar_rango(desde, hasta)
    filas = (
        _vigentes(empresa)
        .filter(fecha__gte=desde, fecha__lte=hasta)
        .exclude(concepto__codigo__in=INTERNOS)
        .values("concepto__nombre", "tipo", "cuenta__moneda")
        .annotate(total=Sum("monto"))
        .order_by("cuenta__moneda", "tipo", "-total", "concepto__nombre")
    )
    resultado = [
        {
            "concepto": f["concepto__nombre"],
            "tipo": f["tipo"],
            "moneda": f["cuenta__moneda"],
            "total": f["total"],
        }
        for f in filas
    ]
    totales: dict[tuple[str, str], Decimal] = {}
    for f in resultado:
        totales[(f["moneda"], f["tipo"])] = totales.get((f["moneda"], f["tipo"]), CERO) + f["total"]
    return {
        "desde": desde,
        "hasta": hasta,
        "filas": resultado,
        "totales": [{"moneda": m, "tipo": t, "total": v} for (m, t), v in sorted(totales.items())],
    }


def por_medio(empresa: Empresa, desde: date, hasta: date) -> dict:
    """Cuánto entró y salió por cada método de pago (efectivo, transferencia, Yape…) en el rango.

    Sin método indicado, el movimiento cuenta según su cuenta: caja = efectivo, banco = banco,
    billetera = billetera digital. No incluye los pasos entre cuentas propias.
    """
    desde, hasta = validar_rango(desde, hasta)
    segun_cuenta = Case(
        When(cuenta__tipo="CAJA", then=Value("Efectivo")),
        When(cuenta__tipo="BANCO", then=Value("Banco")),
        default=Value("Billetera digital"),
        output_field=CharField(),
    )
    filas = (
        _vigentes(empresa)
        .filter(fecha__gte=desde, fecha__lte=hasta)
        .exclude(concepto__codigo__in=INTERNOS)
        .annotate(medio=Coalesce("medio_pago__nombre", segun_cuenta))
        .values("medio", "cuenta__moneda", "tipo")
        .annotate(total=Sum("monto"), cantidad=Count("id"))
    )
    medios: dict[tuple[str, str], dict] = {}
    for f in filas:
        clave = (f["cuenta__moneda"], f["medio"])
        fila = medios.setdefault(
            clave,
            {
                "medio": f["medio"],
                "moneda": f["cuenta__moneda"],
                "ingresos": CERO,
                "egresos": CERO,
                "cantidad": 0,
            },
        )
        fila["ingresos" if f["tipo"] == TipoMovimiento.INGRESO else "egresos"] += f["total"]
        fila["cantidad"] += f["cantidad"]
    resultado = sorted(
        medios.values(), key=lambda x: (x["moneda"], -(x["ingresos"] + x["egresos"]))
    )
    for fila in resultado:
        fila["neto"] = fila["ingresos"] - fila["egresos"]
    return {"desde": desde, "hasta": hasta, "filas": resultado}


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
DINERO = "#,##0.00"
FECHA = "dd/mm/yyyy"
NEGRITA = Font(bold=True)
FONDO_CABECERA = PatternFill("solid", fgColor="D9DEE8")
FONDO_TOTAL = PatternFill("solid", fgColor="EEF1F6")
BORDE = Border(*(Side(style="thin", color="9AA3B2"),) * 4)
CENTRADO = Alignment(horizontal="center", vertical="center", wrap_text=True)
SIMBOLO = {"PEN": "S/", "USD": "US$"}


def _poner(ws, fila, columna, valor, formato=None, *, negrita=False):
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


def _cabecera(ws, titulo: str, empresa: Empresa, subtitulo: str) -> int:
    _poner(ws, 1, 1, titulo).font = Font(bold=True, size=13)
    _poner(ws, 2, 1, subtitulo)
    _poner(ws, 3, 1, "RUC", negrita=True)
    _poner(ws, 3, 3, empresa.ruc)
    _poner(ws, 4, 1, "Razón social", negrita=True)
    _poner(ws, 4, 3, empresa.razon_social)
    return 6


def _titulos(ws, fila: int, titulos: list[str]) -> None:
    for i, titulo in enumerate(titulos, start=1):
        celda = _poner(ws, fila, i, titulo, negrita=True)
        celda.fill, celda.border, celda.alignment = FONDO_CABECERA, BORDE, CENTRADO


def _anchos(ws, anchos: list[int]) -> None:
    for i, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = ancho


def _bytes(libro: Workbook) -> bytes:
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def libro_excel(empresa: Empresa, datos: dict) -> bytes:
    """Libro Caja y Bancos del mes: hoja 1.1 (efectivo) y hoja 1.2 (cuentas de banco)."""
    libro_xlsx = Workbook()
    hojas = (
        (
            "1.1 Efectivo",
            "LIBRO CAJA Y BANCOS - FORMATO 1.1: MOVIMIENTO DEL EFECTIVO",
            datos["efectivo"],
        ),
        (
            "1.2 Bancos",
            "LIBRO CAJA Y BANCOS - FORMATO 1.2: MOVIMIENTO DE LA CUENTA CORRIENTE",
            datos["bancos"],
        ),
    )
    subtitulo = f"Periodo: {datos['mes']:02d}/{datos['anio']}"
    for indice, (nombre, titulo, secciones) in enumerate(hojas):
        ws = libro_xlsx.active if indice == 0 else libro_xlsx.create_sheet()
        ws.title = nombre
        fila = _cabecera(ws, titulo, empresa, subtitulo)
        if not secciones:
            _poner(ws, fila, 1, "Sin cuentas ni movimientos en este periodo.")
        for s in secciones:
            detalle = f"{s['nombre']} ({SIMBOLO[s['moneda']]})"
            if s["banco"] or s["numero_cuenta"]:
                detalle += f" · {s['banco']} {s['numero_cuenta']}".rstrip()
            _poner(ws, fila, 1, detalle, negrita=True)
            fila += 1
            _titulos(
                ws,
                fila,
                [
                    "N°",
                    "Fecha",
                    "Concepto",
                    "Descripción",
                    "N° operación",
                    "Debe (ingresos)",
                    "Haber (egresos)",
                    "Saldo",
                ],
            )
            fila += 1
            _poner(ws, fila, 4, "Saldo inicial", negrita=True)
            _poner(ws, fila, 8, s["saldo_inicial"], DINERO, negrita=True).border = BORDE
            fila += 1
            for linea in s["lineas"]:
                valores = [
                    (linea["numero"], None),
                    (linea["fecha"], FECHA),
                    (linea["concepto"], None),
                    (linea["glosa"], None),
                    (linea["referencia"], None),
                    (linea["debe"], DINERO),
                    (linea["haber"], DINERO),
                    (linea["saldo"], DINERO),
                ]
                for columna, (valor, formato) in enumerate(valores, start=1):
                    if valor is None:
                        valor = ""
                    _poner(ws, fila, columna, valor, formato).border = BORDE
                fila += 1
            _poner(ws, fila, 4, "TOTALES", negrita=True)
            for columna, valor in (
                (6, s["total_debe"]),
                (7, s["total_haber"]),
                (8, s["saldo_final"]),
            ):
                celda = _poner(ws, fila, columna, valor, DINERO, negrita=True)
                celda.fill, celda.border = FONDO_TOTAL, BORDE
            fila += 3
        _anchos(ws, [9, 12, 26, 40, 16, 16, 16, 16])
        ws.page_setup.orientation = "landscape"
    return _bytes(libro_xlsx)


def tabla_excel(
    empresa: Empresa,
    *,
    hoja: str,
    titulo: str,
    subtitulo: str,
    titulos: list[str],
    filas: list[list[tuple]],
    totales: list[list[tuple]] | None = None,
    anchos: list[int] | None = None,
) -> bytes:
    """Excel de una sola tabla. Cada celda es ``(valor, formato)``."""
    libro_xlsx = Workbook()
    ws = libro_xlsx.active
    ws.title = hoja
    fila = _cabecera(ws, titulo, empresa, subtitulo)
    _titulos(ws, fila, titulos)
    fila += 1
    for celdas in filas:
        for columna, (valor, formato) in enumerate(celdas, start=1):
            _poner(ws, fila, columna, "" if valor is None else valor, formato).border = BORDE
        fila += 1
    for celdas in totales or []:
        for columna, (valor, formato) in enumerate(celdas, start=1):
            c = _poner(ws, fila, columna, "" if valor is None else valor, formato, negrita=True)
            c.fill, c.border = FONDO_TOTAL, BORDE
        fila += 1
    _anchos(ws, anchos or [18] * len(titulos))
    ws.freeze_panes = ws.cell(row=7, column=1)
    return _bytes(libro_xlsx)


def nombre_archivo(prefijo: str, empresa: Empresa, sufijo: str, extension: str = "xlsx") -> str:
    """Nombre de archivo seguro: solo letras, números y guiones."""
    limpio = re.sub(r"[^A-Za-z0-9_-]", "", f"{prefijo}_{empresa.ruc}_{sufijo}")
    return f"{limpio}.{extension}"


def saldos_excel(empresa: Empresa, datos: dict) -> bytes:
    filas = [
        [
            (c["nombre"], None),
            (c["tipo_nombre"], None),
            (c["sucursal"], None),
            (SIMBOLO[c["moneda"]], None),
            (c["saldo"], DINERO),
        ]
        for c in datos["cuentas"]
    ]
    totales = [
        [
            ("TOTAL", None),
            ("", None),
            ("", None),
            (SIMBOLO[t["moneda"]], None),
            (t["saldo"], DINERO),
        ]
        for t in datos["totales"]
    ]
    return tabla_excel(
        empresa,
        hoja="Saldos",
        titulo="SALDOS DE CAJAS Y CUENTAS",
        subtitulo=f"Al {datos['fecha']:%d/%m/%Y}",
        titulos=["Caja o cuenta", "Tipo", "Sucursal", "Moneda", "Saldo"],
        filas=filas,
        totales=totales,
        anchos=[32, 22, 20, 9, 16],
    )


def flujo_excel(empresa: Empresa, datos: dict) -> bytes:
    filas = [
        [
            (f["periodo"], None),
            (SIMBOLO[f["moneda"]], None),
            (f["ingresos"], DINERO),
            (f["egresos"], DINERO),
            (f["neto"], DINERO),
        ]
        for f in datos["filas"]
    ]
    totales = [
        [
            ("TOTAL", None),
            (SIMBOLO[t["moneda"]], None),
            (t["ingresos"], DINERO),
            (t["egresos"], DINERO),
            (t["neto"], DINERO),
        ]
        for t in datos["totales"]
    ]
    return tabla_excel(
        empresa,
        hoja="Flujo de caja",
        titulo="FLUJO DE CAJA",
        subtitulo=(
            f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} "
            "(sin pasos entre cuentas propias)"
        ),
        titulos=["Periodo", "Moneda", "Ingresos", "Egresos", "Neto"],
        filas=filas,
        totales=totales,
        anchos=[14, 9, 16, 16, 16],
    )


def conceptos_excel(empresa: Empresa, datos: dict) -> bytes:
    filas = [
        [
            (f["concepto"], None),
            ("Ingreso" if f["tipo"] == TipoMovimiento.INGRESO else "Egreso", None),
            (SIMBOLO[f["moneda"]], None),
            (f["total"], DINERO),
        ]
        for f in datos["filas"]
    ]
    totales = [
        [
            ("TOTAL", None),
            ("Ingresos" if t["tipo"] == TipoMovimiento.INGRESO else "Egresos", None),
            (SIMBOLO[t["moneda"]], None),
            (t["total"], DINERO),
        ]
        for t in datos["totales"]
    ]
    return tabla_excel(
        empresa,
        hoja="Por concepto",
        titulo="MOVIMIENTOS POR CONCEPTO",
        subtitulo=(
            f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} "
            "(sin pasos entre cuentas propias)"
        ),
        titulos=["Concepto", "Tipo", "Moneda", "Total"],
        filas=filas,
        totales=totales,
        anchos=[34, 12, 9, 16],
    )


def medios_excel(empresa: Empresa, datos: dict) -> bytes:
    filas = [
        [
            (f["medio"], None),
            (SIMBOLO[f["moneda"]], None),
            (f["cantidad"], None),
            (f["ingresos"], DINERO),
            (f["egresos"], DINERO),
            (f["neto"], DINERO),
        ]
        for f in datos["filas"]
    ]
    return tabla_excel(
        empresa,
        hoja="Por método",
        titulo="MOVIMIENTOS POR MÉTODO DE PAGO",
        subtitulo=(
            f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} "
            "(sin pasos entre cuentas propias)"
        ),
        titulos=["Método", "Moneda", "Movimientos", "Ingresos", "Egresos", "Neto"],
        filas=filas,
        anchos=[26, 9, 13, 16, 16, 16],
    )
