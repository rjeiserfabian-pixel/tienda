"""Notas de crédito: devolver stock, corregir lo que se debe y reembolsar el resto."""

import itertools
from decimal import Decimal as D

import pytest

from apps.caja.models import MovimientoCaja, Origen
from apps.caja.servicios import saldo_de
from apps.inventario.models import SaldoStock, SerieProducto
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import credito, cuentas_por_cobrar, notas_credito, servicios
from apps.ventas.exceptions import VentaInvalida, VentaNoAnulable
from apps.ventas.models import CuotaVenta, LineaNotaCredito, MotivoNota, NotaCredito

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


def stock(tienda, producto, empresa=None):
    empresa = empresa or tienda.a
    return SaldoStock.objects.get(
        empresa=empresa, almacen=tienda.almacen(empresa), producto=producto
    ).cantidad


def devolver(comprobante, linea, cantidad, **extra):
    return notas_credito.LineaDevuelta(linea, D(str(cantidad)), **extra)


def nota(tienda, comprobante, devueltas, reembolsos, motivo="07", **extra):
    return notas_credito.crear_nota_credito(
        comprobante, motivo=motivo, devueltas=devueltas, reembolsos=reembolsos, **extra
    )


@pytest.fixture
def venta(tienda):
    """Dos unidades a 100 (sin IGV): 236,00 cobrados en efectivo; costo 50 cada una."""
    producto = tienda.producto(costo="50", precios={"PUBLICO": "100"})
    v = tienda.vender(
        [tienda.linea(producto, 2)],
        [tienda.cobro(tienda.efectivo, "236.00")],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
    )
    comp = v.comprobantes.get()
    return type(
        "V", (), {"venta": v, "comp": comp, "linea": comp.lineas.get(), "producto": producto}
    )


class TestDevolucionParcial:
    def test_vuelve_el_stock_y_se_reembolsa_lo_devuelto(self, tienda, venta):
        n = nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        assert n.numero_completo == "FC01-00000001"
        assert (n.op_gravada, n.igv, n.total, n.a_cuotas, n.reembolsado) == (
            D("100.00"),
            D("18.00"),
            D("118.00"),
            D("0"),
            D("118.00"),
        )
        assert stock(tienda, venta.producto) == D("9")  # 10 − 2 vendidas + 1 devuelta
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("118.00")  # 236 cobrados − 118 devueltos
        egreso = MovimientoCaja.objects.sin_ambito().get(origen_tipo=Origen.REEMBOLSO_VENTA)
        assert (egreso.tipo, egreso.monto) == ("EGRESO", D("118.00"))
        (ln,) = n.lineas.all()
        assert (ln.cantidad, ln.costo_total) == (D("1"), D("50.00"))

    def test_lo_devuelto_vuelve_al_mismo_costo_con_que_salio(self, tienda, venta):
        antes = SaldoStock.objects.get(producto=venta.producto, empresa=tienda.a)
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 2)],
            [tienda.cobro(tienda.efectivo, "236.00")],
        )
        despues = SaldoStock.objects.get(producto=venta.producto, empresa=tienda.a)
        assert despues.cantidad == antes.cantidad + 2
        assert despues.costo_unitario == D("50")

    def test_sin_reingreso_el_stock_no_cambia(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            reingresa_stock=False,
        )
        assert stock(tienda, venta.producto) == D("8")

    def test_no_se_devuelve_mas_de_lo_vendido_ni_dos_veces_lo_mismo(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="solo se pueden devolver"):
            nota(tienda, venta.comp, [devolver(venta.comp, venta.linea, 3)], [])
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 2)],
            [tienda.cobro(tienda.efectivo, "236.00")],
        )
        with pytest.raises(VentaInvalida, match="ya se devolvieron 2"):
            nota(tienda, venta.comp, [devolver(venta.comp, venta.linea, 1)], [])
        assert NotaCredito.objects.sin_ambito().count() == 1

    def test_los_reembolsos_deben_sumar_lo_que_se_devuelve_en_dinero(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="deben sumar"):
            nota(
                tienda,
                venta.comp,
                [devolver(venta.comp, venta.linea, 1)],
                [tienda.cobro(tienda.efectivo, "100.00")],
            )
        assert not NotaCredito.objects.sin_ambito().exists()
        assert stock(tienda, venta.producto) == D("8")

    def test_se_puede_reembolsar_con_varios_metodos(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [
                tienda.cobro(tienda.efectivo, "18.00"),
                tienda.cobro(tienda.yape, "100.00", referencia="OP-5"),
            ],
        )
        assert saldo_de(tienda.billeteras[tienda.a.pk]) == D("-100.00")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("218.00")

    def test_el_metodo_con_operacion_la_exige(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="número de operación"):
            nota(
                tienda,
                venta.comp,
                [devolver(venta.comp, venta.linea, 1)],
                [tienda.cobro(tienda.yape, "118.00")],
            )


