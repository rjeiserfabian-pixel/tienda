import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="tienda.enviar_correo_cuenta")
def enviar_correo_cuenta(cuenta_id: int, tipo: str, ip: str | None = None) -> bool:
    """Envía el correo de confirmación, recuperación o aviso fuera de la petición."""
    from . import cuentas

    return cuentas.enviar_correo(cuenta_id, tipo, ip)


@shared_task(name="tienda.purgar_sesiones")
def purgar_sesiones() -> dict:
    """Retención: borra sesiones vencidas o revocadas y enlaces usados o vencidos."""
    from .models import SesionCuenta, TokenCuenta

    limite = timezone.now() - timedelta(days=7)
    sesiones, _ = SesionCuenta.objects.filter(Q(revocada=True) | Q(expira_en__lt=limite)).delete()
    tokens, _ = TokenCuenta.objects.filter(
        Q(expira_en__lt=timezone.now()) | Q(usado_en__isnull=False)
    ).delete()
    logger.info("tienda_sesiones_purgadas", extra={"sesiones": sesiones, "tokens": tokens})
    return {"sesiones": sesiones, "tokens": tokens}


@shared_task(name="tienda.enviar_confirmacion_pedido")
def enviar_confirmacion_pedido(pedido_id: int) -> bool:
    """Correo de confirmación del pedido pagado (sin datos de la tarjeta)."""
    from . import pagar

    return pagar.enviar_confirmacion(pedido_id)


@shared_task(name="tienda.reintentar_comprobantes")
def reintentar_comprobantes() -> int:
    """Reintenta emitir el comprobante de los pedidos ya cobrados que quedaron a medias."""
    from . import pagar

    return pagar.reintentar_comprobantes()


@shared_task(name="tienda.enviar_aviso_pedido")
def enviar_aviso_pedido(pedido_id: int, nota: str = "") -> bool:
    """Avisa al cliente que su pedido salió o está listo para recoger."""
    from . import gestion

    return gestion.enviar_aviso(pedido_id, nota)


@shared_task(name="tienda.expirar_pedidos")
def expirar_pedidos() -> int:
    """Vence los pedidos sin pagar y suelta el stock que tenían apartado."""
    from . import pedidos

    return pedidos.expirar_vencidos()


@shared_task(name="tienda.renovar_tienda")
def renovar_tienda() -> bool:
    """Avisa a la tienda (Next.js) que renueve sus páginas guardadas porque algo cambió.

    Es un aviso de servidor a servidor con un secreto compartido. Si falla no pasa nada grave: la
    tienda se renueva sola por tiempo (1 a 2 minutos).
    """
    import requests
    from django.conf import settings

    if not settings.TIENDA_RENOVAR_URL or not settings.TIENDA_RENOVAR_TOKEN:
        return False
    try:
        r = requests.post(
            settings.TIENDA_RENOVAR_URL,
            headers={"Authorization": f"Bearer {settings.TIENDA_RENOVAR_TOKEN}"},
            timeout=(2, 5),
            allow_redirects=False,
        )
    except requests.RequestException:
        logger.warning("tienda_renovar_sin_respuesta")
        return False
    if r.status_code != 200:
        logger.warning("tienda_renovar_rechazada", extra={"http": r.status_code})
    return r.status_code == 200


@shared_task(name="tienda.revisar_ofertas")
def revisar_ofertas() -> bool:
    """Cada minuto: si una oferta empezó o terminó, renueva lo que la tienda tiene guardado."""
    from . import ofertas

    return ofertas.revisar_cambios()


@shared_task(name="tienda.enviar_correo_reembolso")
def enviar_correo_reembolso(reembolso_id: int) -> bool:
    """Avisa al cliente que se le devolvió su dinero."""
    from . import reembolsos

    return reembolsos.enviar_correo(reembolso_id)


@shared_task(name="tienda.reintentar_reembolsos")
def reintentar_reembolsos() -> int:
    """Reintenta los reembolsos que Culqi no confirmó (nunca devuelve dos veces)."""
    from . import reembolsos

    return reembolsos.reintentar_pendientes()
