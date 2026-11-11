"""Productos: código automático, precios por lista con su utilidad, y los catálogos iniciales.

Regla de precios: ``precio = costo × (1 + utilidad / 100)`` (utilidad sobre el costo) o, si se
prefiere pensar en margen, ``precio = costo ÷ (1 − margen / 100)`` (margen sobre el precio). Lo
que se guarda es el precio y la utilidad; el margen siempre se deriva de ella
(``margen_de_utilidad``). El precio es lo que manda: se guarda tal cual y la utilidad se
DERIVA de él y del costo. Si el costo cambia, los precios no se mueven solos: se recalcula la
utilidad para que siga siendo verdad.
"""

import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError as ErrorValidacion

from apps.auditoria.servicios import registrar

from . import especificaciones
from .models import (
    Correlativo,
    ListaPrecio,
    PrecioProducto,
    Producto,
    UnidadMedida,
    UsoLista,
)
from .services import SIN_UNICIDAD, _guardar

logger = logging.getLogger(__name__)

CUATRO = Decimal("0.0001")
DOS = Decimal("0.01")
CIEN = Decimal("100")

# Unidades de uso común con su código del catálogo de SUNAT.
UNIDADES_COMUNES = (
    ("Unidad", "UND", "NIU"),
    ("Kilogramo", "KG", "KGM"),
    ("Gramo", "GR", "GRM"),
    ("Litro", "LT", "LTR"),
    ("Metro", "M", "MTR"),
    ("Caja", "CAJA", "BX"),
    ("Docena", "DOC", "DZN"),
    ("Par", "PAR", "PR"),
    ("Paquete", "PQT", "PK"),
    ("Servicio", "SERV", "ZZ"),
)
# Las cuatro listas con las que ya trabajan; los nombres se pueden cambiar.
LISTAS_INICIALES = (
    ("Público", UsoLista.PUBLICO),
    ("Descuento", UsoLista.DESCUENTO),
    ("Técnico", UsoLista.TECNICO),
    ("Crédito", UsoLista.CREDITO),
)


def siguiente_codigo(organizacion_id: int) -> str:
    """000001, 000002… sin repetir ni saltar aunque dos personas creen a la vez."""
    with transaction.atomic():
        fila, _ = Correlativo.objects.get_or_create(
            organizacion_id=organizacion_id, clave="producto"
        )
        fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
        fila.ultimo += 1
        fila.save(update_fields=["ultimo"])
        return f"{fila.ultimo:06d}"


def utilidad_de(precio: Decimal, costo: Decimal) -> Decimal | None:
    if costo <= 0:
        return None
    return ((precio / costo - 1) * CIEN).quantize(DOS)


def margen_de_utilidad(utilidad: Decimal | None) -> Decimal | None:
    """Margen sobre el precio equivalente a una utilidad sobre el costo (100 % → 50 %)."""
    if utilidad is None or CIEN + utilidad == 0:
        return None
    return (utilidad / (CIEN + utilidad) * CIEN).quantize(DOS)


def normalizar_precios(
    costo: Decimal, entradas: list[dict], listas: dict[int, ListaPrecio]
) -> list[dict]:
    """Valida los precios enviados y calcula la utilidad de cada uno."""
    vistos: set[int] = set()
    resultado = []
    for entrada in entradas:
        lista_id = entrada["lista"]
        if lista_id not in listas:
            raise ValidationError(
                {"precios": "Hay una lista de precios que no existe o está inactiva."}
            )
        if lista_id in vistos:
            raise ValidationError({"precios": "Una lista de precios está repetida."})
        vistos.add(lista_id)
        precio, utilidad = entrada.get("precio"), entrada.get("utilidad")
        margen = entrada.get("margen")
        if utilidad is not None and margen is not None:
            raise ValidationError({"precios": "Indica la utilidad o el margen, no los dos."})
        if precio is None and utilidad is None and margen is None:
            continue  # sin precio en esa lista
        if precio is None:
            if costo <= 0:
                raise ValidationError(
                    {"precios": "Para calcular con utilidad o margen, ingresa primero el costo."}
                )
            if utilidad is not None:
                precio = costo * (1 + utilidad / CIEN)
            else:  # margen sobre el precio: precio = costo ÷ (1 − margen)
                precio = costo / (1 - margen / CIEN)
        precio = precio.quantize(CUATRO)
        if precio < 0:
            raise ValidationError({"precios": "Un precio no puede ser negativo."})
        resultado.append(
            {"lista": listas[lista_id], "precio": precio, "utilidad": utilidad_de(precio, costo)}
        )
    return resultado


