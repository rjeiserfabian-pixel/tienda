"""Configuración base compartida por todos los entornos.

Todo valor sensible o dependiente del entorno se lee de variables de entorno
(archivo ``backend/.env``). Ningún secreto vive en el código.
"""

import re
from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/

env = environ.Env()
# No pisa variables ya definidas en el sistema (útil en el VPS / contenedores).
environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Núcleo
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Terceros
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # Proyecto
    "apps.core",
    "apps.organizacion",
    "apps.seguridad",
    "apps.auditoria",
    "apps.mantenimiento",
    "apps.inventario",
    "apps.compras",
    "apps.caja",
    "apps.gastos",
    "apps.ventas",
    "apps.servicio_tecnico",
    "apps.facturacion",
    "apps.rrhh",
    "apps.panel",
    "apps.tienda",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "apps.core.middleware.ContextoPeticionMiddleware",
    "apps.core.middleware.CabecerasApiMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.LimpiarContextoTenantMiddleware",
]

ROOT_URLCONF = "config.urls"
# Ruta del admin de Django; en producción conviene cambiarla por una no obvia.
ADMIN_URL = env("ADMIN_URL", default="admin/")
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Base de datos (PostgreSQL)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST", default="localhost"),
        "PORT": env("DB_PORT", default="5432"),
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Redis (caché, throttling y Celery)
# ---------------------------------------------------------------------------
# USAR_REDIS=False en desarrollo local sin Redis: caché en memoria y Celery
# ejecutando las tareas en el mismo proceso. En el VPS: USAR_REDIS=True.
USAR_REDIS = env.bool("USAR_REDIS", default=False)
# REDIS_URL acepta con o sin número de base; se normaliza sin él.
_REDIS_BASE = re.sub(r"/\d+/?$", "", env("REDIS_URL", default="redis://localhost:6379").rstrip("/"))
REDIS_DB_CACHE, REDIS_DB_CELERY, REDIS_DB_THROTTLE = 0, 1, 2


def _redis_url(db: int) -> str:
    return f"{_REDIS_BASE}/{db}"


if USAR_REDIS:
    _opciones_redis = {
        "CLIENT_CLASS": "django_redis.client.DefaultClient",
        "SOCKET_CONNECT_TIMEOUT": 5,
        "SOCKET_TIMEOUT": 5,
    }
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url(REDIS_DB_CACHE),
            "OPTIONS": _opciones_redis,
            "KEY_PREFIX": "tienda",
            "TIMEOUT": 300,
        },
        "throttle": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url(REDIS_DB_THROTTLE),
            "OPTIONS": _opciones_redis,
            "KEY_PREFIX": "tienda-throttle",
        },
    }
    CELERY_BROKER_URL = _redis_url(REDIS_DB_CELERY)
    CELERY_RESULT_BACKEND = _redis_url(REDIS_DB_CELERY)
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "tienda-default",
        },
        "throttle": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "tienda-throttle",
        },
    }
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=not USAR_REDIS)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TIMEZONE = "America/Lima"

# ---------------------------------------------------------------------------
# Autenticación y contraseñas
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "seguridad.Usuario"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",  # solo para verificar hashes antiguos
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

