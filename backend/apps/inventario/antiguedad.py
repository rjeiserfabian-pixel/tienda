"""Antigüedad del stock: de qué fecha es lo que hay hoy en cada almacén (método PEPS).

NO cambia el costeo: el Kardex sigue en costo promedio ponderado. Esto solo responde «¿cuánto de lo
que tengo lleva mucho tiempo guardado?» para despachar primero lo más antiguo.

Se calcula SIN tablas nuevas, a partir de las líneas del Kardex: se recorren las entradas y salidas
de cada producto en orden cronológico y cada salida consume primero las unidades de la entrada
más antigua. Lo que queda son las «capas»: (fecha de ingreso, cantidad).

Reglas, para no inventar nada:

* Un movimiento anulado y su extorno se ignoran juntos (el efecto neto es cero).
* Un traspaso entre almacenes de la MISMA empresa conserva la antigüedad: lo que sale con su fecha
  entra al destino con esa misma fecha.
* Un traslado o venta interna entre EMPRESAS distintas no se puede seguir (son Kardex separados):
  para la empresa que recibe, la mercadería cuenta desde la fecha del traslado.
* Una devolución de un cliente o un ajuste de entrada cuentan desde su propia fecha.
* Una salida (venta, ajuste, merma, devolución a un proveedor…) consume lo más antiguo; no se sabe
  de qué lote física salió cada unidad, así que es el supuesto PEPS.
* Si al final las capas no suman lo mismo que el saldo real, la diferencia se informa
  (``descuadre``) y nunca se oculta: si sobran capas se descuenta de las más antiguas; si faltan, lo
  que falta se muestra aparte como «sin fecha».
"""

import bisect
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.inventario.models import (
    LineaMovimiento,
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    TipoMovimiento,
)
from apps.organizacion.models import ConfiguracionEmpresa

CERO = Decimal("0")
DIAS_POR_DEFECTO = 90
TRAMOS = ((0, 30), (31, 60), (61, 90), (91, 180), (181, None))
LOTE_PRODUCTOS = 300  # productos que se leen del Kardex por consulta


@dataclass(frozen=True, slots=True)
class Capa:
    """Unidades que ingresaron el mismo día y siguen en el almacén."""

    fecha: date
    cantidad: Decimal


@dataclass(slots=True)
class Antiguedad:
    """Lo que hay hoy de un producto en un almacén, ordenado de lo más antiguo a lo más nuevo."""

    almacen_id: int
    producto_id: int
    saldo: Decimal
    capas: list[Capa] = field(default_factory=list)
    sin_fecha: Decimal = CERO  # saldo que el Kardex no logró explicar
    descuadre: Decimal = CERO  # capas calculadas menos saldo real (0 = todo cuadra)

    def mas_antigua(self) -> date | None:
        return self.capas[0].fecha if self.capas else None

    def dias_de_la_mas_antigua(self, hoy: date | None = None) -> int | None:
        fecha = self.mas_antigua()
        return None if fecha is None else ((hoy or timezone.localdate()) - fecha).days

    def unidades_con_mas_de(self, dias: int, hoy: date | None = None) -> Decimal:
        """Unidades que llevan MÁS de ``dias`` días en el almacén."""
        limite = hoy or timezone.localdate()
        return sum((c.cantidad for c in self.capas if (limite - c.fecha).days > dias), CERO)

    def por_tramos(self, hoy: date | None = None) -> list[Decimal]:
        """Unidades en cada tramo de días (ver ``TRAMOS``)."""
        limite = hoy or timezone.localdate()
        cubos = [CERO] * len(TRAMOS)
        for capa in self.capas:
            edad = (limite - capa.fecha).days
            for i, (desde, hasta) in enumerate(TRAMOS):
                if edad >= desde and (hasta is None or edad <= hasta):
                    cubos[i] += capa.cantidad
                    break
        return cubos


def dias_para_considerar_antiguo(empresa_id: int) -> int:
    """Días a partir de los cuales el stock se considera antiguo (configurable por empresa)."""
    dias = (
        ConfiguracionEmpresa.objects.sin_ambito()
        .filter(empresa_id=empresa_id)
        .values_list("dias_stock_antiguo", flat=True)
        .first()
    )
    return dias or DIAS_POR_DEFECTO


