"""Cupones de la tienda: descuento, reglas, uso apartado/consumido/liberado y límites."""

# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.mantenimiento.models import ListaPrecio, PrecioProducto, UsoLista
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda.models import Cupon, OfertaProducto, PedidoTienda, UsoCupon

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import COTIZAR, PEDIDOS, con_direccion, contexto, cuerpo, vende  # noqa: F401

pytestmark = pytest.mark.django_db

CODIGO = "VERANO20"


def hacer_cupon(tienda, codigo=CODIGO, **extra):
    datos = {
        "organizacion_id": tienda.org.pk,
        "codigo": codigo,
        "tipo": Cupon.Tipo.PORCENTAJE,
        "valor": Decimal("20"),
        **extra,
    }
    return Cupon.objects.sin_ambito().create(**datos)


def mouse(vende, **extra):
    contexto(vende)
    return vende.publicar(
        "Mouse", costo=Decimal("40"), precio=100, stock=10, peso_kg=Decimal("0.5"), **extra
    )


def pedir(vende, cliente, p, cantidad=2, cupon=None, modalidad="ENVIO"):
    """Crea un pedido con (o sin) cupón; devuelve la respuesta."""
    contexto(vende)
    extra = {"direccion": con_direccion(cliente)} if modalidad == "ENVIO" else {}
    if cupon:
        extra["cupon"] = cupon
    return cliente.post(PEDIDOS, cuerpo((p, cantidad), modalidad=modalidad, **extra), format="json")


class TestDescuento:
    def test_porcentaje_se_reparte_y_se_nota_en_el_precio_de_la_linea(self, vende):
        hacer_cupon(vende)
        p, c = mouse(vende), registrada()
        r = pedir(vende, c, p, cupon="verano20")  # el código no distingue mayúsculas
        assert r.status_code == 201, r.content
        d = r.json()
        # 2 × 118 = 236; 20 % = 47.20 → 188.80 (+ envío 11.80 = 200.60)
        assert d["importes"]["subtotal_productos"] == "188.80"
        assert d["importes"]["total"] == "200.60"
        assert d["importes"]["cupon"] == CODIGO and d["importes"]["descuento_cupon"] == "47.20"
        linea = next(ln for ln in d["lineas"] if not ln["es_envio"])
        assert linea["precio_unitario"] == "94.40" and linea["descuento"] == "47.20"
        # el IGV queda bien calculado sobre el precio ya rebajado
        assert d["importes"]["igv"] == "30.60"

    def test_monto_fijo(self, vende):
        hacer_cupon(vende, tipo=Cupon.Tipo.MONTO, valor=Decimal("30"))
        p, c = mouse(vende), registrada()
        d = pedir(vende, c, p, cupon=CODIGO).json()
        assert d["importes"]["subtotal_productos"] == "206.00"
        assert d["importes"]["descuento_cupon"] == "30.00"

    def test_el_tope_limita_el_descuento(self, vende):
        hacer_cupon(vende, valor=Decimal("50"), tope_descuento=Decimal("20"))
        p, c = mouse(vende), registrada()
        d = pedir(vende, c, p, cupon=CODIGO).json()
        assert d["importes"]["descuento_cupon"] == "20.00"
        assert d["importes"]["subtotal_productos"] == "216.00"

    def test_envio_gratis(self, vende):
        hacer_cupon(vende, tipo=Cupon.Tipo.ENVIO_GRATIS, valor=Decimal("0"))
        p, c = mouse(vende), registrada()
        d = pedir(vende, c, p, cupon=CODIGO).json()
        assert d["importes"]["costo_envio"] == "0.00" and d["importes"]["total"] == "236.00"
        assert d["importes"]["descuento_cupon"] == "11.80"

    def test_envio_gratis_no_sirve_si_se_recoge_en_tienda(self, vende):
        hacer_cupon(vende, tipo=Cupon.Tipo.ENVIO_GRATIS, valor=Decimal("0"))
        p, c = mouse(vende), registrada()
        punto = cliente_de("admin").get("/api/v1/tienda/admin/envios/").json()["puntos"][0]["id"]
        contexto(vende)
        r = c.post(
            PEDIDOS,
            cuerpo((p, 1), modalidad="RECOJO", punto=punto, cupon=CODIGO),
            format="json",
        )
        assert r.status_code == 400 and "envío gratis" in r.json()["error"]["mensaje"]

    def test_no_baja_del_precio_minimo_y_avisa(self, vende):
        p = mouse(vende)
        descuento = (
            ListaPrecio.objects.sin_ambito()
            .filter(organizacion=vende.org, uso=UsoLista.DESCUENTO)
            .first()
        )
        PrecioProducto.objects.sin_ambito().update_or_create(
            organizacion=vende.org, producto=p, lista=descuento, defaults={"precio": Decimal("85")}
        )
        hacer_cupon(vende, valor=Decimal("50"))
        c = registrada()
        contexto(vende)
        cot = c.post(
            COTIZAR,
            {
                "lineas": [{"producto": p.pk, "cantidad": 1}],
                "modalidad": "ENVIO",
                "direccion": con_direccion(c),
                "cupon": CODIGO,
            },
            format="json",
        ).json()["totales"]
        # el 50 % ideal serían S/ 59.00; el mínimo es 85 sin IGV = 100.30 con IGV → ahorra 17.70
        assert cot["descuento"] == "17.70"
        assert "solo en parte" in cot["cupon"]["aviso"]
        assert cot["subtotal_productos"] == "100.30"


