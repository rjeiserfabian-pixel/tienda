"""Aviso por correo a quien tiene una garantía por vencer.

Reglas:

* Los avisos nacen APAGADOS (``ConfiguracionGarantias.avisos_activos``): cada negocio decide.
* Un solo aviso por garantía, y un solo correo por cliente aunque tenga varias por vencer.
* No se escribe a quien no tiene correo ni a quien pidió no recibir más (enlace de baja del correo).
* El texto es solo informativo: dice qué vence y cuándo, sin ofertas.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.utils import timezone

from apps.core.exceptions import ErrorDominio

from . import publico
from .models import (
    AvisoGarantia,
    BajaAvisoGarantia,
    ConfiguracionGarantias,
    EstadoAviso,
    EstadoGarantia,
    Garantia,
)

logger = logging.getLogger(__name__)

SAL_BAJA = "garantias-baja-avisos"
VIGENCIA_BAJA = 3 * 365 * 24 * 3600  # el enlace de baja sirve 3 años
MAXIMO_INTENTOS = 3
DIAS_POR_DEFECTO = 30


class EnlaceInvalido(ErrorDominio):
    status_code = 400
    codigo = "enlace_invalido"
    mensaje = "El enlace no es válido o ya venció."


def _normal(correo: str) -> str:
    return (correo or "").strip().lower()


# --- baja ------------------------------------------------------------------------------
def token_de_baja(organizacion_id: int, correo: str) -> str:
    return signing.dumps({"o": organizacion_id, "c": _normal(correo)}, salt=SAL_BAJA)


def dar_de_baja(token: str) -> bool:
    """Anota que ese correo no quiere más avisos. Siempre responde igual (no revela nada)."""
    try:
        datos = signing.loads(token or "", salt=SAL_BAJA, max_age=VIGENCIA_BAJA)
        organizacion_id, correo = int(datos["o"]), _normal(datos["c"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        raise EnlaceInvalido() from None
    if correo:
        BajaAvisoGarantia.objects.sin_ambito().get_or_create(
            organizacion_id=organizacion_id, correo=correo
        )
    return True


# --- configuración ---------------------------------------------------------------------
def configuracion_de(organizacion_id: int) -> ConfiguracionGarantias | None:
    return (
        ConfiguracionGarantias.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    )


def datos_de_configuracion(organizacion_id: int) -> dict:
    config = configuracion_de(organizacion_id)
    return {
        "avisos_activos": bool(config and config.avisos_activos),
        "dias_antes": config.dias_antes if config else DIAS_POR_DEFECTO,
    }


# --- a quién se avisa ------------------------------------------------------------------
def candidatas(config: ConfiguracionGarantias, hoy: date | None = None):
    """Garantías activas que vencen dentro de los días configurados y aún sin aviso resuelto."""
    hoy = hoy or timezone.localdate()
    return (
        Garantia.objects.sin_ambito()
        .select_related("empresa", "producto", "cliente")
        .filter(
            empresa__organizacion_id=config.organizacion_id,
            estado=EstadoGarantia.ACTIVA,
            cliente__isnull=False,
            vence_el__gte=hoy,
            vence_el__lte=hoy + timedelta(days=config.dias_antes),
        )
        # Lo enviado no se repite; lo omitido o fallido se reintenta unos días (el cliente pudo
        # agregar su correo) y luego se deja.
        .exclude(aviso__estado=EstadoAviso.ENVIADO)
        .exclude(aviso__intentos__gte=MAXIMO_INTENTOS)
        .order_by("cliente_id", "vence_el", "id")
    )


def _anotar(garantia: Garantia, estado: str, correo: str, detalle: str = "") -> None:
    aviso, _ = AvisoGarantia.objects.sin_ambito().get_or_create(
        garantia=garantia,
        defaults={"empresa": garantia.empresa, "estado": estado, "correo": correo},
    )
    aviso.estado = estado
    aviso.correo = correo
    aviso.detalle = detalle[:250]
    aviso.intentos += 1
    aviso.save(update_fields=["estado", "correo", "detalle", "intentos", "actualizado_en"])


def _texto(garantias: list[Garantia], organizacion_id: int, correo: str) -> tuple[str, str]:
    primera = garantias[0]
    empresa = primera.empresa
    nombre_tienda = empresa.nombre_comercial or empresa.razon_social
    nombre = (primera.cliente.nombre or "").split(" ")[0].title() or "cliente"
    lineas = "\n".join(
        f"  - {g.producto.nombre}{f' (serie {g.numero_serie})' if g.numero_serie else ''}: "
        f"vence el {g.vence_el:%d/%m/%Y} — {publico.url_publica(g)}"
        for g in garantias
    )
    plural = len(garantias) > 1
    asunto = (
        f"Tus garantías están por vencer — {nombre_tienda}"
        if plural
        else f"Tu garantía está por vencer — {nombre_tienda}"
    )
    base = settings.TIENDA_URL.rstrip("/")
    cuerpo = (
        f"Hola {nombre},\n\n"
        f"Te recordamos que {'estas garantías vencen' if plural else 'esta garantía vence'} pronto:"
        f"\n\n{lineas}\n\n"
        "Si tu producto tiene algún problema, tráelo antes de esa fecha con tu comprobante "
        f"o con el certificado de garantía.\n"
        + (f"Teléfono: {empresa.telefono}\n" if empresa.telefono else "")
        + f"\n— {nombre_tienda}\n\n"
        "Recibes este aviso porque compraste en nuestra tienda. Si no quieres recibir más avisos "
        f"de garantía, puedes darte de baja aquí: "
        f"{base}/garantia/baja?t={token_de_baja(organizacion_id, correo)}"
    )
    return asunto, cuerpo


def avisar(config: ConfiguracionGarantias, hoy: date | None = None) -> int:
    """Manda los avisos que tocan a una organización. Devuelve cuántos correos salieron."""
    por_cliente: dict[int, list[Garantia]] = defaultdict(list)
    for g in candidatas(config, hoy):
        por_cliente[g.cliente_id].append(g)
    bajas = set(
        BajaAvisoGarantia.objects.sin_ambito()
        .filter(organizacion_id=config.organizacion_id)
        .values_list("correo", flat=True)
    )
    enviados = 0
    for garantias in por_cliente.values():
        correo = _normal(garantias[0].cliente.correo)
        if not correo:
            for g in garantias:
                _anotar(g, EstadoAviso.OMITIDO, "", "El cliente no tiene correo registrado.")
            continue
        if correo in bajas:
            for g in garantias:
                _anotar(g, EstadoAviso.OMITIDO, correo, "El cliente pidió no recibir avisos.")
            continue
        asunto, cuerpo = _texto(garantias, config.organizacion_id, correo)
        try:
            send_mail(asunto, cuerpo, None, [correo], fail_silently=False)
        except Exception as error:  # noqa: BLE001  (un correo caído no frena a los demás)
            logger.warning("aviso_garantia_fallido", extra={"correo_error": type(error).__name__})
            for g in garantias:
                _anotar(
                    g, EstadoAviso.FALLIDO, correo, f"No se pudo enviar: {type(error).__name__}"
                )
            continue
        for g in garantias:
            _anotar(g, EstadoAviso.ENVIADO, correo)
        enviados += 1
    return enviados


def avisar_todas(hoy: date | None = None) -> int:
    """Para la tarea diaria: cada organización con los avisos encendidos."""
    total = 0
    for config in ConfiguracionGarantias.objects.sin_ambito().filter(avisos_activos=True):
        total += avisar(config, hoy)
    return total
