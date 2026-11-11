"""Pedidos de la tienda: importes del motor de Ventas, reserva de stock, vencimiento y API."""

# ruff: noqa: F811

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import TipoComprobante
from apps.organizacion.models import ConfiguracionEmpresa, Empresa
from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import catalogo, pedidos
from apps.tienda.models import PedidoTienda, ReservaStock, ZonaEnvio

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import nuevo_cliente, registrada

pytestmark = pytest.mark.django_db

PEDIDOS = "/api/v1/tienda/pedidos"
COTIZAR = "/api/v1/tienda/compra/cotizar"
ENVIOS = "/api/v1/tienda/admin/envios/"
MIRAFLORES, IQUITOS, PUNO = "150122", "160101", "210101"


def contexto(tienda):
    e = tienda.e
    establecer_contexto(tienda.org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)


@pytest.fixture
def vende(tienda):
    """La tienda lista para vender: empresa principal, series de boleta y factura, zonas y punto."""
    from apps.mantenimiento.models import SerieComprobante

    e = tienda.e
    Empresa.objects.sin_ambito().filter(pk=e.e1.pk).update(es_principal=True)
    for empresa, sufijo in ((e.e1, "1"), (e.e2, "2")):
        for codigo, prefijo in (("01", "F"), ("03", "B")):
            SerieComprobante.objects.sin_ambito().get_or_create(
                empresa=empresa,
                tipo_comprobante=TipoComprobante.objects.sin_ambito().get(
                    organizacion=tienda.org, codigo=codigo
                ),
                defaults={"serie": f"{prefijo}00{sufijo}", "es_electronica": True},
            )
    admin = cliente_de("admin")
    r = admin.post(
        ENVIOS + "zonas/",
        {
            "nombre": "Lima",
            "modalidad": "TIENDA",
            "tarifas": [{"hasta_kg": "5", "costo": "11.80"}, {"hasta_kg": "20", "costo": "20"}],
            "coberturas": ["1501", "16"],
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    admin.post(
        ENVIOS + "zonas/",
        {"nombre": "Provincias", "modalidad": "DESTINO", "coberturas": ["21"]},
        format="json",
    )
    admin.post(
        ENVIOS + "puntos/",
        {"nombre": "Centro", "direccion": "Av. 1", "almacenes": [e.alm1.pk]},
        format="json",
    )
    contexto(tienda)
    return tienda


def amazonia(tienda):
    for empresa in (tienda.e.e1, tienda.e.e2):
        fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=empresa)
        fila.regimen_igv = "AMAZONIA"
        fila.save()


def cuerpo(*pares, modalidad="ENVIO", **extra):
    return {
        "lineas": [{"producto": p.pk, "cantidad": c} for p, c in pares],
        "modalidad": modalidad,
        "clave_idempotencia": str(uuid.uuid4()),
        **extra,
    }


def con_direccion(cliente, ubigeo=MIRAFLORES):
    r = cliente.post(
        "/api/v1/tienda/cuenta/direcciones",
        {"receptor": "Ana", "celular": "987654321", "ubigeo": ubigeo, "direccion": "Av. Sol 100"},
        format="json",
    )
    assert r.status_code == 201, r.content
    return r.json()[0]["id"]


def pedido_de_prueba(vende, cliente=None, *, stock=10, cantidad=1, **extra):
    contexto(vende)
    p = vende.publicar("Mouse", precio=100, stock=stock, peso_kg=Decimal("0.5"))
    cliente = cliente or registrada()
    d = con_direccion(cliente)
    r = cliente.post(PEDIDOS, cuerpo((p, cantidad), direccion=d, **extra), format="json")
    return p, cliente, r


class TestImportes:
    def test_precio_mas_igv_y_envio_como_linea(self, vende):
        p, c, r = pedido_de_prueba(vende, cantidad=2)
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["numero"] == "T-000001" and d["estado"] == "PENDIENTE_PAGO"
        # 2 × 100 + 18% = 236.00; el envío (11.80) ya trae su IGV: total 247.80
        assert d["importes"]["subtotal_productos"] == "236.00"
        assert d["importes"]["costo_envio"] == "11.80"
        assert d["importes"]["total"] == "247.80" and d["importes"]["igv"] == "37.80"
        assert d["importes"]["igv_exonerado"] is False
        envio = [ln for ln in d["lineas"] if ln["es_envio"]]
        assert len(envio) == 1 and envio[0]["total"] == "11.80"

    def test_la_amazonia_exonera_el_igv_y_el_total_baja(self, vende):
        amazonia(vende)
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10, peso_kg=Decimal("0.5"))
        c = registrada()
        d = con_direccion(c, IQUITOS)
        r = c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json").json()
        assert r["importes"]["subtotal_productos"] == "100.00" and r["importes"]["igv"] == "0.00"
        assert r["importes"]["igv_exonerado"] is True and "Amazonía" in r["importes"]["motivo_igv"]
        assert r["importes"]["costo_envio"] == "11.80"  # la tarifa es el monto final
        assert r["importes"]["total"] == "111.80"

    def test_fuera_de_la_amazonia_con_empresas_amazonia_si_se_grava(self, vende):
        amazonia(vende)
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10, peso_kg=Decimal("0.5"))
        c = registrada()
        d = con_direccion(c, MIRAFLORES)
        r = c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json").json()
        assert r["importes"]["subtotal_productos"] == "118.00"
        assert r["importes"]["igv_exonerado"] is False

    def test_recojo_sin_costo_de_envio(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=5)
        c = registrada()
        punto = cliente_de("admin").get(ENVIOS).json()["puntos"][0]["id"]
        r = c.post(PEDIDOS, cuerpo((p, 1), modalidad="RECOJO", punto=punto), format="json").json()
        assert r["importes"]["costo_envio"] == "0.00" and r["importes"]["total"] == "118.00"
        assert r["entrega"]["punto"] == "Centro"

    def test_agencia_no_suma_flete(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=5)
        c = registrada()
        d = con_direccion(c, PUNO)
        r = c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json").json()
        assert r["importes"]["costo_envio"] == "0.00" and r["entrega"]["paga_en_destino"] is True

    def test_cotizar_devuelve_los_totales_exactos_del_motor(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=5, peso_kg=Decimal("0.5"))
        r = (
            APIClient(HTTP_X_REQUESTED_WITH="tienda")
            .post(
                COTIZAR,
                {**cuerpo((p, 1)), "ubigeo": MIRAFLORES},
                format="json",
            )
            .json()
        )
        assert r["totales_error"] is None
        t = r["totales"]
        assert t["total"] == "129.80" and t["igv"] == "19.80" and t["igv_exonerado"] is False
        assert t["por_empresa"][0]["total"] == "129.80"
        assert r["entrega"]["valida"] is True  # lo anterior no cambia


