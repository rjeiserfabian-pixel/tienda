from django.conf import settings
from django.http import Http404
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.servicios import registrar
from apps.core.manejador_errores import manejador_excepciones
from apps.core.pagination import PaginaSesiones
from apps.core.throttles import ApiPublicaThrottle, LoginThrottle
from apps.core.utils.red import ip_cliente
from apps.seguridad.exceptions import PermisoDenegado, SesionInvalida
from apps.seguridad.models import MotivoRevocacion, Permiso, Plataforma
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import auth, mfa, passwords, politicas, recuperacion, sesiones
from apps.seguridad.services import permisos_engine as motor
from apps.seguridad.services.accesos import empresas_habilitadas
from apps.seguridad.services.auth import ResultadoAutenticacion
from apps.seguridad.services.menu import menu_de

from .serializers import (
    AutenticacionRespuestaSerializer,
    CambiarPasswordSerializer,
    LoginSerializer,
    MfaCodigoSerializer,
    MfaCodigosRecuperacionSerializer,
    MfaConfiguracionSerializer,
    MfaCredencialesSerializer,
    MfaDesafioRespuestaSerializer,
    MfaEstadoSerializer,
    MfaPasswordSerializer,
    MfaVerificarSerializer,
    MisPermisosSerializer,
    NodoMenuSerializer,
    PermisoSerializer,
    RecuperarConfirmarSerializer,
    RecuperarSolicitudSerializer,
    RefreshSerializer,
    SesionSerializer,
    UsuarioPublicoSerializer,
)


def _cuerpo_autenticacion(r: ResultadoAutenticacion, *, incluir_refresh: bool) -> dict:
    organizacion = r.usuario.organizacion
    cuerpo = {
        "access": r.access,
        "sesion_id": str(r.sesion.pk),
        "usuario": UsuarioPublicoSerializer(r.usuario).data,
        "organizacion": {"id": organizacion.pk, "nombre": organizacion.nombre}
        if organizacion
        else None,
        "empresas": [e.como_dict() for e in r.empresas],
    }
    if incluir_refresh:
        cuerpo["refresh"] = r.refresh
    return cuerpo


def _poner_cookie_refresh(respuesta: Response, refresh: str, persistente: bool = True) -> None:
    respuesta.set_cookie(
        settings.COOKIE_REFRESH_NOMBRE,
        refresh,
        # Sin "mantener sesión activa" no hay max_age: es una cookie de sesión del navegador.
        max_age=settings.REFRESH_TOKEN_DIAS * 24 * 3600 if persistente else None,
        path=settings.COOKIE_REFRESH_RUTA,
        httponly=True,  # JavaScript no puede leerla (mitiga XSS)
        secure=settings.COOKIE_REFRESH_SECURE,
        samesite="Strict",  # mitiga CSRF
    )


def _borrar_cookie_refresh(respuesta: Response) -> None:
    respuesta.delete_cookie(
        settings.COOKIE_REFRESH_NOMBRE, path=settings.COOKIE_REFRESH_RUTA, samesite="Strict"
    )


def _respuesta_de_sesion(resultado, plataforma: str) -> Response:
    """Web: el refresh va en cookie HttpOnly. Móvil: va en el cuerpo."""
    es_web = plataforma == Plataforma.WEB
    respuesta = Response(_cuerpo_autenticacion(resultado, incluir_refresh=not es_web))
    if es_web:
        _poner_cookie_refresh(respuesta, resultado.refresh, resultado.sesion.persistente)
    return respuesta


