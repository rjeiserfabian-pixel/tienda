"""Avisos al cliente por sus pedidos: correo y WhatsApp, con su registro (bandeja de salida).

* Cada cambio importante del pedido (pagado, en preparación, enviado, listo, entregado, cancelado)
  genera un aviso por cada canal. Cada aviso queda anotado en ``AvisoPedido`` (uno por pedido,
  evento y canal): así se ve si el cliente fue avisado y nunca se repite el mismo aviso.
* WhatsApp solo se usa si el cliente lo aceptó, tiene un celular válido y el negocio configuró su
  cuenta (pantalla «WhatsApp Business»). Un aviso que el negocio inicia debe ir con una plantilla
  aprobada por Meta: los parámetros son siempre nombre, número de pedido y enlace.
* El correo de confirmación de pago y los de «enviado» y «listo para recoger» ya existían: siguen
  igual y solo anotan aquí cómo salieron. Los de «en preparación», «entregado» y «cancelado» se
  mandan desde aquí.
"""

import logging
import re
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.organizacion.whatsapp import normalizar_telefono
from apps.servicio_tecnico import proveedores

from . import adelantos
from .models import AvisoPedido, PedidoTienda

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado

EVENTO_POR_ESTADO = {
    Estado.PAGADO: "PEDIDO_PAGADO",
    Estado.ADELANTO_PAGADO: "PEDIDO_ADELANTO",
    Estado.EN_PREPARACION: "PEDIDO_PREPARACION",
    Estado.ENVIADO: "PEDIDO_ENVIADO",
    Estado.LISTO_PARA_RECOJO: "PEDIDO_LISTO",
    Estado.ENTREGADO: "PEDIDO_ENTREGADO",
    Estado.CANCELADO: "PEDIDO_CANCELADO",
    Estado.NO_RECOGIDO: "PEDIDO_NO_RECOGIDO",
}

# Eventos cuyo correo ya lo manda otra parte (se anota aquí, pero no se manda dos veces).
CORREO_PROPIO = {"PEDIDO_PAGADO", "PEDIDO_ADELANTO", "PEDIDO_ENVIADO", "PEDIDO_LISTO"}

NOMBRES = {
    "PEDIDO_PAGADO": "Pedido pagado",
    "PEDIDO_ADELANTO": "Adelanto recibido",
    "PEDIDO_PREPARACION": "Pedido en preparación",
    "PEDIDO_ENVIADO": "Pedido enviado",
    "PEDIDO_LISTO": "Pedido listo para recoger",
    "PEDIDO_ENTREGADO": "Pedido entregado",
    "PEDIDO_CANCELADO": "Pedido cancelado",
    "PEDIDO_RECORDATORIO": "Recordatorio: recoge tu pedido",
    "PEDIDO_NO_RECOGIDO": "Pedido no recogido",
    "PEDIDO_RESENA": "Pedido de reseña",
    "PEDIDO_VOUCHER": "Comprobante de transferencia recibido",
    "PEDIDO_PAGO_RECHAZADO": "Transferencia no verificada",
}

_REPETIDO = re.compile(r"_\d+$")


def evento_base(evento: str) -> str:
    """Los avisos que pueden repetirse llevan un número al final (``..._2``): sin él es el tipo."""
    return _REPETIDO.sub("", evento)


MAXIMO_INTENTOS = 5


def enlace_del_pedido(pedido: PedidoTienda) -> str:
    return f"{settings.TIENDA_URL.rstrip('/')}/cuenta/pedidos/{pedido.numero}"


def _primer_nombre(pedido: PedidoTienda) -> str:
    nombre = " ".join((pedido.cuenta.nombres or "").split())
    return (nombre.split(" ")[0] if nombre else "cliente").title()[:30]


def _anotar(pedido: PedidoTienda, evento: str, canal: str, **campos) -> AvisoPedido | None:
    """Crea el aviso si no existía. Devuelve ``None`` si ya estaba (no se repite)."""
    aviso, creado = AvisoPedido.objects.sin_ambito().get_or_create(
        pedido=pedido,
        evento=evento,
        canal=canal,
        defaults={"organizacion_id": pedido.organizacion_id, **campos},
    )
    return aviso if creado else None


