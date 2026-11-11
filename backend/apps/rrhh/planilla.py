"""Planilla mensual de una empresa: cálculo por conceptos, revisión y cierre.

Cómo funciona
-------------
* Hay UNA planilla por empresa y mes. Mientras está «en revisión» se recalcula todas las veces que
  haga falta; al cerrarla quedan fijos los montos, las cuotas de adelantos del mes pasan a
  «descontadas» y se bloquea la asistencia y los descuentos de ese mes (``cierre.py``).
* Cada trabajador con contrato en el mes tiene sus renglones por concepto (sueldo, faltas, AFP,
  un adelanto…). Lo que cambia con la ley (RMV, UIT, tasas de AFP, tramos de renta…) sale de los
  parámetros con vigencia: si falta alguno, la planilla lo avisa y NO se puede cerrar.
* El cálculo nunca inventa: un día sin marcar en la asistencia, un neto negativo o un valor legal
  sin cargar son errores que impiden el cierre; lo que solo conviene revisar es un aviso.

Criterios (a confirmar con el contador)
---------------------------------------
* Valor del día = sueldo ÷ días del mes de los parámetros (normalmente 30). Un mes completo paga el
  sueldo entero (también febrero y los de 31 días); un mes incompleto paga los días con contrato.
* Cada día sin goce (falta, permiso sin goce…) descuenta un valor del día y reduce las bases de
  pensión, EsSalud y renta.
* Trabajar un feriado o día de descanso suma el valor del día × la sobretasa del parámetro. Las
  horas extra se pagan sobre el valor de la hora (valor del día ÷ horas de la jornada) con la
  sobretasa de las primeras horas de cada día y la de las siguientes.
* EsSalud (aporte del empleador): sobre lo afecto, con una base mínima igual a la RMV (en
  proporción a los días con contrato).
* Renta de 5.ª: proyección anual (lo ya pagado en planillas cerradas del año + lo de este mes por
  los meses que faltan + gratificaciones por venir) menos la deducción en UIT, con la escala por
  tramos; se retiene (impuesto − lo ya retenido) ÷ el divisor del mes. No considera ingresos de
  otros empleadores ni créditos del impuesto.
"""

import calendar
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto, obtener_contexto_requerido
from apps.mantenimiento.models import EstadoRegistro, Personal

from . import adelantos, catalogos, trabajadores
from .asistencia import _cubierto, _dias, _tramos
from .models import (
    AsistenciaDia,
    CategoriaAsistencia,
    CodigoParametro,
    ConceptoPlanilla,
    ContratoLaboral,
    CuotaAdelanto,
    EstadoAdelanto,
    EstadoCuota,
    EstadoPago,
    EstadoPlanilla,
    PagoPlanilla,
    Planilla,
    PlanillaConcepto,
    PlanillaTrabajador,
    SistemaPension,
    TipoAdelanto,
    TipoAsistencia,
    TipoComision,
    TipoConcepto,
    TipoContrato,
    TramoRenta5,
)

logger = logging.getLogger(__name__)

CENTAVO = Decimal("0.01")
CIEN = Decimal("100")
MAXIMO = Decimal("9999999.99")
ERROR = "ERROR"
AVISO = "AVISO"

# Cuántos meses se reparte la retención de renta de 5.ª según el mes (de la norma de la SUNAT).
DIVISOR_RENTA5 = {1: 12, 2: 12, 3: 12, 4: 9, 5: 8, 6: 8, 7: 8, 8: 5, 9: 4, 10: 4, 11: 4, 12: 1}
# Ingresos de la renta de 5.ª que no se repiten todos los meses.
EXTRAORDINARIOS = {"GRATIFICACION", "BONIF_EXTRAORDINARIA"}
MESES_GRATIFICACION = (7, 12)

# Los conceptos que calcula el sistema: una persona no los agrega a mano.
CALCULADOS = {
    "SUELDO_BASICO",
    "ASIGNACION_FAMILIAR",
    "TRABAJO_FERIADO",
    "HORAS_EXTRA_PRIMERAS",
    "HORAS_EXTRA_SIGUIENTES",
    "DESCUENTO_FALTAS",
    "ADELANTOS",
    "PRESTAMOS",
    "RENTA_5TA",
    "ONP",
    "AFP_APORTE",
    "AFP_PRIMA",
    "AFP_COMISION",
    "ESSALUD",
}
# Y los que llegarán con vacaciones, gratificaciones y CTS: tampoco a mano, para no duplicarlos.
RESERVADOS = CALCULADOS | {
    "DESCANSO_PAGADO",
    "VACACIONES",
    "GRATIFICACION",
    "BONIF_EXTRAORDINARIA",
    "CTS",
}


class ErrorPlanilla(ValidationError):
    """Algo impide hacer la operación con la planilla (se muestra al usuario)."""


def _error(campo: str, mensaje: str) -> ErrorPlanilla:
    return ErrorPlanilla({campo: mensaje})


def _exigir_empresa(empresa_id: int) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa_id):
        raise EmpresaNoHabilitada()


