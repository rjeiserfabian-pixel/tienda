"""Guía de remisión de un traspaso entre almacenes: sale del traspaso y no mueve stock."""

import itertools
from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.inventario.exceptions import AnulacionNoPermitida
from apps.inventario.models import (
    MovimientoInventario,
    OrigenMovimiento,
    SaldoStock,
    TipoMovimiento,
)
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    registrar_movimiento,
    registrar_traspaso,
)
from apps.mantenimiento.models import Almacen
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import guias
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import GuiaRemision

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


@pytest.fixture
def alm_b(tienda):
    """Un segundo almacén de la empresa A1, con su propia dirección."""
    e = tienda.entorno
    return Almacen.objects.sin_ambito().create(
        empresa=e.e1,
        sucursal=e.alm1.sucursal,
        codigo="ALM2",
        nombre="Almacén 1B",
        direccion="Av. Grau 456, Moyobamba",
    )


@pytest.fixture
def traspaso(tienda, alm_b):
    """Un traspaso de 3 laptops del almacén principal al 1B."""
    e = tienda.entorno
    p = tienda.producto("Laptop", costo="50", precios={"PUBLICO": "100"})
    salida, entrada = registrar_traspaso(
        empresa=e.e1,
        origen=e.alm1,
        destino=alm_b,
        fecha=e.hoy,
        lineas=[LineaNueva(p, D("3"))],
    )
    return type("T", (), {"salida": salida, "entrada": entrada, "producto": p, "destino": alm_b})


def guia_de(tienda, traspaso, movimiento=None, **extra):
    datos = {
        "punto_partida": "Jr. Lima 123, Tarapoto",
        "punto_llegada": "Av. Grau 456, Moyobamba",
        "fecha_traslado": tienda.entorno.hoy,
        "modalidad": "02",
        "placa": "ABC-123",
        "conductor_nombre": "Luis Soto",
        "usuario_nombre": "Rosa",
    }
    return guias.crear_guia_de_traslado(movimiento or traspaso.salida, **{**datos, **extra})


def stock(tienda, producto, almacen):
    return SaldoStock.objects.get(producto=producto, almacen=almacen, empresa=tienda.a).cantidad