class TestComprobante:
    def test_factura_exige_ruc_razon_social_y_direccion(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=5)
        c = registrada()
        d = con_direccion(c)
        base = cuerpo((p, 1), direccion=d)
        malo = c.post(PEDIDOS, {**base, "comprobante": {"tipo": "01"}}, format="json")
        assert malo.status_code == 400 and "RUC" in malo.json()["error"]["mensaje"]
        ok = c.post(
            PEDIDOS,
            {
                **base,
                "comprobante": {
                    "tipo": "01",
                    "documento_tipo": "RUC",
                    "documento_numero": "20100000017",
                    "nombre": "Mi Empresa SAC",
                    "direccion_fiscal": "Jr. Uno 123",
                },
            },
            format="json",
        )
        assert ok.status_code == 201, ok.content
        assert ok.json()["comprobante"]["nombre"] == "Mi Empresa SAC"

    def test_boleta_grande_sin_dni_se_rechaza_y_con_dni_pasa(self, vende):
        contexto(vende)
        p = vende.publicar("Laptop", precio=2000, stock=3)
        c = registrada()
        d = con_direccion(c)
        base = cuerpo((p, 1), direccion=d)
        sin = c.post(PEDIDOS, base, format="json")
        assert sin.status_code == 400 and "DNI" in sin.json()["error"]["mensaje"]
        con = c.post(
            PEDIDOS,
            {
                **base,
                "comprobante": {
                    "documento_tipo": "DNI",
                    "documento_numero": "12345678",
                    "nombre": "Ana",
                },
            },
            format="json",
        )
        assert con.status_code == 201, con.content

    def test_documento_invalido(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=5)
        c = registrada()
        d = con_direccion(c)
        r = c.post(
            PEDIDOS,
            {
                **cuerpo((p, 1), direccion=d),
                "comprobante": {"documento_tipo": "DNI", "documento_numero": "12"},
            },
            format="json",
        )
        assert r.status_code == 400

    def test_sin_serie_de_comprobante_avisa_con_claridad(self, tienda):
        contexto(tienda)
        Empresa.objects.sin_ambito().filter(pk=tienda.e.e1.pk).update(es_principal=True)
        cliente_de("admin").post(
            ENVIOS + "puntos/",
            {"nombre": "Centro", "direccion": "Av. 1", "almacenes": [tienda.e.alm1.pk]},
            format="json",
        )
        contexto(tienda)
        p = tienda.publicar("Mouse", precio=100, stock=5)
        c = registrada()
        punto = cliente_de("admin").get(ENVIOS).json()["puntos"][0]["id"]
        r = c.post(PEDIDOS, cuerpo((p, 1), modalidad="RECOJO", punto=punto), format="json")
        assert r.status_code == 400 and "serie" in r.json()["error"]["mensaje"].lower()


