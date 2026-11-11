from django.db.models import Q
from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizacion.exceptions import LogoInvalido
from apps.organizacion.models import Empresa, Estado, Sucursal
from apps.organizacion.services import gestion
from apps.organizacion.services import logo as servicio_logo
from apps.seguridad.exceptions import PermisoDenegado
from apps.seguridad.mixins import ScopedQuerysetMixin
from apps.seguridad.models import AccesoEmpresa
from apps.seguridad.permissions import PermisoRBAC, empresa_declarada
from apps.seguridad.services import permisos_engine as motor

from .serializers import (
    EmpresaActualizarSerializer,
    EmpresaCrearSerializer,
    EmpresaSerializer,
    OrganizacionSerializer,
    SucursalActualizarSerializer,
    SucursalCrearSerializer,
    SucursalSerializer,
)

GESTIONAR_ORGANIZACION = "SEGURIDAD.ORGANIZACION.GESTIONAR"
VER_EMPRESAS = "SEGURIDAD.EMPRESAS.VER"
GESTIONAR_EMPRESAS = "SEGURIDAD.EMPRESAS.GESTIONAR"
GESTIONAR_SUCURSALES = "SEGURIDAD.SUCURSALES.GESTIONAR"


def _exigir_alcance_organizacion(request) -> None:
    """Operaciones que afectan a TODA la organización exigen el permiso con ese alcance."""
    alcances = getattr(request, "alcances_permiso", {})
    if not any(motor.alcance_cubre(a, "ORGANIZACION") for a in alcances.values()):
        raise PermisoDenegado("Esta operación requiere alcance de organización.")


class OrganizacionView(APIView):
    """Datos de la propia organización. Cualquier usuario la ve; solo quien gestiona la edita."""

    @extend_schema(responses={200: OrganizacionSerializer}, tags=["organizacion"])
    def get(self, request):
        organizacion = request.user.organizacion
        if organizacion is None:
            raise Http404
        return Response(OrganizacionSerializer(organizacion).data)

    @extend_schema(
        request=OrganizacionSerializer,
        responses={200: OrganizacionSerializer},
        tags=["organizacion"],
    )
    def patch(self, request):
        organizacion = request.user.organizacion
        if organizacion is None:
            raise Http404
        alcance = motor.exigir_permiso(request.user, GESTIONAR_ORGANIZACION, None)
        if not motor.alcance_cubre(alcance, "ORGANIZACION"):
            raise PermisoDenegado()
        datos = OrganizacionSerializer(organizacion, data=request.data, partial=True)
        datos.is_valid(raise_exception=True)
        gestion.actualizar_organizacion(
            organizacion,
            nombre=datos.validated_data.get("nombre", organizacion.nombre),
            mfa_obligatorio=datos.validated_data.get(
                "mfa_obligatorio", organizacion.mfa_obligatorio
            ),
            calculo_precios=datos.validated_data.get(
                "calculo_precios", organizacion.calculo_precios
            ),
        )
        return Response(OrganizacionSerializer(organizacion).data)


class EmpresaViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Empresas a las que el usuario tiene acceso (incluidas las inactivas, para reactivarlas).

    No se eliminan: se inactivan. El permiso se valida a nivel organización para entrar y,
    al modificar una empresa activa, también en esa empresa concreta.
    """

    serializer_class = EmpresaSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {
        "list": VER_EMPRESAS,
        "retrieve": VER_EMPRESAS,
        "create": GESTIONAR_EMPRESAS,
        "update": GESTIONAR_EMPRESAS,
        "partial_update": GESTIONAR_EMPRESAS,
        "logo": VER_EMPRESAS,
        "subir_logo": GESTIONAR_EMPRESAS,
        "quitar_logo": GESTIONAR_EMPRESAS,
    }
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def empresas_de_la_operacion(self, request):
        return [None]

    def get_queryset(self):
        ahora = timezone.now()
        con_acceso = AccesoEmpresa.objects.filter(
            Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gt=ahora),
            usuario=self.request.user,
            estado=Estado.ACTIVO,
        ).values("empresa_id")
        queryset = Empresa.objects.filter(pk__in=con_acceso)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                Q(razon_social__icontains=q)
                | Q(ruc__icontains=q)
                | Q(nombre_comercial__icontains=q)
            )
        estado = self.request.query_params.get("estado")
        if estado:
            queryset = queryset.filter(estado=estado)
        return queryset.order_by("id")

    @extend_schema(
        request=EmpresaCrearSerializer, responses={201: EmpresaSerializer}, tags=["organizacion"]
    )
    def create(self, request, *args, **kwargs):
        _exigir_alcance_organizacion(request)
        datos = EmpresaCrearSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        empresa = gestion.crear_empresa(
            organizacion=request.user.organizacion, creador=request.user, **datos.validated_data
        )
        return Response(EmpresaSerializer(empresa).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=EmpresaActualizarSerializer,
        responses={200: EmpresaSerializer},
        tags=["organizacion"],
    )
    def update(self, request, *args, **kwargs):
        empresa = self.get_object()
        # Una empresa inactiva no cuenta como "habilitada": solo se puede comprobar a nivel
        # organización (así se permite reactivarla).
        motor.exigir_permiso(
            request.user,
            GESTIONAR_EMPRESAS,
            empresa.pk if empresa.estado == Estado.ACTIVO else None,
        )
        datos = EmpresaActualizarSerializer(data=request.data, partial=kwargs.get("partial", False))
        datos.is_valid(raise_exception=True)
        valores = {
            "razon_social": empresa.razon_social,
            "nombre_comercial": empresa.nombre_comercial,
            "estado": empresa.estado,
            **{campo: getattr(empresa, campo) for campo in gestion.CAMPOS_FICHA},
            **datos.validated_data,
        }
        nuevo_ruc = (valores.get("ruc") or "").strip()
        if nuevo_ruc and nuevo_ruc != empresa.ruc:
            # Cambiar la identidad tributaria es más delicado que editar la ficha.
            motor.exigir_permiso(request.user, GESTIONAR_ORGANIZACION, None)
        gestion.actualizar_empresa(empresa, **valores)
        return Response(EmpresaSerializer(empresa).data)

    def _exigir_gestion(self, request, empresa) -> None:
        motor.exigir_permiso(
            request.user,
            GESTIONAR_EMPRESAS,
            empresa.pk if empresa.estado == Estado.ACTIVO else None,
        )

    @extend_schema(tags=["organizacion"], responses={(200, "image/png"): bytes})
    @action(
        detail=True,
        methods=["get"],
        url_path="logo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def logo(self, request, pk=None):
        """El logo en PNG; solo con sesión y permiso (no se sirve como archivo público)."""
        empresa = self.get_object()
        try:
            archivo = empresa.logo.open("rb")
        except (FileNotFoundError, ValueError):
            raise Http404 from None
        respuesta = FileResponse(archivo, content_type="image/png")
        respuesta["Cache-Control"] = "private, max-age=3600"
        respuesta["X-Content-Type-Options"] = "nosniff"
        return respuesta

    @logo.mapping.post
    @extend_schema(
        tags=["organizacion"],
        request={"multipart/form-data": dict},
        responses={200: EmpresaSerializer},
    )
    def subir_logo(self, request, pk=None):
        empresa = self.get_object()
        self._exigir_gestion(request, empresa)
        archivo = request.FILES.get("logo")
        if archivo is None:
            raise LogoInvalido("Elige un logo para subir.")
        return Response(EmpresaSerializer(servicio_logo.guardar(empresa, archivo)).data)

    @logo.mapping.delete
    @extend_schema(tags=["organizacion"], request=None, responses={200: EmpresaSerializer})
    def quitar_logo(self, request, pk=None):
        empresa = self.get_object()
        self._exigir_gestion(request, empresa)
        return Response(EmpresaSerializer(servicio_logo.quitar(empresa)).data)


class SucursalViewSet(
    ScopedQuerysetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Sucursales de las empresas habilitadas (``?empresa=ID`` para acotar)."""

    modelo = Sucursal
    serializer_class = SucursalSerializer
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permisos_por_accion = {
        "list": VER_EMPRESAS,
        "retrieve": VER_EMPRESAS,
        "create": GESTIONAR_SUCURSALES,
        "update": GESTIONAR_SUCURSALES,
        "partial_update": GESTIONAR_SUCURSALES,
    }
    lookup_value_regex = r"\d+"
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def empresas_de_la_operacion(self, request):
        if "pk" in self.kwargs:
            empresa_id = (
                Sucursal.objects.filter(pk=self.kwargs["pk"])
                .values_list("empresa_id", flat=True)
                .first()
            )
            if empresa_id is None:
                raise Http404
            return [empresa_id]
        if self.action == "create":
            self.requiere_empresa = True  # la empresa es obligatoria y explícita al crear
        return [empresa_declarada(request, self)]

    def get_queryset(self):
        queryset = super().get_queryset()
        empresa_id = empresa_declarada(self.request, self)
        if empresa_id is not None:
            queryset = queryset.filter(empresa_id=empresa_id)
        estado = self.request.query_params.get("estado")
        if estado:
            queryset = queryset.filter(estado=estado)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(
                Q(nombre__icontains=q) | Q(codigo__icontains=q) | Q(direccion__icontains=q)
            )
        return queryset.order_by("empresa_id", "codigo")

    @extend_schema(
        request=SucursalCrearSerializer, responses={201: SucursalSerializer}, tags=["organizacion"]
    )
    def create(self, request, *args, **kwargs):
        datos = SucursalCrearSerializer(data=request.data)
        datos.is_valid(raise_exception=True)
        valores = dict(datos.validated_data)
        empresa = Empresa.objects.filter(pk=valores.pop("empresa")).first()
        if empresa is None:
            raise Http404
        sucursal = gestion.crear_sucursal(empresa=empresa, **valores)
        return Response(SucursalSerializer(sucursal).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=SucursalActualizarSerializer,
        responses={200: SucursalSerializer},
        tags=["organizacion"],
    )
    def update(self, request, *args, **kwargs):
        sucursal = self.get_object()
        datos = SucursalActualizarSerializer(
            data=request.data, partial=kwargs.get("partial", False)
        )
        datos.is_valid(raise_exception=True)
        valores = {
            "nombre": sucursal.nombre,
            "local_fisico": sucursal.local_fisico,
            "direccion": sucursal.direccion,
            "ubigeo": sucursal.ubigeo,
            "estado": sucursal.estado,
            **datos.validated_data,
        }
        gestion.actualizar_sucursal(sucursal, **valores)
        return Response(SucursalSerializer(sucursal).data)
