"""IP y user-agent de la petición en curso, disponibles para servicios y auditoría.

Se guardan en ``ContextVar`` (seguro con hilos); el middleware los fija al entrar y los
restablece al salir, así nunca se filtran de una petición a otra.
"""

from contextvars import ContextVar

_ip: ContextVar[str | None] = ContextVar("peticion_ip", default=None)
_user_agent: ContextVar[str] = ContextVar("peticion_user_agent", default="")


def establecer(ip: str | None, user_agent: str):
    return _ip.set(ip), _user_agent.set(user_agent)


def restablecer(tokens) -> None:
    _ip.reset(tokens[0])
    _user_agent.reset(tokens[1])


def ip_actual() -> str | None:
    return _ip.get()


def user_agent_actual() -> str:
    return _user_agent.get()
