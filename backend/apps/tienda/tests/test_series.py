"""Productos con número de serie en la tienda: la más antigua se asigna sola al pagar y el
almacén puede cambiarla al preparar el pedido."""

# ruff: noqa: F811

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.auditoria.models import AuditoriaEvento
from apps.inventario import series as inv_series
from apps.inventario.models import (
    EstadoSerie,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import Producto
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda.models import CambioSerie, HistorialPedido, LineaPedido, PedidoTienda
from apps.ventas.models import LineaVenta

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import PEDIDOS, con_direccion, contexto, cuerpo, vende  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/pedidos"
CALCULAR = "/api/v1/tienda/carrito/calcular"


def laptop(tienda, nombre="Laptop", precio=300):
    """Un producto publicado que lleva serie (sin stock todavía: entra con sus series)."""
    contexto(tienda)
    p = tienda.publicar(nombre, precio=precio, stock=0, peso_kg=Decimal("2"))
    Producto.objects.sin_ambito().filter(pk=p.pk).update(lleva_serie=True)
    p.refresh_from_db()
    return p


def ingresar(tienda, producto, numeros, *, dias=0, empresa=None, almacen=None):
    """Una entrada de compra con esas series, fechada ``dias`` atrás."""
    e = tienda.e
    contexto(tienda)
    return registrar_movimiento(
        empresa=empresa or e.e1,
        almacen=almacen or e.alm1,
        tipo=TipoMovimiento.ENTRADA,
        origen=OrigenMovimiento.COMPRA,
        fecha=e.hace(dias),
        lineas=[LineaNueva(producto, Decimal(len(numeros)), Decimal("500"), series=tuple(numeros))],
    )


def sacar(tienda, producto, numeros, *, almacen=None):
    """Una salida real (venta en el local) de esas series: quedan «ya salió»."""
    e = tienda.e
    contexto(tienda)
    return registrar_movimiento(
        empresa=e.e1,
        almacen=almacen or e.alm1,
        tipo=TipoMovimiento.SALIDA,
        origen=OrigenMovimiento.VENTA,
        fecha=e.hace(0),
        lineas=[LineaNueva(producto, Decimal(len(numeros)), None, series=tuple(numeros))],
    )


def serie(producto, numero, estado=None):
    filas = SerieProducto.objects.sin_ambito().filter(producto=producto, numero=numero)
    return filas.filter(estado=estado).first() if estado else filas.order_by("-id").first()


def pedir(tienda, producto, cantidad=1, cliente=None):
    contexto(tienda)
    cliente = cliente or registrada()
    r = cliente.post(
        PEDIDOS,
        cuerpo((producto, cantidad), direccion=con_direccion(cliente)),
        format="json",
    )
    assert r.status_code == 201, r.content
    return cliente, r.json()


def anonimo() -> APIClient:
    return APIClient(HTTP_X_REQUESTED_WITH="tienda")


def estado(admin, numero, nuevo):
    r = admin.post(f"{ADMIN}/{numero}/estado/", {"estado": nuevo}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


class TestMasAntiguas:
    def test_la_de_fecha_mas_antigua_sale_primero_aunque_se_registre_despues(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["NUEVA-1", "NUEVA-2"], dias=0)
        ingresar(tienda, p, ["VIEJA-1"], dias=30)
        ingresar(tienda, p, ["MEDIA-1"], dias=10)
        e = tienda.e
        elegidas = inv_series.mas_antiguas(p.pk, e.e1.pk, e.alm1.pk, 3)
        assert [s.numero for s in elegidas] == ["VIEJA-1", "MEDIA-1", "NUEVA-1"]

    def test_a_igual_fecha_la_que_se_registro_antes_y_solo_las_que_estan_en_stock(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["AAA", "BBB", "CCC"], dias=5)
        e = tienda.e
        sacar(tienda, p, ["AAA"])
        assert [s.numero for s in inv_series.mas_antiguas(p.pk, e.e1.pk, e.alm1.pk, 5)] == [
            "BBB",
            "CCC",
        ]

    def test_cantidad_cero_y_otro_almacen(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["AAA"])
        e = tienda.e
        assert inv_series.mas_antiguas(p.pk, e.e1.pk, e.alm1.pk, 0) == []
        assert inv_series.mas_antiguas(p.pk, e.e1.pk, e.alm2.pk, 3) == []


class TestCarrito:
    def test_ya_no_se_bloquea_si_hay_series_en_stock(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["AAA", "BBB"])
        r = (
            anonimo()
            .post(CALCULAR, {"lineas": [{"producto": p.pk, "cantidad": 2}]}, format="json")
            .json()
        )
        assert r["puede_comprar"] is True and r["lineas"][0]["problema"] is None

    def test_no_se_ofrece_mas_de_las_series_que_hay(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["AAA"])
        # El saldo dice 3 pero solo hay una serie: manda la serie.
        SaldoStock.objects.sin_ambito().filter(producto=p).update(cantidad=3)
        from apps.tienda import catalogo

        catalogo.invalidar()
        contexto(tienda)
        r = (
            anonimo()
            .post(CALCULAR, {"lineas": [{"producto": p.pk, "cantidad": 2}]}, format="json")
            .json()
        )
        assert "Solo quedan 1" in r["lineas"][0]["problema"]
        assert r["lineas"][0]["stock_maximo"] == 1


class TestAlPagar:
    def test_se_asigna_la_serie_mas_antigua_y_sale_en_el_comprobante(self, cobra, culqi_falso):
        p = laptop(cobra)
        ingresar(cobra, p, ["NUEVA-1"], dias=0)
        ingresar(cobra, p, ["VIEJA-1"], dias=40)
        c, ped = pedir(cobra, p)
        r = pagar_pedido(c, ped["numero"])
        assert r.status_code == 200 and r.json()["estado"] == "PAGADO", r.content
        contexto(cobra)
        linea = LineaPedido.objects.sin_ambito().get(pedido__numero=ped["numero"], producto=p)
        assert linea.series_asignadas == ["VIEJA-1"] and linea.series_fisicas == []
        assert LineaVenta.objects.sin_ambito().get(producto=p).series == ["VIEJA-1"]
        assert serie(p, "VIEJA-1").estado == EstadoSerie.SALIDO
        assert serie(p, "NUEVA-1").estado == EstadoSerie.EN_STOCK

    def test_dos_pedidos_no_toman_la_misma_serie(self, cobra, culqi_falso):
        p = laptop(cobra)
        ingresar(cobra, p, ["S-001", "S-002"], dias=3)
        c1, p1 = pedir(cobra, p, cliente=registrada("uno@ejemplo.pe"))
        c2, p2 = pedir(cobra, p, cliente=registrada("dos@ejemplo.pe"))
        assert pagar_pedido(c1, p1["numero"]).status_code == 200
        assert pagar_pedido(c2, p2["numero"]).status_code == 200
        contexto(cobra)
        usadas = sorted(
            n
            for ln in LineaPedido.objects.sin_ambito().filter(producto=p)
            for n in ln.series_asignadas
        )
        assert usadas == ["S-001", "S-002"]

    def test_si_faltan_series_el_cobro_se_conserva_y_el_reintento_lo_repara(
        self, cobra, culqi_falso
    ):
        p = laptop(cobra)
        ingresar(cobra, p, ["S-001"])
        c, ped = pedir(cobra, p)
        # La única unidad se vendió en el local antes de que este cliente pagara.
        sacar(cobra, p, ["S-001"])
        r = pagar_pedido(c, ped["numero"])
        assert r.status_code == 200
        assert r.json()["estado"] == "PAGADO_SIN_COMPROBANTE", r.content
        admin = cliente_de("admin")
        d = admin.get(f"{ADMIN}/{ped['numero']}/").json()
        assert "serie" in d["motivo_atencion"].lower()
        # Llega mercadería nueva con series y el reintento asigna la más antigua.
        contexto(cobra)
        ingresar(cobra, p, ["S-NUEVA"], dias=1)
        r = admin.post(f"{ADMIN}/{ped['numero']}/reintentar-comprobante/", {}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "PAGADO", r.content
        contexto(cobra)
        linea = LineaPedido.objects.sin_ambito().get(pedido__numero=ped["numero"], producto=p)
        assert linea.series_asignadas == ["S-NUEVA"]


class TestVisibilidadParaElCliente:
    def test_la_serie_solo_se_ve_cuando_el_equipo_ya_va_hacia_el_cliente(self, cobra, culqi_falso):
        p = laptop(cobra)
        ingresar(cobra, p, ["S-001"])
        c, ped = pedir(cobra, p)
        numero = ped["numero"]
        assert pagar_pedido(c, numero).status_code == 200
        admin = cliente_de("admin")

        def serie_vista():
            lineas = c.get(f"{PEDIDOS}/{numero}").json()["lineas"]
            return [ln["series"] for ln in lineas if not ln["es_envio"]][0]

        assert serie_vista() is None  # PAGADO
        estado(admin, numero, "EN_PREPARACION")
        assert serie_vista() is None
        estado(admin, numero, "ENVIADO")
        assert serie_vista() == ["S-001"]
        estado(admin, numero, "ENTREGADO")
        assert serie_vista() == ["S-001"]


class TestCambiarSerie:
    def pagado(self, cobra, nuevas=("S-VIEJA", "S-OTRA")):
        p = laptop(cobra)
        ingresar(cobra, p, [nuevas[0]], dias=50)
        ingresar(cobra, p, [nuevas[1]], dias=5)
        c, ped = pedir(cobra, p)
        assert pagar_pedido(c, ped["numero"]).status_code == 200
        return p, c, ped["numero"]

    def linea_id(self, numero, producto):
        return LineaPedido.objects.sin_ambito().get(pedido__numero=numero, producto=producto).pk

    def cambiar(self, admin, numero, linea, **extra):
        datos = {
            "linea": linea,
            "anterior": "S-VIEJA",
            "nueva": "S-OTRA",
            "motivo": "La unidad estaba dañada",
            **extra,
        }
        return admin.post(f"{ADMIN}/{numero}/serie/", datos, format="json")

    def test_cambia_la_unidad_fisica_sin_tocar_el_comprobante(self, cobra, culqi_falso):
        p, c, numero = self.pagado(cobra)
        admin = cliente_de("admin")
        linea = self.linea_id(numero, p)
        assert admin.get(f"{ADMIN}/{numero}/").json()["acciones"]["cambiar_serie"] is True
        r = self.cambiar(admin, numero, linea)
        assert r.status_code == 200, r.content
        det = r.json()
        sp = [ln["series_panel"] for ln in det["lineas"] if ln["series_panel"]][0]
        assert sp == {"comprobante": ["S-VIEJA"], "entregadas": ["S-OTRA"], "cambiada": True}
        # Inventario: la unidad tomada salió y la anterior volvió al stock del almacén.
        assert serie(p, "S-OTRA").estado == EstadoSerie.SALIDO
        volvio = serie(p, "S-VIEJA", EstadoSerie.EN_STOCK)
        assert volvio is not None and volvio.salida_id is None
        # El comprobante no se editó y el pedido distingue ambas series.
        assert LineaVenta.objects.sin_ambito().get(producto=p).series == ["S-VIEJA"]
        ln = LineaPedido.objects.sin_ambito().get(pk=linea)
        assert ln.series_asignadas == ["S-VIEJA"] and ln.series_fisicas == ["S-OTRA"]
        # Quedó registro: cambio, historial y auditoría.
        cambio = CambioSerie.objects.sin_ambito().get()
        assert (cambio.serie_anterior, cambio.serie_nueva) == ("S-VIEJA", "S-OTRA")
        assert cambio.motivo == "La unidad estaba dañada" and cambio.usuario_id is not None
        assert any("S-VIEJA → S-OTRA" in h["texto"] for h in det["historial"])
        assert HistorialPedido.objects.filter(pedido__numero=numero).exists()
        assert AuditoriaEvento.objects.filter(accion="tienda.serie_cambiada").exists()

    def test_el_cliente_ve_la_serie_entregada(self, cobra, culqi_falso):
        p, c, numero = self.pagado(cobra)
        admin = cliente_de("admin")
        self.cambiar(admin, numero, self.linea_id(numero, p))
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        lineas = c.get(f"{PEDIDOS}/{numero}").json()["lineas"]
        assert [ln["series"] for ln in lineas if not ln["es_envio"]] == [["S-OTRA"]]

    @pytest.mark.parametrize(
        ("cambio", "texto"),
        [
            ({"motivo": "ab"}, "por qué"),
            ({"anterior": "NO-ES"}, "no es una de las entregadas"),
            ({"nueva": "S-VIEJA"}, "ya está en esta línea"),
            ({"nueva": "NO-EXISTE"}, "no está en el stock"),
        ],
    )
    def test_rechaza_cambios_invalidos(self, cobra, culqi_falso, cambio, texto):
        p, c, numero = self.pagado(cobra)
        r = self.cambiar(cliente_de("admin"), numero, self.linea_id(numero, p), **cambio)
        assert r.status_code == 400, r.content
        assert texto in str(r.json()).lower() or texto in str(r.json())
        assert not CambioSerie.objects.sin_ambito().exists()

    def test_una_serie_de_otro_almacen_no_vale(self, cobra, culqi_falso):
        p, c, numero = self.pagado(cobra)
        e = cobra.e
        ingresar(cobra, p, ["S-OTRO-ALM"], empresa=e.e2, almacen=e.alm2)
        r = self.cambiar(cliente_de("admin"), numero, self.linea_id(numero, p), nueva="S-OTRO-ALM")
        assert r.status_code == 400 and not CambioSerie.objects.sin_ambito().exists()

    def test_despues_del_despacho_ya_no_se_puede(self, cobra, culqi_falso):
        p, c, numero = self.pagado(cobra)
        admin = cliente_de("admin")
        estado(admin, numero, "EN_PREPARACION")
        estado(admin, numero, "ENVIADO")
        d = admin.get(f"{ADMIN}/{numero}/").json()
        assert d["acciones"]["cambiar_serie"] is False
        r = self.cambiar(admin, numero, self.linea_id(numero, p))
        assert r.status_code == 400 and "pagado o en preparación" in str(r.json())

    def test_exige_sesion_del_panel(self, cobra, culqi_falso):
        p, c, numero = self.pagado(cobra)
        linea = self.linea_id(numero, p)
        assert APIClient().post(f"{ADMIN}/{numero}/serie/", {}, format="json").status_code == 401
        assert self.cambiar(c, numero, linea).status_code == 401  # el cliente no entra al panel

    def test_se_puede_volver_a_cambiar_y_la_unidad_anterior_regresa(self, cobra, culqi_falso):
        p, c, numero = self.pagado(cobra)
        admin = cliente_de("admin")
        linea = self.linea_id(numero, p)
        assert self.cambiar(admin, numero, linea).status_code == 200
        r = self.cambiar(admin, numero, linea, anterior="S-OTRA", nueva="S-VIEJA")
        assert r.status_code == 200, r.content
        assert serie(p, "S-VIEJA").estado == EstadoSerie.SALIDO
        assert serie(p, "S-OTRA", EstadoSerie.EN_STOCK) is not None
        assert PedidoTienda.objects.sin_ambito().get(numero=numero).estado == "PAGADO"


class TestPuntoDeVenta:
    URL = "/api/v1/ventas/series-sugeridas/"

    def pedir_sugeridas(self, cliente, tienda, producto, cantidad, **extra):
        e = tienda.e
        params = {
            "empresa": e.e1.pk,
            "surte": e.e1.pk,
            "almacen": e.alm1.pk,
            "producto": producto.pk,
            "cantidad": cantidad,
            **extra,
        }
        return cliente.get(self.URL, params)

    def test_propone_las_mas_antiguas(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["NUE-1", "NUE-2"], dias=0)
        ingresar(tienda, p, ["VIE-1"], dias=90)
        r = self.pedir_sugeridas(cliente_de("vendedor"), tienda, p, 2)
        assert r.status_code == 200, r.content
        assert r.json() == {"series": ["VIE-1", "NUE-1"]}
        assert r["Cache-Control"] == "no-store"

    def test_valida_el_producto_el_almacen_y_la_sesion(self, tienda):
        p = laptop(tienda)
        ingresar(tienda, p, ["AAA"])
        e = tienda.e
        sin_serie = tienda.publicar("Mouse", precio=10, stock=3)
        contexto(tienda)
        v = cliente_de("vendedor")
        assert self.pedir_sugeridas(v, tienda, sin_serie, 1).status_code == 400
        assert self.pedir_sugeridas(v, tienda, p, 1, almacen=e.alm2.pk).status_code == 400
        assert self.pedir_sugeridas(v, tienda, p, 0).status_code == 400
        assert APIClient().get(self.URL, {"empresa": e.e1.pk}).status_code == 401