class LoginView(APIView):
    """Inicia sesión. Web: el refresh va en cookie HttpOnly. Móvil: va en el cuerpo."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: PolymorphicProxySerializer(
                component_name="LoginRespuesta",
                serializers=[AutenticacionRespuestaSerializer, MfaDesafioRespuestaSerializer],
                resource_type_field_name=None,
            )
        },
        auth=[],
        tags=["auth"],
    )
    def post(self, request):
        datos = LoginSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        resultado = auth.iniciar_sesion(
            identificador=v["identificador"],
            password=v["password"],
            plataforma=v["plataforma"],
            dispositivo=v["dispositivo"],
            push_token=v["push_token"],
            ip=ip_cliente(request),
            user_agent=request.headers.get("User-Agent", ""),
            recordar=v["recordar"],
        )
        if isinstance(resultado, auth.DesafioMfa):
            # Aún no hay sesión: el cliente debe enviar el código a ``auth/mfa/verificar/``.
            return Response({"mfa_requerido": True, "desafio": resultado.desafio})
        return _respuesta_de_sesion(resultado, v["plataforma"])


class MfaVerificarLoginView(APIView):
    """Segundo paso del login: canjea el desafío + código por la sesión."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        request=MfaVerificarSerializer,
        responses={200: AutenticacionRespuestaSerializer},
        auth=[],
        tags=["auth"],
    )
    def post(self, request):
        datos = MfaVerificarSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        resultado = auth.completar_login_mfa(
            desafio=datos.validated_data["desafio"],
            codigo=datos.validated_data["codigo"],
            ip=ip_cliente(request),
            user_agent=request.headers.get("User-Agent", ""),
        )
        return _respuesta_de_sesion(resultado, resultado.sesion.plataforma)


