"""Transferencias, depósitos y retiros entre cajas y cuentas.

Un depósito es de una caja de efectivo a un banco o billetera; un retiro, al revés; todo lo demás es
una transferencia. Entre monedas distintas (soles y dólares) se convierte con el tipo de cambio
indicado. La comisión y el ITF, si los hay, salen de la cuenta de origen como movimientos aparte.
Todo ocurre en una transacción y se anula junto.
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa

from . import servicios
from .exceptions import MovimientoInvalido
from .models import ClaseTransferencia, Origen, TipoMovimiento, Transferencia

logger = logging.getLogger(__name__)

DOS = Decimal("0.01")
CUATRO = Decimal("0.0001")
CERO = Decimal("0")
EFECTIVO = "CAJA"
MAXIMO = Decimal("9999999999999.99")


def _a_dos(valor: Decimal) -> Decimal:
    return valor.quantize(DOS, rounding=ROUND_HALF_UP)


def clase_de(origen: CuentaFinanciera, destino: CuentaFinanciera) -> str:
    if origen.tipo == EFECTIVO and destino.tipo != EFECTIVO:
        return ClaseTransferencia.DEPOSITO
    if origen.tipo != EFECTIVO and destino.tipo == EFECTIVO:
        return ClaseTransferencia.RETIRO
    return ClaseTransferencia.TRANSFERENCIA


def convertir(monto: Decimal, origen: str, destino: str, tipo_cambio: Decimal) -> Decimal:
    """Monto en la moneda de destino: soles→dólares divide; dólares→soles multiplica."""
    if origen == destino:
        return monto
    return _a_dos(monto / tipo_cambio if origen == "PEN" else monto * tipo_cambio)


def _dinero(valor, campo: str, *, minimo: Decimal = CERO) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor != valor.quantize(DOS):
        raise MovimientoInvalido(f"{campo}: admite hasta 2 decimales.")
    if valor < minimo or valor > MAXIMO:
        raise MovimientoInvalido(f"{campo}: el valor no es válido.")
    return valor


def _siguiente_numero(empresa: Empresa) -> int:
    from apps.mantenimiento.models import Correlativo

    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"caja:transferencia:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


@transaction.atomic
def registrar_transferencia(
    *,
    empresa: Empresa,
    cuenta_origen: CuentaFinanciera,
    cuenta_destino: CuentaFinanciera,
    monto: Decimal,
    fecha: date | None = None,
    tipo_cambio: Decimal | None = None,
    monto_destino: Decimal | None = None,
    comision: Decimal = CERO,
    itf: Decimal = CERO,
    glosa: str = "",
    referencia: str = "",
) -> Transferencia:
    """Pasa ``monto`` de la cuenta de origen a la de destino (y descuenta comisión e ITF)."""
    contexto = obtener_contexto_requerido()
    destino_empresa = cuenta_destino.empresa
    for e in (empresa, destino_empresa):
        if not contexto.empresa_habilitada(e.pk):
            raise EmpresaNoHabilitada()
    if destino_empresa.organizacion_id != empresa.organizacion_id:
        raise MovimientoInvalido("Las dos cuentas deben ser de la misma organización.")
    if cuenta_origen.empresa_id != empresa.pk:
        raise MovimientoInvalido("La cuenta de origen no pertenece a la empresa.")
    if cuenta_origen.pk == cuenta_destino.pk:
        raise MovimientoInvalido("El origen y el destino deben ser distintos.")
    for cuenta in (cuenta_origen, cuenta_destino):
        if cuenta.estado != EstadoRegistro.ACTIVO:
            raise MovimientoInvalido(f"«{cuenta.nombre}» está inactiva.")
    monto = _dinero(monto, "Monto", minimo=DOS)
    comision = _dinero(comision, "Comisión")
    itf = _dinero(itf, "ITF")
    fecha = fecha or timezone.localdate()
    if fecha > timezone.localdate():
        raise MovimientoInvalido("La fecha no puede ser futura.")

    if cuenta_origen.moneda == cuenta_destino.moneda:
        if tipo_cambio is not None:
            raise MovimientoInvalido("Entre cuentas de la misma moneda no hay tipo de cambio.")
        if monto_destino is not None and monto_destino != monto:
            raise MovimientoInvalido("Entre cuentas de la misma moneda entra lo mismo que sale.")
        recibe = monto
    else:
        if tipo_cambio is None or not isinstance(tipo_cambio, Decimal) or tipo_cambio <= 0:
            raise MovimientoInvalido(
                "Indique el tipo de cambio: las cuentas son de distinta moneda."
            )
        if tipo_cambio != tipo_cambio.quantize(CUATRO) or tipo_cambio > Decimal("9999.9999"):
            raise MovimientoInvalido("El tipo de cambio admite hasta 4 decimales.")
        recibe = convertir(monto, cuenta_origen.moneda, cuenta_destino.moneda, tipo_cambio)
        if monto_destino is not None:  # lo que de verdad abonó el banco, si difiere del cálculo
            recibe = _dinero(monto_destino, "Monto que recibe", minimo=DOS)
    if recibe <= 0:
        raise MovimientoInvalido("El monto que recibe debe ser mayor que cero.")

    glosa = " ".join((glosa or "").split())[:250]
    referencia = " ".join((referencia or "").split())[:60]
    transferencia = Transferencia.objects.create(
        empresa=empresa,
        empresa_destino=destino_empresa,
        numero=_siguiente_numero(empresa),
        cuenta_origen=cuenta_origen,
        cuenta_destino=cuenta_destino,
        clase=clase_de(cuenta_origen, cuenta_destino),
        fecha=fecha,
        monto_origen=monto,
        monto_destino=recibe,
        tipo_cambio=tipo_cambio,
        comision=comision,
        itf=itf,
        glosa=glosa,
        referencia=referencia,
    )

    def movimiento(*, e, cuenta, tipo, valor, codigo, texto):
        return servicios.registrar_movimiento(
            empresa=e,
            cuenta=cuenta,
            tipo=tipo,
            monto=valor,
            concepto=servicios.concepto_del_sistema(e, codigo),
            fecha=fecha,
            glosa=texto,
            referencia=referencia,
            origen_tipo=Origen.TRANSFERENCIA,
            origen_id=transferencia.pk,
        )

    etiqueta = transferencia.get_clase_display()
    detalle = f" · {glosa}" if glosa else ""
    movimiento(
        e=empresa,
        cuenta=cuenta_origen,
        tipo=TipoMovimiento.EGRESO,
        valor=monto,
        codigo="TRANSFERENCIA_SALIDA",
        texto=f"{etiqueta} N° {transferencia.numero:06d} a {cuenta_destino.nombre}{detalle}",
    )
    movimiento(
        e=destino_empresa,
        cuenta=cuenta_destino,
        tipo=TipoMovimiento.INGRESO,
        valor=recibe,
        codigo="TRANSFERENCIA_ENTRADA",
        texto=f"{etiqueta} N° {transferencia.numero:06d} desde {cuenta_origen.nombre}{detalle}",
    )
    if comision > 0:
        movimiento(
            e=empresa,
            cuenta=cuenta_origen,
            tipo=TipoMovimiento.EGRESO,
            valor=comision,
            codigo="COMISION_BANCARIA",
            texto=f"Comisión de la {etiqueta.lower()} N° {transferencia.numero:06d}",
        )
    if itf > 0:
        movimiento(
            e=empresa,
            cuenta=cuenta_origen,
            tipo=TipoMovimiento.EGRESO,
            valor=itf,
            codigo="ITF",
            texto=f"ITF de la {etiqueta.lower()} N° {transferencia.numero:06d}",
        )
    registrar(
        "caja.transferencia_registrada",
        recurso_tipo="transferencia",
        recurso_id=transferencia.pk,
        empresa_id=empresa.pk,
        resumen=(
            f"{etiqueta} N° {transferencia.numero:06d}: {monto} de {cuenta_origen.nombre} "
            f"a {cuenta_destino.nombre}"
        ),
        detalle={
            "origen": cuenta_origen.pk,
            "destino": cuenta_destino.pk,
            "monto": monto,
            "recibe": recibe,
            "tipo_cambio": tipo_cambio,
            "comision": comision,
            "itf": itf,
            "entre_empresas": destino_empresa.pk != empresa.pk,
        },
    )
    logger.info(
        "transferencia_registrada", extra={"empresa_id": empresa.pk, "id": transferencia.pk}
    )
    return transferencia


@transaction.atomic
def anular_transferencia(transferencia: Transferencia, *, motivo: str) -> Transferencia:
    """Anula la transferencia y todos sus movimientos (salida, entrada, comisión e ITF)."""
    transferencia.anular(motivo=motivo)  # valida el motivo y que no esté anulada
    servicios.anular_por_origen(
        Origen.TRANSFERENCIA, transferencia.pk, motivo=f"Transferencia anulada: {motivo.strip()}"
    )
    registrar(
        "caja.transferencia_anulada",
        recurso_tipo="transferencia",
        recurso_id=transferencia.pk,
        empresa_id=transferencia.empresa_id,
        resumen=f"Transferencia N° {transferencia.numero:06d} anulada",
        detalle={"motivo": motivo.strip()[:200], "monto": transferencia.monto_origen},
    )
    return transferencia
