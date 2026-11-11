"""Reportes de RR.HH. para el contador y la gerencia: se ven en pantalla y se descargan en Excel.

* ``planilla``: la planilla de un mes con una columna por concepto (como la hoja de Excel que
  reemplaza).
* ``plame``: los conceptos de cada trabajador con su código PLAME y la jornada del mes. Es un
  archivo de APOYO para preparar el PLAME: NO es el archivo oficial de la SUNAT (su formato lo arma
  el contador con su programa). Avisa los conceptos que todavía no tienen código PLAME.
* ``t-registro``: los datos de cada trabajador con contrato vigente que se declaran en el T-Registro
  (también de apoyo, sin sueldos ni cuentas).
* ``anual``: el neto de cada mes por trabajador, los totales del año y la renta de 5.ª retenida.

Los textos que vienen de la base se escriben siempre como texto, nunca como fórmula.
"""

import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import (
    ContratoLaboral,
    EstadoContrato,
    EstadoPlanilla,
    Planilla,
    PlanillaConcepto,
    PlanillaTrabajador,
    TipoConcepto,
)

MAX_FILAS_VISTA = 200
CERO = Decimal("0.00")
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
TIPOS = ("planilla", "plame", "t-registro", "anual")
ORDEN_TIPO = {TipoConcepto.INGRESO: 0, TipoConcepto.DESCUENTO: 1, TipoConcepto.APORTE_EMPLEADOR: 2}


class ErrorReporte(ValidationError):
    """No se puede armar el reporte pedido (se muestra al usuario)."""


@dataclass
class Tabla:
    hoja: str
    titulo: str
    columnas: list[tuple[str, str]]  # (título, tipo: texto | dinero | numero | fecha)
    filas: list[list] = field(default_factory=list)
    totales: list | None = None


@dataclass
class Reporte:
    tipo: str
    titulo: str
    subtitulo: str
    archivo: str
    tablas: list[Tabla]
    avisos: list[str] = field(default_factory=list)


def periodo_de(texto: str | None) -> date:
    """«2026-03» → 1 de marzo de 2026."""
    try:
        anio, mes = (texto or "").split("-")
        return date(int(anio), int(mes), 1)
    except (ValueError, TypeError):
        raise ErrorReporte({"periodo": "Indique el mes con el formato AAAA-MM."}) from None


def _planilla(empresa, periodo: date, *, cerrada: bool) -> Planilla:
    planilla = Planilla.objects.filter(empresa=empresa, periodo=periodo).first()
    if planilla is None:
        raise ErrorReporte({"periodo": f"No hay planilla de {periodo:%m/%Y}."})
    if cerrada and planilla.estado != EstadoPlanilla.CERRADA:
        raise ErrorReporte({"periodo": f"La planilla de {periodo:%m/%Y} todavía no está cerrada."})
    return planilla


def _detalles(planilla: Planilla):
    return list(
        PlanillaTrabajador.objects.filter(planilla=planilla)
        .select_related("personal")
        .order_by("personal__apellidos", "personal__nombres", "id")
    )


# ---------------------------------------------------------------------------
# Los reportes
# ---------------------------------------------------------------------------
def planilla_del_mes(empresa, periodo: date) -> Reporte:
    planilla = _planilla(empresa, periodo, cerrada=False)
    detalles = _detalles(planilla)
    montos: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    conceptos: dict[str, tuple[int, int, str, str]] = {}
    for linea in PlanillaConcepto.objects.filter(detalle__planilla=planilla).select_related(
        "concepto"
    ):
        montos[linea.detalle_id][linea.codigo] += linea.monto
        conceptos.setdefault(
            linea.codigo,
            (ORDEN_TIPO.get(linea.tipo, 3), linea.concepto.orden, linea.nombre, linea.tipo),
        )
    ordenados = sorted(conceptos.items(), key=lambda par: par[1][:3])
    columnas = [
        ("Trabajador", "texto"),
        ("Documento", "texto"),
        ("Cargo", "texto"),
        ("Días trabajados", "numero"),
        ("Faltas", "numero"),
    ]
    signo = {"INGRESO": "+", "DESCUENTO": "-"}
    columnas += [
        (f"{datos[2]} ({signo.get(datos[3], 'empresa')})", "dinero") for _, datos in ordenados
    ]
    columnas += [
        ("Total ingresos", "dinero"),
        ("Total descuentos", "dinero"),
        ("Neto a pagar", "dinero"),
    ]
    filas = []
    for d in detalles:
        fila = [
            d.personal.nombre_completo,
            d.personal.numero_documento,
            d.cargo,
            d.dias_laborados,
            d.dias_falta,
        ]
        fila += [montos[d.pk].get(codigo, CERO) for codigo, _ in ordenados]
        fila += [d.total_ingresos, d.total_descuentos, d.neto]
        filas.append(fila)
    totales = ["TOTALES", "", "", "", ""]
    for i in range(5, len(columnas)):
        totales.append(sum((f[i] for f in filas), CERO))
    totales = totales[: len(columnas)]
    estado = "cerrada" if planilla.estado == EstadoPlanilla.CERRADA else "EN REVISIÓN"
    return Reporte(
        tipo="planilla",
        titulo="PLANILLA DE REMUNERACIONES",
        subtitulo=f"{periodo:%m/%Y} · {estado}",
        archivo=f"planilla-{empresa.ruc}-{periodo:%Y-%m}.xlsx",
        tablas=[Tabla("Planilla", "Planilla", columnas, filas, totales)],
        avisos=[]
        if planilla.estado == EstadoPlanilla.CERRADA
        else ["La planilla aún no está cerrada: los montos pueden cambiar."],
    )


