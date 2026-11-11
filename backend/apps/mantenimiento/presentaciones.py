"""Presentaciones de un producto (caja, docena…): alta, precios y conversión a la unidad base.

El stock y el Kardex siempre van en la unidad base del producto. Comprar o vender "2 cajas de 12"
mueve 24 unidades: ``convertir_a_base`` hace esa cuenta, con la regla de que el resultado cabe en
las 3 decimales que usa el inventario (no se compran 0,0004 unidades).
"""

import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.auditoria.servicios import registrar

from .models import ListaPrecio, PrecioPresentacion, PresentacionProducto, Producto, UnidadMedida
from .productos import CIEN, DOS, normalizar_precios
from .services import SIN_UNICIDAD, _guardar

logger = logging.getLogger(__name__)

TRES = Decimal("0.001")


# ---------------------------------------------------------------------------
# Conversión
# ---------------------------------------------------------------------------
def convertir_a_base(presentacion: PresentacionProducto, cantidad: Decimal) -> Decimal:
    """Cantidad en unidades base: 2 cajas de 12 → 24. ``ValueError`` si no cuadra."""
    if not isinstance(cantidad, Decimal) or not cantidad.is_finite() or cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    base = cantidad * presentacion.factor
    if base != base.quantize(TRES):
        raise ValueError(
            f"{cantidad.normalize():f} {presentacion.unidad.nombre} no equivale a una cantidad "
            "exacta de unidades base (como máximo 3 decimales)."
        )
    return base


def costo_de_presentacion(producto: Producto, presentacion: PresentacionProducto) -> Decimal:
    """Lo que cuesta una presentación: el costo base por su factor."""
    return producto.costo * presentacion.factor


def utilidad_de_presentacion(
    precio: Decimal, costo_base: Decimal, factor: Decimal
) -> Decimal | None:
    costo = costo_base * factor
    if costo <= 0:
        return None
    return ((precio / costo - 1) * CIEN).quantize(DOS)


# ---------------------------------------------------------------------------
# Precios de la presentación
# ---------------------------------------------------------------------------
def _listas_permitidas(presentacion: PresentacionProducto | None) -> dict[int, ListaPrecio]:
    """Listas activas, más las desactivadas en las que la presentación ya tiene precio."""
    condicion = Q(estado="ACTIVO")
    if presentacion is not None and presentacion.pk:
        condicion |= Q(precios_presentacion__presentacion=presentacion)
    return {lista.pk: lista for lista in ListaPrecio.objects.filter(condicion).distinct()}


def _guardar_precios(presentacion: PresentacionProducto, precios: list[dict]) -> dict:
    """Deja exactamente esos precios; devuelve qué cambió (para la auditoría)."""
    actuales = {p.lista_id: p for p in PrecioPresentacion.objects.filter(presentacion=presentacion)}
    cambios: dict[str, list] = {}
    nuevas = {p["lista"].pk: p for p in precios}
    for lista_id, datos in nuevas.items():
        fila = actuales.get(lista_id)
        if fila is None:
            PrecioPresentacion(
                organizacion_id=presentacion.organizacion_id,
                presentacion=presentacion,
                lista=datos["lista"],
                precio=datos["precio"],
                utilidad=datos["utilidad"],
            ).save()
            cambios[datos["lista"].nombre] = [None, str(datos["precio"])]
        elif (fila.precio, fila.utilidad) != (datos["precio"], datos["utilidad"]):
            if fila.precio != datos["precio"]:
                cambios[datos["lista"].nombre] = [str(fila.precio), str(datos["precio"])]
            fila.precio, fila.utilidad = datos["precio"], datos["utilidad"]
            fila.save(update_fields=["precio", "utilidad"])
    for lista_id, fila in actuales.items():
        if lista_id not in nuevas and fila.lista.estado == "ACTIVO":
            cambios[fila.lista.nombre] = [str(fila.precio), None]
            fila.delete()
    return cambios


