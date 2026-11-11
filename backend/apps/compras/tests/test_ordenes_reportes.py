"""Reposición sugerida, reportes de órdenes de compra y aviso de órdenes atrasadas."""

# Las fixtures de otros módulos de prueba se importan para usarlas (patrón del proyecto).
# ruff: noqa: F811

from datetime import timedelta
from decimal import Decimal
from io import BytesIO

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.auditoria.models import AuditoriaEvento
from apps.caja.alertas import alertas
from apps.core.tenant import establecer_contexto
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)
from .test_api import clave, cuerpo, datos, registrar  # noqa: F401
from .test_api_ordenes import accion, nueva, recibir

pytestmark = pytest.mark.django_db

BASE = "/api/v1/compras"
HOY = timezone.localdate


def comprar_stock(datos, producto, cantidad, **extra):
    """Compra por la API: deja `cantidad` unidades de `producto` en el almacén."""
    total = f"{float(cantidad) * 10 * 1.18:.2f}"
    c = cuerpo(
        datos,
        producto,
        lineas=[{"producto": producto.pk, "cantidad": str(cantidad), "precio_unitario": "10"}],
        pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": total}],
        **extra,
    )
    r = registrar(cliente_de("almacenero"), c)
    assert r.status_code == 201, r.content
    return r.json()


def sugerencias(datos, usuario="almacenero", **extra):
    return cliente_de(usuario).get(
        f"{BASE}/ordenes/reposicion/",
        {"empresa": datos.mundo.e1.pk, "almacen": datos.mundo.alm[1].pk, **extra},
    )


def productos_de(respuesta):
    return {p["nombre"]: p for g in respuesta.json()["grupos"] for p in g["productos"]}


class TestReposicion:
    def test_sugiere_hasta_el_doble_del_minimo_al_proveedor_de_la_ultima_compra(self, datos):
        p = datos.mundo.producto("Cemento", stock_minimo=Decimal("10"), costo=Decimal("7"))
        comprar_stock(datos, p, 4)
        r = sugerencias(datos)
        assert r.status_code == 200, r.content
        j = r.json()
        assert (j["hasta"], j["total_productos"], j["almacen"]) == ("2", 1, datos.mundo.alm[1].pk)
        grupo = j["grupos"][0]
        assert grupo["proveedor"]["nombre"] == "Distribuidora Selva"
        fila = grupo["productos"][0]
        assert (fila["stock"], fila["minimo"], fila["en_camino"], fila["sugerido"]) == (
            "4.000",
            "10.000",
            "0.000",
            "16.000",
        )
        assert fila["precio_estimado"] == "7.0000" and fila["ultima_compra"]

    def test_lo_que_ya_viene_en_ordenes_emitidas_se_descuenta(self, datos):
        p = datos.mundo.producto("Cemento", stock_minimo=Decimal("10"))
        comprar_stock(datos, p, 4)
        o = nueva(datos, producto=p)
        accion("admin", o["id"], "emitir")
        # 4 en el almacén + 10 que vienen: ya pasa el mínimo, no hace falta pedir
        assert sugerencias(datos).json()["total_productos"] == 0

    def test_una_orden_en_camino_chica_solo_reduce_lo_sugerido(self, datos):
        p = datos.mundo.producto("Cemento", stock_minimo=Decimal("10"))
        comprar_stock(datos, p, 4)
        o = nueva(
            datos, producto=p, lineas=[{"producto": p.pk, "cantidad": "3", "precio_unitario": "10"}]
        )
        accion("admin", o["id"], "emitir")
        fila = productos_de(sugerencias(datos))["Cemento"]
        assert (fila["en_camino"], fila["sugerido"]) == ("3.000", "13.000")  # 20 - 4 - 3

    def test_una_orden_en_borrador_no_cuenta_como_en_camino(self, datos):
        p = datos.mundo.producto("Cemento", stock_minimo=Decimal("10"))
        comprar_stock(datos, p, 4)
        nueva(datos, producto=p)
        assert productos_de(sugerencias(datos))["Cemento"]["en_camino"] == "0.000"

    def test_sin_compras_previas_va_en_el_grupo_sin_proveedor_y_al_final(self, datos):
        con = datos.mundo.producto("Con historia", stock_minimo=Decimal("5"))
        comprar_stock(datos, con, 1)
        datos.mundo.producto("Nuevo", stock_minimo=Decimal("5"))
        grupos = sugerencias(datos).json()["grupos"]
        assert [g["proveedor"] is None for g in grupos] == [False, True]
        assert grupos[1]["productos"][0]["nombre"] == "Nuevo"
        assert grupos[1]["productos"][0]["stock"] == "0.000"

    def test_no_sugiere_lo_que_no_hace_falta(self, datos):
        arriba = datos.mundo.producto("Arriba del mínimo", stock_minimo=Decimal("3"))
        comprar_stock(datos, arriba, 10)
        datos.mundo.producto("Sin mínimo")  # stock_minimo 0
        assert sugerencias(datos).json()["total_productos"] == 0

    def test_el_multiplo_se_puede_cambiar_y_se_valida(self, datos):
        p = datos.mundo.producto("Cemento", stock_minimo=Decimal("10"))
        comprar_stock(datos, p, 4)
        assert productos_de(sugerencias(datos, hasta="3"))["Cemento"]["sugerido"] == "26.000"
        for malo in ("0.5", "11", "abc"):
            assert sugerencias(datos, hasta=malo).status_code == 400, malo

    def test_almacen_obligatorio_y_de_la_empresa(self, datos):
        api = cliente_de("almacenero")
        e = datos.mundo.e1.pk
        assert api.get(f"{BASE}/ordenes/reposicion/", {"empresa": e}).status_code == 400
        r = api.get(f"{BASE}/ordenes/reposicion/", {"empresa": e, "almacen": datos.mundo.alm[2].pk})
        assert r.status_code == 400

    def test_permisos(self, datos):
        assert sugerencias(datos, "admin").status_code == 200
        for usuario in ("contador", "vendedor", "vendedor_a2"):
            assert sugerencias(datos, usuario).status_code == 403, usuario


