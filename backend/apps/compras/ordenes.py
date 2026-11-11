"""Órdenes de compra: el pedido al proveedor antes de comprar.

Una orden nace en BORRADOR y solo ahí se edita. Al emitirla puede necesitar aprobación según su
monto (cada empresa fija desde cuánto). Una vez EMITIDA, la mercadería se recibe por partes y la
orden pasa sola a PARCIAL y a RECIBIDA. Se puede CERRAR una orden recibida en parte (el proveedor ya
no entregará el resto) o ANULAR una que todavía no recibió nada.

Los importes salen del mismo cálculo que una compra (``calculo.calcular_compra``): lo que se ve
en la orden es lo que luego se facturará, salvo que el proveedor cambie el precio.

Todas las transiciones bloquean la orden (``select_for_update``) y dejan huella en la auditoría.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto
from apps.inventario import periodos
from apps.inventario.costeo import a_dos
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import resolver_tipo_cambio
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    Correlativo,
    EstadoRegistro,
    PresentacionProducto,
    Producto,
    Proveedor,
)
from apps.organizacion.models import Empresa

from . import calculo
from .exceptions import CompraInvalida, OrdenCompraInvalida, OrdenCompraNoModificable
from .models import FormaPago, LineaOrdenCompra, Moneda, OrdenCompra
from .recepcion import (  # noqa: F401  (se reexportan: son parte de la API de órdenes)
    EN_RECEPCION,
    pendiente_de_recibir,
    recalcular_estado,
    tiene_recepciones,
    tolerancia_de_recepcion,
)
from .recepcion import auditar_orden as _auditar
from .recepcion import configuracion_de as _configuracion
from .servicios import MAX_LINEAS, MAX_TOTAL, LineaEntrada, _fecha, _preparar_linea, _texto

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
MAX_PLAZO_DIAS = 365
Estado = OrdenCompra.Estado


# ---------------------------------------------------------------------------
# Lo que pide quien crea o edita la orden
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LineaOrden:
    producto: Producto
    cantidad: Decimal  # en la unidad pedida (la presentación si se indica)
    precio_unitario: Decimal  # por unidad pedida, como lo pactó el proveedor
    presentacion: PresentacionProducto | None = None
    afectacion: AfectacionIGV | None = None  # None = la que propone el sistema


@dataclass(slots=True)
class OrdenPreparada:
    """Orden validada y calculada, lista para guardarse."""

    empresa: Empresa
    proveedor: Proveedor
    almacen: Almacen
    fecha_emision: date
    fecha_entrega: date | None
    observacion: str
    moneda: str
    tipo_cambio: Decimal
    precios_incluyen_igv: bool
    forma_pago: str
    plazo_dias: int
    lineas: list[LineaOrden]
    afectaciones: list[tuple[AfectacionIGV, Decimal]]
    cantidades_base: list[Decimal]
    resultado: calculo.ResultadoCompra
    total_soles: Decimal


# ---------------------------------------------------------------------------
# Configuración de la empresa
# ---------------------------------------------------------------------------


def monto_de_aprobacion(empresa: Empresa) -> Decimal | None:
    """Desde qué monto en soles una orden necesita aprobación (None = nunca)."""
    config = _configuracion(empresa)
    return config.orden_compra_monto_aprobacion if config else None


def requiere_aprobacion(orden: OrdenCompra) -> bool:
    """Si el monto de la orden (en soles) pasa del que fijó la empresa."""
    umbral = monto_de_aprobacion(orden.empresa)
    return umbral is not None and orden.total_soles > umbral


# ---------------------------------------------------------------------------
# Validación y cálculo (sin escribir)
# ---------------------------------------------------------------------------
def preparar_orden(
    *,
    empresa: Empresa,
    proveedor: Proveedor,
    almacen: Almacen,
    fecha_emision: date,
    lineas: list[LineaOrden],
    forma_pago: str = FormaPago.CONTADO,
    plazo_dias: int = 0,
    fecha_entrega: date | None = None,
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    precios_incluyen_igv: bool = False,
    observacion: str = "",
) -> OrdenPreparada:
    """Valida la orden y calcula sus importes. No escribe en la base de datos."""
    periodos.exigir_empresa(empresa)
    if proveedor.organizacion_id != empresa.organizacion_id:
        raise OrdenCompraInvalida("El proveedor no pertenece a la organización.")
    if proveedor.estado != EstadoRegistro.ACTIVO:
        raise OrdenCompraInvalida("El proveedor está inactivo.")
    if almacen.empresa_id != empresa.pk:
        raise OrdenCompraInvalida("El almacén no pertenece a la empresa.")
    if almacen.estado != EstadoRegistro.ACTIVO:
        raise OrdenCompraInvalida("El almacén está inactivo.")
    if moneda not in Moneda.values:
        raise OrdenCompraInvalida("La moneda no es válida.")
    if forma_pago not in FormaPago.values:
        raise OrdenCompraInvalida("La forma de pago no es válida.")
    if not isinstance(fecha_emision, date) or isinstance(fecha_emision, datetime):
        raise OrdenCompraInvalida("La fecha de emisión no es válida.")
    if fecha_emision > timezone.localdate():
        raise OrdenCompraInvalida("La fecha de emisión no puede ser futura.")
    if fecha_entrega is not None:
        _fecha(fecha_entrega, "Fecha de entrega")
        if fecha_entrega < fecha_emision:
            raise OrdenCompraInvalida("La entrega no puede ser anterior a la emisión.")
    if not isinstance(plazo_dias, int) or isinstance(plazo_dias, bool):
        raise OrdenCompraInvalida("El plazo de crédito debe ser un número de días.")
    if forma_pago == FormaPago.CONTADO and plazo_dias != 0:
        raise OrdenCompraInvalida("Una orden al contado no lleva plazo de crédito.")
    if forma_pago == FormaPago.CREDITO and not 1 <= plazo_dias <= MAX_PLAZO_DIAS:
        raise OrdenCompraInvalida(f"El plazo de crédito es de 1 a {MAX_PLAZO_DIAS} días.")
    if not lineas:
        raise OrdenCompraInvalida("Agregue al menos un producto.")
    if len(lineas) > MAX_LINEAS:
        raise OrdenCompraInvalida(f"Una orden admite hasta {MAX_LINEAS} productos.")
    vistos: set[tuple[int, int | None]] = set()
    for ln in lineas:
        clave = (ln.producto.pk, ln.presentacion.pk if ln.presentacion else None)
        if clave in vistos:
            raise OrdenCompraInvalida(
                f"{ln.producto.nombre} está repetido: súmalo en una sola línea."
            )
        vistos.add(clave)

    cambio = resolver_tipo_cambio(
        empresa, moneda, tipo_cambio, TipoMovimiento.ENTRADA, fecha_emision
    )
    preparadas = []
    for ln in lineas:
        try:
            preparadas.append(
                _preparar_linea(
                    empresa,
                    proveedor,
                    fecha_emision,
                    LineaEntrada(
                        producto=ln.producto,
                        cantidad=ln.cantidad,
                        precio_unitario=ln.precio_unitario,
                        presentacion=ln.presentacion,
                        afectacion=ln.afectacion,
                    ),
                )
            )
        except CompraInvalida as error:  # los errores de línea de Compras se muestran tal cual
            raise OrdenCompraInvalida(error.mensaje) from None
    resultado = calculo.calcular_compra(
        [p[0] for p in preparadas],
        precios_incluyen_igv=precios_incluyen_igv,
        igv_al_costo=False,  # una orden no valoriza inventario: solo es el pedido
        tipo_cambio=cambio,
    )
    if resultado.total > MAX_TOTAL:
        raise OrdenCompraInvalida("El total de la orden es demasiado grande.")
    return OrdenPreparada(
        empresa=empresa,
        proveedor=proveedor,
        almacen=almacen,
        fecha_emision=fecha_emision,
        fecha_entrega=fecha_entrega,
        observacion=_texto(observacion, 250),
        moneda=moneda,
        tipo_cambio=cambio,
        precios_incluyen_igv=precios_incluyen_igv,
        forma_pago=forma_pago,
        plazo_dias=plazo_dias,
        lineas=list(lineas),
        afectaciones=[(p[1], p[2]) for p in preparadas],
        cantidades_base=[p[3] for p in preparadas],
        resultado=resultado,
        total_soles=a_dos(resultado.total * cambio),
    )


# ---------------------------------------------------------------------------
# Crear y editar
# ---------------------------------------------------------------------------
def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"compras:orden:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _campos_de(p: OrdenPreparada) -> dict:
    r = p.resultado
    return {
        "proveedor": p.proveedor,
        "almacen": p.almacen,
        "fecha_emision": p.fecha_emision,
        "fecha_entrega": p.fecha_entrega,
        "observacion": p.observacion,
        "moneda": p.moneda,
        "tipo_cambio": p.tipo_cambio,
        "precios_incluyen_igv": p.precios_incluyen_igv,
        "forma_pago": p.forma_pago,
        "plazo_dias": p.plazo_dias,
        "op_gravada": r.op_gravada,
        "igv": r.igv,
        "op_ivap": r.op_ivap,
        "ivap": r.ivap,
        "op_exonerada": r.op_exonerada,
        "op_inafecta": r.op_inafecta,
        "total": r.total,
        "total_soles": p.total_soles,
    }


def _crear_lineas(orden: OrdenCompra, p: OrdenPreparada) -> None:
    LineaOrdenCompra.objects.bulk_create(
        [
            LineaOrdenCompra(
                empresa=orden.empresa,
                orden=orden,
                orden_linea=posicion,
                producto=ln.producto,
                presentacion=ln.presentacion,
                unidad=ln.presentacion.unidad.nombre
                if ln.presentacion
                else ln.producto.unidad.nombre,
                factor=ln.presentacion.factor if ln.presentacion else Decimal("1"),
                cantidad=ln.cantidad,
                cantidad_base=base,
                afectacion=afectacion,
                afectacion_codigo=afectacion.codigo,
                tasa=tasa,
                precio_unitario=ln.precio_unitario,
                valor_venta=calculada.valor_venta,
                impuesto=calculada.impuesto,
                total=calculada.total,
            )
            for posicion, (ln, base, (afectacion, tasa), calculada) in enumerate(
                zip(p.lineas, p.cantidades_base, p.afectaciones, p.resultado.lineas, strict=True),
                start=1,
            )
        ]
    )


@transaction.atomic
def crear_orden(**datos) -> OrdenCompra:
    """Crea la orden en borrador. Recibe los mismos argumentos que ``preparar_orden``."""
    p = preparar_orden(**datos)
    orden = OrdenCompra.objects.create(
        empresa=p.empresa,
        numero=_siguiente_numero(p.empresa),
        estado=Estado.BORRADOR,
        **_campos_de(p),
    )
    _crear_lineas(orden, p)
    registrar(
        "compras.orden_creada",
        recurso_tipo="orden_compra",
        recurso_id=orden.pk,
        empresa_id=orden.empresa_id,
        resumen=f"Orden de compra {orden.codigo} creada",
        detalle={
            "proveedor": p.proveedor.pk,
            "total": orden.total,
            "moneda": orden.moneda,
            "lineas": len(p.lineas),
        },
    )
    logger.info("orden_compra_creada", extra={"empresa_id": orden.empresa_id, "orden_id": orden.pk})
    return orden


def _bloquear(orden: OrdenCompra) -> OrdenCompra:
    periodos.exigir_empresa(orden.empresa)
    return OrdenCompra.objects.select_for_update().get(pk=orden.pk)


def _exigir_estado(orden: OrdenCompra, permitidos: tuple[str, ...], accion: str) -> None:
    if orden.estado not in permitidos:
        raise OrdenCompraNoModificable(
            f"No se puede {accion} una orden en estado «{orden.get_estado_display()}»."
        )


@transaction.atomic
def editar_orden(orden: OrdenCompra, **datos) -> OrdenCompra:
    """Cambia una orden en borrador (cabecera y líneas). Después de emitida ya no se edita."""
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.BORRADOR,), "editar")
    p = preparar_orden(empresa=actual.empresa, **datos)
    for campo, valor in _campos_de(p).items():
        setattr(actual, campo, valor)
    actual.save()
    LineaOrdenCompra.objects.filter(orden=actual).delete()  # borrado lógico: queda el rastro
    _crear_lineas(actual, p)
    registrar(
        "compras.orden_editada",
        recurso_tipo="orden_compra",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"Orden de compra {actual.codigo} editada",
        detalle={"total": actual.total, "lineas": len(p.lineas)},
    )
    return actual


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------
def _usuario_id():
    contexto = obtener_contexto()
    return contexto.usuario_id if contexto else None


def _motivo(texto: str, que: str) -> str:
    motivo = _texto(texto, 250)
    if len(motivo) < 3:
        raise OrdenCompraInvalida(f"Indique el motivo {que}.")
    return motivo


@transaction.atomic
def emitir_orden(orden: OrdenCompra, *, puede_aprobar: bool) -> OrdenCompra:
    """Emite la orden; si pide aprobación y quien emite no puede darla, queda por aprobar."""
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.BORRADOR,), "emitir")
    if actual.total <= 0:
        raise OrdenCompraInvalida("Una orden con total cero no se puede emitir.")
    if not LineaOrdenCompra.objects.filter(orden=actual).exists():
        raise OrdenCompraInvalida("La orden no tiene productos.")
    pide = requiere_aprobacion(actual)
    ahora = timezone.now()
    if pide and not puede_aprobar:
        actual.estado = Estado.PENDIENTE
        actual.save(update_fields=["estado"])
        _auditar("compras.orden_por_aprobar", actual, "enviada a aprobación")
        return actual
    actual.estado = Estado.EMITIDA
    actual.emitida_en = ahora
    campos = ["estado", "emitida_en"]
    if pide:  # la emite alguien que puede aprobarla: queda aprobada por esa misma persona
        actual.aprobada_por_id, actual.aprobada_en = _usuario_id(), ahora
        campos += ["aprobada_por_id", "aprobada_en"]
    actual.save(update_fields=campos)
    _auditar("compras.orden_emitida", actual, "emitida", requirio_aprobacion=pide)
    return actual


@transaction.atomic
def aprobar_orden(orden: OrdenCompra) -> OrdenCompra:
    """Aprueba una orden que estaba por aprobar: queda emitida."""
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.PENDIENTE,), "aprobar")
    ahora = timezone.now()
    actual.estado, actual.emitida_en = Estado.EMITIDA, ahora
    actual.aprobada_por_id, actual.aprobada_en = _usuario_id(), ahora
    actual.motivo_rechazo = ""
    actual.save(
        update_fields=["estado", "emitida_en", "aprobada_por_id", "aprobada_en", "motivo_rechazo"]
    )
    _auditar("compras.orden_aprobada", actual, "aprobada")
    return actual


@transaction.atomic
def rechazar_orden(orden: OrdenCompra, *, motivo: str) -> OrdenCompra:
    """No aprueba la orden: vuelve a borrador con el motivo, para corregirla."""
    motivo = _motivo(motivo, "del rechazo")
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.PENDIENTE,), "rechazar")
    actual.estado, actual.motivo_rechazo = Estado.BORRADOR, motivo
    actual.save(update_fields=["estado", "motivo_rechazo"])
    _auditar("compras.orden_rechazada", actual, "rechazada", motivo=motivo[:200])
    return actual


@transaction.atomic
def reabrir_orden(orden: OrdenCompra) -> OrdenCompra:
    """Devuelve a borrador una orden por aprobar o emitida que todavía no recibió nada."""
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.PENDIENTE, Estado.EMITIDA), "reabrir")
    if tiene_recepciones(actual):
        raise OrdenCompraNoModificable("La orden ya recibió mercadería: no se puede reabrir.")
    actual.estado = Estado.BORRADOR
    actual.emitida_en = actual.aprobada_en = actual.aprobada_por_id = None
    actual.save(update_fields=["estado", "emitida_en", "aprobada_en", "aprobada_por_id"])
    _auditar("compras.orden_reabierta", actual, "vuelta a borrador")
    return actual


@transaction.atomic
def anular_orden(orden: OrdenCompra, *, motivo: str) -> OrdenCompra:
    """Anula una orden que no recibió nada. El motivo es obligatorio."""
    motivo = _motivo(motivo, "de la anulación")
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.BORRADOR, Estado.PENDIENTE, Estado.EMITIDA), "anular")
    if tiene_recepciones(actual):
        raise OrdenCompraNoModificable(
            "La orden ya recibió mercadería: ciérrala en vez de anularla."
        )
    actual.estado, actual.motivo_anulacion = Estado.ANULADA, motivo
    actual.anulada_por_id, actual.anulada_en = _usuario_id(), timezone.now()
    actual.save(update_fields=["estado", "motivo_anulacion", "anulada_por_id", "anulada_en"])
    _auditar("compras.orden_anulada", actual, "anulada", motivo=motivo[:200])
    return actual


@transaction.atomic
def cerrar_orden(orden: OrdenCompra, *, motivo: str) -> OrdenCompra:
    """Da por terminada una orden recibida en parte: el proveedor no entregará el resto."""
    motivo = _motivo(motivo, "del cierre")
    actual = _bloquear(orden)
    _exigir_estado(actual, (Estado.PARCIAL,), "cerrar")
    actual.estado, actual.motivo_cierre = Estado.CERRADA, motivo
    actual.cerrada_por_id, actual.cerrada_en = _usuario_id(), timezone.now()
    actual.save(update_fields=["estado", "motivo_cierre", "cerrada_por_id", "cerrada_en"])
    _auditar("compras.orden_cerrada", actual, "cerrada con faltante", motivo=motivo[:200])
    return actual