def plame_conceptos(empresa, periodo: date) -> Reporte:
    planilla = _planilla(empresa, periodo, cerrada=True)
    detalles = _detalles(planilla)
    lineas = (
        PlanillaConcepto.objects.filter(detalle__planilla=planilla)
        .select_related("concepto", "detalle__personal")
        .order_by(
            "detalle__personal__apellidos", "detalle__personal__nombres", "tipo", "concepto__orden"
        )
    )
    filas = []
    sin_codigo: dict[str, str] = {}
    for linea in lineas:
        personal = linea.detalle.personal
        codigo_plame = linea.concepto.codigo_plame
        if not codigo_plame:
            sin_codigo[linea.codigo] = linea.nombre
        filas.append(
            [
                personal.tipo_documento,
                personal.numero_documento,
                personal.nombre_completo,
                codigo_plame or "SIN CÓDIGO",
                linea.nombre,
                dict(TipoConcepto.choices).get(linea.tipo, linea.tipo),
                linea.monto,
            ]
        )
    conceptos = Tabla(
        "Conceptos",
        "Conceptos por trabajador",
        [
            ("Tipo de documento", "texto"),
            ("Documento", "texto"),
            ("Trabajador", "texto"),
            ("Código PLAME", "texto"),
            ("Concepto", "texto"),
            ("Tipo", "texto"),
            ("Monto", "dinero"),
        ],
        filas,
    )
    jornada = Tabla(
        "Jornada",
        "Jornada y bases del mes",
        [
            ("Tipo de documento", "texto"),
            ("Documento", "texto"),
            ("Trabajador", "texto"),
            ("Días con contrato", "numero"),
            ("Días trabajados", "numero"),
            ("Días sin goce", "numero"),
            ("Días de descanso médico", "numero"),
            ("Días de vacaciones", "numero"),
            ("Horas trabajadas", "numero"),
            ("Horas extra", "numero"),
            ("Base de pensión", "dinero"),
            ("Base de EsSalud", "dinero"),
        ],
        [
            [
                d.personal.tipo_documento,
                d.personal.numero_documento,
                d.personal.nombre_completo,
                d.dias_contrato,
                d.dias_laborados,
                d.dias_falta,
                d.dias_descanso_medico,
                d.dias_vacaciones,
                d.horas_trabajadas,
                d.horas_extra,
                d.base_pension,
                d.base_essalud,
            ]
            for d in detalles
        ],
    )
    avisos = [
        "Es un archivo de apoyo para preparar el PLAME; no es el archivo oficial de la SUNAT."
    ]
    if sin_codigo:
        avisos.append(
            "Conceptos sin código PLAME (complételos en Conceptos de planilla): "
            + ", ".join(sorted(sin_codigo.values()))
            + "."
        )
    return Reporte(
        tipo="plame",
        titulo="CONCEPTOS PARA EL PLAME",
        subtitulo=f"{periodo:%m/%Y}",
        archivo=f"plame-apoyo-{empresa.ruc}-{periodo:%Y-%m}.xlsx",
        tablas=[conceptos, jornada],
        avisos=avisos,
    )


