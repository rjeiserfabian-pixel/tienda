"""Carrito y resumen de la compra: precios y stock vigentes, entrega y carrito guardado."""

# ruff: noqa: F811

from decimal import Decimal

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import CLAVE, nuevo_cliente, registrada

pytestmark = pytest.mark.django_db

CALCULAR = "/api/v1/tienda/carrito/calcular"
COTIZAR = "/api/v1/tienda/compra/cotizar"
GUARDADO = "/api/v1/tienda/cuenta/carrito"
ENVIOS = "/api/v1/tienda/admin/envios/"
MIRAFLORES = "150122"


def contexto(tienda):
    """Las llamadas a la API limpian el contexto: se vuelve a fijar para preparar datos."""
    from apps.core.tenant import establecer_contexto

    e = tienda.e
    establecer_contexto(tienda.org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)


def anonimo() -> APIClient:
    return APIClient(HTTP_X_REQUESTED_WITH="tienda")


def lineas(*pares):
    return {"lineas": [{"producto": p.pk, "cantidad": c} for p, c in pares]}


def zona_lima():
    r = cliente_de("admin").post(
        ENVIOS + "zonas/",
        {
            "nombre": "Lima",
            "modalidad": "TIENDA",
            "tarifas": [{"hasta_kg": "2", "costo": "10"}, {"hasta_kg": "5", "costo": "15"}],
            "coberturas": ["1501"],
            "envio_gratis_desde": "1000",
        },
        format="json",
    )
    assert r.status_code == 201, r.content


class TestCalcular:
    def test_precios_y_totales_salen_del_servidor(self, tienda):
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        laptop = tienda.publicar("Laptop", precio=2000, stock=3)
        r = anonimo().post(CALCULAR, lineas((mouse, 2), (laptop, 1)), format="json").json()
        assert [ln["cantidad"] for ln in r["lineas"]] == [2, 1]
        unitario = Decimal(r["lineas"][0]["precio_unitario"])
        assert unitario >= 50 and Decimal(r["lineas"][0]["subtotal"]) == unitario * 2
        assert Decimal(r["subtotal"]) == sum(Decimal(ln["subtotal"]) for ln in r["lineas"])
        assert r["puede_comprar"] is True and r["problemas"] == 0

    def test_el_precio_que_manda_el_navegador_no_cuenta(self, tienda):
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        cuerpo = {"lineas": [{"producto": mouse.pk, "cantidad": 1, "precio": "0.01"}]}
        r = anonimo().post(CALCULAR, cuerpo, format="json").json()
        assert Decimal(r["lineas"][0]["precio_unitario"]) >= 50

    def test_avisa_si_pide_mas_de_lo_que_hay_o_esta_agotado(self, tienda):
        poco = tienda.publicar("Poco", precio=10, stock=2)
        nada = tienda.publicar("Nada", precio=10, stock=0)
        r = anonimo().post(CALCULAR, lineas((poco, 5), (nada, 1)), format="json").json()
        assert "Solo quedan 2" in r["lineas"][0]["problema"] and r["lineas"][0]["stock_maximo"] == 2
        assert "agotó" in r["lineas"][1]["problema"]
        assert r["puede_comprar"] is False and r["problemas"] == 2

    def test_producto_sin_precio_no_se_puede_comprar(self, tienda):
        sin = tienda.publicar("Sin precio", stock=3)
        r = anonimo().post(CALCULAR, lineas((sin, 1)), format="json").json()
        assert "cotización" in r["lineas"][0]["problema"] and r["puede_comprar"] is False

    def test_lo_no_publicado_o_de_otra_organizacion_se_quita(self, tienda):
        oculto = tienda.publicar("Oculto", precio=10, stock=3, publicado=False)
        visible = tienda.publicar("Visible", precio=10, stock=3)
        r = anonimo().post(CALCULAR, lineas((oculto, 1), (visible, 1)), format="json").json()
        assert [ln["producto"] for ln in r["lineas"]] == [visible.pk]
        assert r["quitados"] == [oculto.pk]
        assert anonimo().post(
            CALCULAR, {"lineas": [{"producto": 999999, "cantidad": 1}]}, format="json"
        ).json()["quitados"] == [999999]

    def test_junta_repetidos_y_limita_la_cantidad(self, tienda):
        mouse = tienda.publicar("Mouse", precio=10, stock=500)
        cuerpo = {
            "lineas": [
                {"producto": mouse.pk, "cantidad": 60},
                {"producto": mouse.pk, "cantidad": 60},
            ]
        }
        r = anonimo().post(CALCULAR, cuerpo, format="json").json()
        assert len(r["lineas"]) == 1 and r["lineas"][0]["cantidad"] == 99

    @pytest.mark.parametrize(
        "cuerpo",
        [
            {"lineas": [{"producto": 1, "cantidad": 0}]},
            {"lineas": [{"producto": "x", "cantidad": 1}]},
            {"lineas": [{"producto": 1, "cantidad": 1000}]},
            {"lineas": "no es lista"},
            {"lineas": [{"producto": i, "cantidad": 1} for i in range(1, 140)]},
        ],
    )
    def test_rechaza_carritos_mal_formados(self, tienda, cuerpo):
        assert anonimo().post(CALCULAR, cuerpo, format="json").status_code == 400

    def test_pide_la_cabecera_anti_csrf_y_no_se_guarda_en_cache(self, tienda):
        assert APIClient().post(CALCULAR, {"lineas": []}, format="json").status_code == 403
        r = anonimo().post(CALCULAR, {"lineas": []}, format="json")
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        assert r.json()["puede_comprar"] is False

    def test_el_stock_nuevo_se_ve_de_inmediato(self, tienda):
        from apps.tienda import catalogo

        mouse = tienda.publicar("Mouse", precio=10, stock=1)
        assert anonimo().post(CALCULAR, lineas((mouse, 2)), format="json").json()["problemas"] == 1
        catalogo.invalidar()
        contexto(tienda)
        from apps.inventario.tests.conftest import comprar as comprar_stock

        comprar_stock(tienda.e, mouse, 5, 1)
        assert anonimo().post(CALCULAR, lineas((mouse, 2)), format="json").json()["problemas"] == 0


