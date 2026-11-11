"""Ciclo de vida de las sesiones: crear, revocar, consultar.

Al revocar se deja una marca en caché durante la vida del access token, así un
access token de una sesión revocada se rechaza al instante (sin consultar la base).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.seguridad.models import MotivoRevocacion, Sesion
from apps.seguridad.services.tokens import nuevo_jti

logger = logging.getLogger(__name__)

_CLAVE_REVOCADA = "seguridad:sesion_revocada:{}"


def _marcar_revocada_en_cache(sesion_ids) -> None:
    vigencia = settings.ACCESS_TOKEN_MINUTOS * 60 + 60
    cache.set_many({_CLAVE_REVOCADA.format(sid): 1 for sid in sesion_ids}, vigencia)


def sesion_revocada_en_cache(sesion_id) -> bool:
    return cache.get(_CLAVE_REVOCADA.format(sesion_id)) is not None


def vigencia_de(persistente: bool) -> timedelta:
    """Cuánto vive una sesión sin actividad (se renueva en cada refresh)."""
    if persistente:
        return timedelta(days=settings.REFRESH_TOKEN_DIAS)
    return timedelta(hours=settings.SESION_NO_PERSISTENTE_HORAS)


def crear_sesion(
    usuario,
    *,
    plataforma: str,
    dispositivo: str,
    user_agent: str,
    ip,
    push_token: str,
    persistente: bool = True,
) -> Sesion:
    ahora = timezone.now()
    return Sesion.objects.create(
        usuario=usuario,
        plataforma=plataforma,
        dispositivo=dispositivo[:200],
        user_agent=user_agent[:300],
        ip=ip,
        push_token=push_token[:255],
        persistente=persistente,
        jti_actual=nuevo_jti(),
        ultimo_uso=ahora,
        expira_en=ahora + vigencia_de(persistente),
    )


def revocar_sesion(sesion: Sesion, motivo: str) -> None:
    if sesion.revocada:
        return
    sesion.revocada = True
    sesion.revocada_en = timezone.now()
    sesion.motivo_revocacion = motivo
    sesion.save(update_fields=["revocada", "revocada_en", "motivo_revocacion"])
    _marcar_revocada_en_cache([sesion.pk])
    logger.info(
        "sesion_revocada",
        extra={"sesion_id": str(sesion.pk), "usuario_id": str(sesion.usuario_id), "motivo": motivo},
    )


def revocar_sesiones_de_usuario(usuario, motivo: str, *, excepto_id=None) -> int:
    """Revoca todas las sesiones activas del usuario (menos ``excepto_id``)."""
    activas = Sesion.objects.filter(usuario=usuario, revocada=False)
    if excepto_id is not None:
        activas = activas.exclude(pk=excepto_id)
    ids = list(activas.values_list("pk", flat=True))
    if not ids:
        return 0
    Sesion.objects.filter(pk__in=ids).update(
        revocada=True, revocada_en=timezone.now(), motivo_revocacion=motivo
    )
    _marcar_revocada_en_cache(ids)
    logger.info(
        "sesiones_revocadas",
        extra={"usuario_id": str(usuario.pk), "cantidad": len(ids), "motivo": motivo},
    )
    return len(ids)


def sesiones_activas(usuario):
    return Sesion.objects.filter(usuario=usuario, revocada=False, expira_en__gt=timezone.now())


def cerrar_sesion(usuario, sesion_id, motivo: str = MotivoRevocacion.LOGOUT) -> bool:
    """Revoca UNA sesión del propio usuario. Devuelve False si no existe o no es suya."""
    sesion = Sesion.objects.filter(pk=sesion_id, usuario=usuario, revocada=False).first()
    if sesion is None:
        return False
    revocar_sesion(sesion, motivo)
    return True
