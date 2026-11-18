"""Cupones de descuento de la tienda.

Reglas (decididas con el negocio):

* Un cupón por pedido. NO se combina con productos en oferta, salvo que el cupón lo permita.
* El descuento se REPARTE entre los productos a los que aplica (a todos la misma proporción) y se
  nota en el precio de cada línea; así el IGV y los totales del comprobante salen correctos.
* Un producto nunca baja de su precio mínimo (el mismo que usan Ventas y las ofertas): si el cupón
  llegara más abajo, se aplica hasta ese límite y se avisa.
* Los cupones de monto y de porcentaje se calculan sobre lo que paga el cliente (con IGV).
* El uso se aparta al crear el pedido, se consume al pagar y se libera si el pedido vence o se
  cancela. Los códigos no se pueden adivinar a fuerza bruta: hay un límite de intentos fallidos.
"""

import logging
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .exceptions import CuponBloqueado, CuponInvalido
from .models import Cupon, PedidoTienda, UsoCupon

logger = logging.getLogger(__name__)

CERO = Decimal("0")
CENTIMO = Decimal("0.01")
CODIGO = re.compile(r"^[A-Z0-9_-]{3,30}$")
MAX_FALLOS = 8
VENTANA_FALLOS = 15 * 60  # segundos
ESTADOS_SIN_COMPRA = (
    PedidoTienda.Estado.PENDIENTE_PAGO,
    PedidoTienda.Estado.CANCELADO,
    PedidoTienda.Estado.EXPIRADO,
)


def _q(valor: Decimal) -> Decimal:
    return valor.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def normalizar_codigo(texto: str) -> str:
    codigo = (texto or "").strip().upper().replace(" ", "")
    if not CODIGO.match(codigo):
        raise CuponInvalido("Ese código de cupón no es válido.")
    return codigo


# --- límite de intentos fallidos ---------------------------------------------------------
def _clave_fallos(quien) -> str:
    return f"tienda:cupon:fallos:{quien}"


def exigir_sin_bloqueo(quien) -> None:
    if (cache.get(_clave_fallos(quien)) or 0) >= MAX_FALLOS:
        raise CuponBloqueado()


def anotar_fallo(quien) -> None:
    clave = _clave_fallos(quien)
    try:
        cache.add(clave, 0, VENTANA_FALLOS)
        cache.incr(clave)
    except ValueError:  # la clave venció entre las dos llamadas
        cache.set(clave, 1, VENTANA_FALLOS)


# --- revisión ----------------------------------------------------------------------------
def obtener(organizacion_id: int, codigo: str) -> Cupon:
    cupon = (
        Cupon.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, codigo__iexact=normalizar_codigo(codigo))
        .first()
    )
    if cupon is None:
        raise CuponInvalido("No encontramos ese cupón.")
    return cupon


def usos_vigentes(cupon: Cupon, cuenta=None) -> int:
    usos = UsoCupon.objects.sin_ambito().filter(
        cupon=cupon, estado__in=[UsoCupon.Estado.RESERVADO, UsoCupon.Estado.CONSUMIDO]
    )
    if cuenta is not None:
        usos = usos.filter(cuenta=cuenta)
    return usos.count()


def _ya_compro(cuenta) -> bool:
    return (
        PedidoTienda.objects.sin_ambito()
        .filter(cuenta=cuenta)
        .exclude(estado__in=ESTADOS_SIN_COMPRA)
        .exists()
    )


def revisar(cupon: Cupon, cuenta, *, productos_total: Decimal, ahora=None) -> None:
    """Lanza ``CuponInvalido`` con un mensaje claro si el cupón no se puede usar ahora."""
    ahora = ahora or timezone.now()
    if cuenta is None:
        raise CuponInvalido("Ingresa a tu cuenta para usar un cupón.")
    if not cupon.activo or (cupon.inicia_en and ahora < cupon.inicia_en):
        raise CuponInvalido("Este cupón no está disponible.")
    if cupon.termina_en and ahora > cupon.termina_en:
        raise CuponInvalido("Este cupón ya venció.")
    if cupon.usos_maximos is not None and usos_vigentes(cupon) >= cupon.usos_maximos:
        raise CuponInvalido("Este cupón ya se agotó.")
    if usos_vigentes(cupon, cuenta) >= max(cupon.usos_por_cliente, 1):
        raise CuponInvalido("Ya usaste este cupón.")
    if cupon.solo_primera_compra and _ya_compro(cuenta):
        raise CuponInvalido("Este cupón es solo para tu primera compra.")
    if productos_total < cupon.compra_minima:
        raise CuponInvalido(
            f"Este cupón se usa en compras de S/ {cupon.compra_minima:,.2f} o más en productos."
        )


