"""Precios de venta: de dónde sale cada precio y hasta cuánto se puede bajar. Sin IGV.

El precio de lista es la base; el IGV se suma encima. El vendedor puede SUBIR el precio libremente
y puede BAJARLO hasta el mínimo de la línea:

* El mínimo es el menor de los precios configurados en las listas de descuento y técnico del
  producto. Si no tiene ninguno, el mínimo es su costo de compra. Nunca baja del costo.
* Si el producto no tiene descuento posible (sin esas listas y sin costo), el mínimo es el
  precio de lista: no se puede bajar.
* Con el permiso de un administrador se puede vender bajo el mínimo, pero jamás bajo el costo.
  Si la propia lista ya está por debajo del costo (un dato mal cargado), el precio de lista
  siempre se puede vender.

Las reglas son funciones puras (sin base de datos) y todo se compara en una misma moneda.
"""

from dataclasses import dataclass
from decimal import Decimal

from apps.inventario.costeo import a_seis
from apps.mantenimiento.models import EstadoRegistro, ListaPrecio, PrecioProducto, UsoLista

CERO = Decimal("0")

OK = "OK"
BAJO_MINIMO = "BAJO_MINIMO"  # bajo el mínimo, pero no bajo el costo: requiere permiso
BAJO_COSTO = "BAJO_COSTO"  # bajo el costo: no se puede vender


def precio_minimo(
    *,
    precio_lista: Decimal,
    descuento: Decimal | None,
    tecnico: Decimal | None,
    costo: Decimal,
) -> Decimal:
    """Hasta cuánto puede bajar el precio sin permiso especial."""
    configurados = [p for p in (descuento, tecnico) if p is not None and p > 0]
    if configurados:
        base = min(configurados)
    elif costo > 0:
        base = costo
    else:
        base = precio_lista
    return min(precio_lista, max(base, costo))


def precio_absoluto(*, precio_lista: Decimal, costo: Decimal) -> Decimal:
    """Lo más bajo que se puede vender aun con permiso: el costo (o la lista, si ya es menor)."""
    return min(precio_lista, costo)


def evaluar_precio(precio: Decimal, *, minimo: Decimal, absoluto: Decimal) -> str:
    if precio < absoluto:
        return BAJO_COSTO
    if precio < minimo:
        return BAJO_MINIMO
    return OK


def a_moneda(monto_soles: Decimal, moneda: str, tipo_cambio: Decimal) -> Decimal:
    """Un monto en soles expresado en la moneda de la venta (soles por dólar)."""
    return monto_soles if moneda == "PEN" else a_seis(monto_soles / tipo_cambio)


@dataclass(frozen=True, slots=True)
class ListasDeVenta:
    """Las listas de precios de la organización según su uso."""

    por_id: dict[int, ListaPrecio]
    principal: ListaPrecio | None

    def de_uso(self, *usos: str) -> list[ListaPrecio]:
        return [lista for lista in self.por_id.values() if lista.uso in usos]


def cargar_listas(organizacion_id: int) -> ListasDeVenta:
    listas = {
        lista.pk: lista
        for lista in ListaPrecio.objects.sin_ambito().filter(
            organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO
        )
    }
    principal = next((lista for lista in listas.values() if lista.es_principal), None)
    return ListasDeVenta(listas, principal)


def precios_de(producto_ids: list[int]) -> dict[int, dict[int, Decimal]]:
    """``{producto: {lista: precio}}`` en soles, sin IGV, por unidad base."""
    filas = PrecioProducto.objects.sin_ambito().filter(producto_id__in=producto_ids)
    resultado: dict[int, dict[int, Decimal]] = {}
    for fila in filas:
        resultado.setdefault(fila.producto_id, {})[fila.lista_id] = fila.precio
    return resultado


def _menor_de_uso(listas: ListasDeVenta, precios: dict[int, Decimal], uso: str) -> Decimal | None:
    valores = [precios[lista.pk] for lista in listas.de_uso(uso) if precios.get(lista.pk, CERO) > 0]
    return min(valores) if valores else None


def minimo_del_producto(
    listas: ListasDeVenta,
    precios: dict[int, Decimal],
    *,
    precio_lista: Decimal,
    costo: Decimal,
) -> tuple[Decimal, bool]:
    """``(mínimo en soles, oculto)``; «oculto» si lo fija el costo (no se muestra al vendedor)."""
    descuento = _menor_de_uso(listas, precios, UsoLista.DESCUENTO)
    tecnico = _menor_de_uso(listas, precios, UsoLista.TECNICO)
    minimo = precio_minimo(
        precio_lista=precio_lista, descuento=descuento, tecnico=tecnico, costo=costo
    )
    de_listas = [p for p in (descuento, tecnico) if p is not None]
    fijado_por_listas = bool(de_listas) and min(de_listas) > costo
    return minimo, minimo < precio_lista and not fijado_por_listas
