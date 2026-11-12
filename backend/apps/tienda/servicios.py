"""Marca de la tienda: logo propio (distinto del de cada empresa) y datos públicos de contacto."""

import hashlib
import io
import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageChops

from apps.auditoria.servicios import registrar
from apps.organizacion.models import Empresa
from apps.organizacion.services import logo as servicio_logo

from .models import ConfiguracionTienda

logger = logging.getLogger(__name__)

RUTA_LOGO = "/api/v1/tienda/logo"
# El logo se muestra a ~50 px de alto (hasta ~300 de ancho): 600×240 cubre pantallas retina sobrado.
LOGO_MAX_ANCHO = 600
LOGO_MAX_ALTO = 240
LOGO_CALIDAD = 90


def _borrar(campo) -> None:
    try:
        if campo and campo.name:
            campo.storage.delete(campo.name)
    except OSError:
        logger.warning("tienda_logo_no_borrado", extra={"nombre": campo.name})


MARGEN_LOGO = 4  # píxeles que se dejan alrededor del dibujo


def recortar_margenes(png: bytes) -> bytes:
    """Quita los márgenes vacíos del logo (transparentes o del color del fondo).

    Muchos logos vienen con mucho aire alrededor y, al mostrarlos con un alto fijo en la cabecera,
    el dibujo queda diminuto. Si no hay nada que recortar o algo sale mal, se deja tal cual.
    """
    try:
        with Image.open(io.BytesIO(png)) as original:
            imagen = original.convert("RGBA")
        transparente = imagen.getchannel("A").getextrema()[0] < 255
        if transparente:
            caja = imagen.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        else:
            fondo = Image.new("RGBA", imagen.size, imagen.getpixel((0, 0)))
            dif = ImageChops.difference(imagen, fondo).convert("L")
            caja = dif.point(lambda v: 255 if v > 24 else 0).getbbox()
        if not caja:
            return png
        izq, arr, der, aba = caja
        caja = (
            max(izq - MARGEN_LOGO, 0),
            max(arr - MARGEN_LOGO, 0),
            min(der + MARGEN_LOGO, imagen.width),
            min(aba + MARGEN_LOGO, imagen.height),
        )
        if caja == (0, 0, imagen.width, imagen.height):
            return png
        salida = io.BytesIO()
        imagen.crop(caja).save(salida, format="PNG", optimize=True)
        return salida.getvalue()
    except (OSError, ValueError):
        return png


def reducir_logo(png: bytes) -> tuple[bytes, str]:
    """Achica el logo y lo pasa a WebP (con transparencia): de ~200 KB a ~15 KB sin que se note.

    Devuelve ``(contenido, extension)``. Si algo sale mal se deja el PNG tal cual (``"png"``).
    """
    try:
        with Image.open(io.BytesIO(png)) as original:
            imagen = original.convert("RGBA")
        imagen.thumbnail((LOGO_MAX_ANCHO, LOGO_MAX_ALTO), Image.Resampling.LANCZOS)
        salida = io.BytesIO()
        imagen.save(salida, format="WEBP", quality=LOGO_CALIDAD, method=6)
        return salida.getvalue(), "webp"
    except (OSError, ValueError):
        logger.warning("tienda_logo_no_reducido")
        return png, "png"


def tipo_de_logo(config: ConfiguracionTienda) -> str:
    """Tipo de archivo del logo guardado (los logos viejos son PNG; los nuevos, WebP)."""
    return "image/webp" if (config.logo.name or "").lower().endswith(".webp") else "image/png"


