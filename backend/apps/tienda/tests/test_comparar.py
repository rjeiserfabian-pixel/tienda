"""Comparador público: hasta 4 productos con una tabla de especificaciones unificada."""

# ruff: noqa: F811

import pytest
from rest_framework.test import APIClient

from apps.mantenimiento.models import CampoEspecificacion, Producto

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/tienda/comparar"


def ids(*productos):
    return ",".join(str(p.pk) for p in productos)


def valores(producto, **datos):
    Producto.objects.sin_ambito().filter(pk=producto.pk).update(especificaciones=datos)


def preparar(tienda):
    """Dos laptops con RAM y SSD distintos y un campo que nadie llena."""
    tienda.campo(
        tienda.laptops,
        "RAM",
        CampoEspecificacion.Tipo.NUMERO,
        clave="ram",
        unidad="GB",
        seccion="Memoria",
        orden=1,
    )
    tienda.campo(
        tienda.laptops,
        "Pantalla",
        CampoEspecificacion.Tipo.TEXTO,
        clave="pantalla",
        seccion="Pantalla",
        orden=2,
    )
    tienda.campo(
        tienda.laptops,
        "Color",
        CampoEspecificacion.Tipo.TEXTO,
        clave="color",
        seccion="General",
        orden=3,
    )
    tienda.campo(
        tienda.laptops,
        "Vacío",
        CampoEspecificacion.Tipo.TEXTO,
        clave="vacio",
        seccion="General",
        orden=4,
    )
    a = tienda.publicar("Laptop A", precio=1000, stock=5, marca=tienda.hp, garantia_meses=12)
    b = tienda.publicar("Laptop B", precio=2000, stock=5, marca=tienda.lenovo)
    valores(a, ram=8, pantalla="15.6", color="Plata")
    valores(b, ram=16, pantalla="15.6")
    return a, b


def filas(respuesta):
    return {f["nombre"]: f for s in respuesta["secciones"] for f in s["filas"]}


class TestComparar:
    def test_compara_dos_de_la_misma_categoria(self, tienda):
        a, b = preparar(tienda)
        r = APIClient().get(URL, {"ids": ids(a, b)})
        assert r.status_code == 200, r.content
        d = r.json()
        assert [p["nombre"] for p in d["productos"]] == ["Laptop A", "Laptop B"]
        assert d["misma_categoria"] is True and d["avisos"] == []
        f = filas(d)
        assert f["RAM"]["valores"] == ["8 GB", "16 GB"] and f["RAM"]["difiere"] is True
        assert f["Pantalla"]["valores"] == ["15.6", "15.6"] and f["Pantalla"]["difiere"] is False
        assert f["Color"]["valores"] == ["Plata", None] and f["Color"]["difiere"] is True
        assert "Vacío" not in f  # nadie tiene el dato: no se muestra
        assert [s["seccion"] for s in d["secciones"]][0] == "Datos del producto"
        assert f["Marca"]["valores"] == ["HP", "Lenovo"] and f["Garantía"]["valores"] == [
            "12 meses",
            None,
        ]

    def test_trae_el_mismo_precio_y_disponibilidad_que_la_ficha_y_ningun_costo(self, tienda):
        a, b = preparar(tienda)
        d = APIClient().get(URL, {"ids": ids(a, b)}).json()
        ficha = APIClient().get(f"/api/v1/tienda/productos/{a.slug}").json()
        p = d["productos"][0]
        assert (
            p["precio_mostrar"] == ficha["precio_mostrar"]
            and p["disponibilidad"] == ficha["disponibilidad"]
        )
        texto = str(d).lower()
        for prohibido in ("costo", "utilidad", "stock_web"):
            assert prohibido not in texto

    def test_categorias_distintas_se_unen_por_nombre_de_campo(self, tienda):
        tienda.campo(
            tienda.laptops,
            "Color",
            CampoEspecificacion.Tipo.TEXTO,
            clave="color",
            seccion="General",
        )
        tienda.campo(
            tienda.mouse,
            "Color",
            CampoEspecificacion.Tipo.TEXTO,
            clave="color-mouse",
            seccion="General",
        )
        a = tienda.publicar("Laptop", precio=1000, stock=2)
        m = tienda.publicar("Mouse", categoria=tienda.mouse, precio=50, stock=2)
        valores(a, color="Plata")
        Producto.objects.sin_ambito().filter(pk=m.pk).update(
            especificaciones={"color-mouse": "Negro"}
        )
        d = APIClient().get(URL, {"ids": ids(a, m)}).json()
        assert d["misma_categoria"] is False
        assert filas(d)["Color"]["valores"] == ["Plata", "Negro"]

    def test_ids_invalidos_repetidos_y_no_publicados(self, tienda):
        a, b = preparar(tienda)
        oculto = tienda.publicar("Oculto", precio=10, stock=1, publicado=False)
        r = APIClient().get(URL, {"ids": f"{a.pk},{a.pk},abc,-3,0,{b.pk},{oculto.pk},99999999999"})
        assert r.status_code == 200
        d = r.json()
        assert [p["id"] for p in d["productos"]] == [a.pk, b.pk]  # repetido, basura y oculto fuera
        assert len(d["avisos"]) == 1 and str(oculto.pk) in d["avisos"][0]

    def test_mas_de_cuatro_o_ninguno_es_400(self, tienda):
        cinco = [tienda.publicar(f"P{i}", precio=10, stock=1) for i in range(5)]
        assert APIClient().get(URL, {"ids": ids(*cinco)}).status_code == 400
        assert APIClient().get(URL, {"ids": ids(*cinco[:4])}).status_code == 200
        assert APIClient().get(URL).status_code == 400
        assert APIClient().get(URL, {"ids": "x,y"}).status_code == 400

    def test_un_producto_de_otra_organizacion_no_se_compara(self, tienda):
        # El id de un producto que no es de la tienda se trata como no disponible.
        a, _ = preparar(tienda)
        r = APIClient().get(URL, {"ids": f"{a.pk},987654"}).json()
        assert [p["id"] for p in r["productos"]] == [a.pk] and len(r["avisos"]) == 1

    def test_tienda_cerrada_y_cache_publica(self, tienda):
        a, b = preparar(tienda)
        r = APIClient().get(URL, {"ids": ids(a, b)})
        assert "public" in r["Cache-Control"]
        tienda.config.activa = False
        tienda.config.save()
        from django.core.cache import cache

        cache.clear()
        assert APIClient().get(URL, {"ids": ids(a, b)}).status_code == 503

    def test_funciona_sin_barra_final_y_con_ella(self, tienda):
        a, b = preparar(tienda)
        assert APIClient().get(URL + "/", {"ids": ids(a, b)}).status_code == 200
