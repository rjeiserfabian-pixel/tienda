"""Asistencia diaria de los trabajadores de una empresa.

Reglas:

* Se marca por trabajador y por día con un tipo del catálogo (A, F, DS, V…). Un día sin marca es un
  día sin marcar: el sistema no asume nada y lo muestra como pendiente.
* Solo se marcan días cubiertos por un contrato del trabajador (desde su inicio hasta su cese).
* Las horas extra solo van en días trabajados y son de 0 a 12 por día.
* «Completar el mes» rellena SOLO los días vacíos (nunca pisa lo ya marcado): feriado → FER,
  día de descanso → DS y el resto → A. La persona corrige después lo que no fue así.
"""

import calendar
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import EstadoRegistro, Personal

from . import catalogos
from .cierre import exigir_mes_abierto, mes_cerrado
from .models import (
    AsistenciaDia,
    CategoriaAsistencia,
    CodigoParametro,
    ContratoLaboral,
    Feriado,
    TipoAsistencia,
)

logger = logging.getLogger(__name__)

MAX_DIAS_RANGO = 62  # un rango de días (vacaciones, descanso médico…) no pasa de dos meses
ANIO_MIN, ANIO_MAX = 2000, 2100

DESCANSOS = {
    "DOMINGO": {6},
    "SABADO_DOMINGO": {5, 6},
}
DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


class ErrorAsistencia(ValidationError):
    """Una marca de asistencia no es válida (se muestra junto al campo)."""


def _error(campo: str, mensaje: str) -> ErrorAsistencia:
    return ErrorAsistencia({campo: mensaje})


def _exigir_empresa(empresa_id: int) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa_id):
        raise EmpresaNoHabilitada()


def validar_mes(anio: int, mes: int) -> tuple[date, date]:
    """Primer y último día del mes; error si el año o el mes no tienen sentido."""
    if not ANIO_MIN <= anio <= ANIO_MAX:
        raise _error("anio", "Indique un año válido.")
    if not 1 <= mes <= 12:
        raise _error("mes", "El mes va de 1 a 12.")
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def _dias(desde: date, hasta: date):
    for n in range((hasta - desde).days + 1):
        yield desde + timedelta(days=n)


# ---------------------------------------------------------------------------
# Cobertura: qué días del mes tiene un trabajador con contrato
# ---------------------------------------------------------------------------
def _tramos(contratos: list[ContratoLaboral]) -> list[tuple[date, date | None]]:
    """(inicio, cese) de cada contrato; el cese es ``None`` mientras el contrato siga vigente."""
    return [(c.fecha_inicio, c.fecha_cese) for c in contratos]


def _cubierto(tramos, dia: date) -> bool:
    return any(inicio <= dia and (fin is None or dia <= fin) for inicio, fin in tramos)


def _contratos_por_trabajador(empresa_id: int, desde: date, hasta: date, personal_ids=None):
    """Contratos de la empresa que tocan el rango, agrupados por trabajador."""
    consulta = ContratoLaboral.objects.filter(empresa_id=empresa_id, fecha_inicio__lte=hasta)
    consulta = consulta.exclude(fecha_cese__lt=desde)
    if personal_ids is not None:
        consulta = consulta.filter(personal_id__in=personal_ids)
    por_trabajador = defaultdict(list)
    for contrato in consulta:
        por_trabajador[contrato.personal_id].append(contrato)
    return por_trabajador


def _tipos(organizacion_id: int) -> dict[str, TipoAsistencia]:
    return {
        t.codigo: t
        for t in TipoAsistencia.objects.sin_ambito().filter(
            organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO
        )
    }


def _feriados(organizacion_id: int, desde: date, hasta: date) -> dict[date, str]:
    return {
        f.fecha: f.nombre
        for f in Feriado.objects.sin_ambito().filter(
            organizacion_id=organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            fecha__gte=desde,
            fecha__lte=hasta,
        )
    }


