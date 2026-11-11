"""Reglas fiscales: tasas con vigencia, IGV que propone cada operación y serie de comprobantes.

* ``tasa_vigente``: el porcentaje de un impuesto en una fecha (las tasas son de la organización).
* ``sugerir_afectacion``: qué afectación del IGV corresponde a una compra o venta, según el
  producto, el régimen de la empresa y la zona del proveedor o cliente.
* ``validar_serie_numero``: la serie y el número de un comprobante según su tipo.
* ``sembrar_catalogos_fiscales``: carga los catálogos de SUNAT en una organización.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, RegimenIgv

from . import fiscal_datos
from .exceptions import AfectacionNoDisponible, TasaNoVigente
from .models import (
    AfectacionIGV,
    EstadoRegistro,
    Producto,
    TasaImpuesto,
    TipoComprobante,
    ZonaFiscal,
)

logger = logging.getLogger(__name__)

COMPRA = "COMPRA"
VENTA = "VENTA"
CERO = Decimal("0")


# ---------------------------------------------------------------------------
# Tasas con vigencia
# ---------------------------------------------------------------------------
def tasa_vigente(organizacion_id: int, impuesto: str, fecha: date | None = None) -> Decimal:
    """Porcentaje del impuesto en ``fecha`` (hoy si no se indica): la última tasa ya iniciada."""
    dia = fecha or timezone.localdate()
    porcentaje = (
        TasaImpuesto.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, impuesto=impuesto, vigente_desde__lte=dia)
        .order_by("-vigente_desde")
        .values_list("porcentaje", flat=True)
        .first()
    )
    if porcentaje is None:
        raise TasaNoVigente(
            f"No hay una tasa de {impuesto} vigente al {dia:%d/%m/%Y}. "
            "Cárgala en Tasas de impuesto."
        )
    return porcentaje


def tasa_en_uso(
    organizacion_id: int, impuesto: str, desde: date, *, excluir_pk: int | None = None
) -> bool:
    """¿Algún documento ya se registró con la tasa que rige desde ``desde``?

    Cada documento guarda el porcentaje con que se calculó. Si ya hay uno dentro de los días en
    que rige esta tasa, cambiarla dejaría la historia incoherente: en ese caso se agrega una
    tasa nueva desde la fecha del cambio. Hoy solo el inventario registra IGV; cuando Compras y
    Ventas guarden sus propios documentos, se suman aquí.
    """
    if impuesto != "IGV":
        return False  # el IVAP aún no lo usa ningún documento
    from apps.inventario.models import MovimientoInventario

    siguientes = TasaImpuesto.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, impuesto=impuesto, vigente_desde__gt=desde
    )
    if excluir_pk is not None:
        siguientes = siguientes.exclude(pk=excluir_pk)
    fin = siguientes.order_by("vigente_desde").values_list("vigente_desde", flat=True).first()
    movimientos = MovimientoInventario.objects.sin_ambito().filter(
        empresa__organizacion_id=organizacion_id, fecha__gte=desde, igv_porcentaje__gt=0
    )
    if fin is not None:
        movimientos = movimientos.filter(fecha__lt=fin)
    return movimientos.exists()


# ---------------------------------------------------------------------------
# IGV que propone cada operación
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SugerenciaIgv:
    """La afectación propuesta, su porcentaje a esa fecha y el porqué (para mostrarlo)."""

    afectacion: AfectacionIGV
    porcentaje: Decimal
    motivo: str


def _afectacion(organizacion_id: int, codigo: str) -> AfectacionIGV:
    afectacion = (
        AfectacionIGV.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, codigo=codigo)
        .first()
    )
    if afectacion is None or afectacion.estado != EstadoRegistro.ACTIVO:
        raise AfectacionNoDisponible(
            f"La afectación {codigo} no está activa. Actívala en Mantenimiento → IGV."
        )
    return afectacion


def _regimen(empresa: Empresa) -> str:
    regimen = (
        ConfiguracionEmpresa.objects.sin_ambito()
        .filter(empresa=empresa)
        .values_list("regimen_igv", flat=True)
        .first()
    )
    return regimen or RegimenIgv.NORMAL


def _codigo_por_zona(regimen: str, operacion: str, zona: str) -> tuple[str, str]:
    """``(código, motivo)`` cuando no hay una excepción del producto."""
    if regimen != RegimenIgv.AMAZONIA:
        return fiscal_datos.CODIGO_GRAVADO, "Régimen normal de la empresa: gravado."
    quien = "proveedor" if operacion == COMPRA else "cliente"
    if zona == ZonaFiscal.FUERA:
        return fiscal_datos.CODIGO_GRAVADO, f"El {quien} está fuera de la región: gravado."
    if zona == ZonaFiscal.DENTRO:
        return fiscal_datos.CODIGO_EXONERADO, f"El {quien} está en la región: exonerado."
    if operacion == COMPRA:
        return fiscal_datos.CODIGO_GRAVADO, "Compra sin zona definida: gravado."
    return fiscal_datos.CODIGO_EXONERADO, "Venta sin zona definida: exonerado (Amazonía)."


def sugerir_afectacion(
    *,
    empresa: Empresa,
    operacion: str,
    zona: str = "",
    producto: Producto | None = None,
    fecha: date | None = None,
) -> SugerenciaIgv:
    """La afectación del IGV que corresponde a una línea de compra o venta.

    Orden: 1) la excepción del producto, si es válida para la operación; 2) el régimen de la
    empresa y la zona del proveedor o cliente. Siempre se puede cambiar a mano.
    """
    if operacion not in (COMPRA, VENTA):
        raise ValueError("La operación es COMPRA o VENTA.")
    organizacion_id = empresa.organizacion_id
    afectacion = None
    motivo = ""
    propia = getattr(producto, "afectacion_igv", None)
    if propia is not None and propia.estado == EstadoRegistro.ACTIVO:
        aplica = propia.aplica_compras if operacion == COMPRA else propia.aplica_ventas
        if aplica:
            afectacion, motivo = propia, "El producto tiene su propia afectación del IGV."
    if afectacion is None:
        codigo, motivo = _codigo_por_zona(_regimen(empresa), operacion, zona)
        afectacion = _afectacion(organizacion_id, codigo)
    porcentaje = (
        tasa_vigente(organizacion_id, afectacion.impuesto, fecha)
        if afectacion.paga_impuesto
        else CERO
    )
    return SugerenciaIgv(afectacion, porcentaje, motivo)


def elegir_afectacion(
    *, empresa: Empresa, operacion: str, codigo: str, fecha: date | None = None
) -> SugerenciaIgv:
    """La afectación que el usuario eligió a mano para una línea (debe servir para la operación)."""
    if operacion not in (COMPRA, VENTA):
        raise ValueError("La operación es COMPRA o VENTA.")
    afectacion = _afectacion(empresa.organizacion_id, codigo)
    aplica = afectacion.aplica_compras if operacion == COMPRA else afectacion.aplica_ventas
    if not aplica:
        raise AfectacionNoDisponible(
            f"La afectación «{afectacion.nombre}» no se ofrece en esta operación."
        )
    porcentaje = (
        tasa_vigente(empresa.organizacion_id, afectacion.impuesto, fecha)
        if afectacion.paga_impuesto
        else CERO
    )
    return SugerenciaIgv(afectacion, porcentaje, "Elegida a mano.")


# ---------------------------------------------------------------------------
# Serie y número de un comprobante
# ---------------------------------------------------------------------------
_NUMERO_ELECTRONICO = re.compile(r"\d{1,8}")


def validar_serie_numero(tipo: TipoComprobante, serie: str, numero: str) -> tuple[str, str]:
    """Serie y número normalizados; lanza ``ValueError`` con un mensaje claro si no cuadran."""
    serie = " ".join((serie or "").split()).upper()
    numero = " ".join((numero or "").split()).upper()
    if serie and tipo.patron_serie and not re.fullmatch(tipo.patron_serie, serie):
        raise ValueError(f"La serie «{serie}» no tiene el formato de {tipo.nombre}.")
    if numero and tipo.es_electronico and not _NUMERO_ELECTRONICO.fullmatch(numero):
        raise ValueError(f"El número de {tipo.nombre} son hasta 8 dígitos.")
    return serie, numero


# ---------------------------------------------------------------------------
# Carga inicial
# ---------------------------------------------------------------------------
@transaction.atomic
def sembrar_catalogos_fiscales(organizacion_id: int) -> dict[str, int]:
    """Agrega lo que falta de los catálogos de SUNAT; nunca cambia ni repone lo ya editado.

    Un código que el administrador eliminó tampoco se vuelve a crear. Devuelve cuántas filas
    nuevas hubo de cada catálogo.
    """
    creados = {"tipos_comprobante": 0, "afectaciones_igv": 0, "tasas": 0}

    existentes = set(
        TipoComprobante.objects.sin_ambito(incluir_eliminados=True)
        .filter(organizacion_id=organizacion_id)
        .values_list("codigo", flat=True)
    )
    for (
        codigo,
        nombre,
        abrev,
        electronico,
        compras,
        ventas,
        igv,
        serie,
    ) in fiscal_datos.TIPOS_COMPROBANTE:
        if codigo in existentes:
            continue
        TipoComprobante.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            codigo=codigo,
            nombre=nombre,
            abreviatura=abrev,
            es_electronico=electronico,
            aplica_compras=compras,
            aplica_ventas=ventas,
            lleva_igv=igv,
            patron_serie=serie,
            ejemplo_serie=fiscal_datos.EJEMPLOS_SERIE.get(codigo, ""),
        )
        creados["tipos_comprobante"] += 1

    existentes = set(
        AfectacionIGV.objects.sin_ambito(incluir_eliminados=True)
        .filter(organizacion_id=organizacion_id)
        .values_list("codigo", flat=True)
    )
    for codigo, nombre, grupo, impuesto, gratuita, compras, ventas in fiscal_datos.AFECTACIONES_IGV:
        if codigo in existentes:
            continue
        AfectacionIGV.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            codigo=codigo,
            nombre=nombre,
            grupo=grupo,
            impuesto=impuesto,
            gratuita=gratuita,
            aplica_compras=compras,
            aplica_ventas=ventas,
        )
        creados["afectaciones_igv"] += 1

    existentes = set(
        TasaImpuesto.objects.sin_ambito(incluir_eliminados=True)
        .filter(organizacion_id=organizacion_id)
        .values_list("impuesto", flat=True)
    )
    for impuesto, porcentaje, desde in fiscal_datos.TASAS_INICIALES:
        if impuesto in existentes:  # ya hay una tasa de ese impuesto: no se toca
            continue
        TasaImpuesto.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            impuesto=impuesto,
            porcentaje=Decimal(porcentaje),
            vigente_desde=desde,
        )
        creados["tasas"] += 1

    if any(creados.values()):
        registrar(
            "fiscal.catalogos_sembrados",
            recurso_tipo="organizacion",
            recurso_id=organizacion_id,
            organizacion_id=organizacion_id,
            resumen="Se cargaron los catálogos fiscales de SUNAT",
            detalle=creados,
        )
        logger.info("catalogos_fiscales_sembrados", extra={"organizacion_id": organizacion_id})
    return creados
