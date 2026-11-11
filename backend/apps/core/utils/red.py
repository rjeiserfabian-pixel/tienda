"""Datos de red de la petición."""

from django.conf import settings


def ip_cliente(request) -> str | None:
    """IP del cliente respetando SOLO los proxies de confianza (``NUM_PROXIES``).

    Con ``NUM_PROXIES = 0`` se usa ``REMOTE_ADDR``. Detrás de Nginx (1 proxy) se toma
    el elemento correspondiente de ``X-Forwarded-For``; lo que el cliente haya
    escrito antes de ese punto se ignora, así no se puede falsificar la IP.
    """
    remota = request.META.get("REMOTE_ADDR") or None
    proxies = settings.NUM_PROXIES
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not proxies or not reenviada:
        return remota
    cadena = [parte.strip() for parte in reenviada.split(",") if parte.strip()]
    if len(cadena) < proxies:
        return remota
    return cadena[-proxies]
