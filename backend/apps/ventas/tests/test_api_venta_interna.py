"""API de la venta interna: permiso especial, vista previa con un solo comprobante y detalle."""

from decimal import Decimal as D

import pytest

from apps.inventario.models import MovimientoInventario, OrigenMovimiento, SaldoStock
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas.models import Venta, VentaInterna

from .test_api import BASE, carrito, cuerpo, efectivo, linea, vender

pytestmark = pytest.mark.django_db


@pytest.fixture
def dueno(tienda, nuevo_usuario):
    """Quien tiene la venta interna: el superadministrador (el administrador la trae apagada)."""
    return nuevo_usuario(
        tienda.a.organizacion, "dueno", [tienda.a, tienda.b], [("SUPERADMIN", None)]
    )


def lineas_mixtas(tienda, mixto, cantidad_b=2):
    de_a, de_b = mixto
    return [linea(tienda, de_a, 1), linea(tienda, de_b, cantidad_b, empresa=tienda.b)]


def stock_de(tienda, producto, empresa):
    return (
        SaldoStock.objects.sin_ambito()
        .get(empresa=empresa, almacen=tienda.almacen(empresa), producto=producto)
        .cantidad
    )


class TestPermiso:
    def test_la_configuracion_dice_quien_puede_y_que_respaldos_hay(self, tienda, dueno):
        admin = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        assert admin["permisos"]["venta_interna"] is False  # viene apagado, se activa a mano
        jefe = cliente_de("dueno").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk}).json()
        assert jefe["permisos"]["venta_interna"] is True
        documentos = {d["codigo"]: d["motivo"] for d in jefe["venta_interna"]["documentos"]}
        assert documentos["INTERNO"] == ""
        assert "todavía no está disponible" in documentos["FACTURA"]

    def test_sin_el_permiso_no_se_puede_ni_previsualizar_ni_vender(self, tienda, mixto):
        for usuario in ("vendedor", "admin"):
            datos = cuerpo(
                tienda,
                lineas_mixtas(tienda, mixto),
                [efectivo(tienda, "354.00")],
                facturar_por=tienda.a.pk,
            )
            r = vender(usuario, datos)
            assert r.status_code == 403, (usuario, r.content)
            previa = cliente_de(usuario).post(
                f"{BASE}/previsualizar/",
                carrito(tienda, datos["lineas"], facturar_por=tienda.a.pk),
                format="json",
            )
            assert previa.status_code == 403
        assert (
            not Venta.objects.sin_ambito().exists()
            and not VentaInterna.objects.sin_ambito().exists()
        )
        assert stock_de(tienda, mixto[1], tienda.b) == D("10")

    def test_el_permiso_se_exige_en_las_dos_empresas(self, tienda, mixto, nuevo_usuario):
        """Con el permiso solo en A, no puede pasar mercadería de B."""
        nuevo_usuario(
            tienda.a.organizacion, "solo_en_a", [tienda.a, tienda.b], [("SUPERADMIN", tienda.a)]
        )
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto),
            [efectivo(tienda, "354.00")],
            facturar_por=tienda.a.pk,
        )
        assert vender("solo_en_a", datos).status_code == 403
        assert not VentaInterna.objects.sin_ambito().exists()