# --- reparto -----------------------------------------------------------------------------
@dataclass(slots=True)
class Reparto:
    """Qué fracción del precio se descuenta en cada línea (índice de línea → fracción 0..1)."""

    fracciones: dict[int, Decimal] = field(default_factory=dict)
    descuento_ideal: Decimal = CERO
    base_elegible: Decimal = CERO


class _Alcance:
    """Los productos a los que aplica un cupón (se consulta una sola vez por cálculo)."""

    def __init__(self, cupon: Cupon):
        self.alcance = cupon.alcance
        self.categorias = set(cupon.categorias.values_list("pk", flat=True))
        self.marcas = set(cupon.marcas.values_list("pk", flat=True))
        self.productos = set(cupon.productos.values_list("pk", flat=True))

    def aplica(self, producto) -> bool:
        if self.alcance == Cupon.Alcance.TODO:
            return True
        if self.alcance == Cupon.Alcance.CATEGORIAS:
            return producto.categoria_id in self.categorias
        if self.alcance == Cupon.Alcance.MARCAS:
            return producto.marca_id in self.marcas
        return producto.pk in self.productos


def repartir(cupon: Cupon, lineas: list[dict], *, en_oferta, minimo_de) -> Reparto:
    """Reparte el descuento entre las líneas elegibles.

    ``lineas``: las del pedido (``producto``, ``base`` y ``total`` con IGV, ``cantidad``,
    ``es_envio``). ``en_oferta(producto)`` dice si el producto está en oferta;
    ``minimo_de(producto)`` da su precio mínimo por unidad (sin IGV).
    """
    alcance = _Alcance(cupon)
    elegibles = [
        i
        for i, ln in enumerate(lineas)
        if not ln["es_envio"]
        and alcance.aplica(ln["producto"])
        and (cupon.incluye_ofertas or not en_oferta(ln["producto"]))
    ]
    base = sum((lineas[i]["total"] for i in elegibles), CERO)
    if not elegibles or base <= 0:
        raise CuponInvalido(
            "Este cupón no aplica a los productos de tu carrito"
            + ("" if cupon.incluye_ofertas else " (los productos en oferta no entran)")
            + "."
        )
    if cupon.tipo == Cupon.Tipo.PORCENTAJE:
        descuento = base * cupon.valor / Decimal(100)
        if cupon.tope_descuento is not None:
            descuento = min(descuento, cupon.tope_descuento)
    else:  # MONTO
        descuento = min(cupon.valor, base)
    descuento = _q(descuento)
    fraccion = descuento / base
    reparto = Reparto(descuento_ideal=descuento, base_elegible=base)
    for i in elegibles:
        ln = lineas[i]
        unitario = ln["base"] / ln["cantidad"]
        tope = CERO
        if unitario > 0:
            tope = max(Decimal(1) - minimo_de(ln["producto"]) / unitario, CERO)
        reparto.fracciones[i] = min(fraccion, tope)
    return reparto


# --- uso del cupón -----------------------------------------------------------------------
@transaction.atomic
def reservar(pedido: PedidoTienda, cupon: Cupon, cuenta, monto: Decimal) -> UsoCupon:
    """Aparta el uso al crear el pedido. Bloquea el cupón: dos pedidos a la vez no se pasan del
    límite de usos."""
    bloqueado = Cupon.objects.sin_ambito().select_for_update().get(pk=cupon.pk)
    if bloqueado.usos_maximos is not None and usos_vigentes(bloqueado) >= bloqueado.usos_maximos:
        raise CuponInvalido("Este cupón ya se agotó.")
    if usos_vigentes(bloqueado, cuenta) >= max(bloqueado.usos_por_cliente, 1):
        raise CuponInvalido("Ya usaste este cupón.")
    return UsoCupon.objects.sin_ambito().create(
        organizacion_id=pedido.organizacion_id,
        cupon=bloqueado,
        pedido=pedido,
        cuenta=cuenta,
        monto=monto,
    )


def consumir(pedido: PedidoTienda) -> None:
    """El cliente pagó: el uso queda consumido (también si el pedido ya había vencido)."""
    UsoCupon.objects.sin_ambito().filter(
        pedido=pedido, estado__in=[UsoCupon.Estado.RESERVADO, UsoCupon.Estado.LIBERADO]
    ).update(estado=UsoCupon.Estado.CONSUMIDO)


def liberar(pedido: PedidoTienda) -> None:
    UsoCupon.objects.sin_ambito().filter(pedido=pedido, estado=UsoCupon.Estado.RESERVADO).update(
        estado=UsoCupon.Estado.LIBERADO
    )
