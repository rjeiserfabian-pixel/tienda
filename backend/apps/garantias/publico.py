"""Lo que el cliente ve de su garantía sin iniciar sesión (con el QR o con serie y documento).

Solo sale lo que no compromete a nadie: el producto, su serie, las fechas, si sigue vigente, el
reclamo en curso y cómo contactar a la tienda. NUNCA salen precios, el nombre ni el documento del
cliente, ni el costo del producto.
"""

import re

from django.conf import settings
from django.utils import timezone

from .models import EstadoGarantia, Garantia, ReclamoGarantia

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
_DOCUMENTO = re.compile(r"^[A-Za-z0-9]{6,20}$")
POR_VENCER_DIAS = 30

CONDICIONES = (
    "La garantía cubre defectos de fabricación y fallas de funcionamiento durante el plazo "
    "indicado, contado desde la fecha de venta.",
    "No cubre daños por golpes, caídas, humedad o líquidos, mala instalación o manipulación, "
    "uso indebido, sobrecargas eléctricas ni el desgaste normal.",
    "Pierde validez si el producto fue abierto, reparado o modificado por terceros, o si su "
    "número de serie fue alterado o retirado.",
    "Para hacerla efectiva presente este certificado o el comprobante de venta.",
    "La reparación o el cambio del producto no amplía el plazo original de la garantía.",
)

TEXTO_SITUACION = {
    "VIGENTE": "Tu garantía está vigente.",
    "POR_VENCER": "Tu garantía está por vencer.",
    "VENCIDA": "Tu garantía ya venció.",
    "ANULADA": "Esta garantía fue anulada (la compra se anuló o el producto se devolvió).",
    "REEMPLAZADA": "Este producto fue cambiado por otro; el nuevo tiene su propia garantía.",
}


def situacion_de(garantia: Garantia, hoy=None) -> str:
    """VIGENTE, POR_VENCER (30 días o menos), VENCIDA, ANULADA o REEMPLAZADA."""
    if garantia.estado in (EstadoGarantia.ANULADA, EstadoGarantia.REEMPLAZADA):
        return garantia.estado
    if not garantia.vigente(hoy):
        return "VENCIDA"
    return "POR_VENCER" if garantia.dias_restantes(hoy) <= POR_VENCER_DIAS else "VIGENTE"


def url_publica(garantia: Garantia) -> str:
    return f"{settings.TIENDA_URL.rstrip('/')}/garantia/{garantia.token_publico}"


def garantia_por_token(token: str) -> Garantia | None:
    """La garantía de ese enlace, o ``None`` (un token mal escrito no toca la base de datos)."""
    if not _TOKEN.fullmatch(token or ""):
        return None
    return (
        Garantia.objects.sin_ambito()
        .select_related("empresa", "producto", "comprobante")
        .filter(token_publico=token)
        .first()
    )


def token_por_serie_y_documento(serie: str, documento: str) -> str | None:
    """El código de la garantía de esa serie comprada con ese documento (DNI o RUC), si existe.

    Hace falta acertar las DOS cosas: así nadie puede recorrer series para ver garantías ajenas.
    """
    serie = " ".join(str(serie or "").split()).upper()[:40]
    documento = "".join(str(documento or "").split())
    if not serie or not _DOCUMENTO.fullmatch(documento):
        return None
    garantia = (
        Garantia.objects.sin_ambito()
        .filter(numero_serie=serie, cliente_documento__iexact=documento)
        .order_by("-id")
        .first()
    )
    return garantia.token_publico if garantia else None


def estado_publico(garantia: Garantia) -> dict:
    hoy = timezone.localdate()
    situacion = situacion_de(garantia, hoy)
    # Sin sesión no hay ámbito activo: el reclamo se lee a propósito sin él.
    reclamo = ReclamoGarantia.objects.sin_ambito().filter(garantia=garantia).order_by("-id").first()
    empresa = garantia.empresa
    return {
        "producto": {
            "nombre": garantia.producto.nombre,
            "numero_serie": garantia.numero_serie,
            "unidades": 1 if garantia.numero_serie else int(garantia.cantidad),
        },
        "comprobante": garantia.comprobante.numero_completo,
        "garantia": {
            "meses": garantia.meses,
            "desde": garantia.fecha_inicio.isoformat(),
            "hasta": garantia.vence_el.isoformat(),
            "situacion": situacion,
            "texto": TEXTO_SITUACION[situacion],
            "dias_restantes": garantia.dias_restantes(hoy),
            "vigente": garantia.vigente(hoy),
        },
        "reclamo": (
            {
                "numero": reclamo.numero_completo,
                "fecha": reclamo.fecha.isoformat(),
                "estado": reclamo.estado,
                "estado_texto": reclamo.get_estado_display(),
            }
            if reclamo
            else None
        ),
        "condiciones": list(CONDICIONES),
        "empresa": {
            "nombre": empresa.nombre_comercial or empresa.razon_social,
            "telefono": empresa.telefono,
            "correo": empresa.correo,
            "direccion": empresa.direccion_fiscal,
        },
    }
