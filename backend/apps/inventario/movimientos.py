"""Registro y anulación de movimientos de inventario: el corazón del Kardex.

Reglas que se cumplen aquí (y no en las vistas):

* Todo ocurre en UNA transacción: o se registra el movimiento completo, o no queda nada.
* Se bloquean el correlativo de la empresa y las filas de saldo, siempre en el mismo orden, para
  que dos operaciones simultáneas no se pisen ni se crucen (sin interbloqueos).
* No hay stock negativo, ni siquiera al insertar un movimiento con fecha atrasada: las líneas
  posteriores se recalculan en orden y, si alguna se quedara sin stock, se rechaza todo.
* El movimiento no se edita ni se borra. Anular crea un extorno (movimiento inverso, con fecha de
  hoy y al mismo valor del original) y marca el original como anulado, con su motivo.
* El costo del inventario va siempre en soles y sin IGV; el comprobante conserva su moneda.
"""

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.mantenimiento import tipo_cambio as servicio_tipo_cambio
from apps.mantenimiento.fiscal import tasa_vigente, validar_serie_numero
from apps.mantenimiento.models import (
    Almacen,
    Cliente,
    EstadoRegistro,
    Producto,
    Proveedor,
    TipoComprobante,
    TipoProducto,
)
from apps.organizacion.models import Empresa

from . import costeo, numeracion, periodos
from .catalogos import OTROS, SALDO_INICIAL, TIPOS_OPERACION
from .costeo import DOS, Saldo, a_dos, a_seis
from .exceptions import (
    AnulacionNoPermitida,
    ComprobanteDuplicado,
    MovimientoInvalido,
    ProductoNoInventariable,
    StockInsuficiente,
    TipoCambioNoDisponible,
)
from .models import (
    EstadoSerie,
    LineaMovimiento,
    Moneda,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)

logger = logging.getLogger(__name__)

MAX_LINEAS = 200
MAX_CANTIDAD = Decimal("99999999999.999")  # cabe en max_digits=14, decimal_places=3
MAX_IMPORTE = Decimal("99999999999999.99")  # cabe en max_digits=16, decimal_places=2
MAX_PRECIO = Decimal("9999999999.999999")  # cabe en max_digits=16, decimal_places=6
TRES = Decimal("0.001")
CUATRO = Decimal("0.0001")
SEIS = Decimal("0.000001")
CIEN = Decimal("100")
UNO = Decimal("1")

_SERIE = re.compile(r"[A-Z0-9\-]{1,10}")
_NUMERO_SERIE = re.compile(r"[A-Z0-9][A-Z0-9\-_./]{2,39}")
TOPE_OTROS_DATOS = 120  # largo máximo del dato adicional de una serie
_NUMERO = re.compile(r"[A-Z0-9\-]{1,20}")

# Qué tipo (entrada o salida) admite cada origen. El extorno solo lo crea el sistema.
_TIPOS_POR_ORIGEN = {
    OrigenMovimiento.COMPRA: {TipoMovimiento.ENTRADA},
    OrigenMovimiento.VENTA: {TipoMovimiento.SALIDA},
    OrigenMovimiento.DEVOLUCION_CLIENTE: {TipoMovimiento.ENTRADA},
    OrigenMovimiento.DEVOLUCION_PROVEEDOR: {TipoMovimiento.SALIDA},
    OrigenMovimiento.SALDO_INICIAL: {TipoMovimiento.ENTRADA},
    OrigenMovimiento.AJUSTE: {TipoMovimiento.ENTRADA, TipoMovimiento.SALIDA},
    OrigenMovimiento.MERMA: {TipoMovimiento.SALIDA},
    OrigenMovimiento.TRASPASO: {TipoMovimiento.ENTRADA, TipoMovimiento.SALIDA},
    OrigenMovimiento.SERVICIO_TECNICO: {TipoMovimiento.SALIDA},
    OrigenMovimiento.VENTA_INTERNA: {TipoMovimiento.ENTRADA, TipoMovimiento.SALIDA},
    OrigenMovimiento.TRASLADO_EMPRESAS: {TipoMovimiento.ENTRADA, TipoMovimiento.SALIDA},
}
# Tipo de operación SUNAT (tabla 12) que corresponde a cada origen si no se indica otro.
_OPERACION_POR_ORIGEN = {
    OrigenMovimiento.COMPRA: "02",
    OrigenMovimiento.VENTA: "01",
    OrigenMovimiento.DEVOLUCION_CLIENTE: "05",
    OrigenMovimiento.DEVOLUCION_PROVEEDOR: "06",
    OrigenMovimiento.SALDO_INICIAL: SALDO_INICIAL,
    OrigenMovimiento.AJUSTE: OTROS,
    OrigenMovimiento.MERMA: OTROS,
    OrigenMovimiento.TRASPASO: OTROS,
    OrigenMovimiento.SERVICIO_TECNICO: OTROS,
    OrigenMovimiento.VENTA_INTERNA: OTROS,
    OrigenMovimiento.TRASLADO_EMPRESAS: OTROS,
}
# Orígenes que llevan IGV por defecto (los demás son movimientos internos, sin impuesto).
_CON_IGV = {
    OrigenMovimiento.COMPRA,
    OrigenMovimiento.VENTA,
    OrigenMovimiento.DEVOLUCION_CLIENTE,
    OrigenMovimiento.DEVOLUCION_PROVEEDOR,
}


