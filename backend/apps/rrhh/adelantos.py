"""Adelantos de sueldo y préstamos a los trabajadores (con salida de Caja).

Reglas:

* Solo se le entrega a un trabajador ACTIVO con contrato vigente.
* Adelanto de sueldo = una cuota (en el mes de la entrega, o el que se elija); préstamo = de 1 a 36
  cuotas mensuales iguales (la última absorbe los centavos).
* Lo que se descuenta en un mes (todas las cuotas por descontar) no puede pasar del sueldo mensual
  del trabajador: así la planilla no queda en negativo.
* La entrega es un egreso de una caja o cuenta en soles (movimiento de Caja de origen
  ``ADELANTO_PERSONAL``). Anular el adelanto anula ese movimiento y sus cuotas; no se puede si ya
  se descontó alguna cuota en una planilla.
"""

import logging
from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import Correlativo, CuentaFinanciera, EstadoRegistro, Personal

from . import trabajadores
from .cierre import exigir_mes_abierto
from .models import (
    AdelantoPersonal,
    ContratoLaboral,
    CuotaAdelanto,
    EstadoAdelanto,
    EstadoContrato,
    EstadoCuota,
    TipoAdelanto,
)

logger = logging.getLogger(__name__)

CENTAVO = Decimal("0.01")
MAXIMO = Decimal("9999999.99")
MAX_CUOTAS = 36
MAX_MESES_ADELANTE = 24  # el primer descuento no puede quedar a más de dos años


class ErrorAdelanto(ValidationError):
    """Un dato del adelanto o préstamo no es válido (se muestra junto al campo)."""


def _error(campo: str, mensaje: str) -> ErrorAdelanto:
    return ErrorAdelanto({campo: mensaje})


def _exigir_empresa(empresa_id: int) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa_id):
        raise EmpresaNoHabilitada()


