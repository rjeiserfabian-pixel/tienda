"""Registrar y anular movimientos de caja y bancos, y calcular saldos.

Los demás módulos (compras hoy; ventas y gastos después) registran su dinero por aquí con su
``origen_tipo`` y ``origen_id``, sin que caja conozca sus modelos. Todo movimiento nace dentro de la
transacción de quien lo genera: si esa operación falla, el movimiento tampoco queda.
"""

import logging
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Case, DecimalField, F, Max, Q, Sum, Value, When
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.conceptos_caja import asegurar_concepto
from apps.mantenimiento.models import ConceptoCaja, Correlativo, CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa

from .exceptions import (
    MovimientoInvalido,
    MovimientoNoAnulable,
    SaldoInsuficiente,
    SesionRequerida,
)
from .models import MovimientoCaja, Origen, SesionCaja, TipoMovimiento

logger = logging.getLogger(__name__)

CERO = Decimal("0")
DOS = Decimal("0.01")
MAXIMO = Decimal("9999999999999.99")
_DINERO = DecimalField(max_digits=16, decimal_places=2)


def _exigir_empresa(empresa: Empresa) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa.pk):
        raise EmpresaNoHabilitada()


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"caja:movimiento:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def concepto_del_sistema(empresa: Empresa, codigo: str) -> ConceptoCaja:
    """El concepto de fábrica; si la organización aún no los tiene cargados, se cargan."""
    return asegurar_concepto(empresa.organizacion_id, codigo)


def _sesion_para(cuenta: CuentaFinanciera) -> SesionCaja | None:
    """La sesión abierta donde cae el efectivo; las cajas con sesión obligatoria la exigen."""
    if cuenta.tipo != CuentaFinanciera.Tipo.CAJA:
        return None
    sesion = (
        SesionCaja.objects.select_for_update()
        .filter(cuenta=cuenta, estado=SesionCaja.Estado.ABIERTA)
        .first()
    )
    if sesion is None and cuenta.exige_sesion:
        raise SesionRequerida(f"Abra la sesión de «{cuenta.nombre}» para mover su efectivo.")
    return sesion


# Lo que ya pasó fuera del sistema (el conteo del cajón, lo que cobró el banco o el procesador):
# se asienta aunque deje la cuenta en negativo, porque negarlo no cambia la realidad.
_SALIDAS_SIN_TOPE = (Origen.ARQUEO, Origen.EXTRACTO, Origen.COMISION_TARJETA)


def _exigir_saldo(cuenta: CuentaFinanciera, monto: Decimal) -> None:
    """Una salida no puede dejar en negativo una caja de efectivo (ni un banco sin sobregiro)."""
    if not settings.CAJA_BLOQUEA_SALDO_NEGATIVO:
        return
    if cuenta.tipo != CuentaFinanciera.Tipo.CAJA and cuenta.permite_saldo_negativo:
        return
    # Se bloquea la cuenta: dos pagos a la vez no pueden gastar el mismo dinero.
    CuentaFinanciera.objects.select_for_update().filter(pk=cuenta.pk).first()
    disponible = saldo_de(cuenta)
    if disponible >= monto:
        return
    simbolo = "US$" if cuenta.moneda == "USD" else "S/"
    raise SaldoInsuficiente(
        f"«{cuenta.nombre}» tiene {simbolo} {max(disponible, CERO):.2f} y esta salida es de "
        f"{simbolo} {monto:.2f}. Registra primero el ingreso que falta (Caja y bancos → "
        "Movimientos) o mueve dinero desde otra caja o cuenta (Transferencias)."
    )


