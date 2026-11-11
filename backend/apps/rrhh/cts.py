"""CTS (compensación por tiempo de servicios): cálculo del semestre y su depósito.

Criterio (a confirmar con el contador):

* Hay dos cálculos al año: el de MAYO cubre de noviembre a abril y el de NOVIEMBRE, de mayo a
  octubre. Se calcula cuando el semestre ya terminó.
* Remuneración computable = sueldo + asignación familiar + 1/6 de la última gratificación (la de
  diciembre para mayo, la de julio para noviembre), tomada de la planilla cerrada de ese mes; si
  esa planilla no existe se estima con el factor del régimen y se avisa.
* Monto = remuneración computable ÷ 12 por cada mes completo + ÷ 360 por cada día sobrante, menos
  ÷ 360 por cada falta, por los sueldos de CTS al año del régimen (1 en el general, 0.5 en la
  pequeña empresa). Hace falta al menos un mes completo.
* Quien cesó dentro del semestre no entra: su CTS va en su liquidación, que se calcula aparte.
* El depósito sale de una caja o cuenta en soles (un egreso de Caja por trabajador); no se guarda
  nada si Caja rechaza alguno. No considera promedios de comisiones ni horas extra.
"""

import calendar
import logging
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import CuentaFinanciera, Personal

from . import catalogos, trabajadores
from .asistencia import _cubierto, _dias, _tramos
from .models import (
    AsistenciaDia,
    CodigoParametro,
    ContratoLaboral,
    DepositoCts,
    DepositoCtsTrabajador,
    EstadoDepositoCts,
    EstadoPlanilla,
    PeriodoCts,
    PlanillaConcepto,
    TipoAsistencia,
)

logger = logging.getLogger(__name__)

CENTAVO = Decimal("0.01")
CIEN = Decimal("100")
ERROR = "ERROR"
AVISO = "AVISO"


class ErrorCts(ValidationError):
    """Algo impide hacer la operación con la CTS (se muestra al usuario)."""


def _error(campo: str, mensaje: str) -> ErrorCts:
    return ErrorCts({campo: mensaje})


def _exigir_empresa(empresa_id: int) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa_id):
        raise EmpresaNoHabilitada()


