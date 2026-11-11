"""Panel de gestión: usuarios (con accesos, roles y excepciones) y roles (con su matriz)."""

from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.organizacion.models import Empresa
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.models import AccesoEmpresa, Rol, UsuarioPermiso, UsuarioRol
from apps.seguridad.permissions import PermisoRBAC, codigo_requerido
from apps.seguridad.services import gestion_usuarios as gestion
from apps.seguridad.services import roles as servicio_roles

from .serializers_gestion import (
    AccesoEntradaSerializer,
    AccesoSerializer,
    AsignacionSerializer,
    AsignarRolSerializer,
    ExcepcionEntradaSerializer,
    ExcepcionSerializer,
    MatrizPermisosSerializer,
    RolActualizarSerializer,
    RolCrearSerializer,
    RolDetalleSerializer,
    RolListaSerializer,
    UsuarioActualizarSerializer,
    UsuarioCrearSerializer,
    UsuarioDetalleSerializer,
    UsuarioListaSerializer,
)

TAG_USUARIOS = ["gestion-usuarios"]
TAG_ROLES = ["gestion-roles"]


def _enteros(valor) -> list[int]:
    """Lista de enteros tolerante: lo inválido se descarta (valida el serializer después)."""
    if not isinstance(valor, list):
        return []
    return [v for v in valor if isinstance(v, int) and not isinstance(v, bool) and v > 0]


# Columnas por las que se puede ordenar el listado (lista cerrada: el cliente nunca elige campos).
# Cada orden termina en ``username`` (único) para que la paginación sea estable.
ORDENES_USUARIO = {
    "username": ("username",),
    "nombre": ("first_name", "last_name", "username"),
    "email": ("email", "username"),
    "estado": ("is_active", "username"),
    "ultimo_acceso": ("last_login", "username"),
}


def _ordenar_usuarios(queryset, valor: str):
    """``?orden=nombre`` ascendente, ``?orden=-ultimo_acceso`` descendente.

    Cualquier otro valor se ignora y se usa el orden por defecto (usuario, ascendente).
    """
    clave = valor.lstrip("-")
    if clave not in ORDENES_USUARIO:
        clave, valor = "username", ""
    descendente = valor.startswith("-")
    campos = ORDENES_USUARIO[clave]
    expresiones = [
        F(campo).desc(nulls_last=True) if descendente else F(campo).asc(nulls_last=True)
        for campo in campos
    ]
    return queryset.order_by(*expresiones)


def _por_pk_o_validacion(modelo, pk: int | None, campo: str):
    """Objeto del ámbito activo; si no existe se informa como error de campo (no se revela más)."""
    if pk is None:
        return None
    instancia = modelo.objects.filter(pk=pk).first()
    if instancia is None:
        raise ValidationError({campo: "No existe."})
    return instancia


class UsuarioViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Usuarios de la organización visibles para quien consulta (``?q=``, ``?activo=``…)."""

    serializer_class = UsuarioListaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {
        "list": gestion.VER,
        "retrieve": gestion.VER,
        "create": gestion.CREAR,
        "partial_update": gestion.EDITAR,
        "desactivar": gestion.DESACTIVAR,
        "reactivar": gestion.DESACTIVAR,
        "restablecer_mfa": gestion.EDITAR,
        "restablecer_password": gestion.RESTABLECER_CLAVE,
        "acceso": gestion.EDITAR,
        "asignar_rol": servicio_roles.ASIGNAR_ROL,
        "quitar_rol": servicio_roles.ASIGNAR_ROL,
        "otorgar_excepcion": servicio_roles.EXCEPCIONES,
        "revocar_excepcion": servicio_roles.EXCEPCIONES,
    }
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def empresas_de_la_operacion(self, request):
        if self.action == "acceso":
            return [int(self.kwargs["empresa_id"])]
        if self.action == "create":
            datos = request.data if hasattr(request.data, "get") else {}
            return _enteros(datos.get("empresa_ids")) or [None]
        return [None]  # el servicio exige el permiso en cada empresa del usuario objetivo

    def get_serializer_class(self):
        return UsuarioDetalleSerializer if self.action == "retrieve" else UsuarioListaSerializer

    def get_queryset(self):
        codigo = codigo_requerido(self, self.request)
        queryset = gestion.usuarios_visibles(self.request.user, codigo)
        parametros = self.request.query_params
        q = (parametros.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )
        activo = parametros.get("activo")
        if activo in ("true", "false"):
            queryset = queryset.filter(is_active=activo == "true")
        empresa = parametros.get("empresa")
        if empresa and empresa.isdigit():
            queryset = queryset.filter(
                Exists(
                    AccesoEmpresa.objects.filter(usuario=OuterRef("pk"), empresa_id=int(empresa))
                )
            )
        rol = parametros.get("rol")
        if rol and rol.isdigit():
            queryset = queryset.filter(
                Exists(UsuarioRol.objects.filter(usuario=OuterRef("pk"), rol_id=int(rol)))
            )
        if self.action == "list":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "accesos_empresa", queryset=AccesoEmpresa.objects.select_related("empresa")
                ),
                Prefetch("roles_asignados", queryset=UsuarioRol.objects.select_related("rol")),
            )
        return _ordenar_usuarios(queryset, parametros.get("orden", ""))

    def _detalle(self, usuario, codigo_http=status.HTTP_200_OK) -> Response:
        return Response(UsuarioDetalleSerializer(usuario).data, status=codigo_http)

    @extend_schema(
        request=UsuarioCrearSerializer, responses={201: UsuarioDetalleSerializer}, tags=TAG_USUARIOS
    )
    def create(self, request, *args, **kwargs):
        datos = UsuarioCrearSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        valores = dict(datos.validated_data)
        rol = _por_pk_o_validacion(Rol, valores.pop("rol"), "rol")
        usuario = gestion.crear_usuario_gestionado(request.user, rol=rol, **valores)
        return self._detalle(usuario, status.HTTP_201_CREATED)

    @extend_schema(
        request=UsuarioActualizarSerializer,
        responses={200: UsuarioDetalleSerializer},
        tags=TAG_USUARIOS,
    )
    def partial_update(self, request, *args, **kwargs):
        usuario = self.get_object()
        datos = UsuarioActualizarSerializer(data=request.data, partial=True)
        datos.is_valid(raise_exception=True)
        gestion.actualizar_usuario(request.user, usuario, **datos.a_campos_modelo())
        return self._detalle(usuario)

    @extend_schema(request=None, responses={200: UsuarioDetalleSerializer}, tags=TAG_USUARIOS)
    @action(detail=True, methods=["post"])
    def desactivar(self, request, pk=None):
        usuario = self.get_object()
        gestion.desactivar_usuario_gestionado(request.user, usuario)
        usuario.refresh_from_db()
        return self._detalle(usuario)

    @extend_schema(request=None, responses={200: UsuarioDetalleSerializer}, tags=TAG_USUARIOS)
    @action(detail=True, methods=["post"])
    def reactivar(self, request, pk=None):
        usuario = gestion.reactivar_usuario(request.user, self.get_object())
        return self._detalle(usuario)

    @extend_schema(request=None, responses={200: UsuarioDetalleSerializer}, tags=TAG_USUARIOS)
    @action(detail=True, methods=["post"], url_path="restablecer-mfa", url_name="restablecer-mfa")
    def restablecer_mfa(self, request, pk=None):
        usuario = self.get_object()
        gestion.restablecer_mfa(request.user, usuario)
        usuario.refresh_from_db()
        return self._detalle(usuario)

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT}, tags=TAG_USUARIOS)
    @action(
        detail=True,
        methods=["post"],
        url_path="restablecer-password",
        url_name="restablecer-password",
    )
    def restablecer_password(self, request, pk=None):
        """Genera una contraseña temporal; se muestra una sola vez y no se vuelve a consultar."""
        temporal = gestion.restablecer_password(request.user, self.get_object())
        respuesta = Response({"password_temporal": temporal})
        respuesta["Cache-Control"] = "no-store"
        return respuesta

    # -- accesos ------------------------------------------------------------
    @extend_schema(
        request=AccesoEntradaSerializer, responses={200: AccesoSerializer}, tags=TAG_USUARIOS
    )
    @action(
        detail=True,
        methods=["put", "delete"],
        url_path=r"accesos/(?P<empresa_id>\d+)",
        url_name="acceso",
    )
    def acceso(self, request, pk=None, empresa_id=None):
        usuario = self.get_object()
        if request.method == "DELETE":
            gestion.quitar_acceso(request.user, usuario, int(empresa_id))
            return Response(status=status.HTTP_204_NO_CONTENT)
        datos = AccesoEntradaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        acceso = gestion.establecer_acceso(
            request.user,
            usuario,
            int(empresa_id),
            cargo=v["cargo"],
            estado=v["estado"],
            vigente_hasta=v["vigente_hasta"],
            sucursal_ids=v["sucursales"],
        )
        return Response(AccesoSerializer(acceso).data)

    # -- roles --------------------------------------------------------------
    @extend_schema(
        request=AsignarRolSerializer, responses={201: AsignacionSerializer}, tags=TAG_USUARIOS
    )
    @action(detail=True, methods=["post"], url_path="roles", url_name="roles")
    def asignar_rol(self, request, pk=None):
        usuario = self.get_object()
        datos = AsignarRolSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        asignacion = servicio_roles.asignar_rol(
            request.user,
            usuario=usuario,
            rol=_por_pk_o_validacion(Rol, v["rol"], "rol"),
            empresa=_por_pk_o_validacion(Empresa, v["empresa"], "empresa"),
            vigente_hasta=v["vigente_hasta"],
        )
        return Response(AsignacionSerializer(asignacion).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None}, tags=TAG_USUARIOS)
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"roles/(?P<asignacion_id>\d+)",
        url_name="rol-quitar",
    )
    def quitar_rol(self, request, pk=None, asignacion_id=None):
        usuario = self.get_object()
        asignacion = (
            UsuarioRol.objects.filter(pk=asignacion_id, usuario=usuario)
            .select_related("rol", "usuario")
            .first()
        )
        if asignacion is None:
            raise Http404
        servicio_roles.quitar_rol(request.user, asignacion)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -- excepciones individuales ------------------------------------------
    @extend_schema(
        request=ExcepcionEntradaSerializer, responses={201: ExcepcionSerializer}, tags=TAG_USUARIOS
    )
    @action(detail=True, methods=["post"], url_path="excepciones", url_name="excepciones")
    def otorgar_excepcion(self, request, pk=None):
        usuario = self.get_object()
        datos = ExcepcionEntradaSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        v = datos.validated_data
        excepcion = servicio_roles.otorgar_excepcion(
            request.user,
            usuario=usuario,
            codigo=v["codigo"],
            tipo=v["tipo"],
            motivo=v["motivo"],
            empresa=_por_pk_o_validacion(Empresa, v["empresa"], "empresa"),
            alcance=v["alcance"],
            vigente_hasta=v["vigente_hasta"],
        )
        return Response(ExcepcionSerializer(excepcion).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={204: None}, tags=TAG_USUARIOS)
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"excepciones/(?P<excepcion_id>\d+)",
        url_name="excepcion-revocar",
    )
    def revocar_excepcion(self, request, pk=None, excepcion_id=None):
        usuario = self.get_object()
        excepcion = (
            UsuarioPermiso.objects.filter(pk=excepcion_id, usuario=usuario)
            .select_related("usuario", "permiso")
            .first()
        )
        if excepcion is None:
            raise Http404
        servicio_roles.revocar_excepcion(request.user, excepcion)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RolViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Roles de la organización y su matriz de permisos."""

    modelo = Rol
    campo_empresa = None  # los roles son de la organización
    serializer_class = RolListaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {
        "list": "SEGURIDAD.ROLES.VER",
        "retrieve": "SEGURIDAD.ROLES.VER",
        "create": servicio_roles.GESTIONAR_ROLES,
        "partial_update": servicio_roles.GESTIONAR_ROLES,
        "destroy": servicio_roles.GESTIONAR_ROLES,
        "permisos": "SEGURIDAD.ROLES.VER",
        "establecer_permisos": servicio_roles.GESTIONAR_ROLES,
    }
    lookup_value_regex = r"\d+"

    def get_serializer_class(self):
        return (
            RolDetalleSerializer if self.action in ("retrieve", "permisos") else RolListaSerializer
        )

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .annotate(
                n_usuarios=Count(
                    "asignaciones", filter=Q(asignaciones__eliminado_en__isnull=True), distinct=True
                ),
                n_permisos=Count(
                    "permisos", filter=Q(permisos__eliminado_en__isnull=True), distinct=True
                ),
            )
        )
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
        return queryset.order_by("codigo")

    def _detalle(self, rol, codigo_http=status.HTTP_200_OK) -> Response:
        rol = self.get_queryset().get(pk=rol.pk)
        return Response(RolDetalleSerializer(rol).data, status=codigo_http)

    @extend_schema(
        request=RolCrearSerializer, responses={201: RolDetalleSerializer}, tags=TAG_ROLES
    )
    def create(self, request, *args, **kwargs):
        datos = RolCrearSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        rol = servicio_roles.crear_rol(
            request.user, organizacion=request.user.organizacion, **datos.validated_data
        )
        return self._detalle(rol, status.HTTP_201_CREATED)

    @extend_schema(
        request=RolActualizarSerializer, responses={200: RolDetalleSerializer}, tags=TAG_ROLES
    )
    def partial_update(self, request, *args, **kwargs):
        rol = self.get_object()
        datos = RolActualizarSerializer(data=request.data, partial=True)
        datos.is_valid(raise_exception=True)
        servicio_roles.actualizar_rol(
            request.user,
            rol,
            nombre=datos.validated_data.get("nombre", rol.nombre),
            descripcion=datos.validated_data.get("descripcion", rol.descripcion),
        )
        return self._detalle(rol)

    def perform_destroy(self, instance):
        servicio_roles.eliminar_rol(self.request.user, instance)

    @extend_schema(responses={200: RolDetalleSerializer}, tags=TAG_ROLES)
    @action(detail=True, methods=["get"], url_path="permisos", url_name="permisos")
    def permisos(self, request, pk=None):
        return self._detalle(self.get_object())

    @extend_schema(
        request=MatrizPermisosSerializer, responses={200: RolDetalleSerializer}, tags=TAG_ROLES
    )
    @permisos.mapping.put
    def establecer_permisos(self, request, pk=None):
        rol = self.get_object()
        datos = MatrizPermisosSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        servicio_roles.establecer_permisos_de_rol(
            request.user, rol, datos.validated_data["permisos"]
        )
        return self._detalle(rol)