class TestCentimos:
    def test_las_devoluciones_suman_exactamente_lo_que_se_vendio(self, tienda):
        p = tienda.producto(costo="5", precios={"PUBLICO": "10.01"})
        v = tienda.vender([tienda.linea(p, 3)], [tienda.cobro(tienda.efectivo, "35.44")])
        comp = v.comprobantes.get()
        linea = comp.lineas.get()
        assert (linea.valor_venta, linea.igv, linea.total) == (D("30.03"), D("5.41"), D("35.44"))
        total = D("0")
        for _ in range(3):
            n = nota(
                tienda,
                comp,
                [devolver(comp, linea, 1)],
                [tienda.cobro(tienda.efectivo, str(_total_de_una(comp, linea)))],
            )
            total += n.total
        assert total == comp.total
        assert sum(ln.valor_venta for ln in LineaNotaCredito.objects.sin_ambito().all()) == (
            linea.valor_venta
        )
        assert sum(ln.igv for ln in LineaNotaCredito.objects.sin_ambito().all()) == linea.igv


def _total_de_una(comp, linea):
    """Lo que vale devolver una unidad más de la línea (calculado por el sistema)."""
    pendiente = notas_credito.calcular_nota(comp, [devolver(comp, linea, 1)])
    return pendiente.total


