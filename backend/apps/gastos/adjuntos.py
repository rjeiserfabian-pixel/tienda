"""Comprobantes de los gastos: foto o PDF, con la misma revisión que los vouchers de caja.

El archivo subido es entrada no confiable: las fotos se vuelven a guardar como WebP sin metadatos y
un PDF solo se acepta si empieza como PDF. El nombre guardado es aleatorio.
"""

import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.caja import adjuntos as revision
from apps.caja.exceptions import AdjuntoInvalido
from apps.caja.sesiones import nombre_de

from .exceptions import GastoNoModificable
from .models import AdjuntoGasto, Gasto
from .servicios import _exigir_empresa

logger = logging.getLogger(__name__)

MAX_POR_GASTO = 5


@transaction.atomic
def agregar(gasto: Gasto, archivo, usuario) -> AdjuntoGasto:
    _exigir_empresa(gasto.empresa)
    if gasto.estado != Gasto.Estado.EMITIDO:
        raise GastoNoModificable("El gasto está anulado: no admite más adjuntos.")
    if AdjuntoGasto.objects.filter(gasto=gasto).count() >= MAX_POR_GASTO:
        raise AdjuntoInvalido(f"Un gasto admite hasta {MAX_POR_GASTO} adjuntos.")
    contenido, tipo = revision.procesar(archivo)
    adjunto = AdjuntoGasto(
        empresa=gasto.empresa,
        gasto=gasto,
        tipo_contenido=tipo,
        nombre_original=" ".join((getattr(archivo, "name", "") or "").split())[:120],
        tamano=len(contenido),
        subido_por_nombre=nombre_de(usuario),
    )
    extension = "pdf" if tipo == revision.PDF else "webp"
    adjunto.archivo.save(f"{uuid.uuid4().hex}.{extension}", ContentFile(contenido), save=False)
    try:
        adjunto.save()
    except Exception:
        _borrar_archivo(adjunto)  # no dejar archivos huérfanos si la base falla
        raise
    registrar(
        "gastos.adjunto_agregado",
        recurso_tipo="gasto",
        recurso_id=gasto.pk,
        empresa_id=gasto.empresa_id,
        resumen=f"Comprobante agregado al gasto N° {gasto.numero:06d}",
        detalle={"tipo": tipo, "tamano": adjunto.tamano},
    )
    return adjunto


def _borrar_archivo(adjunto: AdjuntoGasto) -> None:
    try:
        if adjunto.archivo and adjunto.archivo.name:
            adjunto.archivo.storage.delete(adjunto.archivo.name)
    except OSError:
        logger.warning("adjunto_gasto_no_borrado", extra={"adjunto_id": adjunto.pk})


@transaction.atomic
def eliminar(adjunto: AdjuntoGasto, usuario) -> None:
    _exigir_empresa(adjunto.empresa)
    _borrar_archivo(adjunto)
    adjunto.delete()  # borrado lógico: el registro queda, el archivo ya no
    registrar(
        "gastos.adjunto_eliminado",
        recurso_tipo="gasto",
        recurso_id=adjunto.gasto_id,
        empresa_id=adjunto.empresa_id,
        resumen="Comprobante quitado de un gasto",
        detalle={"por": nombre_de(usuario)},
    )
