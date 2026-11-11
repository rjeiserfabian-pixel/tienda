"""Registro de eventos de auditoría, asíncrono y que NUNCA rompe la operación auditada.

Uso desde cualquier servicio::

    registrar("usuario.creado", recurso_tipo="usuario", recurso_id=usuario.pk,
              resumen=f"Alta de {usuario.username}", detalle={"empresas": [1, 2]})

* Se encola en Celery. Si está dentro de una transacción se espera al COMMIT: lo que se
  revierte no deja evento. Para eventos que deben quedar aunque la operación falle
  (intentos de acceso) se usa ``inmediato=True``.
* Si el broker no responde se inserta de forma sincrónica; si tampoco se puede, queda en
  el log con nivel CRITICAL. La auditoría no se pierde en silencio ni tumba la petición.
* Los datos sensibles (claves, tokens, códigos) se reemplazan antes de guardar.
"""

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db import connection, transaction

from apps.core import contexto_peticion
from apps.core.logging import obtener_request_id
from apps.core.tenant import obtener_contexto

logger = logging.getLogger(__name__)

_SENSIBLE = re.compile(r"pass|clave|token|secret|codigo_mfa|otp|huella|hash", re.IGNORECASE)
_PROFUNDIDAD_MAX = 4
_LARGO_TEXTO_MAX = 500
OCULTO = "***"


def sanear(valor, _nivel: int = 0):
    """Deja el detalle como JSON simple, sin secretos y con tamaño acotado."""
    if _nivel >= _PROFUNDIDAD_MAX:
        return "…"
    if isinstance(valor, dict):
        return {
            str(k)[:60]: (OCULTO if _SENSIBLE.search(str(k)) else sanear(v, _nivel + 1))
            for k, v in list(valor.items())[:50]
        }
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [sanear(v, _nivel + 1) for v in list(valor)[:50]]
    if isinstance(valor, (UUID, Decimal)):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, str):
        return valor[:_LARGO_TEXTO_MAX]
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    return str(valor)[:_LARGO_TEXTO_MAX]


def diferencia(antes: dict, despues: dict) -> dict:
    """Solo los campos que cambiaron: ``{campo: [antes, despues]}``."""
    return {
        campo: [antes.get(campo), despues.get(campo)]
        for campo in despues
        if antes.get(campo) != despues.get(campo)
    }


def _insertar(carga: dict) -> None:
    from .models import AuditoriaEvento

    AuditoriaEvento.objects.create(**carga)


def _despachar(carga: dict) -> None:
    from .tasks import registrar_evento

    try:
        registrar_evento.delay(carga)
    except Exception:  # noqa: BLE001 - cualquier fallo del broker cae al camino sincrónico
        logger.exception("auditoria_broker_no_disponible", extra={"accion": carga["accion"]})
        try:
            _insertar(carga)
        except Exception:  # noqa: BLE001 - último recurso: dejar el rastro en el log
            logger.critical("auditoria_perdida", extra={"evento": carga}, exc_info=True)


def registrar(
    accion: str,
    *,
    recurso_tipo: str = "",
    recurso_id="",
    resumen: str = "",
    detalle: dict | None = None,
    empresa_id: int | None = None,
    organizacion_id: int | None = None,
    usuario_id=None,
    exito: bool = True,
    inmediato: bool = False,
) -> None:
    contexto = obtener_contexto()
    if contexto is not None:
        if organizacion_id is None:
            organizacion_id = contexto.organizacion_id
        if usuario_id is None:
            usuario_id = contexto.usuario_id
    carga = {
        "organizacion_id": organizacion_id,
        "usuario_id": str(usuario_id) if usuario_id else None,
        "empresa_id": empresa_id,
        "accion": accion[:60],
        "recurso_tipo": recurso_tipo[:40],
        "recurso_id": "" if recurso_id == "" else str(recurso_id)[:64],
        "resumen": resumen[:250],
        "detalle": sanear(detalle or {}),
        "exito": exito,
        "ip": contexto_peticion.ip_actual(),
        "user_agent": contexto_peticion.user_agent_actual(),
        "request_id": obtener_request_id()[:64],
    }
    if not inmediato and connection.in_atomic_block:
        transaction.on_commit(lambda: _despachar(carga))
    else:
        _despachar(carga)