class TestTotal:
    def test_una_devolucion_total_devuelve_todo_lo_pendiente(self, tienda, venta):
        n = nota(
            tienda,
            venta.comp,
            None,
            [tienda.cobro(tienda.efectivo, "236.00")],
            motivo=MotivoNota.DEVOLUCION_TOTAL,
        )
        assert n.total == venta.comp.total and n.motivo == "06"
        assert stock(tienda, venta.producto) == D("10")
        with pytest.raises(VentaInvalida, match="por completo"):
            nota(tienda, venta.comp, None, [], motivo=MotivoNota.DEVOLUCION_TOTAL)

    def test_total_despues_de_una_parcial_devuelve_solo_lo_que_falta(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        n = nota(
            tienda,
            venta.comp,
            None,
            [tienda.cobro(tienda.efectivo, "118.00")],
            motivo=MotivoNota.DEVOLUCION_TOTAL,
        )
        assert n.total == D("118.00")


class TestSinStockYSeries:
    def test_un_servicio_se_devuelve_sin_mover_stock(self, tienda):
        s = tienda.producto(
            "Instalación", costo="20", stock={}, tipo="SERVICIO", controla_stock=False
        )
        v = tienda.vender(
            [servicios.LineaEntrada(s, D("1"), tienda.a)], [tienda.cobro(tienda.efectivo, "118.00")]
        )
        comp = v.comprobantes.get()
        n = nota(
            tienda,
            comp,
            [devolver(comp, comp.lineas.get(), 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        assert n.lineas.get().movimiento is None

    def test_las_series_devueltas_vuelven_al_stock(self, tienda):
        from apps.inventario.models import TipoMovimiento
        from apps.inventario.movimientos import LineaNueva, registrar_movimiento

        p = tienda.producto(
            "Celular", costo="500", precios={"PUBLICO": "800"}, stock={}, lleva_serie=True
        )
        registrar_movimiento(
            empresa=tienda.a,
            almacen=tienda.almacen(tienda.a),
            tipo=TipoMovimiento.ENTRADA,
            origen="COMPRA",
            fecha=tienda.entorno.hoy,
            lineas=[LineaNueva(p, D("2"), D("500"), series=("IMEI-1", "IMEI-2"))],
        )
        v = tienda.vender(
            [tienda.linea(p, 1, series=("IMEI-1",))],
            [tienda.cobro(tienda.efectivo, "944.00")],
            tipo_comprobante="NV",
        )
        comp = v.comprobantes.get()
        linea = comp.lineas.get()
        with pytest.raises(VentaInvalida, match="serie"):
            nota(tienda, comp, [devolver(comp, linea, 1)], [])
        with pytest.raises(VentaInvalida, match="no se vendieron"):
            nota(tienda, comp, [devolver(comp, linea, 1, series=("IMEI-2",))], [])
        nota(
            tienda,
            comp,
            [devolver(comp, linea, 1, series=("imei-1",))],
            [tienda.cobro(tienda.efectivo, "944.00")],
        )
        assert (
            SerieProducto.objects.sin_ambito().filter(numero="IMEI-1", estado="EN_STOCK").count()
            == 1
        )


class TestACredito:
    def test_primero_se_reduce_lo_que_debe_y_solo_el_resto_se_reembolsa(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})
        cliente = tienda.cliente("1000")
        v = tienda.credito([tienda.linea(p, 1)], cliente=cliente)  # 141,60 en 3 cuotas de 47,20
        comp = v.comprobantes.get()
        cuentas_por_cobrar.registrar_abonos(comp, abonos=[tienda.cobro(tienda.efectivo, "47.20")])
        n = nota(
            tienda,
            comp,
            [devolver(comp, comp.lineas.get(), 1)],
            [tienda.cobro(tienda.efectivo, "47.20")],
        )
        # De los 141,60: 94,40 se debían todavía (cuotas 3 y 2) y 47,20 ya estaban cobrados.
        assert (n.total, n.a_cuotas, n.reembolsado) == (D("141.60"), D("94.40"), D("47.20"))
        cuotas = list(CuotaVenta.objects.sin_ambito().filter(comprobante=comp).order_by("numero"))
        assert [c.monto for c in cuotas] == [D("47.20"), D("0.00"), D("0.00")]
        assert cuentas_por_cobrar.saldo_de(comp) == D("0")
        assert credito.deuda_en_soles(cliente) == D("0.00")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0.00")  # abono entró y se devolvió

    def test_una_devolucion_menor_a_la_deuda_no_lleva_reembolso(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})
        cliente = tienda.cliente("1000")
        v = tienda.credito([tienda.linea(p, 2)], cliente=cliente)  # 283,20
        comp = v.comprobantes.get()
        n = nota(tienda, comp, [devolver(comp, comp.lineas.get(), 1)], [])
        assert (n.total, n.a_cuotas, n.reembolsado) == (D("141.60"), D("141.60"), D("0"))
        assert cuentas_por_cobrar.saldo_de(comp) == D("141.60")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("0")
        assert credito.deuda_en_soles(cliente) == D("141.60")

    def test_una_reduccion_no_deja_pagar_mas_de_lo_que_queda(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})
        v = tienda.credito([tienda.linea(p, 2)], cliente=tienda.cliente("1000"))
        comp = v.comprobantes.get()
        nota(tienda, comp, [devolver(comp, comp.lineas.get(), 1)], [])
        with pytest.raises(VentaInvalida, match="más de lo que se debe"):
            cuentas_por_cobrar.registrar_abonos(
                comp, abonos=[tienda.cobro(tienda.efectivo, "141.61")]
            )


class TestAnularYCasos:
    def test_un_comprobante_con_notas_no_se_anula(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        with pytest.raises(VentaNoAnulable, match="notas de crédito"):
            servicios.anular_comprobante(venta.comp, motivo="Error")

    def test_un_comprobante_anulado_no_admite_notas(self, tienda, venta):
        servicios.anular_venta(venta.venta, motivo="Error")
        venta.comp.refresh_from_db()
        with pytest.raises(VentaInvalida, match="anulado"):
            nota(tienda, venta.comp, [devolver(venta.comp, venta.linea, 1)], [])

    def test_sin_serie_de_nota_de_credito_no_se_puede_emitir(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("07")
        ).update(estado="INACTIVO")
        with pytest.raises(VentaInvalida, match="serie"):
            nota(
                tienda,
                venta.comp,
                [devolver(venta.comp, venta.linea, 1)],
                [tienda.cobro(tienda.efectivo, "118.00")],
            )

    def test_cada_empresa_devuelve_lo_suyo(self, tienda):
        pa = tienda.producto("Cable", costo="10", precios={"PUBLICO": "30"}, stock={tienda.a: 10})
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        v = tienda.vender(
            [tienda.linea(pa, 2), tienda.linea(pb, 1, empresa=tienda.b)],
            [tienda.cobro(tienda.efectivo, "129.80")],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
        )
        a, b = v.comprobantes.order_by("id")
        n = nota(
            tienda,
            b,
            [devolver(b, b.lineas.get(), 1)],
            [tienda.cobro(tienda.efectivo, "59.00")],
        )
        assert (n.empresa, n.serie) == (tienda.b, "FC02")
        assert stock(tienda, pb, tienda.b) == D("10")
        assert saldo_de(tienda.cajas[tienda.b.pk]) == D("0")
        assert saldo_de(tienda.cajas[tienda.a.pk]) == D("70.80")


def emitir(usuario, comprobante_id, cuerpo):
    return cliente_de(usuario).post(
        f"{BASE}/comprobantes/{comprobante_id}/nota-credito/",
        cuerpo,
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"nota-credito-{next(_claves):06d}",
    )


class TestApi:
    def test_ve_lo_pendiente_calcula_y_emite(self, tienda, venta):
        c = cliente_de("admin")
        pendiente = c.get(f"{BASE}/comprobantes/{venta.comp.pk}/devolucion/").json()
        (ln,) = pendiente["lineas"]
        assert ln["disponible"] == "2.000" and pendiente["a_credito"] is False
        cuerpo = {
            "motivo": "07",
            "lineas": [{"linea": ln["id"], "cantidad": "1"}],
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "118.00"}],
        }
        previo = c.post(
            f"{BASE}/comprobantes/{venta.comp.pk}/nota-credito/previsualizar/",
            cuerpo,
            format="json",
        ).json()
        assert (previo["total"], previo["a_cuotas"], previo["a_reembolsar"]) == (
            "118.00",
            "0",
            "118.00",
        )
        r = emitir("admin", venta.comp.pk, cuerpo)
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["numero_completo"] == "FC01-00000001" and d["reembolsado"] == "118.00"
        assert d["lineas"][0]["cantidad"] == "1.000" and d["reembolsos"][0]["monto"] == "118.00"
        assert d["emisor"]["ruc"] == tienda.a.ruc and "costo" not in str(d).lower()
        # Para dibujar el logo de la empresa en la nota impresa (la imagen se pide aparte).
        assert d["emisor"]["empresa"] == tienda.a.pk and d["emisor"]["tiene_logo"] is False
        despues = c.get(f"{BASE}/comprobantes/{venta.comp.pk}/devolucion/").json()
        assert despues["lineas"][0]["disponible"] == "1.000"

    def test_el_vendedor_no_emite_notas_de_credito(self, tienda, venta):
        cuerpo = {
            "motivo": "06",
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "236"}],
        }
        assert emitir("vendedor", venta.comp.pk, cuerpo).status_code == 403
        r = cliente_de("vendedor").get(f"{BASE}/comprobantes/{venta.comp.pk}/devolucion/")
        assert r.status_code == 403
        assert not NotaCredito.objects.sin_ambito().exists()

    def test_devolucion_total_y_un_reintento_no_devuelve_dos_veces(self, tienda, venta):
        cuerpo = {
            "motivo": "06",
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "236.00"}],
        }
        c = cliente_de("admin")
        for _ in range(2):
            r = c.post(
                f"{BASE}/comprobantes/{venta.comp.pk}/nota-credito/",
                cuerpo,
                format="json",
                HTTP_IDEMPOTENCY_KEY="nota-clave-001",
            )
            assert r.status_code == 201
        assert NotaCredito.objects.sin_ambito().count() == 1

    def test_errores_claros(self, tienda, venta):
        mal = {"motivo": "07", "lineas": [{"linea": venta.linea.pk, "cantidad": "5"}]}
        r = emitir("admin", venta.comp.pk, mal)
        assert r.status_code == 400 and "solo se pueden devolver" in r.json()["error"]["mensaje"]
        ajena = {"motivo": "07", "lineas": [{"linea": 999999, "cantidad": "1"}]}
        assert emitir("admin", venta.comp.pk, ajena).status_code == 400

    def test_lista_y_detalle(self, tienda, venta):
        cuerpo = {
            "motivo": "06",
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "236.00"}],
        }
        nota_id = emitir("admin", venta.comp.pk, cuerpo).json()["id"]
        c = cliente_de("vendedor")
        lista = c.get(f"{BASE}/notas-credito/", {"empresa": tienda.a.pk}).json()
        assert lista["count"] == 1
        fila = lista["results"][0]
        assert (fila["numero_completo"], fila["motivo_nombre"], fila["total"]) == (
            "FC01-00000001",
            "Devolución total",
            "236.00",
        )
        assert c.get(f"{BASE}/notas-credito/{nota_id}/").status_code == 200