@dataclass(frozen=True, slots=True)
class LineaNueva:
    """Una línea que pide quien registra: producto, cantidad y precio del comprobante.

    En las entradas el precio es obligatorio (es el costo; en soles si el comprobante es en soles).
    En las salidas no hace falta: salen al costo promedio. Si se da, solo alimenta los importes
    del comprobante.
    """

    producto: Producto
    cantidad: Decimal
    precio_unitario: Decimal | None = None
    # Productos que llevan serie o IMEI: una por unidad (la cantidad debe coincidir).
    series: tuple[str, ...] = ()
    # «Otros datos» de cada serie, en el mismo orden (vacío = sin datos). Solo en las entradas.
    datos_series: tuple[str, ...] = ()
    # Valor de la entrada en soles, ya calculado (lo usa el traspaso para llevar el costo exacto).
    importe: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _Linea:
    """Línea ya validada. ``importe`` (soles) viene dado en entradas y en extornos."""

    producto: Producto
    cantidad: Decimal
    precio_unitario: Decimal | None
    importe: Decimal | None
    costo_fijo: bool
    series: tuple[str, ...] = ()
    datos_series: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Validación (sin tocar la base de datos más de lo necesario)
# ---------------------------------------------------------------------------
def _decimal_valido(valor, campo: str, *, maximo: Decimal, decimales: Decimal) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise MovimientoInvalido(f"{campo}: indique un número válido.")
    if valor != valor.quantize(decimales):
        raise MovimientoInvalido(f"{campo}: tiene demasiados decimales.")
    if valor > maximo:
        raise MovimientoInvalido(f"{campo}: el valor es demasiado grande.")
    return valor


def _validar_fecha(fecha) -> date:
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise MovimientoInvalido("La fecha no es válida.")
    if fecha > timezone.localdate():
        raise MovimientoInvalido("La fecha no puede ser futura.")
    return fecha


def _validar_comprobante(
    empresa: Empresa, tipo: str, serie: str, numero: str
) -> tuple[str, str, str]:
    tipo = (tipo or "").strip()
    serie = " ".join((serie or "").split()).upper()
    numero = " ".join((numero or "").split()).upper()
    if tipo:
        catalogo = (
            TipoComprobante.objects.sin_ambito()
            .filter(organizacion_id=empresa.organizacion_id, codigo=tipo)
            .first()
        )
        if catalogo is None or catalogo.estado != EstadoRegistro.ACTIVO:
            raise MovimientoInvalido("El tipo de comprobante no es válido.")
        try:
            serie, numero = validar_serie_numero(catalogo, serie, numero)
        except ValueError as error:
            raise MovimientoInvalido(str(error)) from None
    if (serie or numero) and not tipo:
        raise MovimientoInvalido("Indique el tipo de comprobante.")
    if serie and not _SERIE.fullmatch(serie):
        raise MovimientoInvalido("La serie solo admite letras, números y guiones (hasta 10).")
    if numero and not _NUMERO.fullmatch(numero):
        raise MovimientoInvalido("El número solo admite letras, números y guiones (hasta 20).")
    return tipo, serie, numero


def _tasa_igv(
    empresa: Empresa, origen: str, igv_porcentaje: Decimal | None, fecha: date
) -> Decimal:
    if igv_porcentaje is not None:
        if not isinstance(igv_porcentaje, Decimal) or not (Decimal("0") <= igv_porcentaje <= CIEN):
            raise MovimientoInvalido("El porcentaje de IGV debe estar entre 0 y 100.")
        return igv_porcentaje
    if origen not in _CON_IGV:
        return Decimal("0")
    # La tasa de la organización vigente en la fecha del movimiento (cambia con la ley).
    return tasa_vigente(empresa.organizacion_id, "IGV", fecha)


def _resolver_tipo_cambio(
    empresa: Empresa, moneda: str, tipo_cambio: Decimal | None, tipo: str, fecha: date
) -> Decimal:
    """Soles por dólar. En soles es 1. En dólares: el indicado, o el del día.

    Práctica contable habitual: las compras (entradas) con el tipo de cambio VENTA y las ventas
    (salidas) con el de COMPRA, de la fuente oficial SUNAT.
    """
    if moneda == Moneda.PEN:
        return UNO
    if tipo_cambio is not None:
        valor = _decimal_valido(
            tipo_cambio, "Tipo de cambio", maximo=Decimal("9999.9999"), decimales=CUATRO
        )
        if valor <= 0:
            raise MovimientoInvalido("El tipo de cambio debe ser mayor que cero.")
        return valor
    vigente = servicio_tipo_cambio.vigente(empresa.organizacion_id, fecha)
    if vigente is None:
        raise TipoCambioNoDisponible()
    return vigente.venta if tipo == TipoMovimiento.ENTRADA else vigente.compra


def _validar_producto(producto: Producto, empresa: Empresa) -> None:
    if producto.organizacion_id != empresa.organizacion_id:
        raise MovimientoInvalido("Un producto no pertenece a la organización.")
    if producto.tipo != TipoProducto.BIEN or not producto.controla_stock:
        raise ProductoNoInventariable(f"{producto.nombre} no lleva control de stock.")


def _preparar_lineas(
    lineas: Sequence[LineaNueva],
    *,
    empresa: Empresa,
    tipo: str,
    tasa: Decimal,
    incluye_igv: bool,
    tipo_cambio: Decimal,
    salida_con_costo: bool = False,
) -> list[_Linea]:
    if not lineas:
        raise MovimientoInvalido("Agregue al menos un producto.")
    if len(lineas) > MAX_LINEAS:
        raise MovimientoInvalido(f"Un movimiento admite hasta {MAX_LINEAS} productos.")
    preparadas = []
    vistas: set[tuple[int, str]] = set()
    for nueva in lineas:
        _validar_producto(nueva.producto, empresa)
        cantidad = _decimal_valido(nueva.cantidad, "Cantidad", maximo=MAX_CANTIDAD, decimales=TRES)
        if cantidad <= 0:
            raise MovimientoInvalido("La cantidad debe ser mayor que cero.")
        series = _validar_series(nueva, cantidad)
        datos_series = _validar_datos_series(nueva, series)
        for numero in series:
            if (nueva.producto.pk, numero) in vistas:
                raise MovimientoInvalido(f"La serie {numero} se repite en el movimiento.")
            vistas.add((nueva.producto.pk, numero))
        precio = nueva.precio_unitario
        if precio is not None:
            precio = _decimal_valido(precio, "Precio", maximo=MAX_PRECIO, decimales=SEIS)
            if precio < 0:
                raise MovimientoInvalido("El precio no puede ser negativo.")
        importe = None
        if tipo == TipoMovimiento.ENTRADA:
            if nueva.importe is not None:
                importe = _decimal_valido(
                    nueva.importe, "Importe", maximo=MAX_IMPORTE, decimales=DOS
                )
                if importe < 0:
                    raise MovimientoInvalido("El importe no puede ser negativo.")
            elif precio is None:
                raise MovimientoInvalido(f"Indique el precio de {nueva.producto.nombre}.")
            else:
                neto = precio / (UNO + tasa / CIEN) if incluye_igv else precio
                importe = a_dos(cantidad * neto * tipo_cambio)
                if importe > MAX_IMPORTE:
                    raise MovimientoInvalido("El importe es demasiado grande.")
        elif nueva.importe is not None:
            if not salida_con_costo:
                raise MovimientoInvalido("Las salidas se valorizan solas, al costo promedio.")
            # Devolución a un proveedor: sale por lo que costó en la compra de origen.
            importe = _decimal_valido(nueva.importe, "Importe", maximo=MAX_IMPORTE, decimales=DOS)
            if importe < 0:
                raise MovimientoInvalido("El importe no puede ser negativo.")
        preparadas.append(
            _Linea(
                nueva.producto, cantidad, precio, importe, importe is not None, series, datos_series
            )
        )
    return preparadas


