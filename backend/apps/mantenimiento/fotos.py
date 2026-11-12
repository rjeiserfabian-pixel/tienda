"""Fotos de productos: se validan, se re-codifican a WebP (sin metadatos) y se guardan.

El archivo subido es entrada no confiable. Por eso NO se guarda tal cual: se abre con Pillow (solo
JPG, PNG o WEBP), se comprueba que decodifica entero, se le quita la rotación EXIF y cualquier
metadato (GPS, cámara, comentarios) al volver a codificarlo, y se reduce a un tamaño razonable.
Si el archivo era otra cosa (un SVG, un HTML, un ejecutable renombrado), simplemente no pasa.
"""

import io
import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.auditoria.servicios import registrar

from .exceptions import ImagenInvalida
from .models import FotoProducto

logger = logging.getLogger(__name__)

# 15 MB por foto: se reduce sola (WebP, 1600 px), así se aceptan las fotos directas del celular.
TAMANO_MAXIMO = 15 * 1024 * 1024
PIXELES_MAXIMOS = 40_000_000  # evita las «bombas» de descompresión
FORMATOS = {"JPEG", "PNG", "WEBP"}
MAX_FOTOS = 8
LADO_GRANDE = 1600
LADO_MINIATURA = 400


def _a_webp(imagen: Image.Image, lado: int, calidad: int) -> bytes:
    copia = imagen.copy()
    copia.thumbnail((lado, lado), Image.Resampling.LANCZOS)
    salida = io.BytesIO()
    copia.save(salida, format="WEBP", quality=calidad, method=4)  # sin EXIF ni otros metadatos
    return salida.getvalue()


def procesar(archivo) -> tuple[bytes, bytes]:
    """Devuelve ``(imagen_grande, miniatura)`` ya re-codificadas, o lanza ``ImagenInvalida``."""
    if archivo.size > TAMANO_MAXIMO:
        raise ImagenInvalida("La foto pesa más de 15 MB.")
    try:
        with Image.open(archivo) as original:
            if original.format not in FORMATOS:
                raise ImagenInvalida("Usa una foto JPG, PNG o WEBP.")
            if original.width * original.height > PIXELES_MAXIMOS:
                raise ImagenInvalida("La imagen es demasiado grande.")
            if original.format == "JPEG":
                # Las fotos del celular son enormes: se decodifican ya reducidas (≥ LADO_GRANDE)
                # y así se ahorra memoria.
                original.draft("RGB", (LADO_GRANDE, LADO_GRANDE))
            original.load()  # decodifica todo: detecta archivos truncados o corruptos
            imagen = ImageOps.exif_transpose(original)
            if imagen.mode in ("RGBA", "LA", "P"):  # la transparencia se pasa a fondo blanco
                imagen = imagen.convert("RGBA")
                fondo = Image.new("RGB", imagen.size, (255, 255, 255))
                fondo.paste(imagen, mask=imagen.getchannel("A"))
                imagen = fondo
            else:
                imagen = imagen.convert("RGB")
            return _a_webp(imagen, LADO_GRANDE, 85), _a_webp(imagen, LADO_MINIATURA, 80)
    except ImagenInvalida:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImagenInvalida("No se pudo leer la imagen. Prueba con otra foto.") from None


@transaction.atomic
def agregar(producto, archivo) -> FotoProducto:
    if FotoProducto.objects.filter(producto=producto).count() >= MAX_FOTOS:
        raise ImagenInvalida(f"Un producto admite hasta {MAX_FOTOS} fotos.")
    grande, miniatura = procesar(archivo)
    hay_principal = FotoProducto.objects.filter(producto=producto, es_principal=True).exists()
    nombre = uuid.uuid4().hex
    foto = FotoProducto(
        producto=producto,
        organizacion_id=producto.organizacion_id,
        es_principal=not hay_principal,  # la primera foto es la principal
        orden=FotoProducto.objects.filter(producto=producto).count(),
        nombre_original=(getattr(archivo, "name", "") or "")[:120],
    )
    foto.imagen.save(f"{nombre}.webp", ContentFile(grande), save=False)
    foto.miniatura.save(f"{nombre}_m.webp", ContentFile(miniatura), save=False)
    try:
        foto.save()
    except Exception:
        _borrar_archivos(foto)  # no dejar archivos huérfanos si la base falla
        raise
    registrar(
        "producto.foto_agregada",
        recurso_tipo="producto",
        recurso_id=producto.pk,
        resumen=f"Foto agregada al producto {producto}",
    )
    return foto


def _borrar_archivos(foto: FotoProducto) -> None:
    for campo in (foto.imagen, foto.miniatura):
        try:
            if campo and campo.name:
                campo.storage.delete(campo.name)
        except OSError:
            logger.warning("foto_producto_no_borrada", extra={"foto_id": foto.pk})


@transaction.atomic
def eliminar(foto: FotoProducto) -> None:
    producto = foto.producto
    era_principal = foto.es_principal
    _borrar_archivos(foto)
    foto.delete()  # borrado lógico: el registro queda, el archivo ya no
    if era_principal:
        siguiente = FotoProducto.objects.filter(producto=producto).order_by("orden", "id").first()
        if siguiente is not None:
            siguiente.es_principal = True
            siguiente.save(update_fields=["es_principal"])
    registrar(
        "producto.foto_eliminada",
        recurso_tipo="producto",
        recurso_id=producto.pk,
        resumen=f"Foto eliminada del producto {producto}",
    )


@transaction.atomic
def hacer_principal(foto: FotoProducto) -> FotoProducto:
    FotoProducto.objects.filter(producto=foto.producto).exclude(pk=foto.pk).update(
        es_principal=False
    )
    foto.es_principal = True
    foto.save(update_fields=["es_principal"])
    return foto


@transaction.atomic
def reordenar(producto, ids: list[int]) -> list[FotoProducto]:
    """Deja las fotos en el orden dado; la primera pasa a ser la principal."""
    fotos = {f.pk: f for f in FotoProducto.objects.select_for_update().filter(producto=producto)}
    if len(ids) != len(set(ids)) or set(ids) != set(fotos):
        raise ImagenInvalida("Envíe todas las fotos del producto, una sola vez cada una.")
    for posicion, pk in enumerate(ids):
        foto = fotos[pk]
        foto.orden = posicion
        foto.es_principal = False
        foto.save(update_fields=["orden", "es_principal"])
    primera = fotos[ids[0]] if ids else None
    if primera is not None:
        primera.es_principal = True
        primera.save(update_fields=["es_principal"])
    return [fotos[pk] for pk in ids]
