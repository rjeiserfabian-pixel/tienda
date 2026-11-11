"""API pública de la tienda: qué se ve, qué NO se ve, filtros, fotos y caché."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.mantenimiento.models import CampoEspecificacion, Producto
from apps.tienda.models import ConfiguracionTienda

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

BASE = "/api/v1/tienda"


def cache_limpiar():
    cache.clear()


def get(ruta, **params):
    return APIClient().get(f"{BASE}/{ruta}", params)


def nombres(respuesta):
    return [p["nombre"] for p in respuesta.json()["results"]]


class TestDisponibilidad:
    def test_con_la_tienda_apagada_responde_503_sin_dar_detalles(self, tienda):
        tienda.config.activa = False
        tienda.config.save()
        r = get("productos/")
        assert r.status_code == 503
        assert r.json()["error"]["codigo"] == "tienda_no_disponible"

    def test_sin_configurar_responde_503(self, tienda):
        ConfiguracionTienda.objects.sin_ambito().all().delete()
        assert get("menu/").status_code == 503

    def test_dos_tiendas_activas_sin_indicar_cual_no_se_adivina(self, tienda, settings):
        from apps.core.tenant import establecer_contexto

        e = tienda.e
        org_b = e.e.org_b
        establecer_contexto(org_b.pk, [e.e.emp_b1.pk], e.e.usuario_id)
        ConfiguracionTienda.objects.sin_ambito().create(
            organizacion=org_b, activa=True, nombre="Otra"
        )
        establecer_contexto(tienda.org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)
        assert get("menu/").status_code == 503
        settings.TIENDA_ORGANIZACION_ID = tienda.org.pk
        cache_limpiar()
        assert get("menu/").status_code == 200

    def test_no_pide_sesion_ni_deja_cookies(self, tienda):
        tienda.publicar("Laptop", precio=100)
        r = get("productos/")
        assert r.status_code == 200 and not r.cookies


class TestSoloLoPublicado:
    def test_se_ven_solo_los_publicados_activos_de_categorias_activas(self, tienda):
        tienda.publicar("Visible", precio=100)
        tienda.publicar("Borrador", precio=100, publicado=False)
        tienda.publicar("Inactivo", precio=100, estado="INACTIVO")
        escondida = tienda.publicar("En categoría inactiva", precio=100, categoria=tienda.mouse)
        tienda.mouse.estado = "INACTIVO"
        tienda.mouse.save()
        assert escondida.pk
        assert nombres(get("productos/")) == ["Visible"]

    def test_un_producto_no_publicado_da_404_aunque_se_conozca_su_direccion(self, tienda):
        p = tienda.publicar("Borrador", precio=100, publicado=False)
        Producto.objects.sin_ambito().filter(pk=p.pk).update(slug="borrador")
        assert get("productos/borrador/").status_code == 404

    def test_los_productos_de_otra_organizacion_no_aparecen(self, tienda):
        ajeno = tienda.e.ajeno
        Producto.objects.sin_ambito().filter(pk=ajeno.pk).update(publicado_web=True, slug="ajeno")
        assert get("productos/ajeno/").status_code == 404
        assert "Producto ajeno" not in nombres(get("productos/"))

    def test_nunca_se_expone_costo_utilidad_ni_stock_exacto(self, tienda):
        tienda.publicar("Laptop", precio=100, stock=37, costo=Decimal("60"))
        r = get("productos/")
        texto = r.content.decode()
        for prohibido in ("costo", "utilidad", "stock_web", "organizacion"):
            assert prohibido not in texto, prohibido
        assert r.json()["results"][0]["unidades"] is None  # 37 en stock: no se dice cuántas
        ficha = get("productos/laptop/").content.decode()
        for prohibido in ("costo", "utilidad", "stock_web", "organizacion"):
            assert prohibido not in ficha, prohibido


class TestPreciosYStock:
    def test_el_precio_web_sale_de_la_lista_y_se_le_suma_el_igv(self, tienda):
        tienda.publicar("Laptop", precio=100)
        p = get("productos/").json()["results"][0]
        assert (p["precio"], p["precio_con_igv"], p["precio_mostrar"]) == (
            "100.00",
            "118.00",
            "118.00",
        )
        assert p["incluye_igv"] is True and p["consultar_precio"] is False

    def test_se_puede_mostrar_el_precio_sin_igv(self, tienda):
        tienda.config.precios_con_igv = False
        tienda.config.save()
        tienda.publicar("Laptop", precio=100)
        p = get("productos/").json()["results"][0]
        assert (p["precio_mostrar"], p["incluye_igv"]) == ("100.00", False)

    def test_un_producto_exonerado_no_suma_igv(self, tienda):
        from apps.mantenimiento.models import AfectacionIGV

        exonerado = (
            AfectacionIGV.objects.sin_ambito()
            .filter(organizacion=tienda.org, grupo="EXONERADO")
            .first()
        )
        assert exonerado is not None
        tienda.publicar("Libro", precio=50, afectacion_igv=exonerado)
        p = get("productos/").json()["results"][0]
        assert p["precio_con_igv"] == "50.00"

    def test_sin_precio_en_la_lista_pide_consultar(self, tienda):
        tienda.publicar("Sin precio")
        p = get("productos/").json()["results"][0]
        assert (p["consultar_precio"], p["precio"], p["precio_mostrar"]) == (True, None, None)

    def test_la_disponibilidad_no_revela_el_stock_exacto(self, tienda):
        tienda.publicar("Agotado", precio=1, stock=0)
        tienda.publicar("Pocas", precio=1, stock=3)
        tienda.publicar("Muchas", precio=1, stock=50)
        por_nombre = {p["nombre"]: p for p in get("productos/").json()["results"]}
        assert (por_nombre["Agotado"]["disponibilidad"], por_nombre["Agotado"]["unidades"]) == (
            "agotado",
            0,
        )
        assert (por_nombre["Pocas"]["disponibilidad"], por_nombre["Pocas"]["unidades"]) == (
            "pocas",
            3,
        )
        assert (por_nombre["Muchas"]["disponibilidad"], por_nombre["Muchas"]["unidades"]) == (
            "disponible",
            None,
        )

    def test_el_stock_suma_solo_los_almacenes_elegidos(self, tienda):
        tienda.publicar("Laptop", precio=1, stock=40)
        tienda.config.almacenes.set([tienda.e.alm2])  # el stock está en alm1
        from apps.tienda import catalogo

        catalogo.invalidar()
        assert get("productos/").json()["results"][0]["disponibilidad"] == "agotado"

    def test_un_servicio_siempre_figura_disponible(self, tienda):
        tienda.publicar("Instalación", precio=30, tipo="SERVICIO", controla_stock=False)
        assert get("productos/").json()["results"][0]["disponibilidad"] == "disponible"


class TestListado:
    def _surtido(self, tienda):
        tienda.publicar(
            "Lenovo IdeaPad", marca=tienda.lenovo, precio=1000, stock=10, destacado=True
        )
        tienda.publicar("HP Pavilion", marca=tienda.hp, precio=2000, stock=10, es_nuevo=True)
        tienda.publicar("Lenovo Legion", marca=tienda.lenovo, precio=3000, stock=0)
        tienda.publicar("Mouse Logitech", categoria=tienda.mouse, precio=50, stock=10)

    def test_filtra_por_categoria_y_marca(self, tienda):
        self._surtido(tienda)
        assert sorted(nombres(get("productos/", categoria="laptops"))) == [
            "HP Pavilion", "Lenovo IdeaPad", "Lenovo Legion",
        ]  # fmt: skip
        assert sorted(nombres(get("productos/", categoria="laptops", marca="lenovo"))) == [
            "Lenovo IdeaPad", "Lenovo Legion",
        ]  # fmt: skip
        varias = APIClient().get(f"{BASE}/productos/?marca=lenovo&marca=hp")
        assert varias.json()["count"] == 3

    def test_una_categoria_que_no_existe_da_404(self, tienda):
        assert get("productos/", categoria="no-existe").status_code == 404
        assert get("productos/", familia="no-existe").status_code == 404

    def test_filtra_por_familia(self, tienda):
        self._surtido(tienda)
        assert get("productos/", familia="computadoras").json()["count"] == 4

    def test_busca_por_texto_en_nombre_marca_y_categoria(self, tienda):
        self._surtido(tienda)
        assert sorted(nombres(get("productos/", q="legion"))) == ["Lenovo Legion"]
        assert get("productos/", q="hp pavilion").json()["count"] == 1
        assert get("productos/", q="mouse").json()["count"] == 1  # por nombre y por categoría
        assert get("productos/", q="zzzz").json()["count"] == 0

    def test_filtra_por_precio_mostrado_con_igv(self, tienda):
        self._surtido(tienda)
        # 1000 + IGV = 1180: «entre 1000 y 1200» deja solo ese
        r = get("productos/", precio_min="1000", precio_max="1200", categoria="laptops")
        assert nombres(r) == ["Lenovo IdeaPad"]

    def test_solo_disponibles_nuevos_y_destacados(self, tienda):
        self._surtido(tienda)
        assert "Lenovo Legion" not in nombres(get("productos/", disponible="1"))
        assert nombres(get("productos/", nuevo="1")) == ["HP Pavilion"]
        assert nombres(get("productos/", destacado="1")) == ["Lenovo IdeaPad"]

    def test_ordena_por_precio_y_nombre_con_los_sin_precio_al_final(self, tienda):
        self._surtido(tienda)
        tienda.publicar("Zeta sin precio")
        asc = nombres(get("productos/", categoria="laptops", orden="precio_asc"))
        assert asc == ["Lenovo IdeaPad", "HP Pavilion", "Lenovo Legion", "Zeta sin precio"]
        desc = nombres(get("productos/", categoria="laptops", orden="precio_desc"))
        assert (
            desc[:3] == ["Lenovo Legion", "HP Pavilion", "Lenovo IdeaPad"]
            and desc[-1] == "Zeta sin precio"
        )
        assert nombres(get("productos/", categoria="laptops", orden="nombre"))[0] == "HP Pavilion"

    def test_la_relevancia_pone_primero_los_destacados_y_novedades(self, tienda):
        self._surtido(tienda)
        assert nombres(get("productos/", categoria="laptops"))[:2] == [
            "Lenovo IdeaPad",
            "HP Pavilion",
        ]

    def test_pagina_y_limita_el_tamano(self, tienda):
        for i in range(5):
            tienda.publicar(f"Laptop {i}", precio=100 + i)
        r = get("productos/", page_size="2", page="2", orden="nombre").json()
        assert (r["count"], r["page"], r["page_size"], r["paginas"], len(r["results"])) == (
            5,
            2,
            2,
            3,
            2,
        )
        enorme = get("productos/", page_size="5000").json()
        assert enorme["page_size"] == 48
        fuera = get("productos/", page="99").json()
        assert fuera["page"] == fuera["paginas"] == 1

    def test_los_parametros_basura_no_rompen_nada(self, tienda):
        tienda.publicar("Laptop", precio=100)
        r = get(
            "productos/",
            page="abc",
            page_size="-4",
            precio_min="x",
            precio_max="y",
            orden="'; drop",
        )
        assert r.status_code == 200 and r.json()["count"] == 1

    def test_la_tarjeta_trae_los_datos_clave_de_su_categoria(self, tienda):
        tienda.campo(tienda.laptops, "Memoria RAM", "NUMERO", unidad="GB", en_tarjeta=True, orden=1)
        tienda.campo(tienda.laptops, "Táctil", "SI_NO", clave="tactil", en_tarjeta=True, orden=2)
        tienda.campo(tienda.laptops, "Color", "TEXTO", orden=3)  # no es de tarjeta
        p = tienda.publicar("Laptop", precio=100)
        Producto.objects.sin_ambito().filter(pk=p.pk).update(
            especificaciones={"memoria-ram": "16", "tactil": False, "color": "Gris"}
        )
        from apps.tienda import catalogo

        catalogo.invalidar()
        tarjeta = get("productos/").json()["results"][0]["tarjeta"]
        assert tarjeta == [
            {"nombre": "Memoria RAM", "valor": "16 GB"},
            {"nombre": "Táctil", "valor": "No"},
        ]


class TestFiltrosPorEspecificacion:
    def _con_ram(self, tienda):
        tienda.campo(tienda.laptops, "Memoria RAM", "NUMERO", unidad="GB", es_filtro=True, orden=1)
        tienda.campo(
            tienda.laptops,
            "Tipo de memoria",
            "LISTA",
            clave="tipo-de-memoria",
            opciones=["DDR4", "DDR5"],
            es_filtro=True,
            orden=2,
        )
        tienda.campo(tienda.laptops, "Táctil", "SI_NO", clave="tactil", es_filtro=True, orden=3)
        tienda.campo(tienda.laptops, "Serie", "TEXTO", orden=4)
        datos = [
            ("Laptop A", {"memoria-ram": "8", "tipo-de-memoria": "DDR4", "tactil": False}),
            ("Laptop B", {"memoria-ram": "16", "tipo-de-memoria": "DDR5", "tactil": True}),
            ("Laptop C", {"memoria-ram": "16", "tipo-de-memoria": "DDR4", "tactil": False}),
            ("Laptop D", {"memoria-ram": "32", "tipo-de-memoria": "DDR5", "tactil": False}),
        ]
        for nombre, esp in datos:
            p = tienda.publicar(nombre, precio=100)
            Producto.objects.sin_ambito().filter(pk=p.pk).update(especificaciones=esp)
        from apps.tienda import catalogo

        catalogo.invalidar()

    def test_filtra_por_un_valor_o_varios_de_un_mismo_dato(self, tienda):
        self._con_ram(tienda)
        r = get("productos/", categoria="laptops", **{"esp.memoria-ram": "16"})
        assert sorted(nombres(r)) == ["Laptop B", "Laptop C"]
        varios = APIClient().get(
            f"{BASE}/productos/?categoria=laptops&esp.memoria-ram=8&esp.memoria-ram=32"
        )
        assert sorted(nombres(varios)) == ["Laptop A", "Laptop D"]

    def test_combina_datos_distintos_con_y(self, tienda):
        self._con_ram(tienda)
        r = get(
            "productos/",
            categoria="laptops",
            **{"esp.memoria-ram": "16", "esp.tipo-de-memoria": "DDR5"},
        )
        assert nombres(r) == ["Laptop B"]

    def test_acepta_numeros_con_coma_y_mayusculas_en_las_listas(self, tienda):
        self._con_ram(tienda)
        assert nombres(get("productos/", categoria="laptops", **{"esp.memoria-ram": "16,0"})) != []
        assert (
            len(nombres(get("productos/", categoria="laptops", **{"esp.tipo-de-memoria": "ddr5"})))
            == 2
        )

    def test_si_no_con_1_y_0(self, tienda):
        self._con_ram(tienda)
        assert nombres(get("productos/", categoria="laptops", **{"esp.tactil": "1"})) == [
            "Laptop B"
        ]
        assert len(nombres(get("productos/", categoria="laptops", **{"esp.tactil": "0"}))) == 3

    def test_ignora_filtros_de_campos_que_no_son_filtro_o_no_existen(self, tienda):
        self._con_ram(tienda)
        r = get(
            "productos/",
            categoria="laptops",
            **{"esp.serie": "x", "esp.inventado": "1", "esp.memoria-ram": "zzz"},
        )
        assert r.json()["count"] == 4  # nada de eso filtra

    def test_sin_categoria_no_se_filtra_por_especificaciones(self, tienda):
        self._con_ram(tienda)
        assert get("productos/", **{"esp.memoria-ram": "16"}).json()["count"] == 4

    def test_las_facetas_ofrecen_las_opciones_con_sus_cantidades(self, tienda):
        self._con_ram(tienda)
        f = get("productos/", categoria="laptops", facetas="1").json()["filtros"]
        por_clave = {e["clave"]: e for e in f["especificaciones"]}
        assert [(o["valor"], o["cantidad"]) for o in por_clave["memoria-ram"]["opciones"]] == [
            ("8", 1), ("16", 2), ("32", 1),
        ]  # fmt: skip
        assert por_clave["memoria-ram"]["opciones"][0]["etiqueta"] == "8 GB"
        assert [(o["valor"], o["cantidad"]) for o in por_clave["tipo-de-memoria"]["opciones"]] == [
            ("DDR4", 2), ("DDR5", 2),
        ]  # fmt: skip
        assert [(o["etiqueta"], o["cantidad"]) for o in por_clave["tactil"]["opciones"]] == [
            ("Sí", 1), ("No", 3),
        ]  # fmt: skip
        assert "serie" not in por_clave  # el texto libre no es filtro
        assert f["precio"]["minimo"] == "118.00" and f["precio"]["maximo"] == "118.00"

    def test_las_facetas_traen_las_marcas_con_cantidades(self, tienda):
        tienda.publicar("A", marca=tienda.lenovo, precio=1)
        tienda.publicar("B", marca=tienda.lenovo, precio=1)
        tienda.publicar("C", marca=tienda.hp, precio=1)
        f = get("productos/", facetas="1").json()["filtros"]
        assert [(m["slug"], m["cantidad"]) for m in f["marcas"]] == [("hp", 1), ("lenovo", 2)]

    def test_un_campo_quitado_de_la_plantilla_ya_no_filtra(self, tienda):
        self._con_ram(tienda)
        CampoEspecificacion.objects.sin_ambito().filter(clave="memoria-ram").update(
            estado="INACTIVO"
        )
        from apps.tienda import catalogo

        catalogo.invalidar()
        r = get("productos/", categoria="laptops", **{"esp.memoria-ram": "16"})
        assert r.json()["count"] == 4


class TestFicha:
    def test_trae_todo_lo_que_la_tienda_necesita(self, tienda):
        tienda.campo(
            tienda.laptops, "Memoria RAM", "NUMERO", unidad="GB", seccion="Memoria", orden=1
        )
        tienda.campo(
            tienda.laptops,
            "Tipo",
            "LISTA",
            clave="tipo",
            opciones=["DDR4"],
            seccion="Memoria",
            orden=2,
        )
        tienda.campo(tienda.laptops, "Táctil", "SI_NO", clave="tactil", seccion="Pantalla", orden=3)
        p = tienda.publicar(
            "Laptop Lenovo IdeaPad",
            marca=tienda.lenovo,
            precio=1000,
            stock=3,
            fotos=2,
            codigo_fabricante="83K1016CLM",
            descripcion="Descripción interna",
            descripcion_web="Ideal para estudiar.",
            puntos_destacados=["Pantalla IPS", "SSD NVMe"],
            garantia_meses=12,
            peso_kg=Decimal("1.590"),
            largo_cm=Decimal("34.34"),
            es_nuevo=True,
        )
        Producto.objects.sin_ambito().filter(pk=p.pk).update(
            especificaciones={"memoria-ram": "16", "tipo": "DDR4", "tactil": False, "viejo": "x"}
        )
        from apps.tienda import catalogo

        catalogo.invalidar()
        r = get("productos/laptop-lenovo-ideapad/")
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["nombre"], d["numero_de_parte"], d["descripcion"]) == (
            "Laptop Lenovo IdeaPad", "83K1016CLM", "Ideal para estudiar.",
        )  # fmt: skip
        assert d["marca"] == {"nombre": "Lenovo", "slug": "lenovo"}
        assert d["puntos_destacados"] == ["Pantalla IPS", "SSD NVMe"]
        assert d["especificaciones"] == [
            {"seccion": "Memoria", "datos": [
                {"nombre": "Memoria RAM", "valor": "16 GB"}, {"nombre": "Tipo", "valor": "DDR4"},
            ]},
            {"seccion": "Pantalla", "datos": [{"nombre": "Táctil", "valor": "No"}]},
        ]  # fmt: skip
        assert (d["garantia_meses"], d["peso_kg"], d["medidas_cm"]["largo"]) == (
            12,
            "1.590",
            "34.34",
        )
        assert (d["disponibilidad"], d["unidades"], d["nuevo"]) == ("pocas", 3, True)
        assert [f["principal"] for f in d["fotos"]] == [True, False]
        assert d["fotos"][0]["grande"].endswith("/grande/") and d["fotos"][0]["mini"].endswith(
            "/mini/"
        )
        assert [m["tipo"] for m in d["migas"]] == ["inicio", "familia", "categoria"]
        assert d["seo"]["titulo"].startswith("Laptop Lenovo IdeaPad") and d["seo"]["descripcion"]

    def test_sin_descripcion_web_usa_la_descripcion_normal(self, tienda):
        tienda.publicar("Laptop", precio=1, descripcion="Descripción interna")
        assert get("productos/laptop/").json()["descripcion"] == "Descripción interna"

    def test_los_relacionados_son_de_la_misma_categoria_publicados_y_sin_el_mismo(self, tienda):
        tienda.publicar("Laptop 1", precio=1)
        tienda.publicar("Laptop 2", precio=1)
        tienda.publicar("Borrador", precio=1, publicado=False)
        tienda.publicar("Mouse", categoria=tienda.mouse, precio=1)
        rel = get("productos/laptop-1/").json()["relacionados"]
        assert [p["nombre"] for p in rel] == ["Laptop 2"]


class TestMenuInicioSugerenciasSitemap:
    def test_el_menu_trae_solo_lo_que_tiene_productos_con_sus_cantidades(self, tienda):
        tienda.publicar("Laptop 1", marca=tienda.lenovo, precio=1)
        tienda.publicar("Laptop 2", marca=tienda.lenovo, precio=1)
        tienda.publicar("Borrador", categoria=tienda.mouse, precio=1, publicado=False)
        m = get("menu/").json()
        assert m["tienda"] == {"nombre": "Technology", "precios_con_igv": True}
        assert [(f["slug"], f["cantidad"]) for f in m["familias"]] == [("computadoras", 2)]
        assert [(c["slug"], c["cantidad"]) for c in m["familias"][0]["categorias"]] == [
            ("laptops", 2)
        ]
        assert [(x["slug"], x["cantidad"]) for x in m["marcas"]] == [("lenovo", 2)]

    def test_el_inicio_trae_destacados_y_novedades(self, tienda):
        tienda.publicar("Estrella", precio=1, destacado=True)
        tienda.publicar("Nueva", precio=1, es_nuevo=True)
        tienda.publicar("Común", precio=1)
        d = get("inicio/").json()
        assert [p["nombre"] for p in d["destacados"]] == ["Estrella"]
        assert [p["nombre"] for p in d["novedades"]] == ["Nueva"]

    def test_las_sugerencias_piden_al_menos_dos_letras(self, tienda):
        tienda.publicar("Laptop Lenovo", marca=tienda.lenovo, precio=100)
        assert get("sugerencias/", q="l").json() == {
            "productos": [],
            "categorias": [],
            "marcas": [],
        }
        d = get("sugerencias/", q="len").json()
        assert [p["nombre"] for p in d["productos"]] == ["Laptop Lenovo"]
        assert [m["slug"] for m in d["marcas"]] == ["lenovo"]
        assert get("sugerencias/", q="lapt").json()["categorias"][0]["slug"] == "laptops"

    def test_el_mapa_del_sitio_lista_solo_lo_publico(self, tienda):
        tienda.publicar("Visible", precio=1)
        tienda.publicar("Borrador", precio=1, publicado=False)
        s = get("sitemap/").json()
        assert [p["slug"] for p in s["productos"]] == ["visible"]
        assert s["categorias"] == ["laptops"]


class TestFotos:
    def test_se_sirven_con_cache_largo_y_solo_las_de_productos_publicados(self, tienda):
        p = tienda.publicar("Laptop", precio=1)
        foto = p.fotos.first()
        r = get(f"fotos/{foto.pk}/mini/")
        contenido = b"".join(r.streaming_content)  # leerla completa también cierra el archivo
        assert contenido[:4] == b"RIFF"  # un WebP de verdad
        assert r.status_code == 200
        assert r["Content-Type"] == "image/webp"
        assert "immutable" in r["Cache-Control"] and r["X-Content-Type-Options"] == "nosniff"
        grande = get(f"fotos/{foto.pk}/grande/")
        assert grande.status_code == 200
        b"".join(grande.streaming_content)

    def test_la_foto_de_un_producto_no_publicado_da_404(self, tienda):
        p = tienda.publicar("Borrador", precio=1, publicado=False)
        assert get(f"fotos/{p.fotos.first().pk}/mini/").status_code == 404

    def test_tamanos_raros_o_fotos_inexistentes_dan_404(self, tienda):
        p = tienda.publicar("Laptop", precio=1)
        foto = p.fotos.first()
        assert get(f"fotos/{foto.pk}/original/").status_code == 404
        assert get("fotos/99999999/mini/").status_code == 404

    def test_la_ficha_apunta_a_fotos_que_si_se_pueden_abrir(self, tienda):
        tienda.publicar("Laptop", precio=1)
        url = get("productos/laptop/").json()["fotos"][0]["mini"]
        r = APIClient().get(url)
        assert r.status_code == 200
        b"".join(r.streaming_content)


class TestCache:
    def test_las_respuestas_traen_cabeceras_para_guardarse(self, tienda):
        tienda.publicar("Laptop", precio=1)
        r = get("productos/")
        assert "public" in r["Cache-Control"] and "s-maxage=60" in r["Cache-Control"]

    def test_un_cambio_en_el_catalogo_se_ve_de_inmediato(self, tienda):
        p = tienda.publicar("Laptop", precio=100)
        assert get("productos/").json()["count"] == 1
        p.publicado_web = False
        p.save()  # la señal invalida la caché
        assert get("productos/").json()["count"] == 0

    def test_cambiar_el_precio_se_ve_de_inmediato(self, tienda):
        p = tienda.publicar("Laptop", precio=100)
        fila = p.precios.first()
        assert get("productos/").json()["results"][0]["precio"] == "100.00"
        fila.precio = Decimal("200")
        fila.save()
        assert get("productos/").json()["results"][0]["precio"] == "200.00"


class TestDireccionesConYSinBarraFinal:
    """El sitio en Next.js quita la barra final: la API debe responder igual con o sin ella."""

    def test_todas_las_rutas_publicas_aceptan_ambas_formas(self, tienda):
        p = tienda.publicar("Laptop", precio=100)
        foto = p.fotos.first()
        for ruta in (
            "menu",
            "inicio",
            "productos",
            "sugerencias?q=lap",
            "sitemap",
            "productos/laptop",
        ):
            con_barra = ruta.replace("?", "/?") if "?" in ruta else ruta + "/"
            assert get(ruta).status_code == 200, ruta
            assert get(con_barra).status_code == 200, con_barra
        for ruta in (f"fotos/{foto.pk}/mini", f"fotos/{foto.pk}/mini/"):
            r = get(ruta)
            assert r.status_code == 200, ruta
            b"".join(r.streaming_content)