class TestReglas:
    def test_no_se_combina_con_ofertas_salvo_que_el_cupon_lo_permita(self, vende):
        p = mouse(vende)
        ahora = timezone.now()
        OfertaProducto.objects.sin_ambito().create(
            organizacion=vende.org,
            producto=p,
            precio_oferta=Decimal("80"),
            desde=ahora - timedelta(hours=1),
            hasta=ahora + timedelta(hours=48),
        )
        hacer_cupon(vende)
        c = registrada()
        r = pedir(vende, c, p, cupon=CODIGO)
        assert r.status_code == 400 and "oferta" in r.json()["error"]["mensaje"]
        Cupon.objects.sin_ambito().update(incluye_ofertas=True)
        cache.clear()
        d = pedir(vende, c, p, cupon=CODIGO).json()
        # 2 × 94.40 = 188.80; 20 % = 37.76 → 151.04
        assert d["importes"]["subtotal_productos"] == "151.04"

    def test_alcance_por_producto(self, vende):
        p, otro = mouse(vende), None
        cupon = hacer_cupon(vende, alcance=Cupon.Alcance.PRODUCTOS)
        otro = vende.publicar("Teclado", costo=Decimal("30"), precio=100, stock=5)
        cupon.productos.add(otro)
        c = registrada()
        r = pedir(vende, c, p, cupon=CODIGO)  # el mouse no entra
        assert r.status_code == 400 and "no aplica" in r.json()["error"]["mensaje"]

    @pytest.mark.parametrize(
        ("cambios", "mensaje"),
        [
            ({"activo": False}, "no está disponible"),
            ({"termina_en": timezone.now() - timedelta(days=1)}, "ya venció"),
            ({"inicia_en": timezone.now() + timedelta(days=1)}, "no está disponible"),
            ({"compra_minima": Decimal("500")}, "500.00"),
            ({"usos_maximos": 0}, "ya se agotó"),
        ],
    )
    def test_cupones_que_no_se_pueden_usar(self, vende, cambios, mensaje):
        hacer_cupon(vende, **cambios)
        p, c = mouse(vende), registrada()
        r = pedir(vende, c, p, cupon=CODIGO)
        assert r.status_code == 400 and mensaje in r.json()["error"]["mensaje"]

    def test_un_codigo_que_no_existe(self, vende):
        p, c = mouse(vende), registrada()
        r = pedir(vende, c, p, cupon="NOEXISTE")
        assert r.status_code == 400 and "No encontramos" in r.json()["error"]["mensaje"]

    def test_uno_por_cliente_y_solo_primera_compra(self, vende, culqi_falso):
        hacer_cupon(vende)
        p, c = mouse(vende), registrada()
        assert pedir(vende, c, p, cupon=CODIGO).status_code == 201
        # el mismo cliente ya lo usó (el pedido sigue esperando el pago)
        segunda = pedir(vende, c, p, cupon=CODIGO)
        assert segunda.status_code == 400 and "Ya usaste" in segunda.json()["error"]["mensaje"]
        # otro cliente sí puede
        assert pedir(vende, registrada("luis@ejemplo.pe"), p, cupon=CODIGO).status_code == 201

    def test_sin_cuenta_pide_ingresar(self, vende):
        hacer_cupon(vende)
        p = mouse(vende)
        r = APIClient(HTTP_X_REQUESTED_WITH="tienda").post(
            COTIZAR,
            {
                "lineas": [{"producto": p.pk, "cantidad": 1}],
                "modalidad": "ENVIO",
                "ubigeo": "150122",
                "cupon": CODIGO,
            },
            format="json",
        )
        assert r.status_code == 200
        assert r.json()["totales"] is None or r.json()["totales"]["cupon_error"]