class TestAnulacionDeLaOperacion:
    def test_devuelve_todo_el_comprobante(self, tienda, venta):
        n = nota(
            tienda,
            venta.comp,
            None,
            [tienda.cobro(tienda.efectivo, "236.00")],
            motivo=MotivoNota.ANULACION,
        )
        assert (n.motivo, n.total) == ("01", venta.comp.total)
        assert stock(tienda, venta.producto) == D("10")

    def test_no_sirve_si_ya_se_devolvio_algo_pero_la_devolucion_total_si(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
        )
        with pytest.raises(VentaInvalida, match="Devolución total"):
            nota(tienda, venta.comp, None, [], motivo=MotivoNota.ANULACION)
        n = nota(
            tienda,
            venta.comp,
            None,
            [tienda.cobro(tienda.efectivo, "118.00")],
            motivo=MotivoNota.DEVOLUCION_TOTAL,
        )
        assert n.total == D("118.00")

    def test_una_segunda_anulacion_dice_que_ya_se_devolvio(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            None,
            [tienda.cobro(tienda.efectivo, "236.00")],
            motivo=MotivoNota.ANULACION,
        )
        with pytest.raises(VentaInvalida, match="por completo"):
            nota(tienda, venta.comp, None, [], motivo=MotivoNota.ANULACION)


