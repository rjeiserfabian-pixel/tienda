"""Idempotencia para operaciones críticas (cobros, emisión de comprobantes).

Uso desde una vista::

    clave = clave_desde_request(request)
    codigo, datos, repetida = ejecutar_idempotente(
        clave=clave, metodo=request.method, ruta=request.path,
        cuerpo=request.body, operacion=lambda: (201, servicio_cobrar(...)),
    )

Un reintento con la misma clave y el mismo cuerpo devuelve el resultado guardado
sin volver a ejecutar la operación. Misma clave con distinto cuerpo: 422.
"""

import hashlib
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .exceptions import (
    ClaveIdempotenciaRequerida,
    ClaveIdempotenciaReutilizada,
    OperacionEnCurso,
)
from .models import RegistroIdempotencia
from .tenant import obtener_contexto_requerido

_CLAVE_VALIDA = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def clave_desde_request(request) -> str:
    clave = request.headers.get("Idempotency-Key", "")
    if not _CLAVE_VALIDA.match(clave):
        raise ClaveIdempotenciaRequerida()
    return clave


def _hash_peticion(metodo: str, ruta: str, cuerpo: bytes) -> str:
    huella = hashlib.sha256()
    huella.update(f"{metodo.upper()}\n{ruta}\n".encode())
    huella.update(cuerpo or b"")
    return huella.hexdigest()


def ejecutar_idempotente(
    *,
    clave: str,
    metodo: str,
    ruta: str,
    cuerpo: bytes,
    operacion: Callable[[], tuple[int, Any]],
    _reintento: bool = False,
) -> tuple[int, Any, bool]:
    """Ejecuta ``operacion`` una sola vez por (organización, clave).

    ``operacion`` devuelve ``(codigo_http, datos_serializables)``. Retorna
    ``(codigo_http, datos, repetida)``; ``repetida`` es True si se reutilizó
    un resultado guardado.
    """
    contexto = obtener_contexto_requerido()
    huella = _hash_peticion(metodo, ruta, cuerpo)
    ahora = timezone.now()

    try:
        with transaction.atomic():
            registro = RegistroIdempotencia.objects.create(
                organizacion_id=contexto.organizacion_id,
                usuario_id=contexto.usuario_id,
                clave=clave,
                metodo=metodo.upper(),
                ruta=ruta[:255],
                hash_peticion=huella,
                expira_en=ahora + timedelta(hours=settings.IDEMPOTENCIA_VIGENCIA_HORAS),
            )
    except IntegrityError:
        existente = RegistroIdempotencia.objects.get(
            organizacion_id=contexto.organizacion_id, clave=clave
        )
        if existente.hash_peticion != huella:
            raise ClaveIdempotenciaReutilizada() from None
        if existente.estado == RegistroIdempotencia.Estado.COMPLETADO:
            return existente.codigo_http, existente.respuesta, True
        abandonado = ahora - existente.creado_en > timedelta(
            seconds=settings.IDEMPOTENCIA_TIMEOUT_EN_PROCESO_SEG
        )
        if abandonado and not _reintento:
            # El proceso anterior murió a medias: se libera la clave y se reintenta una vez.
            existente.delete()
            return ejecutar_idempotente(
                clave=clave,
                metodo=metodo,
                ruta=ruta,
                cuerpo=cuerpo,
                operacion=operacion,
                _reintento=True,
            )
        raise OperacionEnCurso() from None

    try:
        codigo_http, datos = operacion()
    except BaseException:
        registro.delete()  # el fallo no se memoriza: el cliente puede reintentar
        raise

    registro.estado = RegistroIdempotencia.Estado.COMPLETADO
    registro.codigo_http = codigo_http
    registro.respuesta = datos
    registro.save(update_fields=["estado", "codigo_http", "respuesta"])
    return codigo_http, datos, False
