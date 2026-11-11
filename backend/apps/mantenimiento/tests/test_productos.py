"""Productos, unidades de medida, listas de precios y fotos."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.auditoria import servicios
from apps.mantenimiento import fotos as servicio_fotos
from apps.mantenimiento.models import FotoProducto, Producto
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture(autouse=True)
def _media_temporal(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "almacenero": nuevo_usuario(e.org_a, "almacenero", [e.emp_a1], [("ALMACENERO", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


@pytest.fixture
def base(equipo):
    """Catálogos listos: categoría, unidad y las cuatro listas de precios."""
    api = cliente_de("super")
    familia = api.post(f"{BASE}/familias/", {"nombre": "Repuestos"}, format="json").json()
    categoria = api.post(
        f"{BASE}/categorias/", {"familia": familia["id"], "nombre": "Teclado"}, format="json"
    ).json()
    api.post(f"{BASE}/unidades/sembrar/")
    api.post(f"{BASE}/listas-precio/sembrar/")
    unidad = api.get(f"{BASE}/unidades/", {"q": "Unidad"}).json()["results"][0]
    listas = api.get(f"{BASE}/listas-precio/").json()["results"]
    return {
        "api": api,
        "familia": familia,
        "categoria": categoria,
        "unidad": unidad,
        "listas": listas,
    }


def datos_producto(base, **extra):
    return {
        "nombre": "Teclado Logitech K120",
        "categoria": base["categoria"]["id"],
        "unidad": base["unidad"]["id"],
        **extra,
    }


def crear(base, **extra):
    r = base["api"].post(f"{BASE}/productos/", datos_producto(base, **extra), format="json")
    assert r.status_code == 201, r.content
    return r.json()


def png(ancho=20, alto=10, formato="PNG") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (ancho, alto), (200, 30, 30)).save(buffer, format=formato)
    tipo = {"PNG": "image/png", "JPEG": "image/jpeg"}[formato]
    return SimpleUploadedFile("foto.png", buffer.getvalue(), content_type=tipo)


# ---------------------------------------------------------------------------
# Unidades y listas de precios
# ---------------------------------------------------------------------------
class TestCatalogosIniciales:
    def test_sembrar_unidades_es_repetible_y_no_duplica(self, equipo):
        api = cliente_de("super")
        assert api.post(f"{BASE}/unidades/sembrar/").json()["creadas"] == 10
        assert api.post(f"{BASE}/unidades/sembrar/").json()["creadas"] == 0
        assert api.get(f"{BASE}/unidades/").json()["count"] == 10

    def test_sembrar_listas_deja_publico_como_principal(self, equipo):
        api = cliente_de("super")
        assert api.post(f"{BASE}/listas-precio/sembrar/").json()["creadas"] == 4
        listas = api.get(f"{BASE}/listas-precio/").json()["results"]
        assert [lista["nombre"] for lista in listas] == [
            "Público",
            "Descuento",
            "Técnico",
            "Crédito",
        ]
        assert [lista["es_principal"] for lista in listas] == [True, False, False, False]

    def test_los_nombres_de_las_listas_se_pueden_cambiar(self, base):
        api = base["api"]
        r = api.patch(
            f"{BASE}/listas-precio/{base['listas'][1]['id']}/",
            {"nombre": "Mayorista"},
            format="json",
        )
        assert r.status_code == 200 and r.json()["nombre"] == "Mayorista"

    def test_la_lista_principal_no_se_elimina_ni_se_desactiva(self, base):
        api, principal = base["api"], base["listas"][0]
        assert api.delete(f"{BASE}/listas-precio/{principal['id']}/").status_code == 409
        r = api.patch(
            f"{BASE}/listas-precio/{principal['id']}/", {"estado": "INACTIVO"}, format="json"
        )
        assert r.status_code == 400

    def test_la_primera_lista_creada_es_la_principal(self, equipo):
        api = cliente_de("super")
        r = api.post(f"{BASE}/listas-precio/", {"nombre": "Normal"}, format="json")
        assert r.json()["es_principal"] is True
        assert (
            api.post(f"{BASE}/listas-precio/", {"nombre": "Oferta"}, format="json").json()[
                "es_principal"
            ]
            is False
        )

    def test_unidad_duplicada_se_rechaza(self, equipo):
        api = cliente_de("super")
        api.post(f"{BASE}/unidades/", {"nombre": "Caja", "abreviatura": "cj"}, format="json")
        r = api.post(f"{BASE}/unidades/", {"nombre": "Cajita", "abreviatura": "CJ"}, format="json")
        assert r.status_code == 400 and "abreviatura" in r.json()["error"]["detalle"]

    def test_unidad_en_uso_no_se_elimina(self, base):
        crear(base)
        r = base["api"].delete(f"{BASE}/unidades/{base['unidad']['id']}/")
        assert r.status_code == 409

    def test_categoria_y_marca_en_uso_no_se_eliminan(self, base):
        api = base["api"]
        marca = api.post(f"{BASE}/marcas/", {"nombre": "Logitech"}, format="json").json()
        crear(base, marca=marca["id"])
        assert api.delete(f"{BASE}/marcas/{marca['id']}/").status_code == 409
        assert api.delete(f"{BASE}/categorias/{base['categoria']['id']}/").status_code == 409

    def test_lista_con_precios_no_se_elimina(self, base):
        crear(base, costo="10", precios=[{"lista": base["listas"][1]["id"], "precio": "15"}])
        assert (
            base["api"].delete(f"{BASE}/listas-precio/{base['listas'][1]['id']}/").status_code
            == 409
        )


# ---------------------------------------------------------------------------
# Productos
# ---------------------------------------------------------------------------
class TestProductos:
    def test_el_codigo_se_genera_solo_y_es_correlativo(self, base):
        assert crear(base)["codigo"] == "000001"
        assert crear(base, nombre="Mouse")["codigo"] == "000002"

    def test_precio_con_utilidad_y_utilidad_con_precio(self, base):
        publico, descuento = base["listas"][0]["id"], base["listas"][1]["id"]
        producto = crear(
            base,
            costo="100",
            precios=[{"lista": publico, "utilidad": "30"}, {"lista": descuento, "precio": "120"}],
        )
        por_lista = {p["lista"]: p for p in producto["precios"]}
        assert Decimal(por_lista[publico]["precio"]) == Decimal("130")
        assert Decimal(por_lista[descuento]["utilidad"]) == Decimal("20.00")

    def test_utilidad_sin_costo_se_rechaza(self, base):
        r = base["api"].post(
            f"{BASE}/productos/",
            datos_producto(base, precios=[{"lista": base["listas"][0]["id"], "utilidad": "30"}]),
            format="json",
        )
        assert r.status_code == 400

    def test_al_cambiar_el_costo_la_utilidad_se_recalcula_y_el_precio_no_se_mueve(self, base):
        publico = base["listas"][0]["id"]
        producto = crear(base, costo="100", precios=[{"lista": publico, "precio": "150"}])
        r = base["api"].patch(
            f"{BASE}/productos/{producto['id']}/", {"costo": "120"}, format="json"
        )
        precio = r.json()["precios"][0]
        assert Decimal(precio["precio"]) == Decimal("150")
        assert Decimal(precio["utilidad"]) == Decimal("25.00")

    def test_editar_precios_reemplaza_y_quita_las_listas_omitidas(self, base):
        publico, tecnico = base["listas"][0]["id"], base["listas"][2]["id"]
        producto = crear(
            base,
            costo="10",
            precios=[{"lista": publico, "precio": "15"}, {"lista": tecnico, "precio": "13"}],
        )
        r = base["api"].patch(
            f"{BASE}/productos/{producto['id']}/",
            {"precios": [{"lista": publico, "precio": "16"}]},
            format="json",
        )
        assert [(p["lista"], Decimal(p["precio"])) for p in r.json()["precios"]] == [
            (publico, Decimal("16"))
        ]

    def test_precios_de_una_lista_desactivada_se_conservan_al_editar(self, base):
        publico, credito = base["listas"][0]["id"], base["listas"][3]["id"]
        producto = crear(
            base,
            costo="10",
            precios=[{"lista": publico, "precio": "15"}, {"lista": credito, "precio": "17"}],
        )
        base["api"].patch(f"{BASE}/listas-precio/{credito}/", {"estado": "INACTIVO"}, format="json")
        # La pantalla ya no muestra «Crédito» y solo envía las listas activas.
        r = base["api"].patch(
            f"{BASE}/productos/{producto['id']}/",
            {"precios": [{"lista": publico, "precio": "16"}]},
            format="json",
        )
        por_lista = {p["lista"]: Decimal(p["precio"]) for p in r.json()["precios"]}
        assert por_lista == {publico: Decimal("16"), credito: Decimal("17")}

    def test_lista_repetida_o_inexistente_se_rechaza(self, base):
        publico = base["listas"][0]["id"]
        for precios in (
            [{"lista": publico, "precio": "1"}, {"lista": publico, "precio": "2"}],
            [{"lista": 999999, "precio": "1"}],
        ):
            r = base["api"].post(
                f"{BASE}/productos/", datos_producto(base, precios=precios), format="json"
            )
            assert r.status_code == 400

    def test_codigo_de_barras_duplicado_se_rechaza(self, base):
        crear(base, codigo_barras="7750000000017")
        r = base["api"].post(
            f"{BASE}/productos/",
            datos_producto(base, nombre="Otro", codigo_barras="7750000000017"),
            format="json",
        )
        assert r.status_code == 400 and "codigo_barras" in r.json()["error"]["detalle"]

    def test_sin_codigo_de_barras_se_usa_el_interno_en_la_etiqueta(self, base):
        producto = crear(base)
        assert producto["codigo_barras"] == ""
        assert producto["codigo_barras_efectivo"] == producto["codigo"]

    def test_un_servicio_no_controla_stock_ni_serie(self, base):
        producto = crear(
            base, tipo="SERVICIO", controla_stock=True, lleva_serie=True, stock_minimo="5"
        )
        assert producto["controla_stock"] is False
        assert producto["lleva_serie"] is False
        assert Decimal(producto["stock_minimo"]) == 0

    def test_categoria_inactiva_no_se_puede_elegir(self, base):
        base["api"].patch(
            f"{BASE}/categorias/{base['categoria']['id']}/", {"estado": "INACTIVO"}, format="json"
        )
        r = base["api"].post(f"{BASE}/productos/", datos_producto(base), format="json")
        assert r.status_code == 400 and "categoria" in r.json()["error"]["detalle"]

    def test_filtros_y_busqueda(self, base):
        crear(base, nombre="Teclado Logitech", codigo_barras="1111")
        crear(base, nombre="Mouse Genius", tipo="SERVICIO")
        api = base["api"]
        assert api.get(f"{BASE}/productos/", {"q": "logitech"}).json()["count"] == 1
        assert api.get(f"{BASE}/productos/", {"q": "1111"}).json()["count"] == 1
        assert api.get(f"{BASE}/productos/", {"tipo": "SERVICIO"}).json()["count"] == 1
        assert (
            api.get(f"{BASE}/productos/", {"familia": base["familia"]["id"]}).json()["count"] == 2
        )
        assert api.get(f"{BASE}/productos/", {"categoria": "abc"}).status_code == 400

    def test_eliminar_es_logico_y_libera_el_codigo_de_barras(self, base):
        producto = crear(base, codigo_barras="2222")
        assert base["api"].delete(f"{BASE}/productos/{producto['id']}/").status_code == 204
        assert base["api"].get(f"{BASE}/productos/{producto['id']}/").status_code == 404
        crear(base, nombre="Nuevo", codigo_barras="2222")  # ya se puede reutilizar

    def test_la_auditoria_registra_el_cambio_de_precio(self, base):
        from apps.auditoria.models import AuditoriaEvento

        publico = base["listas"][0]["id"]
        producto = crear(base, costo="10", precios=[{"lista": publico, "precio": "15"}])
        base["api"].patch(
            f"{BASE}/productos/{producto['id']}/",
            {"precios": [{"lista": publico, "precio": "18"}]},
            format="json",
        )
        evento = AuditoriaEvento.objects.filter(accion="producto.editado").latest("id")
        assert evento.detalle["precios"]["Público"] == ["15.0000", "18.0000"]


class TestPermisosDePrecio:
    def test_sin_permiso_no_ve_el_costo_ni_la_utilidad(self, base):
        publico = base["listas"][0]["id"]
        producto = crear(base, costo="100", precios=[{"lista": publico, "precio": "130"}])
        r = cliente_de("almacenero").get(f"{BASE}/productos/{producto['id']}/")
        assert r.status_code == 200
        datos = r.json()
        assert "costo" not in datos
        assert Decimal(datos["precios"][0]["precio"]) == Decimal("130")
        assert "utilidad" not in datos["precios"][0]

    def test_con_permiso_ve_costo_y_utilidad(self, base):
        publico = base["listas"][0]["id"]
        producto = crear(base, costo="100", precios=[{"lista": publico, "precio": "130"}])
        datos = base["api"].get(f"{BASE}/productos/{producto['id']}/").json()
        assert Decimal(datos["costo"]) == 100
        assert Decimal(datos["precios"][0]["utilidad"]) == Decimal("30.00")

    def test_sin_permiso_no_puede_poner_costo_ni_precios(self, base):
        almacenero = cliente_de("almacenero")
        r = almacenero.post(f"{BASE}/productos/", datos_producto(base, costo="50"), format="json")
        assert r.status_code == 403
        r = almacenero.post(
            f"{BASE}/productos/",
            datos_producto(base, precios=[{"lista": base["listas"][0]["id"], "precio": "5"}]),
            format="json",
        )
        assert r.status_code == 403
        assert Producto.objects.sin_ambito().count() == 0

    def test_sin_permiso_si_puede_crear_y_editar_los_datos_generales(self, base):
        almacenero = cliente_de("almacenero")
        r = almacenero.post(f"{BASE}/productos/", datos_producto(base), format="json")
        assert r.status_code == 201
        r = almacenero.patch(
            f"{BASE}/productos/{r.json()['id']}/", {"nombre": "Teclado K"}, format="json"
        )
        assert r.status_code == 200 and r.json()["nombre"] == "Teclado K"

    def test_vendedor_solo_ve_no_crea_ni_edita(self, base):
        producto = crear(base)
        vendedor = cliente_de("vendedor")
        assert vendedor.get(f"{BASE}/productos/").status_code == 200
        assert (
            vendedor.post(f"{BASE}/productos/", datos_producto(base), format="json").status_code
            == 403
        )
        r = vendedor.patch(f"{BASE}/productos/{producto['id']}/", {"nombre": "X"}, format="json")
        assert r.status_code == 403

    def test_otra_organizacion_no_ve_ni_toca_los_productos(self, base):
        producto = crear(base)
        ajeno = cliente_de("otra_org")
        assert ajeno.get(f"{BASE}/productos/").json()["count"] == 0
        assert ajeno.get(f"{BASE}/productos/{producto['id']}/").status_code == 404
        r = ajeno.post(f"{BASE}/productos/", datos_producto(base), format="json")
        assert r.status_code == 400  # su organización no tiene esa categoría ni unidad


# ---------------------------------------------------------------------------
# Fotos
# ---------------------------------------------------------------------------
def subir(api, producto, archivo):
    return api.post(
        f"{BASE}/productos/{producto['id']}/fotos/", {"imagen": archivo}, format="multipart"
    )


class TestFotos:
    def test_la_primera_foto_es_la_principal_y_aparece_en_el_listado(self, base):
        producto = crear(base)
        r = subir(base["api"], producto, png())
        assert r.status_code == 201 and r.json()["es_principal"] is True
        segunda = subir(base["api"], producto, png()).json()
        assert segunda["es_principal"] is False
        listado = base["api"].get(f"{BASE}/productos/").json()["results"][0]
        assert listado["foto_principal"] == r.json()["id"]

    def test_la_imagen_se_recodifica_a_webp_y_se_sirve_con_sesion(self, base):
        producto = crear(base)
        foto = subir(base["api"], producto, png(3000, 2000, "JPEG")).json()
        url = f"{BASE}/productos/{producto['id']}/fotos/{foto['id']}/imagen/"
        grande = base["api"].get(url)
        assert grande.status_code == 200 and grande["Content-Type"] == "image/webp"
        imagen = Image.open(io.BytesIO(b"".join(grande.streaming_content)))
        assert imagen.format == "WEBP" and max(imagen.size) <= 1600
        mini = base["api"].get(url, {"tam": "mini"})
        assert max(Image.open(io.BytesIO(b"".join(mini.streaming_content))).size) <= 400

    def test_sin_sesion_no_se_puede_ver_la_foto(self, base):
        from rest_framework.test import APIClient

        producto = crear(base)
        foto = subir(base["api"], producto, png()).json()
        r = APIClient().get(f"{BASE}/productos/{producto['id']}/fotos/{foto['id']}/imagen/")
        assert r.status_code in (401, 403)

    def test_otra_organizacion_no_puede_ver_la_foto(self, base):
        producto = crear(base)
        foto = subir(base["api"], producto, png()).json()
        r = cliente_de("otra_org").get(
            f"{BASE}/productos/{producto['id']}/fotos/{foto['id']}/imagen/"
        )
        assert r.status_code == 404

    def test_un_archivo_que_no_es_imagen_se_rechaza(self, base):
        producto = crear(base)
        falso = SimpleUploadedFile(
            "foto.png", b"<html><script>alert(1)</script></html>", "image/png"
        )
        r = subir(base["api"], producto, falso)
        assert r.status_code == 400
        assert FotoProducto.objects.sin_ambito().count() == 0

    def test_un_svg_o_gif_se_rechaza(self, base):
        producto = crear(base)
        svg = SimpleUploadedFile(
            "a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"
        )
        assert subir(base["api"], producto, svg).status_code == 400
        buffer = io.BytesIO()
        Image.new("RGB", (5, 5)).save(buffer, format="GIF")
        gif = SimpleUploadedFile("a.gif", buffer.getvalue(), "image/gif")
        assert subir(base["api"], producto, gif).status_code == 400

    def test_una_foto_muy_pesada_se_rechaza(self, base, monkeypatch):
        monkeypatch.setattr(servicio_fotos, "TAMANO_MAXIMO", 100)
        r = subir(base["api"], crear(base), png(200, 200))
        assert r.status_code == 400

    def test_una_foto_truncada_se_rechaza(self, base):
        archivo = png(200, 200)
        truncado = SimpleUploadedFile("a.png", archivo.read()[:60], "image/png")
        assert subir(base["api"], crear(base), truncado).status_code == 400

    def test_maximo_de_fotos_por_producto(self, base, monkeypatch):
        monkeypatch.setattr(servicio_fotos, "MAX_FOTOS", 2)
        producto = crear(base)
        assert subir(base["api"], producto, png()).status_code == 201
        assert subir(base["api"], producto, png()).status_code == 201
        assert subir(base["api"], producto, png()).status_code == 400

    def test_sin_archivo_se_rechaza(self, base):
        r = base["api"].post(f"{BASE}/productos/{crear(base)['id']}/fotos/", {}, format="multipart")
        assert r.status_code == 400

    def test_cambiar_la_principal(self, base):
        producto = crear(base)
        primera = subir(base["api"], producto, png()).json()
        segunda = subir(base["api"], producto, png()).json()
        r = base["api"].post(f"{BASE}/productos/{producto['id']}/fotos/{segunda['id']}/principal/")
        assert r.status_code == 200
        fotos = base["api"].get(f"{BASE}/productos/{producto['id']}/fotos/").json()
        assert [(f["id"], f["es_principal"]) for f in fotos] == [
            (segunda["id"], True),
            (primera["id"], False),
        ]

    def test_al_borrar_la_principal_la_siguiente_pasa_a_serlo_y_el_archivo_se_borra(self, base):
        producto = crear(base)
        primera = subir(base["api"], producto, png()).json()
        segunda = subir(base["api"], producto, png()).json()
        ruta = FotoProducto.objects.sin_ambito().get(pk=primera["id"]).imagen.path
        r = base["api"].delete(f"{BASE}/productos/{producto['id']}/fotos/{primera['id']}/")
        assert r.status_code == 204
        import os

        assert not os.path.exists(ruta)
        fotos = base["api"].get(f"{BASE}/productos/{producto['id']}/fotos/").json()
        assert [(f["id"], f["es_principal"]) for f in fotos] == [(segunda["id"], True)]
        listado = base["api"].get(f"{BASE}/productos/").json()["results"][0]
        assert listado["foto_principal"] == segunda["id"]

    def test_sin_permiso_de_editar_no_sube_fotos(self, base):
        producto = crear(base)
        assert subir(cliente_de("vendedor"), producto, png()).status_code == 403

    def test_los_metadatos_exif_no_sobreviven(self, base):
        buffer = io.BytesIO()
        imagen = Image.new("RGB", (30, 30), (10, 10, 10))
        exif = Image.Exif()
        exif[0x010E] = "SECRETO-GPS"
        imagen.save(buffer, format="JPEG", exif=exif)
        archivo = SimpleUploadedFile("a.jpg", buffer.getvalue(), "image/jpeg")
        grande, _ = servicio_fotos.procesar(archivo)
        assert b"SECRETO-GPS" not in grande


class TestMargen:
    """Margen (sobre el precio) y utilidad (sobre el costo): dos formas de decir el mismo precio."""

    def test_precio_con_margen(self, base):
        publico = base["listas"][0]["id"]
        # Compra a 90 y quiere ganar 25 % del precio de venta: 90 ÷ 0,75 = 120.
        producto = crear(base, costo="90", precios=[{"lista": publico, "margen": "25"}])
        fila = producto["precios"][0]
        assert Decimal(fila["precio"]) == Decimal("120")
        assert Decimal(fila["margen"]) == Decimal("25.00")
        assert Decimal(fila["utilidad"]) == Decimal("33.33")

    def test_el_margen_siempre_sale_derivado_del_precio(self, base):
        publico = base["listas"][0]["id"]
        producto = crear(base, costo="100", precios=[{"lista": publico, "utilidad": "100"}])
        assert Decimal(producto["precios"][0]["margen"]) == Decimal("50.00")

    def test_utilidad_y_margen_a_la_vez_se_rechazan(self, base):
        r = base["api"].post(
            f"{BASE}/productos/",
            datos_producto(
                base,
                costo="100",
                precios=[{"lista": base["listas"][0]["id"], "utilidad": "30", "margen": "20"}],
            ),
            format="json",
        )
        assert r.status_code == 400

    def test_margen_sin_costo_o_de_100_se_rechaza(self, base):
        lista = base["listas"][0]["id"]
        sin_costo = datos_producto(base, precios=[{"lista": lista, "margen": "20"}])
        cien = datos_producto(base, costo="50", precios=[{"lista": lista, "margen": "100"}])
        for datos in (sin_costo, cien):
            r = base["api"].post(f"{BASE}/productos/", datos, format="json")
            assert r.status_code == 400

    def test_al_cambiar_el_costo_el_margen_se_ajusta(self, base):
        publico = base["listas"][0]["id"]
        producto = crear(base, costo="100", precios=[{"lista": publico, "precio": "125"}])
        r = base["api"].patch(
            f"{BASE}/productos/{producto['id']}/", {"costo": "100.00"}, format="json"
        )
        assert Decimal(r.json()["precios"][0]["margen"]) == Decimal("20.00")
