"""API de ventas: configuración, catálogo, vista previa, registro, permisos y anulación."""

import itertools
import json
from decimal import Decimal

import pytest

from apps.seguridad.tests.conftest import cliente_de
from apps.ventas.models import Venta

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


def vender(usuario, cuerpo, llave=None):
    return cliente_de(usuario).post(
        f"{BASE}/",
        cuerpo,
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or f"venta-de-prueba-{next(_claves):06d}",
    )


def linea(tienda, producto, cantidad=1, empresa=None, **extra):
    empresa = empresa or tienda.a
    return {
        "producto": producto.pk,
        "cantidad": str(cantidad),
        "empresa": empresa.pk,
        "almacen": tienda.almacen(empresa).pk,
        **extra,
    }


def carrito(tienda, lineas, **extra):
    return {"empresa": tienda.a.pk, "tipo_comprobante": "NV", "lineas": lineas, **extra}


def cuerpo(tienda, lineas, cobros, **extra):
    return carrito(tienda, lineas, cobros=cobros, **extra)


def efectivo(tienda, monto, **extra):
    return {"medio_pago": tienda.efectivo.pk, "monto": str(monto), **extra}


class TestConfiguracion:
    def test_trae_lo_que_la_pantalla_necesita(self, tienda):
        r = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk})
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["igv_porcentaje"] == "18.00" and datos["tope_boleta"] == "700.00"
        # La empresa principal va primero y es la A.
        assert [(e["id"], e["letra"], e["es_principal"]) for e in datos["empresas"]] == [
            (tienda.a.pk, "A", True),
            (tienda.b.pk, "B", False),
        ]
        assert all(set(e["tipos"]) == {"01", "03", "NV"} for e in datos["empresas"])
        assert [t["codigo"] for t in datos["tipos_comprobante"]] == ["01", "03", "NV"]
        usos = {lista["uso"]: lista["permitida"] for lista in datos["listas"]}
        assert usos == {"PUBLICO": True, "DESCUENTO": True, "TECNICO": True, "CREDITO": False}
        assert datos["permisos"]["bajo_minimo"] is False  # el administrador lo tiene apagado
        assert any(v["nombre"] for v in datos["vendedores"])

    def test_dice_si_cada_metodo_entra_a_una_cuenta(self, tienda):
        datos = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        cobros = datos["cobros"]["PEN"]
        assert cobros[str(tienda.a.pk)][str(tienda.efectivo.pk)]["ok"] is True
        assert cobros[str(tienda.b.pk)][str(tienda.yape.pk)]["ok"] is True
        sin_cuenta = cobros[str(tienda.a.pk)][str(tienda.tarjeta.pk)]
        assert sin_cuenta["ok"] is False and "Tarjeta" in sin_cuenta["motivo"]
        # No hay caja en dólares para la empresa B.
        assert cobros[str(tienda.b.pk)][str(tienda.efectivo.pk)]["ok"] is True
        assert datos["cobros"]["USD"][str(tienda.b.pk)][str(tienda.efectivo.pk)]["ok"] is False

    def test_el_vendedor_no_elige_vendedor_ni_usa_listas_especiales(self, tienda):
        datos = (
            cliente_de("vendedor").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        )
        assert datos["vendedores"] == []
        assert datos["permisos"]["elegir_vendedor"] is False
        usos = {lista["uso"]: lista["permitida"] for lista in datos["listas"]}
        assert usos["DESCUENTO"] is False and usos["TECNICO"] is False

    def test_exige_el_permiso_de_vender(self, tienda):
        r = cliente_de("contador").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk})
        assert r.status_code == 403