def _numero_siguiente(empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"rrhh:adelanto:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def primer_dia(fecha: date) -> date:
    return fecha.replace(day=1)


def sumar_meses(periodo: date, meses: int) -> date:
    total = periodo.year * 12 + (periodo.month - 1) + meses
    return date(total // 12, total % 12 + 1, 1)


def repartir(monto: Decimal, n: int) -> list[Decimal]:
    """Cuotas iguales; la última lleva la diferencia para que sumen exactamente el monto."""
    base = (monto / n).quantize(CENTAVO, rounding=ROUND_DOWN)
    cuotas = [base] * (n - 1)
    cuotas.append(monto - base * (n - 1))
    return cuotas


def saldo_pendiente(adelanto: AdelantoPersonal) -> Decimal:
    """Lo que falta descontar de un adelanto (cuotas por descontar)."""
    if adelanto.estado != EstadoAdelanto.VIGENTE:
        return Decimal("0")
    total = adelanto.cuotas.filter(estado=EstadoCuota.PENDIENTE).aggregate(t=Sum("monto"))["t"]
    return total or Decimal("0")


def _exigir_cabe_en_sueldo(personal, contrato, periodos_y_montos, fecha: date) -> None:
    """Lo descontado en cada mes (lo ya pendiente más lo nuevo) no pasa del sueldo mensual."""
    sueldo = trabajadores.sueldo_vigente(contrato, fecha)
    if sueldo is None:
        raise _error("monto", "El trabajador no tiene un sueldo registrado en su contrato.")
    for periodo, monto in periodos_y_montos:
        pendiente = CuotaAdelanto.objects.filter(
            adelanto__personal=personal, periodo=periodo, estado=EstadoCuota.PENDIENTE
        ).aggregate(t=Sum("monto"))["t"] or Decimal("0")
        if pendiente + monto > sueldo:
            raise _error(
                "monto",
                f"En {periodo:%m/%Y} se le descontaría más que su sueldo mensual "
                "(contando lo que ya tiene pendiente). Reduzca el monto o reparta en más cuotas.",
            )


@transaction.atomic
def crear_adelanto(
    *,
    empresa,
    personal: Personal,
    tipo: str,
    fecha: date,
    monto: Decimal,
    num_cuotas: int,
    primer_periodo: date | None,
    cuenta: CuentaFinanciera,
    medio_pago=None,
    referencia: str = "",
    motivo: str = "",
) -> AdelantoPersonal:
    """Entrega el dinero (egreso de Caja) y deja programados los descuentos."""
    _exigir_empresa(empresa.pk)
    if tipo not in TipoAdelanto.values:
        raise _error("tipo", "Elija si es un adelanto de sueldo o un préstamo.")
    if personal.empresa_id != empresa.pk:
        raise _error("personal", "El trabajador no es de esta empresa.")
    if not isinstance(monto, Decimal) or monto != monto.quantize(CENTAVO) or monto <= 0:
        raise _error("monto", "Un monto en soles mayor que cero, con hasta 2 decimales.")
    if monto > MAXIMO:
        raise _error("monto", "El monto es demasiado grande.")
    if fecha > timezone.localdate():
        raise _error("fecha", "La fecha de entrega no puede ser futura.")
    if cuenta.moneda != CuentaFinanciera.Moneda.PEN:
        raise _error("cuenta", "Elija una caja o cuenta en soles.")

    personal = Personal.objects.select_for_update().get(pk=personal.pk)
    if personal.estado != EstadoRegistro.ACTIVO:
        raise _error("personal", "El trabajador está inactivo.")
    contrato = ContratoLaboral.objects.filter(
        personal=personal, estado=EstadoContrato.VIGENTE
    ).first()
    if contrato is None or contrato.fecha_inicio > fecha:
        raise _error("personal", "El trabajador no tiene un contrato vigente a esa fecha.")

    if tipo == TipoAdelanto.ADELANTO:
        num_cuotas = 1
    elif not 1 <= num_cuotas <= MAX_CUOTAS:
        raise _error("num_cuotas", f"Las cuotas van de 1 a {MAX_CUOTAS}.")
    mes_entrega = primer_dia(fecha)
    if primer_periodo is None:
        # El adelanto se descuenta el mismo mes; el préstamo empieza el mes siguiente.
        primer_periodo = (
            mes_entrega if tipo == TipoAdelanto.ADELANTO else sumar_meses(mes_entrega, 1)
        )
    primer_periodo = primer_dia(primer_periodo)
    if primer_periodo < mes_entrega:
        raise _error("primer_periodo", "El descuento no puede empezar antes del mes de la entrega.")
    if primer_periodo > sumar_meses(mes_entrega, MAX_MESES_ADELANTE):
        raise _error("primer_periodo", "El primer descuento queda demasiado lejos.")

    montos = repartir(monto, num_cuotas)
    periodos = [sumar_meses(primer_periodo, i) for i in range(num_cuotas)]
    # Una cuota en un mes con planilla cerrada nunca se descontaría.
    for periodo in periodos:
        exigir_mes_abierto(empresa.pk, periodo, ErrorAdelanto, "fecha")
    _exigir_cabe_en_sueldo(personal, contrato, list(zip(periodos, montos, strict=True)), fecha)

    adelanto = AdelantoPersonal.objects.create(
        empresa=empresa,
        numero=_numero_siguiente(empresa),
        personal=personal,
        tipo=tipo,
        fecha=fecha,
        monto=monto,
        num_cuotas=num_cuotas,
        primer_periodo=primer_periodo,
        cuenta=cuenta,
        medio_pago=medio_pago,
        referencia=" ".join((referencia or "").split())[:60],
        motivo=" ".join((motivo or "").split())[:150],
    )
    # Si Caja no puede (sin saldo, sesión cerrada…), nada se guarda: la transacción se revierte.
    caja.registrar_adelanto_de_personal(
        empresa=empresa,
        cuenta=cuenta,
        monto=monto,
        fecha=fecha,
        referencia=adelanto.referencia,
        glosa=f"{adelanto.get_tipo_display()} N° {adelanto.numero:06d} "
        f"a {personal.nombre_completo}",
        adelanto_id=adelanto.pk,
        medio_pago=medio_pago,
    )
    CuotaAdelanto.objects.bulk_create(
        [
            CuotaAdelanto(empresa=empresa, adelanto=adelanto, numero=i, periodo=p, monto=m)
            for i, (p, m) in enumerate(zip(periodos, montos, strict=True), start=1)
        ]
    )
    registrar(
        "rrhh.adelanto_registrado",
        recurso_tipo="adelanto_personal",
        recurso_id=adelanto.pk,
        empresa_id=empresa.pk,
        resumen=f"{adelanto.get_tipo_display()} N° {adelanto.numero:06d} a "
        f"{personal.nombre_completo}",
        detalle={"monto": monto, "cuotas": num_cuotas, "primer_periodo": primer_periodo},
    )
    logger.info("adelanto_registrado", extra={"adelanto_id": adelanto.pk})
    return adelanto


@transaction.atomic
def anular_adelanto(adelanto: AdelantoPersonal, *, motivo: str) -> AdelantoPersonal:
    """Deshace la entrega: se anula el egreso de Caja y las cuotas que faltaban descontar."""
    _exigir_empresa(adelanto.empresa_id)
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise _error("motivo", "Indique el motivo de la anulación.")
    actual = AdelantoPersonal.objects.select_for_update().get(pk=adelanto.pk)
    if actual.estado == EstadoAdelanto.ANULADO:
        raise _error("estado", "El adelanto ya está anulado.")
    cuotas = list(CuotaAdelanto.objects.select_for_update().filter(adelanto=actual))
    if any(c.estado == EstadoCuota.DESCONTADA for c in cuotas):
        raise _error(
            "estado", "Ya se descontó alguna cuota en una planilla: no se puede anular el adelanto."
        )
    caja.anular_por_origen(
        Origen.ADELANTO_PERSONAL, actual.pk, motivo=f"Adelanto anulado: {motivo}"
    )
    for cuota in cuotas:
        cuota.estado = EstadoCuota.ANULADA
    CuotaAdelanto.objects.bulk_update(cuotas, ["estado"])
    actual.estado = EstadoAdelanto.ANULADO
    actual.anulado_en = timezone.now()
    actual.motivo_anulacion = motivo[:250]
    actual.save(update_fields=["estado", "anulado_en", "motivo_anulacion"])
    registrar(
        "rrhh.adelanto_anulado",
        recurso_tipo="adelanto_personal",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.get_tipo_display()} N° {actual.numero:06d} anulado",
        detalle={"motivo": motivo[:200], "monto": actual.monto},
    )
    return actual
