"""Asignación de la ubicación física de un producto dentro de un almacén.

Es independiente del stock (se puede asignar antes de recibir mercadería) y un producto tiene
como máximo UNA ubicación por almacén. Quitarla es un borrado lógico y deja rastro de auditoría.
"""

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import (
    Almacen,
    EstadoRegistro,
    Producto,
    TipoProducto,
    Ubicacion,
    UbicacionProducto,
)


@transaction.atomic
def asignar_ubicacion(
    *, empresa, almacen_id: int, producto_id: int, ubicacion_id: int | None
) -> UbicacionProducto | None:
    """Pone, cambia o quita (``ubicacion_id=None``) la ubicación de un producto en un almacén."""
    almacen = Almacen.objects.filter(pk=almacen_id, empresa=empresa).first()
    if almacen is None:
        raise ValidationError({"almacen": "Elija un almacén de la empresa."})
    producto = Producto.objects.filter(
        pk=producto_id, organizacion_id=empresa.organizacion_id, tipo=TipoProducto.BIEN
    ).first()
    if producto is None:
        raise ValidationError({"producto": "Elija un producto (bien) del catálogo."})

    # Se bloquea la fila vigente para que dos personas no pisen la misma asignación.
    actual = (
        UbicacionProducto.objects.select_for_update()
        .filter(empresa=empresa, almacen=almacen, producto=producto)
        .select_related("ubicacion")
        .first()
    )
    anterior = actual.ubicacion.codigo if actual else None

    if ubicacion_id is None:
        if actual is not None:
            actual.delete()
            _auditar(empresa, almacen, producto, anterior, None)
        return None

    ubicacion = Ubicacion.objects.filter(
        pk=ubicacion_id, empresa=empresa, almacen=almacen, estado=EstadoRegistro.ACTIVO
    ).first()
    if ubicacion is None:
        raise ValidationError({"ubicacion": "Elija una ubicación activa de ese almacén."})
    if actual is not None and actual.ubicacion_id == ubicacion.pk:
        return actual  # sin cambios

    if actual is None:
        actual = UbicacionProducto(empresa=empresa, almacen=almacen, producto=producto)
    actual.ubicacion = ubicacion
    actual.full_clean(validate_unique=False, validate_constraints=False)
    actual.save()
    _auditar(empresa, almacen, producto, anterior, ubicacion.codigo)
    return actual


def _auditar(empresa, almacen, producto, antes: str | None, despues: str | None) -> None:
    registrar(
        "producto.ubicacion",
        recurso_tipo="producto",
        recurso_id=producto.pk,
        empresa_id=empresa.pk,
        resumen=f"Ubicación de {producto} en {almacen.nombre}: {antes or '—'} → {despues or '—'}",
        detalle={"almacen": almacen.pk, "antes": antes, "despues": despues},
    )
