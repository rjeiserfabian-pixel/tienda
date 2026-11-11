"""Especificaciones por categoría y datos de tienda del producto (fase 1 de la tienda virtual)."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

import pytest

from apps.mantenimiento import especificaciones
from apps.seguridad.tests.conftest import cliente_de

from .test_productos import (  # noqa: F401
    BASE,
    _auditoria_al_instante,
    _media_temporal,
    base,
    crear,
    equipo,
    png,
)

pytestmark = pytest.mark.django_db


def categoria_url(base, sufijo=""):
    return f"{BASE}/categorias/{base['categoria']['id']}/especificaciones/{sufijo}"


def guardar(base, campos, usuario="super"):
    return cliente_de(usuario).post(categoria_url(base), {"campos": campos}, format="json")


def campo(nombre, tipo="TEXTO", **extra):
    return {"nombre": nombre, "tipo": tipo, **extra}


def con_campos(base):
    """Una categoría con cuatro campos de cada tipo; devuelve el mapa nombre → clave."""
    r = guardar(
        base,
        [
            campo("Memoria RAM", "NUMERO", unidad="GB", es_filtro=True, en_tarjeta=True),
            campo("Tipo", "LISTA", opciones=["DDR4", "DDR5"], es_filtro=True),
            campo("Táctil", "SI_NO"),
            campo("Modelo", "TEXTO", seccion="Datos"),
        ],
    )
    assert r.status_code == 200, r.content
    return {c["nombre"]: c["clave"] for c in r.json()}


def subir_foto(base, producto_id):
    r = base["api"].post(
        f"{BASE}/productos/{producto_id}/fotos/", {"imagen": png()}, format="multipart"
    )
    assert r.status_code == 201, r.content
    return r.json()


class TestPlantillasDeEjemplo:
    def test_hay_trece_plantillas_con_sus_secciones(self, base):
        r = base["api"].get(f"{BASE}/categorias/plantillas-especificaciones/")
        assert r.status_code == 200, r.content
        claves = {p["clave"]: p for p in r.json()}
        assert set(claves) == {
            "laptop", "mouse", "teclado", "procesador", "memoria-ram", "ssd", "monitor",
            "placa-base", "impresora", "gabinete", "fuente-de-poder", "tarjeta-de-video",
            "refrigeracion",
        }  # fmt: skip
        assert claves["laptop"]["campos"] > 25 and "Pantalla" in claves["laptop"]["secciones"]

    def test_todas_son_validas_por_dentro(self):
        for clave, p in especificaciones.PLANTILLAS.items():
            nombres = [c["nombre"].lower() for c in p["campos"]]
            assert len(nombres) == len(set(nombres)), clave  # sin nombres repetidos
            assert len(nombres) <= especificaciones.MAX_CAMPOS, clave
            for c in p["campos"]:
                assert c["tipo"] in ("TEXTO", "NUMERO", "LISTA", "SI_NO")
                assert (c["tipo"] == "LISTA") == bool(c["opciones"]), (clave, c["nombre"])
                assert not (c["tipo"] == "TEXTO" and c["es_filtro"]), (clave, c["nombre"])

    def test_cargar_una_plantilla_crea_sus_campos_y_no_duplica_al_repetir(self, base):
        api = base["api"]
        r = api.post(categoria_url(base, "plantilla/"), {"plantilla": "mouse"}, format="json")
        assert r.status_code == 200, r.content
        campos = r.json()
        assert len(campos) == len(especificaciones.PLANTILLAS["mouse"]["campos"])
        assert campos[0]["orden"] == 1 and all(c["clave"] for c in campos)
        otra = api.post(categoria_url(base, "plantilla/"), {"plantilla": "mouse"}, format="json")
        assert len(otra.json()) == len(campos)
        lista = api.get(f"{BASE}/categorias/", {"q": "Teclado"}).json()["results"][0]
        assert lista["n_campos"] == len(campos)

    def test_una_plantilla_que_no_existe_da_400(self, base):
        r = base["api"].post(
            categoria_url(base, "plantilla/"), {"plantilla": "nave"}, format="json"
        )
        assert r.status_code == 400

    def test_cargar_encima_de_campos_propios_respeta_los_que_ya_hay(self, base):
        guardar(base, [campo("Resolución máxima", "NUMERO", unidad="DPI")])
        r = base["api"].post(
            categoria_url(base, "plantilla/"), {"plantilla": "mouse"}, format="json"
        )
        nombres = [c["nombre"] for c in r.json()]
        assert nombres.count("Resolución máxima") == 1


class TestPlantillaSobreCamposQuitados:
    """El caso real: se cargó una plantilla equivocada, se quitó, y luego se carga la correcta."""

    def test_cargar_la_plantilla_otra_vez_despues_de_quitar_todo_vuelve_a_llenarla(self, base):
        api = base["api"]
        api.post(categoria_url(base, "plantilla/"), {"plantilla": "teclado"}, format="json")
        assert guardar(base, []).json() == []  # nadie los usa: se eliminan del todo
        r = api.post(categoria_url(base, "plantilla/"), {"plantilla": "mouse"}, format="json")
        activos = [c for c in r.json() if c["estado"] == "ACTIVO"]
        assert len(activos) == len(especificaciones.PLANTILLAS["mouse"]["campos"])

    def test_los_quitados_que_aun_tienen_datos_se_reactivan_con_la_definicion_de_la_plantilla(
        self, base
    ):
        api = base["api"]
        api.post(categoria_url(base, "plantilla/"), {"plantilla": "teclado"}, format="json")
        crear(base, especificaciones={"conexion": "Bluetooth"})  # el producto usa «Conexión»
        guardar(base, [])  # se quita todo; «Conexión» queda inactivo porque tiene datos
        inactivos = [c for c in api.get(categoria_url(base)).json() if c["estado"] == "INACTIVO"]
        assert [c["clave"] for c in inactivos] == ["conexion"]
        r = api.post(categoria_url(base, "plantilla/"), {"plantilla": "mouse"}, format="json")
        por_clave = {c["clave"]: c for c in r.json()}
        assert por_clave["conexion"]["estado"] == "ACTIVO"
        assert "Inalámbrico 2.4 GHz" in por_clave["conexion"]["opciones"]
        assert len(por_clave) == len(especificaciones.PLANTILLAS["mouse"]["campos"])

    def test_cargar_encima_de_un_campo_activo_no_pisa_lo_que_el_usuario_ajusto(self, base):
        api = base["api"]
        guardar(base, [campo("Botones", "NUMERO", unidad="uds", es_filtro=False)])
        r = api.post(categoria_url(base, "plantilla/"), {"plantilla": "mouse"}, format="json")
        botones = next(c for c in r.json() if c["nombre"] == "Botones")
        assert (botones["unidad"], botones["es_filtro"]) == ("uds", False)


class TestEditarLaPlantilla:
    def test_guarda_en_orden_con_claves_estables(self, base):
        claves = con_campos(base)
        assert list(claves.values()) == ["memoria-ram", "tipo", "tactil", "modelo"]
        lista = base["api"].get(categoria_url(base)).json()
        assert [c["orden"] for c in lista] == [1, 2, 3, 4]
        assert lista[3]["seccion"] == "Datos" and lista[0]["seccion"] == "General"

    def test_renombrar_no_cambia_la_clave_y_lo_quitado_con_datos_queda_inactivo(self, base):
        claves = con_campos(base)
        crear(base, especificaciones={claves["Modelo"]: "X1"})  # un producto usa «Modelo»
        actual = base["api"].get(categoria_url(base)).json()
        enviado = [
            {**c, "nombre": "RAM instalada"} if c["clave"] == "memoria-ram" else c
            for c in actual
            if c["clave"] != "modelo"
        ]
        r = guardar(base, enviado)
        assert r.status_code == 200, r.content
        por_clave = {c["clave"]: c for c in r.json()}
        assert por_clave["memoria-ram"]["nombre"] == "RAM instalada"
        assert por_clave["modelo"]["estado"] == "INACTIVO"

    def test_lo_quitado_que_ningun_producto_usa_se_elimina_del_todo(self, base):
        con_campos(base)
        actual = base["api"].get(categoria_url(base)).json()
        r = guardar(base, [c for c in actual if c["clave"] != "modelo"])
        assert "modelo" not in {c["clave"] for c in r.json()}
        # y la clave queda libre para un campo nuevo con ese nombre
        r = guardar(base, [*r.json(), campo("Modelo")])
        assert [c["clave"] for c in r.json() if c["nombre"] == "Modelo"] == ["modelo"]

    def test_un_campo_nuevo_con_nombre_repetido_recibe_clave_distinta(self, base):
        claves = con_campos(base)
        crear(base, especificaciones={claves["Modelo"]: "X1"})
        actual = base["api"].get(categoria_url(base)).json()
        quitado = [c for c in actual if c["clave"] != "modelo"]
        r = guardar(base, [*quitado, campo("Modelo")])
        claves = [c["clave"] for c in r.json() if c["nombre"] == "Modelo"]
        assert sorted(claves) == ["modelo", "modelo-2"]

    def test_valida_nombres_repetidos_tipos_y_opciones(self, base):
        assert guardar(base, [campo("A"), campo("a")]).status_code == 400
        assert guardar(base, [campo("")]).status_code == 400
        assert guardar(base, [campo("A", "FOTO")]).status_code == 400
        sobran = [f"op{i}" for i in range(41)]
        assert guardar(base, [campo("A", "LISTA", opciones=sobran)]).status_code == 400

    def test_el_texto_nunca_es_filtro_y_la_unidad_solo_va_en_numeros(self, base):
        r = guardar(
            base,
            [
                campo("Modelo", "TEXTO", es_filtro=True, unidad="GB"),
                campo("Peso", "NUMERO", unidad="kg"),
            ],
        )
        modelo, peso = r.json()
        assert (modelo["es_filtro"], modelo["unidad"]) == (False, "")
        assert peso["unidad"] == "kg"

    def test_un_campo_de_otra_categoria_se_rechaza(self, base):
        api = base["api"]
        otra = api.post(
            f"{BASE}/categorias/",
            {"familia": base["familia"]["id"], "nombre": "Mouse"},
            format="json",
        ).json()
        ajeno = api.post(
            f"{BASE}/categorias/{otra['id']}/especificaciones/",
            {"campos": [campo("DPI", "NUMERO")]},
            format="json",
        ).json()[0]
        r = guardar(base, [{"id": ajeno["id"], "nombre": "DPI", "tipo": "NUMERO"}])
        assert r.status_code == 400

    def test_el_vendedor_no_edita_y_otra_organizacion_no_la_ve(self, base):
        con_campos(base)
        assert guardar(base, [campo("X")], usuario="vendedor").status_code == 403
        r = cliente_de("otra_org").get(categoria_url(base))
        assert r.status_code in (403, 404)


class TestValoresDelProducto:
    def test_guarda_y_normaliza_cada_tipo(self, base):
        claves = con_campos(base)
        p = crear(
            base,
            especificaciones={
                claves["Memoria RAM"]: "16,0",
                claves["Tipo"]: "ddr5",
                claves["Táctil"]: "sí",
                claves["Modelo"]: "  IdeaPad   Slim 3 ",
            },
        )
        assert p["especificaciones"] == {
            "memoria-ram": "16",
            "tipo": "DDR5",
            "tactil": True,
            "modelo": "IdeaPad Slim 3",
        }

    def test_un_valor_vacio_se_omite(self, base):
        claves = con_campos(base)
        p = crear(base, especificaciones={claves["Modelo"]: "  ", claves["Táctil"]: None})
        assert p["especificaciones"] == {}

    @pytest.mark.parametrize(
        ("campo_", "valor", "mensaje"),
        [
            ("Memoria RAM", "mucha", "número"),
            ("Memoria RAM", "-4", "no es válido"),
            ("Memoria RAM", "1.2345", "3 decimales"),
            ("Tipo", "DDR9", "opciones"),
            ("Táctil", "quizás", "Sí o No"),
        ],
    )
    def test_rechaza_lo_que_no_calza_con_el_tipo(self, base, campo_, valor, mensaje):
        claves = con_campos(base)
        r = base["api"].post(
            f"{BASE}/productos/",
            {
                "nombre": "X",
                "categoria": base["categoria"]["id"],
                "unidad": base["unidad"]["id"],
                "especificaciones": {claves[campo_]: valor},
            },
            format="json",
        )
        assert r.status_code == 400, r.content
        assert mensaje in r.content.decode()

    def test_un_dato_que_no_existe_en_la_categoria_se_rechaza(self, base):
        con_campos(base)
        r = base["api"].post(
            f"{BASE}/productos/",
            {
                "nombre": "X",
                "categoria": base["categoria"]["id"],
                "unidad": base["unidad"]["id"],
                "especificaciones": {"inventado": "1"},
            },
            format="json",
        )
        assert r.status_code == 400

    def test_se_edita_y_un_campo_desactivado_ya_no_se_acepta(self, base):
        claves = con_campos(base)
        p = crear(base, especificaciones={claves["Modelo"]: "A"})
        actual = base["api"].get(categoria_url(base)).json()
        guardar(base, [c for c in actual if c["clave"] != "modelo"])
        r = base["api"].patch(
            f"{BASE}/productos/{p['id']}/", {"especificaciones": {"modelo": "B"}}, format="json"
        )
        assert r.status_code == 400
        r = base["api"].patch(
            f"{BASE}/productos/{p['id']}/",
            {"especificaciones": {claves["Memoria RAM"]: "8"}},
            format="json",
        )
        assert r.status_code == 200 and r.json()["especificaciones"] == {"memoria-ram": "8"}

    def test_al_cambiar_de_categoria_se_conservan_solo_los_datos_que_la_nueva_tambien_pide(
        self, base
    ):
        claves = con_campos(base)
        api = base["api"]
        p = crear(
            base,
            especificaciones={claves["Memoria RAM"]: "8", claves["Modelo"]: "X"},
        )
        otra = api.post(
            f"{BASE}/categorias/",
            {"familia": base["familia"]["id"], "nombre": "Mouse"},
            format="json",
        ).json()
        api.post(
            f"{BASE}/categorias/{otra['id']}/especificaciones/",
            {"campos": [campo("Memoria RAM", "NUMERO", unidad="GB")]},
            format="json",
        )
        r = api.patch(f"{BASE}/productos/{p['id']}/", {"categoria": otra["id"]}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["especificaciones"] == {"memoria-ram": "8"}


class TestParaLaTienda:
    def test_sin_foto_no_se_publica_y_con_foto_si_con_direccion_web_automatica(self, base):
        p = crear(base, nombre="Laptop Lenovo IdeaPad 15.3")
        api = base["api"]
        r = api.patch(f"{BASE}/productos/{p['id']}/", {"publicado_web": True}, format="json")
        assert r.status_code == 400 and "foto" in r.content.decode()
        subir_foto(base, p["id"])
        r = api.patch(f"{BASE}/productos/{p['id']}/", {"publicado_web": True}, format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["publicado_web"], r.json()["slug"]) == (True, "laptop-lenovo-ideapad-153")

    def test_no_se_puede_crear_ya_publicado_porque_aun_no_tiene_fotos(self, base):
        r = base["api"].post(
            f"{BASE}/productos/",
            {
                "nombre": "X",
                "categoria": base["categoria"]["id"],
                "unidad": base["unidad"]["id"],
                "publicado_web": True,
            },
            format="json",
        )
        assert r.status_code == 400

    def test_las_direcciones_web_son_unicas_y_validas(self, base):
        a, b = crear(base, nombre="Uno"), crear(base, nombre="Dos")
        api = base["api"]
        assert (
            api.patch(
                f"{BASE}/productos/{a['id']}/", {"slug": "mi-laptop"}, format="json"
            ).status_code
            == 200
        )
        r = api.patch(f"{BASE}/productos/{b['id']}/", {"slug": "mi-laptop"}, format="json")
        assert r.status_code == 400 and "dirección web" in r.content.decode()
        for malo in ("Mi Laptop", "mi_laptop", "-x", "x--y"):
            assert (
                api.patch(f"{BASE}/productos/{b['id']}/", {"slug": malo}, format="json").status_code
                == 400
            )

    def test_dos_productos_con_el_mismo_nombre_reciben_direcciones_distintas(self, base):
        api = base["api"]
        ids = []
        for _ in range(2):
            p = crear(base, nombre="Mouse Gamer")
            subir_foto(base, p["id"])
            r = api.patch(f"{BASE}/productos/{p['id']}/", {"publicado_web": True}, format="json")
            ids.append(r.json()["slug"])
        assert ids == ["mouse-gamer", "mouse-gamer-2"]

    def test_un_producto_inactivo_no_se_publica(self, base):
        p = crear(base)
        subir_foto(base, p["id"])
        r = base["api"].patch(
            f"{BASE}/productos/{p['id']}/",
            {"publicado_web": True, "estado": "INACTIVO"},
            format="json",
        )
        assert r.status_code == 400

    def test_guarda_los_demas_datos_de_la_tienda(self, base):
        p = crear(
            base,
            descripcion_web="Laptop ideal para estudiar.",
            puntos_destacados=["Pantalla IPS", "  SSD NVMe  ", ""],
            garantia_meses=12,
            peso_kg="1.590",
            largo_cm="34.34",
            ancho_cm="23.95",
            alto_cm="1.79",
            destacado=True,
            es_nuevo=True,
        )
        assert p["puntos_destacados"] == ["Pantalla IPS", "SSD NVMe"]
        assert (p["garantia_meses"], p["peso_kg"], p["alto_cm"]) == (12, "1.590", "1.79")
        assert (p["destacado"], p["es_nuevo"], p["publicado_web"]) == (True, True, False)

    def test_valida_puntos_destacados_garantia_y_medidas(self, base):
        api = base["api"]
        datos = {
            "nombre": "X",
            "categoria": base["categoria"]["id"],
            "unidad": base["unidad"]["id"],
        }
        assert (
            api.post(
                f"{BASE}/productos/", {**datos, "puntos_destacados": ["a"] * 9}, format="json"
            ).status_code
            == 400
        )
        assert (
            api.post(
                f"{BASE}/productos/", {**datos, "garantia_meses": 999}, format="json"
            ).status_code
            == 400
        )
        assert (
            api.post(f"{BASE}/productos/", {**datos, "peso_kg": "-1"}, format="json").status_code
            == 400
        )

    def test_el_listado_filtra_por_publicado(self, base):
        p = crear(base, nombre="Publicado")
        crear(base, nombre="Borrador")
        subir_foto(base, p["id"])
        base["api"].patch(f"{BASE}/productos/{p['id']}/", {"publicado_web": True}, format="json")
        api = base["api"]
        en_tienda = api.get(f"{BASE}/productos/", {"publicado": "1"}).json()["results"]
        assert [x["nombre"] for x in en_tienda] == ["Publicado"]
        fuera = api.get(f"{BASE}/productos/", {"publicado": "0"}).json()["results"]
        assert [x["nombre"] for x in fuera] == ["Borrador"]


class TestOrdenDeFotos:
    def test_la_primera_de_la_lista_queda_como_principal(self, base):
        p = crear(base)
        a, b, c = (subir_foto(base, p["id"])["id"] for _ in range(3))
        api = base["api"]
        r = api.post(f"{BASE}/productos/{p['id']}/fotos/orden/", {"ids": [c, a, b]}, format="json")
        assert r.status_code == 200, r.content
        assert [f["id"] for f in r.json()] == [c, a, b]
        assert [f["es_principal"] for f in r.json()] == [True, False, False]
        lista = api.get(f"{BASE}/productos/{p['id']}/fotos/").json()
        assert [f["id"] for f in lista] == [c, a, b]

    def test_exige_todas_las_fotos_una_sola_vez(self, base):
        p = crear(base)
        a, b = (subir_foto(base, p["id"])["id"] for _ in range(2))
        api = base["api"]
        for ids in ([a], [a, a], [a, b, 9999]):
            r = api.post(f"{BASE}/productos/{p['id']}/fotos/orden/", {"ids": ids}, format="json")
            assert r.status_code == 400, ids

    def test_el_vendedor_no_ordena(self, base):
        p = crear(base)
        a = subir_foto(base, p["id"])["id"]
        r = cliente_de("vendedor").post(
            f"{BASE}/productos/{p['id']}/fotos/orden/", {"ids": [a]}, format="json"
        )
        assert r.status_code == 403