class TestReservaDeStock:
    def test_el_pedido_aparta_el_stock_y_baja_lo_que_se_ofrece(self, vende):
        p, c, r = pedido_de_prueba(vende, stock=5, cantidad=3)
        assert r.status_code == 201
        reserva = ReservaStock.objects.sin_ambito().get()
        assert reserva.cantidad == 3 and reserva.liberada_en is None
        contexto(vende)
        catalogo.invalidar()
        ctx = catalogo.contexto()
        disponible = catalogo.productos_publicos(ctx).get(pk=p.pk).stock_web
        assert disponible == 2  # 5 - 3 apartados
        # otro cliente ya no puede pedir más de lo que queda
        otro = registrada(correo="luis@ejemplo.pe")
        d2 = con_direccion(otro)
        r2 = otro.post(PEDIDOS, cuerpo((p, 3), direccion=d2), format="json")
        assert r2.status_code == 400

    def test_cancelar_libera_el_stock(self, vende):
        p, c, r = pedido_de_prueba(vende, stock=5, cantidad=3)
        numero = r.json()["numero"]
        out = c.post(f"{PEDIDOS}/{numero}/cancelar", {}, format="json")
        assert out.status_code == 200 and out.json()["estado"] == "CANCELADO"
        assert ReservaStock.objects.sin_ambito().get().liberada_en is not None
        assert c.post(f"{PEDIDOS}/{numero}/cancelar", {}, format="json").status_code == 409
        contexto(vende)
        catalogo.invalidar()
        assert catalogo.productos_publicos(catalogo.contexto()).get(pk=p.pk).stock_web == 5

    def test_los_pedidos_sin_pagar_vencen_y_sueltan_el_stock(self, vende):
        p, c, r = pedido_de_prueba(vende, stock=5, cantidad=2)
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(minutes=1))
        assert pedidos.expirar_vencidos() == 1
        assert PedidoTienda.objects.sin_ambito().get().estado == "EXPIRADO"
        assert ReservaStock.objects.sin_ambito().get().liberada_en is not None
        assert pedidos.expirar_vencidos() == 0

    def test_la_tarea_vence_pedidos(self, vende):
        from apps.tienda.tasks import expirar_pedidos

        pedido_de_prueba(vende, stock=5)
        PedidoTienda.objects.sin_ambito().update(expira_en=timezone.now() - timedelta(minutes=1))
        assert expirar_pedidos() == 1

    def test_un_pedido_pagado_no_vence(self, vende):
        pedido_de_prueba(vende, stock=5)
        PedidoTienda.objects.sin_ambito().update(
            expira_en=timezone.now() - timedelta(minutes=1), estado="PAGADO"
        )
        assert pedidos.expirar_vencidos() == 0

    def test_cada_linea_sale_completa_de_una_sola_empresa(self, vende):
        from apps.inventario.tests.conftest import comprar as comprar_stock

        e = vende.e
        contexto(vende)
        p = vende.publicar("Cable", precio=10, stock=2)  # 2 en la principal
        comprar_stock(e, p, 3, 1, empresa=e.e2, almacen=e.alm2)  # y 3 en la otra
        c = registrada()
        d = con_direccion(c)
        contexto(vende)
        r = c.post(PEDIDOS, cuerpo((p, 3), direccion=d), format="json")
        assert r.status_code == 201, r.content
        linea = pedidos.LineaPedido.objects.sin_ambito().get(es_envio=False)
        assert linea.empresa_id == e.e2.pk  # la principal no tenía las 3: sale entera de la otra
        # pedir 5 no se puede aunque entre las dos sumen 5: ninguna tiene las 5
        r2 = c.post(PEDIDOS, cuerpo((p, 5), direccion=d), format="json")
        assert r2.status_code == 400

    def test_con_stock_en_la_principal_surte_la_principal(self, vende):
        p, c, r = pedido_de_prueba(vende, stock=5, cantidad=2)
        linea = pedidos.LineaPedido.objects.sin_ambito().get(es_envio=False)
        assert linea.empresa_id == vende.e.e1.pk