class TestResumen:
    def test_envio_a_domicilio_suma_el_costo_segun_el_peso(self, tienda):
        zona_lima()
        contexto(tienda)
        mouse = tienda.publicar("Mouse", precio=50, stock=10, peso_kg=Decimal("1.5"))
        r = (
            anonimo()
            .post(
                COTIZAR,
                {**lineas((mouse, 1)), "modalidad": "ENVIO", "ubigeo": MIRAFLORES},
                format="json",
            )
            .json()
        )
        assert r["entrega"]["valida"] is True and r["costo_envio"] == "10.00"
        assert Decimal(r["total"]) == Decimal(r["subtotal"]) + 10
        assert r["puede_continuar"] is True and r["nota_pago"] is None

    def test_envio_gratis_por_monto(self, tienda):
        zona_lima()
        contexto(tienda)
        laptop = tienda.publicar("Laptop", precio=1500, stock=3)
        r = (
            anonimo()
            .post(
                COTIZAR,
                {**lineas((laptop, 1)), "modalidad": "ENVIO", "ubigeo": MIRAFLORES},
                format="json",
            )
            .json()
        )
        assert r["costo_envio"] == "0.00" and r["entrega"]["envio"]["gratis"] is True

    def test_lugar_sin_cobertura_bloquea_el_envio(self, tienda):
        zona_lima()
        contexto(tienda)
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        r = (
            anonimo()
            .post(
                COTIZAR,
                {**lineas((mouse, 1)), "modalidad": "ENVIO", "ubigeo": "210101"},
                format="json",
            )
            .json()
        )
        assert r["entrega"]["valida"] is False and r["puede_continuar"] is False
        assert "recoger" in r["entrega"]["motivo"]

    def test_agencia_no_suma_flete_y_lo_explica(self, tienda):
        cliente_de("admin").post(
            ENVIOS + "zonas/",
            {"nombre": "Provincias", "modalidad": "DESTINO", "coberturas": ["21"]},
            format="json",
        )
        contexto(tienda)
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        r = (
            anonimo()
            .post(
                COTIZAR,
                {**lineas((mouse, 1)), "modalidad": "ENVIO", "ubigeo": "210101"},
                format="json",
            )
            .json()
        )
        assert r["costo_envio"] == "0.00" and r["total"] == r["subtotal"]
        assert "agencia" in r["nota_pago"] and r["entrega"]["envio"]["paga_en_destino"] is True

    def test_recojo_exige_un_punto_con_todo_el_pedido(self, tienda):
        e = tienda.e
        punto = (
            cliente_de("admin")
            .post(
                ENVIOS + "puntos/",
                {"nombre": "Centro", "direccion": "Av. 1", "almacenes": [e.alm1.pk]},
                format="json",
            )
            .json()["puntos"][0]
        )
        contexto(tienda)
        mouse = tienda.publicar("Mouse", precio=50, stock=3)

        def pide(cantidad, **extra):
            cuerpo = {**lineas((mouse, cantidad)), "modalidad": "RECOJO", **extra}
            return anonimo().post(COTIZAR, cuerpo, format="json").json()

        sin_elegir = pide(1)
        assert (
            sin_elegir["entrega"]["valida"] is False
            and "Elige la tienda" in sin_elegir["entrega"]["motivo"]
        )
        assert pide(1, punto=punto["id"])["puede_continuar"] is True
        falta = pide(4, punto=punto["id"])
        assert falta["entrega"]["valida"] is False and falta["puede_continuar"] is False

    def test_modalidad_invalida(self, tienda):
        assert (
            anonimo().post(COTIZAR, {"lineas": [], "modalidad": "DRON"}, format="json").status_code
            == 400
        )

    def test_usa_la_direccion_guardada_solo_con_sesion_y_solo_las_propias(self, tienda):
        zona_lima()
        contexto(tienda)
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        ana = registrada()
        direccion = ana.post(
            "/api/v1/tienda/cuenta/direcciones",
            {"receptor": "Ana", "celular": "987654321", "ubigeo": MIRAFLORES, "direccion": "Av. 1"},
            format="json",
        ).json()[0]
        cuerpo = {**lineas((mouse, 1)), "modalidad": "ENVIO", "direccion": direccion["id"]}
        ok = ana.post(COTIZAR, cuerpo, format="json").json()
        assert ok["entrega"]["valida"] is True and ok["cuenta"] == {
            "autenticada": True,
            "correo_verificado": True,
        }
        assert anonimo().post(COTIZAR, cuerpo, format="json").status_code == 400
        luis = registrada(correo="luis@ejemplo.pe")
        assert luis.post(COTIZAR, cuerpo, format="json").status_code == 400

    def test_informa_si_el_correo_esta_sin_confirmar(self, tienda):
        c = registrada(verificar=False)
        r = c.post(COTIZAR, {"lineas": []}, format="json").json()
        assert r["cuenta"] == {"autenticada": True, "correo_verificado": False}
        assert (
            anonimo().post(COTIZAR, {"lineas": []}, format="json").json()["cuenta"]["autenticada"]
            is False
        )


