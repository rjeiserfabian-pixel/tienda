"""Catálogos de fábrica del servicio técnico y su carga en cada organización.

Se cargan al crear la organización y con ``sync_permisos``. Lo ya editado no se pisa y lo que la
organización eliminó no se vuelve a crear.
"""

import logging

from django.db import transaction

from .models import (
    AccesorioEquipo,
    CategoriaServicio,
    ItemChecklist,
    TipoEquipo,
    TipoServicio,
)

logger = logging.getLogger(__name__)

# (código, nombre)
TIPOS_EQUIPO = (
    ("LAPTOP", "Laptop"),
    ("PC", "PC de escritorio"),
    ("ALL_IN_ONE", "All in One"),
    ("MONITOR", "Monitor"),
    ("IMPRESORA", "Impresora"),
    ("CELULAR", "Celular"),
    ("TABLET", "Tablet"),
    ("RED", "Equipo de red"),
    ("OTRO", "Otro equipo"),
)

ACCESORIOS = (
    ("CARGADOR", "Cargador o adaptador"),
    ("CABLE_PODER", "Cable de poder"),
    ("MOUSE", "Mouse"),
    ("TECLADO", "Teclado"),
    ("MALETIN", "Maletín o funda"),
    ("BATERIA", "Batería"),
    ("CABLES", "Cables (USB, HDMI, red)"),
    ("CARTUCHOS", "Cartuchos o tóner"),
    ("MEMORIA", "Memoria, disco o USB"),
    ("CAJA", "Caja o embalaje"),
)

# (código, nombre, orden)
REVISIONES = (
    ("ENCIENDE", "¿Enciende?", 1),
    ("SISTEMA", "¿Arranca el sistema operativo?", 2),
    ("PANTALLA", "Pantalla (rayones, manchas, píxeles)", 3),
    ("CARCASA", "Carcasa y golpes", 4),
    ("TECLADO", "Teclado y touchpad", 5),
    ("PUERTOS", "Puertos (USB, HDMI, red, carga)", 6),
    ("BATERIA", "Batería (carga y dura)", 7),
    ("AUDIO", "Audio y parlantes", 8),
    ("RED", "Wi-Fi y red", 9),
    ("DISCO", "Disco o almacenamiento", 10),
    ("PRECINTOS", "Precintos o sellos de garantía intactos", 11),
)

# (código, nombre, categoría, días de garantía)
TIPOS_SERVICIO = (
    ("DIAGNOSTICO", "Diagnóstico técnico", CategoriaServicio.DIAGNOSTICO, 0),
    ("MANT_PREVENTIVO", "Mantenimiento preventivo", CategoriaServicio.MANTENIMIENTO, 30),
    ("LIMPIEZA_INTERNA", "Limpieza interna y pasta térmica", CategoriaServicio.MANTENIMIENTO, 30),
    ("FORMATEO", "Formateo e instalación de sistema", CategoriaServicio.MANTENIMIENTO, 30),
    ("ANTIVIRUS", "Eliminación de virus y optimización", CategoriaServicio.MANTENIMIENTO, 15),
    ("REPARACION_HW", "Reparación de hardware", CategoriaServicio.REPARACION, 30),
    ("CAMBIO_PANTALLA", "Cambio de pantalla", CategoriaServicio.REPARACION, 30),
    ("CAMBIO_REPUESTO", "Cambio de repuesto o componente", CategoriaServicio.REPARACION, 30),
    ("RECUPERACION", "Recuperación de información", CategoriaServicio.REPARACION, 0),
)


def _agregar(modelo, organizacion_id: int, filas: list[tuple[str, str, dict]]) -> int:
    """Crea lo que falte por código o nombre, sin tocar lo editado ni lo eliminado."""
    existentes = modelo.objects.sin_ambito(incluir_eliminados=True).filter(
        organizacion_id=organizacion_id
    )
    por_codigo = {f.codigo for f in existentes if f.codigo}
    por_nombre = {f.nombre.lower() for f in existentes}
    creadas = 0
    for codigo, nombre, extra in filas:
        if codigo in por_codigo or nombre.lower() in por_nombre:
            continue
        modelo.objects.sin_ambito().create(
            organizacion_id=organizacion_id, codigo=codigo, nombre=nombre, **extra
        )
        creadas += 1
    return creadas


@transaction.atomic
def sembrar_catalogos_servicio(organizacion_id: int) -> dict[str, int]:
    """Agrega lo que falte; no cambia lo editado ni vuelve a crear lo que se eliminó."""
    resultado = {
        "tipos_equipo": _agregar(
            TipoEquipo, organizacion_id, [(c, n, {}) for c, n in TIPOS_EQUIPO]
        ),
        "accesorios": _agregar(
            AccesorioEquipo, organizacion_id, [(c, n, {}) for c, n in ACCESORIOS]
        ),
        "revisiones": _agregar(
            ItemChecklist, organizacion_id, [(c, n, {"orden": o}) for c, n, o in REVISIONES]
        ),
        "tipos_servicio": _agregar(
            TipoServicio,
            organizacion_id,
            [(c, n, {"categoria": cat, "garantia_dias": g}) for c, n, cat, g in TIPOS_SERVICIO],
        ),
    }
    if any(resultado.values()):
        logger.info("catalogos_servicio_sembrados", extra={"organizacion_id": organizacion_id})
    return resultado