@transaction.atomic
def guardar_logo(config: ConfiguracionTienda, archivo) -> ConfiguracionTienda:
    """Valida (reglas del logo de empresa), recorta márgenes, lo achica a WebP y lo guarda."""
    contenido, extension = reducir_logo(recortar_margenes(servicio_logo.procesar(archivo)))
    anterior = config.logo.name
    config.logo.save(f"logo_{uuid.uuid4().hex}.{extension}", ContentFile(contenido), save=False)
    config.logo_version = hashlib.sha256(contenido).hexdigest()[:12]
    try:
        config.save(update_fields=["logo", "logo_version"])
    except Exception:
        _borrar(config.logo)  # no dejar archivos huérfanos si la base falla
        raise
    if anterior:
        config.logo.storage.delete(anterior)
    registrar(
        "tienda.logo_actualizado",
        recurso_tipo="configuracion_tienda",
        recurso_id=config.pk,
        resumen="Logo de la tienda actualizado",
    )
    return config


@transaction.atomic
def quitar_logo(config: ConfiguracionTienda) -> ConfiguracionTienda:
    if not config.logo:
        return config
    _borrar(config.logo)
    config.logo = ""
    config.logo_version = ""
    config.save(update_fields=["logo", "logo_version"])
    registrar(
        "tienda.logo_eliminado",
        recurso_tipo="configuracion_tienda",
        recurso_id=config.pk,
        resumen="Logo de la tienda eliminado",
    )
    return config


def empresa_principal(organizacion_id: int) -> Empresa | None:
    """La empresa «cara» del grupo: de ella salen los datos que la tienda no tenga propios."""
    base = Empresa.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    return base.filter(es_principal=True).first() or base.order_by("pk").first()


def _o_none(valor: str):
    valor = (valor or "").strip()
    return valor or None


def datos_publicos(config: ConfiguracionTienda) -> dict:
    """Lo que el público ve de la marca, contacto y textos. Lo vacío vale ``None``.

    Teléfono, correo y dirección, si la tienda no puso los suyos, salen de la empresa principal.
    Solo datos pensados para el público: nunca nada interno.
    """
    empresa = empresa_principal(config.organizacion_id)
    return {
        "nombre": config.nombre,
        "descripcion": _o_none(config.descripcion),
        "logo": f"{RUTA_LOGO}/{config.logo_version}"
        if config.logo and config.logo_version
        else None,
        "color": _o_none(config.color_principal),
        "nombre_junto_al_logo": config.nombre_junto_al_logo,
        "contacto": {
            "whatsapp": _o_none(config.whatsapp),
            "telefono": _o_none(config.telefono) or _o_none(getattr(empresa, "telefono", "")),
            "correo": _o_none(config.correo) or _o_none(getattr(empresa, "correo", "")),
            "direccion": _o_none(config.direccion)
            or _o_none(getattr(empresa, "direccion_fiscal", "")),
            "horario": _o_none(config.horario),
            "mapa_url": _o_none(config.mapa_url),
        },
        "redes": {
            "facebook": _o_none(config.facebook),
            "instagram": _o_none(config.instagram),
            "tiktok": _o_none(config.tiktok),
            "youtube": _o_none(config.youtube),
        },
        "avisos": [a for a in (config.avisos or []) if str(a).strip()][:3],
        "portada": {
            "etiqueta": _o_none(config.portada_etiqueta),
            "titulo": _o_none(config.portada_titulo),
            "subtitulo": _o_none(config.portada_subtitulo),
        },
        "servicio": {
            "visible": config.servicio_visible,
            "titulo": _o_none(config.servicio_titulo),
            "texto": _o_none(config.servicio_texto),
            "puntos": [p for p in (config.servicio_puntos or []) if str(p).strip()][:4],
        },
        "garantia_texto": _o_none(config.garantia_texto),
        "entrega_texto": _o_none(config.entrega_texto),
        "legal": {
            "razon_social": getattr(empresa, "razon_social", None),
            "nombre_comercial": _o_none(getattr(empresa, "nombre_comercial", "")),
            "ruc": getattr(empresa, "ruc", None),
            "libro_reclamaciones_url": _o_none(config.libro_reclamaciones_url),
            "terminos_url": _o_none(config.terminos_url),
            "privacidad_url": _o_none(config.privacidad_url),
        },
    }
