"""API de la toma de inventario físico: permisos, conteo a ciegas, aislamiento e idempotencia."""

import pytest

from apps.auditoria import servicios
from apps.inventario.models import ConteoToma, DetalleToma
from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE, clave, cuerpo, registrar

pytestmark = pytest.mark.django_db

TOMAS = f"{BASE}/tomas"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def stock(mundo):
    """Cemento con 10 unidades a S/ 20 en el almacén de la empresa 1."""
    cemento = mundo.producto()
    r = registrar(cliente_de("almacenero"), cuerpo(mundo, cemento))
    assert r.status_code == 201, r.content
    return cemento


def _crear(api, mundo, **extra):
    return api.post(
        f"{TOMAS}/",
        {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk, **extra},
        format="json",
    )


def _abierta(api, mundo):
    toma = _crear(api, mundo).json()
    r = api.post(f"{TOMAS}/{toma['id']}/abrir/")
    assert r.status_code == 200, r.content
    return r.json()


def _contar(api, toma_id, producto, cantidad, llave=None, **extra):
    return api.post(
        f"{TOMAS}/{toma_id}/contar/",
        {"producto": producto.pk, "cantidad": cantidad, **extra},
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


class TestFlujo:
    def test_crear_abrir_contar_y_ver_el_avance(self, mundo, stock):
        api = cliente_de("almacenero")
        creada = _crear(api, mundo)
        assert creada.status_code == 201, creada.content
        toma = creada.json()
        assert (toma["estado"], toma["numero"], toma["conteo_ciego"]) == ("BORRADOR", 1, True)
        assert toma["almacen_nombre"] == "Almacén A1"

        abierta = api.post(f"{TOMAS}/{toma['id']}/abrir/").json()
        assert abierta["estado"] == "ABIERTA" and abierta["fecha_corte"]

        r = _contar(api, toma["id"], stock, "9")
        assert r.status_code == 200, r.content
        assert r.json()["cantidad_contada"] == "9.000"

        avance = api.get(f"{TOMAS}/{toma['id']}/avance/").json()
        assert (avance["total"], avance["contados"], avance["porcentaje_avance"]) == (1, 1, "100.0")
        assert api.get(f"{TOMAS}/{toma['id']}/").json()["estado"] == "EN_CONTEO"

    def test_listado_paginado_y_filtrado_por_empresa(self, mundo, stock):
        api = cliente_de("almacenero")
        _crear(api, mundo)
        r = api.get(f"{TOMAS}/", {"empresa": mundo.e1.pk})
        assert r.status_code == 200 and r.json()["count"] == 1
        assert api.get(f"{TOMAS}/").status_code == 400  # la empresa es obligatoria

    def test_cerrar_con_pendientes_pide_confirmacion(self, mundo, stock):
        api = cliente_de("almacenero")
        otro = mundo.producto("Fierro")
        registrar(api, cuerpo(mundo, otro, cantidad="5"))
        toma = _abierta(api, mundo)
        _contar(api, toma["id"], stock, "10")
        r = api.post(f"{TOMAS}/{toma['id']}/cerrar/", {}, format="json")
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "toma_incompleta"
        r = api.post(f"{TOMAS}/{toma['id']}/cerrar/", {"confirmar_pendientes": True}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "CERRADA"

    def test_anular_pide_motivo(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _crear(api, mundo).json()
        assert api.post(f"{TOMAS}/{toma['id']}/anular/", {}, format="json").status_code == 400
        r = api.post(f"{TOMAS}/{toma['id']}/anular/", {"motivo": "Error"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADA"

    def test_nota_y_turnos(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _abierta(api, mundo)
        sin_conteo = api.post(
            f"{TOMAS}/{toma['id']}/nota/", {"producto": stock.pk, "nota": "x"}, format="json"
        )
        assert sin_conteo.status_code == 400
        _contar(api, toma["id"], stock, "9")
        r = api.post(
            f"{TOMAS}/{toma['id']}/nota/",
            {"producto": stock.pk, "nota": "Caja dañada"},
            format="json",
        )
        assert r.status_code == 200 and r.json()["nota"] == "Caja dañada"

        t = api.post(
            f"{TOMAS}/{toma['id']}/turnos/nuevo/",
            {
                "fecha": "2026-10-15",
                "turno": "TARDE",
                "hora_inicio": "16:00",
                "equipo": "Ana, Luis",
            },
            format="json",
        )
        assert t.status_code == 201, t.content
        fin = api.post(
            f"{TOMAS}/{toma['id']}/turnos/{t.json()['id']}/finalizar/",
            {"hora_fin": "19:00"},
            format="json",
        )
        assert fin.status_code == 200 and fin.json()["hora_fin"] == "19:00:00"
        antes = api.post(
            f"{TOMAS}/{toma['id']}/turnos/{t.json()['id']}/finalizar/",
            {"hora_fin": "20:00"},
            format="json",
        )
        assert antes.status_code == 400
        assert len(api.get(f"{TOMAS}/{toma['id']}/turnos/").json()) == 1


class TestConteoACiegas:
    def test_quien_cuenta_no_ve_el_stock_del_sistema_ni_las_diferencias(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _abierta(api, mundo)
        fila = _contar(api, toma["id"], stock, "7").json()
        for campo in (
            "stock_sistema",
            "costo_unitario",
            "diferencia",
            "importe_diferencia",
            "resultado",
        ):
            assert campo not in fila
        lista = api.get(f"{TOMAS}/{toma['id']}/detalle/").json()["results"][0]
        assert "stock_sistema" not in lista and lista["cantidad_contada"] == "7.000"
        avance = api.get(f"{TOMAS}/{toma['id']}/avance/").json()
        assert "resultado" not in avance
        r = api.get(f"{TOMAS}/{toma['id']}/detalle/", {"resultado": "FALTANTE"})
        assert r.status_code == 400  # filtrar por resultado revelaría la diferencia

    def test_quien_aprueba_si_lo_ve(self, mundo, stock):
        almacenero, admin = cliente_de("almacenero"), cliente_de("super")
        toma = _abierta(almacenero, mundo)
        _contar(almacenero, toma["id"], stock, "7")
        fila = admin.get(f"{TOMAS}/{toma['id']}/detalle/").json()["results"][0]
        assert (fila["stock_sistema"], fila["diferencia"], fila["resultado"]) == (
            "10.000",
            "-3.000",
            "FALTANTE",
        )
        assert fila["importe_diferencia"] == "-60.00"
        resultado = admin.get(f"{TOMAS}/{toma['id']}/avance/").json()["resultado"]
        assert resultado["faltantes"] == 1 and resultado["importe_faltante"] == "-60.00"

    def test_sin_conteo_a_ciegas_todos_lo_ven(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _crear(api, mundo, conteo_ciego=False).json()
        api.post(f"{TOMAS}/{toma['id']}/abrir/")
        fila = api.get(f"{TOMAS}/{toma['id']}/detalle/").json()["results"][0]
        assert fila["stock_sistema"] == "10.000"


class TestDetalle:
    def test_filtros_de_la_hoja_de_conteo(self, mundo, stock):
        api = cliente_de("almacenero")
        otro = mundo.producto("Fierro corrugado")
        registrar(api, cuerpo(mundo, otro, cantidad="5"))
        toma = _abierta(api, mundo)
        _contar(api, toma["id"], stock, "10")
        url = f"{TOMAS}/{toma['id']}/detalle/"
        assert api.get(url).json()["count"] == 2
        assert [f["producto"] for f in api.get(url, {"estado": "pendiente"}).json()["results"]] == [
            otro.pk
        ]
        assert [f["producto"] for f in api.get(url, {"estado": "contado"}).json()["results"]] == [
            stock.pk
        ]
        assert api.get(url, {"q": "fierro"}).json()["count"] == 1
        assert api.get(url, {"estado": "otro"}).status_code == 400

    def test_filtro_sin_nota_y_contador_en_el_avance(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _abierta(api, mundo)
        _contar(api, toma["id"], stock, "5")  # 5 de 10: diferencia importante
        url = f"{TOMAS}/{toma['id']}/detalle/"
        assert [f["producto"] for f in api.get(url, {"sin_nota": 1}).json()["results"]] == [
            stock.pk
        ]
        assert api.get(f"{TOMAS}/{toma['id']}/avance/").json()["por_anotar"] == 1
        api.post(
            f"{TOMAS}/{toma['id']}/nota/", {"producto": stock.pk, "nota": "Revisado"}, format="json"
        )
        assert api.get(url, {"sin_nota": 1}).json()["count"] == 0


class TestPermisosYAislamiento:
    def test_sin_permiso_no_se_ve_ni_se_crea(self, mundo, stock):
        vendedor = cliente_de("vendedor")
        assert vendedor.get(f"{TOMAS}/", {"empresa": mundo.e1.pk}).status_code == 403
        assert _crear(vendedor, mundo).status_code == 403

    def test_el_contador_ve_pero_no_gestiona_ni_cuenta(self, mundo, stock):
        toma = _abierta(cliente_de("almacenero"), mundo)
        contador = cliente_de("contador")
        assert contador.get(f"{TOMAS}/{toma['id']}/").status_code == 200
        assert contador.post(f"{TOMAS}/{toma['id']}/cerrar/", {}, format="json").status_code == 403
        assert _contar(contador, toma["id"], stock, "1").status_code == 403

    def test_otra_organizacion_no_ve_la_toma(self, mundo, stock):
        toma = _abierta(cliente_de("almacenero"), mundo)
        ajeno = cliente_de("otra_org")
        assert ajeno.get(f"{TOMAS}/{toma['id']}/").status_code in (403, 404)
        assert ajeno.post(f"{TOMAS}/{toma['id']}/abrir/").status_code in (403, 404)

    def test_otra_empresa_de_la_misma_organizacion_tampoco(self, mundo, stock):
        toma = _abierta(cliente_de("almacenero"), mundo)
        assert cliente_de("vendedor_a2").get(f"{TOMAS}/{toma['id']}/").status_code in (403, 404)

    def test_no_se_crea_con_un_almacen_de_otra_empresa(self, mundo, stock):
        api = cliente_de("super")
        r = api.post(
            f"{TOMAS}/", {"empresa": mundo.e1.pk, "almacen": mundo.alm[2].pk}, format="json"
        )
        assert r.status_code == 400 and r.json()["error"]["codigo"] == "toma_invalida"


class TestIdempotencia:
    def test_un_reintento_no_registra_dos_veces_el_conteo(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _abierta(api, mundo)
        llave = clave()
        primero = _contar(api, toma["id"], stock, "9", llave)
        segundo = _contar(api, toma["id"], stock, "9", llave)
        assert (primero.status_code, segundo.status_code) == (200, 200)
        assert segundo.json() == primero.json() and segundo["Idempotency-Replayed"] == "true"
        assert ConteoToma.objects.sin_ambito().count() == 1
        assert DetalleToma.objects.sin_ambito().get().numero_conteos == 1

    def test_sin_clave_no_se_cuenta(self, mundo, stock):
        api = cliente_de("almacenero")
        toma = _abierta(api, mundo)
        r = api.post(
            f"{TOMAS}/{toma['id']}/contar/", {"producto": stock.pk, "cantidad": "9"}, format="json"
        )
        assert r.status_code == 400
        assert ConteoToma.objects.sin_ambito().count() == 0


def _cerrada(api, mundo, producto, cantidad="9"):
    toma = _abierta(api, mundo)
    assert _contar(api, toma["id"], producto, cantidad).status_code == 200
    r = api.post(f"{TOMAS}/{toma['id']}/cerrar/", {}, format="json")
    assert r.status_code == 200, r.content
    return toma


class TestAprobacion:
    def test_solo_quien_aprueba_puede_aprobar_y_se_genera_el_ajuste(self, mundo, stock):
        almacenero, admin = cliente_de("almacenero"), cliente_de("super")
        toma = _cerrada(almacenero, mundo, stock)
        url = f"{TOMAS}/{toma['id']}/aprobar/"
        assert almacenero.post(url, {}, format="json").status_code == 403
        r = admin.post(url, {"nota": "Conforme"}, format="json")
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["estado"] == "APROBADA" and datos["aprobada_en"] and datos["fecha_ajuste"]
        (movimiento,) = datos["movimientos"]
        assert (movimiento["tipo"], movimiento["estado"]) == ("SALIDA", "EMITIDO")
        # El ajuste es un movimiento normal de inventario, con la operación 28 de SUNAT.
        detalle = admin.get(f"{BASE}/movimientos/{movimiento['id']}/").json()
        assert (detalle["origen"], detalle["tipo_operacion"]) == ("AJUSTE", "28")
        assert detalle["lineas"][0]["saldo_cantidad"] == "9.000"
        # La ficha también lista los ajustes.
        assert (
            admin.get(f"{TOMAS}/{toma['id']}/").json()["movimientos"][0]["id"] == movimiento["id"]
        )

    def test_la_vista_previa_puede_filtrar_los_productos_con_serie(self, mundo, stock):
        admin = cliente_de("super")
        toma = _cerrada(admin, mundo, stock)
        datos = admin.get(f"{TOMAS}/{toma['id']}/ajustes/", {"lleva_serie": 1}).json()
        assert datos["count"] == 0  # el cemento no lleva serie
        assert datos["resumen"]["faltantes"] == 1  # pero el resumen sigue siendo de toda la toma

    def test_vista_previa_del_ajuste_solo_para_quien_aprueba(self, mundo, stock):
        almacenero, admin = cliente_de("almacenero"), cliente_de("super")
        toma = _cerrada(almacenero, mundo, stock)
        url = f"{TOMAS}/{toma['id']}/ajustes/"
        assert almacenero.get(url).status_code == 403
        r = admin.get(url)
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["count"] == 1
        fila = datos["results"][0]
        assert (fila["tipo"], fila["cantidad"], fila["importe_estimado"]) == (
            "SALIDA",
            "1.000",
            "20.00",
        )
        assert datos["resumen"]["faltantes"] == 1 and datos["resumen"]["importe_neto"] == "-20.00"

    def test_la_vista_previa_exige_la_toma_cerrada(self, mundo, stock):
        admin = cliente_de("super")
        toma = _abierta(admin, mundo)
        assert admin.get(f"{TOMAS}/{toma['id']}/ajustes/").status_code == 409

    def test_aprobar_dos_veces_no_ajusta_dos_veces(self, mundo, stock):
        admin = cliente_de("super")
        toma = _cerrada(admin, mundo, stock)
        url = f"{TOMAS}/{toma['id']}/aprobar/"
        assert admin.post(url, {}, format="json").status_code == 200
        r = admin.post(url, {}, format="json")
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "toma_estado_invalido"
        stock_actual = admin.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk}).json()["results"][0]
        assert stock_actual["cantidad"] == "9.000"

    def test_la_fecha_futura_se_rechaza(self, mundo, stock):
        admin = cliente_de("super")
        toma = _cerrada(admin, mundo, stock)
        r = admin.post(f"{TOMAS}/{toma['id']}/aprobar/", {"fecha": "2999-01-01"}, format="json")
        assert r.status_code == 400 and r.json()["error"]["codigo"] == "toma_invalida"

    def test_un_faltante_con_serie_pide_las_series(self, mundo):
        admin = cliente_de("super")
        laptop = mundo.producto("Laptop", lleva_serie=True)
        r = registrar(
            admin,
            cuerpo(
                mundo,
                laptop,
                cantidad="2",
                precio="1500",
            )
            | {
                "lineas": [
                    {
                        "producto": laptop.pk,
                        "cantidad": "2",
                        "precio_unitario": "1500",
                        "series": ["SN-001", "SN-002"],
                    }
                ]
            },
        )
        assert r.status_code == 201, r.content
        toma = _abierta(admin, mundo)
        assert _contar(admin, toma["id"], laptop, "1").status_code == 200
        # 1 de 2 laptops: diferencia importante, pide reconteo y nota antes de cerrar.
        assert admin.post(f"{TOMAS}/{toma['id']}/reconteo/").status_code == 200
        assert _contar(admin, toma["id"], laptop, "1", nota="Verificado").status_code == 200
        assert admin.post(f"{TOMAS}/{toma['id']}/cerrar/", {}, format="json").status_code == 200
        url = f"{TOMAS}/{toma['id']}/aprobar/"
        r = admin.post(url, {}, format="json")
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "ajuste_imposible"
        assert r.json()["error"]["detalle"]["total"] == 1
        r = admin.post(
            url, {"series": [{"producto": laptop.pk, "series": ["SN-002"]}]}, format="json"
        )
        assert r.status_code == 200, r.content


class TestAnularAprobada:
    def test_anular_una_toma_aprobada_exige_el_permiso_de_aprobar(self, mundo, stock):
        almacenero, admin = cliente_de("almacenero"), cliente_de("super")
        toma = _cerrada(almacenero, mundo, stock)
        assert admin.post(f"{TOMAS}/{toma['id']}/aprobar/", {}, format="json").status_code == 200
        url = f"{TOMAS}/{toma['id']}/anular/"
        assert almacenero.post(url, {"motivo": "Error"}, format="json").status_code == 403
        r = admin.post(url, {"motivo": "Se contó mal"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADA"
        stock_actual = admin.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk}).json()["results"][0]
        assert stock_actual["cantidad"] == "10.000"


class TestInformeApi:
    def test_descarga_en_excel_y_pdf_solo_quien_aprueba(self, mundo, stock):
        almacenero, admin = cliente_de("almacenero"), cliente_de("super")
        toma = _cerrada(almacenero, mundo, stock)
        url = f"{TOMAS}/{toma['id']}/reporte/"
        assert almacenero.get(url).status_code == 403  # no puede aprobar
        excel = admin.get(url, {"formato": "xlsx"})
        assert excel.status_code == 200, excel.content
        assert excel["Content-Type"].endswith("spreadsheetml.sheet")
        assert (
            "toma-inventario_" in excel["Content-Disposition"]
            and excel["Cache-Control"] == "no-store"
        )
        pdf = admin.get(url, {"formato": "pdf"})
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    def test_formato_invalido_se_rechaza(self, mundo, stock):
        admin = cliente_de("super")
        toma = _cerrada(admin, mundo, stock)
        assert admin.get(f"{TOMAS}/{toma['id']}/reporte/", {"formato": "doc"}).status_code == 400

    def test_una_toma_en_borrador_no_tiene_informe(self, mundo, stock):
        admin = cliente_de("super")
        toma = _crear(admin, mundo).json()
        r = admin.get(f"{TOMAS}/{toma['id']}/reporte/")
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "toma_estado_invalido"
