"""Cierre mensual del inventario.

Un periodo cerrado (AAAAMM) no admite movimientos nuevos ni anulaciones con esa fecha, para que
los libros que el contador ya usó no cambien. Se cierran en orden, del más antiguo al más
reciente, y solo se reabre el último cerrado. Así registrar o recalcular un movimiento nunca
toca meses cerrados: un periodo cerrado posterior a la fecha del movimiento lo impide.
"""

import logging
import re
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.organizacion.models import Empresa

from . import numeracion
from .exceptions import CierreFueraDeOrden, PeriodoCerrado, PeriodoInvalido
from .models import CierrePeriodo, MovimientoInventario

logger = logging.getLogger(__name__)

_FORMATO = re.compile(r"\d{4}(0[1-9]|1[0-2])")


def periodo_de(fecha: date) -> str:
    return f"{fecha:%Y%m}"


def etiqueta(periodo: str) -> str:
    return f"{periodo[4:]}/{periodo[:4]}"


def exigir_empresa(empresa: Empresa) -> None:
    """La empresa debe estar entre las habilitadas del usuario que opera."""
    if not obtener_contexto_requerido().empresa_habilitada(empresa.pk):
        raise EmpresaNoHabilitada()


def validar_formato(periodo: str) -> str:
    if not isinstance(periodo, str) or not _FORMATO.fullmatch(periodo):
        raise PeriodoInvalido()
    return periodo


def exigir_abierto(empresa_id: int, fecha: date) -> None:
    """Rechaza una fecha que cae en un periodo cerrado o anterior a uno ya cerrado."""
    cerrado = (
        CierrePeriodo.objects.filter(empresa_id=empresa_id, periodo__gte=periodo_de(fecha))
        .order_by("-periodo")
        .values_list("periodo", flat=True)
        .first()
    )
    if cerrado is not None:
        raise PeriodoCerrado(
            f"El periodo {etiqueta(cerrado)} ya está cerrado. Registre el movimiento con una "
            "fecha posterior (por ejemplo la de hoy) y deje la fecha del comprobante "
            "como referencia."
        )


def cerrados(empresa: Empresa) -> list[str]:
    return list(
        CierrePeriodo.objects.filter(empresa=empresa)
        .order_by("periodo")
        .values_list("periodo", flat=True)
    )


@transaction.atomic
def cerrar_periodo(empresa: Empresa, periodo: str) -> CierrePeriodo:
    exigir_empresa(empresa)
    validar_formato(periodo)
    if periodo >= periodo_de(timezone.localdate()):
        raise PeriodoInvalido("Solo se pueden cerrar meses que ya terminaron.")
    numeracion.bloquear(empresa)  # cerrojo por empresa: ningún movimiento se cuela mientras tanto
    if CierrePeriodo.objects.filter(empresa=empresa, periodo=periodo).exists():
        raise PeriodoCerrado(f"El periodo {etiqueta(periodo)} ya está cerrado.")
    pendiente = (
        MovimientoInventario.objects.filter(empresa=empresa, periodo__lt=periodo)
        .exclude(periodo__in=CierrePeriodo.objects.filter(empresa=empresa).values("periodo"))
        .order_by("periodo")
        .values_list("periodo", flat=True)
        .first()
    )
    if pendiente is not None:
        raise CierreFueraDeOrden(f"Cierre primero el periodo {etiqueta(pendiente)}.")
    cierre = CierrePeriodo.objects.create(empresa=empresa, periodo=periodo)
    registrar(
        "inventario.periodo_cerrado",
        recurso_tipo="empresa",
        recurso_id=empresa.pk,
        empresa_id=empresa.pk,
        resumen=f"Inventario de {etiqueta(periodo)} cerrado",
        detalle={"periodo": periodo},
    )
    logger.info("periodo_inventario_cerrado", extra={"empresa_id": empresa.pk, "periodo": periodo})
    return cierre


@transaction.atomic
def reabrir_periodo(empresa: Empresa, periodo: str) -> None:
    """Reabre el ÚLTIMO periodo cerrado (los anteriores dependen de él)."""
    exigir_empresa(empresa)
    validar_formato(periodo)
    numeracion.bloquear(empresa)
    ultimo = (
        CierrePeriodo.objects.select_for_update()
        .filter(empresa=empresa)
        .order_by("-periodo")
        .first()
    )
    if ultimo is None or ultimo.periodo != periodo:
        raise CierreFueraDeOrden(
            "Solo se puede reabrir el último periodo cerrado."
            if ultimo
            else f"El periodo {etiqueta(periodo)} no está cerrado."
        )
    ultimo.delete()  # borrado lógico: queda el rastro del cierre
    registrar(
        "inventario.periodo_reabierto",
        recurso_tipo="empresa",
        recurso_id=empresa.pk,
        empresa_id=empresa.pk,
        resumen=f"Inventario de {etiqueta(periodo)} reabierto",
        detalle={"periodo": periodo},
    )
    logger.info(
        "periodo_inventario_reabierto", extra={"empresa_id": empresa.pk, "periodo": periodo}
    )
