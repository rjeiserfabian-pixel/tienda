"""Llevar lo liquidado a la planilla de RR.HH. (o marcarlo como pagado aparte).

La comisión entra a la planilla como el concepto «Comisiones» (ingreso afecto a pensiones, EsSalud
y renta de 5.ª), agregado a mano al trabajador, con la explicación del mes. Por eso:

* La persona debe tener ficha de personal y estar en esa planilla (con contrato vigente).
* La planilla debe existir y estar en revisión (no cerrada).
* Una línea no se envía dos veces: si el renglón sigue en la planilla, se avisa; si lo quitaron de
  la planilla, se puede volver a enviar.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.rrhh import planilla as rrhh_planilla
from apps.rrhh.models import (
    ConceptoPlanilla,
    EstadoPlanilla,
    Planilla,
    PlanillaConcepto,
    PlanillaTrabajador,
)

from .cierre import CierreInvalido
from .models import LineaLiquidacion

CODIGO_CONCEPTO = "COMISIONES"
NOTA_MINIMA = 3


def _linea_bloqueada(linea_id: int) -> LineaLiquidacion:
    linea = (
        LineaLiquidacion.objects.sin_ambito()
        .select_for_update(of=("self",))
        .select_related("liquidacion", "personal")
        .filter(pk=linea_id)
        .first()
    )
    if linea is None:
        raise CierreInvalido("No encontramos esa línea de la liquidación.")
    return linea


def _explicacion(linea: LineaLiquidacion) -> str:
    partes = []
    if linea.comisiones_ventas:
        partes.append(f"ventas S/ {linea.comisiones_ventas}")
    if linea.bonos:
        partes.append(f"bonos S/ {linea.bonos}")
    if linea.comisiones_tecnico:
        partes.append(f"servicios S/ {linea.comisiones_tecnico}")
    if linea.arrastre_anterior:
        partes.append(f"saldo anterior S/ {linea.arrastre_anterior}")
    return f"Comisiones de {linea.liquidacion.periodo} ({', '.join(partes)})"[:200]


@transaction.atomic
def llevar_a_planilla(linea_id: int, periodo: date, *, usuario_id=None) -> LineaLiquidacion:
    """Agrega lo que se le paga a la persona como ingreso de la planilla de ``periodo``."""
    linea = _linea_bloqueada(linea_id)
    if linea.estado == LineaLiquidacion.Estado.PAGADA_APARTE:
        raise CierreInvalido("Esta línea ya se marcó como pagada aparte.")
    if linea.estado == LineaLiquidacion.Estado.SIN_MONTO or linea.a_pagar <= 0:
        raise CierreInvalido("No hay nada que pagar a esta persona este mes.")
    if linea.estado == LineaLiquidacion.Estado.EN_PLANILLA and (
        linea.planilla_concepto_id
        and PlanillaConcepto.objects.sin_ambito().filter(pk=linea.planilla_concepto_id).exists()
    ):
        raise CierreInvalido(
            "Esta línea ya está en la planilla. Quítala allí si quieres reenviarla."
        )
    personal = linea.personal
    if personal is None:
        raise CierreInvalido(
            "Esta persona no tiene ficha de personal en Recursos Humanos: págale aparte y "
            "márcala como pagada."
        )
    periodo = periodo.replace(day=1)
    planilla = (
        Planilla.objects.sin_ambito()
        .filter(empresa_id=personal.empresa_id, periodo=periodo)
        .first()
    )
    if planilla is None:
        raise CierreInvalido(
            f"No existe la planilla de {periodo:%m/%Y} de la empresa de {linea.nombre}. "
            "Créala primero en Recursos Humanos."
        )
    if planilla.estado != EstadoPlanilla.BORRADOR:
        raise CierreInvalido(f"La planilla de {periodo:%m/%Y} está cerrada. Reábrela para agregar.")
    detalle = (
        PlanillaTrabajador.objects.sin_ambito().filter(planilla=planilla, personal=personal).first()
    )
    if detalle is None:
        raise CierreInvalido(
            f"{linea.nombre} no está en la planilla de {periodo:%m/%Y} (¿tiene contrato vigente?)."
        )
    concepto = (
        ConceptoPlanilla.objects.sin_ambito()
        .filter(organizacion_id=linea.organizacion_id, codigo=CODIGO_CONCEPTO)
        .first()
    )
    if concepto is None:
        raise CierreInvalido(
            "Falta el concepto «Comisiones» en la planilla: carga el catálogo de Recursos Humanos."
        )
    monto = Decimal(linea.a_pagar).quantize(Decimal("0.01"))
    try:
        rrhh_planilla.agregar_ajuste(
            planilla,
            detalle_id=detalle.pk,
            concepto_id=concepto.pk,
            monto=monto,
            explicacion=_explicacion(linea),
        )
    except ValidationError as error:
        raise CierreInvalido(" ".join(error.messages)) from None
    renglon = (
        PlanillaConcepto.objects.sin_ambito()
        .filter(detalle=detalle, concepto=concepto, manual=True, monto=monto)
        .order_by("-id")
        .first()
    )
    linea.estado = LineaLiquidacion.Estado.EN_PLANILLA
    linea.planilla = planilla
    linea.planilla_concepto = renglon
    linea.enviada_en = timezone.now()
    linea.save(
        update_fields=["estado", "planilla", "planilla_concepto", "enviada_en", "actualizado_en"]
    )
    registrar(
        "comisiones.enviada_a_planilla",
        recurso_tipo="linea_liquidacion",
        recurso_id=linea.pk,
        empresa_id=personal.empresa_id,
        usuario_id=usuario_id,
        resumen=(
            f"Comisiones de {linea.nombre} ({linea.liquidacion.periodo}) "
            f"a la planilla {periodo:%m/%Y}"
        ),
        detalle={"monto": str(monto), "planilla": planilla.pk},
    )
    return linea


@transaction.atomic
def marcar_pagada_aparte(linea_id: int, nota: str, *, usuario_id=None) -> LineaLiquidacion:
    """Se le pagó fuera de la planilla (efectivo, transferencia): queda anotado con su nota."""
    linea = _linea_bloqueada(linea_id)
    texto = " ".join((nota or "").split())
    if len(texto) < NOTA_MINIMA:
        raise CierreInvalido(
            "Escribe cómo y cuándo se le pagó (por ejemplo, «Transferencia 12/12»)."
        )
    if linea.estado != LineaLiquidacion.Estado.PENDIENTE:
        raise CierreInvalido("Solo se marca como pagada una línea que está por pagar.")
    linea.estado = LineaLiquidacion.Estado.PAGADA_APARTE
    linea.pagada_en = timezone.now()
    linea.pagada_nota = texto[:200]
    linea.save(update_fields=["estado", "pagada_en", "pagada_nota", "actualizado_en"])
    registrar(
        "comisiones.pagada_aparte",
        recurso_tipo="linea_liquidacion",
        recurso_id=linea.pk,
        usuario_id=usuario_id,
        organizacion_id=linea.organizacion_id,
        resumen=f"Comisiones de {linea.nombre} ({linea.liquidacion.periodo}) pagadas aparte",
        detalle={"monto": str(linea.a_pagar), "nota": linea.pagada_nota},
    )
    return linea
