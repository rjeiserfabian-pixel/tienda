"""Entrega de los pedidos de la tienda: zona y costo del envío, y puntos de recojo con stock.

* ENVÍO: el distrito de entrega decide la zona (la cobertura más específica gana: distrito, luego
  provincia, luego departamento). El costo sale del peso total del pedido en los tramos de la zona.
  Una zona de ``DESTINO`` (agencia) no cobra envío en la compra: el cliente paga al recibir.
* RECOJO: cada punto ofrece solo lo que hay en SUS almacenes (que además abastezcan la tienda).
  El cliente solo ve los puntos que tienen TODO el pedido.

Nada de lo que sale de aquí es un cobro definitivo: la Fase 5 lo recalcula al crear el pedido.
"""

import math
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from apps.inventario.models import SaldoStock
from apps.mantenimiento.models import Almacen, EstadoRegistro, TipoProducto

from . import reservas
from .catalogo import Contexto
from .models import CoberturaZona, PuntoRecojo, TarifaZona, ZonaEnvio

CENTIMO = Decimal("0.01")


def _dinero(valor: Decimal) -> str:
    return format(valor.quantize(CENTIMO, rounding=ROUND_HALF_UP), "f")


def peso_de(producto, ctx: Contexto) -> Decimal:
    """Peso en kg de un producto para el envío (el de la ficha o el de la tienda por defecto)."""
    if producto.tipo == TipoProducto.SERVICIO:
        return Decimal("0")
    return producto.peso_kg if producto.peso_kg else ctx.peso_defecto_kg


def peso_total(lineas, ctx: Contexto) -> Decimal:
    """``lineas``: lista de (producto, cantidad)."""
    return sum((peso_de(p, ctx) * c for p, c in lineas), Decimal("0"))


# ---------------------------------------------------------------------------
# Envío a domicilio
# ---------------------------------------------------------------------------
def zona_para(organizacion_id: int, ubigeo: str) -> ZonaEnvio | None:
    """La zona activa que cubre ese distrito (la cobertura más específica gana)."""
    if len(ubigeo or "") != 6:
        return None
    prefijos = [ubigeo, ubigeo[:4], ubigeo[:2]]
    cobertura = {
        c.prefijo: c.zona
        for c in CoberturaZona.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, prefijo__in=prefijos, zona__activa=True)
        .select_related("zona")
        if c.zona.eliminado_en is None
    }
    for prefijo in prefijos:
        if prefijo in cobertura:
            return cobertura[prefijo]
    return None


def costo_por_peso(zona: ZonaEnvio, peso: Decimal) -> Decimal | None:
    """Costo del envío para ese peso, o ``None`` si la zona no atiende un peso tan grande."""
    # Sin sesión (tienda pública): se consulta explícitamente, sin el aislamiento por sesión.
    tramos = list(TarifaZona.objects.sin_ambito().filter(zona=zona).order_by("hasta_kg"))
    if not tramos:
        return None
    for tramo in tramos:
        if peso <= tramo.hasta_kg:
            return tramo.costo
    if zona.kg_adicional is None:
        return None
    ultimo = tramos[-1]
    extra = Decimal(math.ceil(peso - ultimo.hasta_kg))
    return ultimo.costo + extra * zona.kg_adicional