class TestCarritoGuardado:
    def test_guarda_y_recupera_el_carrito_de_la_cuenta(self, tienda):
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        ana = registrada()
        assert ana.get(GUARDADO).json()["lineas"] == []
        r = ana.put(GUARDADO, lineas((mouse, 3)), format="json").json()
        assert r["lineas"][0]["cantidad"] == 3
        otro_equipo = nuevo_cliente()
        otro_equipo.post(
            "/api/v1/tienda/cuenta/ingresar",
            {"correo": "ana@ejemplo.pe", "password": CLAVE},
            format="json",
        )
        assert otro_equipo.get(GUARDADO).json()["lineas"][0]["cantidad"] == 3

    def test_cada_cuenta_ve_solo_su_carrito(self, tienda):
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        ana = registrada()
        ana.put(GUARDADO, lineas((mouse, 2)), format="json")
        luis = registrada(correo="luis@ejemplo.pe")
        assert luis.get(GUARDADO).json()["lineas"] == []

    def test_requiere_sesion(self, tienda):
        assert anonimo().get(GUARDADO).status_code == 401
        assert anonimo().put(GUARDADO, {"lineas": []}, format="json").status_code == 401

    def test_vaciar_el_carrito(self, tienda):
        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        ana = registrada()
        ana.put(GUARDADO, lineas((mouse, 2)), format="json")
        assert ana.put(GUARDADO, {"lineas": []}, format="json").json()["lineas"] == []
        assert ana.get(GUARDADO).json()["lineas"] == []

    def test_un_producto_que_dejo_de_venderse_sale_del_carrito_guardado(self, tienda):
        from apps.mantenimiento.models import Producto

        mouse = tienda.publicar("Mouse", precio=50, stock=10)
        ana = registrada()
        ana.put(GUARDADO, lineas((mouse, 2)), format="json")
        Producto.objects.sin_ambito().filter(pk=mouse.pk).update(publicado_web=False)
        from django.core.cache import cache

        cache.clear()
        r = ana.get(GUARDADO).json()
        assert r["lineas"] == [] and r["quitados"] == [mouse.pk]
        assert len(mail.outbox) >= 0


class TestSeries:
    def test_un_producto_con_serie_sin_series_en_stock_se_muestra_agotado(self, tienda):
        from apps.mantenimiento.models import Producto

        con_serie = tienda.publicar("Laptop serie", precio=1000, stock=3)
        # Tiene saldo pero ninguna serie registrada en stock: no se puede asignar una unidad.
        Producto.objects.sin_ambito().filter(pk=con_serie.pk).update(lleva_serie=True)
        r = anonimo().post(CALCULAR, lineas((con_serie, 1)), format="json").json()
        assert "agotó" in r["lineas"][0]["problema"] and r["puede_comprar"] is False
