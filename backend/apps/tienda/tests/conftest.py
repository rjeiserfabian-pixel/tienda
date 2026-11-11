"""Escenario de la tienda: una organización con tienda abierta y productos de ejemplo."""

import io
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.compras.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    api,
    compras,
    entorno,
    mundo,
    nuevo_usuario,
    rbac,
)
from apps.core.tenant import establecer_contexto
from apps.inventario.tests.conftest import comprar as comprar_stock
from apps.mantenimiento import fotos as servicio_fotos
from apps.mantenimiento.especificaciones import generar_slug
from apps.mantenimiento.models import (
    CampoEspecificacion,
    Categoria,
    Familia,
    ListaPrecio,
    Marca,
    PrecioProducto,
    Producto,
)
from apps.mantenimiento.productos import sembrar_listas
from apps.tienda.models import ConfiguracionTienda


def png() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buffer, format="PNG")
    return SimpleUploadedFile("foto.png", buffer.getvalue(), content_type="image/png")


@pytest.fixture(autouse=True)
def _cache_limpia():
    """La tienda guarda respuestas en caché: cada prueba empieza de cero."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tienda(nuevo_usuario, compras, settings, tmp_path):  # noqa: F811
    settings.MEDIA_ROOT = str(tmp_path)
    e = compras.entorno
    org = e.e.org_a
    for nombre, rol in (("admin", "ADMIN"), ("vendedor", "VENDEDOR"), ("almacenero", "ALMACENERO")):
        nuevo_usuario(org, nombre, [e.e1], [(rol, e.e1)])
    establecer_contexto(e.e.org_b.pk, [e.eb.pk], e.e.usuario_id)
    nuevo_usuario(e.e.org_b, "otra_org", [e.eb], [("SUPERADMIN", None)])
    establecer_contexto(org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)
    sembrar_listas(org.pk)
    lista = ListaPrecio.objects.sin_ambito().get(organizacion=org, es_principal=True)
    familia = Familia.objects.sin_ambito().create(organizacion=org, nombre="Computadoras")
    laptops = Categoria.objects.sin_ambito().create(
        organizacion=org, familia=familia, nombre="Laptops"
    )
    mouse = Categoria.objects.sin_ambito().create(organizacion=org, familia=familia, nombre="Mouse")
    lenovo = Marca.objects.sin_ambito().create(organizacion=org, nombre="Lenovo")
    hp = Marca.objects.sin_ambito().create(organizacion=org, nombre="HP")
    config = ConfiguracionTienda.objects.sin_ambito().create(
        organizacion=org, activa=True, nombre="Technology", pocas_unidades=5
    )
    config.almacenes.set([e.alm1, e.alm2])

    def campo(categoria, nombre, tipo, clave=None, **extra):
        return CampoEspecificacion.objects.sin_ambito().create(
            organizacion=org,
            categoria=categoria,
            clave=clave or nombre.lower().replace(" ", "-"),
            nombre=nombre,
            tipo=tipo,
            **extra,
        )

    def publicar(
        nombre,
        *,
        categoria=None,
        marca=None,
        precio=None,
        stock=0,
        publicado=True,
        fotos=1,
        **extra,
    ):
        producto = e.producto(nombre, publicado_web=publicado, **extra)
        cambios = {"categoria": categoria or laptops}
        if marca is not None:
            cambios["marca"] = marca
        if publicado:
            cambios["slug"] = generar_slug(org.pk, nombre)
        Producto.objects.sin_ambito().filter(pk=producto.pk).update(**cambios)
        producto.refresh_from_db()
        if precio is not None:
            PrecioProducto.objects.sin_ambito().create(
                organizacion=org, producto=producto, lista=lista, precio=Decimal(str(precio))
            )
        if stock:
            comprar_stock(e, producto, stock, 1)
        for _ in range(fotos):
            servicio_fotos.agregar(producto, png())
        return producto

    return SimpleNamespace(
        compras=compras,
        e=e,
        org=org,
        lista=lista,
        familia=familia,
        laptops=laptops,
        mouse=mouse,
        lenovo=lenovo,
        hp=hp,
        config=config,
        campo=campo,
        publicar=publicar,
    )
