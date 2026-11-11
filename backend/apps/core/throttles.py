"""Límites de tasa diferenciados. Usan su propia caché (Redis db 2 en el VPS)."""

from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    """Estricto: para login y recuperación de contraseña (por IP)."""

    scope = "login"

    @property
    def cache(self):
        return caches["throttle"]


class ApiPublicaThrottle(AnonRateThrottle):
    """API pública (tienda, sin autenticar), por IP."""

    scope = "anon"

    @property
    def cache(self):
        return caches["throttle"]


class ConsultaDocumentoThrottle(UserRateThrottle):
    """Consultas a servicios externos de pago (RENIEC/SUNAT): por usuario, para cuidar la cuota."""

    scope = "consultas"

    @property
    def cache(self):
        return caches["throttle"]


class MostradorThrottle(UserRateThrottle):
    """Pantalla de venta: busca, calcula y vuelve a calcular a cada cambio del carrito."""

    scope = "mostrador"

    @property
    def cache(self):
        return caches["throttle"]


class ImportacionThrottle(UserRateThrottle):
    """Importaciones masivas: pocas por hora y por usuario."""

    scope = "importaciones"

    @property
    def cache(self):
        return caches["throttle"]


class ExportacionThrottle(UserRateThrottle):
    """Reportes y libros exportables (Excel/PDF): cuestan más que una consulta, por usuario."""

    scope = "exportaciones"

    @property
    def cache(self):
        return caches["throttle"]


class ApiAutenticadaThrottle(UserRateThrottle):
    """API autenticada, por usuario."""

    scope = "usuario"

    @property
    def cache(self):
        return caches["throttle"]


class TiendaThrottle(AnonRateThrottle):
    """Tienda pública (catálogo, búsqueda), por IP. Con la caché de respuestas alcanza de sobra."""

    scope = "tienda"

    @property
    def cache(self):
        return caches["throttle"]


class TiendaFotosThrottle(AnonRateThrottle):
    """Fotos de la tienda pública: una página trae muchas, así que el tope es mayor."""

    scope = "tienda_fotos"

    @property
    def cache(self):
        return caches["throttle"]


class TiendaCuentaThrottle(AnonRateThrottle):
    """Cuenta, carrito y pedido del cliente de la tienda, por IP."""

    scope = "tienda_cuenta"

    @property
    def cache(self):
        return caches["throttle"]


class TiendaWebhookThrottle(AnonRateThrottle):
    """Avisos de Culqi (webhook): llegan de pocas direcciones, así que el tope es más alto."""

    scope = "tienda_webhook"

    @property
    def cache(self):
        return caches["throttle"]