@transaction.atomic
def registrar_movimiento(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    tipo: str,
    monto: Decimal,
    concepto: ConceptoCaja,
    fecha: date | None = None,
    glosa: str = "",
    referencia: str = "",
    origen_tipo: str = Origen.MANUAL,
    origen_id: int | None = None,
    medio_pago=None,
) -> MovimientoCaja:
    """Registra un ingreso o un egreso de una caja o cuenta de la empresa."""
    _exigir_empresa(empresa)
    if tipo not in TipoMovimiento.values:
        raise MovimientoInvalido("El tipo de movimiento no es válido.")
    if cuenta.empresa_id != empresa.pk:
        raise MovimientoInvalido("La caja o cuenta no pertenece a la empresa.")
    if cuenta.estado != EstadoRegistro.ACTIVO:
        raise MovimientoInvalido("La caja o cuenta está inactiva.")
    if concepto.organizacion_id != empresa.organizacion_id:
        raise MovimientoInvalido("El concepto no pertenece a la organización.")
    if concepto.estado != EstadoRegistro.ACTIVO:
        raise MovimientoInvalido("El concepto está inactivo.")
    if concepto.tipo != tipo:
        raise MovimientoInvalido("El concepto no corresponde a ese tipo de movimiento.")
    if not isinstance(monto, Decimal) or not monto.is_finite() or monto != monto.quantize(DOS):
        raise MovimientoInvalido("El monto admite hasta 2 decimales.")
    if monto <= 0:
        raise MovimientoInvalido("El monto debe ser mayor que cero.")
    if monto > MAXIMO:
        raise MovimientoInvalido("El monto es demasiado grande.")
    fecha = fecha or timezone.localdate()
    if fecha > timezone.localdate():
        raise MovimientoInvalido("La fecha no puede ser futura.")
    # Un movimiento hecho a mano no puede ser anterior al saldo con que se abrió la cuenta.
    apertura = cuenta.fecha_saldo_inicial
    if origen_tipo in Origen.A_MANO and apertura and fecha < apertura:
        raise MovimientoInvalido(
            f"La fecha no puede ser anterior al saldo inicial de la cuenta ({apertura:%d/%m/%Y})."
        )
    if medio_pago is not None and (
        medio_pago.organizacion_id != empresa.organizacion_id
        or medio_pago.estado != EstadoRegistro.ACTIVO
    ):
        raise MovimientoInvalido("El método de pago no existe o está inactivo.")
    glosa = " ".join((glosa or "").split())[:250]
    referencia = " ".join((referencia or "").split())[:60]
    sesion = _sesion_para(cuenta)
    if tipo == TipoMovimiento.EGRESO and origen_tipo not in _SALIDAS_SIN_TOPE:
        _exigir_saldo(cuenta, monto)

    movimiento = MovimientoCaja.objects.create(
        sesion=sesion,
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        cuenta=cuenta,
        fecha=fecha,
        tipo=tipo,
        monto=monto,
        concepto=concepto,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        medio_pago=medio_pago,
    )
    registrar(
        "caja.movimiento_registrado",
        recurso_tipo="movimiento_caja",
        recurso_id=movimiento.pk,
        empresa_id=empresa.pk,
        resumen=(
            f"{movimiento.get_tipo_display()} N° {movimiento.numero:06d} "
            f"de {monto} en {cuenta.nombre}"
        ),
        detalle={
            "cuenta": cuenta.pk,
            "monto": monto,
            "concepto": concepto.nombre,
            "origen": origen_tipo,
            "origen_id": origen_id,
        },
    )
    return movimiento


def anular_movimiento(
    movimiento: MovimientoCaja,
    *,
    motivo: str,
    desde_origen: bool = False,
    ignorar_sesion: bool = False,
):
    """Anula un movimiento: deja de contar en el saldo (los de otro módulo se anulan allí)."""
    if not desde_origen and not movimiento.es_manual:
        raise MovimientoNoAnulable(
            "Este movimiento viene de otro documento (una compra, por ejemplo): "
            "anula ese documento."
        )
    from .models import LineaEstadoCuenta  # el extracto conoce al movimiento, no al revés

    if LineaEstadoCuenta.objects.filter(movimiento=movimiento).exists():
        raise MovimientoNoAnulable(
            "El movimiento está conciliado con el estado de cuenta del banco: "
            "deshaz esa conciliación primero."
        )
    if (
        not ignorar_sesion
        and movimiento.sesion_id
        and SesionCaja.objects.filter(
            pk=movimiento.sesion_id, estado=SesionCaja.Estado.CERRADA
        ).exists()
    ):
        raise MovimientoNoAnulable(
            "El movimiento es de una sesión de caja ya cerrada: un supervisor debe reabrirla."
        )
    _exigir_empresa(movimiento.empresa)
    with transaction.atomic():
        movimiento.anular(motivo=motivo)
        registrar(
            "caja.movimiento_anulado",
            recurso_tipo="movimiento_caja",
            recurso_id=movimiento.pk,
            empresa_id=movimiento.empresa_id,
            resumen=f"Movimiento N° {movimiento.numero:06d} anulado",
            detalle={"motivo": (motivo or "").strip()[:200], "monto": movimiento.monto},
        )
    return movimiento


