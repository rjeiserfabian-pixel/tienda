"""Anticipos a proveedores: dinero que se adelanta y que luego se descuenta de sus compras.

Al registrar un anticipo sale el dinero de una caja o cuenta (un egreso en el libro de Caja) y nace
un saldo a favor con ese proveedor, igual al que dejan las devoluciones: se usa después para pagar
cuotas de sus compras a crédito (ver ``creditos.py``). Puede ligarse a una orden de compra, y entre
todos sus anticipos no pueden pasar del total de la orden.

* Si el proveedor devuelve el dinero se registra una DEVOLUCIÓN: entra a una caja o cuenta y baja
  el saldo a favor.
* Un anticipo se ANULA con motivo solo si su saldo no se usó ni se devolvió nada: el dinero vuelve a
  la caja (se anula el egreso). Lo ya usado en compras se corrige antes, deshaciendo esa aplicación.
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import MovimientoCaja, Origen, TipoMovimiento
from apps.inventario import periodos
from apps.mantenimiento.models import (
    Correlativo,
    CuentaFinanciera,
    EstadoRegistro,
    MedioPago,
    Proveedor,
)
from apps.organizacion.models import Empresa

from .exceptions import AnticipoInvalido
from .models import AnticipoProveedor, CreditoProveedor, Moneda, OrdenCompra

logger = logging.getLogger(__name__)

CERO = Decimal("0")
DOS = Decimal("0.01")
MAX_MONTO = Decimal("9999999999999.99")
# Una orden admite anticipos mientras todavía se espera la mercadería.
ESTADOS_DE_ORDEN = (OrdenCompra.Estado.EMITIDA, OrdenCompra.Estado.PARCIAL)


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _monto(valor, campo: str = "Monto") -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor != valor.quantize(DOS):
        raise AnticipoInvalido(f"{campo}: indique un monto con hasta 2 decimales.")
    if valor <= 0 or valor > MAX_MONTO:
        raise AnticipoInvalido(f"{campo}: debe ser mayor que cero.")
    return valor


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"compras:anticipo:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _cuenta(empresa: Empresa, cuenta: CuentaFinanciera, moneda: str) -> None:
    if cuenta.empresa_id != empresa.pk or cuenta.estado != EstadoRegistro.ACTIVO:
        raise AnticipoInvalido("Elija una caja o cuenta activa de la empresa.")
    if cuenta.moneda != moneda:
        raise AnticipoInvalido("La caja o cuenta debe ser de la misma moneda del anticipo.")


def total_anticipado(orden: OrdenCompra) -> Decimal:
    """Lo anticipado y vigente para una orden (sin contar lo anulado)."""
    return (
        AnticipoProveedor.objects.filter(
            orden=orden, estado=AnticipoProveedor.Estado.EMITIDO
        ).aggregate(t=Sum("monto"))["t"]
        or CERO
    )


def devuelto(anticipo: AnticipoProveedor) -> Decimal:
    """Lo que el proveedor ya devolvió de este anticipo (según el libro de Caja)."""
    return (
        MovimientoCaja.objects.filter(
            origen_tipo=Origen.DEVOLUCION_ANTICIPO,
            origen_id=anticipo.pk,
            estado=MovimientoCaja.Estado.EMITIDO,
        ).aggregate(t=Sum("monto"))["t"]
        or CERO
    )


# ---------------------------------------------------------------------------
@transaction.atomic
def registrar_anticipo(
    *,
    empresa: Empresa,
    proveedor: Proveedor,
    monto: Decimal,
    cuenta: CuentaFinanciera,
    moneda: str = Moneda.PEN,
    fecha: date | None = None,
    medio_pago: MedioPago | None = None,
    referencia: str = "",
    glosa: str = "",
    orden: OrdenCompra | None = None,
) -> AnticipoProveedor:
    """Adelanta dinero a un proveedor: sale de la caja o cuenta y queda un saldo a favor."""
    periodos.exigir_empresa(empresa)
    if proveedor.organizacion_id != empresa.organizacion_id:
        raise AnticipoInvalido("El proveedor no pertenece a la organización.")
    if proveedor.estado != EstadoRegistro.ACTIVO:
        raise AnticipoInvalido("El proveedor está inactivo.")
    if moneda not in Moneda.values:
        raise AnticipoInvalido("La moneda no es válida.")
    monto = _monto(monto)
    _cuenta(empresa, cuenta, moneda)
    fecha = fecha or timezone.localdate()
    if not isinstance(fecha, date) or fecha > timezone.localdate():
        raise AnticipoInvalido("La fecha no es válida o es futura.")
    if medio_pago is not None and medio_pago.organizacion_id != empresa.organizacion_id:
        raise AnticipoInvalido("El método de pago no pertenece a la organización.")
    if orden is not None:
        orden = OrdenCompra.objects.select_for_update().get(pk=orden.pk)
        if orden.empresa_id != empresa.pk or orden.proveedor_id != proveedor.pk:
            raise AnticipoInvalido("La orden de compra no es de esta empresa y este proveedor.")
        if orden.moneda != moneda:
            raise AnticipoInvalido("La orden de compra está en otra moneda.")
        if orden.estado not in ESTADOS_DE_ORDEN:
            raise AnticipoInvalido(
                "Solo se anticipa sobre una orden emitida o recibida en parte "
                f"(esta está «{orden.get_estado_display()}»)."
            )
        ya = total_anticipado(orden)
        if ya + monto > orden.total:
            raise AnticipoInvalido(
                f"Con este anticipo se pasaría del total de la orden: ya se anticiparon {ya:,.2f} "
                f"de {orden.total:,.2f}."
            )

    anticipo = AnticipoProveedor.objects.create(
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        fecha=fecha,
        proveedor=proveedor,
        moneda=moneda,
        monto=monto,
        cuenta=cuenta,
        medio_pago=medio_pago,
        referencia=_texto(referencia, 60),
        glosa=_texto(glosa, 250),
        orden=orden,
    )
    caja.registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=caja.concepto_del_sistema(empresa, "ANTICIPO_PROVEEDOR"),
        fecha=fecha,
        glosa=f"Anticipo {anticipo.codigo} · {proveedor.nombre}"
        + (f" · {orden.codigo}" if orden else ""),
        referencia=anticipo.referencia,
        origen_tipo=Origen.ANTICIPO_PROVEEDOR,
        origen_id=anticipo.pk,
        medio_pago=medio_pago,
    )
    CreditoProveedor.objects.create(
        empresa=empresa, proveedor=proveedor, anticipo=anticipo, moneda=moneda, monto=monto
    )
    registrar(
        "compras.anticipo_registrado",
        recurso_tipo="anticipo_proveedor",
        recurso_id=anticipo.pk,
        empresa_id=empresa.pk,
        resumen=f"Anticipo {anticipo.codigo} de {monto} a {proveedor.nombre}",
        detalle={
            "proveedor": proveedor.pk,
            "monto": monto,
            "moneda": moneda,
            "orden": orden.pk if orden else None,
            "cuenta": cuenta.pk,
        },
    )
    logger.info("anticipo_registrado", extra={"empresa_id": empresa.pk, "anticipo_id": anticipo.pk})
    return anticipo


def _credito_bloqueado(anticipo: AnticipoProveedor) -> CreditoProveedor:
    return CreditoProveedor.objects.select_for_update().get(anticipo=anticipo)


@transaction.atomic
def devolver_anticipo(
    anticipo: AnticipoProveedor,
    *,
    monto: Decimal,
    cuenta: CuentaFinanciera,
    fecha: date | None = None,
    referencia: str = "",
    medio_pago: MedioPago | None = None,
) -> CreditoProveedor:
    """El proveedor devuelve (todo o parte de) el dinero: entra a una caja y baja el saldo."""
    periodos.exigir_empresa(anticipo.empresa)
    credito = _credito_bloqueado(anticipo)
    if anticipo.estado != AnticipoProveedor.Estado.EMITIDO or credito.anulado:
        raise AnticipoInvalido("El anticipo está anulado.")
    monto = _monto(monto, "Monto devuelto")
    if monto > credito.disponible:
        raise AnticipoInvalido(
            f"Del anticipo solo quedan {credito.disponible:,.2f} sin usar: "
            "no se pueden devolver más."
        )
    _cuenta(anticipo.empresa, cuenta, anticipo.moneda)
    fecha = fecha or timezone.localdate()
    if fecha > timezone.localdate() or fecha < anticipo.fecha:
        raise AnticipoInvalido("La fecha de la devolución no es válida.")
    caja.registrar_movimiento(
        empresa=anticipo.empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.INGRESO,
        monto=monto,
        concepto=caja.concepto_del_sistema(anticipo.empresa, "DEVOLUCION_ANTICIPO"),
        fecha=fecha,
        glosa=f"Devolución del anticipo {anticipo.codigo} · {anticipo.proveedor.nombre}",
        referencia=_texto(referencia, 60),
        origen_tipo=Origen.DEVOLUCION_ANTICIPO,
        origen_id=anticipo.pk,
        medio_pago=medio_pago,
    )
    credito.usado += monto
    credito.save(update_fields=["usado"])
    registrar(
        "compras.anticipo_devuelto",
        recurso_tipo="anticipo_proveedor",
        recurso_id=anticipo.pk,
        empresa_id=anticipo.empresa_id,
        resumen=f"El proveedor devolvió {monto} del anticipo {anticipo.codigo}",
        detalle={"monto": monto, "disponible": credito.disponible},
    )
    return credito


@transaction.atomic
def anular_anticipo(anticipo: AnticipoProveedor, *, motivo: str) -> AnticipoProveedor:
    """Anula el anticipo si su saldo está intacto: el dinero vuelve a la caja."""
    motivo = _texto(motivo, 250)
    if len(motivo) < 3:
        raise AnticipoInvalido("Indique el motivo de la anulación.")
    periodos.exigir_empresa(anticipo.empresa)
    credito = _credito_bloqueado(anticipo)
    if credito.usado > 0:
        raise AnticipoInvalido(
            "Ya se usó o se devolvió parte de este anticipo: deshaz esos usos primero "
            "(en «Saldos a favor») o registra la devolución del resto."
        )
    anticipo.anular(motivo=motivo)  # bloquea y valida que no esté anulado
    credito.anulado = True
    credito.save(update_fields=["anulado"])
    caja.anular_por_origen(
        Origen.ANTICIPO_PROVEEDOR, anticipo.pk, motivo=f"Anticipo anulado: {motivo}"
    )
    registrar(
        "compras.anticipo_anulado",
        recurso_tipo="anticipo_proveedor",
        recurso_id=anticipo.pk,
        empresa_id=anticipo.empresa_id,
        resumen=f"Anticipo {anticipo.codigo} anulado",
        detalle={"motivo": motivo[:200]},
    )
    return anticipo