# ---------------------------------------------------------------------------
# Cálculo de las capas
# ---------------------------------------------------------------------------
class _Capas:
    """Capas de un almacén, siempre ordenadas por fecha de ingreso."""

    def __init__(self) -> None:
        self.fechas: list[date] = []
        self.cantidades: list[Decimal] = []

    def agregar(self, fecha: date, cantidad: Decimal) -> None:
        # Si ya hay una capa del mismo día se suma (a la derecha de las anteriores de ese día).
        i = bisect.bisect_left(self.fechas, fecha)
        if i < len(self.fechas) and self.fechas[i] == fecha:
            self.cantidades[i] += cantidad
            return
        self.fechas.insert(i, fecha)
        self.cantidades.insert(i, cantidad)

    def sacar(self, cantidad: Decimal) -> list[tuple[date, Decimal]]:
        """Consume ``cantidad`` de lo más antiguo. Devuelve lo que salió (con su fecha)."""
        salio: list[tuple[date, Decimal]] = []
        falta = cantidad
        while falta > CERO and self.fechas:
            disponible = self.cantidades[0]
            tomar = min(disponible, falta)
            salio.append((self.fechas[0], tomar))
            falta -= tomar
            if tomar == disponible:
                del self.fechas[0]
                del self.cantidades[0]
            else:
                self.cantidades[0] = disponible - tomar
        return salio

    def total(self) -> Decimal:
        return sum(self.cantidades, CERO)

    def lista(self) -> list[Capa]:
        return [Capa(f, c) for f, c in zip(self.fechas, self.cantidades, strict=True)]


def _lineas_del_kardex(empresa_id: int, producto_ids: list[int]):
    """Líneas vigentes (sin anuladas ni extornos) de esos productos, en orden cronológico."""
    return (
        LineaMovimiento.objects.sin_ambito()
        .filter(
            empresa_id=empresa_id,
            producto_id__in=producto_ids,
            movimiento__estado=MovimientoInventario.Estado.EMITIDO,
            movimiento__extorna__isnull=True,
        )
        .order_by("producto_id", "fecha", "movimiento_id", "orden", "id")
        .values_list(
            "producto_id",
            "almacen_id",
            "fecha",
            "tipo",
            "cantidad",
            "movimiento__origen",
            "movimiento__traspaso_id",
        )
    )


def _capas_de_producto(eventos: list[tuple]) -> dict[int, _Capas]:
    """Recorre los eventos de UN producto (todos sus almacenes) y devuelve las capas por almacén."""
    por_almacen: dict[int, _Capas] = defaultdict(_Capas)
    # Traspasos dentro de la empresa: a qué almacén llegó cada uno (se reparte con la salida).
    destino: dict = {}
    con_salida: set = set()
    for _, almacen, _, tipo, cantidad, origen, traspaso in eventos:
        if origen != OrigenMovimiento.TRASPASO or traspaso is None:
            continue
        if tipo == TipoMovimiento.ENTRADA:
            destino.setdefault(traspaso, []).append((almacen, cantidad))
        else:
            con_salida.add(traspaso)
    for _, almacen, fecha, tipo, cantidad, origen, traspaso in eventos:
        es_traspaso = origen == OrigenMovimiento.TRASPASO and traspaso is not None
        if tipo == TipoMovimiento.ENTRADA:
            if es_traspaso and traspaso in con_salida:
                continue  # la antigüedad llega con la salida de su pareja
            por_almacen[almacen].agregar(fecha, cantidad)
            continue
        salio = por_almacen[almacen].sacar(cantidad)
        if es_traspaso and traspaso in destino:
            llegadas = destino.pop(traspaso)
            # Lo que salió se reparte en los destinos, de lo más antiguo a lo más nuevo.
            pendiente = list(salio)
            for almacen_destino, pedida in llegadas:
                falta = pedida
                while falta > CERO and pendiente:
                    f, c = pendiente[0]
                    tomar = min(c, falta)
                    por_almacen[almacen_destino].agregar(f, tomar)
                    falta -= tomar
                    if tomar == c:
                        pendiente.pop(0)
                    else:
                        pendiente[0] = (f, c - tomar)
                if falta > CERO:
                    # Salió menos de lo que dice llegar (datos incompletos): cuenta desde hoy.
                    por_almacen[almacen_destino].agregar(fecha, falta)
    return por_almacen


