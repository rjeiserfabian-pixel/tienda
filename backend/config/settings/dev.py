"""Desarrollo local."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])
DOCS_API_HABILITADA = env.bool("DOCS_API_HABILITADA", default=True)
LOG_JSON = env.bool("LOG_JSON", default=False)
COOKIE_REFRESH_SECURE = env.bool("COOKIE_REFRESH_SECURE", default=False)  # http://localhost
TIENDA_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
