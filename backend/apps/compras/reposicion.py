"""Reposición sugerida: qué pedir a los proveedores según el stock mínimo de cada producto.

Para un almacén se miran los productos con stock mínimo. Un producto necesita reposición cuando lo
que hay MÁS lo que ya viene en órdenes emitidas (pendiente de recibir) no pasa de su mínimo. Se
sugiere pedir hasta ``hasta`` veces el mínimo (por defecto el doble), redondeando hacia arriba a
unidades enteras. Cada producto se propone al proveedor de su compra vigente más reciente; los que
nunca se compraron quedan aparte, para que alguien decida a quién pedírselos.

Es solo una sugerencia: no crea nada. Las cantidades y los precios (el costo del catálogo) se
corrigen al armar la orden.
"""

import math
from decimal import Decimal

from django.db.models import F

from apps.inventario.models import SaldoStock
from apps.mantenimiento.models import Almacen, EstadoRegistro, Producto, TipoProducto
from apps.organizacion.models import Empresa

from .exceptions import OrdenCompraInvalida
from .models import Compra, LineaCompra, LineaOrdenCompra, OrdenCompra

CERO = Decimal("0")
HASTA_POR_DEFECTO = Decimal("2")
HASTA_MAXIMO = Decimal("10")


def _entero_arriba(valor: Decimal) -> Decimal:
    return Decimal(math.ceil(valor))


def _en_camino(empresa: Empresa, almacen: Almacen) -> dict[int, Decimal]:
    """Por producto, lo que falta recibir de órdenes emitidas para ese almacén, en unidad base."""
    lineas = LineaOrdenCompra.objects.filter(
        orden__empresa=empresa,
        orden__almacen=almacen,
        orden__estado__in=(OrdenCompra.Estado.EMITIDA, OrdenCompra.Estado.PARCIAL),
        cantidad_recibida__lt=F("cantidad"),
    )
    camino: dict[int, Decimal] = {}
    for ln in lineas:
        camino[ln.producto_id] = camino.get(ln.producto_id, CERO) + ln.pendiente * ln.factor
    return camino


def _ultimos_proveedores(empresa: Empresa, producto_ids: list[int]) -> dict[int, tuple]:
    """Por producto, el proveedor de su compra vigente más reciente y la fecha de esa compra."""
    lineas = (
        LineaCompra.objects.filter(
            compra__empresa=empresa,
            compra__estado=Compra.Estado.EMITIDO,
            producto_id__in=producto_ids,
        )
        .select_related("compra__proveedor")
        .order_by("producto_id", "-compra__fecha_emision", "-compra_id")
    )
    ultimos: dict[int, tuple] = {}
    for ln in lineas:
        ultimos.setdefault(ln.producto_id, (ln.compra.proveedor, ln.compra.fecha_emision))
    return ultimos


def reposicion_sugerida(
    empresa: Empresa, almacen: Almacen, hasta: Decimal = HASTA_POR_DEFECTO
) -> dict:
    """Los productos que conviene pedir para ese almacén, agrupados por proveedor."""
    if almacen.empresa_id != empresa.pk:
        raise OrdenCompraInvalida("El almacén no pertenece a la empresa.")
    if not isinstance(hasta, Decimal) or not hasta.is_finite() or not 1 <= hasta <= HASTA_MAXIMO:
        raise OrdenCompraInvalida(f"«Reponer hasta» es de 1 a {HASTA_MAXIMO:f} veces el mínimo.")

    productos = list(
        Producto.objects.filter(
            tipo=TipoProducto.BIEN,
            controla_stock=True,
            estado=EstadoRegistro.ACTIVO,
            stock_minimo__gt=0,
        ).select_related("unidad")
    )
    saldos = dict(
        SaldoStock.objects.filter(
            empresa=empresa, almacen=almacen, producto_id__in=[p.pk for p in productos]
        ).values_list("producto_id", "cantidad")
    )
    camino = _en_camino(empresa, almacen)

    necesitan = []
    for producto in productos:
        stock = saldos.get(producto.pk, CERO)
        viene = camino.get(producto.pk, CERO)
        if stock + viene > producto.stock_minimo:
            continue
        sugerido = _entero_arriba(producto.stock_minimo * hasta - stock - viene)
        if sugerido >= 1:
            necesitan.append((producto, stock, viene, sugerido))

    ultimos = _ultimos_proveedores(empresa, [p.pk for p, *_ in necesitan])
    grupos: dict[int | None, dict] = {}
    for producto, stock, viene, sugerido in sorted(necesitan, key=lambda t: t[0].nombre):
        proveedor, fecha = ultimos.get(producto.pk, (None, None))
        clave = proveedor.pk if proveedor else None
        grupo = grupos.setdefault(clave, {"proveedor": proveedor, "productos": []})
        grupo["productos"].append(
            {
                "producto": producto,
                "stock": stock,
                "minimo": producto.stock_minimo,
                "en_camino": viene,
                "sugerido": sugerido,
                "precio_estimado": producto.costo,
                "ultima_compra": fecha,
            }
        )
    # Primero los proveedores con nombre (por orden alfabético) y al final «sin proveedor habitual».
    ordenados = sorted(
        grupos.values(),
        key=lambda g: (g["proveedor"] is None, g["proveedor"].nombre if g["proveedor"] else ""),
    )
    return {
        "almacen": almacen,
        "hasta": hasta,
        "grupos": ordenados,
        "total_productos": len(necesitan),
    }
