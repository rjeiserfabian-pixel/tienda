"""Carrito y resumen de la compra de la tienda.

El navegador solo guarda QUÉ y CUÁNTO (ids y cantidades). Todo lo demás —nombre, foto, precio,
disponibilidad, peso, envío— lo decide siempre el servidor con lo vigente, así un precio o un stock
viejo guardado en el navegador no sirve para nada. El monto es el precio que se muestra en la
tienda (con IGV si así se configuró); el cobro definitivo lo recalcula la Fase 5 al crear el pedido.
"""

from decimal import ROUND_HALF_UP, Decimal

from apps.mantenimiento.models import TipoProducto

from . import catalogo, envios, series_pedido
from .catalogo import Contexto
from .exceptions import DatosInvalidos
from .models import CarritoCuenta, CuentaCliente

MAX_LINEAS = 50
MAX_CANTIDAD = 99
CENTIMO = Decimal("0.01")


def _dinero(valor: Decimal) -> str:
    return format(valor.quantize(CENTIMO, rounding=ROUND_HALF_UP), "f")


def normalizar(entradas) -> list[dict]:
    """Valida lo que manda el navegador: ids y cantidades enteras; suma los repetidos."""
    if not isinstance(entradas, list) or len(entradas) > MAX_LINEAS * 2:
        raise DatosInvalidos("El carrito no es válido.")
    acumulado: dict[int, int] = {}
    for fila in entradas:
        try:
            producto = int(fila["producto"])
            cantidad = int(fila["cantidad"])
        except (KeyError, TypeError, ValueError):
            raise DatosInvalidos("El carrito no es válido.") from None
        if producto < 1 or cantidad < 1:
            raise DatosInvalidos("El carrito no es válido.")
        acumulado[producto] = min(acumulado.get(producto, 0) + cantidad, MAX_CANTIDAD)
    if len(acumulado) > MAX_LINEAS:
        raise DatosInvalidos(f"El carrito admite hasta {MAX_LINEAS} productos distintos.")
    return [{"producto": p, "cantidad": c} for p, c in acumulado.items()]


def _linea(producto, cantidad: int, ctx: Contexto) -> dict:
    precios = catalogo._precios(producto, ctx)
    disp = catalogo._disponibilidad(producto, ctx)
    controla = producto.controla_stock and producto.tipo != TipoProducto.SERVICIO
    stock = int(producto.stock_web or 0) if controla else None
    if controla and producto.lleva_serie:
        # Cada unidad lleva su serie: solo se ofrece lo que tiene series en stock (la más antigua
        # se asigna sola al pagar).
        stock = min(stock, series_pedido.disponibles(ctx.almacen_ids, producto.pk))
    unitario = Decimal(precios["precio_mostrar"]) if precios["precio_mostrar"] else None
    problema = None
    if unitario is None:
        problema = "Este producto es solo por cotización: escríbenos para comprarlo."
    elif controla and stock < 1:
        problema = "Este producto se agotó."
    elif controla and cantidad > stock:
        problema = f"Solo quedan {stock} unidad(es) disponibles."
    return {
        "producto": producto.pk,
        "slug": producto.slug,
        "nombre": producto.nombre,
        "marca": producto.marca.nombre if producto.marca else None,
        "foto": catalogo.url_foto(producto.foto_principal_id, "mini")
        if producto.foto_principal_id
        else None,
        "cantidad": cantidad,
        "precio_unitario": precios["precio_mostrar"],
        "incluye_igv": precios["incluye_igv"],
        "subtotal": _dinero(unitario * cantidad) if unitario is not None else None,
        "disponibilidad": disp["disponibilidad"],
        "stock_maximo": stock if stock is None else min(stock, MAX_CANTIDAD),
        "problema": problema,
    }


