"""Adelantos de los clientes: recibo interno, caja y descuento al facturar.

Un adelanto es dinero que el cliente deja antes de que el servicio esté hecho. Se le da un recibo
interno (RA-0001); el dinero entra a la caja ese día. Al entregar, el comprobante sale por el total
y el adelanto se descuenta de lo que paga. Si el servicio no se hace, se le devuelve con un egreso
de caja (no hay nota de crédito: nunca se facturó). Un adelanto sin aplicar ni devolver queda «por
devolver» y bloquea entregar el equipo sin cobro, para que el dinero del cliente no se pierda.

El adelanto solo se descuenta del comprobante de la empresa que lo recibió: su dinero está en su
caja. Si la otra empresa también factura, cobra su parte completa al entregar.
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.mantenimiento.models import Correlativo, EstadoRegistro, MedioPago
from apps.ventas import servicios as ventas
from apps.ventas.models import ComprobanteVenta
from apps.ventas.servicios import CobroPrevio

from .exceptions import OrdenInvalida
from .models import AdelantoServicio, EstadoAdelanto, EstadoOrden, OrdenServicio

logger = logging.getLogger(__name__)

CERO = Decimal("0")
CENTAVO = Decimal("0.01")
MONTO_MAXIMO = Decimal("99999.99")
MOTIVO_MINIMO = 5


def _motivo(texto: str) -> str:
    motivo = " ".join((texto or "").split())[:250]
    if len(motivo) < MOTIVO_MINIMO:
        raise OrdenInvalida("Explique el motivo con unas palabras.")
    return motivo


def disponibles(orden: OrdenServicio) -> QuerySet[AdelantoServicio]:
    """Los adelantos que el cliente tiene a su favor: sin aplicar, o cuyo comprobante se anuló."""
    return AdelantoServicio.objects.filter(orden=orden, estado=EstadoAdelanto.VIGENTE).filter(
        Q(comprobante__isnull=True) | Q(comprobante__estado=ComprobanteVenta.Estado.ANULADO)
    )


def total_disponible(orden: OrdenServicio) -> Decimal:
    return disponibles(orden).aggregate(s=Sum("monto"))["s"] or CERO


def resumen(orden: OrdenServicio) -> dict:
    """Cuánto hay por descontar, cuánto ya se descontó y cuánto se devolvió."""
    todos = list(AdelantoServicio.objects.filter(orden=orden))
    libres = {a.pk for a in disponibles(orden)}
    return {
        "disponible": _suma(a for a in todos if a.pk in libres),
        "aplicado": _suma(
            a for a in todos if a.estado == EstadoAdelanto.VIGENTE and a.pk not in libres
        ),
        "devuelto": _suma(a for a in todos if a.estado == EstadoAdelanto.DEVUELTO),
    }


def _suma(filas) -> Decimal:
    return sum((a.monto for a in filas), CERO)


def tope(orden: OrdenServicio) -> Decimal | None:
    """Lo máximo que se puede adelantar: el total del presupuesto (lo cobra la empresa de la orden)."""
    from . import presupuesto

    vigente = presupuesto.vigente_de(orden)
    if vigente is None:
        return None
    total = sum((ln.total for ln in vigente.proforma.lineas.all()), CERO)
    return total if total > 0 else None


@transaction.atomic
def registrar_adelanto(
    orden: OrdenServicio,
    *,
    monto: Decimal,
    medio_pago: MedioPago,
    referencia: str = "",
    fecha: date | None = None,
) -> AdelantoServicio:
    """Recibe un adelanto: da el recibo interno y entra el dinero a la caja de la empresa."""
    actual = (
        OrdenServicio.objects.select_for_update(of=("self",))
        .select_related("empresa", "sucursal", "cliente")
        .get(pk=orden.pk)
    )
    if actual.estado == EstadoOrden.ENTREGADO:
        raise OrdenInvalida("La orden ya está entregada: no se reciben más adelantos.")
    if actual.es_garantia:
        raise OrdenInvalida("Un reingreso por garantía no se cobra: no lleva adelanto.")
    if (
        not isinstance(monto, Decimal)
        or not monto.is_finite()
        or monto != monto.quantize(CENTAVO)
        or not (CENTAVO <= monto <= MONTO_MAXIMO)
    ):
        raise OrdenInvalida("El adelanto debe ser un monto mayor que cero, con hasta 2 decimales.")
    empresa = actual.empresa
    if medio_pago.organizacion_id != empresa.organizacion_id or (
        medio_pago.estado != EstadoRegistro.ACTIVO
    ):
        raise OrdenInvalida("El método de pago no está disponible.")
    limite = tope(actual)
    if limite is not None and total_disponible(actual) + monto > limite:
        libre = max(limite - total_disponible(actual), CERO)
        raise OrdenInvalida(
            f"Los adelantos no pueden pasar del total que cobra la empresa (S/ {limite:,.2f}). "
            f"Se pueden recibir hasta S/ {libre:,.2f} más."
        )
    cuenta = ventas.resolver_cuenta(empresa, medio_pago, actual.sucursal, "PEN")
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id,
        clave=f"servicio_tecnico:adelanto:{empresa.pk}",
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    hoy = fecha or timezone.localdate()
    adelanto = AdelantoServicio.objects.create(
        empresa=empresa,
        orden=actual,
        numero=fila.ultimo,
        monto=monto,
        medio_pago=medio_pago,
        cuenta=cuenta,
        referencia=" ".join((referencia or "").split())[:60],
        fecha=hoy,
    )
    if medio_pago.requiere_referencia and not adelanto.referencia:
        raise OrdenInvalida(f"Indique el número de operación del pago con {medio_pago.nombre}.")
    movimiento = caja.registrar_adelanto_de_servicio(
        empresa=empresa,
        cuenta=cuenta,
        monto=monto,
        fecha=hoy,
        referencia=adelanto.referencia or adelanto.codigo,
        glosa=f"Adelanto {adelanto.codigo} · {actual.codigo} · {actual.cliente.nombre}"[:250],
        adelanto_id=adelanto.pk,
        medio_pago=medio_pago,
    )
    adelanto.movimiento_caja = movimiento
    adelanto.save(update_fields=["movimiento_caja"])
    registrar(
        "servicio_tecnico.adelanto_recibido",
        recurso_tipo="adelanto_servicio",
        recurso_id=adelanto.pk,
        empresa_id=empresa.pk,
        resumen=f"{adelanto.codigo}: S/ {monto:,.2f} por adelantado de {actual.codigo}",
        detalle={"orden": actual.pk, "medio": medio_pago.nombre},
    )
    return adelanto


def _bloquear(adelanto: AdelantoServicio) -> AdelantoServicio:
    """El adelanto bloqueado, y solo si el cliente todavía lo tiene a favor."""
    actual = (
        AdelantoServicio.objects.select_for_update(of=("self",))
        .select_related("empresa", "cuenta", "medio_pago", "orden")
        .get(pk=adelanto.pk)
    )
    if actual.estado != EstadoAdelanto.VIGENTE:
        raise OrdenInvalida(
            f"El recibo {actual.codigo} ya está {actual.get_estado_display().lower()}."
        )
    if (
        actual.comprobante_id is not None
        and actual.comprobante.estado == ComprobanteVenta.Estado.EMITIDO
    ):
        raise OrdenInvalida(
            f"El recibo {actual.codigo} ya se descontó del comprobante "
            f"{actual.comprobante.numero_completo}: no se puede devolver ni anular."
        )
    return actual


@transaction.atomic
def devolver(adelanto: AdelantoServicio, *, motivo: str) -> AdelantoServicio:
    """Le devuelve el dinero al cliente por donde entró a la caja. No lleva nota de crédito."""
    motivo = _motivo(motivo)
    actual = _bloquear(adelanto)
    hoy = timezone.localdate()
    caja.registrar_devolucion_de_adelanto(
        empresa=actual.empresa,
        cuenta=actual.cuenta,
        monto=actual.monto,
        fecha=hoy,
        referencia=actual.codigo,
        glosa=f"Devolución del adelanto {actual.codigo} · {actual.orden.codigo}"[:250],
        adelanto_id=actual.pk,
        medio_pago=actual.medio_pago,
    )
    actual.estado = EstadoAdelanto.DEVUELTO
    actual.devuelto_en = timezone.now()
    actual.devolucion_motivo = motivo
    actual.save(update_fields=["estado", "devuelto_en", "devolucion_motivo"])
    registrar(
        "servicio_tecnico.adelanto_devuelto",
        recurso_tipo="adelanto_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo}: S/ {actual.monto:,.2f} devueltos al cliente",
        detalle={"motivo": motivo},
    )
    return actual


@transaction.atomic
def anular(adelanto: AdelantoServicio, *, motivo: str) -> AdelantoServicio:
    """Anula un recibo emitido por error: el ingreso a la caja se deshace (no sale dinero)."""
    motivo = _motivo(motivo)
    actual = _bloquear(adelanto)
    caja.anular_por_origen(
        Origen.ADELANTO_SERVICIO, actual.pk, motivo=f"Recibo {actual.codigo}: {motivo}"
    )
    actual.estado = EstadoAdelanto.ANULADO
    actual.anulado_en = timezone.now()
    actual.anulacion_motivo = motivo
    actual.save(update_fields=["estado", "anulado_en", "anulacion_motivo"])
    registrar(
        "servicio_tecnico.adelanto_anulado",
        recurso_tipo="adelanto_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo} anulado",
        detalle={"motivo": motivo},
    )
    return actual


def cobros_previos(orden: OrdenServicio) -> list[CobroPrevio]:
    """Los adelantos disponibles, listos para descontarlos al facturar."""
    return [
        CobroPrevio(
            empresa=a.empresa,
            monto=a.monto,
            medio_pago=a.medio_pago,
            cuenta=a.cuenta,
            referencia=a.codigo,
        )
        for a in disponibles(orden).select_related("empresa", "medio_pago", "cuenta")
    ]


def aplicar(orden: OrdenServicio, venta) -> int:
    """Marca los adelantos como descontados del comprobante de su empresa."""
    por_empresa = {c.empresa_id: c for c in venta.comprobantes.all()}
    ahora = timezone.now()
    n = 0
    for adelanto in disponibles(orden).select_for_update(of=("self",)):
        adelanto.comprobante = por_empresa[adelanto.empresa_id]
        adelanto.aplicado_en = ahora
        adelanto.save(update_fields=["comprobante", "aplicado_en"])
        n += 1
    return n


def exigir_sin_pendientes(orden: OrdenServicio) -> None:
    """Para entregar sin cobrar, el cliente no puede tener dinero a favor sin devolver."""
    pendiente = total_disponible(orden)
    if pendiente > 0:
        raise OrdenInvalida(
            f"El cliente tiene S/ {pendiente:,.2f} de adelanto por devolver: "
            "devuélvelo antes de entregar el equipo."
        )
