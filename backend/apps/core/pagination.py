"""Paginación obligatoria: 25 por defecto, máximo 100."""

from rest_framework.pagination import CursorPagination, PageNumberPagination

TAMANOS_PERMITIDOS = (10, 25, 50, 100)
TAMANO_POR_DEFECTO = 25
TAMANO_MAXIMO = 100


class PaginaEstandar(PageNumberPagination):
    """Para pantallas con tablas: ``?page=2&page_size=50``."""

    page_size = TAMANO_POR_DEFECTO
    page_size_query_param = "page_size"
    max_page_size = TAMANO_MAXIMO
    tamanos_permitidos = TAMANOS_PERMITIDOS

    def get_page_size(self, request):
        tamano = super().get_page_size(request)
        # Valores fuera del catálogo caen al tamaño por defecto.
        return tamano if tamano in self.tamanos_permitidos else self.page_size


class PaginaAuditoria(PaginaEstandar):
    """Auditoría: 20 filas por defecto (10, 20, 50 o 100), con número de página y total."""

    page_size = 20
    tamanos_permitidos = (10, 20, 50, 100)


class PaginaSesiones(PaginaAuditoria):
    """Mis sesiones: igual que Auditoría (20 por defecto, con número de página y total)."""


class PaginacionCursor(CursorPagination):
    """Para tablas que crecen sin fin (auditoría, sesiones, movimientos)."""

    page_size = TAMANO_POR_DEFECTO
    page_size_query_param = "page_size"
    max_page_size = TAMANO_MAXIMO
    ordering = ("-creado_en", "-id")
