"""Descarga de libros y reportes: contenido real de los archivos, permisos y validaciones."""

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE, cuerpo, registrar

pytestmark = pytest.mark.django_db

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def dia(dias: int):
    return timezone.localdate() - timedelta(days=dias)


@pytest.fixture
def con_historia(mundo):
    """Cemento: compra 50 a 20 (día 40), merma de 5 (35), compra 20 a 22 (20), merma de 10 (10)."""
    cemento = mundo.producto()
    api = cliente_de("super")
    for dias, tipo, origen, cant, precio in [
        (40, "ENTRADA", "COMPRA", "50", "20"),
        (35, "SALIDA", "MERMA", "5", None),
        (20, "ENTRADA", "COMPRA", "20", "22"),
        (10, "SALIDA", "MERMA", "10", None),
    ]:
        datos = cuerpo(mundo, cemento, cantidad=cant, precio=precio)
        datos.update(tipo=tipo, origen=origen, fecha=dia(dias).isoformat())
        if precio is None:
            datos["lineas"][0].pop("precio_unitario")
        assert registrar(api, datos).status_code == 201
    return cemento


def pedir(usuario, tipo, mundo, **parametros):
    return cliente_de(usuario).get(
        f"{BASE}/reportes/{tipo}/", {"empresa": mundo.e1.pk, **parametros}
    )


def filas(respuesta):
    libro = load_workbook(io.BytesIO(respuesta.content))
    return libro, [list(f) for f in libro.worksheets[0].iter_rows(values_only=True)]


def kardex_params(mundo, cemento, desde=30, hasta=0):
    return {
        "almacen": mundo.alm[1].pk,
        "producto": cemento.pk,
        "desde": dia(desde).isoformat(),
        "hasta": dia(hasta).isoformat(),
    }


class TestExcel:
    def test_formato_12_1_con_saldo_inicial_entradas_salidas_y_totales(self, mundo, con_historia):
        r = pedir("contador", "kardex-fisico", mundo, **kardex_params(mundo, con_historia))
        assert r.status_code == 200 and r["Content-Type"] == XLSX
        libro, tabla = filas(r)
        assert libro.worksheets[0].title == "Formato 12.1"
        textos = " ".join(str(c) for f in tabla[:14] for c in f if c)
        assert mundo.e1.ruc in textos and "Cemento Pacasmayo MS" in textos
        assert "Promedio ponderado" in textos
        cabecera = next(i for i, f in enumerate(tabla) if f[0] == "FECHA")
        cuerpo_ = tabla[cabecera + 1 :]
        assert cuerpo_[0][3] == "SALDO INICIAL" and cuerpo_[0][7] == 45
        assert [(f[5], f[6], f[7]) for f in cuerpo_[1:3]] == [(20, None, 65), (None, 10, 55)]
        assert (cuerpo_[3][5], cuerpo_[3][6], cuerpo_[3][7]) == (20, 10, 55)  # totales

    def test_formato_13_1_valorizado(self, mundo, con_historia):
        r = pedir("contador", "kardex-valorizado", mundo, **kardex_params(mundo, con_historia))
        assert r.status_code == 200
        _, tabla = filas(r)
        cabecera = next(i for i, f in enumerate(tabla) if f[0] == "FECHA")
        inicial, compra, venta, totales = tabla[cabecera + 1 : cabecera + 5]
        assert (inicial[11], inicial[13]) == (45, 900)
        assert (compra[5], compra[7], compra[11], compra[13]) == (20, 440, 65, 1340)
        assert (venta[8], venta[10], venta[11], venta[13]) == (10, 206.15, 55, 1133.85)
        assert (totales[7], totales[10], totales[13]) == (440, 206.15, 1133.85)

    def test_saldos_a_una_fecha(self, mundo, con_historia):
        r = pedir("contador", "saldos", mundo, fecha=dia(25).isoformat())
        assert r.status_code == 200
        _, tabla = filas(r)
        cabecera = next(i for i, f in enumerate(tabla) if f[2] == "PRODUCTO")
        producto, total = tabla[cabecera + 1], tabla[cabecera + 2]
        assert (producto[2], producto[4], producto[6]) == ("Cemento Pacasmayo MS", 45, 900)
        assert total[6] == 900

    def test_costo_de_venta(self, mundo, con_historia):
        r = pedir(
            "contador", "costo-venta", mundo, desde=dia(30).isoformat(), hasta=dia(0).isoformat()
        )
        assert r.status_code == 200
        _, tabla = filas(r)
        cabecera = next(i for i, f in enumerate(tabla) if f[0] == "ALMACÉN" and f[4] == "CANTIDAD")
        f = tabla[cabecera + 1]
        assert (f[5], f[7], f[9], f[11], f[12]) == (900, 440, 206.15, 1133.85, 206.15)

    def test_libro_de_movimientos_con_hojas_dcab_y_ddet(self, mundo, con_historia):
        r = pedir(
            "contador", "movimientos", mundo, desde=dia(45).isoformat(), hasta=dia(0).isoformat()
        )
        assert r.status_code == 200
        libro = load_workbook(io.BytesIO(r.content))
        assert libro.sheetnames == ["Léeme", "Dcab", "Ddet"]
        dcab = [list(f) for f in libro["Dcab"].iter_rows(values_only=True)]
        ddet = [list(f) for f in libro["Ddet"].iter_rows(values_only=True)]
        assert dcab[0][:4] == ["ID", "DCTIPMOV", "DCTOCOD", "DCCPCOD"]
        assert [f[1] for f in dcab[1:]] == ["D", "H", "D", "H"]  # entradas D, salidas H
        assert [f[15] for f in dcab[1:]] == [1, 1, 1, 1]  # DCEST vigente
        assert len(ddet) == 5 and ddet[1][0] == dcab[1][0]  # el ID une cabecera y detalle
        assert ddet[2][7] == 20  # costo unitario de la salida al promedio

    def test_un_nombre_que_parece_formula_se_guarda_como_texto(self, mundo):
        peligroso = mundo.producto('=HYPERLINK("http://malo.example","clic")')
        api = cliente_de("super")
        registrar(api, cuerpo(mundo, peligroso, cantidad="5", precio="10"))
        r = pedir("contador", "saldos", mundo)
        libro = load_workbook(io.BytesIO(r.content))
        celdas = [c for fila in libro.worksheets[0].iter_rows() for c in fila if c.value]
        celda = next(c for c in celdas if "HYPERLINK" in str(c.value))
        assert celda.data_type == "s" and celda.value.startswith("=HYPERLINK")