# ---------------------------------------------------------------------------
# Correo
# ---------------------------------------------------------------------------
def anotar_correo(pedido: PedidoTienda, evento: str, *, enviado: bool, detalle: str = "") -> None:
    """Deja anotado cómo salió un correo que mandó otra parte (confirmación, enviado, listo)."""
    aviso = _anotar(
        pedido,
        evento,
        AvisoPedido.Canal.CORREO,
        destino=pedido.cuenta.correo[:150],
        estado=AvisoPedido.Estado.ENVIADO if enviado else AvisoPedido.Estado.OMITIDO,
        intentos=1,
        detalle=detalle[:255],
        enviado_en=timezone.now() if enviado else None,
    )
    if aviso is None:  # ya estaba: se actualiza (por ejemplo, un reenvío)
        AvisoPedido.objects.sin_ambito().filter(
            pedido=pedido, evento=evento, canal=AvisoPedido.Canal.CORREO
        ).update(
            estado=AvisoPedido.Estado.ENVIADO if enviado else AvisoPedido.Estado.OMITIDO,
            detalle=detalle[:255],
            enviado_en=timezone.now() if enviado else None,
        )


def _texto_correo(pedido: PedidoTienda, evento: str) -> tuple[str, str] | None:
    nombre = pedido.cuenta.nombres
    cierre = f"\nPuedes ver tu pedido en {enlace_del_pedido(pedido)}"
    if evento == "PEDIDO_PREPARACION":
        return (
            f"Estamos preparando tu pedido {pedido.numero}",
            f"Hola {nombre},\n\nYa estamos preparando tu pedido {pedido.numero}. "
            f"Te avisaremos cuando salga o esté listo.\n{cierre}",
        )
    if evento == "PEDIDO_ENTREGADO":
        return (
            f"Tu pedido {pedido.numero} fue entregado",
            f"Hola {nombre},\n\nTu pedido {pedido.numero} fue entregado. ¡Gracias por tu compra!\n"
            f"Si algo no está bien, escríbenos y lo resolvemos.\n{cierre}",
        )
    if evento == "PEDIDO_RECORDATORIO" and pedido.adelanto_vence_en:
        vence = timezone.localtime(pedido.adelanto_vence_en).strftime("%d/%m/%Y %H:%M")
        return (
            f"Recuerda recoger tu pedido {pedido.numero}",
            f"Hola {nombre},\n\nTu pedido {pedido.numero} te espera en tienda hasta el {vence}. "
            f"Pagas el saldo de S/ {pedido.saldo} al recogerlo.\n"
            f"{adelantos.texto_condiciones(pedido)}\n{cierre}",
        )
    if evento == "PEDIDO_NO_RECOGIDO":
        devuelto = pedido.adelanto_monto - pedido.adelanto_retenido
        if devuelto > 0:
            suerte = (
                f"Te devolvemos S/ {devuelto} del adelanto (según tu banco, puede tardar unos "
                f"días en verse). Retuvimos S/ {pedido.adelanto_retenido}, como se te explicó "
                "al pagar."
            )
        else:
            suerte = "Como se te explicó al pagar, el adelanto no se devuelve."
        return (
            f"Tu pedido {pedido.numero} no se recogió a tiempo",
            f"Hola {nombre},\n\nEl plazo para recoger tu pedido {pedido.numero} terminó y lo "
            f"liberamos para otros clientes.\n{suerte}\n{cierre}",
        )
    if evento == "PEDIDO_RESENA":
        from . import resenas

        return resenas.texto_del_correo(pedido)
    if evento == "PEDIDO_VOUCHER":
        return (
            f"Recibimos tu comprobante del pedido {pedido.numero}",
            f"Hola {nombre},\n\nRecibimos tu comprobante de transferencia del pedido "
            f"{pedido.numero}. Lo verificaremos y te avisaremos apenas esté confirmado.\n{cierre}",
        )
    if evento_base(evento) == "PEDIDO_PAGO_RECHAZADO":
        return (
            f"No pudimos verificar tu pago del pedido {pedido.numero}",
            f"Hola {nombre},\n\nNo pudimos verificar tu transferencia del pedido "
            f"{pedido.numero}.\nMotivo: {pedido.transferencia_rechazo}\n"
            f"Puedes subir otro comprobante hasta el "
            f"{timezone.localtime(pedido.expira_en).strftime('%d/%m/%Y %H:%M')}.\n{cierre}",
        )
    if evento == "PEDIDO_CANCELADO":
        return (
            f"Tu pedido {pedido.numero} fue cancelado",
            f"Hola {nombre},\n\nTu pedido {pedido.numero} fue cancelado. "
            f"Si ya habías pagado, te devolveremos el dinero.\n{cierre}",
        )
    return None