def _validar_series(nueva: LineaNueva, cantidad: Decimal) -> tuple[str, ...]:
    """Normaliza las series de una línea y exige una por unidad si el producto las lleva."""
    producto = nueva.producto
    series = tuple(" ".join(str(s).split()).upper() for s in nueva.series)
    if not producto.lleva_serie:
        if series:
            raise MovimientoInvalido(f"{producto.nombre} no lleva serie o IMEI.")
        return ()
    if cantidad != cantidad.to_integral_value():
        raise MovimientoInvalido(f"{producto.nombre}: con serie, la cantidad es un número entero.")
    if len(series) != int(cantidad):
        raise MovimientoInvalido(
            f"{producto.nombre}: indique {int(cantidad)} serie(s) y recibió {len(series)}."
        )
    for numero in series:
        if not _NUMERO_SERIE.fullmatch(numero):
            raise MovimientoInvalido(
                f"La serie «{numero[:40]}» no es válida: use de 3 a 40 letras, números, "
                "guiones o puntos."
            )
    if len(set(series)) != len(series):
        raise MovimientoInvalido(f"{producto.nombre}: hay series repetidas.")
    return series


def _validar_datos_series(nueva: LineaNueva, series: tuple[str, ...]) -> tuple[str, ...]:
    """Los «otros datos» de cada serie: opcionales, de hasta 120 caracteres y uno por serie."""
    if not series:
        return ()
    if not nueva.datos_series:
        return ("",) * len(series)
    if len(nueva.datos_series) != len(series):
        raise MovimientoInvalido(
            f"{nueva.producto.nombre}: los otros datos deben ser uno por cada serie."
        )
    datos = tuple(" ".join(str(d or "").split()) for d in nueva.datos_series)
    if any(len(d) > TOPE_OTROS_DATOS for d in datos):
        raise MovimientoInvalido(
            f"Los otros datos de una serie admiten hasta {TOPE_OTROS_DATOS} caracteres."
        )
    return datos


def _totales(
    lineas: Sequence[_Linea], tasa: Decimal, incluye_igv: bool
) -> tuple[Decimal, Decimal, Decimal]:
    """Subtotal, IGV y total del comprobante, en su moneda."""
    suma = sum(
        (ln.cantidad * ln.precio_unitario for ln in lineas if ln.precio_unitario), Decimal(0)
    )
    if incluye_igv and tasa > 0:
        total = a_dos(suma)
        subtotal = a_dos(suma / (UNO + tasa / CIEN))
        return subtotal, total - subtotal, total
    subtotal = a_dos(suma)
    igv = a_dos(suma * tasa / CIEN)
    return subtotal, igv, subtotal + igv


# ---------------------------------------------------------------------------
# Bloqueos y recálculo del Kardex
# ---------------------------------------------------------------------------
def _bloquear_saldos(
    empresa: Empresa, almacen: Almacen, producto_ids: set[int]
) -> dict[int, SaldoStock]:
    """Crea (si faltan) y bloquea los saldos, siempre en orden de producto (sin interbloqueos)."""
    ids = sorted(producto_ids)
    existentes = set(
        SaldoStock.objects.filter(
            empresa=empresa, almacen=almacen, producto_id__in=ids
        ).values_list("producto_id", flat=True)
    )
    faltan = [pid for pid in ids if pid not in existentes]
    if faltan:
        SaldoStock.objects.bulk_create(
            [SaldoStock(empresa=empresa, almacen=almacen, producto_id=pid) for pid in faltan],
            ignore_conflicts=True,
        )
    filas = (
        SaldoStock.objects.select_for_update()
        .filter(empresa=empresa, almacen=almacen, producto_id__in=ids)
        .order_by("producto_id")
    )
    return {fila.producto_id: fila for fila in filas}


