"""Quién entrega los mensajes de WhatsApp. Por defecto, nadie: hay que encenderlo a propósito.

* ``apagado``: no se envía nada (los avisos quedan como «No se envió»).
* ``consola``: solo escribe en el registro; sirve para probar sin mandar mensajes reales.
* ``meta``: WhatsApp Cloud API de Meta. Un aviso que el negocio inicia solo puede ir con una
  plantilla aprobada por Meta, así que cada aviso usa la plantilla configurada para su evento.

La cuenta se toma de lo que el negocio guardó en el panel (``ConfiguracionWhatsApp``). Si el
negocio nunca guardó nada, se usa lo que diga el servidor (variables de entorno), como antes.

El token nunca se escribe en el registro ni en los errores que se guardan.
"""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ErrorProveedor(Exception):
    """El proveedor rechazó el envío y reintentar no ayuda (teléfono inexistente, plantilla…)."""


class ErrorTemporal(Exception):
    """Falló algo pasajero (sin red, límite de tasa, caída del proveedor): se puede reintentar."""


@dataclass(frozen=True, slots=True)
class Mensaje:
    telefono: str  # solo dígitos, con código de país (51987654321)
    evento: str
    texto: str  # el mensaje completo (lo que se le cuenta al cliente)
    parametros: tuple[str, ...]  # lo que llena la plantilla: nombre, código, enlace
    idioma: str = ""  # solo para casos especiales (la prueba de Meta va en inglés)


class Proveedor:
    nombre = "base"

    def configurado(self) -> bool:
        return False

    def falta(self, evento: str) -> str:
        """Por qué no se puede enviar este aviso (vacío si se puede)."""
        return "" if self.configurado() else "El proveedor de WhatsApp no está configurado."

    def enviar(self, mensaje: Mensaje) -> str:  # pragma: no cover - lo define cada proveedor
        raise NotImplementedError


class ProveedorApagado(Proveedor):
    nombre = "apagado"

    def falta(self, evento: str) -> str:
        return "Los avisos por WhatsApp están apagados en el servidor."


class ProveedorConsola(Proveedor):
    nombre = "consola"

    def configurado(self) -> bool:
        return True

    def enviar(self, mensaje: Mensaje) -> str:
        logger.info(
            "whatsapp_simulado",
            extra={"evento": mensaje.evento, "telefono_final": mensaje.telefono[-3:]},
        )
        return "consola"


class ProveedorMeta(Proveedor):
    nombre = "meta"

    def __init__(self, cuenta=None):
        # ``cuenta``: la configuración guardada en el panel. Sin ella, manda el servidor.
        self._cuenta = cuenta

    @property
    def _token(self) -> str:
        return self._cuenta.token if self._cuenta else settings.WHATSAPP_META_TOKEN

    @property
    def _telefono_id(self) -> str:
        return self._cuenta.telefono_id if self._cuenta else settings.WHATSAPP_META_TELEFONO_ID

    @property
    def _version(self) -> str:
        return self._cuenta.version_api if self._cuenta else settings.WHATSAPP_META_VERSION

    @property
    def _idioma(self) -> str:
        return self._cuenta.idioma if self._cuenta else settings.WHATSAPP_META_IDIOMA

    def _plantilla(self, evento: str) -> str:
        plantillas = self._cuenta.plantillas if self._cuenta else settings.WHATSAPP_PLANTILLAS
        return str((plantillas or {}).get(evento) or "").strip()

    def configurado(self) -> bool:
        return bool(self._token and self._telefono_id)

    def falta(self, evento: str) -> str:
        if not self.configurado():
            return "Falta el token o el número de WhatsApp Business en el servidor."
        if not self._plantilla(evento):
            return "Falta la plantilla aprobada de WhatsApp para este aviso."
        return ""

    def enviar(self, mensaje: Mensaje) -> str:
        url = f"https://graph.facebook.com/{self._version}/{self._telefono_id}/messages"
        cuerpo = {
            "messaging_product": "whatsapp",
            "to": mensaje.telefono,
            "type": "template",
            "template": {
                "name": self._plantilla(mensaje.evento),
                "language": {"code": mensaje.idioma or self._idioma},
            },
        }
        if mensaje.parametros:  # una plantilla sin variables (la de prueba de Meta) no lleva cuerpo
            cuerpo["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in mensaje.parametros],
                }
            ]
        try:
            respuesta = requests.post(
                url,
                json=cuerpo,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=settings.WHATSAPP_TIMEOUT,
            )
        except requests.RequestException:
            raise ErrorTemporal("No se pudo conectar con WhatsApp.") from None
        if respuesta.status_code == 429 or respuesta.status_code >= 500:
            raise ErrorTemporal(
                f"WhatsApp no pudo recibirlo ahora (código {respuesta.status_code})."
            )
        if respuesta.status_code >= 400:
            raise ErrorProveedor(_motivo(respuesta))
        try:
            return str(respuesta.json()["messages"][0]["id"])[:80]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ErrorProveedor("WhatsApp respondió algo inesperado.") from None


def _motivo(respuesta) -> str:
    """El motivo que da Meta, sin datos sensibles y con un largo razonable."""
    try:
        texto = str(respuesta.json().get("error", {}).get("message", ""))
    except (ValueError, AttributeError):
        texto = ""
    return (texto or f"WhatsApp rechazó el mensaje (código {respuesta.status_code}).")[:200]


_PROVEEDORES = {"apagado": ProveedorApagado, "consola": ProveedorConsola, "meta": ProveedorMeta}


def _del_panel(organizacion_id: int) -> Proveedor | None:
    """El proveedor según lo guardado en el panel, o ``None`` si el negocio nunca lo configuró."""
    from apps.organizacion.models import ConfiguracionWhatsApp

    cuenta = (
        ConfiguracionWhatsApp.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()
    )
    if cuenta is None:
        return None
    if cuenta.modo == ConfiguracionWhatsApp.Modo.ACTIVO:
        return ProveedorMeta(cuenta)
    if cuenta.modo == ConfiguracionWhatsApp.Modo.PRUEBA:
        return ProveedorConsola()
    return ProveedorApagado()


def obtener(organizacion_id: int | None = None) -> Proveedor:
    """El proveedor que corresponde: lo del panel si el negocio lo configuró; si no, el servidor
    (uno desconocido se trata como apagado)."""
    if organizacion_id is not None:
        del_panel = _del_panel(organizacion_id)
        if del_panel is not None:
            return del_panel
    return _PROVEEDORES.get(settings.WHATSAPP_PROVEEDOR, ProveedorApagado)()
