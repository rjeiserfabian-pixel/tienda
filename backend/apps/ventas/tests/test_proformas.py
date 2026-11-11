"""Proformas: cotizar sin mover stock ni dinero, y venderlas después."""

import itertools
from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.inventario.models import SaldoStock
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import proformas
from apps.ventas.exceptions import PrecioBajoElMinimo, VentaInvalida
from apps.ventas.models import LineaProforma, Proforma, Venta
from apps.ventas.servicios import LineaEntrada

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


def linea(tienda, producto, cantidad=1, empresa=None, **extra):
    """Una línea de cotización: la empresa que surtiría, sin almacén."""
    return LineaEntrada(producto, D(str(cantidad)), empresa or tienda.a, **extra)


def cotizar(tienda, lineas, **extra):
    datos = {
        "empresa": tienda.a,
        "lineas": lineas,
        "vendedor_nombre": "Rosa Pérez",
        "cliente_nombre": "Juan Pérez",
        "puede_vender_stock_otra_empresa": True,
    }
    return proformas.crear_proforma(**{**datos, **extra})


class TestCrear:
    def test_cotiza_con_precio_e_igv_sin_tocar_stock_ni_dinero(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        pro = cotizar(tienda, [linea(tienda, p, 2)])
        assert (pro.numero, pro.total, pro.estado) == (1, D("236.00"), "EMITIDO")
        assert pro.valida_hasta == tienda.entorno.hoy + timedelta(days=7)
        (ln,) = pro.lineas.all()
        assert (ln.precio_unitario, ln.valor_venta, ln.igv, ln.total) == (
            D("100"),
            D("200.00"),
            D("36.00"),
            D("236.00"),
        )
        assert SaldoStock.objects.get(producto=p, empresa=tienda.a).cantidad == D("10")
        assert not Venta.objects.sin_ambito().exists()

    def test_cotiza_lo_que_no_hay_en_stock(self, tienda):
        p = tienda.producto(stock={tienda.a: 1})
        pro = cotizar(tienda, [linea(tienda, p, 50)])
        assert pro.total == D("5900.00")

    def test_dos_empresas_cada_una_con_su_igv(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        pro = cotizar(tienda, [linea(tienda, pa, 2), linea(tienda, pb, 1, tienda.b)])
        assert pro.total == D("129.80")
        assert {ln.empresa_id: ln.total for ln in pro.lineas.all()} == {
            tienda.a.pk: D("70.80"),
            tienda.b.pk: D("59.00"),
        }

    def test_respeta_el_precio_minimo_como_la_venta(self, tienda):
        p = tienda.producto(costo="60", precios={"PUBLICO": "100", "DESCUENTO": "90"})
        with pytest.raises(PrecioBajoElMinimo):
            cotizar(tienda, [linea(tienda, p, 1, precio_unitario=D("80"))])
        pro = cotizar(tienda, [linea(tienda, p, 1, precio_unitario=D("95"))])
        assert pro.total == D("112.10")

    def test_pide_a_quien_va_dirigida_y_valida_los_datos(self, tienda):
        p = tienda.producto()
        with pytest.raises(VentaInvalida, match="para quién"):
            cotizar(tienda, [linea(tienda, p)], cliente_nombre="")
        with pytest.raises(VentaInvalida, match="1 a 90"):
            cotizar(tienda, [linea(tienda, p)], validez_dias=0)
        with pytest.raises(VentaInvalida, match="al menos un producto"):
            cotizar(tienda, [])
        cliente = tienda.cliente("0")
        pro = cotizar(tienda, [linea(tienda, p)], cliente=cliente, cliente_nombre="")
        assert pro.cliente_nombre == cliente.nombre

    def test_numera_sin_saltos(self, tienda):
        p = tienda.producto()
        numeros = [cotizar(tienda, [linea(tienda, p)]).numero for _ in range(3)]
        assert numeros == [1, 2, 3]


class TestEstado:
    def test_vigente_vencida_y_anulada(self, tienda):
        p = tienda.producto()
        pro = cotizar(tienda, [linea(tienda, p)], validez_dias=1)
        hoy = tienda.entorno.hoy
        assert proformas.estado_de(pro, hoy) == proformas.VIGENTE
        assert proformas.estado_de(pro, hoy + timedelta(days=2)) == proformas.VENCIDA
        otra = cotizar(tienda, [linea(tienda, p)])
        proformas.anular_proforma(otra, motivo="El cliente no quiso")
        assert proformas.estado_de(otra, hoy) == proformas.ANULADA


class TestVender:
    def vender(self, tienda, pro, producto, **extra):
        return tienda.vender(
            [tienda.linea(producto, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            proforma=pro,
            **extra,
        )

    def test_la_venta_recuerda_de_que_proforma_salio(self, tienda):
        p = tienda.producto()
        pro = cotizar(tienda, [linea(tienda, p)])
        venta = self.vender(tienda, pro, p)
        assert venta.proforma == pro
        assert proformas.estado_de(pro, tienda.entorno.hoy) == proformas.VENDIDA

    def test_una_proforma_no_se_vende_dos_veces(self, tienda):
        p = tienda.producto()
        pro = cotizar(tienda, [linea(tienda, p)])
        self.vender(tienda, pro, p)
        with pytest.raises(VentaInvalida, match="ya se vendió"):
            self.vender(tienda, pro, p)

    def test_si_la_venta_se_anula_la_proforma_vuelve_a_estar_disponible(self, tienda):
        from apps.ventas import servicios

        p = tienda.producto()
        pro = cotizar(tienda, [linea(tienda, p)])
        venta = self.vender(tienda, pro, p)
        servicios.anular_venta(venta, motivo="Se arrepintió")
        assert proformas.estado_de(pro, tienda.entorno.hoy) == proformas.VIGENTE
        assert self.vender(tienda, pro, p).proforma == pro

    def test_no_se_vende_una_proforma_anulada_ni_se_anula_una_vendida(self, tienda):
        p = tienda.producto()
        anulada = cotizar(tienda, [linea(tienda, p)])
        proformas.anular_proforma(anulada, motivo="Error")
        with pytest.raises(VentaInvalida, match="anulada"):
            self.vender(tienda, anulada, p)
        vendida = cotizar(tienda, [linea(tienda, p)])
        self.vender(tienda, vendida, p)
        with pytest.raises(VentaInvalida, match="ya se vendió"):
            proformas.anular_proforma(vendida, motivo="Tarde")


def cuerpo(tienda, producto, **extra):
    base = {
        "empresa": tienda.a.pk,
        "cliente_nombre": "Juan Pérez",
        "lineas": [{"producto": producto.pk, "cantidad": "2", "empresa": tienda.a.pk}],
    }
    return {**base, **extra}


def crear(usuario, datos):
    return cliente_de(usuario).post(f"{BASE}/proformas/", datos, format="json")


class TestApi:
    def test_el_vendedor_cotiza_y_ve_el_detalle_para_imprimir(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        r = crear("vendedor", cuerpo(tienda, p, condiciones="Entrega en 2 días", validez_dias=5))
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["total"], d["estado_proforma"]) == (1, "236.00", "VIGENTE")
        assert d["vendedor_nombre"] == "vendedor" and d["condiciones"] == "Entrega en 2 días"
        assert d["emisor"]["ruc"] == tienda.a.ruc
        # Para dibujar el logo de la empresa en la proforma impresa (la imagen se pide aparte).
        assert d["emisor"]["empresa"] == tienda.a.pk and d["emisor"]["tiene_logo"] is False
        assert d["por_empresa"][0]["total"] == "236.00"
        assert d["lineas"][0]["unidad"] and "costo" not in str(d).lower()

    def test_lista_con_filtros(self, tienda):
        p = tienda.producto()
        crear("vendedor", cuerpo(tienda, p))
        crear("vendedor", cuerpo(tienda, p, cliente_nombre="Ana Ruiz"))
        c = cliente_de("vendedor")
        lista = c.get(f"{BASE}/proformas/", {"empresa": tienda.a.pk}).json()
        assert lista["count"] == 2 and lista["results"][0]["cliente_nombre"] == "Ana Ruiz"
        por_nombre = c.get(f"{BASE}/proformas/", {"empresa": tienda.a.pk, "q": "ana"})
        assert por_nombre.json()["count"] == 1
        vigentes = c.get(f"{BASE}/proformas/", {"empresa": tienda.a.pk, "estado": "vigente"})
        assert vigentes.json()["count"] == 2
        vendidas = c.get(f"{BASE}/proformas/", {"empresa": tienda.a.pk, "estado": "vendida"})
        assert vendidas.json()["count"] == 0

    def test_el_contador_no_cotiza_pero_si_ve(self, tienda):
        p = tienda.producto()
        assert crear("contador", cuerpo(tienda, p)).status_code == 403
        crear("vendedor", cuerpo(tienda, p))
        r = cliente_de("contador").get(f"{BASE}/proformas/", {"empresa": tienda.a.pk})
        assert r.status_code == 200

    def test_se_vende_desde_la_proforma_y_queda_vendida(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        pro = crear("vendedor", cuerpo(tienda, p)).json()
        carga = cliente_de("vendedor").get(f"{BASE}/proformas/{pro['id']}/para-vender/").json()
        assert carga["numero"] == 1 and carga["vencida"] is False
        (ln,) = carga["lineas"]
        assert ln["ficha"]["id"] == p.pk and ln["cantidad"] == "2.000" and ln["ficha"]["stock"]
        venta = cliente_de("vendedor").post(
            f"{BASE}/",
            {
                "empresa": tienda.a.pk,
                "tipo_comprobante": "NV",
                "proforma": pro["id"],
                "lineas": [
                    {
                        "producto": p.pk,
                        "cantidad": "2",
                        "empresa": tienda.a.pk,
                        "almacen": tienda.almacen(tienda.a).pk,
                    }
                ],
                "cobros": [{"medio_pago": tienda.efectivo.pk, "monto": "236.00"}],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"proforma-venta-{next(_claves):06d}",
        )
        assert venta.status_code == 201, venta.content
        detalle = cliente_de("vendedor").get(f"{BASE}/proformas/{pro['id']}/").json()
        assert detalle["estado_proforma"] == "VENDIDA"
        otra = cliente_de("vendedor").get(f"{BASE}/proformas/{pro['id']}/para-vender/")
        assert otra.status_code == 409

    def test_guarda_entrega_direccion_y_atencion(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        entrega = (tienda.entorno.hoy + timedelta(days=3)).isoformat()
        r = crear(
            "vendedor",
            cuerpo(
                tienda,
                p,
                cliente_direccion="Jr. Lima 123",
                fecha_entrega=entrega,
                atencion="Ing. Ríos",
                lugar_entrega="Obra Tarapoto",
            ),
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["cliente_direccion"], d["fecha_entrega"], d["atencion"], d["lugar_entrega"]) == (
            "Jr. Lima 123",
            entrega,
            "Ing. Ríos",
            "Obra Tarapoto",
        )

    def test_con_cliente_toma_su_direccion_y_contacto(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        cli = tienda.cliente(direccion="Av. Perú 45", telefono="987654321", correo="sol@x.pe")
        datos = cuerpo(tienda, p, cliente=cli.pk)
        del datos["cliente_nombre"]
        d = crear("vendedor", datos).json()
        assert d["cliente_nombre"] == cli.nombre
        assert d["cliente_direccion"] == "Av. Perú 45"
        assert d["cliente_contacto"] == "987654321 · sol@x.pe"

    def test_la_entrega_no_puede_ser_anterior_a_hoy(self, tienda):
        p = tienda.producto()
        ayer = (tienda.entorno.hoy - timedelta(days=1)).isoformat()
        assert crear("vendedor", cuerpo(tienda, p, fecha_entrega=ayer)).status_code == 400

    def test_convertida_en_venta_descuenta_stock_y_entra_a_caja(self, tienda):
        from apps.caja.servicios import saldo_de

        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        pro = cotizar(tienda, [linea(tienda, p, 2)])
        assert SaldoStock.objects.get(producto=p, empresa=tienda.a).cantidad == D("10")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        tienda.vender([tienda.linea(p, 2)], [tienda.cobro(tienda.efectivo, "236.00")], proforma=pro)
        assert SaldoStock.objects.get(producto=p, empresa=tienda.a).cantidad == D("8")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("236.00")

    def test_anular_pide_motivo(self, tienda):
        p = tienda.producto()
        pro = crear("vendedor", cuerpo(tienda, p)).json()
        url = f"{BASE}/proformas/{pro['id']}/anular/"
        assert cliente_de("vendedor").post(url, {"motivo": ""}, format="json").status_code == 400
        r = cliente_de("vendedor").post(url, {"motivo": "No lo quiso"}, format="json")
        assert r.status_code == 200 and r.json()["estado_proforma"] == "ANULADA"
        assert LineaProforma.objects.sin_ambito().count() == 1
        assert Proforma.objects.sin_ambito().get().estado == "ANULADO"


class TestSerie:
    def test_numera_con_la_serie_de_proformas_de_la_empresa(self, tienda):
        p = tienda.producto()
        pro = cotizar(tienda, [linea(tienda, p)])
        assert (pro.serie, pro.numero, pro.numero_completo) == ("P001", 1, "P001-00000001")
        serie = tienda.series[(tienda.a.pk, "PF")]
        serie.refresh_from_db()
        assert serie.proximo_numero == 2

    def test_sin_serie_de_proformas_no_se_cotiza(self, tienda):
        from apps.mantenimiento.models import SerieComprobante

        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante__codigo="PF"
        ).delete()
        p = tienda.producto()
        with pytest.raises(VentaInvalida, match="serie de proformas"):
            cotizar(tienda, [linea(tienda, p)])

    def test_cada_empresa_numera_las_suyas(self, tienda):
        p = tienda.producto(stock={tienda.entorno.e1: 10, tienda.entorno.e2: 10})
        a = cotizar(tienda, [linea(tienda, p)])
        b = proformas.crear_proforma(
            empresa=tienda.b,
            lineas=[linea(tienda, p, empresa=tienda.b)],
            vendedor_nombre="vendedor",
            cliente_nombre="Ana",
        )
        assert a.numero == b.numero == 1 and a.serie != b.serie

    def test_la_configuracion_ofrece_las_series_de_proforma(self, tienda):
        r = cliente_de("vendedor").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk})
        assert r.status_code == 200, r.content
        (empresa,) = [e for e in r.json()["empresas"] if e["id"] == tienda.a.pk]
        assert [s["proximo"] for s in empresa["series_proforma"]] == ["P001-00000001"]


class TestFormaDePago:
    def test_a_credito_cotiza_con_el_precio_de_credito(self, tienda):
        p = tienda.producto(precios={"PUBLICO": "100", "CREDITO": "110"})
        contado = cotizar(tienda, [linea(tienda, p)])
        credito = cotizar(tienda, [linea(tienda, p)], forma_pago="CREDITO", puede_credito=True)
        assert (contado.forma_pago, contado.total) == ("CONTADO", D("118.00"))
        assert (credito.forma_pago, credito.total) == ("CREDITO", D("129.80"))

    def test_sin_permiso_de_credito_no_se_cotiza_a_credito(self, tienda):
        p = tienda.producto(precios={"PUBLICO": "100", "CREDITO": "110"})
        with pytest.raises(VentaInvalida, match="crédito"):
            cotizar(tienda, [linea(tienda, p)], forma_pago="CREDITO")