class TestCotizar:
    def test_un_cupon_invalido_no_rompe_los_totales(self, vende):
        p, c = mouse(vende), registrada()
        contexto(vende)
        r = c.post(
            COTIZAR,
            {
                "lineas": [{"producto": p.pk, "cantidad": 2}],
                "modalidad": "ENVIO",
                "direccion": con_direccion(c),
                "cupon": "NOEXISTE",
            },
            format="json",
        ).json()
        assert r["totales"]["total"] == "247.80"  # sin descuento
        assert r["totales"]["cupon"] is None and "No encontramos" in r["totales"]["cupon_error"]

    def test_cotiza_con_cupon(self, vende):
        hacer_cupon(vende)
        p, c = mouse(vende), registrada()
        contexto(vende)
        r = c.post(
            COTIZAR,
            {
                "lineas": [{"producto": p.pk, "cantidad": 2}],
                "modalidad": "ENVIO",
                "direccion": con_direccion(c),
                "cupon": CODIGO,
            },
            format="json",
        ).json()["totales"]
        assert r["descuento"] == "47.20" and r["total"] == "200.60"
        assert r["cupon"]["codigo"] == CODIGO and r["cupon_error"] == ""

    def test_demasiados_intentos_fallidos_bloquean(self, vende):
        p, c = mouse(vende), registrada()
        contexto(vende)
        cuerpo_cot = {
            "lineas": [{"producto": p.pk, "cantidad": 1}],
            "modalidad": "ENVIO",
            "direccion": con_direccion(c),
            "cupon": "NOEXISTE",
        }
        for _ in range(8):
            assert c.post(COTIZAR, cuerpo_cot, format="json").status_code == 200
        r = c.post(COTIZAR, cuerpo_cot, format="json")
        assert r.status_code == 429


class TestUso:
    def test_se_aparta_se_consume_al_pagar_y_se_libera_si_vence(self, cobra, culqi_falso):
        hacer_cupon(cobra, usos_por_cliente=2)
        contexto(cobra)
        p = cobra.publicar("Mouse", costo=Decimal("40"), precio=100, stock=10)
        c = registrada()
        contexto(cobra)
        numero = pedir(cobra, c, p, cantidad=1, cupon=CODIGO).json()["numero"]
        uso = UsoCupon.objects.sin_ambito().get()
        assert uso.estado == "RESERVADO" and uso.monto == Decimal("23.60")
        assert pagar_pedido(c, numero).status_code == 200
        uso.refresh_from_db()
        assert uso.estado == "CONSUMIDO"
        # un pedido nuevo con el cupón que vence sin pagar: el uso se libera
        n2 = pedir(cobra, c, p, cantidad=1, cupon=CODIGO).json()["numero"]
        PedidoTienda.objects.sin_ambito().filter(numero=n2).update(
            expira_en=timezone.now() - timedelta(minutes=1)
        )
        from apps.tienda import pedidos

        assert pedidos.expirar_vencidos() >= 1
        assert UsoCupon.objects.sin_ambito().get(pedido__numero=n2).estado == "LIBERADO"

    def test_el_cupon_se_cobra_con_el_precio_rebajado_y_la_venta_coincide(self, cobra, culqi_falso):
        hacer_cupon(cobra)
        contexto(cobra)
        p = cobra.publicar("Mouse", costo=Decimal("40"), precio=100, stock=10)
        c = registrada()
        contexto(cobra)
        numero = pedir(cobra, c, p, cantidad=1, cupon=CODIGO).json()["numero"]
        assert pagar_pedido(c, numero).status_code == 200
        pedido = PedidoTienda.objects.sin_ambito().get(numero=numero)
        assert pedido.estado == "PAGADO" and pedido.descuento_cupon == Decimal("23.60")
        # Culqi cobró el total CON el descuento (94.40 + envío 11.80)
        assert culqi_falso.cobros[0]["amount"] == 10620