def preparar(datos):
    """Una orden de 10 a 10, con entrega vencida (ayer), de la que se reciben 4 a precio 11."""
    ayer = (HOY() - timedelta(days=1)).isoformat()
    antes = (HOY() - timedelta(days=2)).isoformat()
    o = nueva(datos, fecha_emision=antes, fecha_entrega=ayer)
    accion("admin", o["id"], "emitir")
    recibir(datos, o, "4", precio="11")
    return o


def reporte(datos, usuario="contador", ruta="vista/", **extra):
    return cliente_de(usuario).get(
        f"{BASE}/reportes/ordenes/{ruta}",
        {
            "empresa": datos.mundo.e1.pk,
            "desde": (HOY() - timedelta(days=10)).isoformat(),
            "hasta": HOY().isoformat(),
            **extra,
        },
    )


class TestReportes:
    def test_pendientes_de_recibir(self, datos):
        preparar(datos)
        j = reporte(datos).json()["pendientes"]
        assert (j["total_filas"], j["atrasadas"], j["valor"]) == (1, 1, {"PEN": "60.00"})
        f = j["filas"][0]
        assert (f["dias_atraso"], f["pedido"], f["recibido"], f["pendiente"], f["valor"]) == (
            1,
            "10.000",
            "4.000",
            "6.000",
            "60.00",
        )
        assert f["codigo"].startswith("OC-") and f["proveedor"] == "Distribuidora Selva"

    def test_lo_recibido_por_completo_ya_no_esta_pendiente(self, datos):
        o = preparar(datos)
        recibir(datos, o, "6")
        assert reporte(datos).json()["pendientes"]["total_filas"] == 0

    def test_cumplimiento_por_proveedor(self, datos):
        preparar(datos)
        c = reporte(datos).json()["cumplimiento"]
        assert len(c) == 1
        f = c[0]
        assert (f["proveedor"], f["moneda"], f["ordenes"], f["parciales"]) == (
            "Distribuidora Selva",
            "PEN",
            1,
            1,
        )
        assert (f["pedido"], f["recibido"], f["cumplimiento"]) == ("100.00", "40.00", "40.00")
        assert f["dias_promedio"] == "2.0" and f["con_fecha"] == 0

    def test_entregas_a_tiempo_y_tardias(self, datos):
        tarde = preparar(datos)
        recibir(datos, tarde, "6")  # llega hoy, la entrega pactada era ayer
        a_tiempo = nueva(datos, fecha_entrega=(HOY() + timedelta(days=3)).isoformat())
        accion("admin", a_tiempo["id"], "emitir")
        recibir(datos, a_tiempo, "10")
        f = reporte(datos).json()["cumplimiento"][0]
        assert (f["ordenes"], f["recibidas"], f["con_fecha"], f["a_tiempo"]) == (2, 2, 2, 1)
        assert f["cumplimiento"] == "100.00"

    def test_borrador_y_anuladas_no_cuentan(self, datos):
        nueva(datos)  # borrador
        o = nueva(datos)
        accion("admin", o["id"], "anular", {"motivo": "Error"})
        j = reporte(datos).json()
        assert j["cumplimiento"] == [] and j["pendientes"]["total_filas"] == 0

    def test_diferencias_de_precio(self, datos):
        preparar(datos)
        j = reporte(datos).json()["diferencias"]
        assert (j["total_filas"], j["lineas_comparadas"], j["impacto"]) == (1, 1, {"PEN": "4.00"})
        f = j["filas"][0]
        assert (f["cantidad"], f["precio_pactado"], f["precio_facturado"], f["diferencia"]) == (
            "4.000",
            "10.0000",
            "11.0000",
            "1.0000",
        )
        assert (f["porcentaje"], f["impacto"]) == ("10.00", "4.00")

    def test_las_lineas_sin_diferencia_se_cuentan_pero_no_se_listan(self, datos):
        o = preparar(datos)
        recibir(datos, o, "6", precio="10")
        j = reporte(datos).json()["diferencias"]
        assert (j["total_filas"], j["lineas_comparadas"]) == (1, 2)

    def test_una_compra_anulada_no_entra(self, datos):
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        c = recibir(datos, o, "4", precio="11").json()
        cliente_de("admin").post(f"{BASE}/{c['id']}/anular/", {"motivo": "Error"}, format="json")
        j = reporte(datos).json()["diferencias"]
        assert (j["total_filas"], j["lineas_comparadas"]) == (0, 0)

    def test_el_precio_con_igv_se_compara_sin_igv(self, datos):
        # Orden: 10,00 sin IGV. Factura: 11,80 con IGV = 10,00 sin IGV → no hay diferencia.
        o = nueva(datos)
        accion("admin", o["id"], "emitir")
        linea = o["lineas"][0]
        c = cuerpo(
            datos,
            fecha_emision=HOY().isoformat(),
            orden=o["id"],
            precios_incluyen_igv=True,
            lineas=[{"producto": linea["producto"], "cantidad": "2", "precio_unitario": "11.80"}],
            pagos=[{"medio_pago": datos.efectivo.pk, "cuenta": datos.caja.pk, "monto": "23.60"}],
        )
        assert registrar(cliente_de("almacenero"), c).status_code == 201
        j = reporte(datos).json()["diferencias"]
        assert (j["total_filas"], j["lineas_comparadas"]) == (0, 1)

    def test_permisos_y_rango(self, datos):
        preparar(datos)
        assert reporte(datos, "admin").status_code == 200
        for usuario in ("almacenero", "vendedor", "vendedor_a2"):
            assert reporte(datos, usuario).status_code == 403, usuario
        api = cliente_de("contador")
        base = {"empresa": datos.mundo.e1.pk}
        assert api.get(f"{BASE}/reportes/ordenes/vista/", base).status_code == 400
        largo = {
            **base,
            "desde": (HOY() - timedelta(days=400)).isoformat(),
            "hasta": HOY().isoformat(),
        }
        assert api.get(f"{BASE}/reportes/ordenes/vista/", largo).status_code == 400

    def test_excel_con_tres_hojas_y_auditoria(self, datos):
        preparar(datos)
        r = reporte(datos, ruta="")
        assert r.status_code == 200, r.content
        assert "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith('attachment; filename="ordenes-compra_')
        libro = load_workbook(BytesIO(r.content))
        assert libro.sheetnames == [
            "Pendientes de recibir",
            "Cumplimiento por proveedor",
            "Diferencias de precio",
        ]
        pend = [
            [c.value for c in f]
            for f in libro["Pendientes de recibir"].iter_rows(min_row=7, max_row=9)
        ]
        assert pend[0][0] == "Orden" and pend[1][3] == 1 and pend[1][11] == 6 and pend[1][13] == 60
        assert pend[2][7] == "VALOR PENDIENTE EN PEN" and pend[2][13] == 60
        cump = [
            [c.value for c in f]
            for f in libro["Cumplimiento por proveedor"].iter_rows(min_row=8, max_row=8)
        ]
        assert cump[0][2] == "Distribuidora Selva" and cump[0][10] == 40
        dif = [
            [c.value for c in f]
            for f in libro["Diferencias de precio"].iter_rows(min_row=8, max_row=9)
        ]
        assert dif[0][9] == 10 and dif[0][10] == 11 and dif[0][13] == 4
        assert dif[1][6] == "EFECTO TOTAL EN PEN" and dif[1][13] == 4
        assert AuditoriaEvento.objects.filter(accion="compras.ordenes_exportadas").exists()

    def test_los_nombres_con_formula_se_escriben_como_texto(self, datos):
        datos.proveedor.nombre = '=HYPERLINK("http://malo")'
        datos.proveedor.save()
        preparar(datos)
        r = reporte(datos, ruta="")
        libro = load_workbook(BytesIO(r.content))
        assert libro["Pendientes de recibir"].cell(row=8, column=5).data_type == "s"
        assert libro["Cumplimiento por proveedor"].cell(row=8, column=3).data_type == "s"
        assert libro["Diferencias de precio"].cell(row=8, column=5).data_type == "s"

    def test_excel_sin_permiso(self, datos):
        for usuario in ("almacenero", "vendedor"):
            assert reporte(datos, usuario, ruta="").status_code == 403, usuario


