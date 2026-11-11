from datetime import datetime, time

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions, serializers
from rest_framework.exceptions import ValidationError

from apps.auditoria.models import AuditoriaEvento
from apps.core.pagination import PaginaAuditoria
from apps.seguridad.mixins import filtrar_por_alcance
from apps.seguridad.models import Usuario
from apps.seguridad.permissions import PermisoRBAC
from apps.seguridad.services import permisos_engine as motor

VER_AUDITORIA = "SEGURIDAD.AUDITORIA.VER"


class EventoSerializer(serializers.ModelSerializer):
    usuario = serializers.SerializerMethodField()

    class Meta:
        model = AuditoriaEvento
        fields = (
            "id",
            "creado_en",
            "usuario_id",
            "usuario",
            "empresa_id",
            "accion",
            "recurso_tipo",
            "recurso_id",
            "resumen",
            "detalle",
            "exito",
            "ip",
            "request_id",
        )
        read_only_fields = fields

    def get_usuario(self, obj) -> str | None:
        return self.context.get("usuarios", {}).get(str(obj.usuario_id)) if obj.usuario_id else None


def _fecha(valor: str | None, nombre: str, *, fin: bool = False) -> datetime | None:
    if not valor:
        return None
    dia = parse_date(valor)
    if dia is None:
        raise ValidationError({nombre: "Use el formato AAAA-MM-DD."})
    momento = datetime.combine(dia, time.max if fin else time.min)
    return timezone.make_aware(momento)


class EventoListView(generics.ListAPIView):
    """Consulta de auditoría, paginada por número de página (20 por defecto, con total).

    Alcance: con alcance de organización se ven también los eventos que no pertenecen a
    una empresa (roles, políticas); con alcance de empresa, solo los de sus empresas.
    Filtros: ``accion`` (prefijo), ``usuario``, ``recurso_tipo``, ``recurso_id``, ``empresa``,
    ``exito``, ``desde`` y ``hasta``.
    """

    serializer_class = EventoSerializer
    pagination_class = PaginaAuditoria
    permission_classes = [permissions.IsAuthenticated, PermisoRBAC]
    permiso_requerido = VER_AUDITORIA

    def get_queryset(self):
        usuario = self.request.user
        base = AuditoriaEvento.objects.filter(organizacion_id=usuario.organizacion_id)
        if usuario.organizacion_id is None:
            return base.none()
        por_alcance = filtrar_por_alcance(
            base, usuario, VER_AUDITORIA, campo_empresa="empresa_id", campo_propio="usuario_id"
        )
        if motor.alcance_de(usuario, VER_AUDITORIA, None) == "ORGANIZACION":
            por_alcance = por_alcance | base.filter(empresa_id__isnull=True)
        queryset = por_alcance

        p = self.request.query_params
        if p.get("accion"):
            queryset = queryset.filter(accion__startswith=p["accion"][:60])
        if p.get("usuario"):
            queryset = queryset.filter(usuario_id=_uuid(p["usuario"]))
        if p.get("recurso_tipo"):
            queryset = queryset.filter(recurso_tipo=p["recurso_tipo"][:40])
        if p.get("recurso_id"):
            queryset = queryset.filter(recurso_id=p["recurso_id"][:64])
        if p.get("empresa", "").isdigit():
            queryset = queryset.filter(empresa_id=int(p["empresa"]))
        if p.get("exito") in ("true", "false"):
            queryset = queryset.filter(exito=p["exito"] == "true")
        desde, hasta = _fecha(p.get("desde"), "desde"), _fecha(p.get("hasta"), "hasta", fin=True)
        if desde:
            queryset = queryset.filter(creado_en__gte=desde)
        if hasta:
            queryset = queryset.filter(creado_en__lte=hasta)
        return queryset

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        contexto["usuarios"] = getattr(self, "_nombres", {})
        return contexto

    def paginate_queryset(self, queryset):
        pagina = super().paginate_queryset(queryset)
        ids = {e.usuario_id for e in pagina or [] if e.usuario_id}
        self._nombres = {
            str(pk): nombre
            for pk, nombre in Usuario.objects.filter(
                Q(pk__in=ids), organizacion_id=self.request.user.organizacion_id
            ).values_list("pk", "username")
        }
        return pagina

    @extend_schema(
        parameters=[
            OpenApiParameter("accion", str, description="Prefijo, p. ej. 'usuario.' o 'sesion.'"),
            OpenApiParameter("desde", str, description="AAAA-MM-DD"),
            OpenApiParameter("hasta", str, description="AAAA-MM-DD"),
        ],
        tags=["auditoria"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


def _uuid(valor: str):
    import uuid

    try:
        return uuid.UUID(valor)
    except ValueError:
        raise ValidationError({"usuario": "Identificador de usuario inválido."}) from None