ACCESS_TOKEN_MINUTOS = 15
REFRESH_TOKEN_DIAS = 7

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=ACCESS_TOKEN_MINUTOS),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=REFRESH_TOKEN_DIAS),
    "ALGORITHM": "HS256",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "UPDATE_LAST_LOGIN": False,  # lo gestiona el servicio de login
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- Sesiones y login (Fase 2) ---
SESION_MAXIMA_DIAS = 30  # tope absoluto aunque se siga refrescando
SESION_NO_PERSISTENTE_HORAS = 12  # sesión sin "mantener activa": caduca tras 12 h sin uso
REFRESH_GRACIA_SEG = 10  # refrescos simultáneos legítimos (dos pestañas)
LOGIN_FALLOS_PARA_BLOQUEO = 5  # luego: 1, 2, 4… minutos (máximo 60)
LOGIN_BLOQUEO_MAX_MINUTOS = 60
LOGIN_FALLOS_VIGENCIA_SEG = 24 * 3600
HISTORIAL_PASSWORDS = 5
COOKIE_REFRESH_NOMBRE = "refresh_token"
COOKIE_REFRESH_RUTA = "/api/v1/seguridad/auth/"
COOKIE_REFRESH_SECURE = env.bool("COOKIE_REFRESH_SECURE", default=True)
# --- Fase 5: MFA, recuperación, auditoría y retención ---
# Consulta de DNI (RENIEC) y RUC (SUNAT) vía Decolecta. El token es un secreto: solo del entorno.
DECOLECTA_URL = env("DECOLECTA_URL", default="https://api.decolecta.com")
DECOLECTA_TOKEN = env("DECOLECTA_TOKEN", default="")
DECOLECTA_TIMEOUT = env.int("DECOLECTA_TIMEOUT", default=8)
# Cuota del plan (el gratuito da 100 consultas al mes). El sistema cuenta lo que gasta y se
# detiene al llegar al límite; el contador oficial está en https://decolecta.com/profile.
DECOLECTA_LIMITE_MENSUAL = env.int("DECOLECTA_LIMITE_MENSUAL", default=100)
# La actualización diaria del tipo de cambio gasta cuota: apagada salvo que se active a propósito.
TIPO_CAMBIO_AUTOMATICO = env.bool("TIPO_CAMBIO_AUTOMATICO", default=False)
TIPO_CAMBIO_FUENTES_AUTOMATICAS = env.list("TIPO_CAMBIO_FUENTES_AUTOMATICAS", default=["SUNAT"])
# Por encima de este porcentaje de la cuota, lo automático se detiene y queda lo manual.
TIPO_CAMBIO_UMBRAL_AUTOMATICO = env.float("TIPO_CAMBIO_UMBRAL_AUTOMATICO", default=0.6)
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

# --- Facturación electrónica: API propia de facturación (envía a SUNAT) ----------------------
# La API recibe en cada petición las claves SOL de la empresa: debe estar en la red privada del
# servidor o con HTTPS, nunca abierta a internet.
SUNAT_API_URL = env("SUNAT_API_URL", default="http://localhost/API_SUNAT/")
SUNAT_API_TIMEOUT = env.int("SUNAT_API_TIMEOUT", default=30)  # segundos esperando su respuesta
# Archivo de cada tipo de documento dentro de la API. La guía de remisión queda vacía hasta que
# se confirme su dirección: mientras tanto el sistema no intenta enviarla.
SUNAT_ENDPOINTS = {
    "01": "post.php",
    "03": "post.php",
    "07": "post.php",
    "08": "post.php",
    "09": env("SUNAT_ENDPOINT_GUIA", default=""),
}

# --- Servicio técnico: consulta pública del estado y avisos por WhatsApp ---------------------
# Dirección pública donde el cliente ve el estado de su equipo (la del QR de la hoja de ingreso).
SERVICIO_TECNICO_URL_PUBLICA = env("SERVICIO_TECNICO_URL_PUBLICA", default=FRONTEND_URL)
# apagado = no envía nada | consola = solo escribe en el log (pruebas) | meta = WhatsApp Cloud API
WHATSAPP_PROVEEDOR = env("WHATSAPP_PROVEEDOR", default="apagado")
WHATSAPP_META_TOKEN = env("WHATSAPP_META_TOKEN", default="")
WHATSAPP_META_TELEFONO_ID = env("WHATSAPP_META_TELEFONO_ID", default="")
WHATSAPP_META_VERSION = env("WHATSAPP_META_VERSION", default="v21.0")
WHATSAPP_META_IDIOMA = env("WHATSAPP_META_IDIOMA", default="es")
WHATSAPP_TIMEOUT = env.int("WHATSAPP_TIMEOUT", default=10)
# Nombre de la plantilla aprobada en Meta para cada aviso. Cuerpo de cada una: {{1}} nombre del
# cliente, {{2}} código de la orden, {{3}} enlace para ver el estado.
WHATSAPP_PLANTILLAS = {
    "RECIBIDO": env("WHATSAPP_PLANTILLA_RECIBIDO", default=""),
    "PRESUPUESTO": env("WHATSAPP_PLANTILLA_PRESUPUESTO", default=""),
    "LISTO": env("WHATSAPP_PLANTILLA_LISTO", default=""),
    "ENTREGADO": env("WHATSAPP_PLANTILLA_ENTREGADO", default=""),
}
MFA_EMISOR = "Sistema Unificado"
MFA_MAX_FALLOS = 5  # códigos erróneos seguidos antes de bloquear los intentos
MFA_BLOQUEO_SEG = 300
MFA_DESAFIO_SEG = 300  # vigencia del paso intermedio entre contraseña y código
MFA_CODIGOS_RECUPERACION = 10
RECUPERACION_VIGENCIA_MIN = 60
RECUPERACION_MAX_SOLICITUDES_HORA = 3  # por identificador, además del throttle por IP
AUDITORIA_RETENCION_DIAS = env.int("AUDITORIA_RETENCION_DIAS", default=730)
SESIONES_RETENCION_DIAS = env.int("SESIONES_RETENCION_DIAS", default=90)

