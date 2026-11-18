"""Reclamos de garantía: abrir, proveedor, resolver (reparar, cambiar, rechazar) y la API."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.garantias import reclamos
from apps.garantias.exceptions import ReclamoInvalido, ReclamoNoPermitido
from apps.garantias.models import EstadoGarantia, EstadoReclamo, Garantia, ReclamoGarantia
from apps.inventario.models import SaldoStock, SerieProducto, TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/garantias/reclamos/"


def _comprar_series(tienda, producto, *series):
    registrar_movimiento(
        empresa=tienda.a,
        almacen=tienda.almacen(tienda.a),
        tipo=TipoMovimiento.ENTRADA,
        origen="COMPRA",
        fecha=tienda.entorno.hoy,
        lineas=[LineaNueva(producto, D(len(series)), D("500"), series=tuple(series))],
    )


def _celular_vendido(tienda, vendida="IMEI-1", en_stock=("IMEI-2", "IMEI-3")):
    p = tienda.producto(
        "Celular",
        costo="500",
        precios={"PUBLICO": "800"},
        stock={},
        lleva_serie=True,
        garantia_meses=12,
    )
    _comprar_series(tienda, p, vendida, *en_stock)
    tienda.vender(
        [tienda.linea(p, 1, series=(vendida,))],
        [tienda.cobro(tienda.efectivo, "944.00")],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
    )
    return p, Garantia.objects.sin_ambito().get(numero_serie=vendida)


def _audifonos_vendidos(tienda, cantidad=3):
    p = tienda.producto(garantia_meses=6, stock={tienda.a: 10})
    tienda.vender(
        [tienda.linea(p, cantidad)],
        [tienda.cobro(tienda.efectivo, f"{118 * cantidad}.00")],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
    )
    return p, Garantia.objects.sin_ambito().get()


class TestAbrir:
    def test_abre_con_numero_correlativo(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        assert (r.numero_completo, r.estado, r.cantidad) == (
            "RG-000001",
            EstadoReclamo.ABIERTO,
            D("1"),
        )

    def test_una_garantia_no_tiene_dos_reclamos_abiertos(self, tienda):
        _, g = _celular_vendido(tienda)
        reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        with pytest.raises(ReclamoNoPermitido, match="ya tiene un reclamo abierto"):
            reclamos.abrir(garantia_id=g.pk, descripcion="Otra vez la misma falla")

    def test_no_se_reclama_una_garantia_vencida_ni_anulada(self, tienda):
        _, g = _celular_vendido(tienda)
        with pytest.raises(ReclamoInvalido, match="venció"):
            reclamos.abrir(
                garantia_id=g.pk,
                descripcion="No enciende la pantalla",
                hoy=g.vence_el + timedelta(days=1),
            )
        Garantia.objects.sin_ambito().filter(pk=g.pk).update(estado=EstadoGarantia.ANULADA)
        with pytest.raises(ReclamoInvalido, match="anulada"):
            reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")

    def test_la_descripcion_es_obligatoria(self, tienda):
        _, g = _celular_vendido(tienda)
        with pytest.raises(ReclamoInvalido, match="falla"):
            reclamos.abrir(garantia_id=g.pk, descripcion="  ")

    def test_sin_serie_la_cantidad_no_pasa_de_lo_vendido(self, tienda):
        _, g = _audifonos_vendidos(tienda, 3)
        with pytest.raises(ReclamoInvalido, match="entre 1 y 3"):
            reclamos.abrir(garantia_id=g.pk, descripcion="Suenan mal", cantidad=4)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="Suenan mal", cantidad=2)
        assert r.cantidad == D("2")


class TestProveedor:
    def test_envia_y_anota_la_respuesta(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        with pytest.raises(ReclamoNoPermitido, match="envíe"):
            reclamos.respuesta_del_proveedor(r.pk, texto="Lo repusieron")
        r = reclamos.enviar_a_proveedor(
            r.pk, proveedor_id=tienda.entorno.proveedor.pk, rma_numero="RMA-77"
        )
        assert (r.estado, r.rma_numero) == (EstadoReclamo.EN_PROVEEDOR, "RMA-77")
        r = reclamos.respuesta_del_proveedor(r.pk, texto="Repuesto aprobado, llega en 5 días")
        assert r.respuesta_proveedor.startswith("Repuesto aprobado")
        assert r.estado == EstadoReclamo.EN_PROVEEDOR  # sigue abierto hasta resolverlo

    def test_el_proveedor_debe_existir(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        with pytest.raises(ReclamoInvalido, match="proveedor"):
            reclamos.enviar_a_proveedor(r.pk, proveedor_id=999999)

    def test_vincular_una_orden_que_no_existe(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        with pytest.raises(ReclamoInvalido, match="no existe"):
            reclamos.vincular_servicio(r.pk, 999999)


class TestResolver:
    def test_reparado_deja_la_garantia_activa_y_permite_otro_reclamo(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        r = reclamos.resolver(r.pk, resolucion="REPARADO")
        assert (r.estado, r.resolucion) == (EstadoReclamo.RESUELTO, "REPARADO")
        g.refresh_from_db()
        assert g.estado == EstadoGarantia.ACTIVA
        reclamos.abrir(garantia_id=g.pk, descripcion="Volvió a fallar la pantalla")

    def test_rechazado_pide_el_motivo(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        with pytest.raises(ReclamoInvalido, match="detalle"):
            reclamos.resolver(r.pk, resolucion="RECHAZADO")
        r = reclamos.resolver(r.pk, resolucion="RECHAZADO", detalle="Golpe visible en la carcasa")
        assert r.estado == EstadoReclamo.RECHAZADO

    def test_un_reclamo_cerrado_no_se_vuelve_a_resolver(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        reclamos.resolver(r.pk, resolucion="REPARADO")
        with pytest.raises(ReclamoNoPermitido, match="cerrado"):
            reclamos.resolver(r.pk, resolucion="REPARADO")

    def test_cambio_con_serie_conserva_el_plazo_y_mueve_el_stock(self, tienda):
        p, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        almacen = tienda.almacen(tienda.a)
        antes = SaldoStock.objects.sin_ambito().get(producto=p, almacen=almacen).cantidad
        r = reclamos.resolver(
            r.pk,
            resolucion="CAMBIADO",
            detalle="Se entrega IMEI-2",
            cambio=reclamos.Cambio(almacen_id=almacen.pk, series=("imei-2",)),
        )
        g.refresh_from_db()
        nueva = r.garantia_nueva
        assert g.estado == EstadoGarantia.REEMPLAZADA
        assert (nueva.numero_serie, nueva.reemplaza_a_id) == ("IMEI-2", g.pk)
        assert nueva.vence_el == g.vence_el and nueva.estado == EstadoGarantia.ACTIVA
        despues = SaldoStock.objects.sin_ambito().get(producto=p, almacen=almacen).cantidad
        assert despues == antes - 1
        salida = SerieProducto.objects.sin_ambito().get(producto=p, numero="IMEI-2")
        assert salida.estado == "SALIDO" and r.movimiento_id is not None

    def test_cambio_con_serie_exige_la_serie_nueva_y_distinta(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        almacen = tienda.almacen(tienda.a)
        with pytest.raises(ReclamoInvalido, match="serie"):
            reclamos.resolver(
                r.pk,
                resolucion="CAMBIADO",
                detalle="Cambio",
                cambio=reclamos.Cambio(almacen_id=almacen.pk),
            )
        with pytest.raises(ReclamoInvalido, match="misma"):
            reclamos.resolver(
                r.pk,
                resolucion="CAMBIADO",
                detalle="Cambio",
                cambio=reclamos.Cambio(almacen_id=almacen.pk, series=("IMEI-1",)),
            )

    def test_si_el_stock_falla_no_se_cierra_nada(self, tienda):
        p, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        almacen = tienda.almacen(tienda.a)
        with pytest.raises(Exception):  # noqa: B017  (la serie no está en el almacén)
            reclamos.resolver(
                r.pk,
                resolucion="CAMBIADO",
                detalle="Cambio",
                cambio=reclamos.Cambio(almacen_id=almacen.pk, series=("NO-EXISTE",)),
            )
        r.refresh_from_db()
        g.refresh_from_db()
        assert r.estado == EstadoReclamo.ABIERTO and g.estado == EstadoGarantia.ACTIVA
        assert not Garantia.objects.sin_ambito().filter(reemplaza_a=g).exists()

    def test_cambio_parcial_sin_serie_divide_la_garantia(self, tienda):
        p, g = _audifonos_vendidos(tienda, 3)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="Uno suena mal", cantidad=1)
        almacen = tienda.almacen(tienda.a)
        antes = SaldoStock.objects.sin_ambito().get(producto=p, almacen=almacen).cantidad
        r = reclamos.resolver(
            r.pk,
            resolucion="CAMBIADO",
            detalle="Cambio de uno",
            cambio=reclamos.Cambio(almacen_id=almacen.pk),
        )
        g.refresh_from_db()
        assert (g.estado, g.cantidad) == (EstadoGarantia.ACTIVA, D("2.000"))
        assert (r.garantia_nueva.cantidad, r.garantia_nueva.vence_el) == (D("1.000"), g.vence_el)
        despues = SaldoStock.objects.sin_ambito().get(producto=p, almacen=almacen).cantidad
        assert despues == antes - 1

    def test_nota_de_credito_solo_se_anota(self, tienda):
        _, g = _celular_vendido(tienda)
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        r = reclamos.resolver(r.pk, resolucion="NOTA_CREDITO", detalle="Nota FC01-00000003")
        assert r.estado == EstadoReclamo.RESUELTO and r.garantia_nueva_id is None


class TestApi:
    def test_el_vendedor_abre_y_no_puede_resolver(self, tienda):
        _, g = _celular_vendido(tienda)
        r = cliente_de("vendedor").post(
            BASE, {"garantia": g.pk, "descripcion": "No enciende la pantalla"}, format="json"
        )
        assert r.status_code == 201, r.content
        pk = r.json()["id"]
        assert r.json()["numero_completo"] == "RG-000001"
        r = cliente_de("vendedor").post(
            f"{BASE}{pk}/resolver/", {"resolucion": "REPARADO"}, format="json"
        )
        assert r.status_code == 403
        r = cliente_de("admin").post(
            f"{BASE}{pk}/resolver/", {"resolucion": "REPARADO"}, format="json"
        )
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "RESUELTO"

    def test_lista_y_filtra_por_estado(self, tienda):
        _, g = _celular_vendido(tienda)
        reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        lista = cliente_de("vendedor").get(BASE, {"estado": "ABIERTOS"}).json()["results"]
        assert [x["numero_completo"] for x in lista] == ["RG-000001"]
        assert cliente_de("vendedor").get(BASE, {"estado": "RESUELTO"}).json()["results"] == []

    def test_el_cajero_no_abre_reclamos(self, tienda):
        _, g = _celular_vendido(tienda)
        r = cliente_de("cajero").post(
            BASE, {"garantia": g.pk, "descripcion": "No enciende la pantalla"}, format="json"
        )
        assert r.status_code == 403
        assert not ReclamoGarantia.objects.sin_ambito().exists()

    def test_error_de_regla_responde_400(self, tienda):
        _, g = _celular_vendido(tienda)
        r = cliente_de("vendedor").post(BASE, {"garantia": g.pk, "descripcion": ""}, format="json")
        assert r.status_code == 400
