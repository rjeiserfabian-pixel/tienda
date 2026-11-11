"""Caja chica: un fondo fijo para gastos menores, que se rinde y se repone.

Se gasta del fondo con comprobantes; cuando baja, se RINDE: se presentan los gastos hechos y otra
caja repone exactamente lo gastado, de modo que el fondo vuelve a su monto fijo. Cada gasto se
rinde una sola vez. Reponer es una transferencia; anular la rendición la anula y libera los gastos.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Sum

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Correlativo, CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa

from . import transferencias
from .exceptions import RendicionInvalida
from .models import MovimientoCaja, RendicionCaja, RendicionGasto, TipoMovimiento
from .reportes import INTERNOS
from .servicios import CERO, _exigir_empresa, saldo_de
from .sesiones import nombre_de

logger = logging.getLogger(__name__)

MAX_GASTOS = 500


def _exigir_chica(empresa: Empresa, cuenta: CuentaFinanciera) -> None:
    if (
        cuenta.empresa_id != empresa.pk
        or cuenta.tipo != CuentaFinanciera.Tipo.CAJA
        or cuenta.rol_caja != CuentaFinanciera.RolCaja.CAJA_CHICA
    ):
        raise RendicionInvalida("Solo una caja marcada como «caja chica» se rinde.")


def gastos_por_rendir(cuenta: CuentaFinanciera):
    """Egresos vigentes de la caja chica que aún no están en ninguna rendición."""
    rendidos = RendicionGasto.objects.filter(rendicion__estado=RendicionCaja.Estado.EMITIDO).values(
        "movimiento_id"
    )
    return (
        MovimientoCaja.objects.filter(
            cuenta=cuenta, estado=MovimientoCaja.Estado.EMITIDO, tipo=TipoMovimiento.EGRESO
        )
        .exclude(concepto__codigo__in=INTERNOS)
        .exclude(pk__in=rendidos)
        .select_related("concepto")
        .order_by("fecha", "numero")
    )


def resumen(empresa: Empresa) -> list[dict]:
    """Cada caja chica con su fondo fijo, lo que tiene y lo que falta rendir."""
    filas = []
    cuentas = CuentaFinanciera.objects.filter(
        empresa=empresa,
        tipo=CuentaFinanciera.Tipo.CAJA,
        rol_caja=CuentaFinanciera.RolCaja.CAJA_CHICA,
        estado=EstadoRegistro.ACTIVO,
    ).order_by("nombre")
    for cuenta in cuentas:
        pendientes = gastos_por_rendir(cuenta).aggregate(n=Count("id"), total=Sum("monto"))
        saldo = saldo_de(cuenta)
        filas.append(
            {
                "cuenta": cuenta,
                "fondo": cuenta.fondo_inicial,
                "saldo": saldo,
                "por_rendir_cantidad": pendientes["n"],
                "por_rendir_total": pendientes["total"] or CERO,
                "faltante": max(cuenta.fondo_inicial - saldo, CERO),
            }
        )
    return filas


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"caja:rendicion:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


@transaction.atomic
def rendir(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    cuenta_origen: CuentaFinanciera,
    movimientos_ids: list[int] | None,
    usuario,
    glosa: str = "",
) -> RendicionCaja:
    """Rinde los gastos (todos los pendientes o los elegidos) y repone su total desde otra caja."""
    _exigir_empresa(empresa)
    _exigir_chica(empresa, cuenta)
    if cuenta_origen.empresa_id != empresa.pk or cuenta_origen.pk == cuenta.pk:
        raise RendicionInvalida("Elija otra caja o cuenta de la empresa para reponer el fondo.")
    if cuenta_origen.moneda != cuenta.moneda:
        raise RendicionInvalida("La reposición debe salir de una cuenta de la misma moneda.")
    # Se bloquea la fila de la caja chica: dos rendiciones a la vez no toman el mismo gasto.
    CuentaFinanciera.objects.select_for_update().get(pk=cuenta.pk)
    pendientes = gastos_por_rendir(cuenta)
    if movimientos_ids is not None:
        if len(set(movimientos_ids)) != len(movimientos_ids):
            raise RendicionInvalida("Hay gastos repetidos en la lista.")
        pendientes = pendientes.filter(pk__in=movimientos_ids)
    gastos = list(pendientes)
    if movimientos_ids is not None and len(gastos) != len(movimientos_ids):
        raise RendicionInvalida("Algún gasto no es de esta caja chica o ya se rindió.")
    if not gastos:
        raise RendicionInvalida("No hay gastos por rendir.")
    if len(gastos) > MAX_GASTOS:
        raise RendicionInvalida(f"Rinda hasta {MAX_GASTOS} gastos por vez.")
    total = sum((g.monto for g in gastos), Decimal("0"))
    numero = _siguiente_numero(empresa)
    transferencia = transferencias.registrar_transferencia(
        empresa=empresa,
        cuenta_origen=cuenta_origen,
        cuenta_destino=cuenta,
        monto=total,
        glosa=f"Reposición de caja chica: rendición {numero:06d}",
    )
    rendicion = RendicionCaja.objects.create(
        empresa=empresa,
        numero=numero,
        cuenta=cuenta,
        cuenta_origen=cuenta_origen,
        transferencia=transferencia,
        desde=min(g.fecha for g in gastos),
        hasta=max(g.fecha for g in gastos),
        total=total,
        cantidad=len(gastos),
        glosa=" ".join((glosa or "").split())[:250],
        rendida_por_nombre=nombre_de(usuario),
    )
    RendicionGasto.objects.bulk_create(
        [RendicionGasto(empresa=empresa, rendicion=rendicion, movimiento=g) for g in gastos]
    )
    registrar(
        "caja.rendicion_hecha",
        recurso_tipo="rendicion_caja",
        recurso_id=rendicion.pk,
        empresa_id=empresa.pk,
        resumen=f"Rendición {numero:06d} de {cuenta.nombre}: {len(gastos)} gastos, {total}",
        detalle={"origen": cuenta_origen.pk, "gastos": len(gastos)},
    )
    return rendicion


@transaction.atomic
def anular(rendicion: RendicionCaja, *, motivo: str) -> RendicionCaja:
    """Anula la rendición: se anula la reposición y los gastos vuelven a quedar por rendir."""
    _exigir_empresa(rendicion.empresa)
    rendicion.anular(motivo=motivo)
    transferencias.anular_transferencia(
        rendicion.transferencia, motivo=f"Rendición anulada: {motivo}"
    )
    for gasto in RendicionGasto.objects.filter(rendicion=rendicion):
        gasto.delete()  # borrado lógico: el gasto queda libre para otra rendición
    registrar(
        "caja.rendicion_anulada",
        recurso_tipo="rendicion_caja",
        recurso_id=rendicion.pk,
        empresa_id=rendicion.empresa_id,
        resumen=f"Rendición {rendicion.numero:06d} anulada",
        detalle={"motivo": (motivo or "").strip()[:200]},
    )
    return rendicion
