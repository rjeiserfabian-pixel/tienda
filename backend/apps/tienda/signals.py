"""Cuando cambia algo que la tienda muestra, se invalidan sus respuestas guardadas."""

from django.db import transaction
from django.db.models.signals import post_save


def _invalidar(sender, **kwargs):
    from . import catalogo

    # Después de confirmar el cambio: si no, otra visita podría volver a guardar lo viejo.
    transaction.on_commit(catalogo.invalidar)


def conectar() -> None:
    from apps.mantenimiento.models import (
        CampoEspecificacion,
        Categoria,
        Familia,
        FotoProducto,
        Marca,
        PrecioProducto,
        Producto,
    )
    from apps.organizacion.models import Empresa

    from .models import ConfiguracionArmador, ConfiguracionPago, ConfiguracionTienda

    for modelo in (
        Producto,
        FotoProducto,
        PrecioProducto,
        Categoria,
        Familia,
        Marca,
        CampoEspecificacion,
        ConfiguracionTienda,
        ConfiguracionPago,
        ConfiguracionArmador,
        Empresa,
    ):
        post_save.connect(
            _invalidar, sender=modelo, dispatch_uid=f"tienda_invalidar_{modelo.__name__}"
        )