def recalcular_utilidades(producto: Producto) -> None:
    """Tras cambiar el costo (o el factor): la utilidad de cada precio sigue siendo verdad."""
    filas = PrecioPresentacion.objects.filter(presentacion__producto=producto).select_related(
        "presentacion"
    )
    for fila in filas:
        nueva = utilidad_de_presentacion(fila.precio, producto.costo, fila.presentacion.factor)
        if nueva != fila.utilidad:
            fila.utilidad = nueva
            fila.save(update_fields=["utilidad"])


def _normalizar(
    producto: Producto, factor: Decimal, entradas: list[dict], presentacion=None
) -> list[dict]:
    """Valida los precios con el costo de la presentación (costo base × factor)."""
    return normalizar_precios(producto.costo * factor, entradas, _listas_permitidas(presentacion))


# ---------------------------------------------------------------------------
# Alta, edición y baja
# ---------------------------------------------------------------------------
def _unidad_activa(unidad_id: int, organizacion_id: int) -> UnidadMedida:
    unidad = (
        UnidadMedida.objects.sin_ambito()
        .filter(pk=unidad_id, organizacion_id=organizacion_id, estado="ACTIVO")
        .first()
    )
    if unidad is None:
        raise ValidationError({"unidad": "Elija una unidad de medida activa."})
    return unidad


@transaction.atomic
def crear_presentacion(
    *, producto: Producto, unidad_id: int, factor: Decimal, codigo_barras: str, precios
) -> PresentacionProducto:
    presentacion = PresentacionProducto(
        organizacion_id=producto.organizacion_id,
        producto=producto,
        unidad=_unidad_activa(unidad_id, producto.organizacion_id),
        factor=factor,
        codigo_barras=codigo_barras,
    )
    presentacion.full_clean(**SIN_UNICIDAD)
    _guardar(presentacion, "El producto ya tiene esa unidad.", "unidad")
    if precios:
        _guardar_precios(presentacion, _normalizar(producto, presentacion.factor, precios))
    registrar(
        "presentacion.creada",
        recurso_tipo="producto",
        recurso_id=producto.pk,
        resumen=f"{presentacion.equivalencia} en {producto}",
    )
    return presentacion


@transaction.atomic
def actualizar_presentacion(
    presentacion: PresentacionProducto, *, datos: dict, precios
) -> PresentacionProducto:
    """Cambia el factor, el código de barras o el estado; la unidad no cambia."""
    campos = list(datos)
    antes = {c: getattr(presentacion, c) for c in campos}
    for campo, valor in datos.items():
        setattr(presentacion, campo, valor)
    if campos:
        presentacion.full_clean(**SIN_UNICIDAD)
        _guardar(
            presentacion,
            "Ya existe una presentación con ese código de barras.",
            "codigo_barras",
            update_fields=campos,
        )
    cambios = {
        c: [str(a), str(getattr(presentacion, c))]
        for c, a in antes.items()
        if a != getattr(presentacion, c)
    }
    producto = presentacion.producto
    if precios is not None:
        cambios_precio = _guardar_precios(
            presentacion, _normalizar(producto, presentacion.factor, precios, presentacion)
        )
        if cambios_precio:
            cambios["precios"] = cambios_precio
    elif "factor" in datos:
        recalcular_utilidades(producto)  # el costo de la presentación cambió con su factor
    if cambios:
        registrar(
            "presentacion.editada",
            recurso_tipo="producto",
            recurso_id=producto.pk,
            resumen=f"Presentación {presentacion.unidad.nombre} de {producto} modificada",
            detalle=cambios,
        )
    return presentacion


@transaction.atomic
def eliminar_presentacion(presentacion: PresentacionProducto) -> None:
    """Borrado lógico: el historial de documentos guarda su propia copia de la equivalencia."""
    producto = presentacion.producto
    etiqueta = presentacion.equivalencia
    PrecioPresentacion.objects.filter(presentacion=presentacion).delete()
    presentacion.delete()
    registrar(
        "presentacion.eliminada",
        recurso_tipo="producto",
        recurso_id=producto.pk,
        resumen=f"Se quitó la presentación «{etiqueta}» de {producto}",
    )
