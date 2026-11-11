"""Datos de los libros y reportes de inventario (solo lectura, sin formato).

Las consultas se hacen en la base de datos y tienen un tope de filas: un reporte demasiado
grande se rechaza con un mensaje claro en vez de agotar la memoria o tardar sin fin.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Prefetch, Q, Sum

from apps.inventario import antiguedad as servicio_antiguedad
from apps.inventario import consultas
from apps.inventario.costeo import Saldo
from apps.inventario.exceptions import ReporteDemasiadoGrande
from apps.inventario.models import (
    LineaMovimiento,
    MovimientoInventario,
    SaldoStock,
    TipoMovimiento,
)
from apps.mantenimiento.models import Almacen, Producto
from apps.organizacion.models import Empresa

MAX_FILAS = 50_000
CERO = Decimal("0")


def _con_tope(consulta) -> list:
    """Trae las filas de una consulta y rechaza si superan el tope."""
    filas = list(consulta[: MAX_FILAS + 1])
    if len(filas) > MAX_FILAS:
        raise ReporteDemasiadoGrande()
    return filas


# ---------------------------------------------------------------------------
# Kardex de un producto (formatos 12.1 y 13.1)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class KardexDatos:
    empresa: Empresa
    almacen: Almacen
    producto: Producto
    desde: date
    hasta: date
    saldo_inicial: Saldo
    lineas: list[LineaMovimiento]


def kardex(
    empresa: Empresa, almacen: Almacen, producto: Producto, desde: date, hasta: date
) -> KardexDatos:
    lineas = _con_tope(
        LineaMovimiento.objects.filter(
            empresa=empresa,
            almacen=almacen,
            producto=producto,
            fecha__gte=desde,
            fecha__lte=hasta,
        )
        .select_related("movimiento")
        .order_by("fecha", "movimiento_id", "id")
    )
    saldo = consultas.saldo_antes_de(empresa.pk, almacen.pk, producto.pk, desde)
    return KardexDatos(empresa, almacen, producto, desde, hasta, saldo, lineas)


# ---------------------------------------------------------------------------
# Saldos a una fecha
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FilaSaldo:
    almacen: Almacen
    producto: Producto
    cantidad: Decimal
    costo_unitario: Decimal
    costo_total: Decimal


def _ultimas_lineas(empresa: Empresa, fecha: date, almacen: Almacen | None):
    """La última línea de cada (almacén, producto) hasta ``fecha``: trae el saldo a esa fecha."""
    consulta = LineaMovimiento.objects.filter(empresa=empresa, fecha__lte=fecha)
    if almacen is not None:
        consulta = consulta.filter(almacen=almacen)
    return (
        consulta.select_related("producto__unidad", "almacen")
        .order_by("almacen_id", "producto_id", "-fecha", "-movimiento_id", "-id")
        .distinct("almacen_id", "producto_id")
    )


def saldos_a_fecha(empresa: Empresa, fecha: date, almacen: Almacen | None) -> list[FilaSaldo]:
    filas = [
        FilaSaldo(
            ln.almacen,
            ln.producto,
            ln.saldo_cantidad,
            ln.saldo_costo_unitario,
            ln.saldo_costo_total,
        )
        for ln in _con_tope(_ultimas_lineas(empresa, fecha, almacen))
        if ln.saldo_cantidad > 0 or ln.saldo_costo_total > 0
    ]
    return sorted(filas, key=lambda f: (f.almacen.codigo, f.producto.nombre.lower(), f.producto.pk))


# ---------------------------------------------------------------------------
# Costo de venta
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FilaCostoVenta:
    almacen: Almacen
    producto: Producto
    inicial_cantidad: Decimal
    inicial_valor: Decimal
    entradas_cantidad: Decimal
    entradas_valor: Decimal
    salidas_cantidad: Decimal
    salidas_valor: Decimal
    final_cantidad: Decimal
    final_valor: Decimal

    @property
    def costo_de_venta(self) -> Decimal:
        """Inventario inicial + entradas − inventario final (= lo que salió, valorizado)."""
        return self.inicial_valor + self.entradas_valor - self.final_valor


def costo_de_venta(
    empresa: Empresa, desde: date, hasta: date, almacen: Almacen | None
) -> list[FilaCostoVenta]:
    inicial = {
        (ln.almacen_id, ln.producto_id): ln
        for ln in _con_tope(_ultimas_lineas(empresa, desde - timedelta(days=1), almacen))
    }
    final = {
        (ln.almacen_id, ln.producto_id): ln
        for ln in _con_tope(_ultimas_lineas(empresa, hasta, almacen))
    }
    en_periodo = LineaMovimiento.objects.filter(empresa=empresa, fecha__gte=desde, fecha__lte=hasta)
    if almacen is not None:
        en_periodo = en_periodo.filter(almacen=almacen)
    entradas = Q(tipo=TipoMovimiento.ENTRADA)
    salidas = Q(tipo=TipoMovimiento.SALIDA)
    movidos = {
        (f["almacen_id"], f["producto_id"]): f
        for f in en_periodo.values("almacen_id", "producto_id").annotate(
            ec=Sum("cantidad", filter=entradas),
            ev=Sum("costo_total", filter=entradas),
            sc=Sum("cantidad", filter=salidas),
            sv=Sum("costo_total", filter=salidas),
        )
    }
    filas = []
    # Todo lo que tuvo saldo al inicio o se movió en el periodo tiene una línea hasta ``hasta``.
    for clave, ultima in final.items():
        previa = inicial.get(clave)
        mov = movidos.get(clave, {})
        fila = FilaCostoVenta(
            almacen=ultima.almacen,
            producto=ultima.producto,
            inicial_cantidad=previa.saldo_cantidad if previa else CERO,
            inicial_valor=previa.saldo_costo_total if previa else CERO,
            entradas_cantidad=mov.get("ec") or CERO,
            entradas_valor=mov.get("ev") or CERO,
            salidas_cantidad=mov.get("sc") or CERO,
            salidas_valor=mov.get("sv") or CERO,
            final_cantidad=ultima.saldo_cantidad,
            final_valor=ultima.saldo_costo_total,
        )
        if any(
            (
                fila.inicial_valor,
                fila.entradas_valor,
                fila.salidas_valor,
                fila.final_valor,
                fila.inicial_cantidad,
                fila.entradas_cantidad,
                fila.salidas_cantidad,
                fila.final_cantidad,
            )
        ):
            filas.append(fila)
    return sorted(filas, key=lambda f: (f.almacen.codigo, f.producto.nombre.lower(), f.producto.pk))


# ---------------------------------------------------------------------------
# Libro de movimientos (para el contador o para otro sistema)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MovimientosDatos:
    empresa: Empresa
    desde: date
    hasta: date
    movimientos: list[MovimientoInventario]


def movimientos(empresa: Empresa, desde: date, hasta: date) -> MovimientosDatos:
    lista = _con_tope(
        MovimientoInventario.objects.filter(empresa=empresa, fecha__gte=desde, fecha__lte=hasta)
        .select_related("almacen", "proveedor", "cliente")
        .prefetch_related(
            Prefetch(
                "lineas",
                queryset=LineaMovimiento.objects.select_related("producto__unidad")
                .prefetch_related("series_entrada", "series_salida")
                .order_by("orden", "id"),
            )
        )
        .order_by("fecha", "numero")
    )
    if sum(len(m.lineas.all()) for m in lista) > MAX_FILAS:
        raise ReporteDemasiadoGrande()
    return MovimientosDatos(empresa, desde, hasta, lista)


# ---------------------------------------------------------------------------
# Antigüedad del stock (PEPS, ver ``antiguedad``)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FilaAntiguedad:
    almacen: Almacen
    producto: Producto
    saldo: Decimal
    costo_unitario: Decimal
    tramos: list[Decimal]  # unidades en 0-30, 31-60, 61-90, 91-180 y más de 180 días
    mas_antigua: date | None
    dias: int | None
    unidades_antiguas: Decimal  # las que pasan el umbral configurado
    sin_fecha: Decimal  # saldo que el Kardex no explica

    @property
    def valor_antiguo(self) -> Decimal:
        """Lo antiguo, al costo promedio del almacén (el costeo no cambia)."""
        return (self.unidades_antiguas * self.costo_unitario).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class AntiguedadDatos:
    umbral: int
    hoy: date
    filas: list[FilaAntiguedad]


def antiguedad_del_stock(
    empresa: Empresa,
    almacen: Almacen | None,
    categoria: int | None = None,
    marca: int | None = None,
    solo_antiguo: bool = False,
) -> AntiguedadDatos:
    """Stock de la empresa con su antigüedad, lo más viejo primero."""
    from django.utils import timezone

    umbral = servicio_antiguedad.dias_para_considerar_antiguo(empresa.pk)
    hoy = timezone.localdate()
    ids = None
    if categoria or marca:
        productos = Producto.objects.sin_ambito().filter(organizacion_id=empresa.organizacion_id)
        if categoria:
            productos = productos.filter(categoria_id=categoria)
        if marca:
            productos = productos.filter(marca_id=marca)
        ids = list(productos.values_list("pk", flat=True))
    calculadas = servicio_antiguedad.capas_de(
        empresa.pk, producto_ids=ids, almacen_ids=[almacen.pk] if almacen else None
    )
    if not calculadas:
        return AntiguedadDatos(umbral, hoy, [])
    costos = {
        (a, p): c
        for a, p, c in SaldoStock.objects.sin_ambito()
        .filter(empresa=empresa, producto_id__in={x.producto_id for x in calculadas})
        .values_list("almacen_id", "producto_id", "costo_unitario")
    }
    por_producto = {
        p.pk: p
        for p in Producto.objects.sin_ambito()
        .select_related("unidad")
        .filter(pk__in={x.producto_id for x in calculadas})
    }
    por_almacen = {
        a.pk: a
        for a in Almacen.objects.sin_ambito().filter(
            pk__in={x.almacen_id for x in calculadas}, empresa=empresa
        )
    }
    filas = []
    for a in calculadas:
        antiguas = a.unidades_con_mas_de(umbral, hoy)
        if solo_antiguo and antiguas <= CERO:
            continue
        filas.append(
            FilaAntiguedad(
                almacen=por_almacen[a.almacen_id],
                producto=por_producto[a.producto_id],
                saldo=a.saldo,
                costo_unitario=costos.get((a.almacen_id, a.producto_id), CERO),
                tramos=a.por_tramos(hoy),
                mas_antigua=a.mas_antigua(),
                dias=a.dias_de_la_mas_antigua(hoy),
                unidades_antiguas=antiguas,
                sin_fecha=a.sin_fecha,
            )
        )
    filas.sort(key=lambda f: (-f.unidades_antiguas, -(f.dias or 0), f.producto.nombre.lower()))
    return AntiguedadDatos(umbral, hoy, filas[:MAX_FILAS])