def t_registro(empresa) -> Reporte:
    contratos = (
        ContratoLaboral.objects.filter(empresa=empresa, estado=EstadoContrato.VIGENTE)
        .select_related("personal", "regimen", "personal__datos_laborales")
        .order_by("personal__apellidos", "personal__nombres", "id")
    )
    filas = []
    sin_datos = []
    for c in contratos:
        p = c.personal
        datos = getattr(p, "datos_laborales", None)
        if datos is None:
            sin_datos.append(p.nombre_completo)
        filas.append(
            [
                p.tipo_documento,
                p.numero_documento,
                p.apellidos,
                p.nombres,
                datos.get_sexo_display() if datos and datos.sexo else "",
                datos.nacionalidad if datos else "",
                p.fecha_nacimiento,
                p.fecha_ingreso or c.fecha_inicio,
                c.regimen.nombre,
                c.get_tipo_contrato_display(),
                c.get_categoria_display(),
                c.cargo,
                c.fecha_fin,
                datos.get_sistema_pension_display() if datos else "",
                datos.get_afp_display() if datos and datos.afp else "",
                datos.cuspp if datos else "",
                "Sí" if datos and datos.asignacion_familiar else "No",
            ]
        )
    avisos = ["Es un archivo de apoyo para el T-Registro; no es el archivo oficial de la SUNAT."]
    if sin_datos:
        avisos.append("Sin datos laborales completos: " + ", ".join(sin_datos) + ".")
    return Reporte(
        tipo="t-registro",
        titulo="DATOS PARA EL T-REGISTRO",
        subtitulo=f"Trabajadores con contrato vigente al {date.today():%d/%m/%Y}",
        archivo=f"t-registro-apoyo-{empresa.ruc}.xlsx",
        tablas=[
            Tabla(
                "T-Registro",
                "Trabajadores",
                [
                    ("Tipo de documento", "texto"),
                    ("Documento", "texto"),
                    ("Apellidos", "texto"),
                    ("Nombres", "texto"),
                    ("Sexo", "texto"),
                    ("Nacionalidad", "texto"),
                    ("Fecha de nacimiento", "fecha"),
                    ("Fecha de ingreso", "fecha"),
                    ("Régimen laboral", "texto"),
                    ("Tipo de contrato", "texto"),
                    ("Categoría", "texto"),
                    ("Cargo", "texto"),
                    ("Fin del contrato", "fecha"),
                    ("Sistema de pensión", "texto"),
                    ("AFP", "texto"),
                    ("CUSPP", "texto"),
                    ("Asignación familiar", "texto"),
                ],
                filas,
            )
        ],
        avisos=avisos,
    )


def resumen_anual(empresa, anio: int) -> Reporte:
    if not 2000 <= anio <= 2100:
        raise ErrorReporte({"anio": "Indique un año válido."})
    planillas = list(
        Planilla.objects.filter(empresa=empresa, periodo__year=anio, estado=EstadoPlanilla.CERRADA)
    )
    if not planillas:
        raise ErrorReporte({"anio": f"No hay planillas cerradas en {anio}."})
    mes_de = {p.pk: p.periodo.month for p in planillas}
    detalles = list(
        PlanillaTrabajador.objects.filter(planilla__in=planillas).select_related("personal")
    )
    renta = dict(
        PlanillaConcepto.objects.filter(detalle__planilla__in=planillas, codigo="RENTA_5TA")
        .values("detalle__personal_id")
        .annotate(total=Sum("monto"))
        .values_list("detalle__personal_id", "total")
    )
    por_persona: dict[int, dict] = {}
    for d in detalles:
        fila = por_persona.setdefault(
            d.personal_id,
            {
                "personal": d.personal,
                "meses": defaultdict(Decimal),
                "ingresos": CERO,
                "descuentos": CERO,
                "neto": CERO,
            },
        )
        fila["meses"][mes_de[d.planilla_id]] += d.neto
        fila["ingresos"] += d.total_ingresos
        fila["descuentos"] += d.total_descuentos
        fila["neto"] += d.neto
    filas = []
    for personal_id, f in sorted(
        por_persona.items(),
        key=lambda par: (par[1]["personal"].apellidos, par[1]["personal"].nombres),
    ):
        filas.append(
            [
                f["personal"].nombre_completo,
                f["personal"].numero_documento,
                *[f["meses"].get(m, CERO) for m in range(1, 13)],
                f["ingresos"],
                f["descuentos"],
                f["neto"],
                renta.get(personal_id, CERO),
            ]
        )
    totales = ["TOTALES", ""] + [sum((f[i] for f in filas), CERO) for i in range(2, 18)]
    return Reporte(
        tipo="anual",
        titulo=f"RESUMEN ANUAL DE PLANILLAS {anio}",
        subtitulo=f"{len(planillas)} planilla(s) cerrada(s) · neto pagado por mes",
        archivo=f"resumen-anual-{empresa.ruc}-{anio}.xlsx",
        tablas=[
            Tabla(
                "Resumen anual",
                "Neto por mes",
                [("Trabajador", "texto"), ("Documento", "texto")]
                + [(m, "dinero") for m in MESES]
                + [
                    ("Total ingresos", "dinero"),
                    ("Total descuentos", "dinero"),
                    ("Total neto", "dinero"),
                    ("Renta de 5.ª retenida", "dinero"),
                ],
                filas,
                totales,
            )
        ],
    )


