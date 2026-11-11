"""API de series e IMEI y de traspasos entre almacenes."""

import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from openpyxl import Workbook

from apps.inventario.models import MovimientoInventario, SaldoStock
from apps.mantenimiento.models import Almacen
from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE, clave, cuerpo, registrar

pytestmark = pytest.mark.django_db

TRASPASO = f"{BASE}/movimientos/traspaso/"


@pytest.fixture
def alm_b(mundo):
    return Almacen.objects.sin_ambito().create(
        empresa=mundo.e1, sucursal=mundo.alm[1].sucursal, codigo="ALM2", nombre="Almacén 2"
    )


def compra(mundo, producto, series, precio="500", llave=None, usuario="super"):
    datos = cuerpo(mundo, producto, cantidad=str(len(series)), precio=precio)
    datos["lineas"][0]["series"] = list(series)
    return registrar(cliente_de(usuario), datos, llave)


def traspaso(mundo, origen, destino, producto, cantidad, series=None, usuario="super", llave=None):
    linea = {"producto": producto.pk, "cantidad": str(cantidad)}
    if series is not None:
        linea["series"] = list(series)
    return cliente_de(usuario).post(
        TRASPASO,
        {
            "empresa": mundo.e1.pk,
            "almacen_origen": origen.pk,
            "almacen_destino": destino.pk,
            "fecha": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "lineas": [linea],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


def stock(mundo, almacen, producto):
    return SaldoStock.objects.sin_ambito().get(almacen=almacen, producto=producto)


class TestSeriesEnMovimientos:
    def test_la_compra_con_series_las_devuelve_en_el_detalle(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        r = compra(mundo, celular, ["imei333", "IMEI111", "imei222"])
        assert r.status_code == 201, r.content
        linea = r.json()["lineas"][0]
        assert linea["series"] == ["IMEI111", "IMEI222", "IMEI333"]
        assert linea["cantidad"] == "3.000"

    def test_series_que_no_coinciden_con_la_cantidad(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        datos = cuerpo(mundo, celular, cantidad="3", precio="500")
        datos["lineas"][0]["series"] = ["AAA111", "BBB222"]
        r = registrar(cliente_de("super"), datos)
        assert r.status_code == 400 and "serie" in r.json()["error"]["mensaje"]
        assert MovimientoInventario.objects.sin_ambito().count() == 0

    def test_un_producto_con_serie_sin_series_se_rechaza(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        assert registrar(cliente_de("super"), cuerpo(mundo, celular)).status_code == 400

    def test_una_serie_repetida_da_conflicto_claro(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        assert compra(mundo, celular, ["AAA111"]).status_code == 201
        r = compra(mundo, celular, ["AAA111"])
        assert r.status_code == 400 and "ya está en stock" in r.json()["error"]["mensaje"]

    def test_un_reintento_con_la_misma_clave_no_duplica_las_series(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        llave = clave()
        assert compra(mundo, celular, ["AAA111"], llave=llave).status_code == 201
        assert compra(mundo, celular, ["AAA111"], llave=llave).status_code == 201
        assert stock(mundo, mundo.alm[1], celular).cantidad == 1

    def test_el_saldo_inicial_por_archivo_rechaza_productos_con_serie(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        libro = Workbook()
        hoja = libro.active
        hoja.append(["Código del producto", "Cantidad", "Costo unitario (S/ sin IGV)"])
        hoja.append([celular.codigo, 3, 500])
        buffer = io.BytesIO()
        libro.save(buffer)
        r = cliente_de("super").post(
            f"{BASE}/saldo-inicial/importar/",
            {
                "empresa": mundo.e1.pk,
                "fecha": timezone.localdate().isoformat(),
                "modo": "validar",
                "archivo": SimpleUploadedFile("s.xlsx", buffer.getvalue()),
            },
            format="multipart",
        )
        datos = r.json()
        assert (datos["validas"], datos["con_error"]) == (0, 1)
        assert "lleva serie" in datos["errores"][0]["mensaje"]


class TestConsultaDeSeries:
    def _datos(self, mundo):
        celular = mundo.producto("Celular X", lleva_serie=True)
        tablet = mundo.producto("Tablet Y", lleva_serie=True)
        compra(mundo, celular, ["IMEI111", "IMEI222"])
        compra(mundo, tablet, ["TAB777"])
        merma = {**cuerpo(mundo, celular, cantidad="1"), "tipo": "SALIDA", "origen": "MERMA"}
        merma["lineas"][0].pop("precio_unitario")
        merma["lineas"][0]["series"] = ["IMEI111"]
        assert registrar(cliente_de("super"), merma).status_code == 201
        return celular, tablet

    def pedir(self, mundo, usuario="super", **filtros):
        return cliente_de(usuario).get(f"{BASE}/series/", {"empresa": mundo.e1.pk, **filtros})

    def test_busca_por_numero_y_muestra_donde_esta_y_su_historial(self, mundo):
        self._datos(mundo)
        r = self.pedir(mundo, q="imei1")  # búsqueda parcial, sin importar mayúsculas
        assert r.status_code == 200
        datos = r.json()
        assert datos["count"] == 1
        fila = datos["results"][0]
        assert (fila["numero"], fila["estado"], fila["producto_nombre"]) == (
            "IMEI111",
            "SALIDO",
            "Celular X",
        )
        assert fila["entrada_numero"] and fila["salida_numero"] and fila["salida_fecha"]
        assert fila["almacen_nombre"] == "Almacén A1"

    def test_filtros(self, mundo):
        celular, tablet = self._datos(mundo)
        assert self.pedir(mundo).json()["count"] == 3
        assert self.pedir(mundo, estado="EN_STOCK").json()["count"] == 2
        assert self.pedir(mundo, producto=tablet.pk).json()["count"] == 1
        assert self.pedir(mundo, almacen=mundo.alm[1].pk, estado="SALIDO").json()["count"] == 1
        assert self.pedir(mundo, q="zzz").json()["count"] == 0

    def test_la_empresa_es_obligatoria_y_se_respeta_el_acceso(self, mundo):
        self._datos(mundo)
        assert cliente_de("super").get(f"{BASE}/series/").status_code == 400
        assert self.pedir(mundo, usuario="vendedor").status_code == 200
        assert self.pedir(mundo, usuario="otra_org").status_code == 403
        sin_acceso = cliente_de("vendedor_a2").get(f"{BASE}/series/", {"empresa": mundo.e1.pk})
        assert sin_acceso.status_code == 403


class TestTraspasoPorApi:
    def test_traspasa_y_devuelve_la_salida_y_la_entrada(self, mundo, alm_b):
        cemento = mundo.producto()
        registrar(cliente_de("super"), cuerpo(mundo, cemento, cantidad="10", precio="20"))
        r = traspaso(mundo, mundo.alm[1], alm_b, cemento, 4)
        assert r.status_code == 201, r.content
        datos = r.json()
        assert (datos["salida"]["tipo"], datos["entrada"]["tipo"]) == ("SALIDA", "ENTRADA")
        assert datos["salida"]["traspaso_id"] == datos["entrada"]["traspaso_id"]
        assert datos["salida"]["origen"] == "TRASPASO"
        assert datos["entrada"]["lineas"][0]["costo_total"] == "80.00"
        assert stock(mundo, mundo.alm[1], cemento).cantidad == 6
        assert stock(mundo, alm_b, cemento).cantidad == 4

    def test_un_reintento_no_traspasa_dos_veces(self, mundo, alm_b):
        cemento = mundo.producto()
        registrar(cliente_de("super"), cuerpo(mundo, cemento, cantidad="10", precio="20"))
        llave = clave()
        traspaso(mundo, mundo.alm[1], alm_b, cemento, 4, llave=llave)
        segundo = traspaso(mundo, mundo.alm[1], alm_b, cemento, 4, llave=llave)
        assert segundo.status_code == 201 and segundo["Idempotency-Replayed"] == "true"
        assert stock(mundo, alm_b, cemento).cantidad == 4

    def test_las_series_viajan_y_aparecen_en_el_detalle(self, mundo, alm_b):
        celular = mundo.producto("Celular X", lleva_serie=True)
        compra(mundo, celular, ["AAA111", "BBB222", "CCC333"])
        r = traspaso(mundo, mundo.alm[1], alm_b, celular, 2, ["AAA111", "BBB222"])
        assert r.status_code == 201, r.content
        assert r.json()["entrada"]["lineas"][0]["series"] == ["AAA111", "BBB222"]
        en_destino = cliente_de("super").get(
            f"{BASE}/series/", {"empresa": mundo.e1.pk, "almacen": alm_b.pk, "estado": "EN_STOCK"}
        )
        assert sorted(f["numero"] for f in en_destino.json()["results"]) == ["AAA111", "BBB222"]

    def test_errores(self, mundo, alm_b):
        cemento = mundo.producto()
        registrar(cliente_de("super"), cuerpo(mundo, cemento, cantidad="2", precio="20"))
        sin_stock = traspaso(mundo, mundo.alm[1], alm_b, cemento, 5)
        assert (sin_stock.status_code, sin_stock.json()["error"]["codigo"]) == (
            409,
            "stock_insuficiente",
        )
        assert traspaso(mundo, mundo.alm[1], mundo.alm[1], cemento, 1).status_code == 400
        assert traspaso(mundo, mundo.alm[1], mundo.alm[2], cemento, 1).status_code == 400
        sin_clave = cliente_de("super").post(TRASPASO, {}, format="json")
        assert sin_clave.status_code == 400
        assert stock(mundo, mundo.alm[1], cemento).cantidad == 2

    def test_permisos(self, mundo, alm_b):
        cemento = mundo.producto()
        registrar(cliente_de("super"), cuerpo(mundo, cemento, cantidad="10", precio="20"))
        assert (
            traspaso(mundo, mundo.alm[1], alm_b, cemento, 1, usuario="vendedor").status_code == 403
        )
        assert (
            traspaso(mundo, mundo.alm[1], alm_b, cemento, 1, usuario="contador").status_code == 403
        )
        assert (
            traspaso(mundo, mundo.alm[1], alm_b, cemento, 1, usuario="almacenero").status_code
            == 201
        )
        assert (
            traspaso(mundo, mundo.alm[1], alm_b, cemento, 1, usuario="otra_org").status_code == 403
        )

    def test_anular_cualquiera_de_las_dos_mitades_deshace_todo(self, mundo, alm_b):
        celular = mundo.producto("Celular X", lleva_serie=True)
        compra(mundo, celular, ["AAA111", "BBB222"])
        datos = traspaso(mundo, mundo.alm[1], alm_b, celular, 2, ["AAA111", "BBB222"]).json()
        entrada_id = datos["entrada"]["id"]

        r = cliente_de("admin").post(
            f"{BASE}/movimientos/{entrada_id}/anular/",
            {"motivo": "Almacén equivocado"},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["movimiento"]["estado"] == "ANULADO"
        assert stock(mundo, mundo.alm[1], celular).cantidad == 2
        assert stock(mundo, alm_b, celular).cantidad == 0
        otra_mitad = cliente_de("admin").get(f"{BASE}/movimientos/{datos['salida']['id']}/")
        assert otra_mitad.json()["estado"] == "ANULADO"
        repetido = cliente_de("admin").post(
            f"{BASE}/movimientos/{datos['salida']['id']}/anular/", {"motivo": "x"}, format="json"
        )
        assert (repetido.status_code, repetido.json()["error"]["codigo"]) == (
            409,
            "documento_ya_anulado",
        )

    def test_no_se_anula_si_lo_traspasado_ya_salio(self, mundo, alm_b):
        cemento = mundo.producto()
        registrar(cliente_de("super"), cuerpo(mundo, cemento, cantidad="10", precio="20"))
        datos = traspaso(mundo, mundo.alm[1], alm_b, cemento, 4).json()
        merma = {
            **cuerpo(mundo, cemento, cantidad="4"),
            "almacen": alm_b.pk,
            "tipo": "SALIDA",
            "origen": "MERMA",
            "fecha": timezone.localdate().isoformat(),  # después del traspaso (fue ayer)
        }
        merma["lineas"][0].pop("precio_unitario")
        assert registrar(cliente_de("super"), merma).status_code == 201
        r = cliente_de("admin").post(
            f"{BASE}/movimientos/{datos['salida']['id']}/anular/", {"motivo": "x"}, format="json"
        )
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "anulacion_no_permitida")
        assert stock(mundo, mundo.alm[1], cemento).cantidad == 6