# Correo saliente (recuperación de contraseña). En desarrollo: consola (ver dev.py).
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_TIMEOUT = 10  # nunca esperar indefinidamente al servidor de correo
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Sistema Unificado <no-responder@localhost>")

# Cuántos proxies de confianza hay delante (Nginx = 1). 0 = usar solo REMOTE_ADDR.
# Nunca dejar en None: permitiría falsificar la IP con X-Forwarded-For.
NUM_PROXIES = env.int("NUM_PROXIES", default=0)

# ---------------------------------------------------------------------------
# Internacionalización
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Estáticos
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Archivos subidos (fotos de productos). NO se sirven como públicos: pasan por la API.
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.seguridad.authentication.JWTAutenticacion",
    ],
    "NUM_PROXIES": NUM_PROXIES,
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.PaginaEstandar",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.manejador_errores.manejador_excepciones",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.core.throttles.ApiPublicaThrottle",
        "apps.core.throttles.ApiAutenticadaThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": env("THROTTLE_LOGIN", default="5/min"),
        "consultas": env("THROTTLE_CONSULTAS", default="20/min"),
        "importaciones": env("THROTTLE_IMPORTACIONES", default="20/hour"),
        "exportaciones": env("THROTTLE_EXPORTACIONES", default="60/hour"),
        "usuario": env("THROTTLE_USUARIO", default="120/min"),
        "mostrador": env("THROTTLE_MOSTRADOR", default="600/min"),
        "anon": env("THROTTLE_ANON", default="30/min"),
        "tienda": env("THROTTLE_TIENDA", default="240/min"),
        "tienda_fotos": env("THROTTLE_TIENDA_FOTOS", default="1200/min"),
        "tienda_cuenta": env("THROTTLE_TIENDA_CUENTA", default="60/min"),
        "tienda_webhook": env("THROTTLE_TIENDA_WEBHOOK", default="120/min"),
    },
}

# Tienda virtual pública: organización a la que sirve (solo si hay varias tiendas activas).
TIENDA_ORGANIZACION_ID = env.int("TIENDA_ORGANIZACION_ID", default=None)
# Dirección pública de la tienda: los correos a los clientes llevan enlaces a ella.
TIENDA_URL = env("TIENDA_URL", default="http://localhost:3000")
# Aviso a la tienda para que renueve sus páginas al instante cuando cambia algo (opcional).
# URL de la tienda + secreto compartido; sin ellos la tienda se renueva sola por tiempo.
TIENDA_RENOVAR_URL = env("TIENDA_RENOVAR_URL", default="")
TIENDA_RENOVAR_TOKEN = env("TIENDA_RENOVAR_TOKEN", default="")
# El enlace y el QR del servicio técnico llevan a la TIENDA (/servicio-tecnico/<código>).
# En False vuelven a la página del panel (/estado/<código>); los ya entregados siguen sirviendo.
SERVICIO_TECNICO_ENLACE_EN_TIENDA = env.bool("SERVICIO_TECNICO_ENLACE_EN_TIENDA", default=True)
TIENDA_SESION_DIAS = 30
TIENDA_VERIFICACION_HORAS = 48
TIENDA_RECUPERACION_MIN = 60
TIENDA_CORREOS_MAX_HORA = 3  # correos de confirmación/recuperación por dirección y por hora
TIENDA_PEDIDO_MINUTOS = 30  # cuánto se aparta el stock mientras el cliente paga
TIENDA_PEDIDOS_PENDIENTES_MAX = 3  # pedidos sin pagar a la vez por cliente
TIENDA_COOKIE_SECURE = True  # dev y pruebas lo apagan (http://localhost)