# ---------------------------------------------------------------------------
# Lectura: la grilla del mes
# ---------------------------------------------------------------------------
def grilla(empresa, anio: int, mes: int, *, q: str = "") -> dict:
    """Trabajadores con contrato en el mes (o con marcas), sus marcas y totales por trabajador."""
    desde, hasta = validar_mes(anio, mes)
    org = empresa.organizacion_id
    tipos = list(
        TipoAsistencia.objects.sin_ambito()
        .filter(organizacion_id=org, estado=EstadoRegistro.ACTIVO)
        .order_by("codigo")
    )
    por_id = {t.pk: t for t in tipos}
    feriados = _feriados(org, desde, hasta)
    jornada = catalogos.valor_vigente(org, CodigoParametro.HORAS_JORNADA, hasta)

    contratos = _contratos_por_trabajador(empresa.pk, desde, hasta)
    marcas = defaultdict(dict)
    for m in AsistenciaDia.objects.filter(
        empresa_id=empresa.pk, fecha__gte=desde, fecha__lte=hasta
    ):
        marcas[m.personal_id][m.fecha] = m
    ids = set(contratos) | set(marcas)

    personal = Personal.objects.filter(pk__in=ids).order_by("apellidos", "nombres", "id")
    if q:
        q = " ".join(q.split())
        personal = personal.filter(Q(apellidos__icontains=q) | Q(nombres__icontains=q))

    filas = []
    for p in personal:
        tramos = _tramos(contratos.get(p.pk, []))
        propias = marcas.get(p.pk, {})
        dias, totales = {}, defaultdict(int)
        horas_extra = Decimal("0")
        sin_marcar = 0
        for dia in _dias(desde, hasta):
            cubierto = _cubierto(tramos, dia)
            marca = propias.get(dia)
            if marca is None:
                sin_marcar += int(cubierto)
                continue
            tipo = por_id.get(marca.tipo_id)
            dias[dia.isoformat()] = {
                "tipo": tipo.codigo if tipo else "?",
                "horas_extra": marca.horas_extra,
                "observacion": marca.observacion,
            }
            if tipo:
                totales[tipo.categoria] += 1
                totales["laborados"] += int(tipo.cuenta_dia_laborado)
                totales["pagados"] += int(tipo.se_paga)
            horas_extra += marca.horas_extra
        laborados = totales["laborados"]
        filas.append(
            {
                "id": p.pk,
                "nombre_completo": p.nombre_completo,
                "numero_documento": p.numero_documento,
                "cubiertos": [
                    dia.isoformat() for dia in _dias(desde, hasta) if _cubierto(tramos, dia)
                ],
                "dias": dias,
                "totales": {
                    "laborados": laborados,
                    "pagados": totales["pagados"],
                    "faltas": totales[CategoriaAsistencia.FALTA],
                    "descanso_medico": totales[CategoriaAsistencia.DESCANSO_MEDICO],
                    "vacaciones": totales[CategoriaAsistencia.VACACIONES],
                    "feriados": totales[CategoriaAsistencia.FERIADO],
                    "descansos": totales[CategoriaAsistencia.DESCANSO_SEMANAL],
                    "horas_extra": horas_extra,
                    "sin_marcar": sin_marcar,
                    "horas_trabajadas": None if jornada is None else Decimal(laborados) * jornada,
                },
            }
        )
    return {
        "anio": anio,
        "mes": mes,
        "cerrado": mes_cerrado(empresa.pk, desde),
        "dias": [
            {
                "fecha": d.isoformat(),
                "numero": d.day,
                "semana": DIAS_SEMANA[d.weekday()],
                "descanso_semanal": d.weekday() == 6,
                "feriado": feriados.get(d, ""),
            }
            for d in _dias(desde, hasta)
        ],
        "tipos": [
            {
                "id": t.pk,
                "codigo": t.codigo,
                "nombre": t.nombre,
                "categoria": t.categoria,
                "se_paga": t.se_paga,
                "cuenta_dia_laborado": t.cuenta_dia_laborado,
            }
            for t in tipos
        ],
        "trabajadores": filas,
    }


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------
def _trabajador(empresa_id: int, personal_id: int) -> Personal:
    personal = Personal.objects.filter(pk=personal_id, empresa_id=empresa_id).first()
    if personal is None:
        raise _error("personal", "El trabajador no es de esta empresa.")
    return personal


