"""Liquidación de tarjetas: del POS al banco, menos la comisión del procesador.

Una venta con tarjeta no es plata en el banco: el procesador (Niubiz, Izipay…) la deposita días
después, descontando su comisión. Mientras tanto el dinero está en la cuenta del POS, que es la
cuenta configurada para cobrar con tarjeta. Al liquidar, de esa cuenta salen el importe bruto:

* el **neto** pasa al banco como una transferencia, y
* la **comisión** queda como un egreso (concepto «Comisión bancaria»).

Así el saldo del POS es lo que falta liquidar y el banco recibe exactamente lo que depositaron.
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen, TipoMovimiento
from apps.caja.transferencias import anular_transferencia, registrar_transferencia
from apps.inventario import periodos
from apps.mantenimiento.models import Correlativo, CuentaFinanciera, EstadoRegistro, MedioPago
from apps.organizacion.models import Empresa

from .exceptions import VentaInvalida
from .models import CuentaDeCobro, LiquidacionTarjeta

logger = logging.getLogger(__name__)

CERO = Decimal("0")
DOS = Decimal("0.01")


def cuentas_de_tarjeta(empresa: Empresa) -> list[CuentaFinanciera]:
    """Las cuentas de POS: aquellas a las que entra lo cobrado con tarjeta."""
    ids = (
        CuentaDeCobro.objects.sin_ambito()
        .filter(empresa=empresa, medio_pago__tipo=MedioPago.Tipo.TARJETA)
        .values_list("cuenta_id", flat=True)
    )
    return list(
        CuentaFinanciera.objects.sin_ambito()
        .filter(pk__in=list(ids), empresa=empresa, estado=EstadoRegistro.ACTIVO)
        .order_by("nombre")
    )


def pendientes(empresa: Empresa) -> list[dict]:
    """Cada cuenta de POS con lo que falta liquidar (su saldo)."""
    return [
        {
            "cuenta": c.pk,
            "nombre": c.nombre,
            "moneda": c.moneda,
            "saldo": caja.saldo_de(c),
        }
        for c in cuentas_de_tarjeta(empresa)
    ]


def _dinero(valor, campo: str) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor != valor.quantize(DOS):
        raise VentaInvalida(f"{campo}: indique un monto con hasta 2 decimales.")
    return valor


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"ventas:liquidacion:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


@transaction.atomic
def liquidar_tarjeta(
    *,
    empresa: Empresa,
    cuenta_pos: CuentaFinanciera,
    cuenta_destino: CuentaFinanciera,
    bruto: Decimal,
    comision: Decimal = CERO,
    fecha: date | None = None,
    referencia: str = "",
    observacion: str = "",
) -> LiquidacionTarjeta:
    """Pasa ``bruto`` del POS al banco: entra ``bruto - comision`` y la comisión es un egreso."""
    periodos.exigir_empresa(empresa)
    if cuenta_pos not in cuentas_de_tarjeta(empresa):
        raise VentaInvalida(f"«{cuenta_pos.nombre}» no es una cuenta de cobro con tarjeta.")
    if cuenta_destino.empresa_id != empresa.pk or cuenta_destino.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida("Elija una cuenta de la empresa donde se depositó.")
    if cuenta_destino.tipo == CuentaFinanciera.Tipo.CAJA:
        raise VentaInvalida("Las tarjetas se depositan en una cuenta de banco, no en una caja.")
    if cuenta_destino.pk == cuenta_pos.pk:
        raise VentaInvalida("El banco debe ser distinto de la cuenta del POS.")
    if cuenta_destino.moneda != cuenta_pos.moneda:
        raise VentaInvalida("El banco debe ser de la misma moneda que la cuenta del POS.")
    bruto = _dinero(bruto, "Importe de las ventas")
    comision = _dinero(comision, "Comisión")
    if bruto <= 0:
        raise VentaInvalida("El importe de las ventas debe ser mayor que cero.")
    if comision < 0 or comision >= bruto:
        raise VentaInvalida("La comisión debe ser menor que lo vendido.")
    neto = bruto - comision
    # Bloquea la cuenta del POS y revisa lo pendiente: no se liquida lo que no se cobró.
    CuentaFinanciera.objects.sin_ambito().select_for_update().get(pk=cuenta_pos.pk)
    pendiente = caja.saldo_de(cuenta_pos)
    if bruto > pendiente:
        raise VentaInvalida(
            f"En «{cuenta_pos.nombre}» solo hay {pendiente:,.2f} por liquidar: "
            f"no se pueden liquidar {bruto:,.2f}."
        )
    fecha = fecha or timezone.localdate()
    referencia = " ".join((referencia or "").split())[:60]
    observacion = " ".join((observacion or "").split())[:250]

    numero = _siguiente_numero(empresa)
    glosa = f"Liquidación de tarjetas N° {numero:06d}"
    transferencia = registrar_transferencia(
        empresa=empresa,
        cuenta_origen=cuenta_pos,
        cuenta_destino=cuenta_destino,
        monto=neto,
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
    )
    liquidacion = LiquidacionTarjeta.objects.create(
        empresa=empresa,
        numero=numero,
        fecha=fecha,
        cuenta_pos=cuenta_pos,
        cuenta_destino=cuenta_destino,
        bruto=bruto,
        comision=comision,
        neto=neto,
        referencia=referencia,
        observacion=observacion,
        transferencia=transferencia,
    )
    if comision > 0:
        caja.registrar_movimiento(
            empresa=empresa,
            cuenta=cuenta_pos,
            tipo=TipoMovimiento.EGRESO,
            monto=comision,
            concepto=caja.concepto_del_sistema(empresa, "COMISION_BANCARIA"),
            fecha=fecha,
            glosa=f"Comisión de tarjetas · {glosa}",
            referencia=referencia,
            origen_tipo=Origen.COMISION_TARJETA,
            origen_id=liquidacion.pk,
        )
    registrar(
        "ventas.tarjetas_liquidadas",
        recurso_tipo="liquidacion_tarjeta",
        recurso_id=liquidacion.pk,
        empresa_id=empresa.pk,
        resumen=f"Liquidación N° {liquidacion.numero:06d}: {neto} al banco, comisión {comision}",
        detalle={"bruto": bruto, "comision": comision, "neto": neto, "pos": cuenta_pos.pk},
    )
    return liquidacion


@transaction.atomic
def anular_liquidacion(liquidacion: LiquidacionTarjeta, *, motivo: str) -> LiquidacionTarjeta:
    """Deshace la liquidación: el dinero y la comisión vuelven a la cuenta del POS."""
    periodos.exigir_empresa(liquidacion.empresa)
    liquidacion.anular(motivo=motivo)  # exige el motivo y bloquea la fila
    if liquidacion.transferencia_id:
        anular_transferencia(liquidacion.transferencia, motivo=f"Liquidación anulada: {motivo}")
    caja.anular_por_origen(
        Origen.COMISION_TARJETA, liquidacion.pk, motivo=f"Liquidación anulada: {motivo}"
    )
    registrar(
        "ventas.liquidacion_anulada",
        recurso_tipo="liquidacion_tarjeta",
        recurso_id=liquidacion.pk,
        empresa_id=liquidacion.empresa_id,
        resumen=f"Liquidación N° {liquidacion.numero:06d} anulada",
        detalle={"motivo": (motivo or "").strip()[:200]},
    )
    return liquidacion