SPECTACULAR_SETTINGS = {
    "TITLE": "Sistema Unificado API",
    "DESCRIPTION": "API multiempresa del Sistema Unificado.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
# Documentación OpenAPI accesible solo si se habilita (se apaga en producción).
DOCS_API_HABILITADA = env.bool("DOCS_API_HABILITADA", default=False)

# ---------------------------------------------------------------------------
# CORS (frontend React)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True  # refresh token en cookie HttpOnly
CORS_ALLOW_HEADERS = [*default_headers, "idempotency-key", "x-request-id", "x-tenant"]
CORS_EXPOSE_HEADERS = ["X-Request-ID"]

# ---------------------------------------------------------------------------
# Cifrado de credenciales (SUNAT, etc.)
# ---------------------------------------------------------------------------
# Formato: "1:<clave fernet>,2:<clave fernet>". La clave actual cifra; todas descifran.
CIFRADO_CLAVES = dict(
    par.split(":", 1) for par in env.list("CIFRADO_CLAVES", default=[]) if ":" in par
)
CIFRADO_CLAVE_ACTUAL = env("CIFRADO_CLAVE_ACTUAL", default="1")

# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------
IDEMPOTENCIA_VIGENCIA_HORAS = 24
IDEMPOTENCIA_TIMEOUT_EN_PROCESO_SEG = 120

# Una salida de dinero no puede dejar una caja de efectivo en negativo (ni un banco sin sobregiro).
CAJA_BLOQUEA_SALDO_NEGATIVO = True

# ---------------------------------------------------------------------------
# Logging estructurado con request_id
# ---------------------------------------------------------------------------
LOG_JSON = env.bool("LOG_JSON", default=True)
LOG_LEVEL = env("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.logging.FiltroRequestId"}},
    "formatters": {
        "json": {"()": "apps.core.logging.FormatoJson"},
        "simple": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "consola": {
            "class": "logging.StreamHandler",
            "filters": ["request_id"],
            "formatter": "json" if LOG_JSON else "simple",
        },
    },
    "root": {"handlers": ["consola"], "level": LOG_LEVEL},
    "loggers": {
        "django.request": {"handlers": ["consola"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["consola"], "level": "WARNING", "propagate": False},
    },
}

# Tareas periodicas (requieren el proceso celery beat; ver docs/DESPLIEGUE_VPS.md).
CELERY_BEAT_SCHEDULE = {
    "purgar-idempotencia": {"task": "core.purgar_idempotencia", "schedule": 24 * 3600},
    "purgar-auditoria": {"task": "auditoria.purgar", "schedule": 24 * 3600},
    "purgar-sesiones": {"task": "seguridad.purgar_sesiones", "schedule": 24 * 3600},
    "purgar-sesiones-tienda": {"task": "tienda.purgar_sesiones", "schedule": 24 * 3600},
    "revisar-ofertas-tienda": {"task": "tienda.revisar_ofertas", "schedule": 60},
    "expirar-pedidos-tienda": {"task": "tienda.expirar_pedidos", "schedule": 300},
    "reintentar-comprobantes-tienda": {"task": "tienda.reintentar_comprobantes", "schedule": 300},
    "reintentar-reembolsos-tienda": {"task": "tienda.reintentar_reembolsos", "schedule": 300},
}
if TIPO_CAMBIO_AUTOMATICO:
    # Lunes a sábado a las 9:30 (hora de Lima): la tasa del día ya está publicada.
    CELERY_BEAT_SCHEDULE["actualizar-tipo-cambio"] = {
        "task": "mantenimiento.actualizar_tipo_cambio",
        "schedule": crontab(hour=9, minute=30, day_of_week="1-6"),
    }
