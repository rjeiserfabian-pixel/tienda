"""Logo de la empresa: se valida, se re-codifica a PNG (sin metadatos) y se guarda.

El archivo subido es entrada no confiable. Solo se aceptan JPG, PNG o WEBP (nunca SVG: puede
llevar código), se comprueba que decodifica entero y se reduce a un tamaño razonable. Se
conserva la transparencia, para que el logo quede bien sobre cualquier fondo del comprobante.
"""

import io
import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.auditoria.servicios import registrar
from apps.organizacion.exceptions import LogoInvalido
from apps.organizacion.models import Empresa

logger = logging.getLogger(__name__)

TAMANO_MAXIMO = 2 * 1024 * 1024  # 2 MB
PIXELES_MAXIMOS = 25_000_000  # evita las «bombas» de descompresión
FORMATOS = {"JPEG", "PNG", "WEBP"}
LADO_MAXIMO = 800


def procesar(archivo) -> bytes:
    """Devuelve el PNG ya re-codificado, o lanza ``LogoInvalido``."""
    if archivo.size > TAMANO_MAXIMO:
        raise LogoInvalido("El logo pesa más de 2 MB.")
    try:
        with Image.open(archivo) as original:
            if original.format not in FORMATOS:
                raise LogoInvalido("Usa un logo JPG, PNG o WEBP.")
            if original.width * original.height > PIXELES_MAXIMOS:
                raise LogoInvalido("La imagen es demasiado grande.")
            original.load()  # decodifica todo: detecta archivos truncados o corruptos
            imagen = ImageOps.exif_transpose(original)
            imagen = imagen.convert("RGBA")
            imagen.thumbnail((LADO_MAXIMO, LADO_MAXIMO), Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            imagen.save(salida, format="PNG", optimize=True)  # sin EXIF ni otros metadatos
            return salida.getvalue()
    except LogoInvalido:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise LogoInvalido("No se pudo leer la imagen. Prueba con otro archivo.") from None


def _borrar_archivo(campo) -> None:
    try:
        if campo and campo.name:
            campo.storage.delete(campo.name)
    except OSError:
        logger.warning("logo_empresa_no_borrado", extra={"nombre": campo.name})


@transaction.atomic
def guardar(empresa: Empresa, archivo) -> Empresa:
    contenido = procesar(archivo)
    anterior = empresa.logo.name
    empresa.logo.save(f"logo_{uuid.uuid4().hex}.png", ContentFile(contenido), save=False)
    try:
        empresa.save(update_fields=["logo"])
    except Exception:
        _borrar_archivo(empresa.logo)  # no dejar archivos huérfanos si la base falla
        raise
    if anterior:
        empresa.logo.storage.delete(anterior)
    registrar(
        "empresa.logo_actualizado",
        recurso_tipo="empresa",
        recurso_id=empresa.pk,
        empresa_id=empresa.pk,
        resumen=f"Logo de {empresa.razon_social} actualizado",
    )
    return empresa


@transaction.atomic
def quitar(empresa: Empresa) -> Empresa:
    if not empresa.logo:
        return empresa
    _borrar_archivo(empresa.logo)
    empresa.logo = ""
    empresa.save(update_fields=["logo"])
    registrar(
        "empresa.logo_eliminado",
        recurso_tipo="empresa",
        recurso_id=empresa.pk,
        empresa_id=empresa.pk,
        resumen=f"Logo de {empresa.razon_social} eliminado",
    )
    return empresa
