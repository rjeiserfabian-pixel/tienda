"""Autenticación JWT que además fija el contexto de tenant de la petición."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.core.tenant import establecer_contexto
from apps.seguridad.exceptions import CambioPasswordRequerido, MfaConfiguracionRequerida
from apps.seguridad.services import politicas
from apps.seguridad.services.sesiones import sesion_revocada_en_cache


def _ids_validos(valor) -> list[int]:
    if not isinstance(valor, list):
        raise AuthenticationFailed("Token con empresas inválidas.")
    try:
        return [int(v) for v in valor]
    except (TypeError, ValueError):
        raise AuthenticationFailed("Token con empresas inválidas.") from None


# Lo ÚNICO que se permite mientras la cuenta tiene una condición pendiente (clave temporal o
# segundo factor obligatorio sin activar): consultar quién es, salir y resolver la condición.
_URLS_PERMITIDAS = frozenset(
    {
        "me",
        "menu",
        "permisos-mios",
        "logout",
        "logout-global",
        "cambiar-password",
        "mfa-estado",
        "mfa-configurar",
        "mfa-confirmar",
    }
)


def _exigir_cuenta_lista(request, usuario) -> None:
    """Bloquea en la API (no solo en la interfaz) las cuentas con una condición pendiente."""
    coincidencia = getattr(request, "resolver_match", None)
    if coincidencia is not None and coincidencia.url_name in _URLS_PERMITIDAS:
        return
    if usuario.debe_cambiar_password:
        raise CambioPasswordRequerido()
    if politicas.debe_configurar_mfa(usuario):
        raise MfaConfiguracionRequerida()


class JWTAutenticacion(JWTAuthentication):
    """Valida el access token, rechaza sesiones revocadas y activa el tenant.

    El contexto (organización + empresas habilitadas) se toma del token firmado.
    ``LimpiarContextoTenantMiddleware`` lo borra al terminar la petición.
    """

    def authenticate(self, request):
        resultado = super().authenticate(request)
        if resultado is None:
            return None
        usuario, token = resultado

        sid = token.get("sid")
        if sid is None or sesion_revocada_en_cache(sid):
            raise AuthenticationFailed("La sesión fue cerrada.", code="sesion_invalida")

        org_id = token.get("org_id")
        if org_id != usuario.organizacion_id:
            raise AuthenticationFailed("Token no corresponde a la organización.")
        _exigir_cuenta_lista(request, usuario)
        if org_id is not None:
            empresas = _ids_validos(token.get("empresas", []))
            establecer_contexto(org_id, empresas, usuario.pk)
        return usuario, token


class JWTAutenticacionOpenApi(OpenApiAuthenticationExtension):
    target_class = "apps.seguridad.authentication.JWTAutenticacion"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