def _red(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _soles(valor: Decimal) -> str:
    return f"S/ {valor:,.2f}"


def rango_del_periodo(anio: int, periodo: str) -> tuple[date, date]:
    """Primer y último día del semestre que cubre la CTS."""
    if periodo == PeriodoCts.MAYO:
        return date(anio - 1, 11, 1), date(anio, 4, 30)
    return date(anio, 5, 1), date(anio, 10, 31)


def mes_de_gratificacion(anio: int, periodo: str) -> date:
    """El mes de la última gratificación: diciembre para mayo y julio para noviembre."""
    return date(anio - 1, 12, 1) if periodo == PeriodoCts.MAYO else date(anio, 7, 1)


def _sexto_de_gratificacion(deposito, personal, contratos, regimen, sueldo, avisos) -> Decimal:
    """1/6 de la gratificación del mes previo (real si hay planilla cerrada, si no, estimada)."""
    mes = mes_de_gratificacion(deposito.anio, deposito.periodo)
    linea = (
        PlanillaConcepto.objects.filter(
            detalle__planilla__empresa_id=deposito.empresa_id,
            detalle__planilla__periodo=mes,
            detalle__planilla__estado=EstadoPlanilla.CERRADA,
            detalle__planilla__eliminado_en__isnull=True,
            detalle__eliminado_en__isnull=True,
            detalle__personal=personal,
            codigo="GRATIFICACION",
        )
        .values_list("monto", flat=True)
        .first()
    )
    if linea is not None:
        return linea / 6
    # Sin planilla cerrada: se estima, pero solo si ya trabajaba cuando se pagó.
    if _cubierto(_tramos(contratos), mes.replace(day=15)):
        avisos.append(
            {
                "nivel": AVISO,
                "texto": f"No hay planilla cerrada de {mes:%m/%Y}: la gratificación se estimó "
                f"con el sueldo y el factor del régimen ({regimen.factor_gratificacion}).",
            }
        )
        return sueldo * regimen.factor_gratificacion / 6
    return Decimal("0")


def _calcular_interno(deposito: DepositoCts) -> DepositoCts:
    """Recalcula la CTS de todos los trabajadores del semestre. Ya está bloqueado y en revisión."""
    empresa = deposito.empresa
    org = empresa.organizacion_id
    inicio, fin = rango_del_periodo(deposito.anio, deposito.periodo)
    tipos = {t.pk: t for t in TipoAsistencia.objects.sin_ambito().filter(organizacion_id=org)}
    rmv = catalogos.valor_vigente(org, CodigoParametro.RMV, fin)
    porcentaje_af = catalogos.valor_vigente(org, CodigoParametro.ASIGNACION_FAMILIAR, fin)

    contratos: dict[int, list[ContratoLaboral]] = defaultdict(list)
    for contrato in (
        ContratoLaboral.objects.filter(empresa_id=empresa.pk, fecha_inicio__lte=fin)
        .exclude(fecha_cese__lt=inicio)
        .select_related("regimen")
    ):
        contratos[contrato.personal_id].append(contrato)
    personas = Personal.objects.filter(pk__in=list(contratos)).select_related("datos_laborales")
    faltas: dict[int, list[date]] = defaultdict(list)
    for personal_id, fecha, tipo_id in AsistenciaDia.objects.filter(
        empresa_id=empresa.pk, personal_id__in=list(contratos), fecha__gte=inicio, fecha__lte=fin
    ).values_list("personal_id", "fecha", "tipo_id"):
        tipo = tipos.get(tipo_id)
        if tipo is not None and not tipo.se_paga:
            faltas[personal_id].append(fecha)

    DepositoCtsTrabajador.objects.filter(deposito=deposito).delete()
    filas = []
    for personal in sorted(personas, key=lambda p: (p.apellidos, p.nombres, p.pk)):
        propios = contratos[personal.pk]
        avisos: list[dict] = []
        ultimo = max(propios, key=lambda c: (c.fecha_inicio, c.pk))
        regimen = ultimo.regimen
        tramos = _tramos(propios)
        meses = dias = 0
        for numero in range(6):  # el semestre tiene seis meses
            anio = inicio.year + (inicio.month - 1 + numero) // 12
            mes = (inicio.month - 1 + numero) % 12 + 1
            largo = calendar.monthrange(anio, mes)[1]
            cubiertos = sum(
                1 for d in _dias(date(anio, mes, 1), date(anio, mes, largo)) if _cubierto(tramos, d)
            )
            if cubiertos == largo:
                meses += 1
            else:
                dias += cubiertos
        propias = [f for f in faltas.get(personal.pk, []) if _cubierto(tramos, f)]
        fila = DepositoCtsTrabajador(
            empresa=empresa,
            deposito=deposito,
            personal=personal,
            regimen_nombre=regimen.nombre,
            meses=meses,
            dias=dias,
            dias_falta=len(propias),
        )
        if ultimo.fecha_cese is not None and ultimo.fecha_cese <= fin:
            avisos.append(
                {
                    "nivel": AVISO,
                    "texto": f"Cesó el {ultimo.fecha_cese:%d/%m/%Y}: su CTS va en su liquidación, "
                    "que se calcula aparte con el contador.",
                }
            )
        elif meses == 0:
            avisos.append(
                {
                    "nivel": AVISO,
                    "texto": "No tiene un mes completo en el semestre: no le corresponde.",
                }
            )
        elif not regimen.factor_cts:
            avisos.append({"nivel": AVISO, "texto": "Su régimen no paga CTS."})
        else:
            sueldo = trabajadores.sueldo_vigente(ultimo, min(fin, ultimo.fecha_cese or fin))
            datos = getattr(personal, "datos_laborales", None)
            if sueldo is None:
                avisos.append(
                    {"nivel": ERROR, "texto": "No tiene un sueldo registrado en su contrato."}
                )
            else:
                asignacion = Decimal("0")
                if datos is not None and datos.asignacion_familiar:
                    if rmv is None or porcentaje_af is None:
                        avisos.append(
                            {
                                "nivel": ERROR,
                                "texto": "Falta cargar la RMV o la asignación familiar.",
                            }
                        )
                    else:
                        asignacion = _red(rmv * porcentaje_af / CIEN)
                sexto = _red(
                    _sexto_de_gratificacion(deposito, personal, propios, regimen, sueldo, avisos)
                )
                computable = sueldo + asignacion + sexto
                bruto = computable / 12 * meses + computable / 360 * dias
                bruto -= computable / 360 * len(propias)
                fila.sueldo, fila.asignacion_familiar = sueldo, asignacion
                fila.sexto_gratificacion, fila.remuneracion_computable = sexto, computable
                fila.monto = _red(max(bruto, Decimal("0")) * regimen.factor_cts)
                if propias:
                    avisos.append(
                        {
                            "nivel": AVISO,
                            "texto": f"Se descontaron {len(propias)} falta(s) del semestre.",
                        }
                    )
        fila.avisos = avisos
        filas.append(fila)
    DepositoCtsTrabajador.objects.bulk_create(filas)

    todos = [a for f in filas for a in f.avisos]
    deposito.num_trabajadores = len(filas)
    deposito.total = sum((f.monto for f in filas), Decimal("0"))
    deposito.num_errores = sum(1 for a in todos if a["nivel"] == ERROR)
    deposito.num_avisos = sum(1 for a in todos if a["nivel"] == AVISO)
    deposito.calculado_en = timezone.now()
    deposito.save()
    return deposito


def _bloquear(deposito: DepositoCts) -> DepositoCts:
    _exigir_empresa(deposito.empresa_id)
    actual = (
        DepositoCts.objects.select_for_update(of=("self",))
        .select_related("empresa")
        .get(pk=deposito.pk)
    )
    if actual.estado != EstadoDepositoCts.CALCULADO:
        raise _error("estado", "La CTS ya está depositada. Anule el depósito para cambiarla.")
    return actual


@transaction.atomic
def crear_calculo(*, empresa, anio: int, periodo: str) -> DepositoCts:
    """Calcula la CTS de un semestre ya terminado."""
    _exigir_empresa(empresa.pk)
    if periodo not in PeriodoCts.values:
        raise _error("periodo", "Elija mayo o noviembre.")
    if not 2000 <= anio <= 2100:
        raise _error("anio", "Indique un año válido.")
    _, fin = rango_del_periodo(anio, periodo)
    if fin >= timezone.localdate():
        raise _error(
            "periodo", f"Ese semestre termina el {fin:%d/%m/%Y}: aún no se puede calcular."
        )
    try:
        with transaction.atomic():
            deposito = DepositoCts.objects.create(empresa=empresa, anio=anio, periodo=periodo)
    except IntegrityError:
        raise _error("periodo", "Ya existe el cálculo de la CTS de ese periodo.") from None
    deposito = _bloquear(deposito)
    _calcular_interno(deposito)
    registrar(
        "rrhh.cts_calculada",
        recurso_tipo="cts",
        recurso_id=deposito.pk,
        empresa_id=empresa.pk,
        resumen=f"CTS de {deposito.get_periodo_display()} {anio} calculada",
        detalle={"trabajadores": deposito.num_trabajadores, "errores": deposito.num_errores},
    )
    return deposito


@transaction.atomic
def recalcular(deposito: DepositoCts) -> DepositoCts:
    actual = _bloquear(deposito)
    _calcular_interno(actual)
    registrar(
        "rrhh.cts_recalculada",
        recurso_tipo="cts",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"CTS de {actual.get_periodo_display()} {actual.anio} recalculada",
    )
    return actual


@transaction.atomic
def descartar(deposito: DepositoCts) -> None:
    actual = _bloquear(deposito)
    DepositoCtsTrabajador.objects.filter(deposito=actual).delete()
    actual.delete()
    registrar(
        "rrhh.cts_descartada",
        recurso_tipo="cts",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"CTS de {actual.get_periodo_display()} {actual.anio} descartada",
    )


@transaction.atomic
def depositar(
    deposito: DepositoCts,
    *,
    fecha: date,
    cuenta: CuentaFinanciera,
    medio_pago=None,
    referencia: str = "",
    total_visto: Decimal | None = None,
) -> DepositoCts:
    """Registra el depósito: un egreso de Caja por trabajador. Recalcula antes de depositar."""
    actual = _bloquear(deposito)
    if fecha > timezone.localdate():
        raise _error("fecha", "La fecha del depósito no puede ser futura.")
    if cuenta.empresa_id != actual.empresa_id:
        raise _error("cuenta", "Elija una caja o cuenta de la empresa.")
    if cuenta.moneda != CuentaFinanciera.Moneda.PEN:
        raise _error("cuenta", "Elija una caja o cuenta en soles.")
    _calcular_interno(actual)
    if actual.num_errores:
        raise _error(
            "estado", f"Hay {actual.num_errores} error(es) por corregir antes de depositar."
        )
    if total_visto is not None and total_visto != actual.total:
        raise _error(
            "total",
            "La CTS cambió desde la última vez que la vio. Revísela otra vez y vuelva a depositar.",
        )
    filas = list(
        DepositoCtsTrabajador.objects.select_related("personal").filter(
            deposito=actual, monto__gt=0
        )
    )
    if not filas:
        raise _error("estado", "No hay nada que depositar.")
    referencia = " ".join((referencia or "").split())[:60]
    for fila in filas:
        # Si Caja no puede (sin saldo, sesión cerrada…), la transacción entera se revierte.
        caja.registrar_deposito_de_cts(
            empresa=actual.empresa,
            cuenta=cuenta,
            monto=fila.monto,
            fecha=fecha,
            referencia=referencia,
            glosa=f"CTS {actual.get_periodo_display()} {actual.anio}: "
            f"{fila.personal.nombre_completo}",
            cts_id=fila.pk,
            medio_pago=medio_pago,
        )
    actual.estado = EstadoDepositoCts.DEPOSITADO
    actual.fecha_deposito = fecha
    actual.cuenta = cuenta
    actual.medio_pago = medio_pago
    actual.referencia = referencia
    actual.save()
    registrar(
        "rrhh.cts_depositada",
        recurso_tipo="cts",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"CTS de {actual.get_periodo_display()} {actual.anio} depositada: "
        f"{len(filas)} trabajador(es)",
        detalle={"trabajadores": len(filas)},
    )
    return actual


@transaction.atomic
def anular_deposito(deposito: DepositoCts, *, motivo: str) -> DepositoCts:
    """Deshace el depósito: el dinero vuelve a la caja y el cálculo queda otra vez en revisión."""
    _exigir_empresa(deposito.empresa_id)
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise _error("motivo", "Indique el motivo de la anulación.")
    actual = DepositoCts.objects.select_for_update(of=("self",)).get(pk=deposito.pk)
    if actual.estado != EstadoDepositoCts.DEPOSITADO:
        raise _error("estado", "La CTS no está depositada.")
    for fila in DepositoCtsTrabajador.objects.filter(deposito=actual, monto__gt=0):
        caja.anular_por_origen(
            Origen.DEPOSITO_CTS, fila.pk, motivo=f"Depósito de CTS anulado: {motivo}"
        )
    actual.estado = EstadoDepositoCts.CALCULADO
    actual.fecha_deposito = None
    actual.cuenta = None
    actual.medio_pago = None
    actual.referencia = ""
    actual.save()
    registrar(
        "rrhh.cts_deposito_anulado",
        recurso_tipo="cts",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Depósito de CTS de {actual.get_periodo_display()} {actual.anio} anulado",
        detalle={"motivo": motivo[:200]},
    )
    return actual