class TestSerieDeLaNota:
    def _comprobantes(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"}, stock={tienda.a: 10})
        hechos = {}
        for tipo in ("01", "03", "NV"):
            extra = {"cliente": tienda.cliente()} if tipo == "01" else {}
            v = tienda.vender(
                [tienda.linea(p, 1)],
                [tienda.cobro(tienda.efectivo, "118.00")],
                tipo_comprobante=tipo,
                **extra,
            )
            hechos[tipo] = v.comprobantes.get()
        return hechos

    def test_cada_comprobante_lleva_la_serie_de_su_letra(self, tienda):
        hechos = self._comprobantes(tienda)
        series = {
            tipo: nota(
                tienda,
                comp,
                None,
                [tienda.cobro(tienda.efectivo, "118.00")],
                motivo=MotivoNota.DEVOLUCION_TOTAL,
            ).numero_completo
            for tipo, comp in hechos.items()
        }
        assert series == {
            "01": "FC01-00000001",
            "03": "BC01-00000001",
            "NV": "001-00000001",
        }

    def test_sin_serie_de_la_letra_correcta_dice_cual_crear(self, tienda):
        from apps.mantenimiento.models import SerieComprobante

        hechos = self._comprobantes(tienda)
        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("07"), serie="BC01"
        ).update(estado="INACTIVO")
        with pytest.raises(VentaInvalida, match="empiece con B"):
            nota(tienda, hechos["03"], None, [], motivo=MotivoNota.DEVOLUCION_TOTAL)
        # Las series F y la interna no sirven para una boleta: no se emitió nada.
        assert not NotaCredito.objects.sin_ambito().exists()

    def test_con_varias_series_hay_que_elegir_y_solo_vale_una_de_su_letra(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        otra = SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("07"), serie="FC09"
        )
        boleta = SerieComprobante.objects.sin_ambito().get(empresa=tienda.a, serie="BC01")
        with pytest.raises(VentaInvalida, match="elija una"):
            nota(tienda, venta.comp, None, [], motivo="06")
        with pytest.raises(VentaInvalida, match="no sirve"):
            nota(tienda, venta.comp, None, [], motivo="06", serie_id=boleta.pk)
        n = nota(
            tienda,
            venta.comp,
            None,
            [tienda.cobro(tienda.efectivo, "236.00")],
            motivo="06",
            serie_id=otra.pk,
        )
        assert n.numero_completo == "FC09-00000001"