def enviar_correo_nuevo(pedido: PedidoTienda, evento: str) -> None:
    """Los correos que se mandan desde aquí (en preparación, entregado, cancelado)."""
    if evento in CORREO_PROPIO:
        return
    texto = _texto_correo(pedido, evento)
    if texto is None:
        return
    aviso = _anotar(
        pedido,
        evento,
        AvisoPedido.Canal.CORREO,
        destino=pedido.cuenta.correo[:150],
        estado=AvisoPedido.Estado.PENDIENTE,
    )
    if aviso is None:
        return  # ya se le avisó esto
    asunto, cuerpo = texto
    aviso.intentos = 1
    try:
        send_mail(asunto, cuerpo, None, [pedido.cuenta.correo], fail_silently=False)
    except Exception:  # noqa: BLE001 - un correo caído no debe romper nada; queda anotado
        logger.exception("tienda_aviso_correo_fallido", extra={"pedido_id": pedido.pk})
        aviso.estado = AvisoPedido.Estado.FALLIDO
        aviso.detalle = "No se pudo enviar el correo."
    else:
        aviso.estado = AvisoPedido.Estado.ENVIADO
        aviso.enviado_en = timezone.now()
    aviso.save(update_fields=["intentos", "estado", "detalle", "enviado_en"])


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------
def _oculto(telefono: str | None) -> str:
    """El teléfono sin mostrarlo entero (solo los últimos 3 dígitos)."""
    return f"{'•' * 6}{telefono[-3:]}" if telefono else ""


def preparar_whatsapp(pedido: PedidoTienda, evento: str) -> AvisoPedido | None:
    """Anota el aviso de WhatsApp. Devuelve el aviso PENDIENTE (listo para enviar) o ``None``.

    Si el cliente no aceptó WhatsApp no se anota nada. Si lo aceptó pero no se puede enviar
    (sin celular, cuenta apagada o sin plantilla), queda anotado como «no se envió» con el motivo.
    """
    cuenta = pedido.cuenta
    if not cuenta.acepta_whatsapp:
        return None
    telefono = normalizar_telefono(cuenta.celular)
    proveedor = proveedores.obtener(pedido.organizacion_id)
    omitido = ""
    if telefono is None:
        omitido = "El cliente no tiene un celular válido."
    else:
        omitido = proveedor.falta(evento_base(evento))
    aviso = _anotar(
        pedido,
        evento,
        AvisoPedido.Canal.WHATSAPP,
        destino=_oculto(telefono),
        estado=AvisoPedido.Estado.OMITIDO if omitido else AvisoPedido.Estado.PENDIENTE,
        detalle=omitido[:255],
    )
    if aviso is None or omitido:
        return None
    return aviso


def parametros(pedido: PedidoTienda) -> tuple[str, str, str]:
    return (_primer_nombre(pedido), pedido.numero, enlace_del_pedido(pedido))