def _recalcular(saldo: SaldoStock, desde: LineaMovimiento, producto: Producto) -> None:
    """Recalcula el Kardex del producto desde ``desde`` y deja el saldo final al día.

    Normalmente ``desde`` es la última línea y solo se calcula ella. Con fecha atrasada se
    recorren las posteriores, cuyas salidas cambian de costo si el promedio cambió.
    """
    de_este_kardex = LineaMovimiento.objects.filter(
        empresa_id=desde.empresa_id, almacen_id=desde.almacen_id, producto_id=desde.producto_id
    )
    antes = Q(fecha__lt=desde.fecha) | Q(fecha=desde.fecha, movimiento_id__lt=desde.movimiento_id)
    antes |= Q(fecha=desde.fecha, movimiento_id=desde.movimiento_id, id__lt=desde.id)
    anterior = de_este_kardex.filter(antes).order_by("-fecha", "-movimiento_id", "-id").first()
    estado = (
        Saldo(anterior.saldo_cantidad, anterior.saldo_costo_total, anterior.saldo_costo_unitario)
        if anterior
        else Saldo()
    )
    pendientes = list(de_este_kardex.exclude(antes).order_by("fecha", "movimiento_id", "id"))
    modificadas = []
    for linea in pendientes:
        try:
            if linea.tipo == TipoMovimiento.ENTRADA:
                estado_nuevo = costeo.aplicar_entrada(estado, linea.cantidad, linea.costo_total)
                importe = linea.costo_total
            else:
                estado_nuevo, importe = costeo.aplicar_salida(
                    estado, linea.cantidad, linea.costo_total if linea.costo_fijo else None
                )
        except StockInsuficiente as error:
            raise StockInsuficiente(
                f"{producto.nombre} ({linea.fecha:%d/%m/%Y}): {error.mensaje}",
                detalle=error.detalle,
            ) from None
        valores = (
            importe,
            a_seis(importe / linea.cantidad),
            estado_nuevo.cantidad,
            estado_nuevo.costo_total,
            estado_nuevo.costo_unitario,
        )
        actuales = (
            linea.costo_total,
            linea.costo_unitario,
            linea.saldo_cantidad,
            linea.saldo_costo_total,
            linea.saldo_costo_unitario,
        )
        if valores != actuales:
            (
                linea.costo_total,
                linea.costo_unitario,
                linea.saldo_cantidad,
                linea.saldo_costo_total,
                linea.saldo_costo_unitario,
            ) = valores
            modificadas.append(linea)
        estado = estado_nuevo
    if modificadas:
        LineaMovimiento.objects.bulk_update(
            modificadas,
            [
                "costo_total",
                "costo_unitario",
                "saldo_cantidad",
                "saldo_costo_total",
                "saldo_costo_unitario",
            ],
            batch_size=500,
        )
    saldo.cantidad = estado.cantidad
    saldo.costo_total = estado.costo_total
    saldo.costo_unitario = estado.costo_unitario
    saldo.save(update_fields=["cantidad", "costo_total", "costo_unitario"])


def _entradas_sin_historial(
    empresa: Empresa,
    almacen: Almacen,
    movimiento: MovimientoInventario,
    creadas: list[LineaMovimiento],
    saldos: dict[int, SaldoStock],
) -> set[int]:
    """Calcula de una sola vez los productos cuyo Kardex es trivial; devuelve cuáles.

    Es el caso de una carga inicial o de la primera compra de un producto: entra UNA línea en este
    movimiento, es una entrada, el saldo está en cero y el producto nunca tuvo líneas en el
    almacén. Su saldo es simplemente lo que entra, sin recorrer historial. Se escribe todo con
    una escritura masiva en vez de varias consultas por producto (una carga de miles de
    productos pasa de decenas de segundos a unos pocos). Los demás casos siguen el camino normal.
    """
    veces: dict[int, int] = {}
    for linea in creadas:
        veces[linea.producto_id] = veces.get(linea.producto_id, 0) + 1
    candidatos = {
        pid
        for pid, n in veces.items()
        if n == 1 and saldos[pid].cantidad == 0 and saldos[pid].costo_total == 0
    }
    if not candidatos:
        return set()
    con_historial = set(
        LineaMovimiento.objects.filter(empresa=empresa, almacen=almacen, producto_id__in=candidatos)
        .exclude(movimiento=movimiento)
        .values_list("producto_id", flat=True)
        .distinct()
    )
    por_producto = {ln.producto_id: ln for ln in creadas}
    aplicables = {
        pid
        for pid in candidatos - con_historial
        if por_producto[pid].tipo == TipoMovimiento.ENTRADA
    }
    if not aplicables:
        return set()
    ahora = timezone.now()
    lineas_modificadas, saldos_modificados = [], []
    for pid in aplicables:
        linea, saldo = por_producto[pid], saldos[pid]
        nuevo = costeo.aplicar_entrada(Saldo(), linea.cantidad, linea.costo_total)
        linea.saldo_cantidad = nuevo.cantidad
        linea.saldo_costo_total = nuevo.costo_total
        linea.saldo_costo_unitario = nuevo.costo_unitario
        saldo.cantidad, saldo.costo_total, saldo.costo_unitario = (
            nuevo.cantidad,
            nuevo.costo_total,
            nuevo.costo_unitario,
        )
        saldo.actualizado_en = ahora
        lineas_modificadas.append(linea)
        saldos_modificados.append(saldo)
    LineaMovimiento.objects.bulk_update(
        lineas_modificadas,
        ["saldo_cantidad", "saldo_costo_total", "saldo_costo_unitario"],
        batch_size=500,
    )
    SaldoStock.objects.bulk_update(
        saldos_modificados,
        ["cantidad", "costo_total", "costo_unitario", "actualizado_en"],
        batch_size=500,
    )
    return aplicables


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def _guardar_cabecera(**campos) -> MovimientoInventario:
    try:
        with transaction.atomic():  # savepoint: la transacción externa sigue utilizable
            return MovimientoInventario.objects.create(**campos)
    except IntegrityError as error:
        restriccion = getattr(getattr(error.__cause__, "diag", None), "constraint_name", "") or ""
        if restriccion.startswith("uq_movinv_comprobante"):
            raise ComprobanteDuplicado() from None
        raise


