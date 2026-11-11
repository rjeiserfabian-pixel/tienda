"""Ventas por cobrar: abonos a las cuotas de una venta a crédito y su reversión.

Un abono entra a la caja o cuenta de la empresa del comprobante (según el método de pago) y se
aplica a las cuotas más antiguas primero, o solo a las elegidas. Puede cubrir varias cuotas y
quedan guardadas sus aplicaciones, así anularlo devuelve a cada cuota exactamente lo que recibió.
Cada empresa cobra lo suyo: se abona comprobante por comprobante.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.inventario import periodos
from apps.mantenimiento.models import EstadoRegistro, SerieComprobante, TipoComprobante
from apps.mantenimiento.series import siguiente_numero

from . import cobros
from .exceptions import VentaInvalida, VentaNoAnulable
from .models import (
    AbonoVenta,
    AplicacionAbono,
    ComprobanteVenta,
    CuotaVenta,
    FormaPago,
    ReciboCobranza,
)
from .servicios import CobroEntrada, _cobros_validos, resolver_cuenta

CERO = Decimal("0")


def _cuotas_bloqueadas(comprobante: ComprobanteVenta) -> list[CuotaVenta]:
    """Las cuotas del comprobante, bloqueadas y en orden: dos abonos a la vez no se pisan."""
    return list(
        CuotaVenta.objects.select_for_update().filter(comprobante=comprobante).order_by("numero")
    )


def saldo_de(comprobante: ComprobanteVenta) -> Decimal:
    """Lo que falta cobrar de un comprobante vendido a crédito."""
    return sum(
        (c.monto - c.pagado for c in CuotaVenta.objects.filter(comprobante=comprobante)), CERO
    )


def repartir(cuotas: list[CuotaVenta], monto: Decimal, cuota_ids: list[int] | None) -> list[tuple]:
    """``[(cuota, monto)]``: a las cuotas elegidas, o a las pendientes de la más antigua primero."""
    candidatas = cuotas
    if cuota_ids:
        elegidas = set(cuota_ids)
        candidatas = [c for c in cuotas if c.pk in elegidas]
        if len(candidatas) != len(elegidas):
            raise VentaInvalida("Una cuota no pertenece al comprobante.")
        disponible = sum((c.monto - c.pagado for c in candidatas), CERO)
        if monto > disponible:
            raise VentaInvalida(f"Las cuotas elegidas solo tienen pendiente {disponible}.")
    restante = monto
    aplicado = []
    for cuota in candidatas:
        pendiente = cuota.monto - cuota.pagado
        if pendiente <= 0 or restante <= 0:
            continue
        parte = min(pendiente, restante)
        aplicado.append((cuota, parte))
        restante -= parte
    return aplicado


def series_de_recibo(empresa_id: int) -> list[dict]:
    """Las series de recibos de cobranza activas de la empresa, con su próximo número."""
    from apps.mantenimiento import series as numeracion

    return [
        {
            "id": x.pk,
            "serie": x.serie,
            "nombre": x.nombre,
            "sucursal": x.sucursal_id,
            "proximo": numeracion.formatear(x.serie, x.proximo_numero),
        }
        for x in SerieComprobante.objects.sin_ambito()
        .filter(empresa_id=empresa_id, tipo_comprobante__codigo="RI", estado=EstadoRegistro.ACTIVO)
        .order_by("serie")
    ]


def _serie_de_recibos(comprobante: ComprobanteVenta, elegida: int | None) -> SerieComprobante:
    """La serie de recibos con que la empresa del comprobante entrega el recibo del cobro."""
    empresa = comprobante.empresa
    tipo = (
        TipoComprobante.objects.sin_ambito()
        .filter(organizacion_id=empresa.organizacion_id, codigo="RI")
        .first()
    )
    if tipo is None or tipo.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida(
            "El recibo de cobranza no está disponible en esta organización: actualice los "
            "catálogos (tipos de comprobante)."
        )
    series = list(
        SerieComprobante.objects.sin_ambito().filter(
            empresa=empresa, tipo_comprobante=tipo, estado=EstadoRegistro.ACTIVO
        )
    )
    nombre = empresa.nombre_comercial or empresa.razon_social
    if not series:
        raise VentaInvalida(
            f"{nombre} no tiene una serie de recibos de cobranza (por ejemplo RI01). Créela en "
            "Mantenimiento → Series de comprobantes para poder cobrar cuotas."
        )
    if elegida is not None:
        serie = next((x for x in series if x.pk == elegida), None)
        if serie is None:
            raise VentaInvalida(f"La serie de recibos elegida no es válida para {nombre}.")
        return serie
    sucursal = comprobante.venta.sucursal
    propias = [x for x in series if sucursal is not None and x.sucursal_id == sucursal.pk]
    generales = [x for x in series if x.sucursal_id is None]
    for grupo in (propias, generales, series):
        if len(grupo) == 1:
            return grupo[0]
    raise VentaInvalida(f"{nombre} tiene varias series de recibos de cobranza: elija una.")


@transaction.atomic
def registrar_abonos(
    comprobante: ComprobanteVenta,
    *,
    abonos: list[CobroEntrada],
    cuota_ids: list[int] | None = None,
    usuario_nombre: str = "",
    serie_recibo: int | None = None,
) -> list[AbonoVenta]:
    """Cobra a un cliente una parte de lo que debe, con uno o varios métodos a la vez.

    Todo o nada: si un abono no es válido, no se registra ninguno. Entre todos no pueden pasar de
    lo que se debe. El efectivo puede llevar lo recibido para dar el vuelto.
    """
    if not abonos:
        raise VentaInvalida("Indique al menos un abono.")
    periodos.exigir_empresa(comprobante.empresa)
    actual = (
        ComprobanteVenta.objects.select_for_update().select_related("venta").get(pk=comprobante.pk)
    )
    if actual.estado != ComprobanteVenta.Estado.EMITIDO:
        raise VentaInvalida("El comprobante está anulado: no se puede cobrar.")
    venta = actual.venta
    if venta.forma_pago != FormaPago.CREDITO:
        raise VentaInvalida("La venta fue al contado: ya está cobrada.")
    hoy = timezone.localdate()
    if hoy < actual.fecha:
        raise VentaInvalida("El abono no puede ser anterior a la venta.")
    validos = _cobros_validos(abonos)
    cuentas = [resolver_cuenta(actual.empresa, v.medio_pago, None, venta.moneda) for v in validos]
    cuotas = _cuotas_bloqueadas(actual)
    pendiente = sum((c.monto - c.pagado for c in cuotas), CERO)
    if pendiente <= 0:
        raise VentaInvalida("El comprobante ya está cobrado por completo.")
    a_cobrar = sum((v.monto for v in validos), CERO)
    if a_cobrar > pendiente:
        raise VentaInvalida(f"Los abonos suman más de lo que se debe ({pendiente}).")

    serie_obj = _serie_de_recibos(actual, serie_recibo)
    serie, numero = siguiente_numero(actual.empresa, serie_obj.pk)
    recibo = ReciboCobranza.objects.create(
        empresa=actual.empresa,
        comprobante=actual,
        tipo_comprobante=serie_obj.tipo_comprobante,
        serie_comprobante=serie_obj,
        serie=serie,
        numero=numero,
        fecha=hoy,
        cajero_nombre=(usuario_nombre or "")[:150],
    )
    creados = []
    for validado, cuenta in zip(validos, cuentas, strict=True):
        aplicado = repartir(cuotas, validado.monto, cuota_ids)
        nuevo = AbonoVenta.objects.create(
            empresa=actual.empresa,
            comprobante=actual,
            recibo=recibo,
            medio_pago=validado.medio_pago,
            cuenta=cuenta,
            fecha=hoy,
            monto=validado.monto,
            referencia=validado.referencia,
            recibido=validado.recibido,
            vuelto=cobros.calcular_vuelto(validado.monto, validado.recibido),
        )
        for cuota, parte in aplicado:
            cuota.pagado += parte
            cuota.save(update_fields=["pagado"])
        AplicacionAbono.objects.bulk_create(
            [
                AplicacionAbono(empresa=actual.empresa, abono=nuevo, cuota=c, monto=m)
                for c, m in aplicado
            ]
        )
        caja.registrar_abono_de_venta(
            empresa=actual.empresa,
            cuenta=cuenta,
            monto=nuevo.monto,
            fecha=hoy,
            referencia=validado.referencia or actual.numero_completo,
            glosa=(
                f"Abono a la cuota {', '.join(str(c.numero) for c, _ in aplicado)} · "
                f"Venta {venta.numero:06d} · {actual.numero_completo} · {venta.cliente_nombre}"
            ),
            abono_id=nuevo.pk,
            medio_pago=nuevo.medio_pago,
        )
        pendiente -= validado.monto
        registrar(
            "ventas.abono_registrado",
            recurso_tipo="comprobante_venta",
            recurso_id=actual.pk,
            empresa_id=actual.empresa_id,
            resumen=f"Abono de {validado.monto} a {actual.numero_completo}",
            detalle={
                "abono": nuevo.pk,
                "monto": validado.monto,
                "cuenta": cuenta.pk,
                "medio_pago": validado.medio_pago.pk,
                "cuotas": [c.numero for c, _ in aplicado],
                "saldo": pendiente,
            },
        )
        creados.append(nuevo)
    return creados


def _revertir(abono: AbonoVenta, cuotas: dict[int, CuotaVenta], motivo: str) -> None:
    for aplicacion in AplicacionAbono.objects.filter(abono=abono):
        cuota = cuotas[aplicacion.cuota_id]
        cuota.pagado -= aplicacion.monto
        cuota.save(update_fields=["pagado"])
    caja.anular_por_origen(Origen.ABONO_VENTA, abono.pk, motivo=motivo)
    abono.anulado = True
    abono.anulado_en = timezone.now()
    abono.motivo_anulacion = motivo[:250]
    abono.save(update_fields=["anulado", "anulado_en", "motivo_anulacion"])


@transaction.atomic
def anular_abono(abono: AbonoVenta, *, motivo: str) -> AbonoVenta:
    """Revierte un abono: el dinero sale de la caja y cada cuota recupera su deuda."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise MotivoObligatorio()
    periodos.exigir_empresa(abono.empresa)
    comprobante = ComprobanteVenta.objects.select_for_update().get(pk=abono.comprobante_id)
    actual = AbonoVenta.objects.select_for_update().get(pk=abono.pk)
    if actual.anulado:
        raise DocumentoYaAnulado()
    if comprobante.estado != ComprobanteVenta.Estado.EMITIDO:
        raise VentaNoAnulable(
            "El comprobante está anulado: sus abonos ya quedaron anulados con él."
        )
    cuotas = {c.pk: c for c in _cuotas_bloqueadas(comprobante)}
    _revertir(actual, cuotas, f"Abono anulado: {motivo}")
    registrar(
        "ventas.abono_anulado",
        recurso_tipo="comprobante_venta",
        recurso_id=comprobante.pk,
        empresa_id=comprobante.empresa_id,
        resumen=f"Abono de {actual.monto} a {comprobante.numero_completo} anulado",
        detalle={"abono": actual.pk, "monto": actual.monto, "motivo": motivo[:200]},
    )
    return actual


def revertir_abonos_de(comprobante: ComprobanteVenta, motivo: str) -> int:
    """Al anular un comprobante a crédito, lo que el cliente ya había abonado vuelve a su caja."""
    abonos = list(
        AbonoVenta.objects.select_for_update().filter(comprobante=comprobante, anulado=False)
    )
    if not abonos:
        return 0
    cuotas = {c.pk: c for c in _cuotas_bloqueadas(comprobante)}
    for abono in abonos:
        _revertir(abono, cuotas, motivo)
    return len(abonos)
