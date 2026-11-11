"""Ofertas de la tienda: panel (validaciones), efecto en el catálogo, pedido y pago."""

# ruff: noqa: F811

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.mantenimiento.models import ListaPrecio, PrecioProducto, UsoLista
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import catalogo, ofertas
from apps.tienda.models import OfertaProducto

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import CulqiFalso, cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import PEDIDOS, con_direccion, contexto, cuerpo, vende  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/ofertas/"
PUBLICO = "/api/v1/tienda/"


def iso(dt):
    return dt.isoformat()


def datos(producto, precio="80", *, empieza=-1, dura=48, **extra):
    ahora = timezone.now()
    return {
        "producto": producto.pk,
        "precio_oferta": precio,
        "desde": iso(ahora + timedelta(hours=empieza)),
        "hasta": iso(ahora + timedelta(hours=empieza + dura)),
        **extra,
    }


def crear(producto, precio="80", **kw):
    r = cliente_de("admin").post(ADMIN, datos(producto, precio, **kw), format="json")
    assert r.status_code == 201, r.content
    return r.json()


def publico(ruta):
    cache.clear()
    return APIClient().get(PUBLICO + ruta)


def ficha(producto):
    return publico(f"productos/{producto.slug}").json()


class TestValidaciones:
    def test_crea_y_lista_con_su_estado(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        o = crear(p, "80", etiqueta="Cyber")
        assert o["estado"] == "VIGENTE" and o["precio_normal"] == "100.00"
        assert o["ahorro_pct"] == 20 and o["etiqueta"] == "Cyber"
        lista = cliente_de("admin").get(ADMIN).json()
        assert lista["count"] == 1 and lista["results"][0]["producto"]["nombre"] == "Mouse"

    def test_estados_programada_vencida_y_pausada(self, tienda):
        a = tienda.publicar("A", costo=Decimal("40"), precio=100, stock=5)
        b = tienda.publicar("B", costo=Decimal("40"), precio=100, stock=5)
        c = tienda.publicar("C", costo=Decimal("40"), precio=100, stock=5)
        assert crear(a, empieza=24)["estado"] == "PROGRAMADA"
        assert crear(b, empieza=-72, dura=24)["estado"] == "VENCIDA"
        assert crear(c, activa=False)["estado"] == "PAUSADA"
        admin = cliente_de("admin")
        for estado, esperado in (("PROGRAMADA", 1), ("VENCIDA", 1), ("PAUSADA", 1), ("VIGENTE", 0)):
            r = admin.get(ADMIN, {"estado": estado}).json()
            assert r["count"] == esperado, estado

    @pytest.mark.parametrize("precio", ["100", "120"])
    def test_debe_ser_menor_que_el_precio_normal(self, tienda, precio):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        r = cliente_de("admin").post(ADMIN, datos(p, precio), format="json")
        assert r.status_code == 400 and "menor que el precio normal" in str(r.json())

    def test_no_puede_bajar_del_costo_y_no_dice_el_costo_a_quien_no_ve_utilidad(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)  # cuesta S/ 40
        r = cliente_de("vendedor").post(ADMIN, datos(p, "30"), format="json")
        assert r.status_code in (400, 403)
        r = cliente_de("admin").post(ADMIN, datos(p, "30"), format="json")
        assert r.status_code == 400 and "por debajo del costo" in str(r.json())

    def test_respeta_el_precio_minimo_de_las_listas(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        descuento = (
            ListaPrecio.objects.sin_ambito()
            .filter(organizacion=tienda.org, uso=UsoLista.DESCUENTO)
            .first()
        )
        PrecioProducto.objects.sin_ambito().update_or_create(
            organizacion=tienda.org, producto=p, lista=descuento, defaults={"precio": Decimal("85")}
        )
        admin = cliente_de("admin")
        malo = admin.post(ADMIN, datos(p, "70"), format="json")
        assert malo.status_code == 400 and "mínimo permitido" in str(malo.json())
        assert admin.post(ADMIN, datos(p, "90"), format="json").status_code == 201

    def test_dos_ofertas_activas_no_pueden_pisarse(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        crear(p, "80", empieza=0, dura=48)
        admin = cliente_de("admin")
        r = admin.post(ADMIN, datos(p, "75", empieza=24, dura=48), format="json")
        assert r.status_code == 400 and "otra oferta" in str(r.json())
        # una pausada no cuenta, y una que empieza cuando la otra termina tampoco choca
        assert (
            admin.post(
                ADMIN, datos(p, "75", empieza=24, dura=48, activa=False), format="json"
            ).status_code
            == 201
        )
        assert (
            admin.post(ADMIN, datos(p, "78", empieza=48, dura=24), format="json").status_code == 201
        )

    def test_las_fechas_y_el_producto(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        sin_publicar = tienda.publicar(
            "Oculto", costo=Decimal("40"), precio=100, stock=5, publicado=False
        )
        admin = cliente_de("admin")
        malas = {**datos(p), "hasta": iso(timezone.now() - timedelta(days=3))}
        assert admin.post(ADMIN, malas, format="json").status_code == 400
        assert admin.post(ADMIN, datos(sin_publicar), format="json").status_code == 400
        assert admin.post(ADMIN, {"producto": p.pk}, format="json").status_code == 400

    def test_editar_pausar_y_eliminar(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        o = crear(p, "80")
        admin = cliente_de("admin")
        r = admin.patch(
            f"{ADMIN}{o['id']}/", {"precio_oferta": "70", "activa": False}, format="json"
        )
        assert r.status_code == 200 and r.json()["estado"] == "PAUSADA"
        assert r.json()["precio_oferta"] == "70.00"
        assert admin.delete(f"{ADMIN}{o['id']}/").status_code == 204
        assert OfertaProducto.objects.sin_ambito().count() == 0
        assert (
            OfertaProducto.objects.sin_ambito(incluir_eliminados=True).count() == 1
        )  # se conserva

    def test_permiso_y_aislamiento(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        o = crear(p, "80")
        assert cliente_de("almacenero").get(ADMIN).status_code == 403
        assert APIClient().get(ADMIN).status_code == 401
        otra = cliente_de("otra_org")
        assert otra.patch(f"{ADMIN}{o['id']}/", {"etiqueta": "x"}, format="json").status_code in (
            400,
            404,
        )
        assert otra.delete(f"{ADMIN}{o['id']}/").status_code == 404

    def test_el_margen_solo_con_permiso_de_utilidad(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        crear(p, "80")
        r = cliente_de("admin").get(ADMIN).json()
        assert "margen_pct" in r["results"][0] or r["ver_margen"] is False
        assert "costo" not in str(r)

    def test_buscador_de_productos_para_la_oferta(self, tienda):
        tienda.publicar("Teclado mecánico", costo=Decimal("40"), precio=200, stock=5)
        tienda.publicar("Oculto", costo=Decimal("40"), precio=100, stock=5, publicado=False)
        r = cliente_de("admin").get(ADMIN + "productos/", {"q": "tecl"}).json()
        assert [x["nombre"] for x in r] == ["Teclado mecánico"] and r[0][
            "precio_normal"
        ] == "200.00"
        assert cliente_de("admin").get(ADMIN + "productos/", {"q": "oculto"}).json() == []


class TestCatalogo:
    def test_una_oferta_vigente_se_ve_con_precio_tachado_descuento_y_fin(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        o = crear(p, "80", etiqueta="Cyber")
        d = ficha(p)
        assert d["precio_normal_mostrar"] == "118.00" and d["precio_mostrar"] == "94.40"
        assert d["descuento_pct"] == 20
        assert d["oferta"]["etiqueta"] == "Cyber"
        assert datetime.fromisoformat(d["oferta"]["termina_en"]) == datetime.fromisoformat(
            o["hasta"]
        )
        for secreto in ("costo", "minimo"):
            assert secreto not in str(d)

    def test_programada_vencida_y_pausada_no_cambian_el_precio(self, tienda):
        a = tienda.publicar("A", costo=Decimal("40"), precio=100, stock=5)
        b = tienda.publicar("B", costo=Decimal("40"), precio=100, stock=5)
        c = tienda.publicar("C", costo=Decimal("40"), precio=100, stock=5)
        crear(a, empieza=24)
        crear(b, empieza=-72, dura=24)
        crear(c, activa=False)
        for p in (a, b, c):
            d = ficha(p)
            assert d["precio_mostrar"] == "118.00" and d["oferta"] is None
            assert d["descuento_pct"] is None and d["precio_normal_mostrar"] is None

    def test_si_el_precio_normal_baja_de_la_oferta_la_oferta_se_ignora(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        crear(p, "80")
        PrecioProducto.objects.sin_ambito().filter(producto=p, lista=tienda.lista).update(
            precio=Decimal("70")
        )
        d = ficha(p)
        assert d["oferta"] is None and d["precio_mostrar"] == "82.60"

    def test_el_orden_y_el_filtro_por_precio_usan_el_precio_vigente(self, tienda):
        barato = tienda.publicar("Barato", costo=Decimal("40"), precio=90, stock=5)
        gangazo = tienda.publicar("Gangazo", costo=Decimal("40"), precio=150, stock=5)
        crear(gangazo, "60")  # con IGV 70.80: más barato que «Barato» (106.20)
        r = publico("productos?orden=precio_asc").json()
        assert [x["nombre"] for x in r["results"]] == ["Gangazo", "Barato"]
        r = publico("productos?precio_max=80").json()
        assert [x["nombre"] for x in r["results"]] == ["Gangazo"]
        assert barato.pk != gangazo.pk

    def test_la_lista_de_ofertas_ordena_por_mayor_descuento(self, tienda):
        a = tienda.publicar("Poco", costo=Decimal("40"), precio=100, stock=5)
        b = tienda.publicar("Mucho", costo=Decimal("40"), precio=100, stock=5)
        tienda.publicar("Sin oferta", costo=Decimal("40"), precio=100, stock=5)
        crear(a, "90")
        crear(b, "50")
        r = publico("ofertas").json()
        assert [x["nombre"] for x in r["results"]] == ["Mucho", "Poco"] and r["count"] == 2
        assert [x["descuento_pct"] for x in r["results"]] == [50, 10]

    def test_el_inicio_trae_las_ofertas(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        crear(p, "80")
        assert [x["nombre"] for x in publico("inicio").json()["ofertas"]] == ["Mouse"]

    def test_hora_del_servidor_sin_cache(self, tienda):
        r = APIClient().get(PUBLICO + "hora")
        assert r.status_code == 200 and r["Cache-Control"] == "no-store" and "ahora" in r.json()


class TestRenovacion:
    def test_la_tarea_renueva_la_tienda_cuando_una_oferta_empieza_o_termina(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        o = crear(p, "80", empieza=1, dura=24)  # programada
        assert ofertas.revisar_cambios() is False  # primera vez: solo toma nota
        assert ofertas.revisar_cambios() is False  # nada cambió
        OfertaProducto.objects.sin_ambito().filter(pk=o["id"]).update(
            desde=timezone.now() - timedelta(minutes=1)
        )  # ya empezó
        version = catalogo.version()
        assert ofertas.revisar_cambios() is True
        assert catalogo.version() > version


class TestPedidoYPago:
    def test_el_pedido_vende_al_precio_de_oferta_y_lo_congela(self, vende, culqi_falso):
        contexto(vende)
        p = vende.publicar(
            "Mouse", costo=Decimal("40"), precio=100, stock=5, peso_kg=Decimal("0.5")
        )
        crear(p, "80")
        contexto(vende)
        c = registrada()
        direccion = con_direccion(c)
        r = c.post(PEDIDOS, cuerpo((p, 2), direccion=direccion), format="json")
        assert r.status_code == 201, r.content
        d = r.json()
        # 2 × 80 + 18 % = 188.80 (y no 236.00); el envío (11.80) ya trae su IGV
        assert d["importes"]["subtotal_productos"] == "188.80"
        assert d["importes"]["total"] == "200.60"
        linea = next(ln for ln in d["lineas"] if not ln["es_envio"])
        assert linea["precio_unitario"] == "94.40"
        # La oferta termina: el pedido ya creado NO cambia
        OfertaProducto.objects.sin_ambito().update(hasta=timezone.now() - timedelta(minutes=1))
        cache.clear()
        again = c.get(f"{PEDIDOS}/{d['numero']}").json()
        assert again["importes"]["total"] == "200.60"

    def test_se_puede_pagar_aunque_la_oferta_termine_entre_el_pedido_y_el_pago(
        self, cobra, culqi_falso
    ):
        contexto(cobra)
        p = cobra.publicar(
            "Mouse", costo=Decimal("40"), precio=100, stock=5, peso_kg=Decimal("0.5")
        )
        crear(p, "80")
        contexto(cobra)
        c = registrada()
        direccion = con_direccion(c)
        d = c.post(PEDIDOS, cuerpo((p, 1), direccion=direccion), format="json").json()
        total = Decimal(d["importes"]["total"])
        OfertaProducto.objects.sin_ambito().update(hasta=timezone.now() - timedelta(minutes=1))
        r = pagar_pedido(c, d["numero"])
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "PAGADO" and r.json()["requiere_atencion"] is False
        assert culqi_falso.cobros[0]["amount"] == int(total * 100)

    def test_el_carrito_muestra_el_precio_de_oferta(self, tienda):
        p = tienda.publicar("Mouse", costo=Decimal("40"), precio=100, stock=5)
        crear(p, "80")
        r = (
            APIClient(HTTP_X_REQUESTED_WITH="tienda")
            .post(
                "/api/v1/tienda/carrito/calcular",
                {"lineas": [{"producto": p.pk, "cantidad": 2}]},
                format="json",
            )
            .json()
        )
        assert r["lineas"][0]["precio_unitario"] == "94.40" and r["subtotal"] == "188.80"
