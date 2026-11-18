"""WhatsApp Business: qué avisos existen y la guía para configurarlo.

Un aviso que el negocio inicia (el cliente no escribió primero) solo puede ir con una
PLANTILLA que Meta haya aprobado. Aquí están los avisos del sistema con un texto sugerido para
pegar al crear cada plantilla. Los parámetros siempre van en este orden: {{1}} nombre del
cliente, {{2}} código o número, {{3}} enlace para ver el detalle.
"""

import re

PRUEBA = "PRUEBA"  # plantilla para el botón «Enviar mensaje de prueba»

EVENTOS = (
    # (clave, módulo, nombre para el negocio, texto sugerido de la plantilla)
    (
        "RECIBIDO",
        "Servicio técnico",
        "Equipo recibido",
        "Hola {{1}}, recibimos tu equipo. Tu código de orden es {{2}}. Sigue el avance aquí: {{3}}",
    ),
    (
        "PRESUPUESTO",
        "Servicio técnico",
        "Presupuesto por aprobar",
        "Hola {{1}}, ya tenemos el presupuesto de tu orden {{2}}. Revísalo y apruébalo aquí: {{3}}",
    ),
    (
        "LISTO",
        "Servicio técnico",
        "Equipo listo para recoger",
        "Hola {{1}}, tu equipo de la orden {{2}} está listo para recoger. Detalles: {{3}}",
    ),
    (
        "ENTREGADO",
        "Servicio técnico",
        "Equipo entregado (garantía)",
        "Hola {{1}}, gracias por confiar en nosotros. Entregamos tu orden {{2}}. Garantía: {{3}}",
    ),
    (
        "PEDIDO_PAGADO",
        "Tienda",
        "Pedido pagado",
        "Hola {{1}}, recibimos el pago de tu pedido {{2}}. Puedes ver su estado aquí: {{3}}",
    ),
    (
        "PEDIDO_ADELANTO",
        "Tienda",
        "Adelanto recibido (falta el saldo al recoger)",
        "Hola {{1}}, recibimos tu adelanto del pedido {{2}}. Pagas el saldo al recoger. {{3}}",
    ),
    (
        "PEDIDO_RECORDATORIO",
        "Tienda",
        "Recordatorio: recoge tu pedido (vence pronto)",
        "Hola {{1}}, tu pedido {{2}} te espera en tienda y su plazo vence pronto. {{3}}",
    ),
    (
        "PEDIDO_NO_RECOGIDO",
        "Tienda",
        "Pedido no recogido a tiempo",
        "Hola {{1}}, el plazo para recoger tu pedido {{2}} terminó. Detalles: {{3}}",
    ),
    (
        "PEDIDO_RESENA",
        "Tienda",
        "Pedido de reseña (unos días después de entregar)",
        "Hola {{1}}, ¿qué tal tu pedido {{2}}? Cuéntanos tu opinión aquí: {{3}}",
    ),
    (
        "PEDIDO_VOUCHER",
        "Tienda",
        "Comprobante de transferencia recibido",
        "Hola {{1}}, recibimos tu comprobante del pedido {{2}}. Lo verificaremos pronto: {{3}}",
    ),
    (
        "PEDIDO_PAGO_RECHAZADO",
        "Tienda",
        "Transferencia no verificada (sube otro comprobante)",
        "Hola {{1}}, no pudimos verificar tu pago del pedido {{2}}. Revisa el motivo aquí: {{3}}",
    ),
    (
        "PEDIDO_PREPARACION",
        "Tienda",
        "Pedido en preparación",
        "Hola {{1}}, estamos preparando tu pedido {{2}}. Seguimiento: {{3}}",
    ),
    (
        "PEDIDO_ENVIADO",
        "Tienda",
        "Pedido enviado",
        "Hola {{1}}, tu pedido {{2}} ya salió. Mira los datos de seguimiento aquí: {{3}}",
    ),
    (
        "PEDIDO_LISTO",
        "Tienda",
        "Pedido listo para recoger",
        "Hola {{1}}, tu pedido {{2}} está listo para recoger en tienda. Detalles: {{3}}",
    ),
    (
        "PEDIDO_ENTREGADO",
        "Tienda",
        "Pedido entregado",
        "Hola {{1}}, tu pedido {{2}} fue entregado. ¡Gracias por tu compra! {{3}}",
    ),
    (
        "PEDIDO_CANCELADO",
        "Tienda",
        "Pedido cancelado",
        "Hola {{1}}, tu pedido {{2}} fue cancelado. Si tienes dudas, mira aquí: {{3}}",
    ),
)

CLAVES = {e[0] for e in EVENTOS} | {PRUEBA}
_NOMBRE_PLANTILLA = re.compile(r"^[a-z0-9_]{1,80}$")  # así las nombra Meta


def nombre_de_plantilla_valido(nombre: str) -> bool:
    return bool(_NOMBRE_PLANTILLA.match(nombre))


def catalogo() -> list[dict]:
    return [
        {"clave": clave, "modulo": modulo, "nombre": nombre, "texto_sugerido": texto}
        for clave, modulo, nombre, texto in EVENTOS
    ]


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