class TestAvisos:
    def _avisos(self, datos):
        e = datos.mundo.e
        establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
        return {a["codigo"]: a for a in alertas(datos.mundo.e1)}

    def test_ordenes_atrasadas(self, datos):
        assert "ordenes_atrasadas" not in self._avisos(datos)
        preparar(datos)
        a = self._avisos(datos)["ordenes_atrasadas"]
        assert a["nivel"] == "aviso" and a["titulo"].startswith("1 órdenes")
        assert a["enlace"] == "/compras/ordenes?atrasadas=1"

    def test_una_orden_a_tiempo_no_avisa(self, datos):
        o = nueva(datos, fecha_entrega=(HOY() + timedelta(days=3)).isoformat())
        accion("admin", o["id"], "emitir")
        assert "ordenes_atrasadas" not in self._avisos(datos)

    def test_ordenes_por_aprobar(self, datos):
        cliente_de("admin").patch(
            f"{BASE}/ordenes/configuracion/",
            {"empresa": datos.mundo.e1.pk, "monto_aprobacion": "100"},
            format="json",
        )
        o = nueva(datos)
        accion("almacenero", o["id"], "emitir")
        a = self._avisos(datos)["ordenes_por_aprobar"]
        assert a["nivel"] == "info" and a["enlace"] == "/compras/ordenes?estado=PENDIENTE"
