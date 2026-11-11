"""Paginación obligatoria: ningún listado puede devolver todo sin límite."""

import pytest
from django.urls import get_resolver
from rest_framework.mixins import ListModelMixin
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.core.pagination import PaginacionCursor, PaginaEstandar

# Catálogos que se exponen completos A PROPÓSITO (clase -> justificación).
# Declararlos aquí es una decisión explícita, nunca un olvido.
SIN_PAGINAR_A_PROPOSITO: dict[str, str] = {
    "CatalogoPermisosView": "La matriz de roles necesita el catálogo entero (acotado en código).",
}


def _vistas_del_proyecto():
    def recorrer(patrones):
        for patron in patrones:
            if hasattr(patron, "url_patterns"):
                yield from recorrer(patron.url_patterns)
                continue
            callback = patron.callback
            clase = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
            if clase is not None:
                yield clase, getattr(callback, "actions", None)

    yield from recorrer(get_resolver().url_patterns)


def _es_listado(clase, acciones) -> bool:
    if acciones is not None:  # ViewSet
        return "list" in acciones.values() and issubclass(clase, ListModelMixin)
    return issubclass(clase, ListModelMixin)


def listados_sin_paginar(vistas):
    return [
        clase.__name__
        for clase, acciones in vistas
        if _es_listado(clase, acciones)
        and clase.pagination_class is None
        and clase.__name__ not in SIN_PAGINAR_A_PROPOSITO
    ]


def test_todo_listado_del_proyecto_pagina():
    assert listados_sin_paginar(_vistas_del_proyecto()) == []


def test_el_verificador_detecta_un_listado_sin_paginar():
    from rest_framework.generics import ListAPIView

    class ListadoSinPaginar(ListAPIView):
        pagination_class = None

    assert listados_sin_paginar([(ListadoSinPaginar, None)]) == ["ListadoSinPaginar"]


@pytest.mark.parametrize(
    ("pedido", "esperado"),
    [(None, 25), ("10", 10), ("50", 50), ("100", 100), ("30", 25), ("500", 100), ("abc", 25)],
)
def test_tamano_de_pagina(pedido, esperado):
    consulta = {"page_size": pedido} if pedido else {}
    request = Request(APIRequestFactory().get("/", consulta))
    assert PaginaEstandar().get_page_size(request) == esperado


def test_cursor_usa_25_por_defecto_y_maximo_100():
    assert PaginacionCursor.page_size == 25
    assert PaginacionCursor.max_page_size == 100