def armar(tipo: str, empresa, *, periodo: str | None = None, anio: int | None = None) -> Reporte:
    if tipo == "planilla":
        return planilla_del_mes(empresa, periodo_de(periodo))
    if tipo == "plame":
        return plame_conceptos(empresa, periodo_de(periodo))
    if tipo == "t-registro":
        return t_registro(empresa)
    if tipo == "anual":
        if anio is None:
            raise ErrorReporte({"anio": "Indique el año."})
        return resumen_anual(empresa, anio)
    raise ErrorReporte({"tipo": "Elija un reporte de la lista."})


# ---------------------------------------------------------------------------
# Salida: vista previa y Excel
# ---------------------------------------------------------------------------
def _valor_json(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def vista(reporte: Reporte) -> dict:
    return {
        "tipo": reporte.tipo,
        "titulo": reporte.titulo,
        "subtitulo": reporte.subtitulo,
        "archivo": reporte.archivo,
        "avisos": reporte.avisos,
        "tablas": [
            {
                "hoja": t.hoja,
                "titulo": t.titulo,
                "columnas": [{"titulo": c, "tipo": tipo} for c, tipo in t.columnas],
                "total_filas": len(t.filas),
                "filas": [[_valor_json(v) for v in fila] for fila in t.filas[:MAX_FILAS_VISTA]],
                "totales": None if t.totales is None else [_valor_json(v) for v in t.totales],
            }
            for t in reporte.tablas
        ],
    }


DINERO = "#,##0.00"
FECHA = "dd/mm/yyyy"
NEGRITA = Font(bold=True)
FONDO_CABECERA = PatternFill("solid", fgColor="D9DEE8")
FONDO_TOTAL = PatternFill("solid", fgColor="EEF1F6")
BORDE = Border(*(Side(style="thin", color="9AA3B2"),) * 4)


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


def libro_excel(empresa, reporte: Reporte) -> bytes:
    libro = Workbook()
    libro.remove(libro.active)
    for tabla in reporte.tablas:
        ws = libro.create_sheet(tabla.hoja[:31])
        _poner(ws, 1, 1, reporte.titulo).font = Font(bold=True, size=13)
        _poner(ws, 2, 1, reporte.subtitulo)
        _poner(ws, 3, 1, f"{empresa.razon_social} · RUC {empresa.ruc}")
        for i, aviso in enumerate(reporte.avisos):
            _poner(ws, 4 + i, 1, aviso)
        cabecera = 5 + len(reporte.avisos)
        for i, (titulo, _) in enumerate(tabla.columnas, start=1):
            celda = _poner(ws, cabecera, i, titulo, negrita=True)
            celda.fill, celda.border = FONDO_CABECERA, BORDE
            celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        formatos = {"dinero": DINERO, "fecha": FECHA, "numero": None, "texto": None}
        fila = cabecera + 1
        for datos in tabla.filas:
            for i, ((_, tipo), valor) in enumerate(
                zip(tabla.columnas, datos, strict=True), start=1
            ):
                _poner(ws, fila, i, valor, formatos[tipo]).border = BORDE
            fila += 1
        if tabla.totales is not None:
            for i, ((_, tipo), valor) in enumerate(
                zip(tabla.columnas, tabla.totales, strict=True), start=1
            ):
                celda = _poner(ws, fila, i, valor, formatos[tipo], negrita=True)
                celda.fill, celda.border = FONDO_TOTAL, BORDE
        for i, (titulo, tipo) in enumerate(tabla.columnas, start=1):
            ws.column_dimensions[get_column_letter(i)].width = (
                34 if i == 1 and tipo == "texto" else max(12, min(len(titulo) + 2, 28))
            )
        ws.freeze_panes = ws.cell(row=cabecera + 1, column=1)
        ws.page_setup.orientation = "landscape"
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
