"""Series (números de serie o IMEI) por orden de antigüedad: primero en entrar, primero en salir.

Lo usan la tienda en línea y el punto de venta del local para proponer SIEMPRE la unidad más
antigua del almacén (así no se queda stock viejo). Es solo una propuesta: quien vende o prepara el
pedido puede elegir otra. Aquí no se cambia el costo del Kardex (sigue siendo el promedio).

Todas las consultas son EXPLÍCITAS por empresa y almacén (no dependen de la sesión), porque la
tienda pública las usa sin usuario del sistema.
"""

from collections import defaultdict
from collections.abc import Iterable

from django.db import transaction

from .exceptions import MovimientoInvalido
from .models import EstadoSerie, LineaMovimiento, SerieProducto

MAXIMO_SUGERIDAS = 500


def mas_antiguas(
    producto_id: int, empresa_id: int, almacen_id: int, cantidad: int, *, bloquear: bool = False
) -> list[SerieProducto]:
    """Las ``cantidad`` series EN STOCK más antiguas de ese producto en ese almacén.

    Antigüedad = fecha del movimiento que las ingresó; a igual fecha, la que se registró antes.
    Con ``bloquear`` se bloquean las filas (``select_for_update``): para asignarlas dentro de una
    transacción sin que dos ventas a la vez tomen la misma unidad. Devuelve menos de las pedidas
    si no hay suficientes; quien llama decide qué hacer.
    """
    cantidad = max(0, min(int(cantidad), MAXIMO_SUGERIDAS))
    if cantidad == 0:
        return []
    consulta = SerieProducto.objects.sin_ambito().filter(
        producto_id=producto_id,
        empresa_id=empresa_id,
        almacen_id=almacen_id,
        estado=EstadoSerie.EN_STOCK,
    )
    # El orden va antes del bloqueo; ``of=("self",)`` evita bloquear las tablas unidas.
    consulta = consulta.order_by("entrada__fecha", "entrada_id", "id")
    if bloquear:
        consulta = consulta.select_for_update(of=("self",))
    return list(consulta[:cantidad])


def en_stock_por_almacen(
    producto_ids: Iterable[int], almacen_ids: Iterable[int]
) -> dict[tuple[int, int], int]:
    """Cuántas series hay EN STOCK: ``{(almacén, producto): cantidad}``."""
    filas = (
        SerieProducto.objects.sin_ambito()
        .filter(
            producto_id__in=list(producto_ids),
            almacen_id__in=list(almacen_ids),
            estado=EstadoSerie.EN_STOCK,
        )
        .values_list("almacen_id", "producto_id")
    )
    cuenta: dict[tuple[int, int], int] = defaultdict(int)
    for almacen_id, producto_id in filas:
        cuenta[(almacen_id, producto_id)] += 1
    return cuenta


def _numero(texto: str) -> str:
    return " ".join(str(texto).split()).upper()


@transaction.atomic
def intercambiar_series_de_salida(
    *,
    producto_id: int,
    empresa_id: int,
    almacen_id: int,
    movimiento_id: int,
    anterior: str,
    nueva: str,
) -> tuple[SerieProducto, SerieProducto]:
    """La unidad que realmente salió es OTRA: ``nueva`` sale y ``anterior`` vuelve al stock.

    Corrige solo el inventario de series (qué unidad física quedó en el almacén). NO toca el
    comprobante emitido ni el movimiento del Kardex: la salida sigue siendo la misma línea, con el
    mismo costo; solo cambia la unidad con la que se asocia.

    ``anterior`` debe haber salido en ESE movimiento y ``nueva`` debe estar en stock en el mismo
    almacén y empresa. Devuelve (fila de la nueva, fila de la anterior) ya actualizadas.
    """
    anterior, nueva = _numero(anterior), _numero(nueva)
    if not anterior or not nueva or anterior == nueva:
        raise MovimientoInvalido("Indique una serie distinta de la actual.")
    filas = list(
        SerieProducto.objects.sin_ambito()
        .select_for_update(of=("self",))
        .filter(producto_id=producto_id, numero__in=(anterior, nueva))
        .order_by("id")
    )
    previa = next(
        (
            f
            for f in reversed(filas)
            if f.numero == anterior
            and f.estado == EstadoSerie.SALIDO
            and f.empresa_id == empresa_id
            and f.almacen_id == almacen_id
            and f.salida_id is not None
            and LineaMovimiento.objects.filter(pk=f.salida_id, movimiento_id=movimiento_id).exists()
        ),
        None,
    )
    if previa is None:
        raise MovimientoInvalido(f"La serie {anterior} no salió con esta venta.")
    elegida = next(
        (
            f
            for f in filas
            if f.numero == nueva
            and f.estado == EstadoSerie.EN_STOCK
            and f.empresa_id == empresa_id
            and f.almacen_id == almacen_id
        ),
        None,
    )
    if elegida is None:
        raise MovimientoInvalido(
            f"La serie {nueva} no está en el stock de este almacén. Revisa que esté bien escrita."
        )
    salida = previa.salida
    elegida.estado, elegida.salida = EstadoSerie.SALIDO, salida
    elegida.save(update_fields=["estado", "salida", "actualizado_en"])
    previa.estado, previa.salida = EstadoSerie.EN_STOCK, None
    previa.save(update_fields=["estado", "salida", "actualizado_en"])
    return elegida, previa
