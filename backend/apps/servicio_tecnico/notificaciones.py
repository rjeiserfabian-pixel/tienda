"""Avisos al cliente por WhatsApp: cuándo se mandan, qué dicen y cómo se registran.

Un aviso automático solo sale si la empresa lo encendió, el cliente aceptó recibirlos al dejar su
equipo y su teléfono sirve. Cada orden recibe como máximo un aviso por evento. Los mensajes cuentan
lo mínimo (código, equipo, estado y el enlace para ver el avance): nunca precios, diagnóstico ni
datos del cliente.
"""

import logging
import re

from django.conf import settings
from django.db import transaction

from . import proveedores
from .models import (
    ConfiguracionAvisos,
    EstadoNotificacion,
    EstadoOrden,
    EventoAviso,
    NotificacionServicio,
    OrdenServicio,
)

logger = logging.getLogger(__name__)

# El estado al que llega la orden → el aviso que corresponde.
EVENTO_POR_ESTADO = {
    EstadoOrden.RECIBIDO: EventoAviso.RECIBIDO,
    EstadoOrden.PENDIENTE_APROBACION: EventoAviso.PRESUPUESTO,
    EstadoOrden.LISTO_ENTREGA: EventoAviso.LISTO,
    EstadoOrden.ENTREGADO: EventoAviso.ENTREGADO,
}
CAMPO_DE_CONFIGURACION = {
    EventoAviso.RECIBIDO: "aviso_recibido",
    EventoAviso.PRESUPUESTO: "aviso_presupuesto",
    EventoAviso.LISTO: "aviso_listo",
    EventoAviso.ENTREGADO: "aviso_entregado",
}

_SOLO_DIGITOS = re.compile(r"\D")


def normalizar_telefono(texto: str) -> str | None:
    """El teléfono como lo pide WhatsApp: solo dígitos y con código de país (Perú por defecto)."""
    digitos = _SOLO_DIGITOS.sub("", texto or "")
    if digitos.startswith("00"):
        digitos = digitos[2:]
    if len(digitos) == 9 and digitos.startswith("9"):
        return f"51{digitos}"  # un celular peruano sin el código
    if len(digitos) == 11 and digitos.startswith("519"):
        return digitos
    if 10 <= len(digitos) <= 15 and not digitos.startswith("0"):
        return digitos  # otro país, ya con su código
    return None


def url_publica(orden: OrdenServicio) -> str:
    """El enlace que ve el cliente (QR, WhatsApp, correo): lleva a la página de la tienda.

    Los enlaces antiguos (``/estado/<código>`` del panel) siguen funcionando con el mismo código.
    """
    if settings.SERVICIO_TECNICO_ENLACE_EN_TIENDA and settings.TIENDA_URL:
        return f"{settings.TIENDA_URL.rstrip('/')}/servicio-tecnico/{orden.token_publico}"
    return f"{settings.SERVICIO_TECNICO_URL_PUBLICA.rstrip('/')}/estado/{orden.token_publico}"


def _primer_nombre(orden: OrdenServicio) -> str:
    nombre = " ".join(orden.cliente.nombre.split())
    return (nombre.split(" ")[0] if nombre else "cliente").title()[:30]


def _nombre_empresa(orden: OrdenServicio) -> str:
    return orden.empresa.nombre_comercial or orden.empresa.razon_social


FRASES = {
    EventoAviso.RECIBIDO: (
        "Hola {nombre}, recibimos tu equipo en {empresa}. Tu orden es {codigo}. "
        "Mira el avance aquí: {enlace}"
    ),
    EventoAviso.PRESUPUESTO: (
        "Hola {nombre}, el presupuesto de tu orden {codigo} está listo para tu aprobación. "
        "Comunícate con {empresa} para confirmarlo. Detalle del avance: {enlace}"
    ),
    EventoAviso.LISTO: (
        "Hola {nombre}, tu equipo de la orden {codigo} ya está listo para recoger en "
        "{empresa}. Más información: {enlace}"
    ),
    EventoAviso.ENTREGADO: (
        "Hola {nombre}, gracias por confiar en {empresa}. Entregamos tu equipo de la orden "
        "{codigo}. Aquí está el resumen y tu garantía: {enlace}"
    ),
}


def texto_del_aviso(evento: str, orden: OrdenServicio) -> str:
    """Lo que se le cuenta al cliente en cada evento."""
    return FRASES[evento].format(
        nombre=_primer_nombre(orden),
        codigo=orden.codigo,
        empresa=_nombre_empresa(orden),
        enlace=url_publica(orden),
    )[:500]


def mensaje_manual(orden: OrdenServicio) -> str:
    """Un texto general para escribirle al cliente por WhatsApp a mano, según cómo va su orden."""
    nombre, empresa = _primer_nombre(orden), _nombre_empresa(orden)
    return (
        f"Hola {nombre}, te escribimos de {empresa} sobre tu orden {orden.codigo}. "
        f"Su estado actual: {orden.get_estado_display()}. "
        f"Puedes ver el avance aquí: {url_publica(orden)}"
    )[:500]


def _debe_avisar(orden: OrdenServicio, evento: str) -> bool:
    """¿La empresa encendió este aviso y el cliente aceptó recibirlos?"""
    if not orden.acepta_whatsapp:
        return False
    config = ConfiguracionAvisos.objects.sin_ambito().filter(empresa_id=orden.empresa_id).first()
    return bool(
        config and config.whatsapp_activo and getattr(config, CAMPO_DE_CONFIGURACION[evento])
    )


def avisar_por_estado(orden: OrdenServicio, estado: str) -> NotificacionServicio | None:
    """Deja el aviso que corresponde a este estado en la bandeja de salida (y lo manda al terminar).

    Va dentro de la transacción del cambio de estado: si este se deshace, el aviso también.
    """
    evento = EVENTO_POR_ESTADO.get(estado)
    if evento is None or not _debe_avisar(orden, evento):
        return None
    if NotificacionServicio.objects.sin_ambito().filter(orden=orden, evento=evento).exists():
        return None  # ya se le avisó esto: no se repite aunque la orden vuelva a pasar por ahí
    telefono = normalizar_telefono(orden.cliente.telefono)
    proveedor = proveedores.obtener()
    omitido = ""
    if telefono is None:
        omitido = "El cliente no tiene un teléfono válido."
    else:
        omitido = proveedor.falta(evento)
    nueva = NotificacionServicio.objects.create(
        empresa_id=orden.empresa_id,
        orden=orden,
        evento=evento,
        telefono=telefono or "",
        mensaje=texto_del_aviso(evento, orden),
        estado=EstadoNotificacion.OMITIDO if omitido else EstadoNotificacion.PENDIENTE,
        detalle=omitido,
    )
    if not omitido:
        from .tasks import enviar_notificacion

        transaction.on_commit(lambda: enviar_notificacion.delay(nueva.pk))
    return nueva


def parametros_de(notificacion: NotificacionServicio) -> tuple[str, ...]:
    """Lo que llena la plantilla: nombre, código y enlace."""
    orden = notificacion.orden
    return (_primer_nombre(orden), orden.codigo, url_publica(orden))