class TestVender:
    def test_un_solo_comprobante_y_el_detalle_cuenta_que_paso(self, tienda, dueno, mixto):
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto),
            [efectivo(tienda, "354.00")],
            facturar_por=tienda.a.pk,
        )

        r = vender("dueno", datos)

        assert r.status_code == 201, r.content
        venta = r.json()
        assert len(venta["comprobantes"]) == 1
        assert venta["comprobantes"][0]["empresa"] == tienda.a.pk
        (interna,) = venta["ventas_internas"]
        assert interna["empresa"] == tienda.b.pk and interna["empresa_destino"] == tienda.a.pk
        assert interna["documento"] == "INTERNO" and interna["estado"] == "EMITIDO"
        # El detalle no regala costos: eso es de quien ve la utilidad.
        assert "costo" not in str(venta["ventas_internas"]).lower()
        assert stock_de(tienda, mixto[1], tienda.b) == D("8")

    def test_al_reves_factura_la_otra_empresa(self, tienda, dueno, mixto):
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto, 1),
            [efectivo(tienda, "236.00")],
            facturar_por=tienda.b.pk,
        )
        r = vender("dueno", datos)
        assert r.status_code == 201, r.content
        assert r.json()["comprobantes"][0]["empresa"] == tienda.b.pk
        assert r.json()["ventas_internas"][0]["empresa"] == tienda.a.pk

    def test_sin_facturar_por_la_venta_mixta_sigue_con_dos_comprobantes(self, tienda, dueno, mixto):
        datos = cuerpo(tienda, lineas_mixtas(tienda, mixto, 1), [efectivo(tienda, "236.00")])
        r = vender("dueno", datos)
        assert r.status_code == 201
        assert len(r.json()["comprobantes"]) == 2 and r.json()["ventas_internas"] == []

    def test_la_factura_entre_empresas_se_rechaza_con_un_mensaje_claro(self, tienda, dueno, mixto):
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto, 1),
            [efectivo(tienda, "236.00")],
            facturar_por=tienda.a.pk,
            documento_interno="FACTURA",
        )
        r = vender("dueno", datos)
        assert r.status_code == 400 and "factura electrónica" in r.json()["error"]["mensaje"]
        assert stock_de(tienda, mixto[1], tienda.b) == D("10")

    def test_sin_stock_en_la_otra_empresa_lo_dice_y_no_deja_nada(self, tienda, dueno, mixto):
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto, 11),
            [efectivo(tienda, "1416.00")],
            facturar_por=tienda.a.pk,
        )
        r = vender("dueno", datos)
        assert r.status_code == 400 and "se necesitan 11.000" in r.json()["error"]["mensaje"]
        assert not Venta.objects.sin_ambito().exists()
        assert (
            not MovimientoInventario.objects.sin_ambito()
            .filter(origen=OrigenMovimiento.VENTA_INTERNA)
            .exists()
        )

    def test_un_reintento_con_la_misma_clave_no_pasa_la_mercaderia_dos_veces(
        self, tienda, dueno, mixto
    ):
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto),
            [efectivo(tienda, "354.00")],
            facturar_por=tienda.a.pk,
        )
        primera = vender("dueno", datos, llave="interna-0001")
        segunda = vender("dueno", datos, llave="interna-0001")
        assert primera.status_code == 201 and segunda.status_code == 201
        assert segunda["Idempotency-Replayed"] == "true"
        assert VentaInterna.objects.sin_ambito().count() == 1
        assert stock_de(tienda, mixto[1], tienda.b) == D("8")


class TestVistaPrevia:
    def previa(self, usuario, tienda, lineas, **extra):
        return cliente_de(usuario).post(
            f"{BASE}/previsualizar/", carrito(tienda, lineas, **extra), format="json"
        )

    def test_muestra_un_solo_comprobante_con_todo(self, tienda, dueno, mixto):
        r = self.previa("dueno", tienda, lineas_mixtas(tienda, mixto), facturar_por=tienda.a.pk)
        assert r.status_code == 200, r.content
        datos = r.json()
        assert [c["empresa"] for c in datos["comprobantes"]] == [tienda.a.pk]
        assert datos["total"] == "354.00" and datos["avisos"] == []
        assert sorted(ln["indice"] for ln in datos["comprobantes"][0]["lineas"]) == [0, 1]
        assert datos["venta_interna"] == {
            "facturar_por": tienda.a.pk,
            "documento": "INTERNO",
            "problemas": [],
            "entregan": [tienda.b.pk],
        }
        # Es solo una vista: no se movió nada.
        assert stock_de(tienda, mixto[1], tienda.b) == D("10")
        assert not VentaInterna.objects.sin_ambito().exists()

    def test_avisa_si_falta_stock_sin_fallar(self, tienda, dueno, mixto):
        r = self.previa("dueno", tienda, lineas_mixtas(tienda, mixto, 11), facturar_por=tienda.a.pk)
        assert r.status_code == 200
        (aviso,) = r.json()["avisos"]
        assert "se necesitan 11.000" in aviso
        assert r.json()["venta_interna"]["problemas"] == [aviso]

    def test_si_el_carrito_no_es_mixto_avisa_y_sigue_mostrando_la_venta(self, tienda, dueno, mixto):
        de_a, _ = mixto
        r = self.previa("dueno", tienda, [linea(tienda, de_a, 1)], facturar_por=tienda.a.pk)
        assert r.status_code == 200
        assert any("venta normal" in aviso for aviso in r.json()["avisos"])
        assert r.json()["venta_interna"] is None
        assert [c["empresa"] for c in r.json()["comprobantes"]] == [tienda.a.pk]

    def test_avisa_que_la_factura_entre_empresas_aun_no_existe(self, tienda, dueno, mixto):
        r = self.previa(
            "dueno",
            tienda,
            lineas_mixtas(tienda, mixto, 1),
            facturar_por=tienda.a.pk,
            documento_interno="FACTURA",
        )
        assert r.status_code == 200
        assert any("factura electrónica" in aviso for aviso in r.json()["avisos"])

    def test_con_series_no_falla_aunque_aun_esten_en_la_otra_empresa(self, tienda, dueno):
        from apps.inventario.models import OrigenMovimiento, TipoMovimiento
        from apps.inventario.movimientos import LineaNueva, registrar_movimiento

        celular = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        funda = tienda.producto("Funda", costo="10", precios={"PUBLICO": "30"})
        registrar_movimiento(
            empresa=tienda.b,
            almacen=tienda.almacen(tienda.b),
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=tienda.entorno.hoy,
            lineas=[LineaNueva(celular, D("1"), D("500"), series=("IMEI-777",))],
        )
        lineas = [
            linea(tienda, funda, 1),
            linea(tienda, celular, 1, empresa=tienda.b, series=["IMEI-777"]),
        ]
        r = self.previa("dueno", tienda, lineas, facturar_por=tienda.a.pk)
        assert r.status_code == 200, r.content
        assert r.json()["avisos"] == [] and len(r.json()["comprobantes"]) == 1


