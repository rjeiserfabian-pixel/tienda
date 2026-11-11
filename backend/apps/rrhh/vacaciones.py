"""Vacaciones de los trabajadores: saldo de días y registro de las que se toman.

Criterio (a confirmar con el contador):

* Los días ganados crecen mes a mes: los días anuales del régimen (30 en el general, 15 en la
  pequeña empresa) por los meses completos de servicio ÷ 12. El servicio cuenta desde el inicio del
  primer contrato del trabajador en la empresa.
* El saldo es lo ganado menos lo ya tomado. No se registra más de lo que hay en saldo.
* Registrar vacaciones marca esos días como «V» en la asistencia (el sueldo se paga normal en esos
  días). Las vacaciones antiguas se pueden registrar sin tocar la asistencia.
* Anular quita esas marcas, siempre que la planilla del mes no esté cerrada.
* No se calcula aquí el pago de vacaciones truncas al cesar: eso va en la liquidación.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Min, Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar as auditar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import EstadoRegistro, Personal

from . import asistencia
from .cierre import exigir_mes_abierto
from .models import (
    AsistenciaDia,
    CategoriaAsistencia,
    ContratoLaboral,
    EstadoVacacion,
    TipoAsistencia,
    VacacionPersonal,
)

logger = logging.getLogger(__name__)

MAX_DIAS = 60
CENTESIMO = Decimal("0.01")


class ErrorVacacion(ValidationError):
    """Un dato de las vacaciones no es válido (se muestra junto al campo)."""


def _error(campo: str, mensaje: str) -> ErrorVacacion:
    return ErrorVacacion({campo: mensaje})


def _exigir_empresa(empresa_id: int) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa_id):
        raise EmpresaNoHabilitada()


def meses_completos(inicio: date, hasta: date) -> int:
    """Meses completos entre dos fechas (el día de inicio cuenta como primer día)."""
    if hasta < inicio:
        return 0
    meses = (hasta.year - inicio.year) * 12 + (hasta.month - inicio.month)
    return max(meses - (1 if hasta.day < inicio.day else 0), 0)


def saldos_de(personal_ids: list[int], hoy: date | None = None) -> dict[int, dict]:
    """Días ganados, tomados y saldo de cada trabajador (los que no tienen contrato no salen)."""
    hoy = hoy or timezone.localdate()
    if not personal_ids:
        return {}
    inicios = dict(
        ContratoLaboral.objects.filter(personal_id__in=personal_ids)
        .values("personal_id")
        .annotate(inicio=Min("fecha_inicio"))
        .values_list("personal_id", "inicio")
    )
    anuales: dict[int, int] = {}
    for contrato in (
        ContratoLaboral.objects.filter(personal_id__in=personal_ids)
        .select_related("regimen")
        .order_by("personal_id", "-fecha_inicio", "-id")
    ):
        anuales.setdefault(contrato.personal_id, contrato.regimen.dias_vacaciones)
    tomados = defaultdict(int)
    for fila in (
        VacacionPersonal.objects.filter(
            personal_id__in=personal_ids, estado=EstadoVacacion.REGISTRADA
        )
        .values("personal_id")
        .annotate(total=Sum("dias"))
    ):
        tomados[fila["personal_id"]] = fila["total"]
    resultado = {}
    for personal_id, inicio in inicios.items():
        meses = meses_completos(inicio, hoy)
        ganados = (Decimal(anuales[personal_id]) * meses / 12).quantize(
            CENTESIMO, rounding=ROUND_HALF_UP
        )
        resultado[personal_id] = {
            "inicio_servicio": inicio,
            "meses_servicio": meses,
            "dias_anuales": anuales[personal_id],
            "ganados": ganados,
            "tomados": tomados[personal_id],
            "saldo": ganados - tomados[personal_id],
        }
    return resultado


def _tipo_vacaciones(organizacion_id: int) -> TipoAsistencia:
    tipos = TipoAsistencia.objects.sin_ambito().filter(
        organizacion_id=organizacion_id,
        estado=EstadoRegistro.ACTIVO,
        categoria=CategoriaAsistencia.VACACIONES,
    )
    tipo = tipos.filter(codigo="V").first() or tipos.order_by("codigo").first()
    if tipo is None:
        raise _error("marcar_asistencia", "No hay un tipo de asistencia de vacaciones activo.")
    return tipo


@transaction.atomic
def registrar(
    *,
    personal: Personal,
    desde: date,
    hasta: date,
    observacion: str = "",
    marcar_asistencia: bool = True,
) -> VacacionPersonal:
    """Registra las vacaciones que toma un trabajador y, si se pide, las marca en la asistencia."""
    _exigir_empresa(personal.empresa_id)
    personal = Personal.objects.select_for_update().select_related("empresa").get(pk=personal.pk)
    if personal.estado != EstadoRegistro.ACTIVO:
        raise _error("personal", "El trabajador está inactivo.")
    if hasta < desde:
        raise _error("hasta", "No puede ser anterior al primer día.")
    dias = (hasta - desde).days + 1
    if dias > MAX_DIAS:
        raise _error("hasta", f"Las vacaciones no pasan de {MAX_DIAS} días seguidos.")
    saldo = saldos_de([personal.pk]).get(personal.pk)
    if saldo is None:
        raise _error("personal", "El trabajador no tiene contrato.")
    if desde < saldo["inicio_servicio"]:
        raise _error("desde", "No puede ser anterior al inicio de su servicio.")
    cruce = VacacionPersonal.objects.filter(
        personal=personal,
        estado=EstadoVacacion.REGISTRADA,
        desde__lte=hasta,
        hasta__gte=desde,
    ).first()
    if cruce is not None:
        raise _error(
            "desde",
            f"Se cruza con unas vacaciones ya registradas ({cruce.desde:%d/%m/%Y} al "
            f"{cruce.hasta:%d/%m/%Y}).",
        )
    if dias > saldo["saldo"]:
        raise _error(
            "hasta",
            f"Solo tiene {saldo['saldo']:.2f} día(s) de saldo y pide {dias}.",
        )
    if marcar_asistencia:
        tipo = _tipo_vacaciones(personal.empresa.organizacion_id)
        try:
            asistencia.marcar_rango(personal, desde, hasta, tipo_id=tipo.pk, sobrescribir=True)
        except ValidationError as error:
            raise ErrorVacacion(error.message_dict) from None
    vacacion = VacacionPersonal.objects.create(
        empresa=personal.empresa,
        personal=personal,
        desde=desde,
        hasta=hasta,
        dias=dias,
        marco_asistencia=marcar_asistencia,
        observacion=" ".join((observacion or "").split())[:150],
    )
    auditar(
        "rrhh.vacaciones_registradas",
        recurso_tipo="personal",
        recurso_id=personal.pk,
        empresa_id=personal.empresa_id,
        resumen=f"Vacaciones de {personal.nombre_completo}: {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
        detalle={"dias": dias, "marco_asistencia": marcar_asistencia},
    )
    return vacacion


def _meses_del_rango(desde: date, hasta: date):
    actual = desde.replace(day=1)
    while actual <= hasta:
        yield actual
        actual = (actual + timedelta(days=32)).replace(day=1)


@transaction.atomic
def anular(vacacion: VacacionPersonal, *, motivo: str) -> VacacionPersonal:
    """Anula las vacaciones: los días vuelven al saldo y se quitan sus marcas de la asistencia."""
    _exigir_empresa(vacacion.empresa_id)
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise _error("motivo", "Indique el motivo de la anulación.")
    actual = VacacionPersonal.objects.select_for_update().get(pk=vacacion.pk)
    if actual.estado == EstadoVacacion.ANULADA:
        raise _error("estado", "Las vacaciones ya están anuladas.")
    if actual.marco_asistencia:
        for mes in _meses_del_rango(actual.desde, actual.hasta):
            exigir_mes_abierto(actual.empresa_id, mes, ErrorVacacion, "estado")
        AsistenciaDia.objects.filter(
            personal_id=actual.personal_id,
            fecha__gte=actual.desde,
            fecha__lte=actual.hasta,
            tipo__categoria=CategoriaAsistencia.VACACIONES,
        ).delete()
    actual.estado = EstadoVacacion.ANULADA
    actual.anulado_en = timezone.now()
    actual.motivo_anulacion = motivo[:250]
    actual.save(update_fields=["estado", "anulado_en", "motivo_anulacion"])
    auditar(
        "rrhh.vacaciones_anuladas",
        recurso_tipo="personal",
        recurso_id=actual.personal_id,
        empresa_id=actual.empresa_id,
        resumen="Vacaciones anuladas",
        detalle={"motivo": motivo[:200], "dias": actual.dias},
    )
    return actual