class RefreshView(APIView):
    """Canjea el refresh (cuerpo o cookie) por un par nuevo; el anterior queda inválido."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ApiPublicaThrottle]

    @extend_schema(
        request=RefreshSerializer,
        responses={200: AutenticacionRespuestaSerializer},
        auth=[],
        tags=["auth"],
    )
    def post(self, request):
        datos = RefreshSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        en_cuerpo = datos.validated_data["refresh"]
        token = en_cuerpo or request.COOKIES.get(settings.COOKIE_REFRESH_NOMBRE, "")
        try:
            resultado = auth.refrescar_sesion(refresh_token=token, ip=ip_cliente(request))
        except SesionInvalida as exc:
            # Además del error uniforme, se elimina la cookie inservible del navegador.
            respuesta = manejador_excepciones(exc, {"view": self})
            _borrar_cookie_refresh(respuesta)
            return respuesta
        respuesta = Response(_cuerpo_autenticacion(resultado, incluir_refresh=bool(en_cuerpo)))
        if not en_cuerpo:
            _poner_cookie_refresh(respuesta, resultado.refresh, resultado.sesion.persistente)
        return respuesta


class LogoutView(APIView):
    """Cierra solo la sesión actual."""

    @extend_schema(
        request=None, responses={204: OpenApiResponse(description="Sesión cerrada")}, tags=["auth"]
    )
    def post(self, request):
        sesiones.cerrar_sesion(request.user, request.auth.get("sid"), MotivoRevocacion.LOGOUT)
        registrar(
            "sesion.logout",
            recurso_tipo="sesion",
            recurso_id=request.auth.get("sid"),
            usuario_id=request.user.pk,
            organizacion_id=request.user.organizacion_id,
            resumen="Cierre de sesión",
        )
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        _borrar_cookie_refresh(respuesta)
        return respuesta


class LogoutGlobalView(APIView):
    """Cierra TODAS las sesiones del usuario, incluida la actual."""

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Sesiones cerradas")},
        tags=["auth"],
    )
    def post(self, request):
        cerradas = sesiones.revocar_sesiones_de_usuario(
            request.user, MotivoRevocacion.LOGOUT_GLOBAL
        )
        registrar(
            "sesion.logout_global",
            recurso_tipo="usuario",
            recurso_id=request.user.pk,
            usuario_id=request.user.pk,
            organizacion_id=request.user.organizacion_id,
            resumen="Cierre de todas las sesiones",
            detalle={"sesiones_cerradas": cerradas},
        )
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        _borrar_cookie_refresh(respuesta)
        return respuesta


class MiPerfilView(APIView):
    """Usuario autenticado y las empresas que puede operar ahora mismo."""

    @extend_schema(responses={200: AutenticacionRespuestaSerializer}, tags=["auth"])
    def get(self, request):
        usuario = request.user
        organizacion = usuario.organizacion
        return Response(
            {
                "sesion_id": request.auth.get("sid"),
                "usuario": UsuarioPublicoSerializer(usuario).data,
                "organizacion": {"id": organizacion.pk, "nombre": organizacion.nombre}
                if organizacion
                else None,
                "empresas": [e.como_dict() for e in empresas_habilitadas(usuario)],
            }
        )


class CambiarPasswordView(APIView):
    @extend_schema(
        request=CambiarPasswordSerializer,
        responses={204: OpenApiResponse(description="Contraseña actualizada")},
        tags=["auth"],
    )
    def post(self, request):
        datos = CambiarPasswordSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        passwords.cambiar_password(
            request.user,
            actual=datos.validated_data["actual"],
            nueva=datos.validated_data["nueva"],
            sesion_actual_id=request.auth.get("sid"),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SesionListView(generics.ListAPIView):
    """Sesiones activas del propio usuario (``?page=`` y ``?page_size=``, 20 por defecto)."""

    serializer_class = SesionSerializer
    pagination_class = PaginaSesiones

    def get_queryset(self):
        # Orden estable para que la paginación por números no repita ni salte filas.
        return sesiones.sesiones_activas(self.request.user).order_by("-creado_en", "-id")

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "sesion_actual_id": self.request.auth.get("sid"),
        }


class SesionRevocarView(APIView):
    """Revoca una sesión remota. Solo se pueden revocar las propias (si no, 404)."""

    @extend_schema(
        request=None, responses={204: OpenApiResponse(description="Sesión revocada")}, tags=["auth"]
    )
    def delete(self, request, sesion_id):
        if not sesiones.cerrar_sesion(request.user, sesion_id, MotivoRevocacion.REMOTA):
            raise Http404  # no se distingue "no existe" de "es de otro usuario"
        registrar(
            "sesion.revocada_remota",
            recurso_tipo="sesion",
            recurso_id=sesion_id,
            usuario_id=request.user.pk,
            organizacion_id=request.user.organizacion_id,
            resumen="Sesión cerrada desde otro dispositivo",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SesionesOtrasRevocarView(APIView):
    """Revoca todas las sesiones del usuario menos la actual (no lo desconecta de este panel)."""

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Cantidad de sesiones cerradas")},
        tags=["auth"],
    )
    def delete(self, request):
        cerradas = sesiones.revocar_sesiones_de_usuario(
            request.user, MotivoRevocacion.REMOTA, excepto_id=request.auth.get("sid")
        )
        registrar(
            "sesion.revocadas_otras",
            recurso_tipo="usuario",
            recurso_id=request.user.pk,
            usuario_id=request.user.pk,
            organizacion_id=request.user.organizacion_id,
            resumen="Cierre de las demás sesiones",
            detalle={"sesiones_cerradas": cerradas},
        )
        return Response({"cerradas": cerradas})


class CatalogoPermisosView(generics.ListAPIView):
    """Catálogo COMPLETO de permisos para la matriz de roles.

    Sin paginar a propósito: la interfaz necesita la lista entera (~70 filas, tamaño
    acotado por el catálogo en código). Está declarado en el test de paginación.
    """

    serializer_class = PermisoSerializer
    pagination_class = None
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = "SEGURIDAD.ROLES.VER"
    queryset = Permiso.objects.filter(activo=True).order_by("modulo", "codigo")


class MisPermisosView(APIView):
    """Permisos efectivos del usuario en una empresa (``?empresa=ID``) o a nivel organización."""

    @extend_schema(
        parameters=[OpenApiParameter("empresa", int, required=False)],
        responses={200: MisPermisosSerializer},
        tags=["permisos"],
    )
    def get(self, request):
        empresa_id = empresa_declarada(request, self)
        permisos = motor.permisos_de(request.user, empresa_id)
        if empresa_id is not None and not permisos.acceso:
            raise PermisoDenegado("No tiene acceso a esa empresa.")
        return Response({"empresa": empresa_id, "permisos": permisos.permisos})


class MenuView(APIView):
    """Menú del usuario: solo los módulos que puede ver."""

    @extend_schema(responses={200: NodoMenuSerializer(many=True)}, tags=["permisos"])
    def get(self, request):
        return Response(menu_de(request.user))


# ---------------------------------------------------------------------------
# Recuperación de contraseña (públicas)
# ---------------------------------------------------------------------------
class RecuperarSolicitudView(APIView):
    """Pide el enlace de recuperación. Responde igual exista o no la cuenta."""

    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        request=RecuperarSolicitudSerializer,
        responses={202: OpenApiResponse(description="Si la cuenta existe, se envió un correo")},
        auth=[],
        tags=["auth"],
    )
    def post(self, request):
        datos = RecuperarSolicitudSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        recuperacion.solicitar(datos.validated_data["identificador"], ip_cliente(request))
        return Response(
            {"detalle": "Si la cuenta existe, recibirá un correo con las instrucciones."},
            status=status.HTTP_202_ACCEPTED,
        )


class RecuperarConfirmarView(APIView):
    authentication_classes: list = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(
        request=RecuperarConfirmarSerializer,
        responses={204: OpenApiResponse(description="Contraseña restablecida")},
        auth=[],
        tags=["auth"],
    )
    def post(self, request):
        datos = RecuperarConfirmarSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        recuperacion.confirmar(
            token=v["token"], nueva=v["nueva"], codigo_mfa=v["codigo_mfa"], ip=ip_cliente(request)
        )
        respuesta = Response(status=status.HTTP_204_NO_CONTENT)
        _borrar_cookie_refresh(respuesta)
        return respuesta


# ---------------------------------------------------------------------------
# Verificación en dos pasos del propio usuario
# ---------------------------------------------------------------------------
class MfaEstadoView(APIView):
    @extend_schema(responses={200: MfaEstadoSerializer}, tags=["mfa"])
    def get(self, request):
        return Response(
            {
                "activo": request.user.mfa_activo,
                "codigos_restantes": mfa.codigos_restantes(request.user),
                "obligatorio": politicas.mfa_obligatorio(request.user.organizacion_id),
            }
        )


class MfaConfigurarView(APIView):
    """Paso 1: genera el secreto (pide la contraseña). Aún no queda activo."""

    @extend_schema(
        request=MfaPasswordSerializer, responses={200: MfaConfiguracionSerializer}, tags=["mfa"]
    )
    def post(self, request):
        datos = MfaPasswordSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        return Response(mfa.iniciar_configuracion(request.user, datos.validated_data["password"]))


class MfaConfirmarView(APIView):
    """Paso 2: prueba un código del autenticador; activa el factor y entrega los códigos."""

    @extend_schema(
        request=MfaCodigoSerializer, responses={200: MfaCodigosRecuperacionSerializer}, tags=["mfa"]
    )
    def post(self, request):
        datos = MfaCodigoSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        codigos = mfa.confirmar_configuracion(request.user, datos.validated_data["codigo"])
        return Response({"codigos_recuperacion": codigos})


class MfaDesactivarView(APIView):
    @extend_schema(
        request=MfaCredencialesSerializer,
        responses={204: OpenApiResponse(description="Factor desactivado")},
        tags=["mfa"],
    )
    def post(self, request):
        datos = MfaCredencialesSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        mfa.desactivar(
            request.user, datos.validated_data["password"], datos.validated_data["codigo"]
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MfaCodigosView(APIView):
    @extend_schema(
        request=MfaCredencialesSerializer,
        responses={200: MfaCodigosRecuperacionSerializer},
        tags=["mfa"],
    )
    def post(self, request):
        datos = MfaCredencialesSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        codigos = mfa.regenerar_codigos(
            request.user, datos.validated_data["password"], datos.validated_data["codigo"]
        )
        return Response({"codigos_recuperacion": codigos})