def _crear_movimiento(
    *,
    empresa: Empresa,
    almacen: Almacen,
    tipo: str,
    origen: str,
    tipo_operacion: str,
    fecha: date,
    lineas: list[_Linea],
    cabecera: dict,
    extorna: MovimientoInventario | None = None,
) -> MovimientoInventario:
    with transaction.atomic():
        correlativo = numeracion.bloquear(empresa)  # cerrojo por empresa, antes de mirar periodos
        periodos.exigir_abierto(empresa.pk, fecha)
        saldos = _bloquear_saldos(empresa, almacen, {ln.producto.pk for ln in lineas})
        movimiento = _guardar_cabecera(
            empresa=empresa,
            almacen=almacen,
            numero=numeracion.siguiente(correlativo),
            tipo=tipo,
            origen=origen,
            tipo_operacion=tipo_operacion,
            fecha=fecha,
            extorna=extorna,
            **cabecera,
        )
        creadas = LineaMovimiento.objects.bulk_create(
            [
                LineaMovimiento(
                    empresa=empresa,
                    movimiento=movimiento,
                    almacen=almacen,
                    fecha=fecha,
                    tipo=tipo,
                    producto=ln.producto,
                    orden=posicion,
                    cantidad=ln.cantidad,
                    precio_unitario=ln.precio_unitario,
                    costo_total=ln.importe or Decimal("0"),
                    costo_unitario=a_seis(ln.importe / ln.cantidad) if ln.importe else Decimal("0"),
                    costo_fijo=ln.costo_fijo,
                )
                for posicion, ln in enumerate(lineas)
            ]
        )
        _aplicar_series(empresa, almacen, tipo, creadas, lineas)
        primera_de = {}
        for linea in creadas:  # las líneas llegan en orden: la primera de cada producto
            primera_de.setdefault(linea.producto_id, linea)
        productos = {ln.producto.pk: ln.producto for ln in lineas}
        rapidos = _entradas_sin_historial(empresa, almacen, movimiento, creadas, saldos)
        for producto_id, linea in primera_de.items():
            if producto_id not in rapidos:
                _recalcular(saldos[producto_id], linea, productos[producto_id])
        registrar(
            "inventario.movimiento_registrado",
            recurso_tipo="movimiento_inventario",
            recurso_id=movimiento.pk,
            empresa_id=empresa.pk,
            resumen=f"{movimiento.get_tipo_display()} N° {movimiento.numero:06d} "
            f"({movimiento.get_origen_display()})",
            detalle={
                "almacen": almacen.pk,
                "fecha": fecha,
                "lineas": len(lineas),
                "total": movimiento.total,
            },
        )
    logger.info(
        "movimiento_inventario_registrado",
        extra={
            "empresa_id": empresa.pk,
            "movimiento_id": movimiento.pk,
            "tipo": tipo,
            "origen": origen,
            "lineas": len(lineas),
        },
    )
    return movimiento


def registrar_movimiento(
    *,
    empresa: Empresa,
    almacen: Almacen,
    tipo: str,
    origen: str,
    fecha: date,
    lineas: Sequence[LineaNueva],
    tipo_operacion: str | None = None,
    proveedor: Proveedor | None = None,
    cliente: Cliente | None = None,
    comprobante_tipo: str = "",
    comprobante_serie: str = "",
    comprobante_numero: str = "",
    comprobante_fecha: date | None = None,
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    precios_incluyen_igv: bool = False,
    igv_porcentaje: Decimal | None = None,
    observacion: str = "",
    referencia_tipo: str = "",
    referencia_id: int | None = None,
    traspaso_id: uuid.UUID | None = None,
    totales: tuple[Decimal, Decimal, Decimal] | None = None,
    salida_con_costo: bool = False,
) -> MovimientoInventario:
    """Registra una entrada o una salida y deja el Kardex y el stock al día.

    ``salida_con_costo`` solo lo usan las devoluciones a un proveedor y lo que se devuelve de una
    venta interna: cada línea trae su ``importe`` (el costo de origen) y la salida descuenta ese
    valor, no el promedio.

    Quien llama (la vista, o el módulo de compras o ventas) ya validó el permiso; aquí se exige
    que la empresa esté habilitada en el contexto activo. Lanza errores de dominio con mensaje
    claro: ``StockInsuficiente``, ``PeriodoCerrado``, ``TipoCambioNoDisponible``,
    ``ComprobanteDuplicado``, ``MovimientoInvalido``…
    """
    periodos.exigir_empresa(empresa)
    if origen not in _TIPOS_POR_ORIGEN or tipo not in _TIPOS_POR_ORIGEN[origen]:
        raise MovimientoInvalido("El tipo de movimiento no corresponde a su origen.")
    if almacen.empresa_id != empresa.pk:
        raise MovimientoInvalido("El almacén no pertenece a la empresa.")
    if almacen.estado != EstadoRegistro.ACTIVO:
        raise MovimientoInvalido("El almacén está inactivo.")
    fecha = _validar_fecha(fecha)
    operacion = tipo_operacion or _OPERACION_POR_ORIGEN[origen]
    if operacion not in TIPOS_OPERACION:
        raise MovimientoInvalido("El tipo de operación no es válido.")
    if moneda not in Moneda.values:
        raise MovimientoInvalido("La moneda no es válida.")
    if proveedor is not None and cliente is not None:
        raise MovimientoInvalido("Indique un proveedor o un cliente, no ambos.")
    if proveedor is not None and proveedor.organizacion_id != empresa.organizacion_id:
        raise MovimientoInvalido("El proveedor no pertenece a la organización.")
    if cliente is not None and cliente.organizacion_id != empresa.organizacion_id:
        raise MovimientoInvalido("El cliente no pertenece a la organización.")
    if comprobante_fecha is not None and (
        not isinstance(comprobante_fecha, date) or isinstance(comprobante_fecha, datetime)
    ):
        raise MovimientoInvalido("La fecha del comprobante no es válida.")
    tipo_comp, serie, numero = _validar_comprobante(
        empresa, comprobante_tipo, comprobante_serie, comprobante_numero
    )
    tasa = _tasa_igv(empresa, origen, igv_porcentaje, fecha)
    cambio = _resolver_tipo_cambio(empresa, moneda, tipo_cambio, tipo, fecha)
    preparadas = _preparar_lineas(
        lineas,
        empresa=empresa,
        tipo=tipo,
        tasa=tasa,
        incluye_igv=precios_incluyen_igv,
        tipo_cambio=cambio,
        salida_con_costo=(
            salida_con_costo
            and tipo == TipoMovimiento.SALIDA
            and origen
            in (
                OrigenMovimiento.DEVOLUCION_PROVEEDOR,
                OrigenMovimiento.VENTA_INTERNA,
                OrigenMovimiento.TRASLADO_EMPRESAS,
            )
        ),
    )
    if totales is not None:
        # Compras ya calculó el comprobante completo (con exonerado, inafecto, ajuste…).
        subtotal, igv, total = totales
    else:
        subtotal, igv, total = _totales(preparadas, tasa, precios_incluyen_igv)
    cabecera = {
        "comprobante_tipo": tipo_comp,
        "comprobante_serie": serie,
        "comprobante_numero": numero,
        "comprobante_fecha": comprobante_fecha,
        "proveedor": proveedor,
        "cliente": cliente,
        "moneda": moneda,
        "tipo_cambio": cambio,
        "precios_incluyen_igv": precios_incluyen_igv,
        "igv_porcentaje": tasa,
        "subtotal": subtotal,
        "igv": igv,
        "total": total,
        "observacion": " ".join((observacion or "").split())[:250],
        "referencia_tipo": (referencia_tipo or "")[:30],
        "referencia_id": referencia_id,
        "traspaso_id": traspaso_id,
    }
    return _crear_movimiento(
        empresa=empresa,
        almacen=almacen,
        tipo=tipo,
        origen=origen,
        tipo_operacion=operacion,
        fecha=fecha,
        lineas=preparadas,
        cabecera=cabecera,
    )


