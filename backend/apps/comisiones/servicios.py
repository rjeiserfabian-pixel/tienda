"""Reglas de comisión: crearlas con cuidado y decidir qué porcentaje le toca a cada venta.

Qué regla gana cuando varias encajan (de más a menos específica):

1. La de un PRODUCTO, luego la de su MARCA, luego la de su CATEGORÍA y por último la GENERAL.
2. A igual alcance, la regla hecha para ESE vendedor le gana a la que vale para todos.

Si ninguna encaja, el porcentaje es 0: esa venta no paga comisión (y el sistema lo dice).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_date

from apps.auditoria.servicios import diferencia, registrar
from apps.core.exceptions import ErrorDominio
from apps.mantenimiento.models import Categoria, Marca, Producto
from apps.seguridad.models import Usuario

from .models import Alcance, ReglaComision

CERO = Decimal("0")
CIEN = Decimal("100")
NOTA_MAXIMA = 120


class ReglaInvalida(ErrorDominio):
    status_code = 400
    codigo = "regla_comision_invalida"
    mensaje = "La regla de comisión no es válida."


@dataclass(frozen=True, slots=True)
class Resultado:
    """El porcentaje que corresponde y de dónde sale (``regla`` es ``None`` si no hay ninguna)."""

    porcentaje: Decimal
    regla: ReglaComision | None
    texto: str


# --- validación ------------------------------------------------------------------------
def _porcentaje(valor) -> Decimal:
    try:
        numero = Decimal(str(valor).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ReglaInvalida("Escriba el porcentaje como número, por ejemplo 2,5.") from None
    if not numero.is_finite() or numero < CERO or numero > CIEN:
        raise ReglaInvalida("El porcentaje debe estar entre 0 y 100.")
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fecha(valor, campo: str) -> date | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, date):
        return valor
    fecha = parse_date(str(valor))
    if fecha is None:
        raise ReglaInvalida(f"La fecha «{campo}» debe tener el formato AAAA-MM-DD.")
    return fecha


def _uuid(valor) -> uuid.UUID | None:
    if valor in (None, ""):
        return None
    try:
        return valor if isinstance(valor, uuid.UUID) else uuid.UUID(str(valor))
    except ValueError:
        raise ReglaInvalida("El vendedor no es válido.") from None


def _entero(valor, campo: str) -> int | None:
    if valor in (None, ""):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ReglaInvalida(f"«{campo}» no es válido.") from None


def _solapan(a_desde, a_hasta, b_desde, b_hasta) -> bool:
    """¿Dos periodos (con extremos abiertos) tienen algún día en común?"""
    return (a_desde is None or b_hasta is None or a_desde <= b_hasta) and (
        b_desde is None or a_hasta is None or b_desde <= a_hasta
    )


def _validar(organizacion_id: int, datos: dict, *, actual: ReglaComision | None = None) -> dict:
    def dato(campo, por_defecto=None):
        if campo in datos:
            return datos[campo]
        return getattr(actual, campo, por_defecto) if actual else por_defecto

    alcance = dato("alcance")
    if alcance not in Alcance.values:
        raise ReglaInvalida("Elija a qué se aplica la regla.")
    objetivo = {"categoria": None, "marca": None, "producto": None}
    if alcance != Alcance.GENERAL:
        campo = alcance.lower()
        pk = _entero(
            datos.get(campo) if campo in datos else getattr(actual, f"{campo}_id", None), campo
        )
        modelo = {"categoria": Categoria, "marca": Marca, "producto": Producto}[campo]
        if (
            pk is None
            or not modelo.objects.sin_ambito()
            .filter(pk=pk, organizacion_id=organizacion_id)
            .exists()
        ):
            raise ReglaInvalida(
                f"Elija {'la' if campo != 'producto' else 'el'} {campo} de la regla."
            )
        objetivo[campo] = pk
    vendedor_id = _uuid(dato("vendedor_id"))
    if (
        vendedor_id is not None
        and not Usuario.objects.filter(pk=vendedor_id, organizacion_id=organizacion_id).exists()
    ):
        raise ReglaInvalida("Elija un vendedor de esta organización.")
    desde = _fecha(dato("vigente_desde"), "desde")
    hasta = _fecha(dato("vigente_hasta"), "hasta")
    if desde and hasta and hasta < desde:
        raise ReglaInvalida("La fecha «hasta» no puede ser anterior a «desde».")
    nota = " ".join(str(dato("nota", "") or "").split())
    if len(nota) > NOTA_MAXIMA:
        raise ReglaInvalida(f"La nota admite hasta {NOTA_MAXIMA} caracteres.")
    limpio = {
        "alcance": alcance,
        "categoria_id": objetivo["categoria"],
        "marca_id": objetivo["marca"],
        "producto_id": objetivo["producto"],
        "vendedor_id": vendedor_id,
        "porcentaje": _porcentaje(dato("porcentaje")),
        "vigente_desde": desde,
        "vigente_hasta": hasta,
        "activa": bool(dato("activa", True)),
        "nota": nota,
    }
    if limpio["activa"]:
        iguales = ReglaComision.objects.sin_ambito().filter(
            organizacion_id=organizacion_id,
            activa=True,
            alcance=alcance,
            categoria_id=limpio["categoria_id"],
            marca_id=limpio["marca_id"],
            producto_id=limpio["producto_id"],
            vendedor_id=vendedor_id,
        )
        if actual is not None:
            iguales = iguales.exclude(pk=actual.pk)
        if any(_solapan(desde, hasta, o.vigente_desde, o.vigente_hasta) for o in iguales):
            raise ReglaInvalida(
                "Ya hay una regla activa igual para esas fechas. Cámbiala o páusala primero."
            )
    return limpio


def _como_dict(regla: ReglaComision) -> dict:
    return {
        "alcance": regla.alcance,
        "categoria": regla.categoria_id,
        "marca": regla.marca_id,
        "producto": regla.producto_id,
        "vendedor": str(regla.vendedor_id) if regla.vendedor_id else None,
        "porcentaje": str(regla.porcentaje),
        "desde": regla.vigente_desde.isoformat() if regla.vigente_desde else None,
        "hasta": regla.vigente_hasta.isoformat() if regla.vigente_hasta else None,
        "activa": regla.activa,
        "nota": regla.nota,
    }


# --- crear, cambiar, borrar --------------------------------------------------------------
@transaction.atomic
def crear(organizacion_id: int, datos: dict) -> ReglaComision:
    limpio = _validar(organizacion_id, datos)
    regla = ReglaComision.objects.sin_ambito().create(organizacion_id=organizacion_id, **limpio)
    registrar(
        "comisiones.regla_creada",
        recurso_tipo="regla_comision",
        recurso_id=regla.pk,
        resumen=f"Regla de comisión: {explicar(regla)} = {regla.porcentaje} %",
        detalle=_como_dict(regla),
    )
    return regla


@transaction.atomic
def actualizar(regla: ReglaComision, datos: dict) -> ReglaComision:
    regla = ReglaComision.objects.sin_ambito().select_for_update().get(pk=regla.pk)
    antes = _como_dict(regla)
    limpio = _validar(regla.organizacion_id, datos, actual=regla)
    for campo, valor in limpio.items():
        setattr(regla, campo, valor)
    regla.save()
    despues = _como_dict(regla)
    if antes != despues:
        registrar(
            "comisiones.regla_editada",
            recurso_tipo="regla_comision",
            recurso_id=regla.pk,
            resumen=f"Regla de comisión modificada: {explicar(regla)}",
            detalle=diferencia(antes, despues),
        )
    return regla


@transaction.atomic
def eliminar(regla: ReglaComision) -> None:
    regla = ReglaComision.objects.sin_ambito().select_for_update().get(pk=regla.pk)
    datos, texto, regla_id = _como_dict(regla), explicar(regla), regla.pk
    regla.delete()
    registrar(
        "comisiones.regla_eliminada",
        recurso_tipo="regla_comision",
        recurso_id=regla_id,
        resumen=f"Regla de comisión eliminada: {texto}",
        detalle=datos,
    )


# --- qué porcentaje toca -----------------------------------------------------------------
def explicar(regla: ReglaComision) -> str:
    """«Marca Samsung» / «Cualquier venta», con el vendedor si es solo de uno."""
    if regla.alcance == Alcance.PRODUCTO:
        base = f"Producto {regla.producto.nombre}"
    elif regla.alcance == Alcance.MARCA:
        base = f"Marca {regla.marca.nombre}"
    elif regla.alcance == Alcance.CATEGORIA:
        base = f"Categoría {regla.categoria.nombre}"
    else:
        base = "Cualquier venta"
    return base + (" (solo de un vendedor)" if regla.vendedor_id else "")


_NIVEL = {Alcance.PRODUCTO: 0, Alcance.MARCA: 1, Alcance.CATEGORIA: 2, Alcance.GENERAL: 3}


def porcentaje_para(
    organizacion_id: int, *, vendedor_id, producto: Producto, fecha: date
) -> Resultado:
    """El porcentaje de comisión que gana ``vendedor_id`` por vender ``producto`` en ``fecha``."""
    vendedor = _uuid(vendedor_id)
    candidatas = (
        ReglaComision.objects.sin_ambito()
        .select_related("categoria", "marca", "producto")
        .filter(organizacion_id=organizacion_id, activa=True)
        .filter(Q(vigente_desde__isnull=True) | Q(vigente_desde__lte=fecha))
        .filter(Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=fecha))
        .filter(Q(vendedor_id__isnull=True) | Q(vendedor_id=vendedor))
        .filter(
            Q(alcance=Alcance.GENERAL)
            | Q(alcance=Alcance.PRODUCTO, producto_id=producto.pk)
            | Q(alcance=Alcance.MARCA, marca_id=producto.marca_id)
            | Q(alcance=Alcance.CATEGORIA, categoria_id=producto.categoria_id)
        )
    )
    # Un producto sin marca no encaja con «marca = nada».
    elegibles = [
        r for r in candidatas if not (r.alcance == Alcance.MARCA and producto.marca_id is None)
    ]
    if not elegibles:
        return Resultado(CERO, None, "Ninguna regla encaja: no paga comisión.")
    ganadora = min(elegibles, key=lambda r: (_NIVEL[r.alcance], r.vendedor_id is None, -r.pk))
    return Resultado(ganadora.porcentaje, ganadora, explicar(ganadora))
