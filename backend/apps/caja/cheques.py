"""Cheques recibidos de clientes y girados a proveedores: su estado y su cobro.

Recibido: EN_CARTERA → DEPOSITADO → COBRADO (o RECHAZADO). Al cobrarlo, su importe pasa de la
cuenta donde se anotó al cobrar la venta («cuenta de cheques») al banco, como una transferencia: así
el dinero no se cuenta dos veces. Un cheque rechazado NO mueve el importe (el dinero sigue anotado
donde estaba): solo registra, si se indica, la comisión que cobró el banco; la deuda del cliente
hay que volver a abrirla desde Ventas.

Emitido: GIRADO → COBRADO (o RECHAZADO o ANULADO). No mueve dinero: el pago al proveedor ya salió de
su cuenta al registrarlo en Compras con el método «Cheque». Aquí solo se vigila cuáles siguen sin
cobrar. Si un cheque girado se anula, el pago de la compra se anula aparte, desde Compras.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.inventario import periodos
from apps.mantenimiento.models import Cliente, CuentaFinanciera, EstadoRegistro, Proveedor
from apps.organizacion.models import Empresa

from . import servicios
from .exceptions import ChequeInvalido, ChequeNoModificable
from .models import Cheque, Origen, TipoMovimiento
from .transferencias import anular_transferencia, registrar_transferencia

logger = logging.getLogger(__name__)

CERO = Decimal("0")
DOS = Decimal("0.01")
DIAS_AVISO = 5
DIAS_EMITIDO_SIN_COBRAR = 30
Estado = Cheque.Estado
Tipo = Cheque.Tipo


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _dinero(valor, campo: str) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite() or valor != valor.quantize(DOS):
        raise ChequeInvalido(f"{campo}: indique un monto con hasta 2 decimales.")
    return valor


def _auditar(accion: str, cheque: Cheque, resumen: str, **detalle) -> None:
    registrar(
        accion,
        recurso_tipo="cheque",
        recurso_id=cheque.pk,
        empresa_id=cheque.empresa_id,
        resumen=f"Cheque {cheque.numero} ({cheque.banco}) {resumen}",
        detalle=detalle,
    )


def _bloquear(cheque: Cheque) -> Cheque:
    periodos.exigir_empresa(cheque.empresa)
    return Cheque.objects.select_for_update().get(pk=cheque.pk)


def _exigir(cheque: Cheque, permitidos: tuple[str, ...], accion: str) -> None:
    if cheque.estado not in permitidos:
        raise ChequeNoModificable(
            f"No se puede {accion} un cheque en estado «{cheque.get_estado_display()}»."
        )


def _cuenta_de(empresa: Empresa, cuenta: CuentaFinanciera | None, moneda: str, que: str):
    """Una cuenta de la empresa, activa y de la moneda del cheque."""
    if cuenta is None:
        return None
    if cuenta.empresa_id != empresa.pk or cuenta.estado != EstadoRegistro.ACTIVO:
        raise ChequeInvalido(f"{que}: elija una cuenta activa de la empresa.")
    if cuenta.moneda != moneda:
        raise ChequeInvalido(f"{que}: la cuenta debe ser de la misma moneda del cheque.")
    return cuenta


def _banco(empresa: Empresa, cuenta: CuentaFinanciera | None, moneda: str, que: str):
    cuenta = _cuenta_de(empresa, cuenta, moneda, que)
    if cuenta is not None and cuenta.tipo != CuentaFinanciera.Tipo.BANCO:
        raise ChequeInvalido(f"{que}: elija una cuenta de banco.")
    return cuenta


# ---------------------------------------------------------------------------
@transaction.atomic
def registrar_cheque(
    *,
    empresa: Empresa,
    tipo: str,
    numero: str,
    banco: str,
    importe: Decimal,
    fecha_emision: date,
    moneda: str = Cheque.Moneda.PEN,
    fecha_pago: date | None = None,
    tercero: str = "",
    cliente: Cliente | None = None,
    proveedor: Proveedor | None = None,
    cuenta: CuentaFinanciera | None = None,
    cuenta_cartera: CuentaFinanciera | None = None,
    glosa: str = "",
) -> Cheque:
    """Anota un cheque. El recibido queda EN_CARTERA; el emitido, GIRADO."""
    periodos.exigir_empresa(empresa)
    if tipo not in Tipo.values:
        raise ChequeInvalido("El tipo de cheque no es válido.")
    if moneda not in Cheque.Moneda.values:
        raise ChequeInvalido("La moneda no es válida.")
    numero, banco = _texto(numero, 30), _texto(banco, 60)
    if not numero or not banco:
        raise ChequeInvalido("Indique el número del cheque y el banco.")
    importe = _dinero(importe, "Importe")
    if importe <= 0:
        raise ChequeInvalido("El importe debe ser mayor que cero.")
    if not isinstance(fecha_emision, date) or fecha_emision > timezone.localdate():
        raise ChequeInvalido("La fecha de emisión no es válida o es futura.")
    if fecha_pago is not None and fecha_pago < fecha_emision:
        raise ChequeInvalido("La fecha de pago no puede ser anterior a la emisión.")
    if tipo == Tipo.RECIBIDO and proveedor is not None:
        raise ChequeInvalido("Un cheque recibido es de un cliente, no de un proveedor.")
    if tipo == Tipo.EMITIDO and cliente is not None:
        raise ChequeInvalido("Un cheque girado es a un proveedor, no a un cliente.")
    for tercero_fila in (cliente, proveedor):
        if tercero_fila is not None and tercero_fila.organizacion_id != empresa.organizacion_id:
            raise ChequeInvalido("El cliente o proveedor no pertenece a la organización.")
    elegido = cliente or proveedor
    nombre = _texto(tercero, 150) or (_texto(elegido.nombre, 150) if elegido else "")
    if not nombre:
        raise ChequeInvalido("Indique quién lo giró o a quién se giró.")
    if tipo == Tipo.EMITIDO:
        cuenta = _banco(empresa, cuenta, moneda, "Cuenta de giro")
        cuenta_cartera = None
    else:
        cuenta_cartera = _cuenta_de(empresa, cuenta_cartera, moneda, "Cuenta de cheques")
        cuenta = None
    if (
        Cheque.objects.filter(empresa=empresa, tipo=tipo, banco__iexact=banco, numero=numero)
        .exclude(estado=Estado.ANULADO)
        .exists()
    ):
        raise ChequeInvalido("Ya hay un cheque con ese número y banco.")
    cheque = Cheque.objects.create(
        empresa=empresa,
        tipo=tipo,
        estado=Estado.EN_CARTERA if tipo == Tipo.RECIBIDO else Estado.GIRADO,
        numero=numero,
        banco=banco,
        importe=importe,
        moneda=moneda,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        tercero=nombre,
        cliente=cliente,
        proveedor=proveedor,
        cuenta=cuenta,
        cuenta_cartera=cuenta_cartera,
        glosa=_texto(glosa, 250),
    )
    _auditar("caja.cheque_registrado", cheque, "registrado", tipo=tipo, importe=importe)
    return cheque


@transaction.atomic
def depositar(cheque: Cheque, *, cuenta: CuentaFinanciera, fecha: date | None = None) -> Cheque:
    """El cheque recibido se llevó al banco (todavía no es dinero hasta que lo paguen)."""
    actual = _bloquear(cheque)
    if actual.tipo != Tipo.RECIBIDO:
        raise ChequeNoModificable("Solo un cheque recibido se deposita.")
    _exigir(actual, (Estado.EN_CARTERA,), "depositar")
    fecha = fecha or timezone.localdate()
    if fecha > timezone.localdate() or fecha < actual.fecha_emision:
        raise ChequeInvalido("La fecha del depósito no es válida.")
    actual.cuenta = _banco(actual.empresa, cuenta, actual.moneda, "Banco de depósito")
    actual.estado, actual.depositado_en = Estado.DEPOSITADO, fecha
    actual.save(update_fields=["cuenta", "estado", "depositado_en"])
    _auditar("caja.cheque_depositado", actual, "depositado", cuenta=cuenta.pk)
    return actual


@transaction.atomic
def cobrar(
    cheque: Cheque,
    *,
    fecha: date | None = None,
    cuenta: CuentaFinanciera | None = None,
    cuenta_cartera: CuentaFinanciera | None = None,
    referencia: str = "",
) -> Cheque:
    """El banco pagó el cheque. En uno recibido el importe pasa de la cuenta de cheques al banco."""
    actual = _bloquear(cheque)
    fecha = fecha or timezone.localdate()
    if fecha > timezone.localdate() or fecha < actual.fecha_emision:
        raise ChequeInvalido("La fecha del cobro no es válida.")
    if actual.tipo == Tipo.EMITIDO:
        _exigir(actual, (Estado.GIRADO,), "cobrar")
        actual.estado, actual.cobrado_en = Estado.COBRADO, fecha
        actual.save(update_fields=["estado", "cobrado_en"])
        _auditar("caja.cheque_cobrado", actual, "cobrado por el proveedor")
        return actual

    _exigir(actual, (Estado.EN_CARTERA, Estado.DEPOSITADO), "cobrar")
    banco = _banco(actual.empresa, cuenta or actual.cuenta, actual.moneda, "Banco de depósito")
    cartera = _cuenta_de(
        actual.empresa, cuenta_cartera or actual.cuenta_cartera, actual.moneda, "Cuenta de cheques"
    )
    if banco is None:
        raise ChequeInvalido("Indique el banco donde se cobró el cheque.")
    if cartera is None:
        raise ChequeInvalido(
            "Indique la cuenta de cheques donde se anotó el cobro de la venta "
            "(se configura en Ventas, en «Cuentas de cobro»)."
        )
    if cartera.pk == banco.pk:
        raise ChequeInvalido("El banco debe ser distinto de la cuenta de cheques.")
    # Bloquea la cuenta de cheques: no se cobra lo que no se anotó al vender.
    CuentaFinanciera.objects.sin_ambito().select_for_update().get(pk=cartera.pk)
    por_cobrar = servicios.saldo_de(cartera)
    if actual.importe > por_cobrar:
        raise ChequeInvalido(
            f"En «{cartera.nombre}» solo hay {por_cobrar:,.2f} por cobrar: "
            f"no se pueden cobrar {actual.importe:,.2f}."
        )
    transferencia = registrar_transferencia(
        empresa=actual.empresa,
        cuenta_origen=cartera,
        cuenta_destino=banco,
        monto=actual.importe,
        fecha=fecha,
        glosa=f"Cobro del cheque {actual.numero} ({actual.banco})",
        referencia=_texto(referencia, 60) or actual.numero,
    )
    actual.cuenta, actual.cuenta_cartera = banco, cartera
    actual.estado, actual.cobrado_en = Estado.COBRADO, fecha
    actual.depositado_en = actual.depositado_en or fecha
    actual.transferencia = transferencia
    actual.save(
        update_fields=[
            "cuenta",
            "cuenta_cartera",
            "estado",
            "cobrado_en",
            "depositado_en",
            "transferencia",
        ]
    )
    _auditar("caja.cheque_cobrado", actual, "cobrado", importe=actual.importe, banco=banco.pk)
    return actual


@transaction.atomic
def rechazar(
    cheque: Cheque,
    *,
    motivo: str,
    comision: Decimal = CERO,
    fecha: date | None = None,
) -> Cheque:
    """El banco no pagó el cheque (sin fondos, firma, etc.). Opcionalmente anota su comisión."""
    motivo = _texto(motivo, 250)
    if len(motivo) < 3:
        raise ChequeInvalido("Indique el motivo del rechazo.")
    comision = _dinero(comision, "Comisión")
    actual = _bloquear(cheque)
    if actual.tipo == Tipo.RECIBIDO:
        _exigir(actual, (Estado.EN_CARTERA, Estado.DEPOSITADO), "rechazar")
    else:
        _exigir(actual, (Estado.GIRADO,), "rechazar")
    if comision < 0:
        raise ChequeInvalido("La comisión no puede ser negativa.")
    fecha = fecha or timezone.localdate()
    if comision > 0:
        if actual.cuenta is None:
            raise ChequeInvalido("Para anotar la comisión, indique primero el banco del cheque.")
        servicios.registrar_movimiento(
            empresa=actual.empresa,
            cuenta=actual.cuenta,
            tipo=TipoMovimiento.EGRESO,
            monto=comision,
            concepto=servicios.concepto_del_sistema(actual.empresa, "COMISION_BANCARIA"),
            fecha=fecha,
            glosa=f"Comisión por cheque {actual.numero} rechazado",
            referencia=actual.numero,
            origen_tipo=Origen.CHEQUE_RECHAZADO,
            origen_id=actual.pk,
        )
    actual.estado, actual.motivo = Estado.RECHAZADO, motivo
    actual.save(update_fields=["estado", "motivo"])
    _auditar("caja.cheque_rechazado", actual, "rechazado", motivo=motivo[:200], comision=comision)
    return actual


@transaction.atomic
def anular(cheque: Cheque, *, motivo: str) -> Cheque:
    """Anula un cheque que aún no se depositó ni se cobró (devuelto o perdido)."""
    motivo = _texto(motivo, 250)
    if len(motivo) < 3:
        raise ChequeInvalido("Indique el motivo de la anulación.")
    actual = _bloquear(cheque)
    _exigir(actual, (Estado.EN_CARTERA, Estado.GIRADO), "anular")
    actual.estado, actual.motivo = Estado.ANULADO, motivo
    actual.save(update_fields=["estado", "motivo"])
    _auditar("caja.cheque_anulado", actual, "anulado", motivo=motivo[:200])
    return actual


@transaction.atomic
def deshacer_cobro(cheque: Cheque, *, motivo: str) -> Cheque:
    """Corrige un cobro marcado por error: el dinero vuelve a la cuenta de cheques."""
    motivo = _texto(motivo, 250)
    if len(motivo) < 3:
        raise ChequeInvalido("Indique el motivo.")
    actual = _bloquear(cheque)
    _exigir(actual, (Estado.COBRADO,), "corregir el cobro de")
    if actual.transferencia_id:
        anular_transferencia(actual.transferencia, motivo=f"Cobro de cheque deshecho: {motivo}")
        actual.transferencia = None
    if actual.tipo == Tipo.EMITIDO:
        actual.estado = Estado.GIRADO
    else:
        actual.estado = Estado.DEPOSITADO if actual.depositado_en else Estado.EN_CARTERA
    actual.cobrado_en = None
    actual.save(update_fields=["estado", "cobrado_en", "transferencia"])
    _auditar("caja.cheque_cobro_deshecho", actual, "con el cobro deshecho", motivo=motivo[:200])
    return actual


# ---------------------------------------------------------------------------
# Seguimiento
# ---------------------------------------------------------------------------
def pendientes(empresa: Empresa):
    """Los cheques que todavía hay que cobrar o vigilar."""
    return Cheque.objects.filter(
        empresa=empresa, estado__in=(Estado.EN_CARTERA, Estado.DEPOSITADO, Estado.GIRADO)
    )


def resumen_de_avisos(empresa: Empresa, hoy: date | None = None) -> dict:
    """Conteos para los avisos de caja: recibidos por vencer o vencidos y girados sin cobrar."""
    hoy = hoy or timezone.localdate()
    base = pendientes(empresa)
    recibidos = base.filter(tipo=Tipo.RECIBIDO)
    limite = hoy + timedelta(days=DIAS_AVISO)
    # «vence» = fecha de pago (o emisión) + 30 días; se filtra en Python sobre pocos cheques.
    vencidos = por_vencer = 0
    for c in recibidos.only("fecha_emision", "fecha_pago"):
        if c.vence < hoy:
            vencidos += 1
        elif c.vence <= limite:
            por_vencer += 1
    sin_cobrar = sum(
        1
        for c in base.filter(tipo=Tipo.EMITIDO).only("fecha_emision", "fecha_pago")
        if (hoy - (c.fecha_pago or c.fecha_emision)).days > DIAS_EMITIDO_SIN_COBRAR
    )
    return {"vencidos": vencidos, "por_vencer": por_vencer, "emitidos_sin_cobrar": sin_cobrar}