_APORTE_DE = {
    Origen.PAGO_COMPRA: Origen.APORTE_PAGO_COMPRA,
    Origen.PAGO_GASTO: Origen.APORTE_PAGO_GASTO,
}


def anular_por_origen(origen_tipo: str, origen_id: int, *, motivo: str) -> int:
    """Anula los movimientos vigentes que generó un documento (por ejemplo, un pago de compra)."""
    # Si un socio puso el dinero para ese pago, su aporte se anula con él.
    tipos = [origen_tipo, _APORTE_DE.get(origen_tipo, origen_tipo)]
    pendientes = list(
        MovimientoCaja.objects.filter(
            origen_tipo__in=tipos, origen_id=origen_id, estado=MovimientoCaja.Estado.EMITIDO
        ).order_by("-id")
    )
    for movimiento in pendientes:
        anular_movimiento(movimiento, motivo=motivo, desde_origen=True)
    return len(pendientes)


# ---------------------------------------------------------------------------
# Lo que otros módulos registran
# ---------------------------------------------------------------------------
def _aporte_del_socio(empresa, cuenta, monto, fecha, glosa, origen_tipo, pago_id, medio_pago):
    """El socio pagó de su bolsillo: ese dinero entra a la caja y el pago lo gasta enseguida."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.INGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "APORTE_CAPITAL"),
        fecha=fecha,
        glosa=f"Aporte del socio para pagar: {glosa}"[:250],
        origen_tipo=origen_tipo,
        origen_id=pago_id,
        medio_pago=medio_pago,
    )


def registrar_pago_de_compra(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    pago_id: int,
    medio_pago=None,
    aporte_socio: bool = False,
) -> MovimientoCaja:
    """Egreso por un pago a un proveedor (al contado, de una cuota o del flete)."""
    if aporte_socio:
        _aporte_del_socio(
            empresa, cuenta, monto, fecha, glosa, Origen.APORTE_PAGO_COMPRA, pago_id, medio_pago
        )
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "PAGO_PROVEEDOR"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.PAGO_COMPRA,
        origen_id=pago_id,
        medio_pago=medio_pago,
    )


def registrar_reembolso_de_compra(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    reembolso_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Ingreso por el dinero que un proveedor devuelve por mercadería que se le devolvió."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.INGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "DEVOLUCION_COMPRA"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.REEMBOLSO_COMPRA,
        origen_id=reembolso_id,
        medio_pago=medio_pago,
    )


def registrar_pago_de_gasto(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    pago_id: int,
    medio_pago=None,
    aporte_socio: bool = False,
) -> MovimientoCaja:
    """Egreso por el pago de un gasto (luz, alquiler, un taxi…)."""
    if aporte_socio:
        _aporte_del_socio(
            empresa, cuenta, monto, fecha, glosa, Origen.APORTE_PAGO_GASTO, pago_id, medio_pago
        )
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "PAGO_GASTO"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.PAGO_GASTO,
        origen_id=pago_id,
        medio_pago=medio_pago,
    )


def registrar_cobro_de_venta(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    cobro_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Ingreso por lo que un cliente pagó en una venta (efectivo, Yape, tarjeta, transferencia…)."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.INGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "COBRO_VENTA"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.COBRO_VENTA,
        origen_id=cobro_id,
        medio_pago=medio_pago,
    )


def registrar_adelanto_de_servicio(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    adelanto_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Ingreso por lo que un cliente deja por adelantado de un servicio técnico (recibo interno)."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.INGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "ADELANTO_SERVICIO"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.ADELANTO_SERVICIO,
        origen_id=adelanto_id,
        medio_pago=medio_pago,
    )


def registrar_adelanto_de_personal(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    adelanto_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Egreso por el adelanto de sueldo o el préstamo que se entrega a un trabajador."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "ADELANTO_PERSONAL"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.ADELANTO_PERSONAL,
        origen_id=adelanto_id,
        medio_pago=medio_pago,
    )


def registrar_pago_de_planilla(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    pago_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Egreso por el sueldo neto que se paga a un trabajador al cerrar la planilla del mes."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "PAGO_PLANILLA"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.PAGO_PLANILLA,
        origen_id=pago_id,
        medio_pago=medio_pago,
    )


def registrar_deposito_de_cts(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    cts_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Egreso por la CTS que se deposita a un trabajador."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "DEPOSITO_CTS"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.DEPOSITO_CTS,
        origen_id=cts_id,
        medio_pago=medio_pago,
    )


def registrar_devolucion_de_adelanto(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    adelanto_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Egreso por un adelanto que se le devuelve al cliente."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "DEVOLUCION_ADELANTO"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.DEVOLUCION_ADELANTO,
        origen_id=adelanto_id,
        medio_pago=medio_pago,
    )


def registrar_reembolso_de_venta(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    reembolso_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Egreso por lo que se le devuelve a un cliente con una nota de crédito."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.EGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "DEVOLUCION_VENTA"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.REEMBOLSO_VENTA,
        origen_id=reembolso_id,
        medio_pago=medio_pago,
    )


def registrar_abono_de_venta(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    monto: Decimal,
    fecha: date,
    referencia: str,
    glosa: str,
    abono_id: int,
    medio_pago=None,
) -> MovimientoCaja:
    """Ingreso por lo que un cliente abona a una venta a crédito."""
    return registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo=TipoMovimiento.INGRESO,
        monto=monto,
        concepto=concepto_del_sistema(empresa, "COBRO_VENTA"),
        fecha=fecha,
        glosa=glosa,
        referencia=referencia,
        origen_tipo=Origen.ABONO_VENTA,
        origen_id=abono_id,
        medio_pago=medio_pago,
    )


# ---------------------------------------------------------------------------
# Saldos
# ---------------------------------------------------------------------------
def _firmado():
    return Case(
        When(tipo=TipoMovimiento.INGRESO, then=F("monto")),
        default=-F("monto"),
        output_field=_DINERO,
    )


def saldo_de(cuenta: CuentaFinanciera, hasta: date | None = None) -> Decimal:
    """Saldo inicial más ingresos menos egresos vigentes (hasta una fecha, si se indica)."""
    movimientos = MovimientoCaja.objects.filter(cuenta=cuenta, estado=MovimientoCaja.Estado.EMITIDO)
    if hasta is not None:
        movimientos = movimientos.filter(fecha__lte=hasta)
    neto = movimientos.aggregate(neto=Sum(_firmado()))["neto"] or CERO
    return cuenta.saldo_inicial + neto


def saldos_de_la_empresa(empresa: Empresa) -> list[dict]:
    """Cada caja o cuenta de la empresa con su saldo, lo que entró, lo que salió y su movimiento."""
    resumen = {
        fila["cuenta_id"]: fila
        for fila in MovimientoCaja.objects.filter(
            empresa=empresa, estado=MovimientoCaja.Estado.EMITIDO
        )
        .values("cuenta_id")
        .annotate(
            ingresos=Sum("monto", filter=Q(tipo=TipoMovimiento.INGRESO)),
            egresos=Sum("monto", filter=Q(tipo=TipoMovimiento.EGRESO)),
            ultimo=Max("fecha"),
            cantidad=Sum(Value(1)),
        )
    }
    cuentas = CuentaFinanciera.objects.filter(empresa=empresa).select_related("sucursal")
    filas = []
    for cuenta in cuentas:
        r = resumen.get(cuenta.pk)
        if cuenta.estado != EstadoRegistro.ACTIVO and r is None:
            continue  # una cuenta inactiva sin movimientos no aporta nada
        ingresos = (r or {}).get("ingresos") or CERO
        egresos = (r or {}).get("egresos") or CERO
        filas.append(
            {
                "cuenta": cuenta,
                "ingresos": ingresos,
                "egresos": egresos,
                "saldo": cuenta.saldo_inicial + ingresos - egresos,
                "movimientos": (r or {}).get("cantidad") or 0,
                "ultimo_movimiento": (r or {}).get("ultimo"),
            }
        )
    filas.sort(key=lambda f: (f["cuenta"].tipo, f["cuenta"].nombre.lower()))
    return filas