class TestIdempotenciaYLimites:
    def test_la_misma_clave_devuelve_el_mismo_pedido(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10, peso_kg=Decimal("0.5"))
        c = registrada()
        d = con_direccion(c)
        datos = cuerpo((p, 1), direccion=d)
        a = c.post(PEDIDOS, datos, format="json")
        b = c.post(PEDIDOS, datos, format="json")
        assert a.status_code == 201 and b.status_code == 200
        assert a.json()["numero"] == b.json()["numero"]
        assert PedidoTienda.objects.sin_ambito().count() == 1
        assert ReservaStock.objects.sin_ambito().count() == 1

    def test_los_numeros_son_correlativos(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10, peso_kg=Decimal("0.5"))
        c = registrada()
        d = con_direccion(c)
        n = [
            c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json").json()["numero"]
            for _ in range(2)
        ]
        assert n == ["T-000001", "T-000002"]

    def test_tope_de_pedidos_sin_pagar(self, vende, settings):
        settings.TIENDA_PEDIDOS_PENDIENTES_MAX = 2
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10, peso_kg=Decimal("0.5"))
        c = registrada()
        d = con_direccion(c)
        for _ in range(2):
            assert c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json").status_code == 201
        assert c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json").status_code == 400

    def test_correo_sin_confirmar_no_compra(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10)
        c = registrada(verificar=False)
        d = con_direccion(c)
        r = c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json")
        assert r.status_code == 403 and r.json()["error"]["codigo"] == "correo_sin_confirmar"
        assert len(mail.outbox) >= 1


class TestSeguridad:
    def test_cada_cliente_ve_solo_sus_pedidos(self, vende):
        p, ana, r = pedido_de_prueba(vende)
        numero = r.json()["numero"]
        luis = registrada(correo="luis@ejemplo.pe")
        assert luis.get(PEDIDOS).json()["count"] == 0
        assert luis.get(f"{PEDIDOS}/{numero}").status_code == 404
        assert luis.post(f"{PEDIDOS}/{numero}/cancelar", {}, format="json").status_code == 404
        assert ana.get(f"{PEDIDOS}/{numero}").status_code == 200
        lista = ana.get(PEDIDOS).json()
        assert lista["count"] == 1 and lista["results"][0]["numero"] == numero

    def test_requiere_sesion_y_cabecera(self, vende):
        assert nuevo_cliente().get(PEDIDOS).status_code == 401
        assert nuevo_cliente().post(PEDIDOS, {}, format="json").status_code == 401
        assert APIClient().post(PEDIDOS, {}, format="json").status_code == 403

    def test_no_se_usa_la_direccion_de_otro_cliente(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10)
        ana = registrada()
        d_ana = con_direccion(ana)
        luis = registrada(correo="luis@ejemplo.pe")
        r = luis.post(PEDIDOS, cuerpo((p, 1), direccion=d_ana), format="json")
        assert r.status_code == 400

    def test_el_precio_del_navegador_no_cuenta(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10, peso_kg=Decimal("0.5"))
        c = registrada()
        d = con_direccion(c)
        datos = cuerpo((p, 1), direccion=d)
        datos["lineas"][0]["precio"] = "0.01"
        r = c.post(PEDIDOS, datos, format="json")
        assert r.status_code == 201 and r.json()["importes"]["subtotal_productos"] == "118.00"

    def test_producto_no_publicado_o_cantidad_invalida(self, vende):
        contexto(vende)
        oculto = vende.publicar("Oculto", precio=10, stock=5, publicado=False)
        c = registrada()
        d = con_direccion(c)
        assert c.post(PEDIDOS, cuerpo((oculto, 1), direccion=d), format="json").status_code == 400
        assert c.post(PEDIDOS, {**cuerpo(direccion=d)}, format="json").status_code == 400
        bad = {**cuerpo((oculto, 1), direccion=d), "clave_idempotencia": "no-es-uuid"}
        assert c.post(PEDIDOS, bad, format="json").status_code == 400

    def test_lugar_sin_cobertura(self, vende):
        contexto(vende)
        p = vende.publicar("Mouse", precio=100, stock=10)
        c = registrada()
        d = con_direccion(c, "040101")  # Arequipa: sin zona
        r = c.post(PEDIDOS, cuerpo((p, 1), direccion=d), format="json")
        assert r.status_code == 400 and "llegamos" in r.json()["error"]["mensaje"]


class TestEnvioProducto:
    def test_el_producto_de_envio_se_crea_una_vez_y_no_se_publica(self, vende):
        from apps.mantenimiento.models import Producto

        _, c, _ = pedido_de_prueba(vende, stock=5)
        pedido_de_prueba(vende, c, stock=5)
        envios = Producto.objects.sin_ambito().filter(nombre=pedidos.NOMBRE_ENVIO)
        assert envios.count() == 1 and envios.get().publicado_web is False
        assert ZonaEnvio.objects.sin_ambito().exists()
