"""API de órdenes de compra: permisos, idempotencia, estados, configuración y recepción."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auditoria.models import AuditoriaEvento
from apps.compras.models import Compra, OrdenCompra
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)
from .test_api import clave, cuerpo, datos, registrar  # noqa: F401

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras"
_numeros = itertools.count(5000)


def cuerpo_orden(datos, producto=None, **extra):
    producto = producto or datos.mundo.producto()
    base = {
        "empresa": datos.mundo.e1.pk,
        "proveedor": datos.proveedor.pk,
        "almacen": datos.mundo.alm[1].pk,
        "fecha_emision": timezone.localdate().isoformat(),
        "lineas": [{"producto": producto.pk, "cantidad": "10", "precio_unitario": "10"}],
    }
    return {**base, **extra}


def crear(datos, usuario="almacenero", llave=None, **extra):
    return cliente_de(usuario).post(
        f"{BASE}/ordenes/",
        cuerpo_orden(datos, **extra),
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or clave(),
    )


def nueva(datos, usuario="almacenero", **extra):
    r = crear(datos, usuario, **extra)
    assert r.status_code == 201, r.content
    return r.json()


def accion(usuario, orden_id, nombre, cuerpo_=None, llave=None):
    api = cliente_de(usuario)
    extra = {"HTTP_IDEMPOTENCY_KEY": llave or clave()} if nombre == "emitir" else {}
    return api.post(f"{BASE}/ordenes/{orden_id}/{nombre}/", cuerpo_ or {}, format="json", **extra)


def configurar(usuario="admin", empresa=None, **valores):
    return cliente_de(usuario).patch(
        f"{BASE}/ordenes/configuracion/", {"empresa": empresa, **valores}, format="json"
    )


class TestCrear:
    def test_crea_en_borrador_y_responde_el_detalle(self, datos):
        r = crear(datos)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["codigo"], d["estado"], d["total"], d["total_soles"]) == (
            "OC-000001",
            "BORRADOR",
            "118.00",
            "118.00",
        )
        assert (d["op_gravada"], d["igv"], d["forma_pago"], d["plazo_dias"]) == (
            "100.00",
            "18.00",
            "CONTADO",
            0,
        )
        assert d["proveedor_nombre"] == "Distribuidora Selva"
        assert d["emisor"]["ruc"] == datos.mundo.e1.ruc and d["emisor"]["nombre"]
        assert d["proveedor_datos"]["numero_documento"] == datos.proveedor.numero_documento
        assert d["requiere_aprobacion"] is False and d["monto_aprobacion"] is None
        assert d["tolerancia"] == "0.00" and d["atrasada"] is False and d["compras"] == []
        ln = d["lineas"][0]
        assert (ln["cantidad"], ln["cantidad_recibida"], ln["pendiente"]) == (
            "10.000",
            "0.000",
            "10.000",
        )
        assert (ln["precio_unitario"], ln["total"], ln["maximo_recibible"]) == (
            "10.000000",
            "118.00",
            "10.000",
        )

    def test_reintento_con_la_misma_clave_no_duplica(self, datos):
        llave, producto = clave(), datos.mundo.producto()
        primera = crear(datos, llave=llave, producto=producto)
        segunda = crear(datos, llave=llave, producto=producto)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda.json() == primera.json()
        assert segunda["Idempotency-Replayed"] == "true"
        assert OrdenCompra.objects.sin_ambito().count() == 1

    def test_sin_clave_no_crea(self, datos):
        r = cliente_de("almacenero").post(f"{BASE}/ordenes/", cuerpo_orden(datos), format="json")
        assert r.status_code == 400 and OrdenCompra.objects.sin_ambito().count() == 0

    def test_errores_de_negocio_y_de_forma(self, datos):
        api = cliente_de("almacenero")
        for malo in (
            {"lineas": []},
            {"proveedor": 999_999},
            {"almacen": 999_999},
            {"empresa": 999_999},
            {"forma_pago": "CREDITO", "plazo_dias": 0},
            {"fecha_entrega": (timezone.localdate() - timedelta(days=2)).isoformat()},
            {"fecha_emision": (timezone.localdate() + timedelta(days=1)).isoformat()},
        ):
            r = api.post(
                f"{BASE}/ordenes/",
                cuerpo_orden(datos, **malo),
                format="json",
                HTTP_IDEMPOTENCY_KEY=clave(),
            )
            assert r.status_code in (400, 403), malo
        r = api.post(
            f"{BASE}/ordenes/",
            {"empresa": datos.mundo.e1.pk},
            format="json",
            HTTP_IDEMPOTENCY_KEY=clave(),
        )
        assert r.status_code == 400
        assert OrdenCompra.objects.sin_ambito().count() == 0

    def test_permisos(self, datos):
        assert crear(datos, "admin").status_code == 201
        for usuario in ("contador", "vendedor", "vendedor_a2"):
            assert crear(datos, usuario).status_code == 403, usuario
        assert crear(datos, "otra_org").status_code in (400, 403)


class TestConsultar:
    def test_listado_filtros_y_detalle(self, datos):
        a, b = nueva(datos), nueva(datos)
        accion("admin", b["id"], "emitir")
        api = cliente_de("contador")
        e = datos.mundo.e1.pk
        lista = api.get(f"{BASE}/ordenes/?empresa={e}").json()
        assert lista["count"] == 2 and lista["results"][0]["codigo"] == "OC-000002"
        pendientes = api.get(f"{BASE}/ordenes/?empresa={e}&pendientes=1").json()
        assert [x["id"] for x in pendientes["results"]] == [b["id"]]
        borradores = api.get(f"{BASE}/ordenes/?empresa={e}&estado=BORRADOR").json()
        assert [x["id"] for x in borradores["results"]] == [a["id"]]
        por_numero = api.get(f"{BASE}/ordenes/?empresa={e}&q=OC-000001").json()
        assert [x["id"] for x in por_numero["results"]] == [a["id"]]
        por_proveedor = api.get(f"{BASE}/ordenes/?empresa={e}&q=selva").json()
        assert por_proveedor["count"] == 2
        assert api.get(f"{BASE}/ordenes/{a['id']}/").json()["codigo"] == "OC-000001"

    def test_atrasadas(self, datos):
        ayer = (timezone.localdate() - timedelta(days=1)).isoformat()
        antes = (timezone.localdate() - timedelta(days=5)).isoformat()
        vencida = nueva(datos, fecha_emision=antes, fecha_entrega=ayer)
        accion("admin", vencida["id"], "emitir")
        a_tiempo = nueva(
            datos, fecha_entrega=(timezone.localdate() + timedelta(days=3)).isoformat()
        )
        accion("admin", a_tiempo["id"], "emitir")
        borrador_vencido = nueva(datos, fecha_emision=antes, fecha_entrega=ayer)
        e = datos.mundo.e1.pk
        r = cliente_de("admin").get(f"{BASE}/ordenes/?empresa={e}&atrasadas=1").json()
        assert [x["id"] for x in r["results"]] == [vencida["id"]]
        assert r["results"][0]["atrasada"] is True
        assert borrador_vencido["atrasada"] is False

    def test_el_listado_pide_empresa_y_permiso(self, datos):
        assert cliente_de("admin").get(f"{BASE}/ordenes/").status_code == 400
        e = datos.mundo.e1.pk
        assert cliente_de("vendedor").get(f"{BASE}/ordenes/?empresa={e}").status_code == 403

    def test_aislamiento(self, datos):
        o = nueva(datos)
        for usuario in ("vendedor_a2", "otra_org"):
            assert cliente_de(usuario).get(f"{BASE}/ordenes/{o['id']}/").status_code in (403, 404)
        r = cliente_de("vendedor_a2").get(f"{BASE}/ordenes/?empresa={datos.mundo.e1.pk}")
        assert r.status_code == 403


class TestEditarYCalcular:
    def test_edita_en_borrador(self, datos):
        o = nueva(datos)
        nuevo = datos.mundo.producto("Otro")
        r = cliente_de("almacenero").post(
            f"{BASE}/ordenes/{o['id']}/editar/",
            {
                "proveedor": datos.proveedor.pk,
                "almacen": datos.mundo.alm[1].pk,
                "fecha_emision": timezone.localdate().isoformat(),
                "observacion": "Cambió el pedido",
                "lineas": [{"producto": nuevo.pk, "cantidad": "5", "precio_unitario": "20"}],
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["codigo"], d["total"], d["observacion"]) == (
            "OC-000001",
            "118.00",
            "Cambió el pedido",
        )
        assert [ln["producto"] for ln in d["lineas"]] == [nuevo.pk]

    def test_no_se_edita_una_emitida_ni_sin_permiso(self, datos):
        o = nueva(datos)
        cuerpo_ = cuerpo_orden(datos)
        cuerpo_.pop("empresa")
        assert (
            cliente_de("contador")
            .post(f"{BASE}/ordenes/{o['id']}/editar/", cuerpo_, format="json")
            .status_code
            == 403
        )
        accion("admin", o["id"], "emitir")
        r = cliente_de("admin").post(f"{BASE}/ordenes/{o['id']}/editar/", cuerpo_, format="json")
        assert r.status_code == 409

    def test_calcular_no_guarda_y_avisa_si_pediria_aprobacion(self, datos):
        configurar(empresa=datos.mundo.e1.pk, monto_aprobacion="100.00")
        r = cliente_de("almacenero").post(
            f"{BASE}/ordenes/calcular/", cuerpo_orden(datos), format="json"
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["total"], d["igv"], d["total_soles"]) == ("118.00", "18.00", "118.00")
        assert d["requiere_aprobacion"] is True and d["monto_aprobacion"] == "100.00"
        assert d["lineas"][0]["afectacion_codigo"] == "10"
        assert OrdenCompra.objects.sin_ambito().count() == 0


class TestEstados:
    def test_sin_monto_el_almacenero_emite_directo(self, datos):
        o = nueva(datos)
        r = accion("almacenero", o["id"], "emitir")
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "EMITIDA" and r.json()["emitida_en"]

    def test_con_monto_el_almacenero_envia_a_aprobar_y_el_admin_aprueba(self, datos):
        assert configurar(empresa=datos.mundo.e1.pk, monto_aprobacion="100").status_code == 200
        o = nueva(datos)
        r = accion("almacenero", o["id"], "emitir")
        assert r.json()["estado"] == "PENDIENTE" and r.json()["requiere_aprobacion"] is True
        assert accion("almacenero", o["id"], "aprobar").status_code == 403
        aprobada = accion("admin", o["id"], "aprobar")
        assert aprobada.status_code == 200 and aprobada.json()["estado"] == "EMITIDA"
        assert aprobada.json()["aprobada_en"]

    def test_quien_puede_aprobar_emite_y_queda_aprobada(self, datos):
        configurar(empresa=datos.mundo.e1.pk, monto_aprobacion="100")
        o = nueva(datos)
        r = accion("admin", o["id"], "emitir")
        assert r.json()["estado"] == "EMITIDA" and r.json()["aprobada_en"]

    def test_emitir_es_idempotente(self, datos):
        o = nueva(datos)
        llave = clave()
        primera = accion("almacenero", o["id"], "emitir", llave=llave)
        segunda = accion("almacenero", o["id"], "emitir", llave=llave)
        assert (primera.status_code, segunda.status_code) == (200, 200)
        assert segunda["Idempotency-Replayed"] == "true"
        assert accion("almacenero", o["id"], "emitir").status_code == 409  # otra clave: ya no

    def test_rechazar_y_reabrir(self, datos):
        configurar(empresa=datos.mundo.e1.pk, monto_aprobacion="100")
        o = nueva(datos)
        accion("almacenero", o["id"], "emitir")
        assert accion("admin", o["id"], "rechazar", {}).status_code == 400  # sin motivo
        r = accion("admin", o["id"], "rechazar", {"motivo": "Pide mejor precio"})
        assert (
            r.json()["estado"] == "BORRADOR" and r.json()["motivo_rechazo"] == "Pide mejor precio"
        )
        accion("admin", o["id"], "emitir")
        reabierta = accion("almacenero", o["id"], "reabrir")
        assert reabierta.status_code == 200 and reabierta.json()["estado"] == "BORRADOR"

    def test_anular_con_motivo_y_solo_con_permiso(self, datos):
        o = nueva(datos)
        assert accion("almacenero", o["id"], "anular", {"motivo": "Error"}).status_code == 403
        assert accion("admin", o["id"], "anular", {}).status_code == 400
        r = accion("admin", o["id"], "anular", {"motivo": "El proveedor ya no vende"})
        assert r.json()["estado"] == "ANULADA" and r.json()["motivo_anulacion"]
        assert accion("admin", o["id"], "anular", {"motivo": "Otra vez"}).status_code == 409

    def test_cerrar_solo_una_recibida_en_parte_y_con_permiso(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        assert accion("admin", o["id"], "cerrar", {"motivo": "No entrega más"}).status_code == 409
        recibir(datos, o, "4")
        assert (
            accion("almacenero", o["id"], "cerrar", {"motivo": "No entrega más"}).status_code == 403
        )
        r = accion("admin", o["id"], "cerrar", {"motivo": "No entrega más"})
        assert r.status_code == 200 and r.json()["estado"] == "CERRADA"

    def test_otra_empresa_no_toca_la_orden(self, datos):
        o = nueva(datos)
        for nombre, cuerpo_ in (("emitir", {}), ("anular", {"motivo": "x"}), ("aprobar", {})):
            r = accion("vendedor_a2", o["id"], nombre, cuerpo_)
            assert r.status_code in (403, 404), nombre
        assert OrdenCompra.objects.sin_ambito().get().estado == "BORRADOR"


def recibir(datos, orden, cantidad, precio="10", **extra):
    """Recibe mercadería contra la orden registrando una compra por la API."""
    linea = orden["lineas"][0]
    total = f"{float(cantidad) * float(precio) * 1.18:.2f}"
    c = cuerpo(
        datos,
        fecha_emision=timezone.localdate().isoformat(),
        orden=orden["id"],
        lineas=[{"producto": linea["producto"], "cantidad": cantidad, "precio_unitario": precio}],
        pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": total}],
        **extra,
    )
    return registrar(cliente_de("almacenero"), c)


class TestConfiguracion:
    def test_lee_y_cambia(self, datos):
        e = datos.mundo.e1.pk
        r = cliente_de("admin").get(f"{BASE}/ordenes/configuracion/?empresa={e}")
        assert r.json() == {"empresa": e, "monto_aprobacion": None, "tolerancia": "0.00"}
        r = configurar(empresa=e, monto_aprobacion="500.00", tolerancia="5")
        assert r.status_code == 200
        assert r.json() == {"empresa": e, "monto_aprobacion": "500.00", "tolerancia": "5.00"}
        r = cliente_de("admin").get(f"{BASE}/ordenes/configuracion/?empresa={e}")
        assert r.json()["monto_aprobacion"] == "500.00"
        assert AuditoriaEvento.objects.filter(accion="compras.orden_configuracion").exists()

    def test_se_puede_quitar_el_monto(self, datos):
        e = datos.mundo.e1.pk
        configurar(empresa=e, monto_aprobacion="500")
        r = configurar(empresa=e, monto_aprobacion=None)
        assert r.json()["monto_aprobacion"] is None and r.json()["tolerancia"] == "0.00"

    def test_validaciones_y_permiso(self, datos):
        e = datos.mundo.e1.pk
        assert configurar(empresa=e, tolerancia="101").status_code == 400
        assert configurar(empresa=e, tolerancia="-1").status_code == 400
        assert configurar(empresa=e, monto_aprobacion="-5").status_code == 400
        assert configurar(empresa=999_999, tolerancia="1").status_code in (400, 403)
        for usuario in ("almacenero", "contador", "vendedor"):
            assert configurar(usuario, empresa=e, tolerancia="1").status_code == 403, usuario
            r = cliente_de(usuario).get(f"{BASE}/ordenes/configuracion/?empresa={e}")
            assert r.status_code == 403, usuario

    def test_la_tolerancia_se_aplica_al_recibir(self, datos):
        configurar(empresa=datos.mundo.e1.pk, tolerancia="10")
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        assert recibir(datos, o, "11").status_code == 201
        assert recibir(datos, o, "1").status_code == 400  # ya está recibida


class TestRecibirPorLaApi:
    def test_por_recibir_precarga_lo_pendiente(self, datos):
        o = nueva(datos)
        r = cliente_de("almacenero").get(f"{BASE}/ordenes/{o['id']}/por-recibir/")
        assert r.status_code == 200 and r.json()["puede_recibir"] is False  # borrador
        accion("admin", o["id"], "emitir")
        recibir(datos, o, "4")
        d = cliente_de("almacenero").get(f"{BASE}/ordenes/{o['id']}/por-recibir/").json()
        assert (d["codigo"], d["estado"], d["puede_recibir"], d["moneda"]) == (
            "OC-000001",
            "PARCIAL",
            True,
            "PEN",
        )
        ln = d["lineas"][0]
        assert (ln["pedido"], ln["recibido"], ln["pendiente"], ln["maximo_recibible"]) == (
            "10.000",
            "4.000",
            "6.000",
            "6.000",
        )
        assert ln["precio_unitario"] == "10.000000" and ln["afectacion_codigo"] == "10"
        assert (
            cliente_de("contador").get(f"{BASE}/ordenes/{o['id']}/por-recibir/").status_code == 403
        )

    def test_la_compra_queda_enlazada_y_la_orden_avanza(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        r = recibir(datos, o, "4")
        assert r.status_code == 201, r.content
        c = r.json()
        assert (c["orden"], c["orden_codigo"]) == (o["id"], "OC-000001")
        assert c["lineas"][0]["linea_orden"] == o["lineas"][0]["id"]
        assert c["lineas"][0]["precio_pactado"] == "10.000000"
        d = cliente_de("admin").get(f"{BASE}/ordenes/{o['id']}/").json()
        assert d["estado"] == "PARCIAL" and d["lineas"][0]["cantidad_recibida"] == "4.000"
        assert [x["id"] for x in d["compras"]] == [c["id"]]
        recibir(datos, o, "6")
        assert cliente_de("admin").get(f"{BASE}/ordenes/{o['id']}/").json()["estado"] == "RECIBIDA"

    def test_linea_de_orden_indicada(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        linea = o["lineas"][0]
        c = cuerpo(
            datos,
            fecha_emision=timezone.localdate().isoformat(),
            orden=o["id"],
            lineas=[
                {
                    "producto": linea["producto"],
                    "cantidad": "2",
                    "precio_unitario": "10",
                    "linea_orden": linea["id"],
                }
            ],
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "23.60"}],
        )
        assert registrar(cliente_de("almacenero"), c).status_code == 201

    def test_no_se_recibe_de_mas_ni_una_orden_inexistente_ni_ajena(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        r = recibir(datos, o, "11")
        assert r.status_code == 400 and "como máximo se pueden recibir" in r.content.decode()
        assert recibir(datos, {**o, "id": 999_999}, "1").status_code == 400
        assert Compra.objects.sin_ambito().count() == 0

    def test_una_orden_en_borrador_no_recibe(self, datos):
        o = nueva(datos)
        r = recibir(datos, o, "1")
        assert r.status_code == 400 and "borrador" in r.content.decode()

    def test_la_vista_previa_de_la_compra_avisa_diferencias_de_precio(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        linea = o["lineas"][0]
        c = cuerpo(
            datos,
            fecha_emision=timezone.localdate().isoformat(),
            orden=o["id"],
            lineas=[{"producto": linea["producto"], "cantidad": "2", "precio_unitario": "11"}],
        )
        r = cliente_de("almacenero").post(f"{BASE}/calcular/", c, format="json")
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["orden"] == o["id"] and len(d["avisos_precio"]) == 1
        a = d["avisos_precio"][0]
        assert (a["precio_pactado"], a["precio_facturado"], a["diferencia"]) == (
            "10.000000",
            "11.000000",
            "1.0000",
        )
        assert a["producto_nombre"] and a["porcentaje"] == "10.00"
        sin_orden = {k: v for k, v in c.items() if k != "orden"}
        assert (
            cliente_de("almacenero")
            .post(f"{BASE}/calcular/", sin_orden, format="json")
            .json()["avisos_precio"]
            == []
        )

    def test_anular_la_compra_devuelve_la_orden(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        c = recibir(datos, o, "10").json()
        r = cliente_de("admin").post(
            f"{BASE}/{c['id']}/anular/", {"motivo": "Error"}, format="json"
        )
        assert r.status_code == 200
        d = cliente_de("admin").get(f"{BASE}/ordenes/{o['id']}/").json()
        assert d["estado"] == "EMITIDA" and d["lineas"][0]["cantidad_recibida"] == "0.000"

    def test_las_compras_sin_orden_siguen_igual(self, datos):
        r = registrar(cliente_de("almacenero"), cuerpo(datos))
        assert r.status_code == 201, r.content
        assert r.json()["orden"] is None and r.json()["orden_codigo"] is None
        assert r.json()["lineas"][0]["linea_orden"] is None