class TestReembolsoSugerido:
    def test_se_devuelve_por_los_metodos_con_que_pago_el_cliente(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100"})
        v = tienda.vender(
            [tienda.linea(p, 2)],
            [
                tienda.cobro(tienda.efectivo, "36.00"),
                tienda.cobro(tienda.yape, "200.00", referencia="OP-1"),
            ],
            tipo_comprobante="01",
            cliente=tienda.cliente(),
        )
        comp = v.comprobantes.get()
        filas, sin_asignar = notas_credito.sugerir_reembolso(comp, D("118.00"))
        assert {f["medio_pago"]: f["monto"] for f in filas} == {
            tienda.efectivo.pk: D("36.00"),
            tienda.yape.pk: D("82.00"),
        }
        assert sin_asignar == D("0")
        nota(
            tienda,
            comp,
            [devolver(comp, comp.lineas.get(), 1)],
            [
                tienda.cobro(tienda.efectivo, "36.00"),
                tienda.cobro(tienda.yape, "82.00", referencia="OP-2"),
            ],
        )
        disponible = {
            m["medio_pago"]: m["disponible"] for m in notas_credito.reembolsable_por_metodo(comp)
        }
        assert disponible == {tienda.efectivo.pk: D("0"), tienda.yape.pk: D("118.00")}
        # Lo que no cabe en lo que pagó no se asigna: lo elige la persona.
        _, sin_asignar = notas_credito.sugerir_reembolso(comp, D("200.00"))
        assert sin_asignar == D("82.00")

    def test_en_una_venta_a_credito_cuentan_los_abonos(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})
        v = tienda.credito([tienda.linea(p, 1)], cliente=tienda.cliente("1000"))
        comp = v.comprobantes.get()
        cuentas_por_cobrar.registrar_abonos(comp, abonos=[tienda.cobro(tienda.efectivo, "47.20")])
        filas, _ = notas_credito.sugerir_reembolso(comp, D("47.20"))
        assert [(f["medio_pago"], f["monto"]) for f in filas] == [(tienda.efectivo.pk, D("47.20"))]