class TestCrear:
    def test_emite_la_guia_del_traspaso_sin_mover_stock(self, tienda, traspaso):
        e = tienda.entorno
        antes = (
            stock(tienda, traspaso.producto, e.alm1),
            stock(tienda, traspaso.producto, traspaso.destino),
        )
        g = guia_de(tienda, traspaso)
        assert g.numero_completo == "T001-00000001" and g.estado == "EMITIDO"
        assert g.comprobante is None and g.movimiento_salida == traspaso.salida
        assert g.motivo == "04" and g.almacen_origen == e.alm1
        # La destinataria es la propia empresa.
        assert (g.destinatario_nombre, g.destinatario_tipo_documento, g.destinatario_documento) == (
            tienda.a.razon_social,
            "RUC",
            tienda.a.ruc,
        )
        (ln,) = g.lineas.all()
        assert (ln.producto, ln.linea_venta, ln.cantidad, ln.descripcion) == (
            traspaso.producto,
            None,
            D("3"),
            "Laptop",
        )
        assert antes == (
            stock(tienda, traspaso.producto, e.alm1),
            stock(tienda, traspaso.producto, traspaso.destino),
        )
        assert antes == (D("7"), D("3"))

    def test_se_puede_emitir_desde_la_entrada_y_queda_ligada_a_la_salida(self, tienda, traspaso):
        g = guia_de(tienda, traspaso, movimiento=traspaso.entrada)
        assert g.movimiento_salida == traspaso.salida

    def test_el_peso_total_es_la_suma_o_el_escrito(self, tienda, traspaso):
        (linea,) = traspaso.salida.lineas.all()
        g = guia_de(tienda, traspaso, pesos={linea.pk: D("2.500")})
        assert (g.peso_kg, g.lineas.get().peso_kg) == (D("2.500"), D("2.500"))
        guias.anular_guia(g, motivo="Cambia el peso")
        escrito = guia_de(tienda, traspaso, pesos={linea.pk: D("2.5")}, peso_kg=D("9"))
        assert escrito.peso_kg == D("9")

    def test_una_sola_guia_vigente_por_traspaso(self, tienda, traspaso):
        g = guia_de(tienda, traspaso)
        with pytest.raises(VentaInvalida, match="ya tiene la guía T001-00000001"):
            guia_de(tienda, traspaso, movimiento=traspaso.entrada)
        guias.anular_guia(g, motivo="Datos mal escritos")
        assert guia_de(tienda, traspaso).numero == 2

    def test_un_traspaso_anulado_no_admite_guia(self, tienda, traspaso):
        anular_movimiento(traspaso.salida, motivo="Error de carga")
        with pytest.raises(VentaInvalida, match="anulado"):
            guia_de(tienda, traspaso)

    def test_el_traspaso_con_guia_vigente_no_se_anula_hasta_anular_la_guia(self, tienda, traspaso):
        g = guia_de(tienda, traspaso)
        with pytest.raises(AnulacionNoPermitida, match="guía de remisión T001-00000001"):
            anular_movimiento(traspaso.entrada, motivo="Error")
        guias.anular_guia(g, motivo="Se repite")
        anular_movimiento(traspaso.entrada, motivo="Error")
        assert MovimientoInventario.objects.get(pk=traspaso.salida.pk).estado == "ANULADO"

    def test_solo_los_traspasos_tienen_guia(self, tienda):
        e = tienda.entorno
        p = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"})
        compra = registrar_movimiento(
            empresa=e.e1,
            almacen=e.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=e.hoy,
            lineas=[LineaNueva(p, D("1"), D("20"))],
        )
        with pytest.raises(VentaInvalida, match="no es un traspaso"):
            guias.crear_guia_de_traslado(
                compra,
                punto_partida="Jr. Lima 123",
                punto_llegada="Av. Grau 456",
                fecha_traslado=e.hoy,
                modalidad="02",
            )

    @pytest.mark.parametrize(
        ("datos", "mensaje"),
        [
            ({"motivo": "01"}, "motivo"),
            ({"punto_llegada": ""}, "desde dónde y hasta dónde"),
            ({"bultos": 0}, "bultos"),
            ({"peso_kg": D("-1")}, "peso"),
            ({"pesos": {999999: D("1")}}, "no son de este traspaso"),
            ({"modalidad": "01"}, "transportista"),
            ({"placa": ""}, "placa"),
        ],
    )
    def test_valida_los_datos(self, tienda, traspaso, datos, mensaje):
        with pytest.raises(VentaInvalida, match=mensaje):
            guia_de(tienda, traspaso, **datos)

    def test_la_fecha_de_traslado_no_es_anterior_a_hoy(self, tienda, traspaso):
        with pytest.raises(VentaInvalida, match="anterior a hoy"):
            guia_de(tienda, traspaso, fecha_traslado=tienda.entorno.hoy - timedelta(days=1))

    def test_otros_es_un_motivo_valido(self, tienda, traspaso):
        assert guia_de(tienda, traspaso, motivo="13").motivo == "13"

    def test_sin_serie_de_guia_no_se_emite(self, tienda, traspaso):
        from apps.mantenimiento.models import SerieComprobante

        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("09")
        ).update(estado="INACTIVO")
        with pytest.raises(VentaInvalida, match="por ejemplo T001"):
            guia_de(tienda, traspaso)

    def test_las_series_o_imei_viajan_en_la_descripcion(self, tienda, alm_b):
        e = tienda.entorno
        celular = tienda.producto(
            "Celular X", costo="500", precios={"PUBLICO": "900"}, lleva_serie=True, stock={}
        )
        registrar_movimiento(
            empresa=e.e1,
            almacen=e.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=e.hoy,
            lineas=[LineaNueva(celular, D("2"), D("500"), series=("IMEI-1", "IMEI-2"))],
        )
        salida, _ = registrar_traspaso(
            empresa=e.e1,
            origen=e.alm1,
            destino=alm_b,
            fecha=e.hoy,
            lineas=[LineaNueva(celular, D("2"), series=("IMEI-1", "IMEI-2"))],
        )
        g = guias.crear_guia_de_traslado(
            salida,
            punto_partida="Jr. Lima 123, Tarapoto",
            punto_llegada="Av. Grau 456, Moyobamba",
            fecha_traslado=e.hoy,
            modalidad="02",
            placa="ABC-123",
            conductor_nombre="Luis Soto",
        )
        assert g.lineas.get().descripcion == "Celular X (Series: IMEI-1, IMEI-2)"

    def test_la_guia_de_una_venta_sigue_igual(self, tienda, traspaso):
        # El mismo número correlativo se comparte entre guías de ventas y de traspasos.
        p = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"})
        v = tienda.vender([tienda.linea(p, 1)], [tienda.cobro(tienda.efectivo, "59.00")])
        comp = v.comprobantes.get()
        g1 = guias.crear_guia(
            comp,
            lineas=[(comp.lineas.get(), D("1"))],
            punto_partida="Jr. Lima 123, Tarapoto",
            punto_llegada="Av. Grau 456, Moyobamba",
            fecha_traslado=tienda.entorno.hoy,
            modalidad="02",
            placa="ABC-123",
            conductor_nombre="Luis Soto",
        )
        g2 = guia_de(tienda, traspaso)
        assert (g1.numero, g2.numero) == (1, 2) and g1.comprobante == comp