# ---------------------------------------------------------------------------
# Series o IMEI
# ---------------------------------------------------------------------------
def _aplicar_series(
    empresa: Empresa,
    almacen: Almacen,
    tipo: str,
    creadas: list[LineaMovimiento],
    lineas: list[_Linea],
) -> None:
    """Registra las series de las entradas y cierra las de las salidas (todo o nada)."""
    con_series = [(c, ln) for c, ln in zip(creadas, lineas, strict=True) if ln.series]
    if not con_series:
        return
    productos = {ln.producto.pk for _, ln in con_series}
    numeros = {s for _, ln in con_series for s in ln.series}
    if tipo == TipoMovimiento.ENTRADA:
        en_stock = set(
            SerieProducto.objects.sin_ambito()
            .filter(estado=EstadoSerie.EN_STOCK, producto_id__in=productos, numero__in=numeros)
            .values_list("producto_id", "numero")
        )
        for _, ln in con_series:
            for numero in ln.series:
                if (ln.producto.pk, numero) in en_stock:
                    raise MovimientoInvalido(f"La serie {numero} ya está en stock.")
        nuevas = [
            SerieProducto(
                empresa=empresa,
                producto=ln.producto,
                numero=numero,
                otros_datos=datos,
                almacen=almacen,
                entrada=linea,
            )
            for linea, ln in con_series
            for numero, datos in zip(
                ln.series, ln.datos_series or ("",) * len(ln.series), strict=True
            )
        ]
        try:
            with transaction.atomic():  # savepoint: la transacción externa sigue utilizable
                SerieProducto.objects.bulk_create(nuevas, batch_size=500)
        except IntegrityError:
            # Otra empresa registró la misma serie en este instante.
            raise MovimientoInvalido("Una de las series ya está en stock.") from None
        return
    filas = {
        (f.producto_id, f.numero): f
        for f in SerieProducto.objects.select_for_update().filter(
            empresa=empresa,
            almacen=almacen,
            estado=EstadoSerie.EN_STOCK,
            producto_id__in=productos,
            numero__in=numeros,
        )
    }
    cerradas = []
    for linea, ln in con_series:
        for numero in ln.series:
            fila = filas.get((ln.producto.pk, numero))
            if fila is None:
                raise MovimientoInvalido(
                    f"La serie {numero} de {ln.producto.nombre} no está en este almacén."
                )
            fila.estado = EstadoSerie.SALIDO
            fila.salida = linea
            cerradas.append(fila)
    SerieProducto.objects.bulk_update(cerradas, ["estado", "salida"], batch_size=500)