class TestDeshacerPorApi:
    def hecha(self, tienda, mixto):
        datos = cuerpo(
            tienda,
            lineas_mixtas(tienda, mixto),
            [efectivo(tienda, "354.00")],
            facturar_por=tienda.a.pk,
        )
        return vender("dueno", datos).json()

    def test_anular_la_venta_deshace_tambien_la_venta_interna(self, tienda, dueno, mixto):
        venta = self.hecha(tienda, mixto)

        r = cliente_de("dueno").post(
            f"{BASE}/{venta['id']}/anular/", {"motivo": "Error de precio"}, format="json"
        )

        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "ANULADO"
        (interna,) = r.json()["ventas_internas"]
        assert interna["estado"] == "ANULADO" and interna["devolucion"] == "NINGUNA"
        assert stock_de(tienda, mixto[1], tienda.b) == D("10")

    def test_sin_el_permiso_de_anular_en_la_empresa_que_entrego_no_se_anula(
        self, tienda, dueno, mixto, nuevo_usuario
    ):
        venta = self.hecha(tienda, mixto)
        nuevo_usuario(
            tienda.a.organizacion, "jefe_de_a", [tienda.a, tienda.b], [("SUPERADMIN", tienda.a)]
        )

        r = cliente_de("jefe_de_a").post(
            f"{BASE}/{venta['id']}/anular/", {"motivo": "Prueba"}, format="json"
        )

        assert r.status_code in (403, 404), r.content
        assert stock_de(tienda, mixto[1], tienda.b) == D("8")
        assert VentaInterna.objects.sin_ambito().get().estado == "EMITIDO"

    def test_la_pantalla_de_devolucion_dice_a_quien_vuelve_cada_linea(self, tienda, dueno, mixto):
        venta = self.hecha(tienda, mixto)
        comprobante = venta["comprobantes"][0]["id"]

        r = cliente_de("dueno").get(f"{BASE}/comprobantes/{comprobante}/devolucion/")

        assert r.status_code == 200, r.content
        destino = {ln["descripcion"]: ln["vuelve_a"] for ln in r.json()["lineas"]}
        assert destino["Cargador"] != "" and destino["Audífonos"] == ""

    def test_devolver_por_la_api_manda_la_mercaderia_a_su_dueña(self, tienda, dueno, mixto):
        venta = self.hecha(tienda, mixto)
        comprobante = venta["comprobantes"][0]
        linea = next(ln for ln in comprobante["lineas"] if ln["descripcion"] == "Cargador")

        r = cliente_de("dueno").post(
            f"{BASE}/comprobantes/{comprobante['id']}/nota-credito/",
            {
                "motivo": "07",
                "lineas": [{"linea": linea["id"], "cantidad": "1"}],
                "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "118.00"}],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="devolucion-interna-001",
        )

        assert r.status_code == 201, r.content
        assert stock_de(tienda, mixto[1], tienda.b) == D("9")
        detalle = cliente_de("dueno").get(f"{BASE}/{venta['id']}/").json()
        assert detalle["ventas_internas"][0]["devolucion"] == "PARCIAL"

    def test_devolver_pide_el_permiso_tambien_en_la_empresa_que_entrego(
        self, tienda, dueno, mixto, nuevo_usuario
    ):
        venta = self.hecha(tienda, mixto)
        comprobante = venta["comprobantes"][0]
        linea = next(ln for ln in comprobante["lineas"] if ln["descripcion"] == "Cargador")
        nuevo_usuario(
            tienda.a.organizacion, "jefe_de_a", [tienda.a, tienda.b], [("SUPERADMIN", tienda.a)]
        )
        cuerpo_nota = {
            "motivo": "07",
            "lineas": [{"linea": linea["id"], "cantidad": "1"}],
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "118.00"}],
        }

        r = cliente_de("jefe_de_a").post(
            f"{BASE}/comprobantes/{comprobante['id']}/nota-credito/",
            cuerpo_nota,
            format="json",
            HTTP_IDEMPOTENCY_KEY="devolucion-interna-002",
        )

        assert r.status_code == 403, r.content
        assert stock_de(tienda, mixto[1], tienda.b) == D("8")
