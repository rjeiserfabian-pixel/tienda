"""Reclamos de garantía: abrir, pasar por servicio técnico o proveedor, y resolver.

Reglas (acordadas con el dueño):

* Solo se reclama una garantía ACTIVA y todavía vigente; una garantía no tiene dos reclamos
  abiertos a la vez.
* Si se cambia por otra unidad, la garantía NUEVA conserva lo que le quedaba a la anterior (vence el
  mismo día): el cambio no regala ni reinicia el plazo.
* El cambio saca la unidad nueva del almacén al costo (como pérdida por garantía) y deja la
  unidad defectuosa fuera del stock, en manos de la tienda: si el proveedor la repone o la acredita,
  eso se registra aparte (compra o devolución al proveedor).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto
from apps.inventario.models import OrigenMovimiento, TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import Almacen, Correlativo, EstadoRegistro, Proveedor
from apps.servicio_tecnico.models import OrdenServicio

from .exceptions import ReclamoInvalido, ReclamoNoPermitido
from .models import (
    ABIERTOS,
    EstadoGarantia,
    EstadoReclamo,
    Garantia,
    ReclamoGarantia,
    Resolucion,
)
from .servicios import _normalizar

DESCRIPCION_MAXIMA = 1000
TEXTO_MAXIMO = 500


def _texto(valor, maximo: int, campo: str, *, obligatorio=True) -> str:
    limpio = " ".join(str(valor or "").split())
    if obligatorio and len(limpio) < 3:
        raise ReclamoInvalido(f"Escriba {campo}.")
    if len(limpio) > maximo:
        raise ReclamoInvalido(f"{campo[0].upper()}{campo[1:]} admite hasta {maximo} caracteres.")
    return limpio


def _siguiente_numero(empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"garantias:reclamo:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _usuario_id():
    contexto = obtener_contexto()
    return contexto.usuario_id if contexto is not None else None


def _bloquear(reclamo_id: int) -> ReclamoGarantia:
    try:
        return (
            ReclamoGarantia.objects.select_for_update(of=("self",))
            .select_related("garantia", "empresa")
            .get(pk=reclamo_id)
        )
    except ReclamoGarantia.DoesNotExist:
        raise ReclamoInvalido("El reclamo no existe.") from None


def _exigir_abierto(reclamo: ReclamoGarantia) -> None:
    if reclamo.estado not in ABIERTOS:
        raise ReclamoNoPermitido(f"El reclamo {reclamo.numero_completo} ya está cerrado.")


@transaction.atomic
def abrir(*, garantia_id: int, descripcion: str, cantidad=None, hoy: date | None = None):
    """Abre el reclamo de una garantía vigente."""
    hoy = hoy or timezone.localdate()
    try:
        garantia = (
            Garantia.objects.select_for_update(of=("self",))
            .select_related("empresa", "producto")
            .get(pk=garantia_id)
        )
    except Garantia.DoesNotExist:
        raise ReclamoInvalido("La garantía no existe.") from None
    if garantia.estado != EstadoGarantia.ACTIVA:
        raise ReclamoInvalido(
            f"Esta garantía está {garantia.get_estado_display().lower()}: no se puede reclamar."
        )
    if garantia.vence_el < hoy:
        raise ReclamoInvalido(f"La garantía venció el {garantia.vence_el:%d/%m/%Y}.")
    if garantia.reclamos.filter(estado__in=ABIERTOS).exists():
        raise ReclamoNoPermitido("Esta garantía ya tiene un reclamo abierto.")
    texto = _texto(descripcion, DESCRIPCION_MAXIMA, "qué falla tiene el producto")

    if garantia.numero_serie:
        cantidad = Decimal("1")
    else:
        try:
            cantidad = Decimal(str(cantidad if cantidad not in (None, "") else 1))
        except ArithmeticError:
            raise ReclamoInvalido("La cantidad no es válida.") from None
        if cantidad <= 0 or cantidad > garantia.cantidad:
            raise ReclamoInvalido(
                f"La cantidad debe estar entre 1 y {garantia.cantidad.normalize():f}."
            )
        if cantidad != cantidad.to_integral_value():
            raise ReclamoInvalido("La cantidad debe ser un número entero.")

    reclamo = ReclamoGarantia.objects.create(
        empresa=garantia.empresa,
        garantia=garantia,
        numero=_siguiente_numero(garantia.empresa),
        fecha=hoy,
        cantidad=cantidad,
        descripcion=texto,
    )
    registrar(
        "garantias.reclamo_abierto",
        recurso_tipo="reclamo_garantia",
        recurso_id=reclamo.pk,
        empresa_id=garantia.empresa_id,
        resumen=(
            f"{reclamo.numero_completo}: {garantia.producto.nombre} {garantia.numero_serie}"
        ).strip(),
    )
    return reclamo


@transaction.atomic
def vincular_servicio(reclamo_id: int, orden_id: int) -> ReclamoGarantia:
    """Liga el reclamo a una orden de Servicio Técnico de la misma empresa y del mismo cliente."""
    reclamo = _bloquear(reclamo_id)
    _exigir_abierto(reclamo)
    try:
        orden = OrdenServicio.objects.get(pk=orden_id)
    except OrdenServicio.DoesNotExist:
        raise ReclamoInvalido("La orden de servicio no existe.") from None
    if orden.empresa_id != reclamo.empresa_id:
        raise ReclamoInvalido("La orden es de otra empresa.")
    cliente_id = reclamo.garantia.cliente_id
    if cliente_id is not None and orden.cliente_id != cliente_id:
        raise ReclamoInvalido("La orden es de otro cliente.")
    reclamo.orden_servicio = orden
    if reclamo.estado == EstadoReclamo.ABIERTO:
        reclamo.estado = EstadoReclamo.EN_SERVICIO
    reclamo.save(update_fields=["orden_servicio", "estado", "actualizado_en"])
    registrar(
        "garantias.reclamo_servicio",
        recurso_tipo="reclamo_garantia",
        recurso_id=reclamo.pk,
        empresa_id=reclamo.empresa_id,
        resumen=f"{reclamo.numero_completo}: ligado a la orden {orden.codigo}",
    )
    return reclamo


@transaction.atomic
def enviar_a_proveedor(
    reclamo_id: int, *, proveedor_id: int, rma_numero: str = "", fecha: date | None = None
) -> ReclamoGarantia:
    """Anota que la unidad se envió al proveedor para que la repare o la reponga."""
    reclamo = _bloquear(reclamo_id)
    _exigir_abierto(reclamo)
    proveedor = Proveedor.objects.filter(
        pk=proveedor_id, organizacion_id=reclamo.empresa.organizacion_id
    ).first()
    if proveedor is None or proveedor.estado != EstadoRegistro.ACTIVO:
        raise ReclamoInvalido("Elija un proveedor activo.")
    fecha = fecha or timezone.localdate()
    if fecha < reclamo.fecha:
        raise ReclamoInvalido("No puede ser anterior al reclamo.")
    reclamo.proveedor = proveedor
    reclamo.rma_numero = _texto(rma_numero, 40, "el número de RMA", obligatorio=False)
    reclamo.enviado_proveedor_el = fecha
    reclamo.estado = EstadoReclamo.EN_PROVEEDOR
    reclamo.save(
        update_fields=[
            "proveedor",
            "rma_numero",
            "enviado_proveedor_el",
            "estado",
            "actualizado_en",
        ]
    )
    registrar(
        "garantias.reclamo_proveedor",
        recurso_tipo="reclamo_garantia",
        recurso_id=reclamo.pk,
        empresa_id=reclamo.empresa_id,
        resumen=f"{reclamo.numero_completo}: enviado a {proveedor.nombre}",
    )
    return reclamo


@transaction.atomic
def respuesta_del_proveedor(
    reclamo_id: int, *, texto: str, fecha: date | None = None
) -> ReclamoGarantia:
    """Anota lo que respondió el proveedor (repuso, acreditó, rechazó…). No cierra el reclamo."""
    reclamo = _bloquear(reclamo_id)
    _exigir_abierto(reclamo)
    if reclamo.proveedor_id is None:
        raise ReclamoNoPermitido("Primero envíe el reclamo al proveedor.")
    fecha = fecha or timezone.localdate()
    if reclamo.enviado_proveedor_el and fecha < reclamo.enviado_proveedor_el:
        raise ReclamoInvalido("No puede ser anterior al envío al proveedor.")
    reclamo.respuesta_proveedor = _texto(texto, TEXTO_MAXIMO, "la respuesta del proveedor")
    reclamo.respondido_proveedor_el = fecha
    reclamo.save(update_fields=["respuesta_proveedor", "respondido_proveedor_el", "actualizado_en"])
    return reclamo


@dataclass(frozen=True, slots=True)
class Cambio:
    """La unidad con que se reemplaza: de qué almacén sale y, si lleva serie, cuál es."""

    almacen_id: int
    series: tuple[str, ...] = ()


def _cambiar(reclamo: ReclamoGarantia, cambio: Cambio, hoy: date) -> Garantia:
    """Saca la unidad nueva del almacén y crea su garantía con el plazo que le quedaba."""
    original = Garantia.objects.select_for_update(of=("self",)).get(pk=reclamo.garantia_id)
    producto = original.producto
    almacen = Almacen.objects.filter(
        pk=cambio.almacen_id, empresa_id=reclamo.empresa_id, estado=EstadoRegistro.ACTIVO
    ).first()
    if almacen is None:
        raise ReclamoInvalido("Elija un almacén activo de la empresa.")
    series = tuple(_normalizar(s) for s in cambio.series if str(s).strip())
    if producto.lleva_serie:
        if len(series) != int(reclamo.cantidad) or len(set(series)) != len(series):
            raise ReclamoInvalido("Indique la serie o el IMEI de la unidad que se entrega.")
        if original.numero_serie in series:
            raise ReclamoInvalido("La unidad nueva no puede ser la misma que se reclama.")
    elif series:
        raise ReclamoInvalido(f"{producto.nombre} no lleva series.")

    movimiento = registrar_movimiento(
        empresa=reclamo.empresa,
        almacen=almacen,
        tipo=TipoMovimiento.SALIDA,
        origen=OrigenMovimiento.MERMA,
        fecha=hoy,
        lineas=[LineaNueva(producto=producto, cantidad=reclamo.cantidad, series=series)],
        cliente=original.cliente,
        observacion=f"Cambio por garantía {reclamo.numero_completo}",
        referencia_tipo="reclamo_garantia",
        referencia_id=reclamo.pk,
    )
    reclamo.movimiento = movimiento

    # La garantía vieja pasa a «reemplazada» (o pierde las unidades cambiadas) y nace la nueva.
    if original.numero_serie or reclamo.cantidad >= original.cantidad:
        original.estado = EstadoGarantia.REEMPLAZADA
        original.save(update_fields=["estado", "actualizado_en"])
    else:
        original.cantidad -= reclamo.cantidad
        original.save(update_fields=["cantidad", "actualizado_en"])
    return Garantia.objects.create(
        empresa=original.empresa,
        producto=producto,
        linea_venta=original.linea_venta,
        comprobante=original.comprobante,
        cliente=original.cliente,
        cliente_nombre=original.cliente_nombre,
        cliente_documento=original.cliente_documento,
        numero_serie=series[0] if series else "",
        cantidad=reclamo.cantidad,
        fecha_inicio=hoy,
        meses=original.meses,
        vence_el=max(original.vence_el, hoy),  # conserva lo que quedaba, no lo reinicia
        reemplaza_a=original,
    )


@transaction.atomic
def resolver(
    reclamo_id: int,
    *,
    resolucion: str,
    detalle: str = "",
    cambio: Cambio | None = None,
    hoy: date | None = None,
) -> ReclamoGarantia:
    """Cierra el reclamo: reparado, cambiado, devolución con nota de crédito o rechazado."""
    if resolucion not in Resolucion.values:
        raise ReclamoInvalido("Elija cómo se resolvió el reclamo.")
    reclamo = _bloquear(reclamo_id)
    _exigir_abierto(reclamo)
    hoy = hoy or timezone.localdate()
    reclamo.resolucion_detalle = _texto(
        detalle, TEXTO_MAXIMO, "el detalle de la resolución", obligatorio=resolucion != "REPARADO"
    )
    if resolucion == Resolucion.CAMBIADO:
        if cambio is None:
            raise ReclamoInvalido("Indique de qué almacén sale la unidad de reemplazo.")
        reclamo.garantia_nueva = _cambiar(reclamo, cambio, hoy)
    elif cambio is not None:
        raise ReclamoInvalido("Solo el cambio por otra unidad lleva datos de reemplazo.")
    reclamo.resolucion = resolucion
    reclamo.estado = (
        EstadoReclamo.RECHAZADO if resolucion == Resolucion.RECHAZADO else EstadoReclamo.RESUELTO
    )
    reclamo.resuelto_el = hoy
    reclamo.resuelto_por_id = _usuario_id()
    reclamo.save()
    registrar(
        "garantias.reclamo_resuelto",
        recurso_tipo="reclamo_garantia",
        recurso_id=reclamo.pk,
        empresa_id=reclamo.empresa_id,
        resumen=f"{reclamo.numero_completo}: {reclamo.get_resolucion_display()}",
        detalle={"resolucion": resolucion, "garantia_nueva": reclamo.garantia_nueva_id},
    )
    return reclamo