class TestCatalogo:
    def test_busca_y_trae_precios_y_stock_sin_costos(self, tienda):
        p = tienda.producto("Audífonos Sony", costo="50", stock={tienda.a: 5, tienda.b: 3})
        r = cliente_de("vendedor").get(f"{BASE}/catalogo/", {"empresa": tienda.a.pk, "q": "Sony"})
        assert r.status_code == 200
        (ficha,) = r.json()["results"]
        assert ficha["id"] == p.pk
        assert ficha["precios"] == [{"lista": tienda.listas["PUBLICO"].pk, "precio": "100.0000"}]
        assert {(s["empresa"], s["cantidad"]) for s in ficha["stock"]} == {
            (tienda.a.pk, "5.000"),
            (tienda.b.pk, "3.000"),
        }
        assert "costo" not in json.dumps(r.json()).lower()

    def test_un_codigo_exacto_se_marca_como_tal(self, tienda):
        p = tienda.producto("Cable USB")
        r = cliente_de("vendedor").get(f"{BASE}/catalogo/", {"empresa": tienda.a.pk, "q": p.codigo})
        assert r.json()["exacto"] is True

    def test_recorre_el_catalogo_por_paginas_y_filtra_por_categoria(self, tienda):
        for i in range(26):
            tienda.producto(f"Producto {i:02d}", stock={})
        c = cliente_de("vendedor")
        primera = c.get(f"{BASE}/catalogo/", {"empresa": tienda.a.pk}).json()
        assert len(primera["results"]) == 24 and primera["hay_mas"] is True
        segunda = c.get(f"{BASE}/catalogo/", {"empresa": tienda.a.pk, "pagina": 2}).json()
        # 26 productos nuevos más el servicio «Flete» que ya trae el escenario.
        assert len(segunda["results"]) == 3 and segunda["hay_mas"] is False
        categoria = primera["results"][0]["categoria_id"]
        filtrada = c.get(
            f"{BASE}/catalogo/", {"empresa": tienda.a.pk, "categoria": categoria}
        ).json()
        assert len(filtrada["results"]) == 24
        assert (
            c.get(f"{BASE}/catalogo/", {"empresa": tienda.a.pk, "categoria": 999999}).json()[
                "results"
            ]
            == []
        )