def enlace_whatsapp_manual(pedido: PedidoTienda) -> dict | None:
    """Para que el personal le escriba al cliente a mano mientras no haya cuenta de WhatsApp."""
    telefono = normalizar_telefono(pedido.cuenta.celular)
    if telefono is None:
        return None
    mensaje = (
        f"Hola {_primer_nombre(pedido)}, te escribimos por tu pedido {pedido.numero}. "
        f"Estado: {pedido.get_estado_display()}. Puedes verlo aquí: {enlace_del_pedido(pedido)}"
    )
    return {"telefono": telefono, "url": f"https://wa.me/{telefono}?text={quote(mensaje)}"}


def mandar_whatsapp(aviso_id: int) -> str:
    """Envía un aviso de WhatsApp. Lanza ``ErrorTemporal`` si conviene reintentar."""
    aviso = (
        AvisoPedido.objects.sin_ambito()
        .select_related("pedido__cuenta")
        .filter(pk=aviso_id)
        .first()
    )
    if aviso is None or aviso.estado != AvisoPedido.Estado.PENDIENTE:
        return "omitido"  # ya salió, ya falló o no existe: enviar dos veces sería peor
    pedido = aviso.pedido
    telefono = normalizar_telefono(pedido.cuenta.celular)
    if telefono is None:
        _cerrar(aviso, AvisoPedido.Estado.OMITIDO, "El cliente no tiene un celular válido.")
        return "omitido"
    proveedor = proveedores.obtener(pedido.organizacion_id)
    aviso.intentos += 1
    mensaje = proveedores.Mensaje(
        telefono=telefono,
        evento=evento_base(aviso.evento),
        texto=f"{NOMBRES.get(evento_base(aviso.evento), aviso.evento)}: {pedido.numero}",
        parametros=parametros(pedido),
    )
    try:
        externo = proveedor.enviar(mensaje)
    except proveedores.ErrorTemporal as error:
        if aviso.intentos >= MAXIMO_INTENTOS:
            _cerrar(aviso, AvisoPedido.Estado.FALLIDO, f"Se agotaron los reintentos: {error}")
            return "fallido"
        aviso.detalle = str(error)[:255]
        aviso.save(update_fields=["intentos", "detalle"])
        raise
    except proveedores.ErrorProveedor as error:
        _cerrar(aviso, AvisoPedido.Estado.FALLIDO, str(error))
        return "fallido"
    aviso.externo_id = externo
    aviso.enviado_en = timezone.now()
    _cerrar(aviso, AvisoPedido.Estado.ENVIADO, "")
    return "enviado"


def _cerrar(aviso: AvisoPedido, estado: str, detalle: str) -> None:
    aviso.estado = estado
    aviso.detalle = detalle[:255]
    aviso.save(update_fields=["intentos", "estado", "detalle", "externo_id", "enviado_en"])


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def procesar(pedido_id: int, evento: str) -> list[int]:
    """Anota y manda los avisos de un evento. Devuelve los de WhatsApp que hay que enviar."""
    pedido = PedidoTienda.objects.sin_ambito().select_related("cuenta").get(pk=pedido_id)
    enviar_correo_nuevo(pedido, evento)
    aviso = preparar_whatsapp(pedido, evento)
    return [aviso.pk] if aviso else []


def encolar(pedido_id: int, evento: str) -> None:
    """Pide que se manden los avisos de este evento (fuera de la petición del usuario)."""
    from .tasks import avisar_pedido

    avisar_pedido.delay(pedido_id, evento)


def salida(pedido: PedidoTienda) -> list[dict]:
    """Los avisos del pedido, para la ficha del panel."""
    return [
        {
            "evento": a.evento,
            "nombre": NOMBRES.get(evento_base(a.evento), a.evento),
            "canal": a.canal,
            "canal_nombre": a.get_canal_display(),
            "destino": a.destino,
            "estado": a.estado,
            "estado_nombre": a.get_estado_display(),
            "detalle": a.detalle,
            "fecha": (a.enviado_en or a.creado_en).isoformat(),
        }
        for a in AvisoPedido.objects.sin_ambito().filter(pedido=pedido).order_by("id")
    ]
