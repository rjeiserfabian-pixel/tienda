"""Banners del inicio de la tienda: imágenes, enlaces seguros y vigencia.

Las imágenes subidas son entrada NO confiable: solo JPG, PNG o WEBP, se comprueba que decodifican
enteras, se limita el tamaño y los píxeles, se re-codifican a WebP SIN metadatos y se recortan al
tamaño del banner. Nunca se guarda el archivo original. Se sirven por una dirección con su
«versión»: una imagen nueva es otra dirección, así el navegador las guarda un año.
"""

import hashlib
import io
import logging
import re
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.auditoria.servicios import registrar

from .exceptions import DatosInvalidos
from .models import BannerTienda

logger = logging.getLogger(__name__)

TAMANO_MAXIMO = 3 * 1024 * 1024
PIXELES_MAXIMOS = 40_000_000
FORMATOS = {"JPEG", "PNG", "WEBP"}
TAMANOS = {"escritorio": (1600, 600), "movil": (800, 800)}
MAXIMO_PUBLICO = 8
RUTA_PUBLICA = "/api/v1/tienda/banners"
# Un enlace DENTRO de la tienda («/ofertas», «/categoria/laptops?x=1»): empieza con una sola «/».
ENLACE_INTERNO = re.compile(r"^/(?!/)[A-Za-z0-9\-._~/%?=&#]*$")
ENLACE_HTTPS = re.compile(r"^https://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+$")


def validar_enlace(enlace: str) -> str:
    """Solo rutas de la tienda o URL https: nada de «javascript:», «data:» ni «//otro-sitio»."""
    enlace = (enlace or "").strip()
    if not enlace:
        return ""
    if ENLACE_INTERNO.match(enlace) or ENLACE_HTTPS.match(enlace):
        return enlace
    raise DatosInvalidos(
        "El enlace debe ser una dirección de la tienda (ej.: /ofertas) o una URL que empiece con https://."
    )


def procesar(archivo, tamano: str) -> bytes:
    """La imagen ya recortada al tamaño del banner y re-codificada a WebP, o ``DatosInvalidos``."""
    ancho, alto = TAMANOS[tamano]
    if archivo.size > TAMANO_MAXIMO:
        raise DatosInvalidos("La imagen pesa más de 3 MB.")
    try:
        with Image.open(archivo) as original:
            if original.format not in FORMATOS:
                raise DatosInvalidos("Usa una imagen JPG, PNG o WEBP.")
            if original.width * original.height > PIXELES_MAXIMOS:
                raise DatosInvalidos("La imagen es demasiado grande.")
            original.load()  # decodifica todo: detecta archivos truncados o corruptos
            imagen = ImageOps.exif_transpose(original)
            if imagen.mode in ("RGBA", "LA", "P"):
                imagen = imagen.convert("RGBA")
                fondo = Image.new("RGB", imagen.size, (255, 255, 255))
                fondo.paste(imagen, mask=imagen.getchannel("A"))
                imagen = fondo
            else:
                imagen = imagen.convert("RGB")
            imagen = ImageOps.fit(imagen, (ancho, alto), Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            imagen.save(salida, format="WEBP", quality=82, method=4)  # sin EXIF ni metadatos
            return salida.getvalue()
    except DatosInvalidos:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise DatosInvalidos("No se pudo leer la imagen. Prueba con otro archivo.") from None


def _campo(banner: BannerTienda, tamano: str):
    return banner.imagen_escritorio if tamano == "escritorio" else banner.imagen_movil


def _borrar(campo) -> None:
    try:
        if campo and campo.name:
            campo.storage.delete(campo.name)
    except OSError:
        logger.warning("tienda_banner_no_borrado", extra={"nombre": campo.name})


def _version(banner: BannerTienda) -> str:
    huellas = []
    for tamano in TAMANOS:
        campo = _campo(banner, tamano)
        huellas.append(campo.name if campo else "")
    return hashlib.sha256("|".join(huellas).encode()).hexdigest()[:12]


@transaction.atomic
def poner_imagen(banner: BannerTienda, tamano: str, archivo) -> BannerTienda:
    """Guarda (o reemplaza) la imagen de escritorio o de celular del banner."""
    contenido = procesar(archivo, tamano)
    anterior = _campo(banner, tamano)
    nombre_anterior = anterior.name if anterior else ""
    campo = _campo(banner, tamano)
    campo.save(f"{tamano}_{uuid.uuid4().hex}.webp", ContentFile(contenido), save=False)
    banner.version = _version(banner)
    try:
        banner.save()
    except Exception:
        _borrar(campo)  # no dejar archivos huérfanos si la base falla
        raise
    if nombre_anterior:
        campo.storage.delete(nombre_anterior)
    return banner


@transaction.atomic
def quitar_imagen(banner: BannerTienda, tamano: str) -> BannerTienda:
    campo = _campo(banner, tamano)
    if campo:
        _borrar(campo)
        campo.name = ""
        banner.version = _version(banner)
        banner.save()
    return banner


def vigentes(organizacion_id: int):
    ahora = timezone.now()
    from django.db.models import Q

    return (
        BannerTienda.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, activo=True)
        .filter(Q(desde__isnull=True) | Q(desde__lte=ahora))
        .filter(Q(hasta__isnull=True) | Q(hasta__gt=ahora))
        .exclude(imagen_escritorio="")
        .order_by("orden", "id")[:MAXIMO_PUBLICO]
    )


def datos_publicos(banner: BannerTienda) -> dict:
    base = f"{RUTA_PUBLICA}/{banner.pk}"
    return {
        "id": banner.pk,
        "titulo": banner.titulo,
        "subtitulo": banner.subtitulo or None,
        "boton_texto": banner.boton_texto or None,
        "enlace": banner.enlace or None,
        "alt": banner.alt,
        "imagen_escritorio": f"{base}/escritorio/{banner.version}",
        "imagen_movil": f"{base}/movil/{banner.version}" if banner.imagen_movil else None,
    }


def auditar(accion: str, banner: BannerTienda, resumen: str) -> None:
    registrar(accion, recurso_tipo="banner_tienda", recurso_id=banner.pk, resumen=resumen)