def emitir(usuario, movimiento_id, cuerpo):
    return cliente_de(usuario).post(
        f"{BASE}/traspasos/{movimiento_id}/guia-remision/",
        cuerpo,
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"traslado-{next(_claves):06d}",
    )


def cuerpo(tienda, **extra):
    base = {
        "fecha_traslado": str(tienda.entorno.hoy),
        "modalidad": "02",
        "punto_partida": "Jr. Lima 123, Tarapoto",
        "punto_llegada": "Av. Grau 456, Moyobamba",
        "placa": "abc-123",
        "conductor_nombre": "Luis Soto",
        "bultos": 2,
    }
    return {**base, **extra}


class TestApi:
    def test_propone_los_datos_desde_cualquiera_de_las_dos_mitades(self, tienda, traspaso):
        c = cliente_de("vendedor")
        for mitad in (traspaso.salida, traspaso.entrada):
            envio = c.get(f"{BASE}/traspasos/{mitad.pk}/envio/").json()
            assert envio["movimiento"] == traspaso.salida.pk and envio["se_puede_enviar"] is True
            assert envio["guia_vigente"] is None and envio["motivo"] == "04"
            assert envio["remitente"]["ruc"] == tienda.a.ruc
            assert envio["destinatario"]["documento"] == tienda.a.ruc
            assert envio["almacen_origen"]["id"] == tienda.entorno.alm1.pk
            assert envio["almacen_destino"]["nombre"] == "Almacén 1B"
            # La llegada se propone con la dirección del almacén de destino.
            assert envio["punto_llegada"] == "Av. Grau 456, Moyobamba"
            assert [m["codigo"] for m in envio["motivos"]] == ["04", "13"]
            (linea,) = envio["lineas"]
            assert (linea["descripcion"], linea["cantidad"], linea["series"]) == (
                "Laptop",
                "3.000",
                [],
            )
            assert envio["serie_sugerida"] == envio["series"][0]["id"]

    def test_emite_y_despues_ya_no_se_puede(self, tienda, traspaso):
        (linea,) = traspaso.salida.lineas.all()
        r = emitir(
            "vendedor",
            traspaso.entrada.pk,
            cuerpo(tienda, lineas=[{"linea": linea.pk, "peso_kg": "12.5"}], motivo="13"),
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["numero_completo"] == "T001-00000001" and d["motivo"] == "13"
        assert d["comprobante"] is None and d["comprobante_numero"] == "" and d["venta"] is None
        assert (d["traspaso"], d["traspaso_numero"]) == (traspaso.salida.pk, traspaso.salida.numero)
        assert (d["peso_kg"], d["bultos"], d["placa"]) == ("12.500", 2, "ABC-123")
        assert d["almacen_origen_nombre"] and d["emisor"]["ruc"] == tienda.a.ruc
        assert d["lineas"][0]["peso_kg"] == "12.500"
        envio = cliente_de("vendedor").get(f"{BASE}/traspasos/{traspaso.salida.pk}/envio/").json()
        assert envio["se_puede_enviar"] is False and envio["guia_vigente"]["id"] == d["id"]
        otra = emitir("vendedor", traspaso.salida.pk, cuerpo(tienda))
        assert otra.status_code == 400 and "ya tiene la guía" in otra.json()["error"]["mensaje"]

    def test_un_reintento_con_la_misma_clave_no_emite_dos_guias(self, tienda, traspaso):
        c = cliente_de("vendedor")
        for _ in range(2):
            r = c.post(
                f"{BASE}/traspasos/{traspaso.salida.pk}/guia-remision/",
                cuerpo(tienda),
                format="json",
                HTTP_IDEMPOTENCY_KEY="traslado-clave-001",
            )
            assert r.status_code == 201
        assert GuiaRemision.objects.sin_ambito().count() == 1

    def test_el_contador_no_emite(self, tienda, traspaso):
        assert emitir("contador", traspaso.salida.pk, cuerpo(tienda)).status_code == 403
        assert (
            cliente_de("contador").get(f"{BASE}/traspasos/{traspaso.salida.pk}/envio/").status_code
            == 403
        )

    def test_una_compra_no_es_un_traspaso(self, tienda, traspaso):
        compra = MovimientoInventario.objects.sin_ambito().filter(origen="COMPRA").first()
        r = cliente_de("vendedor").get(f"{BASE}/traspasos/{compra.pk}/envio/")
        assert r.status_code == 400 and "no es un traspaso" in r.json()["error"]["mensaje"]

    def test_un_movimiento_que_no_existe_da_404(self, tienda, traspaso):
        assert cliente_de("vendedor").get(f"{BASE}/traspasos/9999999/envio/").status_code == 404

    def test_el_listado_el_detalle_y_el_excel_incluyen_la_guia_del_traspaso(self, tienda, traspaso):
        g = emitir("vendedor", traspaso.salida.pk, cuerpo(tienda)).json()
        lista = cliente_de("vendedor").get(f"{BASE}/guias-remision/", {"empresa": tienda.a.pk})
        assert lista.status_code == 200 and lista.json()["count"] == 1
        fila = lista.json()["results"][0]
        assert (
            fila["traspaso_numero"] == traspaso.salida.numero and fila["comprobante_numero"] == ""
        )
        detalle = cliente_de("vendedor").get(f"{BASE}/guias-remision/{g['id']}/")
        assert detalle.status_code == 200 and detalle.json()["traspaso"] == traspaso.salida.pk
        excel = cliente_de("admin").get(f"{BASE}/guias-remision/excel/", {"empresa": tienda.a.pk})
        assert excel.status_code == 200 and excel.content[:2] == b"PK"

    def test_anular_la_guia_del_traspaso_libera_el_traspaso(self, tienda, traspaso):
        g = emitir("vendedor", traspaso.salida.pk, cuerpo(tienda)).json()
        r = cliente_de("vendedor").post(
            f"{BASE}/guias-remision/{g['id']}/anular/", {"motivo": "Se canceló"}, format="json"
        )
        assert r.status_code == 200 and r.json()["estado"] == "ANULADO"
        assert emitir("vendedor", traspaso.salida.pk, cuerpo(tienda)).status_code == 201