class TestApiBuscadorYListado:
    def test_busca_comprobantes_con_algo_por_devolver(self, tienda, venta):
        c = cliente_de("admin")
        url = f"{BASE}/comprobantes/devolvibles/"
        r = c.get(url, {"empresa": tienda.a.pk}).json()
        assert r["count"] == 1
        fila = r["results"][0]
        assert (fila["id"], fila["numero_completo"], fila["tipo_codigo"]) == (
            venta.comp.pk,
            venta.comp.numero_completo,
            "01",
        )
        assert (fila["cliente_documento"], fila["total"], fila["moneda"]) == (
            "20100000017",
            "236.00",
            "PEN",
        )
        for q, cuenta in (("Sol", 1), ("20100000017", 1), ("F001-1", 1), ("1", 1), ("zzz", 0)):
            assert c.get(url, {"empresa": tienda.a.pk, "q": q}).json()["count"] == cuenta, q
        assert c.get(url, {"empresa": tienda.b.pk}).json()["count"] == 0
        assert c.get(url, {"empresa": tienda.a.pk, "desde": "2999-01-01"}).json()["count"] == 0

    def test_no_trae_lo_ya_devuelto_ni_lo_anulado(self, tienda, venta):
        c = cliente_de("admin")
        url = f"{BASE}/comprobantes/devolvibles/"
        reembolso = [{"medio_pago": tienda.efectivo.pk, "monto": "118.00"}]
        parcial = {
            "motivo": "07",
            "lineas": [{"linea": venta.linea.pk, "cantidad": "1"}],
            "reembolsos": reembolso,
        }
        assert emitir("admin", venta.comp.pk, parcial).status_code == 201
        assert c.get(url, {"empresa": tienda.a.pk}).json()["count"] == 1  # aún queda una
        total = {"motivo": "06", "reembolsos": reembolso}
        assert emitir("admin", venta.comp.pk, total).status_code == 201
        assert c.get(url, {"empresa": tienda.a.pk}).json()["count"] == 0

    def test_no_trae_un_comprobante_anulado(self, tienda, venta):
        servicios.anular_venta(venta.venta, motivo="Error")
        r = cliente_de("admin").get(f"{BASE}/comprobantes/devolvibles/", {"empresa": tienda.a.pk})
        assert r.json()["count"] == 0

    def test_exige_empresa_y_el_permiso_de_notas_de_credito(self, tienda, venta):
        url = f"{BASE}/comprobantes/devolvibles/"
        assert cliente_de("admin").get(url).status_code == 400
        assert cliente_de("vendedor").get(url, {"empresa": tienda.a.pk}).status_code == 403

    def test_el_pendiente_trae_lo_que_la_pantalla_necesita(self, tienda, venta):
        c = cliente_de("admin")
        d = c.get(f"{BASE}/comprobantes/{venta.comp.pk}/devolucion/").json()
        assert (d["tipo_codigo"], d["cliente_documento"], d["total"]) == (
            "01",
            "20100000017",
            "236.00",
        )
        assert d["se_puede_devolver"] is True and d["anulado"] is False
        assert [s["serie"] for s in d["series"]] == ["FC01"]
        assert d["serie_sugerida"] == d["series"][0]["id"]
        assert d["series"][0]["proximo"] == "FC01-00000001"
        motivos = {m["codigo"]: m for m in d["motivos"]}
        assert motivos["01"]["disponible"] and motivos["01"]["total"] and not motivos["07"]["total"]
        (cobrado,) = d["cobrado"]
        assert (cobrado["nombre"], cobrado["disponible"]) == ("Efectivo", "236.00")
        (ln,) = d["lineas"]
        assert ln["unidad"] and ln["tipo_igv"] and ln["disponible"] == "2.000"
        parcial = {
            "motivo": "07",
            "lineas": [{"linea": venta.linea.pk, "cantidad": "1"}],
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "118.00"}],
        }
        assert emitir("admin", venta.comp.pk, parcial).status_code == 201
        despues = c.get(f"{BASE}/comprobantes/{venta.comp.pk}/devolucion/").json()
        assert {m["codigo"]: m["disponible"] for m in despues["motivos"]}["01"] is False
        assert despues["cobrado"][0]["disponible"] == "118.00"

    def test_la_vista_previa_de_la_anulacion_sugiere_el_reembolso(self, tienda, venta):
        r = cliente_de("admin").post(
            f"{BASE}/comprobantes/{venta.comp.pk}/nota-credito/previsualizar/",
            {"motivo": "01"},
            format="json",
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["total"], d["op_gravada"], d["igv"]) == ("236.00", "200.00", "36.00")
        assert d["reembolso_sugerido"][0]["monto"] == "236.00"
        assert d["reembolso_sugerido"][0]["nombre"] == "Efectivo"
        assert d["reembolso_sin_asignar"] == "0.00"

    def test_se_emite_con_la_serie_elegida_y_el_reintento_no_repite(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        otra = SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("07"), serie="FC09"
        )
        cuerpo = {
            "motivo": "01",
            "serie_nota": otra.pk,
            "reembolsos": [{"medio_pago": tienda.efectivo.pk, "monto": "236.00"}],
        }
        c = cliente_de("admin")
        for _ in range(2):
            r = c.post(
                f"{BASE}/comprobantes/{venta.comp.pk}/nota-credito/",
                cuerpo,
                format="json",
                HTTP_IDEMPOTENCY_KEY="nota-anulacion-001",
            )
            assert r.status_code == 201, r.content
        assert r.json()["numero_completo"] == "FC09-00000001"
        assert NotaCredito.objects.sin_ambito().count() == 1

    def test_el_listado_trae_usuario_documento_asociado_y_pendiente(self, tienda):
        p = tienda.producto(costo="50", precios={"PUBLICO": "100", "CREDITO": "120"})
        v = tienda.credito([tienda.linea(p, 2)], cliente=tienda.cliente("1000"))  # 283,20
        comp = v.comprobantes.get()
        nota(
            tienda,
            comp,
            [devolver(comp, comp.lineas.get(), 1)],
            [],
            usuario_nombre="Rosa Pérez",
        )
        c = cliente_de("vendedor")
        url = f"{BASE}/notas-credito/"
        fila = c.get(url, {"empresa": tienda.a.pk}).json()["results"][0]
        assert fila["usuario"] == "Rosa Pérez"
        assert (fila["cliente_documento"], fila["cliente_tipo_documento"]) == (
            "20100000017",
            "RUC",
        )
        assert (fila["comprobante_numero"], fila["comprobante_fecha"]) == (
            comp.numero_completo,
            comp.fecha.isoformat(),
        )
        assert fila["comprobante_tipo"] == comp.tipo_comprobante.nombre
        # De 283,20 se devolvió la mitad: bajó la deuda y todavía deben la otra mitad.
        assert (fila["total"], fila["asociado"], fila["pendiente"]) == (
            "141.60",
            "141.60",
            "141.60",
        )
        for q, cuenta in (
            (comp.serie, 1),
            (comp.numero_completo, 1),
            ("Ferretería", 1),
            ("20100000017", 1),
            ("001-1", 1),
            ("zzz", 0),
        ):
            assert c.get(url, {"empresa": tienda.a.pk, "q": q}).json()["count"] == cuenta, q
        detalle = c.get(f"{url}{fila['id']}/").json()
        assert detalle["pendiente"] == "141.60" and detalle["lineas"]