class TestPrevisualizar:
    def test_calcula_cada_empresa_sin_guardar(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        r = cliente_de("admin").post(
            f"{BASE}/previsualizar/",
            carrito(tienda, [linea(tienda, pa, 2), linea(tienda, pb, 1, tienda.b)]),
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["total"] == "129.80" and datos["avisos"] == []
        a, b = datos["comprobantes"]
        assert (a["empresa"], a["serie"], a["igv"], a["total"]) == (
            tienda.a.pk,
            "N001",
            "10.80",
            "70.80",
        )
        assert (b["empresa"], b["serie"], b["total"]) == (tienda.b.pk, "N002", "59.00")
        assert a["lineas"][0]["indice"] == 0 and b["lineas"][0]["indice"] == 1
        assert not Venta.objects.sin_ambito().exists()

    def test_marca_el_precio_bajo_el_minimo_sin_fallar(self, tienda):
        p = tienda.producto(costo="60", precios={"PUBLICO": "100", "DESCUENTO": "90"})
        r = cliente_de("vendedor").post(
            f"{BASE}/previsualizar/",
            carrito(tienda, [linea(tienda, p, 1, precio_unitario="80")]),
            format="json",
        )
        assert r.status_code == 200
        (l1,) = r.json()["comprobantes"][0]["lineas"]
        assert l1["estado_precio"] == "BAJO_MINIMO"
        assert l1["minimo"] == "90.0000"  # sale de las listas: se puede mostrar

    def test_no_revela_el_costo_cuando_el_minimo_lo_fija_el_costo(self, tienda):
        p = tienda.producto(costo="70", precios={"PUBLICO": "100"})
        r = cliente_de("vendedor").post(
            f"{BASE}/previsualizar/",
            carrito(tienda, [linea(tienda, p, 1, precio_unitario="65")]),
            format="json",
        )
        (l1,) = r.json()["comprobantes"][0]["lineas"]
        assert l1["estado_precio"] == "BAJO_COSTO" and l1["minimo"] is None
        assert "70.00" not in json.dumps(r.json())

    def test_avisa_en_vez_de_fallar_cuando_falta_el_cliente(self, tienda):
        p = tienda.producto(costo="400", precios={"PUBLICO": "600"})
        r = cliente_de("vendedor").post(
            f"{BASE}/previsualizar/",
            carrito(tienda, [linea(tienda, p, 1)], tipo_comprobante="03"),
            format="json",
        )
        assert r.status_code == 200
        assert "identificado" in r.json()["avisos"][0]

    def test_pide_permiso_en_todas_las_empresas_del_carrito(self, tienda, nuevo_usuario):
        nuevo_usuario(tienda.entorno.e.org_a, "solo_a", [tienda.a], [("VENDEDOR", None)])
        p = tienda.producto(stock={tienda.b: 5})
        r = cliente_de("solo_a").post(
            f"{BASE}/previsualizar/",
            carrito(tienda, [linea(tienda, p, 1, tienda.b)]),
            format="json",
        )
        assert r.status_code == 403


class TestRegistrar:
    def test_el_vendedor_vende_a_su_nombre_y_se_guarda_todo(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        r = vender("vendedor", cuerpo(tienda, [linea(tienda, p, 2)], [efectivo(tienda, "236.00")]))
        assert r.status_code == 201, r.content
        datos = r.json()
        assert datos["total"] == "236.00" and datos["estado"] == "EMITIDO"
        assert datos["vendedor_nombre"] == "vendedor"
        (comp,) = datos["comprobantes"]
        assert comp["numero_completo"] == "N001-00000001"
        assert comp["lineas"][0]["precio_unitario"] == "100.000000"
        assert comp["cobros"][0]["medio_pago_nombre"] == "Efectivo"
        # El detalle nunca trae costos.
        assert "costo" not in json.dumps(datos).lower()

    def test_un_reintento_con_la_misma_clave_no_vende_dos_veces(self, tienda):
        p = tienda.producto()
        c = cuerpo(tienda, [linea(tienda, p, 1)], [efectivo(tienda, "118.00")])
        primera = vender("vendedor", c, llave="clave-fija-0001")
        segunda = vender("vendedor", c, llave="clave-fija-0001")
        assert primera.status_code == segunda.status_code == 201
        assert segunda["Idempotency-Replayed"] == "true"
        assert Venta.objects.sin_ambito().count() == 1

    def test_sin_clave_de_idempotencia_no_se_vende(self, tienda):
        p = tienda.producto()
        r = cliente_de("vendedor").post(
            f"{BASE}/",
            cuerpo(tienda, [linea(tienda, p, 1)], [efectivo(tienda, "118.00")]),
            format="json",
        )
        assert r.status_code == 400 and not Venta.objects.sin_ambito().exists()

    def test_el_vendedor_no_puede_vender_a_nombre_de_otro(self, tienda):
        p = tienda.producto()
        otro = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        admin_id = otro["vendedor"]["id"]
        r = vender(
            "vendedor",
            cuerpo(tienda, [linea(tienda, p)], [efectivo(tienda, "118.00")], vendedor=admin_id),
        )
        assert r.status_code == 403 and not Venta.objects.sin_ambito().exists()

    def test_el_administrador_elige_al_vendedor(self, tienda):
        p = tienda.producto()
        lista = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        elegido = next(v for v in lista["vendedores"] if v["nombre"] == "vendedor")
        r = vender(
            "admin",
            cuerpo(
                tienda, [linea(tienda, p)], [efectivo(tienda, "118.00")], vendedor=elegido["id"]
            ),
        )
        assert r.status_code == 201 and r.json()["vendedor_nombre"] == "vendedor"

    def test_bajo_el_minimo_el_vendedor_recibe_un_error_claro(self, tienda):
        p = tienda.producto(costo="60", precios={"PUBLICO": "100", "DESCUENTO": "90"})
        r = vender(
            "vendedor",
            cuerpo(
                tienda,
                [linea(tienda, p, 1, precio_unitario="80")],
                [efectivo(tienda, "94.40")],
            ),
        )
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "precio_bajo_el_minimo"
        assert not Venta.objects.sin_ambito().exists()

    def test_el_vendedor_no_cambia_el_tipo_de_cambio(self, tienda):
        p = tienda.producto()
        r = vender(
            "vendedor",
            cuerpo(
                tienda,
                [linea(tienda, p)],
                [efectivo(tienda, "118.00")],
                moneda="USD",
                tipo_cambio="3.9000",
            ),
        )
        assert r.status_code == 403

    def test_vender_stock_de_la_otra_empresa_exige_permiso_especial(self, tienda):
        p = tienda.producto(stock={tienda.b: 5}, precios={"PUBLICO": "50"}, costo="20")
        c = cuerpo(tienda, [linea(tienda, p, 1, tienda.b)], [efectivo(tienda, "59.00")])
        assert vender("vendedor", c).status_code == 400
        assert not Venta.objects.sin_ambito().exists()
        ok = vender("admin", c)
        assert ok.status_code == 201
        assert ok.json()["comprobantes"][0]["empresa"] == tienda.b.pk

    def test_venta_de_dos_empresas(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        r = vender(
            "admin",
            cuerpo(
                tienda,
                [linea(tienda, pa, 2), linea(tienda, pb, 1, tienda.b)],
                [efectivo(tienda, "129.80", recibido="200.00")],
            ),
        )
        assert r.status_code == 201, r.content
        a, b = r.json()["comprobantes"]
        assert (a["numero_completo"], b["numero_completo"]) == ("N001-00000001", "N002-00000001")
        assert [c["monto"] for c in a["cobros"] + b["cobros"]] == ["70.80", "59.00"]

    def test_datos_mal_formados_se_rechazan_sin_guardar(self, tienda):
        p = tienda.producto()
        base = cuerpo(tienda, [linea(tienda, p)], [efectivo(tienda, "118.00")])
        for malo in (
            {**base, "lineas": []},
            {**base, "cobros": []},
            {**base, "tipo_comprobante": "07"},
            {**base, "lineas": [{**base["lineas"][0], "cantidad": "-1"}]},
            {**base, "lineas": [{**base["lineas"][0], "producto": 999999}]},
        ):
            assert vender("vendedor", malo).status_code in (400, 409)
        assert not Venta.objects.sin_ambito().exists()


class TestConsultarYAnular:
    def registrar(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        r = vender(
            "admin",
            cuerpo(
                tienda,
                [linea(tienda, pa, 2), linea(tienda, pb, 1, tienda.b)],
                [efectivo(tienda, "129.80")],
            ),
        )
        return r.json()["id"]

    def test_lista_con_filtros_y_detalle(self, tienda):
        venta_id = self.registrar(tienda)
        c = cliente_de("vendedor")
        lista = c.get(f"{BASE}/", {"empresa": tienda.a.pk}).json()
        assert lista["count"] == 1 and len(lista["results"][0]["comprobantes"]) == 2
        assert c.get(f"{BASE}/", {"empresa": tienda.a.pk, "q": "N002"}).json()["count"] == 1
        assert c.get(f"{BASE}/", {"empresa": tienda.a.pk, "q": "nadie"}).json()["count"] == 0
        assert c.get(f"{BASE}/", {"empresa": tienda.a.pk, "estado": "ANULADO"}).json()["count"] == 0
        detalle = c.get(f"{BASE}/{venta_id}/")
        assert detalle.status_code == 200
        assert detalle.json()["comprobantes"][1]["empresa_ruc"]

    def test_la_ficha_trae_la_direccion_del_cliente_para_la_hoja_a4(self, tienda):
        cliente = tienda.cliente(direccion="JR. SAN MARTIN NRO. 405 - TARAPOTO")
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        v = tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            tipo_comprobante="01",
            cliente=cliente,
        )
        r = cliente_de("vendedor").get(f"{BASE}/{v.pk}/")
        assert r.status_code == 200
        assert r.json()["cliente_direccion"] == "JR. SAN MARTIN NRO. 405 - TARAPOTO"

    def test_solo_quien_tiene_el_permiso_anula(self, tienda):
        venta_id = self.registrar(tienda)
        r = cliente_de("vendedor").post(
            f"{BASE}/{venta_id}/anular/", {"motivo": "Error"}, format="json"
        )
        assert r.status_code == 403
        assert Venta.objects.sin_ambito().get(pk=venta_id).estado == "EMITIDO"

    def test_anula_un_comprobante_y_luego_la_venta(self, tienda):
        venta_id = self.registrar(tienda)
        c = cliente_de("admin")
        detalle = c.get(f"{BASE}/{venta_id}/").json()
        segundo = detalle["comprobantes"][1]["id"]
        r = c.post(
            f"{BASE}/{venta_id}/comprobantes/{segundo}/anular/",
            {"motivo": "No quiso el mouse"},
            format="json",
        )
        assert r.status_code == 200, r.content
        estados = [x["estado"] for x in r.json()["comprobantes"]]
        assert estados == ["EMITIDO", "ANULADO"] and r.json()["estado"] == "EMITIDO"
        r = c.post(f"{BASE}/{venta_id}/anular/", {"motivo": "Se devolvió todo"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADO"
        sin_motivo = c.post(f"{BASE}/{venta_id}/anular/", {"motivo": ""}, format="json")
        assert sin_motivo.status_code == 400

    def test_una_venta_ajena_no_existe_para_otra_organizacion(self, tienda, nuevo_usuario):
        venta_id = self.registrar(tienda)
        org_b = tienda.entorno.e.org_b
        nuevo_usuario(org_b, "intruso", [tienda.entorno.eb], [("ADMIN", None)])
        r = cliente_de("intruso").get(f"{BASE}/{venta_id}/")
        assert r.status_code in (403, 404)


class TestAfectacionElegida:
    def test_se_puede_elegir_la_afectacion_de_la_linea(self, tienda):
        p = tienda.producto("Libro", costo="10", precios={"PUBLICO": "100"})
        c = cliente_de("vendedor")
        cuerpo = {
            "empresa": tienda.a.pk,
            "tipo_comprobante": "NV",
            "lineas": [
                {
                    "producto": p.pk,
                    "cantidad": "1",
                    "empresa": tienda.a.pk,
                    "almacen": tienda.almacen(tienda.a).pk,
                    "afectacion": "20",
                }
            ],
        }
        r = c.post("/api/v1/ventas/previsualizar/", cuerpo, format="json")
        assert r.status_code == 200, r.content
        (ln,) = r.json()["comprobantes"][0]["lineas"]
        assert Decimal(ln["tasa_igv"]) == 0 and Decimal(ln["igv"]) == 0
        cuerpo["lineas"][0]["afectacion"] = "99"
        assert c.post("/api/v1/ventas/previsualizar/", cuerpo, format="json").status_code in (
            400,
            422,
        )


class TestSerieElegida:
    def test_con_varias_series_se_elige_una(self, tienda):
        from apps.mantenimiento.models import SerieComprobante

        base = SerieComprobante.objects.sin_ambito().get(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("NV")
        )
        SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.a,
            tipo_comprobante=base.tipo_comprobante,
            serie="NV02",
            sucursal=base.sucursal,
        )
        p = tienda.producto("Cable", costo="5", precios={"PUBLICO": "20"})
        c = cliente_de("vendedor")
        cfg = c.get("/api/v1/ventas/configuracion/", {"empresa": tienda.a.pk}).json()
        assert len([s for s in cfg["empresas"][0]["series"] if s["tipo"] == "NV"]) == 2
        cuerpo = {
            "empresa": tienda.a.pk,
            "tipo_comprobante": "NV",
            "lineas": [
                {
                    "producto": p.pk,
                    "cantidad": "1",
                    "empresa": tienda.a.pk,
                    "almacen": tienda.almacen(tienda.a).pk,
                }
            ],
        }
        sin = c.post("/api/v1/ventas/previsualizar/", cuerpo, format="json")
        assert sin.status_code in (400, 422) and "elija una" in json.dumps(sin.json())
        cuerpo["serie_por_empresa"] = {str(tienda.a.pk): base.pk}
        ok = c.post("/api/v1/ventas/previsualizar/", cuerpo, format="json")
        assert ok.status_code == 200, ok.content


class TestHistorialPorEmpresa:
    """Cada empresa ve las ventas donde tiene un comprobante, aunque otra haya hecho la venta."""

    @pytest.fixture
    def mixta(self, tienda):
        pa = tienda.producto("Laptop", costo="50", precios={"PUBLICO": "100"})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        return tienda.vender(
            [tienda.linea(pa, 1), tienda.linea(pb, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "177.00")],
        )

    def lista(self, usuario, empresa):
        r = cliente_de(usuario).get("/api/v1/ventas/", {"empresa": empresa.pk})
        assert r.status_code == 200, r.content
        return r.json()["results"]

    def test_la_empresa_que_vendio_ve_todo_el_carrito(self, tienda, mixta):
        (v,) = self.lista("admin", tienda.a)
        assert (v["total"], v["parcial"], v["mostrador"]) == ("177.00", False, tienda.a.pk)
        assert len(v["comprobantes"]) == 2

    def test_la_otra_empresa_ve_solo_su_parte_y_de_donde_viene(self, tienda, mixta):
        (v,) = self.lista("admin", tienda.b)
        assert v["id"] == mixta.pk and v["parcial"] is True
        assert [c["empresa"] for c in v["comprobantes"]] == [tienda.b.pk]
        assert v["total"] == "59.00" and v["mostrador"] == tienda.a.pk
        assert v["mostrador_nombre"]

    def test_no_se_repite_ni_aparece_en_una_empresa_ajena(self, tienda, mixta):
        assert len(self.lista("admin", tienda.a)) == 1
        assert len(self.lista("admin", tienda.b)) == 1

    def test_quien_solo_ve_una_empresa_ve_solo_sus_comprobantes(self, tienda, mixta, nuevo_usuario):
        nuevo_usuario(tienda.a.organizacion, "solo_b", [tienda.b], [("CONTADOR", None)])
        (v,) = self.lista("solo_b", tienda.b)
        assert v["parcial"] and v["total"] == "59.00"
        ficha = cliente_de("solo_b").get(f"/api/v1/ventas/{mixta.pk}/")
        assert ficha.status_code == 200, ficha.content
        d = ficha.json()
        assert [c["empresa"] for c in d["comprobantes"]] == [tienda.b.pk]
        assert d["parcial"] and d["total"] == "59.00"
        assert (
            cliente_de("solo_b").get("/api/v1/ventas/", {"empresa": tienda.a.pk}).status_code == 403
        )

    def test_la_ficha_completa_la_ve_quien_ve_ambas(self, tienda, mixta):
        d = cliente_de("admin").get(f"/api/v1/ventas/{mixta.pk}/").json()
        assert len(d["comprobantes"]) == 2 and d["parcial"] is False and d["total"] == "177.00"

    def test_quien_ve_una_sola_empresa_no_anula_la_venta(self, tienda, mixta, nuevo_usuario):
        nuevo_usuario(tienda.a.organizacion, "solo_b", [tienda.b], [("ADMIN", None)])
        r = cliente_de("solo_b").post(
            f"/api/v1/ventas/{mixta.pk}/anular/", {"motivo": "Prueba"}, format="json"
        )
        assert r.status_code == 403