class TestPdf:
    @pytest.mark.parametrize("tipo", ["kardex-fisico", "kardex-valorizado"])
    def test_libros_del_kardex(self, mundo, con_historia, tipo):
        r = pedir("contador", tipo, mundo, formato="pdf", **kardex_params(mundo, con_historia))
        assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
        assert r.content.startswith(b"%PDF") and len(r.content) > 1500

    def test_saldos_y_costo_de_venta(self, mundo, con_historia):
        for tipo, extra in [
            ("saldos", {}),
            ("costo-venta", {"desde": dia(30).isoformat(), "hasta": dia(0).isoformat()}),
        ]:
            r = pedir("contador", tipo, mundo, formato="pdf", **extra)
            assert r.status_code == 200 and r.content.startswith(b"%PDF")

    def test_un_nombre_con_marcas_html_no_rompe_el_documento(self, mundo):
        raro = mundo.producto("Tubo <b>3/4</b> & <i>codo")
        registrar(cliente_de("super"), cuerpo(mundo, raro, cantidad="2", precio="5"))
        r = pedir("contador", "saldos", mundo, formato="pdf")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")

    def test_el_libro_de_movimientos_solo_existe_en_excel(self, mundo, con_historia):
        r = pedir(
            "contador",
            "movimientos",
            mundo,
            formato="pdf",
            desde=dia(45).isoformat(),
            hasta=dia(0).isoformat(),
        )
        assert r.status_code == 400


class TestPermisosYValidaciones:
    def test_solo_quien_tiene_el_permiso_exporta(self, mundo, con_historia):
        params = kardex_params(mundo, con_historia)
        for usuario in ("vendedor", "almacenero"):
            assert pedir(usuario, "kardex-fisico", mundo, **params).status_code == 403
        for usuario in ("contador", "admin", "super"):
            assert pedir(usuario, "kardex-fisico", mundo, **params).status_code == 200

    def test_otra_organizacion_no_exporta(self, mundo, con_historia):
        assert pedir("otra_org", "saldos", mundo).status_code == 403

    def test_sin_sesion(self, mundo, api):
        r = api.get(f"{BASE}/reportes/saldos/", {"empresa": mundo.e1.pk})
        assert r.status_code in (401, 403)

    def test_la_empresa_es_obligatoria_y_el_reporte_debe_existir(self, mundo):
        assert cliente_de("contador").get(f"{BASE}/reportes/saldos/").status_code == 400
        assert pedir("contador", "no-existe", mundo).status_code == 404

    def test_el_kardex_exige_almacen_y_producto(self, mundo, con_historia):
        base = {"desde": dia(30).isoformat(), "hasta": dia(0).isoformat()}
        assert pedir("contador", "kardex-fisico", mundo, **base).status_code == 400
        assert (
            pedir(
                "contador", "kardex-valorizado", mundo, almacen=mundo.alm[1].pk, **base
            ).status_code
            == 400
        )

    @pytest.mark.parametrize(
        "cambio",
        [
            {"desde": "2026-13-01"},
            {"hasta": (timezone.localdate() + timedelta(days=1)).isoformat()},
            {"desde": dia(0).isoformat(), "hasta": dia(5).isoformat()},
            {"desde": dia(400).isoformat(), "hasta": dia(0).isoformat()},
            {"almacen": 999999},
            {"formato": "doc"},
        ],
    )
    def test_parametros_invalidos(self, mundo, con_historia, cambio):
        params = {**kardex_params(mundo, con_historia), **cambio}
        assert pedir("contador", "kardex-fisico", mundo, **params).status_code == 400

    def test_el_rango_es_obligatorio_en_costo_de_venta_y_movimientos(self, mundo):
        assert pedir("contador", "costo-venta", mundo).status_code == 400
        assert pedir("contador", "movimientos", mundo).status_code == 400

    def test_saldos_no_admite_fecha_futura(self, mundo):
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        assert pedir("contador", "saldos", mundo, fecha=manana).status_code == 400

    def test_el_archivo_viaja_como_adjunto_sin_cache_y_con_nombre_seguro(self, mundo, con_historia):
        r = pedir("contador", "kardex-fisico", mundo, **kardex_params(mundo, con_historia))
        disposicion = r["Content-Disposition"]
        assert disposicion.startswith('attachment; filename="kardex-fisico_')
        assert disposicion.endswith('.xlsx"') and ".." not in disposicion
        assert r["Cache-Control"] == "no-store" and r["X-Content-Type-Options"] == "nosniff"

    def test_la_exportacion_queda_en_la_auditoria(self, mundo, con_historia):
        from apps.auditoria.models import AuditoriaEvento

        pedir("contador", "saldos", mundo)
        evento = AuditoriaEvento.objects.filter(accion="inventario.reporte_exportado").latest("id")
        assert evento.empresa_id == mundo.e1.pk and evento.detalle["reporte"] == "saldos"
