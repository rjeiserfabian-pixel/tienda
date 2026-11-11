"""Vouchers y comprobantes de los movimientos: foto o PDF.

El archivo subido es entrada no confiable. Las fotos (JPG, PNG o WEBP) se abren con Pillow, se
comprueba que decodifican enteras y se vuelven a guardar como WebP sin metadatos (GPS, cámara). Un
PDF solo se acepta si empieza como PDF y no pasa del tamaño máximo; se entrega siempre como
descarga. El nombre guardado es aleatorio: el que trae el archivo nunca se usa como ruta.
"""

import io
import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.auditoria.servicios import registrar

from .exceptions import AdjuntoInvalido, MovimientoNoAnulable
from .models import AdjuntoMovimiento, MovimientoCaja
from .servicios import _exigir_empresa
from .sesiones import nombre_de

logger = logging.getLogger(__name__)

TAMANO_MAXIMO = 5 * 1024 * 1024
PIXELES_MAXIMOS = 40_000_000
LADO_MAXIMO = 2000
MAX_POR_MOVIMIENTO = 5
FORMATOS_IMAGEN = {"JPEG", "PNG", "WEBP"}
WEBP = "image/webp"
PDF = "application/pdf"


def _imagen_a_webp(archivo) -> bytes:
    try:
        with Image.open(archivo) as original:
            if original.format not in FORMATOS_IMAGEN:
                raise AdjuntoInvalido("Use una foto JPG, PNG o WEBP, o un PDF.")
            if original.width * original.height > PIXELES_MAXIMOS:
                raise AdjuntoInvalido("La imagen es demasiado grande.")
            original.load()  # decodifica todo: detecta archivos truncados o corruptos
            imagen = ImageOps.exif_transpose(original)
            if imagen.mode in ("RGBA", "LA", "P"):
                imagen = imagen.convert("RGBA")
                fondo = Image.new("RGB", imagen.size, (255, 255, 255))
                fondo.paste(imagen, mask=imagen.getchannel("A"))
                imagen = fondo
            else:
                imagen = imagen.convert("RGB")
            imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            imagen.save(salida, format="WEBP", quality=85, method=4)
            return salida.getvalue()
    except AdjuntoInvalido:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise AdjuntoInvalido(
            "No se pudo leer la imagen. Pruebe con otra foto o con un PDF."
        ) from None


def procesar(archivo) -> tuple[bytes, str]:
    """Devuelve ``(contenido, tipo)`` ya revisado, o lanza ``AdjuntoInvalido``."""
    if archivo.size > TAMANO_MAXIMO:
        raise AdjuntoInvalido("El archivo pesa más de 5 MB.")
    cabecera = archivo.read(5)
    archivo.seek(0)
    if cabecera == b"%PDF-":
        return archivo.read(), PDF
    return _imagen_a_webp(archivo), WEBP


@transaction.atomic
def agregar(movimiento: MovimientoCaja, archivo, usuario) -> AdjuntoMovimiento:
    _exigir_empresa(movimiento.empresa)
    if movimiento.estado != MovimientoCaja.Estado.EMITIDO:
        raise MovimientoNoAnulable("El movimiento está anulado: no admite más adjuntos.")
    if AdjuntoMovimiento.objects.filter(movimiento=movimiento).count() >= MAX_POR_MOVIMIENTO:
        raise AdjuntoInvalido(f"Un movimiento admite hasta {MAX_POR_MOVIMIENTO} adjuntos.")
    contenido, tipo = procesar(archivo)
    adjunto = AdjuntoMovimiento(
        empresa=movimiento.empresa,
        movimiento=movimiento,
        tipo_contenido=tipo,
        nombre_original=" ".join((getattr(archivo, "name", "") or "").split())[:120],
        tamano=len(contenido),
        subido_por_nombre=nombre_de(usuario),
    )
    extension = "pdf" if tipo == PDF else "webp"
    adjunto.archivo.save(f"{uuid.uuid4().hex}.{extension}", ContentFile(contenido), save=False)
    try:
        adjunto.save()
    except Exception:
        _borrar_archivo(adjunto)  # no dejar archivos huérfanos si la base falla
        raise
    registrar(
        "caja.adjunto_agregado",
        recurso_tipo="movimiento_caja",
        recurso_id=movimiento.pk,
        empresa_id=movimiento.empresa_id,
        resumen=f"Voucher agregado al movimiento N° {movimiento.numero:06d}",
        detalle={"tipo": tipo, "tamano": adjunto.tamano},
    )
    return adjunto


def _borrar_archivo(adjunto: AdjuntoMovimiento) -> None:
    try:
        if adjunto.archivo and adjunto.archivo.name:
            adjunto.archivo.storage.delete(adjunto.archivo.name)
    except OSError:
        logger.warning("adjunto_caja_no_borrado", extra={"adjunto_id": adjunto.pk})


@transaction.atomic
def eliminar(adjunto: AdjuntoMovimiento, usuario) -> None:
    _exigir_empresa(adjunto.empresa)
    _borrar_archivo(adjunto)
    adjunto.delete()  # borrado lógico: el registro queda, el archivo ya no
    registrar(
        "caja.adjunto_eliminado",
        recurso_tipo="movimiento_caja",
        recurso_id=adjunto.movimiento_id,
        empresa_id=adjunto.empresa_id,
        resumen="Voucher quitado de un movimiento",
        detalle={"por": nombre_de(usuario)},
    )
