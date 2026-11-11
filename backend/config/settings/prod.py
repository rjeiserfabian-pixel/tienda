"""Producción (VPS). Todo se configura por variables de entorno."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import CIFRADO_CLAVES, USAR_REDIS, env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # obligatorio, sin valor por defecto
DOCS_API_HABILITADA = env.bool("DOCS_API_HABILITADA", default=False)

COOKIE_REFRESH_SECURE = True
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # detrás de Nginx
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# En producción, varios workers exigen caché compartida (permisos, throttling).
if not USAR_REDIS:
    raise ImproperlyConfigured("USAR_REDIS debe ser True en producción.")
if not CIFRADO_CLAVES:
    raise ImproperlyConfigured("CIFRADO_CLAVES es obligatorio en producción.")
