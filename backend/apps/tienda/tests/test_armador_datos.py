"""Datos de «Arma tu PC»: informe de productos incompletos y carga masiva por Excel."""

# ruff: noqa: F811

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook, load_workbook

from apps.mantenimiento.models import CampoEspecificacion, Producto
from apps.seguridad.tests.conftest import cliente_de

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_armador import contexto, pc  # noqa: F401

pytestmark = pytest.mark.django_db

DATOS = "/api/v1/tienda/admin/armador/datos/"
PLANTILLA = DATOS + "plantilla/"
IMPORTAR = DATOS + "importar/"


def campo(pc, espacio, clave, nombre, tipo="TEXTO", opciones=()):
    contexto(pc)
    return CampoEspecificacion.objects.sin_ambito().create(
        organizacion=pc.org,
        categoria=pc.categorias[espacio],
        clave=clave,
        nombre=nombre,
        tipo=tipo,
        opciones=list(opciones),
    )


def excel(filas):
    libro = Workbook()
    hoja = libro.active
    for fila in filas:
        hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return SimpleUploadedFile(
        "datos.xlsx",
        salida.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def subir(archivo, aplicar=False):
    return cliente_de("admin").post(
        IMPORTAR,
        {"archivo": archivo, "aplicar": "true" if aplicar else "false"},
        format="multipart",
    )


def specs(producto):
    return Producto.objects.sin_ambito().get(pk=producto.pk).especificaciones


def codigo_de(producto):
    return Producto.objects.sin_ambito().get(pk=producto.pk).codigo


@pytest.fixture
def piezas(pc):
    campo(pc, "procesador", "socket", "Socket")
    campo(pc, "placa", "socket", "Socket")
    completo = pc.pieza("procesador", "Ryzen 5", socket="AM5", **{"potencia-turbo-maxima": 95})
    vacio = pc.pieza("procesador", "Core i5")
    contexto(pc)
    return pc, completo, vacio


class TestInforme:
    def test_cuenta_completos_incompletos_y_lo_que_falta(self, piezas):
        pc, completo, vacio = piezas
        d = cliente_de("admin").get(DATOS).json()
        cpu = next(e for e in d["espacios"] if e["clave"] == "procesador")
        assert (cpu["total"], cpu["completos"], cpu["incompletos"]) == (2, 1, 1)
        socket = next(x for x in cpu["faltan_por_dato"] if x["clave"] == "socket")
        assert socket["faltan"] == 1
        assert [i["nombre"] for i in d["incompletos"] if i["espacio"] == "Procesador"] == [
            "Core i5"
        ]
        assert d["incompletos"][0]["faltan"] == ["Socket", "potencia-turbo-maxima"]

    def test_avisa_las_categorias_que_no_tienen_el_campo(self, piezas):
        pc, *_ = piezas
        d = cliente_de("admin").get(DATOS).json()
        ram = next(e for e in d["espacios"] if e["clave"] == "ram")
        assert any(x["clave"] == "tipo" for x in ram["categorias_sin_el_campo"])

    def test_solo_quien_configura_la_tienda(self, piezas):
        assert cliente_de("vendedor").get(DATOS).status_code == 403
        assert cliente_de("vendedor").post(IMPORTAR, {}, format="multipart").status_code == 403


class TestPlantilla:
    def test_baja_solo_los_incompletos_por_defecto(self, piezas):
        r = cliente_de("admin").get(PLANTILLA, {"espacio": "procesador"})
        assert r.status_code == 200 and "spreadsheetml" in r["Content-Type"]
        hoja = load_workbook(io.BytesIO(r.content)).worksheets[0]
        filas = [list(fila) for fila in hoja.iter_rows(values_only=True)]
        assert filas[0][:4] == ["Código", "Producto", "Categoría", "Socket"]
        assert [f[1] for f in filas[1:]] == ["Core i5"]
        todos = cliente_de("admin").get(PLANTILLA, {"espacio": "procesador", "todos": "1"})
        hoja = load_workbook(io.BytesIO(todos.content)).worksheets[0]
        assert hoja.max_row == 3  # encabezado + 2 productos


class TestCarga:
    def test_revisar_no_cambia_nada_y_aplicar_si(self, piezas):
        pc, completo, vacio = piezas
        archivo = excel([["Código", "Producto", "Socket"], [codigo_de(vacio), "x", "LGA1700"]])
        r = subir(archivo).json()
        assert r["con_cambios"] == 1 and r["con_error"] == 0 and r["aplicado"] is False
        assert specs(vacio) in ({}, None)
        r = subir(excel([["Código", "Socket"], [codigo_de(vacio), "LGA1700"]]), aplicar=True).json()
        assert r["aplicado"] is True
        assert specs(vacio) == {"socket": "LGA1700"}
        # repetirlo ya no cambia nada
        r = subir(excel([["Código", "Socket"], [codigo_de(vacio), "LGA1700"]]), aplicar=True).json()
        assert r["con_cambios"] == 0 and r["sin_cambios"] == 1

    def test_celdas_vacias_o_con_guion_no_borran_ni_cambian(self, piezas):
        pc, completo, vacio = piezas
        r = subir(
            excel([["Código", "Socket"], [codigo_de(completo), ""], [codigo_de(vacio), "—"]]),
            aplicar=True,
        ).json()
        assert r["con_cambios"] == 0 and r["sin_cambios"] == 2
        assert specs(completo) == {"socket": "AM5", "potencia-turbo-maxima": 95}

    def test_un_codigo_que_no_existe_o_repetido_es_error(self, piezas):
        pc, completo, vacio = piezas
        archivo = excel(
            [
                ["Código", "Socket"],
                ["NOEXISTE", "AM5"],
                [codigo_de(vacio), "AM5"],
                [codigo_de(vacio), "AM4"],
            ]
        )
        r = subir(archivo, aplicar=True).json()
        assert r["con_error"] == 2 and r["con_cambios"] == 1
        assert specs(vacio) == {"socket": "AM5"}  # la primera fila válida sí se aplicó

    def test_una_opcion_fuera_de_la_lista_no_se_aplica(self, pc):
        campo(pc, "ram", "tipo", "Tipo", "LISTA", ("DDR4", "DDR5"))
        ram = pc.pieza("ram", "Kingston 8GB")
        contexto(pc)
        r = subir(excel([["Código", "Tipo"], [codigo_de(ram), "DDR3"]]), aplicar=True).json()
        assert r["con_error"] == 1 and r["aplicado"] is False
        assert specs(ram) in ({}, None)
        r = subir(excel([["Código", "Tipo"], [codigo_de(ram), "ddr5"]]), aplicar=True).json()
        assert r["con_cambios"] == 1 and specs(ram) == {"tipo": "DDR5"}

    def test_archivo_invalido_o_sin_columna_codigo(self, piezas):
        mal = SimpleUploadedFile("x.xlsx", b"no soy excel", content_type="application/octet-stream")
        assert subir(mal).status_code == 400
        assert subir(excel([["Producto", "Socket"], ["a", "b"]])).status_code == 400