def resolver(ctx: Contexto, entradas: list[dict]):
    """Devuelve (líneas para mostrar, pares (producto, cantidad)) con los datos vigentes.

    Los productos que ya no se venden (despublicados, inactivos, de otra organización) no
    aparecen: salen en ``quitados``, así el cliente sabe por qué cambió su carrito.
    """
    ids = [e["producto"] for e in entradas]
    vigentes = {p.pk: p for p in catalogo.productos_publicos(ctx).filter(pk__in=ids)}
    lineas, pares, quitados = [], [], []
    for entrada in entradas:
        producto = vigentes.get(entrada["producto"])
        if producto is None:
            quitados.append(entrada["producto"])
            continue
        lineas.append(_linea(producto, entrada["cantidad"], ctx))
        pares.append((producto, entrada["cantidad"]))
    return lineas, pares, quitados


def calcular(ctx: Contexto, entradas: list[dict]) -> dict:
    """Carrito con precios, disponibilidad y totales."""
    lineas, pares, quitados = resolver(ctx, entradas)
    subtotal = sum((Decimal(ln["subtotal"]) for ln in lineas if ln["subtotal"]), Decimal("0"))
    con_problema = [ln for ln in lineas if ln["problema"]]
    return {
        "lineas": lineas,
        "quitados": quitados,
        "cantidad_total": sum(ln["cantidad"] for ln in lineas),
        "subtotal": _dinero(subtotal),
        "peso_kg": _dinero(envios.peso_total(pares, ctx)),
        "problemas": len(con_problema),
        "puede_comprar": bool(lineas) and not con_problema,
        "moneda": "PEN",
    }


def resumen_de_compra(
    ctx: Contexto,
    entradas: list[dict],
    *,
    modalidad: str | None,
    ubigeo: str = "",
    punto_id: int | None = None,
) -> dict:
    """El carrito más la entrega elegida (envío con su costo o recojo con su punto)."""
    lineas, pares, quitados = resolver(ctx, entradas)
    base = calcular(ctx, entradas)
    subtotal = Decimal(base["subtotal"])
    peso = envios.peso_total(pares, ctx)
    entrega = {
        "modalidad": modalidad,
        "envio": None,
        "puntos": None,
        "punto": None,
        "valida": False,
        "motivo": None,
        "opciones": {"envio": ctx.permite_envio, "recojo": ctx.permite_recojo},
    }
    costo_envio = Decimal("0")
    nota = None
    if modalidad == "ENVIO":
        envio = envios.cotizar_envio(ctx, ubigeo=ubigeo, peso=peso, subtotal=subtotal)
        entrega["envio"] = envio
        entrega["valida"] = envio["disponible"]
        entrega["motivo"] = envio["motivo"]
        costo_envio = Decimal(envio["costo"])
        if envio["paga_en_destino"]:
            nota = "El flete lo pagas a la agencia al recibir; aquí solo pagas tus productos."
    elif modalidad == "RECOJO":
        puntos = envios.puntos_de_recojo(ctx, pares)
        entrega["puntos"] = puntos
        elegido = next((p for p in puntos if p["id"] == punto_id), None)
        entrega["punto"] = elegido
        if not puntos:
            entrega["motivo"] = "No hay tiendas disponibles para recoger por ahora."
        elif elegido is None:
            entrega["motivo"] = "Elige la tienda donde recogerás tu pedido."
        elif not elegido["disponible"]:
            entrega["motivo"] = (
                "Esa tienda no tiene todo tu pedido. Elige otra o cambia las cantidades."
            )
        else:
            entrega["valida"] = True
    elif modalidad is not None:
        raise DatosInvalidos("Elige envío a domicilio o recojo en tienda.")
    return {
        **base,
        "quitados": quitados,
        "entrega": entrega,
        "costo_envio": _dinero(costo_envio),
        "total": _dinero(subtotal + costo_envio),
        "nota_pago": nota,
        "puede_continuar": base["puede_comprar"] and entrega["valida"],
    }


# ---------------------------------------------------------------------------
# Carrito guardado de quien tiene cuenta
# ---------------------------------------------------------------------------
def guardado(cuenta: CuentaCliente) -> list[dict]:
    fila = CarritoCuenta.objects.sin_ambito().filter(cuenta=cuenta).first()
    return list(fila.lineas) if fila else []


def guardar(cuenta: CuentaCliente, entradas: list[dict]) -> None:
    CarritoCuenta.objects.sin_ambito().update_or_create(
        cuenta=cuenta,
        defaults={"organizacion_id": cuenta.organizacion_id, "lineas": entradas},
    )