def _tipo(organizacion_id: int, tipo_id: int) -> TipoAsistencia:
    tipo = (
        TipoAsistencia.objects.sin_ambito()
        .filter(pk=tipo_id, organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO)
        .first()
    )
    if tipo is None:
        raise _error("tipo", "Elija un tipo de asistencia de la lista.")
    return tipo


def _exigir_cobertura(personal: Personal, dia: date) -> None:
    contratos = list(ContratoLaboral.objects.filter(personal=personal))
    if not _cubierto(_tramos(contratos), dia):
        raise _error(
            "fecha",
            f"{dia:%d/%m/%Y}: el trabajador no tenía contrato ese día.",
        )


@transaction.atomic
def marcar_dia(
    personal: Personal,
    fecha: date,
    *,
    tipo_id: int | None,
    horas_extra: Decimal = Decimal("0"),
    observacion: str = "",
) -> AsistenciaDia | None:
    """Marca (o cambia) el día de un trabajador. ``tipo_id=None`` borra la marca."""
    _exigir_empresa(personal.empresa_id)
    exigir_mes_abierto(personal.empresa_id, fecha, ErrorAsistencia, "fecha")
    personal = Personal.objects.select_for_update().select_related("empresa").get(pk=personal.pk)
    actual = (
        AsistenciaDia.objects.select_for_update().filter(personal=personal, fecha=fecha).first()
    )
    if tipo_id is None:
        if actual is not None:
            actual.delete()
            registrar(
                "rrhh.asistencia_borrada",
                recurso_tipo="personal",
                recurso_id=personal.pk,
                empresa_id=personal.empresa_id,
                resumen=f"Marca del {fecha:%d/%m/%Y} de {personal.nombre_completo} borrada",
            )
        return None
    tipo = _tipo(personal.empresa.organizacion_id, tipo_id)
    _exigir_cobertura(personal, fecha)
    nueva = actual is None
    fila = actual or AsistenciaDia(empresa=personal.empresa, personal=personal, fecha=fecha)
    fila.tipo = tipo
    fila.horas_extra = horas_extra
    fila.observacion = " ".join((observacion or "").split())[:100]
    try:
        fila.full_clean(validate_unique=False, validate_constraints=False)
        with transaction.atomic():
            fila.save()
    except ValidationError as error:
        raise ErrorAsistencia(error.message_dict) from None
    except IntegrityError:
        raise _error("fecha", "Ese día ya tiene una marca: vuelva a abrir la pantalla.") from None
    registrar(
        "rrhh.asistencia_marcada" if nueva else "rrhh.asistencia_cambiada",
        recurso_tipo="personal",
        recurso_id=personal.pk,
        empresa_id=personal.empresa_id,
        resumen=f"{personal.nombre_completo}: {fecha:%d/%m/%Y} = {tipo.codigo}",
        detalle={"tipo": tipo.codigo, "horas_extra": str(fila.horas_extra)},
    )
    return fila