def _guardar_precios(producto: Producto, precios: list[dict]) -> dict:
    """Deja exactamente esos precios; devuelve qué cambió (para la auditoría)."""
    actuales = {p.lista_id: p for p in PrecioProducto.objects.filter(producto=producto)}
    cambios: dict[str, list] = {}
    nuevas = {p["lista"].pk: p for p in precios}
    for lista_id, datos in nuevas.items():
        fila = actuales.get(lista_id)
        if fila is None:
            PrecioProducto(
                organizacion_id=producto.organizacion_id,
                producto=producto,
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
        # Los precios de una lista desactivada se conservan aunque la pantalla ya no la muestre.
        if lista_id not in nuevas and fila.lista.estado == "ACTIVO":
            cambios[fila.lista.nombre] = [str(fila.precio), None]
            fila.delete()
    return cambios


def _recalcular_utilidades(producto: Producto) -> None:
    for fila in PrecioProducto.objects.filter(producto=producto):
        nueva = utilidad_de(fila.precio, producto.costo)
        if nueva != fila.utilidad:
            fila.utilidad = nueva
            fila.save(update_fields=["utilidad"])


def _listas_permitidas(producto: Producto | None = None) -> dict[int, ListaPrecio]:
    """Listas activas, más las desactivadas en las que el producto ya tiene precio."""
    condicion = Q(estado="ACTIVO")
    if producto is not None and producto.pk:
        condicion |= Q(precios__producto=producto)
    return {lista.pk: lista for lista in ListaPrecio.objects.filter(condicion).distinct()}


def _preparar_tienda(organizacion_id: int, datos: dict, producto: Producto | None) -> dict:
    """Valida lo que el producto trae para la tienda: especificaciones, dirección y publicación."""
    datos = dict(datos)
    categoria = datos.get("categoria") or (producto.categoria if producto else None)
    if "especificaciones" in datos:
        datos["especificaciones"] = especificaciones.validar_valores(
            categoria, datos["especificaciones"]
        )
    elif producto is not None and "categoria" in datos:
        # Al cambiar de categoría se conservan solo los datos que la nueva también pide.
        datos["especificaciones"] = especificaciones.podar(
            datos["categoria"], producto.especificaciones
        )
    if "puntos_destacados" in datos:
        datos["puntos_destacados"] = especificaciones.validar_puntos(datos["puntos_destacados"])
    if datos.get("slug"):
        datos["slug"] = especificaciones.validar_slug(
            organizacion_id, datos["slug"], excluir=producto
        )
    publicado = datos.get("publicado_web", producto.publicado_web if producto else False)
    if publicado:
        estado = datos.get("estado", producto.estado if producto else "ACTIVO")
        if estado != "ACTIVO":
            raise ErrorValidacion({"publicado_web": "Solo un producto activo se publica."})
        if producto is None or not producto.fotos.exists():
            raise ErrorValidacion(
                {"publicado_web": "Sube al menos una foto del producto antes de publicarlo."}
            )
        if not (datos.get("slug") or producto.slug):
            datos["slug"] = especificaciones.generar_slug(
                organizacion_id, datos.get("nombre") or producto.nombre, excluir=producto
            )
    return datos


@transaction.atomic
def crear_producto(*, organizacion_id: int, datos: dict, precios: list[dict] | None) -> Producto:
    datos = _preparar_tienda(organizacion_id, datos, None)
    producto = Producto(
        codigo=siguiente_codigo(organizacion_id), organizacion_id=organizacion_id, **datos
    )
    producto.full_clean(**SIN_UNICIDAD)
    _guardar(producto, "Ya existe un producto con ese código de barras.", "codigo_barras")
    if precios:
        _guardar_precios(
            producto, normalizar_precios(producto.costo, precios, _listas_permitidas(producto))
        )
    registrar(
        "producto.creado",
        recurso_tipo="producto",
        recurso_id=producto.pk,
        resumen=f"Producto {producto} registrado",
        detalle={"codigo": producto.codigo},
    )
    return producto


def _exigir_unidad_base_sin_presentaciones(producto: Producto, datos: dict) -> None:
    """La unidad base y la serie no cambian si ya hay presentaciones o movimientos de stock."""
    cambia_serie = datos.get("lleva_serie") and not producto.lleva_serie
    unidad = datos.get("unidad")
    cambia_unidad = unidad is not None and getattr(unidad, "pk", unidad) != producto.unidad_id
    if not (cambia_serie or cambia_unidad):
        return
    if producto.presentaciones.exists():
        raise ValidationError(
            {
                "unidad" if cambia_unidad else "lleva_serie": "El producto tiene otras "
                "presentaciones (caja, docena…): quítalas antes de hacer este cambio."
            }
        )
    if cambia_unidad:
        from apps.inventario.models import LineaMovimiento  # inventario depende de este módulo

        if LineaMovimiento.objects.sin_ambito().filter(producto=producto).exists():
            raise ValidationError(
                {
                    "unidad": "No se puede cambiar la unidad base: el producto ya tiene "
                    "movimientos de inventario en ella."
                }
            )


@transaction.atomic
def actualizar_producto(producto: Producto, *, datos: dict, precios: list[dict] | None) -> Producto:
    datos = _preparar_tienda(producto.organizacion_id, datos, producto)
    _exigir_unidad_base_sin_presentaciones(producto, datos)
    if "lleva_serie" in datos and datos["lleva_serie"] != producto.lleva_serie:
        # Con stock ya registrado, cambiarlo dejaría unidades sin serie (o series sin unidad).
        from apps.inventario.models import LineaMovimiento  # inventario depende de este módulo

        if LineaMovimiento.objects.sin_ambito().filter(producto=producto).exists():
            raise ValidationError(
                {
                    "lleva_serie": "No se puede cambiar: el producto ya tiene movimientos "
                    "de inventario."
                }
            )
    campos = list(datos)
    antes = {c: getattr(producto, c) for c in campos}
    costo_anterior = producto.costo
    for campo, valor in datos.items():
        setattr(producto, campo, valor)
    producto.full_clean(**SIN_UNICIDAD)
    _guardar(
        producto,
        "Ya existe un producto con ese código de barras.",
        "codigo_barras",
        update_fields=campos,
    )
    cambios = {
        c: [_texto(a), _texto(getattr(producto, c))]
        for c, a in antes.items()
        if a != getattr(producto, c)
    }
    if precios is not None:
        cambios_precio = _guardar_precios(
            producto, normalizar_precios(producto.costo, precios, _listas_permitidas(producto))
        )
        if cambios_precio:
            cambios["precios"] = cambios_precio
    elif producto.costo != costo_anterior:
        _recalcular_utilidades(producto)
    if producto.costo != costo_anterior:
        # Los precios de las presentaciones siguen su costo (base × factor).
        from .presentaciones import recalcular_utilidades

        recalcular_utilidades(producto)
    if cambios:
        registrar(
            "producto.editado",
            recurso_tipo="producto",
            recurso_id=producto.pk,
            resumen=f"Producto {producto} modificado",
            detalle=cambios,
        )
    return producto


def _texto(valor):
    return (
        str(valor.pk)
        if hasattr(valor, "pk")
        else str(valor)
        if isinstance(valor, Decimal)
        else valor
    )


# ---------------------------------------------------------------------------
# Catálogos iniciales
# ---------------------------------------------------------------------------
@transaction.atomic
def sembrar_unidades(organizacion_id: int) -> int:
    filas = list(UnidadMedida.objects.values_list("nombre", "abreviatura"))
    nombres = {n.lower() for n, _ in filas}
    abreviaturas = {a.lower() for _, a in filas}
    creadas = 0
    for nombre, abreviatura, codigo in UNIDADES_COMUNES:
        if nombre.lower() in nombres or abreviatura.lower() in abreviaturas:
            continue
        unidad = UnidadMedida(
            organizacion_id=organizacion_id,
            nombre=nombre,
            abreviatura=abreviatura,
            codigo_sunat=codigo,
        )
        unidad.full_clean(**SIN_UNICIDAD)
        unidad.save()
        creadas += 1
    if creadas:
        registrar(
            "unidad_medida.sembrada",
            recurso_tipo="unidad_medida",
            resumen=f"Se cargaron {creadas} unidades de medida comunes",
        )
    return creadas


@transaction.atomic
def sembrar_listas(organizacion_id: int) -> int:
    existentes = {n.lower() for n in ListaPrecio.objects.values_list("nombre", flat=True)}
    hay_principal = ListaPrecio.objects.filter(es_principal=True).exists()
    creadas = 0
    for orden, (nombre, uso) in enumerate(LISTAS_INICIALES, start=1):
        if nombre.lower() in existentes:
            continue
        lista = ListaPrecio(
            organizacion_id=organizacion_id,
            nombre=nombre,
            orden=orden,
            uso=uso,
            es_principal=not hay_principal and orden == 1,
        )
        lista.full_clean(**SIN_UNICIDAD)
        lista.save()
        hay_principal = hay_principal or lista.es_principal
        creadas += 1
    if creadas:
        registrar(
            "lista_precio.sembrada",
            recurso_tipo="lista_precio",
            resumen=f"Se cargaron {creadas} listas de precios iniciales",
        )
    return creadas
