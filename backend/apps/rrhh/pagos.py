"""Pago de la planilla cerrada, boleta de cada trabajador y archivo para el banco.

Reglas:

* Solo se paga una planilla CERRADA, y se paga el neto completo de cada trabajador, una sola vez.
* Cada pago es un egreso de una caja o cuenta en soles (movimiento de Caja de origen
  ``PAGO_PLANILLA``). Si Caja lo rechaza (sin saldo, sesión cerrada…), no se guarda ningún pago de
  esa operación: o se pagan todos los elegidos o ninguno.
* Anular un pago devuelve el dinero a la caja. Una planilla con pagos vigentes no se reabre.
* El archivo del banco lleva cuentas: solo para quien tiene el permiso de sueldos, y nunca se guarda
  en la auditoría; allí solo queda que se generó.
"""

import csv
import io
import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.mantenimiento.models import CuentaFinanciera

from .models import (
    DatosLaborales,
    EstadoPago,
    EstadoPlanilla,
    MetodoPago,
    PagoPlanilla,
    Planilla,
    PlanillaTrabajador,
    TipoConcepto,
)
from .planilla import ErrorPlanilla, _error, _exigir_empresa

logger = logging.getLogger(__name__)

MAX_PAGOS_POR_OPERACION = 200


def pago_vigente(detalle: PlanillaTrabajador) -> PagoPlanilla | None:
    return detalle.pagos.filter(estado=EstadoPago.PAGADO).first()


def hay_pagos_vigentes(planilla: Planilla) -> bool:
    return PagoPlanilla.objects.filter(planilla=planilla, estado=EstadoPago.PAGADO).exists()


@transaction.atomic
def pagar(
    planilla: Planilla,
    *,
    detalle_ids: list[int],
    fecha: date,
    cuenta: CuentaFinanciera,
    medio_pago=None,
    referencia: str = "",
) -> list[PagoPlanilla]:
    """Paga el neto de los trabajadores elegidos, desde una caja o cuenta en soles."""
    _exigir_empresa(planilla.empresa_id)
    ids = list(dict.fromkeys(detalle_ids))
    if not ids:
        raise _error("detalles", "Elija a quién se le paga.")
    if len(ids) > MAX_PAGOS_POR_OPERACION:
        raise _error("detalles", f"Pague de a {MAX_PAGOS_POR_OPERACION} trabajadores como máximo.")
    if fecha > timezone.localdate():
        raise _error("fecha", "La fecha de pago no puede ser futura.")
    if cuenta.empresa_id != planilla.empresa_id:
        raise _error("cuenta", "Elija una caja o cuenta de la empresa.")
    if cuenta.moneda != CuentaFinanciera.Moneda.PEN:
        raise _error("cuenta", "Elija una caja o cuenta en soles.")

    actual = Planilla.objects.select_for_update(of=("self",)).get(pk=planilla.pk)
    if actual.estado != EstadoPlanilla.CERRADA:
        raise _error("estado", "Cierre la planilla antes de pagarla.")
    detalles = list(
        PlanillaTrabajador.objects.select_for_update(of=("self",))
        .select_related("personal")
        .filter(planilla=actual, pk__in=ids)
        .order_by("pk")
    )
    if len(detalles) != len(ids):
        raise _error("detalles", "Algún trabajador no está en esta planilla.")
    pagados = set(
        PagoPlanilla.objects.filter(detalle_id__in=ids, estado=EstadoPago.PAGADO).values_list(
            "detalle_id", flat=True
        )
    )
    for detalle in detalles:
        nombre = detalle.personal.nombre_completo
        if detalle.pk in pagados:
            raise _error("detalles", f"{nombre} ya tiene su sueldo pagado.")
        if detalle.neto <= 0:
            raise _error("detalles", f"{nombre} no tiene un neto por pagar.")

    referencia = " ".join((referencia or "").split())[:60]
    pagos = []
    for detalle in detalles:
        pago = PagoPlanilla.objects.create(
            empresa=actual.empresa,
            planilla=actual,
            detalle=detalle,
            fecha=fecha,
            monto=detalle.neto,
            cuenta=cuenta,
            medio_pago=medio_pago,
            referencia=referencia,
        )
        # Si Caja no puede (sin saldo, sesión cerrada…), la transacción entera se revierte.
        caja.registrar_pago_de_planilla(
            empresa=actual.empresa,
            cuenta=cuenta,
            monto=detalle.neto,
            fecha=fecha,
            referencia=referencia,
            glosa=f"Sueldo de {actual.periodo:%m/%Y} a {detalle.personal.nombre_completo}",
            pago_id=pago.pk,
            medio_pago=medio_pago,
        )
        pagos.append(pago)
    registrar(
        "rrhh.planilla_pagada",
        recurso_tipo="planilla",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Sueldos de {actual.periodo:%m/%Y} pagados: {len(pagos)} trabajador(es)",
        detalle={"trabajadores": len(pagos)},
    )
    logger.info("planilla_pagada", extra={"planilla_id": actual.pk, "pagos": len(pagos)})
    return pagos


