"""Páginas de texto de la tienda (términos, privacidad, cambios, envíos) que edita el negocio.

Son texto plano: los párrafos se separan con una línea en blanco y una línea que termina en «:» o
empieza con «# » se muestra como subtítulo. No se acepta HTML (no hay nada que pueda romper o
infectar la página). Solo las páginas publicadas son visibles; las demás quedan como borrador.
"""

import re

from django.db import transaction

from apps.auditoria.servicios import registrar

from . import catalogo
from .exceptions import DatosInvalidos, PedidoNoEncontrado
from .models import PaginaLegal

CATALOGO = (
    ("terminos", "Términos y condiciones"),
    ("privacidad", "Política de privacidad"),
    ("cambios-y-devoluciones", "Cambios y devoluciones"),
    ("envios", "Política de envíos"),
)
TITULOS = dict(CATALOGO)
MAX_CONTENIDO = 30000
MIN_PUBLICADA = 50
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Esquemas de apoyo: solo los títulos, para que el negocio (o su abogado) complete el contenido.
SUGERENCIAS = {
    "terminos": (
        "# Quiénes somos\n[Razón social, RUC y domicilio]\n\n# Cómo comprar\n[Pasos, precios, IGV, "
        "comprobantes]\n\n# Medios de pago\n[Tarjeta, Yape, transferencia]\n\n# Entrega\n[Plazos "
        "y zonas]\n\n# Cambios, devoluciones y garantía\n[Condiciones]\n\n# Libro de "
        "Reclamaciones\n[Cómo presentar un reclamo]"
    ),
    "privacidad": (
        "# Qué datos recogemos\n[Nombre, documento, correo, teléfono, direcciones]\n\n# Para qué "
        "los usamos\n[Procesar pedidos, emitir comprobantes, avisos de tu compra]\n\n# Con quién "
        "los compartimos\n[Pasarela de pago, transporte]\n\n# Cuánto tiempo los guardamos\n[Plazo]"
        "\n\n# Tus derechos\n[Acceso, rectificación, cancelación y oposición; cómo ejercerlos]"
    ),
    "cambios-y-devoluciones": (
        "# Cuándo puedes pedir un cambio o devolución\n[Plazo y condiciones]\n\n# Productos que no "
        "tienen cambio\n[Excepciones]\n\n# Cómo solicitarlo\n[Pasos y contacto]\n\n# Cómo te "
        "devolvemos el dinero\n[Medio y plazo]"
    ),
    "envios": (
        "# Zonas y costos de envío\n[Resumen]\n\n# Plazos de entrega\n[Por zona]\n\n# Recojo en "
        "tienda\n[Direcciones y horarios]\n\n# Si tu pedido llega con algún problema\n[Qué hacer]"
    ),
}


def _limpio(texto: str) -> str:
    texto = _CONTROL.sub("", texto or "").replace("\r\n", "\n").replace("\r", "\n")
    lineas = [linea.rstrip() for linea in texto.strip().split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas))


def listar_admin(organizacion_id: int) -> list[dict]:
    existentes = {
        p.slug: p for p in PaginaLegal.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    }
    salida = []
    for slug, titulo in CATALOGO:
        p = existentes.get(slug)
        salida.append(
            {
                "slug": slug,
                "titulo": titulo,
                "contenido": p.contenido if p else "",
                "publicada": bool(p and p.publicada),
                "actualizada": p.actualizado_en.isoformat() if p else None,
                "sugerencia": SUGERENCIAS[slug],
            }
        )
    return salida


def guardar(organizacion_id: int, slug: str, *, contenido: str, publicada: bool) -> dict:
    if slug not in TITULOS:
        raise PedidoNoEncontrado("Esa página no existe.")
    contenido = _limpio(contenido)
    if len(contenido) > MAX_CONTENIDO:
        raise DatosInvalidos(f"El texto admite hasta {MAX_CONTENIDO} caracteres.")
    if publicada and len(contenido) < MIN_PUBLICADA:
        raise DatosInvalidos("Escribe el contenido completo antes de publicarla.")
    with transaction.atomic():
        pagina = (
            PaginaLegal.objects.sin_ambito()
            .select_for_update()
            .filter(organizacion_id=organizacion_id, slug=slug)
            .first()
        )
        if pagina is None:
            pagina = PaginaLegal(organizacion_id=organizacion_id, slug=slug)
        pagina.titulo = TITULOS[slug]
        pagina.contenido = contenido
        pagina.publicada = publicada
        pagina.save()
        registrar(
            "tienda.pagina_legal_guardada",
            recurso_tipo="pagina_legal",
            recurso_id=pagina.pk,
            organizacion_id=organizacion_id,
            resumen=f"Página «{pagina.titulo}» {'publicada' if publicada else 'en borrador'}",
        )
        transaction.on_commit(catalogo.invalidar)
    return next(p for p in listar_admin(organizacion_id) if p["slug"] == slug)


def publicadas(organizacion_id: int) -> list[dict]:
    """Las páginas visibles (para el pie de la tienda)."""
    visibles = set(
        PaginaLegal.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, publicada=True)
        .exclude(contenido="")
        .values_list("slug", flat=True)
    )
    return [{"slug": s, "titulo": t} for s, t in CATALOGO if s in visibles]


def leer(organizacion_id: int, slug: str) -> dict:
    pagina = (
        PaginaLegal.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, slug=slug, publicada=True)
        .exclude(contenido="")
        .first()
    )
    if pagina is None:
        raise PedidoNoEncontrado("No encontramos esa página.")
    return {
        "slug": pagina.slug,
        "titulo": pagina.titulo,
        "contenido": pagina.contenido,
        "actualizada": pagina.actualizado_en.isoformat(),
    }