def _series_de(linea: LineaMovimiento, tipo: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Las series (y sus otros datos) que entraron o salieron con una línea, para anularla."""
    campo = "entrada" if tipo == TipoMovimiento.ENTRADA else "salida"
    consulta = SerieProducto.objects.filter(**{campo: linea}).order_by("id")
    filas = list(consulta.values_list("numero", "otros_datos"))
    return tuple(n for n, _ in filas), tuple(d for _, d in filas)


# ---------------------------------------------------------------------------
# Traspasos entre almacenes de la misma empresa
# ---------------------------------------------------------------------------
def registrar_traspaso(
    *,
    empresa: Empresa,
    origen: Almacen,
    destino: Almacen,
    fecha: date,
    lineas: Sequence[LineaNueva],
    observacion: str = "",
) -> tuple[MovimientoInventario, MovimientoInventario]:
    """Mueve mercadería de un almacén a otro de la MISMA empresa. Devuelve (salida, entrada).

    Son dos movimientos con el mismo código de traspaso: sale del origen al costo promedio de
    allí y entra al destino por ese mismo valor (se mezcla con el costo que ya tenía). Las series
    viajan con la mercadería. Si falta stock en el origen no se hace nada.
    """
    periodos.exigir_empresa(empresa)
    if origen.pk == destino.pk:
        raise MovimientoInvalido("El almacén de origen y el de destino deben ser distintos.")
    for almacen in (origen, destino):
        if almacen.empresa_id != empresa.pk:
            raise MovimientoInvalido("Los almacenes deben pertenecer a la empresa.")
    if any(ln.importe is not None or ln.precio_unitario is not None for ln in lineas):
        raise MovimientoInvalido("Un traspaso no lleva precios: se valoriza solo.")
    codigo = uuid.uuid4()
    nota = " ".join((observacion or "").split())
    with transaction.atomic():
        salida = registrar_movimiento(
            empresa=empresa,
            almacen=origen,
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.TRASPASO,
            fecha=fecha,
            lineas=lineas,
            observacion=f"Traspaso a {destino.nombre}. {nota}".strip()[:250],
            traspaso_id=codigo,
        )
        valores = list(salida.lineas.order_by("orden", "id"))
        entrada = registrar_movimiento(
            empresa=empresa,
            almacen=destino,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.TRASPASO,
            fecha=fecha,
            lineas=[
                LineaNueva(
                    producto=pedida.producto,
                    cantidad=pedida.cantidad,
                    importe=valor.costo_total,
                    series=pedida.series,
                    # Las series viajan con sus otros datos: se leen de las que acaban de salir.
                    datos_series=_datos_de_series_salidas(valor, pedida),
                )
                for pedida, valor in zip(lineas, valores, strict=True)
            ],
            observacion=f"Traspaso desde {origen.nombre}. {nota}".strip()[:250],
            traspaso_id=codigo,
        )
    return salida, entrada


def registrar_traslado_entre_empresas(
    *,
    origen: Almacen,
    destino: Almacen,
    fecha: date,
    lineas: Sequence[LineaNueva],
    codigo: uuid.UUID,
    observacion: str = "",
    motivo: str = OrigenMovimiento.VENTA_INTERNA,
) -> tuple[MovimientoInventario, MovimientoInventario]:
    """Pasa mercadería de un almacén de una empresa a un almacén de OTRA empresa (venta interna).

    ``motivo`` es el origen que queda en el Kardex: la venta interna (por defecto) o un traslado
    entre empresas sin venta al cliente.

    Es la base de la venta interna: sale del origen al costo promedio de allí y entra al destino
    por ese mismo valor, que se mezcla con el costo que el destino ya tenía. Sin margen entre las
    empresas. Las series viajan con la mercadería. Devuelve (salida, entrada); ambas comparten
    ``codigo`` (el de la venta interna que las agrupa). Si falta stock en el origen no se hace nada.

    Se bloquea el correlativo de las DOS empresas, siempre en el mismo orden que usa Ventas
    (primero la principal, luego por id): dos traslados cruzados no se esperan el uno al otro.
    """
    if any(ln.importe is not None or ln.precio_unitario is not None for ln in lineas):
        raise MovimientoInvalido("Una venta interna no lleva precios: se valoriza al costo.")
    return _trasladar_entre_empresas(
        origen, destino, fecha, lineas, codigo, observacion, False, motivo
    )


def devolver_traslado_entre_empresas(
    *,
    origen: Almacen,
    destino: Almacen,
    fecha: date,
    lineas: Sequence[LineaNueva],
    codigo: uuid.UUID,
    observacion: str = "",
) -> tuple[MovimientoInventario, MovimientoInventario]:
    """Devuelve a la empresa que entregó lo que una venta interna le había pasado a ``origen``.

    Cada línea trae su ``importe`` (soles): el costo con que salió de la empresa que entregó. Sale
    de ``origen`` y entra a ``destino`` por EXACTAMENTE ese valor, sin pasar por el costo promedio
    de hoy: así lo que una empresa pierde es lo que la otra recupera y nada se desfasa.
    """
    if any(ln.importe is None for ln in lineas):
        raise MovimientoInvalido("Cada línea de la devolución lleva el costo con que salió.")
    return _trasladar_entre_empresas(
        origen, destino, fecha, lineas, codigo, observacion, True, OrigenMovimiento.VENTA_INTERNA
    )


def _trasladar_entre_empresas(
    origen: Almacen,
    destino: Almacen,
    fecha: date,
    lineas: Sequence[LineaNueva],
    codigo: uuid.UUID,
    observacion: str,
    valor_fijo: bool,
    motivo: str = OrigenMovimiento.VENTA_INTERNA,
) -> tuple[MovimientoInventario, MovimientoInventario]:
    nombre_op = "Traslado" if motivo == OrigenMovimiento.TRASLADO_EMPRESAS else "Venta interna"
    empresa_origen, empresa_destino = origen.empresa, destino.empresa
    periodos.exigir_empresa(empresa_origen)
    periodos.exigir_empresa(empresa_destino)
    if empresa_origen.pk == empresa_destino.pk:
        raise MovimientoInvalido("Los almacenes deben ser de empresas distintas.")
    if empresa_origen.organizacion_id != empresa_destino.organizacion_id:
        raise MovimientoInvalido("Las empresas deben ser de la misma organización.")
    nota = " ".join((observacion or "").split())
    with transaction.atomic():
        for empresa in sorted((empresa_origen, empresa_destino), key=_orden_de_bloqueo):
            numeracion.bloquear(empresa)
        salida = registrar_movimiento(
            empresa=empresa_origen,
            almacen=origen,
            tipo=TipoMovimiento.SALIDA,
            origen=motivo,
            fecha=fecha,
            lineas=lineas,
            observacion=f"{nombre_op} a {destino.empresa.razon_social}. {nota}".strip()[:250],
            traspaso_id=codigo,
            salida_con_costo=valor_fijo,
        )
        valores = list(salida.lineas.order_by("orden", "id"))
        entrada = registrar_movimiento(
            empresa=empresa_destino,
            almacen=destino,
            tipo=TipoMovimiento.ENTRADA,
            origen=motivo,
            fecha=fecha,
            lineas=[
                LineaNueva(
                    producto=pedida.producto,
                    cantidad=pedida.cantidad,
                    importe=valor.costo_total,
                    series=pedida.series,
                    datos_series=_datos_de_series_salidas(valor, pedida),
                )
                for pedida, valor in zip(lineas, valores, strict=True)
            ],
            observacion=f"{nombre_op} de {origen.empresa.razon_social}. {nota}".strip()[:250],
            traspaso_id=codigo,
        )
    return salida, entrada


def _orden_de_bloqueo(empresa: Empresa) -> tuple[bool, int]:
    """La empresa principal primero y las demás por su id (el mismo orden de Ventas)."""
    return (not empresa.es_principal, empresa.pk)


def _datos_de_series_salidas(valor: LineaMovimiento, pedida: LineaNueva) -> tuple[str, ...]:
    """Los otros datos de las series de una línea de salida, en el orden en que se pidieron."""
    if not pedida.series:
        return ()
    por_numero = dict(
        SerieProducto.objects.filter(salida=valor).values_list("numero", "otros_datos")
    )
    return tuple(por_numero.get(" ".join(str(s).split()).upper(), "") for s in pedida.series)


def _anular_traspaso(original: MovimientoInventario, motivo: str) -> MovimientoInventario:
    """Anula las DOS mitades de un traspaso: primero saca del destino y luego devuelve al origen."""
    with transaction.atomic():
        pareja = (
            MovimientoInventario.objects.select_for_update()
            .filter(traspaso_id=original.traspaso_id, empresa_id=original.empresa_id)
            .exclude(pk=original.pk)
            .first()
        )
        if pareja is None:
            raise AnulacionNoPermitida("No se encontró la otra mitad del traspaso.")
        if pareja.estado == MovimientoInventario.Estado.ANULADO:
            raise DocumentoYaAnulado()
        if original.tipo == TipoMovimiento.ENTRADA:
            entrada, salida = original, pareja
        else:
            entrada, salida = pareja, original
        # La guía de remisión describe este traslado: primero se anula la guía.
        guia = salida.guias_de_traslado.filter(estado="EMITIDO").first()
        if guia is not None:
            raise AnulacionNoPermitida(
                f"El traspaso tiene vigente la guía de remisión {guia.numero_completo}: "
                "anúlela primero."
            )
        extorno_entrada = anular_movimiento(entrada, motivo=motivo, _interno=True)
        extorno_salida = anular_movimiento(salida, motivo=motivo, _interno=True)
    return extorno_entrada if original.pk == entrada.pk else extorno_salida


# ---------------------------------------------------------------------------
# Anulación
# ---------------------------------------------------------------------------
def anular_movimiento(
    movimiento: MovimientoInventario, *, motivo: str, _interno: bool = False
) -> MovimientoInventario:
    """Anula un movimiento creando su extorno (movimiento inverso con fecha de hoy).

    El extorno devuelve o saca cada línea por el MISMO valor que tuvo el original, así el
    valorizado se compensa exactamente. No se puede anular una entrada cuya mercadería ya salió
    (no quedaría stock o costo para devolver), ni un extorno. Devuelve el extorno.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise MotivoObligatorio()
    periodos.exigir_empresa(movimiento.empresa)
    with transaction.atomic():
        original = MovimientoInventario.objects.select_for_update().get(pk=movimiento.pk)
        if original.estado == MovimientoInventario.Estado.ANULADO:
            raise DocumentoYaAnulado()
        if original.origen == OrigenMovimiento.EXTORNO:
            raise AnulacionNoPermitida("Un extorno no se puede anular.")
        if original.origen == OrigenMovimiento.TRASPASO and not _interno:
            return _anular_traspaso(original, motivo)
        if original.origen == OrigenMovimiento.TRASLADO_EMPRESAS and not _interno:
            raise AnulacionNoPermitida(
                "Este movimiento es parte de un traslado entre empresas: se anula desde la "
                "pantalla «Traslado entre empresas»."
            )
        if original.origen == OrigenMovimiento.VENTA_INTERNA and not _interno:
            # Las dos mitades están en empresas distintas y atadas a una venta: se anulan juntas
            # desde la venta, nunca una por una desde el Kardex.
            raise AnulacionNoPermitida(
                "Este movimiento es parte de una venta interna entre empresas: se anula desde "
                "la venta."
            )
        lineas = []
        for linea in original.lineas.select_related("producto").order_by("orden", "id"):
            series, datos = (
                _series_de(linea, original.tipo) if linea.producto.lleva_serie else ((), ())
            )
            lineas.append(
                _Linea(
                    producto=linea.producto,
                    cantidad=linea.cantidad,
                    precio_unitario=None,
                    importe=linea.costo_total,
                    costo_fijo=True,
                    series=series,
                    # Si se devuelven unidades que habían salido, vuelven con sus otros datos.
                    datos_series=datos,
                )
            )
        inverso = (
            TipoMovimiento.SALIDA
            if original.tipo == TipoMovimiento.ENTRADA
            else TipoMovimiento.ENTRADA
        )
        try:
            extorno = _crear_movimiento(
                empresa=original.empresa,
                almacen=original.almacen,
                tipo=inverso,
                origen=OrigenMovimiento.EXTORNO,
                tipo_operacion=original.tipo_operacion,
                fecha=timezone.localdate(),
                lineas=lineas,
                cabecera={
                    "observacion": f"Extorno del movimiento N° {original.numero:06d}: {motivo}"[
                        :250
                    ],
                },
                extorna=original,
            )
        except (StockInsuficiente, MovimientoInvalido) as error:
            raise AnulacionNoPermitida(
                "No se puede anular: parte de la mercadería de este movimiento ya salió "
                f"del almacén ({error.mensaje})"
            ) from None
        original.anular(motivo=motivo)
        registrar(
            "inventario.movimiento_anulado",
            recurso_tipo="movimiento_inventario",
            recurso_id=original.pk,
            empresa_id=original.empresa_id,
            resumen=f"Movimiento N° {original.numero:06d} anulado",
            detalle={"motivo": motivo, "extorno": extorno.pk},
        )
    logger.info(
        "movimiento_inventario_anulado",
        extra={"empresa_id": original.empresa_id, "movimiento_id": original.pk},
    )
    return extorno


def resolver_tipo_cambio(
    empresa: Empresa, moneda: str, tipo_cambio: Decimal | None, tipo: str, fecha: date
) -> Decimal:
    """Soles por dólar de un comprobante (para quien arma el documento antes de registrarlo)."""
    return _resolver_tipo_cambio(empresa, moneda, tipo_cambio, tipo, fecha)
