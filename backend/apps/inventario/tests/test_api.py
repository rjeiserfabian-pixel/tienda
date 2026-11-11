"""API de inventario: permisos, aislamiento, idempotencia y consultas."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventario.models import MovimientoInventario, SaldoStock
from apps.seguridad.models import Permiso, UsuarioPermiso
from apps.seguridad.services import permisos_engine as motor
from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE, clave, cuerpo, registrar

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
class TestRegistrar:
    def test_registra_una_compra_y_devuelve_el_detalle(self, mundo):
        cemento = mundo.producto()
        r = registrar(cliente_de("almacenero"), cuerpo(mundo, cemento))
        assert r.status_code == 201, r.content
        datos = r.json()
        assert (datos["numero"], datos["tipo"], datos["origen"], datos["estado"]) == (
            1,
            "ENTRADA",
            "COMPRA",
            "EMITIDO",
        )
        assert datos["almacen_nombre"] == "Almacén A1"
        linea = datos["lineas"][0]
        assert (linea["cantidad"], linea["costo_total"], linea["saldo_cantidad"]) == (
            "10.000",
            "200.00",
            "10.000",
        )
        assert linea["producto_nombre"] == "Cemento Pacasmayo MS"
        assert SaldoStock.objects.sin_ambito().get().cantidad == 10

    def test_un_reintento_con_la_misma_clave_no_registra_dos_veces(self, mundo):
        cemento = mundo.producto()
        api, llave = cliente_de("almacenero"), clave()
        primera = registrar(api, cuerpo(mundo, cemento), llave)
        segunda = registrar(api, cuerpo(mundo, cemento), llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda.json() == primera.json()
        assert segunda["Idempotency-Replayed"] == "true"
        assert MovimientoInventario.objects.sin_ambito().count() == 1
        assert SaldoStock.objects.sin_ambito().get().cantidad == 10

    def test_la_misma_clave_con_otro_contenido_se_rechaza(self, mundo):
        cemento = mundo.producto()
        api, llave = cliente_de("almacenero"), clave()
        registrar(api, cuerpo(mundo, cemento), llave)
        r = registrar(api, cuerpo(mundo, cemento, cantidad="99"), llave)
        assert r.status_code == 422
        assert MovimientoInventario.objects.sin_ambito().count() == 1

    def test_sin_clave_de_idempotencia_no_se_registra(self, mundo):
        r = cliente_de("almacenero").post(
            f"{BASE}/movimientos/", cuerpo(mundo, mundo.producto()), format="json"
        )
        assert r.status_code == 400
        assert MovimientoInventario.objects.sin_ambito().count() == 0

    def test_un_error_de_negocio_no_memoriza_la_clave(self, mundo):
        cemento = mundo.producto()
        api, llave = cliente_de("almacenero"), clave()
        merma = {**cuerpo(mundo, cemento), "tipo": "SALIDA", "origen": "MERMA"}
        r = registrar(api, merma, llave)
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "stock_insuficiente")
        registrar(api, cuerpo(mundo, cemento))  # ahora sí hay stock
        assert registrar(api, merma, llave).status_code == 201  # la misma clave se puede reintentar

    def test_la_venta_y_el_extorno_no_se_registran_a_mano(self, mundo):
        cemento = mundo.producto()
        for origen in ("VENTA", "EXTORNO"):
            r = registrar(cliente_de("super"), {**cuerpo(mundo, cemento), "origen": origen})
            assert r.status_code == 400

    @pytest.mark.parametrize(
        "cambio",
        [
            {"lineas": []},
            {"fecha": "ayer"},
            {"tipo": "OTRO"},
            {"moneda": "EUR"},
            {"igv_porcentaje": "150"},
            {"almacen": 999999},
            {"proveedor": 999999},
        ],
    )
    def test_datos_invalidos(self, mundo, cambio):
        r = registrar(cliente_de("super"), {**cuerpo(mundo, mundo.producto()), **cambio})
        assert r.status_code == 400, r.content
        assert MovimientoInventario.objects.sin_ambito().count() == 0

    def test_cantidad_invalida_y_producto_inexistente(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("super")
        for cantidad in ("0", "-1", "abc", "1.0005"):
            assert registrar(api, cuerpo(mundo, cemento, cantidad=cantidad)).status_code == 400
        r = registrar(
            api,
            {
                **cuerpo(mundo, cemento),
                "lineas": [{"producto": 999999, "cantidad": "1", "precio_unitario": "1"}],
            },
        )
        assert r.status_code == 400

    def test_el_almacen_debe_ser_de_la_empresa(self, mundo):
        r = registrar(
            cliente_de("super"),
            {**cuerpo(mundo, mundo.producto()), "almacen": mundo.alm[2].pk},
        )
        assert r.status_code == 400


class TestPermisos:
    def test_el_vendedor_ve_pero_no_registra(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("vendedor")
        assert registrar(api, cuerpo(mundo, cemento)).status_code == 403
        assert api.get(f"{BASE}/movimientos/", {"empresa": mundo.e1.pk}).status_code == 200
        assert api.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk}).status_code == 200

    def test_el_almacenero_registra_compras_y_ajustes_pero_no_el_saldo_inicial(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("almacenero")
        assert registrar(api, cuerpo(mundo, cemento)).status_code == 201
        ajuste = {**cuerpo(mundo, cemento, cantidad="1"), "origen": "AJUSTE"}
        assert registrar(api, ajuste).status_code == 201
        inicial = {**cuerpo(mundo, cemento), "origen": "SALDO_INICIAL"}
        assert registrar(api, inicial).status_code == 403

    def test_el_administrador_si_puede_cargar_el_saldo_inicial(self, mundo):
        inicial = {**cuerpo(mundo, mundo.producto()), "origen": "SALDO_INICIAL"}
        r = registrar(cliente_de("admin"), inicial)
        assert r.status_code == 201 and r.json()["tipo_operacion"] == "16"

    def test_no_se_opera_en_una_empresa_sin_acceso(self, mundo):
        r = registrar(cliente_de("admin"), cuerpo(mundo, mundo.producto(), empresa=2))
        assert r.status_code == 403
        assert MovimientoInventario.objects.sin_ambito().count() == 0

    def test_otra_organizacion_no_ve_ni_toca_nada(self, mundo):
        cemento = mundo.producto()
        movimiento = registrar(cliente_de("super"), cuerpo(mundo, cemento)).json()
        ajeno = cliente_de("otra_org")
        assert registrar(ajeno, cuerpo(mundo, cemento)).status_code == 403
        assert ajeno.get(f"{BASE}/movimientos/", {"empresa": mundo.e1.pk}).status_code == 403
        assert ajeno.get(f"{BASE}/movimientos/{movimiento['id']}/").status_code == 404
        r = ajeno.post(
            f"{BASE}/movimientos/{movimiento['id']}/anular/", {"motivo": "x"}, format="json"
        )
        assert r.status_code == 404

    def test_sin_sesion(self, mundo, api):
        assert api.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk}).status_code in (401, 403)
        assert api.post(f"{BASE}/movimientos/", {}, format="json").status_code in (401, 403)


class TestListadoYDetalle:
    def _datos(self, mundo):
        cemento, arena = mundo.producto(), mundo.producto("Arena fina")
        api = cliente_de("super")
        registrar(
            api,
            cuerpo(
                mundo,
                cemento,
                comprobante_tipo="01",
                comprobante_serie="F001",
                comprobante_numero="55",
            ),
        )
        registrar(api, cuerpo(mundo, arena, observacion="Lote de arena"))
        registrar(api, cuerpo(mundo, cemento, empresa=2))
        return api, cemento, arena

    def test_la_empresa_es_obligatoria(self, mundo):
        r = cliente_de("super").get(f"{BASE}/movimientos/")
        assert r.status_code == 400

    def test_lista_paginada_solo_de_la_empresa_pedida(self, mundo):
        api, *_ = self._datos(mundo)
        r = api.get(f"{BASE}/movimientos/", {"empresa": mundo.e1.pk})
        assert r.status_code == 200
        datos = r.json()
        assert datos["count"] == 2 and len(datos["results"]) == 2
        assert {m["empresa"] for m in datos["results"]} == {mundo.e1.pk}
        assert datos["results"][0]["cantidad_lineas"] == 1

    def test_filtros(self, mundo):
        api, cemento, arena = self._datos(mundo)
        pedir = lambda **f: api.get(f"{BASE}/movimientos/", {"empresa": mundo.e1.pk, **f}).json()  # noqa: E731
        assert pedir(producto=arena.pk)["count"] == 1
        assert pedir(q="F001")["count"] == 1
        assert pedir(q="arena")["count"] == 1
        assert pedir(q="1")["count"] >= 1  # también busca por número interno
        assert pedir(tipo="SALIDA")["count"] == 0
        assert pedir(origen="COMPRA")["count"] == 2
        assert pedir(estado="ANULADO")["count"] == 0
        assert pedir(desde=timezone.localdate().isoformat())["count"] == 0
        assert pedir(hasta=timezone.localdate().isoformat())["count"] == 2
        assert pedir(page_size=10, page=1)["count"] == 2

    @pytest.mark.parametrize("filtro", [{"desde": "mañana"}, {"almacen": "x"}, {"producto": "1;2"}])
    def test_filtros_invalidos(self, mundo, filtro):
        r = cliente_de("super").get(f"{BASE}/movimientos/", {"empresa": mundo.e1.pk, **filtro})
        assert r.status_code == 400

    def test_detalle_con_sus_lineas(self, mundo):
        api, cemento, _ = self._datos(mundo)
        primero = api.get(f"{BASE}/movimientos/", {"empresa": mundo.e1.pk}).json()["results"][-1]
        r = api.get(f"{BASE}/movimientos/{primero['id']}/")
        assert r.status_code == 200
        assert r.json()["lineas"][0]["producto"] == cemento.pk
        assert r.json()["comprobante_serie"] == "F001"

    def test_un_movimiento_de_una_empresa_sin_acceso_no_se_revela(self, mundo):
        api, *_ = self._datos(mundo)
        de_a2 = MovimientoInventario.objects.sin_ambito().get(empresa=mundo.e2)
        # No se distingue "no existe" de "es de otra empresa": nada se filtra.
        assert cliente_de("admin").get(f"{BASE}/movimientos/{de_a2.pk}/").status_code == 404


class TestAnular:
    def test_anula_y_responde_con_el_original_y_el_extorno(self, mundo):
        cemento = mundo.producto()
        compra = registrar(cliente_de("super"), cuerpo(mundo, cemento)).json()
        r = cliente_de("admin").post(
            f"{BASE}/movimientos/{compra['id']}/anular/",
            {"motivo": "Error de digitación"},
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["movimiento"]["estado"] == "ANULADO"
        assert datos["movimiento"]["motivo_anulacion"] == "Error de digitación"
        assert (datos["extorno"]["tipo"], datos["extorno"]["origen"]) == ("SALIDA", "EXTORNO")
        assert datos["extorno"]["extorna"] == compra["id"]
        assert SaldoStock.objects.sin_ambito().get().cantidad == 0

    def test_exige_motivo_y_permiso_y_no_se_repite(self, mundo):
        cemento = mundo.producto()
        compra = registrar(cliente_de("super"), cuerpo(mundo, cemento)).json()
        url = f"{BASE}/movimientos/{compra['id']}/anular/"
        assert cliente_de("almacenero").post(url, {"motivo": "x"}, format="json").status_code == 403
        admin = cliente_de("admin")
        assert admin.post(url, {}, format="json").status_code == 400
        assert admin.post(url, {"motivo": "   "}, format="json").status_code == 400
        assert admin.post(url, {"motivo": "Duplicada"}, format="json").status_code == 200
        r = admin.post(url, {"motivo": "Otra vez"}, format="json")
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "documento_ya_anulado")

    def test_no_anula_una_compra_cuya_mercaderia_ya_salio(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("super")
        compra = registrar(api, cuerpo(mundo, cemento)).json()
        merma = {**cuerpo(mundo, cemento, cantidad="10"), "tipo": "SALIDA", "origen": "MERMA"}
        assert registrar(api, merma).status_code == 201
        r = api.post(
            f"{BASE}/movimientos/{compra['id']}/anular/", {"motivo": "Error"}, format="json"
        )
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "anulacion_no_permitida")


class TestStock:
    def test_lista_con_costo_y_filtros(self, mundo):
        cemento = mundo.producto(stock_minimo=15)
        arena = mundo.producto("Arena fina")
        api = cliente_de("super")
        registrar(api, cuerpo(mundo, cemento, cantidad="10", precio="20"))
        registrar(api, cuerpo(mundo, arena, cantidad="40", precio="5"))
        merma = {**cuerpo(mundo, arena, cantidad="40"), "tipo": "SALIDA", "origen": "MERMA"}
        registrar(api, merma)

        pedir = lambda **f: api.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk, **f}).json()  # noqa: E731
        datos = pedir()
        assert datos["count"] == 1  # lo que quedó en cero no se muestra
        fila = datos["results"][0]
        assert (fila["producto_nombre"], fila["cantidad"], fila["costo_unitario"]) == (
            "Cemento Pacasmayo MS",
            "10.000",
            "20.000000",
        )
        assert fila["bajo_minimo"] is True and fila["unidad"] == "BLS"
        assert pedir(incluir_cero="1")["count"] == 2
        assert pedir(bajo_minimo="1")["count"] == 1
        assert pedir(q="arena", incluir_cero="1")["count"] == 1
        assert pedir(q="zzz")["count"] == 0

    def test_exige_empresa_y_respeta_el_acceso(self, mundo):
        assert cliente_de("super").get(f"{BASE}/stock/").status_code == 400
        r = cliente_de("vendedor_a2").get(f"{BASE}/stock/", {"empresa": mundo.e1.pk})
        assert r.status_code == 403


class TestKardex:
    def _historia(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("super")
        hoy = timezone.localdate()
        for dias, tipo, origen, cant, precio in [
            (20, "ENTRADA", "COMPRA", "50", "20"),
            (15, "SALIDA", "MERMA", "5", None),
            (10, "ENTRADA", "COMPRA", "20", "22"),
        ]:
            datos = cuerpo(mundo, cemento, cantidad=cant, precio=precio)
            datos.update(tipo=tipo, origen=origen, fecha=(hoy - timedelta(days=dias)).isoformat())
            if precio is None:
                datos["lineas"][0].pop("precio_unitario")
            assert registrar(api, datos).status_code == 201
        return api, cemento, hoy

    def test_muestra_el_saldo_despues_de_cada_linea(self, mundo):
        api, cemento, _ = self._historia(mundo)
        r = api.get(
            f"{BASE}/kardex/",
            {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk, "producto": cemento.pk},
        )
        assert r.status_code == 200
        datos = r.json()
        assert datos["count"] == 3
        assert [(ln["tipo"], ln["saldo_cantidad"]) for ln in datos["results"]] == [
            ("ENTRADA", "50.000"),
            ("SALIDA", "45.000"),
            ("ENTRADA", "65.000"),
        ]
        assert datos["saldo_inicial"]["cantidad"] == "0"

    def test_el_rango_trae_el_saldo_con_el_que_arranca(self, mundo):
        api, cemento, hoy = self._historia(mundo)
        r = api.get(
            f"{BASE}/kardex/",
            {
                "empresa": mundo.e1.pk,
                "almacen": mundo.alm[1].pk,
                "producto": cemento.pk,
                "desde": (hoy - timedelta(days=12)).isoformat(),
            },
        )
        datos = r.json()
        assert datos["count"] == 1
        assert datos["saldo_inicial"]["cantidad"] == "45.000"
        assert datos["saldo_inicial"]["costo_total"] == "900.00"

    def test_exige_empresa_almacen_y_producto(self, mundo):
        api = cliente_de("super")
        r = api.get(f"{BASE}/kardex/", {"empresa": mundo.e1.pk})
        assert r.status_code == 400
        assert set(r.json()["error"]["detalle"]) >= {"almacen", "producto"} or r.status_code == 400

    def test_sin_acceso_a_la_empresa(self, mundo):
        cemento = mundo.producto()
        r = cliente_de("vendedor_a2").get(
            f"{BASE}/kardex/",
            {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk, "producto": cemento.pk},
        )
        assert r.status_code == 403


class TestDisponibilidad:
    def _stock(self, mundo):
        cemento = mundo.producto()
        api = cliente_de("super")
        registrar(api, cuerpo(mundo, cemento, empresa=1, cantidad="10", precio="20"))
        registrar(api, cuerpo(mundo, cemento, empresa=2, cantidad="4", precio="30"))
        return cemento

    def test_quien_ve_las_dos_empresas_ve_el_detalle_de_ambas(self, mundo):
        cemento = self._stock(mundo)
        r = cliente_de("super").get(f"{BASE}/stock/disponibilidad/{cemento.pk}/")
        assert r.status_code == 200
        empresas = r.json()["empresas"]
        assert [e["empresa"] for e in empresas] == [mundo.e1.pk, mundo.e2.pk]
        assert [e["cantidad"] for e in empresas] == ["10.000", "4.000"]
        assert empresas[0]["almacenes"][0]["costo_unitario"] == "20.000000"

    def test_sin_permiso_para_ver_otra_empresa_solo_aparece_la_suya(self, mundo):
        cemento = self._stock(mundo)
        empresas = (
            cliente_de("vendedor")
            .get(f"{BASE}/stock/disponibilidad/{cemento.pk}/")
            .json()["empresas"]
        )
        assert [e["empresa"] for e in empresas] == [mundo.e1.pk]

    def test_con_el_permiso_de_otra_empresa_ve_solo_la_cantidad(self, mundo):
        cemento = self._stock(mundo)
        usuario = mundo.usuarios["vendedor"]
        UsuarioPermiso(
            organizacion=mundo.e.org_a,
            usuario=usuario,
            permiso=Permiso.objects.get(codigo="INVENTARIO.STOCK_OTRA_EMPRESA.VER"),
            tipo="ALLOW",
            alcance="ORGANIZACION",
            motivo="Atiende consultas de las dos empresas",
        ).save()
        motor.invalidar_usuario(usuario.pk)
        empresas = (
            cliente_de("vendedor")
            .get(f"{BASE}/stock/disponibilidad/{cemento.pk}/")
            .json()["empresas"]
        )
        propia, otra = empresas
        assert "almacenes" in propia and propia["propia"] is True
        assert otra == {
            "empresa": mundo.e2.pk,
            "razon_social": mundo.e2.razon_social,
            "nombre_comercial": "",
            "es_principal": False,
            "propia": False,
            "cantidad": "4.000",
        }  # sin almacenes ni costos

    def test_producto_inexistente_o_de_otra_organizacion(self, mundo):
        assert cliente_de("super").get(f"{BASE}/stock/disponibilidad/999999/").status_code == 404
        cemento = mundo.producto()
        assert (
            cliente_de("otra_org").get(f"{BASE}/stock/disponibilidad/{cemento.pk}/").status_code
            == 404
        )


class TestPeriodos:
    def _con_movimiento_del_mes_pasado(self, mundo):
        cemento = mundo.producto()
        hoy = timezone.localdate()
        fin_pasado = hoy.replace(day=1) - timedelta(days=1)
        datos = cuerpo(mundo, cemento, fecha=fin_pasado.isoformat())
        assert registrar(cliente_de("super"), datos).status_code == 201
        return cemento, fin_pasado, f"{fin_pasado:%Y%m}", datos

    def test_el_contador_cierra_y_reabre_y_el_mes_cerrado_no_admite_movimientos(self, mundo):
        cemento, fin_pasado, periodo, datos = self._con_movimiento_del_mes_pasado(mundo)
        contador = cliente_de("contador")
        pedir = lambda: contador.get(f"{BASE}/periodos/", {"empresa": mundo.e1.pk}).json()  # noqa: E731
        assert pedir() == {"empresa": mundo.e1.pk, "cerrados": [], "proximo_a_cerrar": periodo}

        r = contador.post(
            f"{BASE}/periodos/cerrar/", {"empresa": mundo.e1.pk, "periodo": periodo}, format="json"
        )
        assert r.status_code == 200 and r.json()["cerrados"] == [periodo]
        assert pedir()["proximo_a_cerrar"] is None

        r = registrar(cliente_de("super"), datos)
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "periodo_cerrado")

        r = contador.post(
            f"{BASE}/periodos/reabrir/", {"empresa": mundo.e1.pk, "periodo": periodo}, format="json"
        )
        assert r.status_code == 200 and r.json()["cerrados"] == []
        assert registrar(cliente_de("super"), datos).status_code == 201

    def test_el_vendedor_no_cierra_periodos(self, mundo):
        _, _, periodo, _ = self._con_movimiento_del_mes_pasado(mundo)
        r = cliente_de("vendedor").post(
            f"{BASE}/periodos/cerrar/", {"empresa": mundo.e1.pk, "periodo": periodo}, format="json"
        )
        assert r.status_code == 403

    @pytest.mark.parametrize("periodo", ["2026-10", "202613", "", "abcdef"])
    def test_periodo_invalido(self, mundo, periodo):
        r = cliente_de("contador").post(
            f"{BASE}/periodos/cerrar/", {"empresa": mundo.e1.pk, "periodo": periodo}, format="json"
        )
        assert r.status_code == 400

    def test_no_se_cierra_el_mes_en_curso(self, mundo):
        r = cliente_de("contador").post(
            f"{BASE}/periodos/cerrar/",
            {"empresa": mundo.e1.pk, "periodo": f"{timezone.localdate():%Y%m}"},
            format="json",
        )
        assert r.status_code == 400
