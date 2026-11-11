"""Logging estructurado con ``request_id`` para rastrear incidentes."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Atributos estándar de LogRecord que no se repiten como "extra" en el JSON.
_ATRIBUTOS_ESTANDAR = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "request_id",
}


def obtener_request_id() -> str:
    return _request_id.get()


def establecer_request_id(valor: str):
    return _request_id.set(valor)


def restablecer_request_id(token) -> None:
    _request_id.reset(token)


class FiltroRequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class FormatoJson(logging.Formatter):
    """Una línea JSON por registro; incluye campos ``extra`` y la traza si hay."""

    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "fecha": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for clave, valor in record.__dict__.items():
            if clave not in _ATRIBUTOS_ESTANDAR:
                datos[clave] = valor
        if record.exc_info:
            datos["traza"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)
