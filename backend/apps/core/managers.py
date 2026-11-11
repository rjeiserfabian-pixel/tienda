"""Gestores y QuerySets: borrado lógico y aislamiento por ámbito (fail-closed)."""

from django.db import models
from django.utils import timezone

from .exceptions import DocumentoInmutableError
from .tenant import obtener_contexto_requerido


class QuerySetBase(models.QuerySet):
    """QuerySet con borrado lógico y validación de ámbito en inserciones masivas."""

    def delete(self):
        """Borrado lógico: nada con valor contable se elimina físicamente."""
        ahora = timezone.now()
        eliminados = self.update(eliminado_en=ahora, actualizado_en=ahora)
        return eliminados, {self.model._meta.label: eliminados}

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.preparar_para_guardar()
        return super().bulk_create(objs, *args, **kwargs)


class QuerySetInmutable(QuerySetBase):
    """QuerySet de documentos emitidos: bloquea modificaciones masivas."""

    def update(self, **kwargs):
        raise DocumentoInmutableError()

    def delete(self):
        raise DocumentoInmutableError()

    def bulk_update(self, objs, fields, *args, **kwargs):
        raise DocumentoInmutableError()


class GestorBase(models.Manager.from_queryset(QuerySetBase)):
    """Excluye por defecto los registros eliminados lógicamente.

    El aislamiento por ámbito vive en un único punto (``_aplicar_ambito``) que
    usan TODAS las vías de acceso: ``get_queryset`` y ``con_eliminados``. Así no
    existe un camino que olvide filtrar por organización o empresa.
    """

    def _aplicar_ambito(self, queryset):
        return queryset

    def _con_ambito(self):
        return self._aplicar_ambito(super().get_queryset())

    def get_queryset(self):
        return self._con_ambito().filter(eliminado_en__isnull=True)

    def con_eliminados(self):
        """Incluye eliminados lógicos, SIEMPRE dentro del ámbito activo."""
        return self._con_ambito()

    def sin_ambito(self, *, incluir_eliminados: bool = False):
        """Acceso explícito sin aislamiento (comandos, login, tareas de plataforma)."""
        queryset = super().get_queryset()
        return queryset if incluir_eliminados else queryset.filter(eliminado_en__isnull=True)


class GestorOrganizacion(GestorBase):
    """Filtra por la organización del contexto. Sin contexto: error, no datos."""

    def _aplicar_ambito(self, queryset):
        contexto = obtener_contexto_requerido()
        return queryset.filter(organizacion_id=contexto.organizacion_id)


class GestorEmpresa(GestorBase):
    """Filtra por las empresas habilitadas del contexto. Sin contexto: error."""

    def _aplicar_ambito(self, queryset):
        contexto = obtener_contexto_requerido()
        return queryset.filter(empresa_id__in=contexto.empresa_ids)


class GestorEmpresaInmutable(GestorEmpresa):
    """Gestor de empresa cuyo QuerySet rechaza update/delete masivos."""

    _queryset_class = QuerySetInmutable