@transaction.atomic
def anular_pago(pago: PagoPlanilla, *, motivo: str) -> PagoPlanilla:
    """Deshace un pago: el dinero vuelve a la caja y el trabajador queda por pagar."""
    _exigir_empresa(pago.empresa_id)
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise _error("motivo", "Indique el motivo de la anulación.")
    actual = PagoPlanilla.objects.select_for_update().get(pk=pago.pk)
    if actual.estado == EstadoPago.ANULADO:
        raise _error("estado", "El pago ya está anulado.")
    caja.anular_por_origen(Origen.PAGO_PLANILLA, actual.pk, motivo=f"Pago anulado: {motivo}")
    actual.estado = EstadoPago.ANULADO
    actual.anulado_en = timezone.now()
    actual.motivo_anulacion = motivo[:250]
    actual.save(update_fields=["estado", "anulado_en", "motivo_anulacion"])
    registrar(
        "rrhh.pago_planilla_anulado",
        recurso_tipo="planilla",
        recurso_id=actual.planilla_id,
        empresa_id=actual.empresa_id,
        resumen="Pago de sueldo anulado",
        detalle={"motivo": motivo[:200]},
    )
    return actual


# ---------------------------------------------------------------------------
# Boleta de pago
# ---------------------------------------------------------------------------
def boleta(planilla: Planilla, detalle: PlanillaTrabajador) -> dict:
    """Los datos de la boleta de un trabajador, listos para imprimir."""
    empresa = planilla.empresa
    personal = detalle.personal
    lineas = list(detalle.conceptos.all())

    def grupo(tipo: str) -> list[dict]:
        return [
            {"nombre": c.nombre, "detalle": c.explicacion, "monto": str(c.monto)}
            for c in lineas
            if c.tipo == tipo
        ]

    pago = pago_vigente(detalle)
    return {
        "periodo": planilla.periodo,
        "es_borrador": planilla.estado != EstadoPlanilla.CERRADA,
        "emisor": {
            "nombre": empresa.razon_social,
            "ruc": empresa.ruc,
            "direccion": empresa.direccion_fiscal,
        },
        "trabajador": {
            "nombre": personal.nombre_completo,
            "tipo_documento": personal.tipo_documento,
            "numero_documento": personal.numero_documento,
            "cargo": detalle.cargo,
            "fecha_ingreso": personal.fecha_ingreso,
            "regimen": detalle.regimen_nombre,
            "pension": detalle.afp if detalle.sistema_pension == "AFP" else detalle.sistema_pension,
        },
        "dias_contrato": detalle.dias_contrato,
        "dias_laborados": detalle.dias_laborados,
        "dias_falta": detalle.dias_falta,
        "horas_trabajadas": str(detalle.horas_trabajadas),
        "horas_extra": str(detalle.horas_extra),
        "sueldo_mensual": str(detalle.sueldo_mensual),
        "ingresos": grupo(TipoConcepto.INGRESO),
        "descuentos": grupo(TipoConcepto.DESCUENTO),
        "aportes_empleador": grupo(TipoConcepto.APORTE_EMPLEADOR),
        "total_ingresos": str(detalle.total_ingresos),
        "total_descuentos": str(detalle.total_descuentos),
        "neto": str(detalle.neto),
        "pago": None
        if pago is None
        else {
            "fecha": pago.fecha,
            "medio": pago.medio_pago.nombre if pago.medio_pago else "",
            "referencia": pago.referencia,
        },
    }


# ---------------------------------------------------------------------------
# Archivo para el banco
# ---------------------------------------------------------------------------
ENCABEZADO_BANCO = [
    "tipo_documento",
    "numero_documento",
    "trabajador",
    "banco",
    "numero_cuenta",
    "cci",
    "monto",
]


def archivo_banco(planilla: Planilla) -> tuple[str, list[str]]:
    """CSV con las transferencias por hacer y los nombres de quienes no se pudieron incluir.

    Entran los trabajadores a quienes se les paga por transferencia, con neto por pagar y sin
    pago todavía. Quien no tiene banco y cuenta queda fuera y se informa aparte. El formato es
    genérico: cada banco pide el suyo, y este archivo se adapta a él.
    """
    if planilla.estado != EstadoPlanilla.CERRADA:
        raise ErrorPlanilla({"estado": "Cierre la planilla antes de generar el archivo del banco."})
    pagados = set(
        PagoPlanilla.objects.filter(planilla=planilla, estado=EstadoPago.PAGADO).values_list(
            "detalle_id", flat=True
        )
    )
    datos = {
        d.personal_id: d
        for d in DatosLaborales.objects.filter(
            empresa_id=planilla.empresa_id,
            personal_id__in=planilla.trabajadores.values("personal_id"),
        )
    }
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(ENCABEZADO_BANCO)
    omitidos: list[str] = []
    detalles = planilla.trabajadores.select_related("personal").order_by(
        "personal__apellidos", "personal__nombres", "id"
    )
    for detalle in detalles:
        if detalle.pk in pagados or detalle.neto <= Decimal("0"):
            continue
        ficha = datos.get(detalle.personal_id)
        if ficha is None or ficha.metodo_pago != MetodoPago.TRANSFERENCIA:
            continue
        if not (ficha.banco and ficha.numero_cuenta):
            omitidos.append(detalle.personal.nombre_completo)
            continue
        escritor.writerow(
            [
                detalle.personal.tipo_documento,
                detalle.personal.numero_documento,
                detalle.personal.nombre_completo,
                ficha.banco,
                ficha.numero_cuenta,
                ficha.cci,
                detalle.neto,
            ]
        )
    registrar(
        "rrhh.archivo_banco_generado",
        recurso_tipo="planilla",
        recurso_id=planilla.pk,
        empresa_id=planilla.empresa_id,
        resumen=f"Archivo del banco de {planilla.periodo:%m/%Y} generado",
        detalle={"omitidos": len(omitidos)},
    )
    return salida.getvalue(), omitidos