class TestExcelDelListado:
    def _bajar(self, usuario, empresa, **filtros):
        return cliente_de(usuario).get(
            f"{BASE}/notas-credito/excel/", {"empresa": empresa.pk, **filtros}
        )

    def _filas(self, respuesta):
        from io import BytesIO

        from openpyxl import load_workbook

        hoja = load_workbook(BytesIO(respuesta.content)).active
        return [[c.value for c in fila] for fila in hoja.iter_rows(min_row=6)]

    def test_baja_las_notas_filtradas_con_el_total_por_moneda(self, tienda, venta):
        nota(
            tienda,
            venta.comp,
            [devolver(venta.comp, venta.linea, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            descripcion="Falla",
            usuario_nombre="Rosa Pérez",
        )
        r = self._bajar("admin", tienda.a)
        assert r.status_code == 200 and "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith('attachment; filename="ventas-notas-credito_')
        titulos, nota_fila, total = self._filas(r)[:3]
        assert titulos[1] == "Nota de crédito" and titulos[9] == "Total"
        assert (nota_fila[1], nota_fila[2], nota_fila[3], nota_fila[5]) == (
            "FC01-00000001",
            "Rosa Pérez",
            "Ferretería El Sol",
            venta.comp.numero_completo,
        )
        assert (nota_fila[7], nota_fila[8]) == ("Devolución por ítem", "S/")
        assert (float(nota_fila[9]), float(nota_fila[12])) == (118.0, 118.0)
        assert total[0] == "TOTAL" and float(total[9]) == 118.0
        # Los filtros son los mismos de la pantalla: sin coincidencias solo queda la cabecera.
        sin = self._filas(self._bajar("admin", tienda.a, q="zzz"))
        assert len(sin) == 1
        assert len(self._filas(self._bajar("admin", tienda.a, desde="2999-01-01"))) == 1

    def test_exige_el_permiso_de_exportar_y_una_empresa(self, tienda, venta):
        assert self._bajar("vendedor", tienda.a).status_code == 403
        assert cliente_de("admin").get(f"{BASE}/notas-credito/excel/").status_code == 400