@transaction.atomic
def marcar_rango(
    personal: Personal, desde: date, hasta: date, *, tipo_id: int, sobrescribir: bool
) -> int:
    """Marca varios días seguidos (vacaciones, descanso médico…). Devuelve cuántos marcó.

    Salta los días sin contrato; los ya marcados se conservan salvo que ``sobrescribir``.
    """
    _exigir_empresa(personal.empresa_id)
    if hasta < desde:
        raise _error("hasta", "No puede ser anterior al primer día.")
    if (hasta - desde).days + 1 > MAX_DIAS_RANGO:
        raise _error("hasta", f"El rango no puede pasar de {MAX_DIAS_RANGO} días.")
    for extremo in {desde.replace(day=1), hasta.replace(day=1)}:
        exigir_mes_abierto(personal.empresa_id, extremo, ErrorAsistencia, "desde")
    personal = Personal.objects.select_for_update().select_related("empresa").get(pk=personal.pk)
    tipo = _tipo(personal.empresa.organizacion_id, tipo_id)
    tramos = _tramos(list(ContratoLaboral.objects.filter(personal=personal)))
    existentes = {
        m.fecha: m
        for m in AsistenciaDia.objects.select_for_update().filter(
            personal=personal, fecha__gte=desde, fecha__lte=hasta
        )
    }
    marcados = 0
    for dia in _dias(desde, hasta):
        if not _cubierto(tramos, dia):
            continue
        fila = existentes.get(dia)
        if fila is not None and not sobrescribir:
            continue
        if fila is None:
            fila = AsistenciaDia(empresa=personal.empresa, personal=personal, fecha=dia)
        fila.tipo = tipo
        fila.horas_extra = Decimal("0")
        fila.observacion = ""
        fila.save()
        marcados += 1
    if marcados == 0:
        raise _error("desde", "Ningún día del rango se pudo marcar (sin contrato o ya marcados).")
    registrar(
        "rrhh.asistencia_rango",
        recurso_tipo="personal",
        recurso_id=personal.pk,
        empresa_id=personal.empresa_id,
        resumen=f"{personal.nombre_completo}: {tipo.codigo} del {desde:%d/%m/%Y} "
        f"al {hasta:%d/%m/%Y} ({marcados} día(s))",
    )
    return marcados


@transaction.atomic
def completar_mes(empresa, anio: int, mes: int, *, descanso: str, personal_ids=None) -> dict:
    """Rellena los días VACÍOS del mes con A, DS o FER. Nunca pisa lo ya marcado."""
    _exigir_empresa(empresa.pk)
    desde, hasta = validar_mes(anio, mes)
    exigir_mes_abierto(empresa.pk, desde, ErrorAsistencia, "mes")
    if descanso not in DESCANSOS:
        raise _error("descanso", "Elija el descanso semanal.")
    org = empresa.organizacion_id
    tipos = _tipos(org)
    faltan = [c for c in ("A", "DS", "FER") if c not in tipos]
    if faltan:
        raise _error(
            "tipo",
            f"Faltan tipos de asistencia activos para completar el mes: {', '.join(faltan)}.",
        )
    feriados = _feriados(org, desde, hasta)
    contratos = _contratos_por_trabajador(empresa.pk, desde, hasta, personal_ids)
    if not contratos:
        raise _error("personal", "No hay trabajadores con contrato en ese mes.")
    existentes = defaultdict(set)
    for personal_id, fecha in AsistenciaDia.objects.filter(
        empresa_id=empresa.pk, fecha__gte=desde, fecha__lte=hasta, personal_id__in=list(contratos)
    ).values_list("personal_id", "fecha"):
        existentes[personal_id].add(fecha)

    personal = {p.pk: p for p in Personal.objects.filter(pk__in=list(contratos))}
    nuevas = []
    for personal_id, lista in contratos.items():
        tramos = _tramos(lista)
        for dia in _dias(desde, hasta):
            if dia in existentes[personal_id] or not _cubierto(tramos, dia):
                continue
            if dia in feriados:
                codigo = "FER"
            elif dia.weekday() in DESCANSOS[descanso]:
                codigo = "DS"
            else:
                codigo = "A"
            nuevas.append(
                AsistenciaDia(
                    empresa=empresa,
                    personal=personal[personal_id],
                    fecha=dia,
                    tipo=tipos[codigo],
                )
            )
    AsistenciaDia.objects.bulk_create(nuevas)
    registrar(
        "rrhh.asistencia_completada",
        recurso_tipo="empresa",
        recurso_id=empresa.pk,
        empresa_id=empresa.pk,
        resumen=f"Asistencia de {mes:02d}/{anio} completada: {len(nuevas)} día(s) marcados",
        detalle={"trabajadores": len(contratos), "dias": len(nuevas)},
    )
    return {"trabajadores": len(contratos), "dias": len(nuevas)}