def _red(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _soles(valor: Decimal) -> str:
    return f"S/ {valor:,.2f}"


def _num(valor: Decimal) -> str:
    """Un número sin ceros de más: 30.0000 → 30, 25.50 → 25.5."""
    texto = f"{valor:f}"
    return texto.rstrip("0").rstrip(".") if "." in texto else texto


# ---------------------------------------------------------------------------
# Lo que se necesita para calcular (se arma una vez por planilla)
# ---------------------------------------------------------------------------
@dataclass
class _Linea:
    concepto: ConceptoPlanilla
    monto: Decimal
    explicacion: str = ""
    cuota: CuotaAdelanto | None = None
    manual: bool = False
    existente: PlanillaConcepto | None = None

    @property
    def codigo(self) -> str:
        return self.concepto.codigo

    @property
    def tipo(self) -> str:
        return self.concepto.tipo


@dataclass
class _Contexto:
    empresa: object
    periodo: date
    desde: date
    hasta: date
    dias_calendario: int
    params: dict
    conceptos: dict
    tipos: dict
    # Lo que falta cargar y no depende de un trabajador: clave → texto para el usuario.
    faltan: dict = field(default_factory=dict)
    generales: list = field(default_factory=list)
    _tasas: dict = field(default_factory=dict)
    _escala: object = None

    @property
    def org(self) -> int:
        return self.empresa.organizacion_id

    def param(self, codigo: str, para: str) -> Decimal | None:
        """El valor vigente; si no se cargó, se anota para avisar una sola vez."""
        valor = self.params.get(codigo)
        if valor is None:
            nombre = dict(CodigoParametro.choices).get(codigo, codigo)
            self.faltan.setdefault(codigo, f"Falta cargar «{nombre}» (se usa para {para}).")
        return valor

    def tasa_afp(self, afp: str):
        if afp not in self._tasas:
            tasa = catalogos.tasa_afp_vigente(self.org, afp, self.hasta)
            self._tasas[afp] = tasa
            if tasa is None:
                self.faltan.setdefault(
                    f"AFP:{afp}", f"Faltan las tasas de {afp} vigentes en {self.hasta:%m/%Y}."
                )
        return self._tasas[afp]

    def escala(self) -> list[TramoRenta5] | None:
        """La escala de renta de 5.ª vigente en el mes (``None`` si no está o está incompleta)."""
        if self._escala is None:
            self._escala = self._cargar_escala() or False
        return self._escala or None

    def _cargar_escala(self):
        filas = TramoRenta5.objects.sin_ambito().filter(
            organizacion_id=self.org, estado=EstadoRegistro.ACTIVO, vigente_desde__lte=self.hasta
        )
        vigente = filas.order_by("-vigente_desde").values_list("vigente_desde", flat=True).first()
        clave = "ESCALA_RENTA5"
        if vigente is None:
            self.faltan.setdefault(
                clave, "Faltan los tramos de la renta de 5.ª categoría (Recursos humanos › Tramos)."
            )
            return None
        tramos = list(filas.filter(vigente_desde=vigente).order_by("orden"))
        topes = [t.hasta_uit for t in tramos]
        completa = (
            topes[-1] is None
            and all(t is not None for t in topes[:-1])
            and all(a < b for a, b in zip(topes[:-2], topes[1:-1], strict=False))
        )
        if not completa:
            self.faltan.setdefault(
                clave,
                "La escala de renta de 5.ª está mal cargada: los topes deben ir creciendo y el "
                "último tramo no lleva tope.",
            )
            return None
        return tramos


def _armar_contexto(empresa, periodo: date) -> _Contexto:
    hasta = date(periodo.year, periodo.month, calendar.monthrange(periodo.year, periodo.month)[1])
    org = empresa.organizacion_id
    params = {c: catalogos.valor_vigente(org, c, hasta) for c in CodigoParametro.values}
    conceptos = {
        c.codigo: c
        for c in ConceptoPlanilla.objects.sin_ambito().filter(
            organizacion_id=org, estado=EstadoRegistro.ACTIVO
        )
    }
    tipos = {t.pk: t for t in TipoAsistencia.objects.sin_ambito().filter(organizacion_id=org)}
    contexto = _Contexto(
        empresa=empresa,
        periodo=periodo,
        desde=periodo,
        hasta=hasta,
        dias_calendario=hasta.day,
        params=params,
        conceptos=conceptos,
        tipos=tipos,
    )
    faltantes = sorted(CALCULADOS - set(conceptos))
    if faltantes:
        contexto.faltan["CONCEPTOS"] = (
            "Faltan conceptos activos en el catálogo de conceptos de planilla: "
            + ", ".join(faltantes)
            + "."
        )
    return contexto


# ---------------------------------------------------------------------------
# Renta de 5.ª categoría
# ---------------------------------------------------------------------------
def _impuesto_anual(renta: Decimal, uit: Decimal, tramos: list[TramoRenta5]) -> Decimal:
    """Aplica la escala por tramos: cada tasa solo a la parte de la renta que cae en su tramo."""
    total = Decimal("0")
    piso = Decimal("0")
    for tramo in tramos:
        tope = None if tramo.hasta_uit is None else tramo.hasta_uit * uit
        techo = renta if tope is None else min(renta, tope)
        if techo > piso:
            total += (techo - piso) * tramo.tasa / CIEN
        if tope is None or renta <= tope:
            break
        piso = tope
    return total


def _ya_pagado_en_el_anio(ctx: _Contexto, personal: Personal) -> tuple[Decimal, Decimal]:
    """(ingresos de renta de 5.ª, renta retenida) en las planillas cerradas del año."""
    cerradas = PlanillaConcepto.objects.filter(
        detalle__personal=personal,
        detalle__eliminado_en__isnull=True,
        detalle__planilla__eliminado_en__isnull=True,
        detalle__planilla__estado=EstadoPlanilla.CERRADA,
        detalle__planilla__periodo__gte=date(ctx.periodo.year, 1, 1),
        detalle__planilla__periodo__lt=ctx.periodo,
    )
    ingresos = cerradas.filter(tipo=TipoConcepto.INGRESO, concepto__afecto_renta5=True).aggregate(
        t=Sum("monto")
    )["t"] or Decimal("0")
    retenido = cerradas.filter(codigo="RENTA_5TA").aggregate(t=Sum("monto"))["t"] or Decimal("0")
    sueldo = ctx.conceptos.get("SUELDO_BASICO")
    if sueldo is not None and sueldo.afecto_renta5:
        faltas = cerradas.filter(codigo="DESCUENTO_FALTAS").aggregate(t=Sum("monto"))["t"]
        ingresos -= faltas or Decimal("0")
    return ingresos, retenido


def _retencion_renta5(ctx, personal, regimen, sueldo, lineas, descuento_faltas):
    """La retención del mes y cómo se calculó, o ``None`` si falta algún dato legal."""
    uit = ctx.param(CodigoParametro.UIT, "la renta de 5.ª categoría")
    deduccion = ctx.param(CodigoParametro.DEDUCCION_RENTA5_UIT, "la renta de 5.ª categoría")
    tramos = ctx.escala()
    if uit is None or deduccion is None or tramos is None:
        return None
    mes = ctx.periodo.month
    meses_que_faltan = 12 - mes + 1
    afectas = [ln for ln in lineas if ln.tipo == TipoConcepto.INGRESO and ln.concepto.afecto_renta5]
    ordinarios = sum((ln.monto for ln in afectas if ln.codigo not in EXTRAORDINARIOS), Decimal("0"))
    extraordinarios = sum(
        (ln.monto for ln in afectas if ln.codigo in EXTRAORDINARIOS), Decimal("0")
    )
    sueldo_concepto = ctx.conceptos.get("SUELDO_BASICO")
    if sueldo_concepto is not None and sueldo_concepto.afecto_renta5:
        ordinarios = max(ordinarios - descuento_faltas, Decimal("0"))

    # Las gratificaciones que todavía no se pagan se proyectan con el factor del régimen.
    por_venir = Decimal("0")
    gratificacion = ctx.conceptos.get("GRATIFICACION")
    if gratificacion is not None and gratificacion.afecto_renta5:
        unidad = sueldo * regimen.factor_gratificacion
        bonif = ctx.conceptos.get("BONIF_EXTRAORDINARIA")
        porcentaje = ctx.params.get(CodigoParametro.BONIF_EXTRAORDINARIA)
        if bonif is not None and bonif.afecto_renta5 and porcentaje:
            unidad += unidad * porcentaje / CIEN
        pagada_este_mes = any(ln.codigo == "GRATIFICACION" for ln in lineas)
        for m in MESES_GRATIFICACION:
            if m > mes or (m == mes and not pagada_este_mes):
                por_venir += unidad

    previos, retenido = _ya_pagado_en_el_anio(ctx, personal)
    proyeccion = previos + ordinarios * meses_que_faltan + extraordinarios + por_venir
    renta_neta = max(proyeccion - deduccion * uit, Decimal("0"))
    impuesto = _impuesto_anual(renta_neta, uit, tramos)
    divisor = DIVISOR_RENTA5[mes]
    retencion = max((impuesto - retenido) / divisor, Decimal("0"))
    explicacion = (
        f"Impuesto anual proyectado {_soles(_red(impuesto))}; ya retenido "
        f"{_soles(_red(retenido))}; entre {divisor} mes(es)"
    )
    return _red(retencion), explicacion


# ---------------------------------------------------------------------------
# Un trabajador
# ---------------------------------------------------------------------------
@dataclass
class _Resultado:
    contrato: ContratoLaboral
    campos: dict
    lineas: list[_Linea]
    avisos: list[dict]


def _suma(lineas, atributo: str, descuento_faltas: Decimal, ctx: _Contexto) -> Decimal:
    """Lo que está afecto a pensión/EsSalud/renta (las faltas restan del sueldo si es afecto)."""
    total = sum(
        (
            ln.monto
            for ln in lineas
            if ln.tipo == TipoConcepto.INGRESO and getattr(ln.concepto, atributo)
        ),
        Decimal("0"),
    )
    sueldo = ctx.conceptos.get("SUELDO_BASICO")
    if sueldo is not None and getattr(sueldo, atributo):
        total -= descuento_faltas
    return max(total, Decimal("0"))


def _calcular_trabajador(
    ctx: _Contexto,
    personal: Personal,
    contratos: list[ContratoLaboral],
    marcas: dict[date, AsistenciaDia],
    cuotas: list[CuotaAdelanto],
    atrasadas: int,
    manuales: list[PlanillaConcepto],
    semestre: tuple[int, int] | None = None,
) -> _Resultado:
    avisos: list[dict] = []

    def avisar(nivel: str, texto: str) -> None:
        avisos.append({"nivel": nivel, "texto": texto})

    contrato = max(contratos, key=lambda c: (c.fecha_inicio, c.pk))
    if len(contratos) > 1:
        avisar(
            AVISO, "Tuvo más de un contrato en el mes: se usan el sueldo y el régimen del último."
        )
    regimen = contrato.regimen
    datos = getattr(personal, "datos_laborales", None)

    # --- días del mes -------------------------------------------------------------------------
    tramos = _tramos(contratos)
    cubiertos = [d for d in _dias(ctx.desde, ctx.hasta) if _cubierto(tramos, d)]
    dias_contrato = len(cubiertos)
    sin_marcar = [d for d in cubiertos if d not in marcas]
    laborados = faltas = descanso_medico = vacaciones = feriados_trabajados = 0
    horas_por_dia: list[Decimal] = []
    for dia in cubiertos:
        marca = marcas.get(dia)
        tipo = ctx.tipos.get(marca.tipo_id) if marca else None
        if tipo is None:
            continue
        laborados += int(tipo.cuenta_dia_laborado)
        faltas += int(not tipo.se_paga)
        descanso_medico += int(tipo.categoria == CategoriaAsistencia.DESCANSO_MEDICO)
        vacaciones += int(tipo.categoria == CategoriaAsistencia.VACACIONES)
        feriados_trabajados += int(tipo.categoria == CategoriaAsistencia.TRABAJO_FERIADO)
        if marca.horas_extra > 0:
            horas_por_dia.append(marca.horas_extra)
    if sin_marcar:
        primeros = ", ".join(f"{d:%d/%m}" for d in sin_marcar[:6])
        mas = "…" if len(sin_marcar) > 6 else ""
        avisar(
            ERROR,
            f"Faltan marcar {len(sin_marcar)} día(s) en la asistencia ({primeros}{mas}). "
            "Complételos en Asistencia.",
        )

    # --- sueldo -------------------------------------------------------------------------------
    ultimo_dia = cubiertos[-1] if cubiertos else ctx.hasta
    sueldo = trabajadores.sueldo_vigente(contrato, ultimo_dia)
    if sueldo is None:
        avisar(ERROR, "No tiene un sueldo registrado en su contrato para este mes.")
        sueldo = Decimal("0")
    elif contrato.cambios_sueldo.filter(
        vigente_desde__gt=ctx.desde, vigente_desde__lte=ultimo_dia
    ).exists():
        avisar(AVISO, "Su sueldo cambió durante el mes: se usó el vigente al final del mes.")
    rmv = ctx.params.get(CodigoParametro.RMV)
    if (
        sueldo
        and rmv is not None
        and sueldo < rmv
        and contrato.tipo_contrato not in (TipoContrato.TIEMPO_PARCIAL, TipoContrato.PRACTICAS)
    ):
        avisar(AVISO, f"Su sueldo es menor que la remuneración mínima ({_soles(rmv)}).")

    horas_jornada = None
    if laborados:
        horas_jornada = ctx.param(CodigoParametro.HORAS_JORNADA, "las horas trabajadas")

    lineas: list[_Linea] = []

    def agregar(codigo: str, monto: Decimal, explicacion: str = "", cuota=None) -> None:
        concepto = ctx.conceptos.get(codigo)
        if concepto is not None and monto > 0:
            lineas.append(_Linea(concepto, monto, explicacion, cuota))

    # Lo que agregó una persona (bonos, comisiones, otros descuentos) se conserva.
    for fila in manuales:
        concepto = ctx.conceptos.get(fila.codigo) or fila.concepto
        lineas.append(_Linea(concepto, fila.monto, fila.explicacion, None, True, fila))

    # --- ingresos -----------------------------------------------------------------------------
    descuento_faltas = Decimal("0")
    dias_mes = ctx.param(CodigoParametro.DIAS_MES, "el valor del día") if sueldo else None
    if sueldo and dias_mes:
        dias_base = (
            dias_mes
            if dias_contrato == ctx.dias_calendario
            else min(Decimal(dias_contrato), dias_mes)
        )
        valor_dia = sueldo / dias_mes
        sueldo_basico = _red(sueldo * dias_base / dias_mes)
        agregar(
            "SUELDO_BASICO",
            sueldo_basico,
            f"{_num(dias_base)} de {_num(dias_mes)} días × sueldo {_soles(sueldo)}",
        )
        if faltas:
            descuento_faltas = min(_red(valor_dia * faltas), sueldo_basico)
            agregar(
                "DESCUENTO_FALTAS",
                descuento_faltas,
                f"{faltas} día(s) sin goce × {_soles(_red(valor_dia))}",
            )
        if datos is not None and datos.asignacion_familiar:
            porcentaje = ctx.param(CodigoParametro.ASIGNACION_FAMILIAR, "la asignación familiar")
            if rmv is None:
                ctx.param(CodigoParametro.RMV, "la asignación familiar")
            elif porcentaje is not None:
                agregar(
                    "ASIGNACION_FAMILIAR",
                    _red(rmv * porcentaje / CIEN * dias_base / dias_mes),
                    f"{_num(porcentaje)} % de la RMV {_soles(rmv)}",
                )
        if feriados_trabajados:
            sobretasa = ctx.param(CodigoParametro.SOBRETASA_FERIADO, "el trabajo en feriado")
            if sobretasa is not None:
                agregar(
                    "TRABAJO_FERIADO",
                    _red(valor_dia * feriados_trabajados * sobretasa / CIEN),
                    f"{feriados_trabajados} día(s) × {_soles(_red(valor_dia))} "
                    f"× {_num(sobretasa)} %",
                )
        if horas_por_dia and horas_jornada is not None:
            _horas_extra(ctx, valor_dia / horas_jornada, horas_por_dia, agregar)
        elif horas_por_dia:
            ctx.param(CodigoParametro.HORAS_JORNADA, "las horas extra")
    else:
        dias_base = Decimal("0")

    # --- gratificación de julio y diciembre ---------------------------------------------------
    if semestre is not None and sueldo:
        _gratificacion(ctx, regimen, datos, sueldo, semestre, agregar, avisar)
    cese = [c for c in contratos if c.fecha_cese and ctx.desde <= c.fecha_cese <= ctx.hasta]
    if cese:
        avisar(
            AVISO,
            f"Cesó el {cese[0].fecha_cese:%d/%m/%Y}: su liquidación (vacaciones, gratificación y "
            "CTS truncas) se calcula aparte con el contador; no está en esta planilla.",
        )

    # --- adelantos y préstamos del mes ---------------------------------------------------------
    for cuota in cuotas:
        adelanto = cuota.adelanto
        codigo = "ADELANTOS" if adelanto.tipo == TipoAdelanto.ADELANTO else "PRESTAMOS"
        agregar(
            codigo,
            cuota.monto,
            f"{adelanto.get_tipo_display()} N° {adelanto.numero:06d}, cuota {cuota.numero} "
            f"de {adelanto.num_cuotas}",
            cuota,
        )
    if atrasadas:
        avisar(
            AVISO,
            f"Tiene {atrasadas} cuota(s) de meses anteriores sin descontar. No se incluyen "
            "aquí: revíselas en Adelantos y préstamos.",
        )

    # --- pensión ------------------------------------------------------------------------------
    base_pension = _suma(lineas, "afecto_pension", descuento_faltas, ctx)
    if datos is None:
        avisar(ERROR, "Faltan sus datos laborales (pensión, pago…): complete su ficha.")
    elif datos.sistema_pension == SistemaPension.ONP:
        tasa = ctx.param(CodigoParametro.ONP, "el descuento de ONP")
        if tasa is not None:
            agregar(
                "ONP", _red(base_pension * tasa / CIEN), f"{_num(tasa)} % de {_soles(base_pension)}"
            )
    elif datos.sistema_pension == SistemaPension.AFP:
        tasa_afp = ctx.tasa_afp(datos.afp)
        if tasa_afp is not None:
            comision = (
                tasa_afp.comision_flujo
                if datos.tipo_comision == TipoComision.FLUJO
                else tasa_afp.comision_mixta
            )
            asegurable = min(base_pension, tasa_afp.remuneracion_maxima_asegurable)
            agregar(
                "AFP_APORTE",
                _red(base_pension * tasa_afp.aporte_obligatorio / CIEN),
                f"{_num(tasa_afp.aporte_obligatorio)} % de {_soles(base_pension)}",
            )
            agregar(
                "AFP_PRIMA",
                _red(asegurable * tasa_afp.prima_seguro / CIEN),
                f"{_num(tasa_afp.prima_seguro)} % de {_soles(asegurable)} (con tope)",
            )
            agregar(
                "AFP_COMISION",
                _red(base_pension * comision / CIEN),
                f"{_num(comision)} % de {_soles(base_pension)} (comisión "
                f"{'sobre flujo' if datos.tipo_comision == TipoComision.FLUJO else 'mixta'})",
            )
        if not datos.cuspp:
            avisar(AVISO, "No tiene CUSPP registrado.")
    else:
        avisar(AVISO, "No tiene sistema de pensión: no se le descuenta ONP ni AFP.")

    # --- renta de 5.ª -------------------------------------------------------------------------
    if datos is not None and datos.paga_renta_5ta and sueldo:
        calculo = _retencion_renta5(ctx, personal, regimen, sueldo, lineas, descuento_faltas)
        if calculo is not None:
            agregar("RENTA_5TA", calculo[0], calculo[1])

    # --- EsSalud (lo paga el empleador) -----------------------------------------------------------
    base_essalud = _suma(lineas, "afecto_essalud", descuento_faltas, ctx)
    if sueldo and dias_mes:
        if rmv is None:
            ctx.param(CodigoParametro.RMV, "la base mínima de EsSalud")
        else:
            base_essalud = max(base_essalud, _red(rmv * dias_base / dias_mes))
    aporte = _red(base_essalud * regimen.tasa_essalud / CIEN)
    agregar("ESSALUD", aporte, f"{_num(regimen.tasa_essalud)} % de {_soles(base_essalud)}")

    # --- otros avisos -------------------------------------------------------------------------
    if datos is not None:
        if descanso_medico and datos.subsidio_descanso_medico:
            avisar(
                AVISO,
                f"Tiene {descanso_medico} día(s) de descanso médico con subsidio: el subsidio de "
                "EsSalud no se calcula aquí; revíselo con el contador.",
            )
        if datos.metodo_pago == "TRANSFERENCIA" and not (datos.banco and datos.numero_cuenta):
            avisar(AVISO, "Se le paga por transferencia pero no tiene banco y cuenta registrados.")

    ingresos = sum((ln.monto for ln in lineas if ln.tipo == TipoConcepto.INGRESO), Decimal("0"))
    descuentos = sum((ln.monto for ln in lineas if ln.tipo == TipoConcepto.DESCUENTO), Decimal("0"))
    neto = ingresos - descuentos
    if neto < 0:
        avisar(
            ERROR,
            "El neto a pagar sale negativo. Difiera una cuota de adelanto o revise los descuentos.",
        )

    campos = {
        "regimen_nombre": regimen.nombre,
        "cargo": contrato.cargo,
        "sueldo_mensual": sueldo,
        "sistema_pension": datos.sistema_pension if datos else "",
        "afp": datos.afp if datos else "",
        "tipo_comision": datos.tipo_comision if datos else "",
        "metodo_pago": datos.metodo_pago if datos else "",
        "dias_contrato": dias_contrato,
        "dias_laborados": laborados,
        "dias_falta": faltas,
        "dias_descanso_medico": descanso_medico,
        "dias_vacaciones": vacaciones,
        "horas_trabajadas": _red(Decimal(laborados) * horas_jornada) if horas_jornada else 0,
        "horas_extra": sum(horas_por_dia, Decimal("0")),
        "base_pension": base_pension,
        "base_essalud": base_essalud,
        "total_ingresos": ingresos,
        "total_descuentos": descuentos,
        "neto": neto,
        "aporte_empleador": aporte,
        "avisos": avisos,
    }
    return _Resultado(contrato, campos, lineas, avisos)


def _gratificacion(ctx, regimen, datos, sueldo, semestre, agregar, avisar) -> None:
    """La gratificación del semestre: 1/6 por cada mes completo, menos 1/180 por cada falta.

    Se multiplica por los sueldos de gratificación del régimen (1 en el general, 0.5 en la pequeña
    empresa) y se suma la bonificación extraordinaria. La base es el sueldo más la asignación
    familiar; no se promedian comisiones ni horas extra.
    """
    factor = regimen.factor_gratificacion
    meses, faltas = semestre
    if not factor:
        return
    if meses == 0:
        avisar(AVISO, "No tiene meses completos en el semestre: no le corresponde gratificación.")
        return
    base = sueldo
    if datos is not None and datos.asignacion_familiar:
        rmv = ctx.param(CodigoParametro.RMV, "la gratificación")
        porcentaje = ctx.param(CodigoParametro.ASIGNACION_FAMILIAR, "la gratificación")
        if rmv is not None and porcentaje is not None:
            base += _red(rmv * porcentaje / CIEN)
    bruto = max(base * meses / 6 - base * faltas / 180, Decimal("0"))
    gratificacion = _red(factor * bruto)
    agregar(
        "GRATIFICACION",
        gratificacion,
        f"{meses} mes(es) completo(s) de 6 sobre {_soles(base)}, {faltas} falta(s) "
        f"× 1/180, {_num(factor)} sueldo(s)",
    )
    porcentaje = ctx.param(CodigoParametro.BONIF_EXTRAORDINARIA, "la bonificación extraordinaria")
    if porcentaje is not None:
        agregar(
            "BONIF_EXTRAORDINARIA",
            _red(gratificacion * porcentaje / CIEN),
            f"{_num(porcentaje)} % de la gratificación",
        )
    if faltas:
        avisar(AVISO, f"Se descontaron {faltas} falta(s) del semestre en su gratificación.")


def _horas_extra(ctx: _Contexto, valor_hora: Decimal, horas_por_dia, agregar) -> None:
    """Las primeras horas de cada día llevan una sobretasa y las siguientes otra."""
    primeras_dia = ctx.param(CodigoParametro.HORAS_HE_PRIMERAS, "las horas extra")
    sobretasa_1 = ctx.param(CodigoParametro.SOBRETASA_HE_PRIMERAS, "las horas extra")
    sobretasa_2 = ctx.param(CodigoParametro.SOBRETASA_HE_SIGUIENTES, "las horas extra")
    if primeras_dia is None or sobretasa_1 is None or sobretasa_2 is None:
        return
    primeras = sum((min(h, primeras_dia) for h in horas_por_dia), Decimal("0"))
    siguientes = sum((h for h in horas_por_dia), Decimal("0")) - primeras
    agregar(
        "HORAS_EXTRA_PRIMERAS",
        _red(primeras * valor_hora * (1 + sobretasa_1 / CIEN)),
        f"{_num(primeras)} h × {_soles(_red(valor_hora))} + {_num(sobretasa_1)} %",
    )
    agregar(
        "HORAS_EXTRA_SIGUIENTES",
        _red(siguientes * valor_hora * (1 + sobretasa_2 / CIEN)),
        f"{_num(siguientes)} h × {_soles(_red(valor_hora))} + {_num(sobretasa_2)} %",
    )


# ---------------------------------------------------------------------------
# Calcular la planilla completa
# ---------------------------------------------------------------------------
def _semestres(ctx: _Contexto, empresa, personal_ids: list[int]) -> dict[int, tuple[int, int]]:
    """(meses completos, faltas) del semestre de cada trabajador, solo en julio y diciembre."""
    mes = ctx.periodo.month
    if mes not in MESES_GRATIFICACION or not personal_ids:
        return {}
    anio = ctx.periodo.year
    primero, ultimo = (1, 6) if mes == 7 else (7, 12)
    inicio = date(anio, primero, 1)
    fin = date(anio, ultimo, calendar.monthrange(anio, ultimo)[1])
    contratos: dict[int, list[ContratoLaboral]] = defaultdict(list)
    for contrato in ContratoLaboral.objects.filter(
        empresa_id=empresa.pk, personal_id__in=personal_ids, fecha_inicio__lte=fin
    ).exclude(fecha_cese__lt=inicio):
        contratos[contrato.personal_id].append(contrato)
    faltas: dict[int, int] = defaultdict(int)
    for personal_id, fecha, tipo_id in AsistenciaDia.objects.filter(
        empresa_id=empresa.pk, personal_id__in=personal_ids, fecha__gte=inicio, fecha__lte=fin
    ).values_list("personal_id", "fecha", "tipo_id"):
        tipo = ctx.tipos.get(tipo_id)
        if (
            tipo is not None
            and not tipo.se_paga
            and _cubierto(_tramos(contratos[personal_id]), fecha)
        ):
            faltas[personal_id] += 1
    resultado = {}
    for personal_id in personal_ids:
        tramos = _tramos(contratos.get(personal_id, []))
        meses = 0
        for m in range(primero, ultimo + 1):
            ultimo_dia = calendar.monthrange(anio, m)[1]
            if all(_cubierto(tramos, date(anio, m, d)) for d in range(1, ultimo_dia + 1)):
                meses += 1
        resultado[personal_id] = (meses, faltas[personal_id])
    return resultado


def _calcular_interno(planilla: Planilla) -> Planilla:
    """Recalcula todos los trabajadores del mes. La planilla ya está bloqueada y en revisión."""
    empresa = planilla.empresa
    ctx = _armar_contexto(empresa, planilla.periodo)

    contratos_por_persona: dict[int, list[ContratoLaboral]] = defaultdict(list)
    for contrato in (
        ContratoLaboral.objects.filter(empresa_id=empresa.pk, fecha_inicio__lte=ctx.hasta)
        .exclude(fecha_cese__lt=ctx.desde)
        .select_related("regimen")
    ):
        contratos_por_persona[contrato.personal_id].append(contrato)
    personas = {
        p.pk: p
        for p in Personal.objects.filter(pk__in=list(contratos_por_persona)).select_related(
            "datos_laborales"
        )
    }

    marcas: dict[int, dict[date, AsistenciaDia]] = defaultdict(dict)
    for marca in AsistenciaDia.objects.filter(
        empresa_id=empresa.pk, fecha__gte=ctx.desde, fecha__lte=ctx.hasta
    ):
        marcas[marca.personal_id][marca.fecha] = marca

    cuotas_por_persona: dict[int, list[CuotaAdelanto]] = defaultdict(list)
    for cuota in CuotaAdelanto.objects.filter(
        empresa_id=empresa.pk,
        periodo=ctx.periodo,
        estado=EstadoCuota.PENDIENTE,
        adelanto__estado=EstadoAdelanto.VIGENTE,
    ).select_related("adelanto"):
        cuotas_por_persona[cuota.adelanto.personal_id].append(cuota)
    atrasadas: dict[int, int] = defaultdict(int)
    for personal_id in CuotaAdelanto.objects.filter(
        empresa_id=empresa.pk,
        periodo__lt=ctx.periodo,
        estado=EstadoCuota.PENDIENTE,
        adelanto__estado=EstadoAdelanto.VIGENTE,
    ).values_list("adelanto__personal_id", flat=True):
        atrasadas[personal_id] += 1

    existentes = {
        d.personal_id: d
        for d in PlanillaTrabajador.objects.select_for_update(of=("self",))
        .filter(planilla=planilla)
        .order_by("pk")
    }
    manuales: dict[int, list[PlanillaConcepto]] = defaultdict(list)
    for fila in PlanillaConcepto.objects.filter(
        detalle__planilla=planilla, manual=True
    ).select_related("concepto"):
        manuales[fila.detalle_id].append(fila)

    ordenados = sorted(personas.values(), key=lambda p: (p.apellidos, p.nombres, p.pk))
    semestres = _semestres(ctx, empresa, list(personas))
    detalles: list[PlanillaTrabajador] = []
    for personal in ordenados:
        detalle_actual = existentes.get(personal.pk)
        resultado = _calcular_trabajador(
            ctx,
            personal,
            contratos_por_persona[personal.pk],
            marcas.get(personal.pk, {}),
            cuotas_por_persona.get(personal.pk, []),
            atrasadas.get(personal.pk, 0),
            manuales.get(detalle_actual.pk, []) if detalle_actual else [],
            semestres.get(personal.pk),
        )
        detalle = detalle_actual or PlanillaTrabajador(
            empresa=empresa, planilla=planilla, personal=personal
        )
        detalle.contrato = resultado.contrato
        for campo, valor in resultado.campos.items():
            setattr(detalle, campo, valor)
        detalle.save()
        PlanillaConcepto.objects.filter(detalle=detalle, manual=False).delete()
        PlanillaConcepto.objects.bulk_create(
            [
                PlanillaConcepto(
                    empresa=empresa,
                    detalle=detalle,
                    concepto=ln.concepto,
                    codigo=ln.codigo,
                    nombre=ln.concepto.nombre,
                    tipo=ln.tipo,
                    monto=ln.monto,
                    explicacion=ln.explicacion[:200],
                    cuota=ln.cuota,
                )
                for ln in resultado.lineas
                if not ln.manual
            ]
        )
        detalles.append(detalle)

    # Quien ya no tiene contrato en el mes (se corrigió el contrato) sale de la planilla.
    sobran = [d for pid, d in existentes.items() if pid not in personas]
    for detalle in sobran:
        PlanillaConcepto.objects.filter(detalle=detalle).delete()
        detalle.delete()

    generales = [{"nivel": ERROR, "texto": texto} for texto in ctx.faltan.values()]
    if not detalles:
        generales.append({"nivel": ERROR, "texto": "No hay trabajadores con contrato en este mes."})
    planilla.avisos = generales
    planilla.num_trabajadores = len(detalles)
    planilla.total_ingresos = sum((d.total_ingresos for d in detalles), Decimal("0"))
    planilla.total_descuentos = sum((d.total_descuentos for d in detalles), Decimal("0"))
    planilla.total_neto = sum((d.neto for d in detalles), Decimal("0"))
    planilla.total_aportes = sum((d.aporte_empleador for d in detalles), Decimal("0"))
    todos = [*generales, *(a for d in detalles for a in d.avisos)]
    planilla.num_errores = sum(1 for a in todos if a["nivel"] == ERROR)
    planilla.num_avisos = sum(1 for a in todos if a["nivel"] == AVISO)
    planilla.calculada_en = timezone.now()
    planilla.save()
    return planilla


def _bloquear(planilla: Planilla) -> Planilla:
    """La planilla bloqueada y fresca; error si no está en revisión."""
    _exigir_empresa(planilla.empresa_id)
    actual = (
        Planilla.objects.select_for_update(of=("self",))
        .select_related("empresa")
        .get(pk=planilla.pk)
    )
    if actual.estado != EstadoPlanilla.BORRADOR:
        raise _error("estado", "La planilla está cerrada. Reábrala para poder cambiarla.")
    return actual


@transaction.atomic
def crear_planilla(*, empresa, anio: int, mes: int) -> Planilla:
    """Prepara la planilla de un mes y la calcula por primera vez."""
    _exigir_empresa(empresa.pk)
    if not 2000 <= anio <= 2100:
        raise _error("anio", "Indique un año válido.")
    if not 1 <= mes <= 12:
        raise _error("mes", "El mes va de 1 a 12.")
    periodo = date(anio, mes, 1)
    if periodo > timezone.localdate().replace(day=1):
        raise _error("mes", "Ese mes todavía no empieza: no se puede preparar su planilla.")
    try:
        with transaction.atomic():
            planilla = Planilla.objects.create(empresa=empresa, periodo=periodo)
    except IntegrityError:
        raise _error("mes", f"Ya existe la planilla de {periodo:%m/%Y}.") from None
    planilla = (
        Planilla.objects.select_for_update(of=("self",))
        .select_related("empresa")
        .get(pk=planilla.pk)
    )
    _calcular_interno(planilla)
    registrar(
        "rrhh.planilla_creada",
        recurso_tipo="planilla",
        recurso_id=planilla.pk,
        empresa_id=empresa.pk,
        resumen=f"Planilla de {periodo:%m/%Y} preparada",
        detalle={"trabajadores": planilla.num_trabajadores, "errores": planilla.num_errores},
    )
    logger.info("planilla_creada", extra={"planilla_id": planilla.pk})
    return planilla


@transaction.atomic
def recalcular(planilla: Planilla) -> Planilla:
    """Vuelve a calcular con la asistencia, los adelantos y los valores legales de hoy."""
    actual = _bloquear(planilla)
    _calcular_interno(actual)
    registrar(
        "rrhh.planilla_recalculada",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Planilla de {actual.periodo:%m/%Y} recalculada",
        detalle={"trabajadores": actual.num_trabajadores, "errores": actual.num_errores},
    )
    return actual


@transaction.atomic
def cerrar(planilla: Planilla, *, neto_visto: Decimal | None = None) -> Planilla:
    """Cierra la planilla: fija los montos, descuenta las cuotas y bloquea el mes.

    Recalcula justo antes de cerrar y, si el neto total ya no es el que la persona tenía en
    pantalla, no cierra: algo cambió y debe revisarlo.
    """
    actual = _bloquear(planilla)
    # Las cuotas del mes se bloquean ANTES de recalcular: si alguien anula un adelanto al mismo
    # tiempo, uno de los dos espera al otro y ninguno trabaja con datos viejos.
    list(
        CuotaAdelanto.objects.select_for_update().filter(
            empresa_id=actual.empresa_id, periodo=actual.periodo, estado=EstadoCuota.PENDIENTE
        )
    )
    _calcular_interno(actual)
    if actual.num_errores:
        raise _error(
            "estado",
            f"La planilla tiene {actual.num_errores} error(es) por corregir antes de cerrarla.",
        )
    if neto_visto is not None and neto_visto != actual.total_neto:
        raise _error(
            "total_neto",
            "La planilla cambió desde la última vez que la vio (asistencia, adelantos o valores "
            "legales). Revísela otra vez y vuelva a cerrarla.",
        )
    ahora = timezone.now()
    cuotas = list(
        CuotaAdelanto.objects.select_for_update().filter(
            pk__in=PlanillaConcepto.objects.filter(
                detalle__planilla=actual, cuota__isnull=False
            ).values("cuota_id")
        )
    )
    for cuota in cuotas:
        cuota.estado = EstadoCuota.DESCONTADA
        cuota.descontada_en = ahora
    CuotaAdelanto.objects.bulk_update(cuotas, ["estado", "descontada_en"])
    contexto = obtener_contexto()
    actual.estado = EstadoPlanilla.CERRADA
    actual.cerrada_en = ahora
    actual.cerrada_por_id = contexto.usuario_id if contexto else None
    actual.save(update_fields=["estado", "cerrada_en", "cerrada_por_id"])
    registrar(
        "rrhh.planilla_cerrada",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Planilla de {actual.periodo:%m/%Y} cerrada",
        detalle={"trabajadores": actual.num_trabajadores, "cuotas_descontadas": len(cuotas)},
    )
    logger.info("planilla_cerrada", extra={"planilla_id": actual.pk})
    return actual


@transaction.atomic
def reabrir(planilla: Planilla, *, motivo: str) -> Planilla:
    """Reabre una planilla cerrada: las cuotas vuelven a «por descontar» y se libera el mes."""
    _exigir_empresa(planilla.empresa_id)
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise _error("motivo", "Indique el motivo de la reapertura.")
    actual = Planilla.objects.select_for_update(of=("self",)).get(pk=planilla.pk)
    if actual.estado != EstadoPlanilla.CERRADA:
        raise _error("estado", "La planilla no está cerrada.")
    posterior = Planilla.objects.filter(
        empresa_id=actual.empresa_id, estado=EstadoPlanilla.CERRADA, periodo__gt=actual.periodo
    ).first()
    if posterior is not None:
        raise _error(
            "estado",
            f"Ya está cerrada la planilla de {posterior.periodo:%m/%Y}: reábrala primero "
            "(la renta de 5.ª depende de los meses anteriores).",
        )
    if PagoPlanilla.objects.filter(planilla=actual, estado=EstadoPago.PAGADO).exists():
        raise _error(
            "estado",
            "La planilla tiene sueldos pagados: anule primero esos pagos para poder reabrirla.",
        )
    cuotas = list(
        CuotaAdelanto.objects.select_for_update().filter(
            pk__in=PlanillaConcepto.objects.filter(
                detalle__planilla=actual, cuota__isnull=False
            ).values("cuota_id"),
            estado=EstadoCuota.DESCONTADA,
        )
    )
    for cuota in cuotas:
        cuota.estado = EstadoCuota.PENDIENTE
        cuota.descontada_en = None
    CuotaAdelanto.objects.bulk_update(cuotas, ["estado", "descontada_en"])
    actual.estado = EstadoPlanilla.BORRADOR
    actual.cerrada_en = None
    actual.cerrada_por_id = None
    actual.reabierta_en = timezone.now()
    actual.motivo_reapertura = motivo[:250]
    actual.save(
        update_fields=[
            "estado",
            "cerrada_en",
            "cerrada_por_id",
            "reabierta_en",
            "motivo_reapertura",
        ]
    )
    registrar(
        "rrhh.planilla_reabierta",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Planilla de {actual.periodo:%m/%Y} reabierta",
        detalle={"motivo": motivo[:200], "cuotas_liberadas": len(cuotas)},
    )
    return actual


@transaction.atomic
def descartar(planilla: Planilla) -> None:
    """Elimina una planilla que todavía está en revisión (no tiene efectos fuera de ella)."""
    actual = _bloquear(planilla)
    PlanillaConcepto.objects.filter(detalle__planilla=actual).delete()
    PlanillaTrabajador.objects.filter(planilla=actual).delete()
    actual.delete()
    registrar(
        "rrhh.planilla_descartada",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Planilla de {actual.periodo:%m/%Y} descartada",
    )


# ---------------------------------------------------------------------------
# Ajustes a mano y cuotas diferidas (solo con la planilla en revisión)
# ---------------------------------------------------------------------------
def conceptos_para_ajuste(organizacion_id: int):
    """Los conceptos que una persona puede agregar a mano a un trabajador."""
    return [
        c
        for c in ConceptoPlanilla.objects.sin_ambito()
        .filter(
            organizacion_id=organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            tipo__in=(TipoConcepto.INGRESO, TipoConcepto.DESCUENTO),
        )
        .order_by("tipo", "orden", "nombre")
        if c.codigo not in RESERVADOS
    ]


@transaction.atomic
def agregar_ajuste(
    planilla: Planilla, *, detalle_id: int, concepto_id: int, monto: Decimal, explicacion: str
) -> Planilla:
    """Agrega un bono, comisión u otro descuento al trabajador y recalcula."""
    actual = _bloquear(planilla)
    detalle = PlanillaTrabajador.objects.filter(pk=detalle_id, planilla=actual).first()
    if detalle is None:
        raise _error("personal", "El trabajador no está en esta planilla.")
    concepto = next(
        (c for c in conceptos_para_ajuste(actual.empresa.organizacion_id) if c.pk == concepto_id),
        None,
    )
    if concepto is None:
        raise _error("concepto", "Elija un concepto de la lista.")
    if not isinstance(monto, Decimal) or monto != monto.quantize(CENTAVO) or monto <= 0:
        raise _error("monto", "Un monto en soles mayor que cero, con hasta 2 decimales.")
    if monto > MAXIMO:
        raise _error("monto", "El monto es demasiado grande.")
    explicacion = " ".join((explicacion or "").split())[:200]
    PlanillaConcepto.objects.create(
        empresa=actual.empresa,
        detalle=detalle,
        concepto=concepto,
        codigo=concepto.codigo,
        nombre=concepto.nombre,
        tipo=concepto.tipo,
        monto=monto,
        explicacion=explicacion,
        manual=True,
    )
    _calcular_interno(actual)
    registrar(
        "rrhh.planilla_ajuste_agregado",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{concepto.nombre} agregado en la planilla de {actual.periodo:%m/%Y}",
        detalle={"trabajador": detalle.personal_id, "concepto": concepto.codigo},
    )
    return actual


@transaction.atomic
def quitar_ajuste(planilla: Planilla, *, linea_id: int) -> Planilla:
    """Quita un renglón agregado a mano y recalcula."""
    actual = _bloquear(planilla)
    linea = PlanillaConcepto.objects.filter(
        pk=linea_id, detalle__planilla=actual, manual=True
    ).first()
    if linea is None:
        raise _error("linea", "Solo se pueden quitar los renglones agregados a mano.")
    linea.delete()
    _calcular_interno(actual)
    registrar(
        "rrhh.planilla_ajuste_quitado",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{linea.nombre} quitado de la planilla de {actual.periodo:%m/%Y}",
        detalle={"trabajador": linea.detalle.personal_id, "concepto": linea.codigo},
    )
    return actual


@transaction.atomic
def diferir_cuota(planilla: Planilla, *, linea_id: int) -> Planilla:
    """Pasa la cuota de un adelanto o préstamo al mes siguiente (si el neto no alcanza)."""
    actual = _bloquear(planilla)
    linea = (
        PlanillaConcepto.objects.select_related("detalle")
        .filter(pk=linea_id, detalle__planilla=actual, cuota__isnull=False)
        .first()
    )
    if linea is None:
        raise _error("linea", "Solo se pueden diferir las cuotas de adelantos y préstamos.")
    cuota = (
        CuotaAdelanto.objects.select_for_update().select_related("adelanto").get(pk=linea.cuota_id)
    )
    if cuota.estado != EstadoCuota.PENDIENTE:
        raise _error("linea", "La cuota ya no está por descontar.")
    siguiente = adelantos.sumar_meses(cuota.periodo, 1)
    if Planilla.objects.filter(
        empresa_id=actual.empresa_id, periodo=siguiente, estado=EstadoPlanilla.CERRADA
    ).exists():
        raise _error("linea", f"La planilla de {siguiente:%m/%Y} ya está cerrada.")
    contrato = trabajadores.contrato_vigente(cuota.adelanto.personal)
    if contrato is None:
        raise _error("linea", "El trabajador ya no tiene un contrato vigente.")
    try:
        adelantos._exigir_cabe_en_sueldo(
            cuota.adelanto.personal, contrato, [(siguiente, cuota.monto)], siguiente
        )
    except ValidationError as exc:
        raise _error("linea", " ".join(exc.messages)) from None
    cuota.periodo = siguiente
    cuota.save(update_fields=["periodo"])
    _calcular_interno(actual)
    registrar(
        "rrhh.planilla_cuota_diferida",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Cuota {cuota.numero} del adelanto N° {cuota.adelanto.numero:06d} pasó a "
        f"{siguiente:%m/%Y}",
    )
    return actual
