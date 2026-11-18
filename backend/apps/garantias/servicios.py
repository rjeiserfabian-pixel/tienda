"""Alta y anulación automática de garantías según lo que se vende y lo que se devuelve."""

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar

from .models import EstadoGarantia, Garantia


def sumar_meses(desde: date, meses: int) -> date:
    """``desde`` más ``meses`` sin pasarse del fin de mes (31 de enero + 1 mes = 28 de febrero)."""
    return desde + relativedelta(months=meses)


def _normalizar(serie: str) -> str:
    return " ".join(str(serie).split()).upper()


@transaction.atomic
def crear_de_comprobante(comprobante) -> list[Garantia]:
    """Crea la garantía de cada producto del comprobante que tenga meses de garantía.

    Idempotente: si ya existe la garantía de esa línea (y serie) no la duplica.
    """
    from apps.ventas.models import LineaVenta

    venta = comprobante.venta
    creadas: list[Garantia] = []
    lineas = LineaVenta.objects.filter(comprobante=comprobante).select_related("producto")
    for linea in lineas:
        meses = linea.producto.garantia_meses or 0
        if meses <= 0 or linea.cantidad <= 0:
            continue
        series = [_normalizar(s) for s in linea.series]
        # Una por unidad si lleva serie; si no, una sola por la línea completa.
        unidades = [(s, Decimal("1")) for s in series] or [("", linea.cantidad)]
        for serie, cantidad in unidades:
            garantia, nueva = Garantia.objects.get_or_create(
                empresa=comprobante.empresa,
                linea_venta=linea,
                numero_serie=serie,
                reemplaza_a=None,
                defaults={
                    "producto": linea.producto,
                    "comprobante": comprobante,
                    "cliente": venta.cliente,
                    "cliente_nombre": venta.cliente_nombre,
                    "cliente_documento": venta.cliente_documento,
                    "cantidad": cantidad,
                    "fecha_inicio": comprobante.fecha,
                    "meses": meses,
                    "vence_el": sumar_meses(comprobante.fecha, meses),
                },
            )
            if nueva:
                creadas.append(garantia)
    return creadas


def _anular(garantias, motivo: str) -> int:
    ahora = timezone.now()
    cantidad = 0
    for g in garantias:
        g.estado = EstadoGarantia.ANULADA
        g.anulada_en = ahora
        g.motivo_anulacion = motivo[:250]
        g.save(update_fields=["estado", "anulada_en", "motivo_anulacion", "actualizado_en"])
        cantidad += 1
    return cantidad


@transaction.atomic
def cambiar_serie(linea_venta_id: int, anterior: str, nueva: str) -> int:
    """La unidad que realmente se entregó es OTRA que la del comprobante: la garantía la sigue.

    La usa la tienda cuando el almacén cambia la serie de un pedido ya pagado (el comprobante no
    se edita, pero el cliente tiene en la mano la unidad nueva). Devuelve cuántas garantías cambió.
    """
    anterior, nueva = _normalizar(anterior), _normalizar(nueva)
    if not anterior or not nueva or anterior == nueva:
        return 0
    garantias = list(
        Garantia.objects.sin_ambito()
        .select_for_update(of=("self",))
        .filter(
            linea_venta_id=linea_venta_id,
            numero_serie=anterior,
            estado=EstadoGarantia.ACTIVA,
            reemplaza_a=None,
        )
    )
    for g in garantias:
        g.numero_serie = nueva
        g.save(update_fields=["numero_serie", "actualizado_en"])
    if garantias:
        registrar(
            "garantias.serie_cambiada",
            recurso_tipo="garantia",
            recurso_id=garantias[0].pk,
            empresa_id=garantias[0].empresa_id,
            resumen=f"La garantía pasó de la serie {anterior} a {nueva}",
            detalle={"anterior": anterior, "nueva": nueva},
        )
    return len(garantias)


@transaction.atomic
def anular_de_comprobante(comprobante, motivo: str) -> int:
    """Se anuló el comprobante: todas sus garantías activas quedan anuladas."""
    activas = list(
        Garantia.objects.select_for_update().filter(
            comprobante=comprobante, estado=EstadoGarantia.ACTIVA
        )
    )
    total = _anular(activas, f"Anulación de {comprobante.numero_completo}: {motivo}")
    if total:
        registrar(
            "garantias.anuladas",
            recurso_tipo="comprobante_venta",
            recurso_id=comprobante.pk,
            empresa_id=comprobante.empresa_id,
            resumen=f"{total} garantía(s) anulada(s) por anular {comprobante.numero_completo}",
        )
    return total


@transaction.atomic
def reducir_por_devolucion(linea, cantidad: Decimal, series: tuple[str, ...], motivo: str) -> int:
    """Una nota de crédito devolvió ``cantidad`` de la línea (con sus series, si las lleva).

    Con series se anula la garantía de cada unidad devuelta; sin series se descuenta de la garantía
    de la línea y, si ya no queda nada, se anula.
    """
    activas = Garantia.objects.select_for_update().filter(
        linea_venta=linea, estado=EstadoGarantia.ACTIVA
    )
    if series:
        pedidas = {_normalizar(s) for s in series}
        return _anular([g for g in activas if g.numero_serie in pedidas], motivo)
    cambiadas = 0
    for g in activas.filter(numero_serie=""):
        resto = g.cantidad - cantidad
        if resto <= 0:
            cambiadas += _anular([g], motivo)
        else:
            g.cantidad = resto
            g.save(update_fields=["cantidad", "actualizado_en"])
            cambiadas += 1
    return cambiadas
