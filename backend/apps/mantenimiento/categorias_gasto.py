"""Categorías de gasto de fábrica y su carga en cada organización.

Se cargan al crear la organización y con ``sync_permisos``. Lo ya editado no se pisa y lo que la
organización eliminó no se vuelve a crear.
"""

import logging

from django.db import transaction

from .models import CategoriaGasto

logger = logging.getLogger(__name__)

OTROS = "OTROS"

# (código, nombre)
CATEGORIAS = (
    ("SERVICIOS", "Servicios básicos (luz, agua, internet, teléfono)"),
    ("ALQUILER", "Alquiler"),
    ("MOVILIDAD", "Movilidad y transporte"),
    ("MANTENIMIENTO", "Mantenimiento y reparaciones"),
    ("UTILES", "Útiles y suministros"),
    ("PUBLICIDAD", "Publicidad y marketing"),
    ("IMPUESTOS", "Impuestos y tasas"),
    ("HONORARIOS", "Honorarios y servicios de terceros"),
    ("ATENCION", "Atención y alimentación"),
    (OTROS, "Otros gastos"),
)


@transaction.atomic
def sembrar_categorias_gasto(organizacion_id: int) -> dict[str, int]:
    """Agrega lo que falte; no cambia lo editado ni vuelve a crear lo que se eliminó."""
    existentes = CategoriaGasto.objects.sin_ambito(incluir_eliminados=True).filter(
        organizacion_id=organizacion_id
    )
    por_codigo = {c.codigo for c in existentes if c.codigo}
    por_nombre = {c.nombre.lower() for c in existentes}
    creadas = 0
    for codigo, nombre in CATEGORIAS:
        if codigo in por_codigo or nombre.lower() in por_nombre:
            continue
        CategoriaGasto.objects.sin_ambito().create(
            organizacion_id=organizacion_id, nombre=nombre, codigo=codigo
        )
        creadas += 1
    if creadas:
        logger.info("categorias_gasto_sembradas", extra={"organizacion_id": organizacion_id})
    return {"categorias_gasto": creadas}