def capas_de(
    empresa_id: int,
    *,
    producto_ids: Iterable[int] | None = None,
    almacen_ids: Iterable[int] | None = None,
) -> list[Antiguedad]:
    """Antigüedad del stock actual de una empresa (solo lo que tiene saldo mayor que cero).

    Sin ``producto_ids`` calcula todos los productos con stock. Se lee el Kardex por lotes de
    productos (una consulta por lote), nunca un producto a la vez.
    """
    saldos = SaldoStock.objects.sin_ambito().filter(empresa_id=empresa_id, cantidad__gt=0)
    if producto_ids is not None:
        saldos = saldos.filter(producto_id__in=list(producto_ids))
    if almacen_ids is not None:
        saldos = saldos.filter(almacen_id__in=list(almacen_ids))
    filas = list(saldos.values_list("producto_id", "almacen_id", "cantidad"))
    por_producto: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for producto, almacen, cantidad in filas:
        por_producto[producto][almacen] = cantidad

    resultado: list[Antiguedad] = []
    productos = sorted(por_producto)
    for i in range(0, len(productos), LOTE_PRODUCTOS):
        lote = productos[i : i + LOTE_PRODUCTOS]
        eventos: dict[int, list[tuple]] = defaultdict(list)
        for evento in _lineas_del_kardex(empresa_id, lote):
            eventos[evento[0]].append(evento)
        for producto in lote:
            calculadas = _capas_de_producto(eventos.get(producto, []))
            for almacen, saldo in por_producto[producto].items():
                resultado.append(_ajustar(producto, almacen, saldo, calculadas.get(almacen)))
    return resultado


def _ajustar(producto: int, almacen: int, saldo: Decimal, capas: _Capas | None) -> Antiguedad:
    """Compara las capas con el saldo real: si no cuadran, lo informa y no lo esconde."""
    capas = capas or _Capas()
    total = capas.total()
    descuadre = total - saldo
    sin_fecha = CERO
    if descuadre > CERO:
        capas.sacar(descuadre)  # sobran capas: se descuentan las más antiguas (supuesto PEPS)
    elif descuadre < CERO:
        sin_fecha = -descuadre
    return Antiguedad(
        almacen_id=almacen,
        producto_id=producto,
        saldo=saldo,
        capas=capas.lista(),
        sin_fecha=sin_fecha,
        descuadre=descuadre,
    )


# ---------------------------------------------------------------------------
# Resumen para el Inicio y aviso al vender
# ---------------------------------------------------------------------------
SEGUNDOS_RESUMEN = 600


def resumen_de_empresa(empresa_id: int) -> dict:
    """Cuántos productos, unidades y qué valor (al costo promedio) pasan del umbral.

    Se guarda 10 minutos por empresa: leer el Kardex de todo el stock no se repite en cada visita.
    """
    clave = f"inventario:antiguo:{empresa_id}"
    guardado = cache.get(clave)
    if guardado is not None:
        return guardado
    umbral = dias_para_considerar_antiguo(empresa_id)
    hoy = timezone.localdate()
    calculadas = capas_de(empresa_id)
    costos = {
        (a, p): c
        for a, p, c in SaldoStock.objects.sin_ambito()
        .filter(empresa_id=empresa_id, cantidad__gt=0)
        .values_list("almacen_id", "producto_id", "costo_unitario")
    }
    productos: set[int] = set()
    unidades = valor = CERO
    for a in calculadas:
        antiguas = a.unidades_con_mas_de(umbral, hoy)
        if antiguas > CERO:
            productos.add(a.producto_id)
            unidades += antiguas
            valor += antiguas * costos.get((a.almacen_id, a.producto_id), CERO)
    datos = {
        "umbral_dias": umbral,
        "productos": len(productos),
        "unidades": unidades,
        "valor_costo_soles": valor.quantize(Decimal("0.01")),
    }
    cache.set(clave, datos, SEGUNDOS_RESUMEN)
    return datos


def aviso_de_venta(items: list[tuple[int, int, int]]) -> list[dict]:
    """Para el carrito del mostrador: por cada (empresa, almacén, producto) con stock antiguo,
    desde cuándo ingresó lo más viejo. Solo trae los que pasan el umbral (el resto no avisa)."""
    por_empresa: dict[int, set[int]] = defaultdict(set)
    for empresa, _, producto in items:
        por_empresa[empresa].add(producto)
    hoy = timezone.localdate()
    avisos = []
    for empresa, productos in por_empresa.items():
        umbral = dias_para_considerar_antiguo(empresa)
        pedidos = {(a, p) for e, a, p in items if e == empresa}
        for a in capas_de(empresa, producto_ids=productos):
            if (a.almacen_id, a.producto_id) not in pedidos:
                continue
            antiguas = a.unidades_con_mas_de(umbral, hoy)
            if antiguas <= CERO:
                continue
            avisos.append(
                {
                    "empresa": empresa,
                    "almacen": a.almacen_id,
                    "producto": a.producto_id,
                    "ingreso": a.mas_antigua().isoformat(),
                    "dias": a.dias_de_la_mas_antigua(hoy),
                    "unidades_antiguas": antiguas,
                    "umbral_dias": umbral,
                }
            )
    return avisos