def cotizar_envio(ctx: Contexto, *, ubigeo: str, peso: Decimal, subtotal: Decimal) -> dict:
    """Si se puede enviar a ese distrito y cuánto cuesta. Siempre devuelve un diccionario."""
    if not ctx.permite_envio:
        return _sin_envio("La tienda no ofrece envío a domicilio por ahora.")
    zona = zona_para(ctx.organizacion_id, ubigeo)
    if zona is None:
        return _sin_envio("Todavía no llegamos a ese distrito. Puedes recoger tu pedido en tienda.")
    base = {
        "disponible": True,
        "zona": {"id": zona.pk, "nombre": zona.nombre},
        "modalidad": zona.modalidad,
        "paga_en_destino": zona.modalidad == ZonaEnvio.Modalidad.DESTINO,
        "plazo": zona.plazo,
        "detalle": zona.detalle,
        "peso_kg": format(peso.quantize(CENTIMO), "f"),
        "motivo": None,
        "gratis": False,
    }
    if zona.modalidad == ZonaEnvio.Modalidad.DESTINO:
        return {**base, "costo": "0.00"}
    costo = costo_por_peso(zona, peso)
    if costo is None:
        return _sin_envio(
            "Tu pedido pesa más de lo que enviamos por este medio. Escríbenos para coordinarlo.",
            zona=zona,
        )
    gratis = zona.envio_gratis_desde is not None and subtotal >= zona.envio_gratis_desde
    return {**base, "costo": "0.00" if gratis else _dinero(costo), "gratis": gratis}


def _sin_envio(motivo: str, zona: ZonaEnvio | None = None) -> dict:
    return {
        "disponible": False,
        "motivo": motivo,
        "zona": {"id": zona.pk, "nombre": zona.nombre} if zona else None,
        "modalidad": None,
        "paga_en_destino": False,
        "plazo": "",
        "detalle": "",
        "costo": "0.00",
        "gratis": False,
        "peso_kg": None,
    }


# ---------------------------------------------------------------------------
# Recojo en tienda
# ---------------------------------------------------------------------------
def puntos_de_recojo(ctx: Contexto, lineas) -> list[dict]:
    """Los puntos activos y si cada uno tiene TODO el pedido (``lineas``: (producto, cantidad))."""
    if not ctx.permite_recojo:
        return []
    puntos = list(
        PuntoRecojo.objects.sin_ambito()
        .filter(organizacion_id=ctx.organizacion_id, activo=True)
        .order_by("orden", "id")
    )
    if not puntos:
        return []
    # ``ctx.almacen_ids`` ya son solo almacenes activos que abastecen la tienda.
    abastecen = set(ctx.almacen_ids)
    por_punto: dict[int, set[int]] = {p.pk: set() for p in puntos}
    enlaces = PuntoRecojo.almacenes.through.objects.filter(puntorecojo_id__in=list(por_punto))
    for punto_id, almacen_id in enlaces.values_list("puntorecojo_id", "almacen_id"):
        if almacen_id in abastecen:
            por_punto[punto_id].add(almacen_id)
    requeridas = [(p, c) for p, c in lineas if p.controla_stock and p.tipo != TipoProducto.SERVICIO]
    stock: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    todos = set().union(*por_punto.values()) if por_punto else set()
    if requeridas and todos:
        filas = (
            SaldoStock.objects.sin_ambito()
            .filter(producto_id__in=[p.pk for p, _ in requeridas], almacen_id__in=todos)
            .values("almacen_id", "producto_id")
            .annotate(total=Sum("cantidad"))
        )
        for fila in filas:
            stock[(fila["almacen_id"], fila["producto_id"])] += fila["total"]
        # Lo apartado para pedidos en pago no está a la venta.
        for clave, cantidad in reservas.apartado(todos, [p.pk for p, _ in requeridas]).items():
            stock[clave] -= cantidad
    salida = []
    for punto in puntos:
        almacenes = por_punto[punto.pk]
        faltan = [
            producto.pk
            for producto, cantidad in requeridas
            if sum((stock[(a, producto.pk)] for a in almacenes), Decimal("0")) < cantidad
        ]
        salida.append(
            {
                "id": punto.pk,
                "nombre": punto.nombre,
                "direccion": punto.direccion,
                "horario": punto.horario,
                "indicaciones": punto.indicaciones,
                "listo_en": punto.listo_en,
                "telefono": punto.telefono,
                "disponible": not faltan and (bool(almacenes) or not requeridas),
                "faltan": faltan,
            }
        )
    return salida


def almacenes_de_la_organizacion(organizacion_id: int):
    return Almacen.objects.sin_ambito().filter(
        empresa__organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO
    )
