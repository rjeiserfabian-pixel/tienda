"""Filtrado de listados según el ALCANCE del permiso (propio/asignado/sucursal/empresa/org)."""

from functools import reduce
from operator import or_

from django.db.models import Q, QuerySet

from apps.seguridad.permissions import codigo_requerido
from apps.seguridad.services import permisos_engine as motor

EMPRESA_COMPLETA = {"EMPRESA", "ORGANIZACION"}


def filtrar_por_alcance(
    queryset: QuerySet,
    usuario,
    codigo: str,
    *,
    campo_empresa: str | None = "empresa_id",
    campo_propio: str | None = "creado_por_id",
    campo_asignado: str | None = None,
    campo_sucursal: str | None = None,
) -> QuerySet:
    """Restringe ``queryset`` a lo que el usuario puede ver con ese permiso.

    ``campo_empresa=None`` indica un recurso de la ORGANIZACIÓN (clientes, productos).
    Un alcance que la vista no sabe resolver (p. ej. ASIGNADO sin ``campo_asignado``)
    no concede nada: se falla cerrado.
    """
    if usuario.es_admin_plataforma:
        return queryset

    if campo_empresa is None:
        alcance = motor.alcance_de(usuario, codigo, None)
        if alcance is None:
            return queryset.none()
        if alcance == "ASIGNADO":
            return (
                queryset.filter(**{campo_asignado: usuario.pk})
                if campo_asignado
                else queryset.none()
            )
        if alcance == "PROPIO":
            return (
                queryset.filter(**{campo_propio: usuario.pk}) if campo_propio else queryset.none()
            )
        return queryset  # ORGANIZACION / EMPRESA / SUCURSAL: ya acotado a la organización

    completas: list[int] = []
    parciales: list[Q] = []
    for empresa_id in motor.empresas_ids_de(usuario):
        permisos = motor.permisos_de(usuario, empresa_id)
        alcance = permisos.permisos.get(codigo)
        if alcance is None:
            continue
        if alcance in EMPRESA_COMPLETA:
            completas.append(empresa_id)
        elif alcance == "SUCURSAL" and campo_sucursal and permisos.sucursal_ids:
            parciales.append(
                Q(**{campo_empresa: empresa_id, f"{campo_sucursal}__in": permisos.sucursal_ids})
            )
        elif alcance == "ASIGNADO" and campo_asignado:
            parciales.append(Q(**{campo_empresa: empresa_id, campo_asignado: usuario.pk}))
        elif alcance == "PROPIO" and campo_propio:
            parciales.append(Q(**{campo_empresa: empresa_id, campo_propio: usuario.pk}))

    condiciones = list(parciales)
    if completas:
        condiciones.append(Q(**{f"{campo_empresa}__in": completas}))
    if not condiciones:
        return queryset.none()
    return queryset.filter(reduce(or_, condiciones))


class ScopedQuerysetMixin:
    """Mixin de vistas de listado: aplica ``filtrar_por_alcance`` con el permiso de la vista.

    Declarar en la vista el modelo y los campos propios del recurso::

        modelo = Venta                    # NO usar ``queryset = Venta.objects.all()``
        campo_empresa = "empresa_id"      # None si el recurso es de la organización
        campo_propio = "creado_por_id"
        campo_asignado = "tecnico_id"     # opcional
        campo_sucursal = "sucursal_id"    # opcional

    Importante: los gestores con ámbito fallan cerrado sin tenant activo, así que un
    ``queryset = Modelo.objects.all()`` a nivel de clase se evaluaría al IMPORTAR el módulo
    y lanzaría ``ContextoTenantNoDefinido``. Con ``modelo`` el queryset se arma por petición.
    """

    modelo = None

    campo_empresa: str | None = "empresa_id"
    campo_propio: str | None = "creado_por_id"
    campo_asignado: str | None = None
    campo_sucursal: str | None = None

    def get_queryset(self):
        queryset = self.modelo.objects.all() if self.modelo is not None else super().get_queryset()
        codigo = codigo_requerido(self, self.request)
        if codigo is None:
            return queryset.none()
        return filtrar_por_alcance(
            queryset,
            self.request.user,
            codigo,
            campo_empresa=self.campo_empresa,
            campo_propio=self.campo_propio,
            campo_asignado=self.campo_asignado,
            campo_sucursal=self.campo_sucursal,
        )
