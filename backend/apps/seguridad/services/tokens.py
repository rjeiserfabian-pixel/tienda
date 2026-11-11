"""Emisión y lectura de tokens JWT (access sin estado, refresh rotativo).

Claims del *refresh*: ``user_id``, ``sid`` (id de sesión), ``jti`` (único válido).
Claims del *access*: lo anterior + ``org_id`` y ``empresas`` (ids habilitados).
"""

import uuid
from dataclasses import dataclass

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.seguridad.exceptions import SesionInvalida


@dataclass(frozen=True, slots=True)
class ParRefresh:
    sid: str
    jti: str
    user_id: str


def nuevo_jti() -> str:
    return uuid.uuid4().hex


def emitir_tokens(*, usuario, sesion_id, jti: str, empresa_ids: list[int]) -> tuple[str, str]:
    """Devuelve ``(access, refresh)`` firmados."""
    refresh = RefreshToken()
    refresh[api_settings.JTI_CLAIM] = jti
    refresh[api_settings.USER_ID_CLAIM] = str(usuario.pk)
    refresh["sid"] = str(sesion_id)

    access = refresh.access_token  # copia user_id y sid; genera su propio jti y exp
    access["org_id"] = usuario.organizacion_id
    access["empresas"] = list(empresa_ids)
    return str(access), str(refresh)


def leer_refresh(token: str) -> ParRefresh:
    """Valida firma, expiración y tipo del refresh. Cualquier fallo es ``SesionInvalida``."""
    try:
        decodificado = RefreshToken(token)
        sid = decodificado["sid"]
        jti = decodificado[api_settings.JTI_CLAIM]
        user_id = decodificado[api_settings.USER_ID_CLAIM]
    except (TokenError, KeyError, TypeError):
        raise SesionInvalida() from None
    return ParRefresh(sid=str(sid), jti=str(jti), user_id=str(user_id))
