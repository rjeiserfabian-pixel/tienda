"""Toma de inventario físico (entrega 2): aprobar, ajustar el Kardex (operación 28) y anular."""

import time
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.inventario import tomas
from apps.inventario.exceptions import (
    AjusteImposible,
    AnulacionNoPermitida,
    TomaEstadoInvalido,
    TomaInvalida,
    TomaVigenteExistente,
)
from apps.inventario.models import (
    DetalleToma,
    EstadoSerie,
    EstadoToma,
    MovimientoInventario,
    OrigenMovimiento,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, registrar_movimiento

from .conftest import comprar, saldo_de, vender

pytestmark = pytest.mark.django_db

D = Decimal


def _pausa():
    """Separa los instantes: el ajuste compara la hora de cada movimiento con la del conteo."""
    time.sleep(0.02)


def _abrir(entorno, **extra):
    toma = tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk, **extra)
    toma = tomas.abrir_toma(toma.pk)
    _pausa()
    return toma


def _contar(toma, producto, cantidad):
    detalle = tomas.registrar_conteo(
        toma_id=toma.pk, producto_id=producto.pk, cantidad=D(str(cantidad)), confirmar_cero=True
    )
    _pausa()
    return detalle


def _cerrar(toma):
    """Recuenta lo marcado (con nota) y cierra, dejando fuera lo que no se contó."""
    marcados = list(DetalleToma.objects.filter(toma=toma, requiere_reconteo=True))
    if marcados:
        tomas.iniciar_reconteo(toma.pk)
        for d in marcados:
            tomas.registrar_conteo(
                toma_id=toma.pk,
                producto_id=d.producto_id,
                cantidad=d.cantidad_contada,
                nota="Verificado",
                confirmar_cero=True,
            )
    _pausa()
    return tomas.cerrar_toma(toma.pk, confirmar_pendientes=True)


def _ajustes(toma):
    return list(
        MovimientoInventario.objects.filter(
            referencia_tipo="toma_inventario", referencia_id=toma.pk
        ).order_by("numero")
    )


def _detalle(toma, producto) -> DetalleToma:
    return DetalleToma.objects.get(toma=toma, producto=producto)


# ---------------------------------------------------------------------------
class TestAjuste:
    def test_sin_diferencias_se_aprueba_sin_mover_el_kardex(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 10)
        _cerrar(toma)
        antes = MovimientoInventario.objects.sin_ambito().count()
        aprobada, movimientos = tomas.aprobar_toma(toma.pk)
        assert aprobada.estado == EstadoToma.APROBADA and movimientos == []
        assert MovimientoInventario.objects.sin_ambito().count() == antes
        d = _detalle(toma, cemento)
        assert (d.diferencia_ajuste, d.importe_ajuste, d.linea_ajuste) == (D("0"), D("0.00"), None)

    def test_un_faltante_sale_al_costo_promedio_con_la_operacion_28(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 9)
        _cerrar(toma)
        aprobada, movimientos = tomas.aprobar_toma(toma.pk, nota="Revisado por el contador")
        (m,) = movimientos
        assert (m.tipo, m.origen, m.tipo_operacion) == (
            TipoMovimiento.SALIDA,
            OrigenMovimiento.AJUSTE,
            "28",
        )
        assert (m.referencia_tipo, m.referencia_id, m.fecha) == (
            "toma_inventario",
            toma.pk,
            entorno.hoy,
        )
        assert f"N° {toma.numero:06d}" in m.observacion and "Revisado" in m.observacion
        assert saldo_de(entorno, cemento).cantidad == 9
        d = _detalle(toma, cemento)
        assert (d.diferencia_ajuste, d.importe_ajuste) == (D("-1"), D("-20.00"))
        assert d.linea_ajuste.movimiento_id == m.pk
        assert aprobada.aprobada_en is not None and aprobada.nota_aprobacion.startswith("Revisado")

    def test_un_sobrante_entra_al_costo_de_la_foto(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 12)
        _cerrar(toma)
        _, (m,) = tomas.aprobar_toma(toma.pk)
        assert (m.tipo, m.tipo_operacion) == (TipoMovimiento.ENTRADA, "28")
        saldo = saldo_de(entorno, cemento)
        assert (saldo.cantidad, saldo.costo_total) == (D("12"), D("240.00"))
        assert _detalle(toma, cemento).importe_ajuste == D("40.00")

    def test_un_sobrante_sin_costo_en_la_foto_entra_al_promedio_de_hoy(self, entorno):
        regalo = entorno.producto("Regalo")
        comprar(entorno, regalo, 5, 0)
        toma = _abrir(entorno)
        comprar(entorno, regalo, 5, 10)  # después del corte: promedio 5
        _pausa()
        _contar(toma, regalo, 11)  # el sistema debía tener 10: sobra 1
        _cerrar(toma)
        tomas.aprobar_toma(toma.pk)
        assert saldo_de(entorno, regalo).costo_total == D("55.00")

    def test_los_productos_sin_contar_no_se_ajustan(self, entorno):
        contado, sin_contar = entorno.producto("A"), entorno.producto("B")
        comprar(entorno, contado, 10, 20)
        comprar(entorno, sin_contar, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, contado, 9)
        _cerrar(toma)
        tomas.aprobar_toma(toma.pk)
        assert saldo_de(entorno, sin_contar).cantidad == 10
        assert _detalle(toma, sin_contar).diferencia_ajuste is None


class TestVentasDuranteElConteo:
    def test_una_venta_antes_del_conteo_no_es_un_faltante(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        vender(entorno, cemento, 2)  # el sistema baja a 8
        _pausa()
        _contar(toma, cemento, 8)  # y en el almacén hay 8: todo cuadra
        _cerrar(toma)
        _, movimientos = tomas.aprobar_toma(toma.pk)
        assert movimientos == []
        d = _detalle(toma, cemento)
        assert (d.movimientos_posteriores, d.diferencia_ajuste) == (D("-2"), D("0"))
        assert saldo_de(entorno, cemento).cantidad == 8

    def test_una_venta_despues_del_conteo_tampoco(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 10)
        _pausa()
        vender(entorno, cemento, 3)  # se vende cuando ya se había contado
        _cerrar(toma)
        _, movimientos = tomas.aprobar_toma(toma.pk)
        assert movimientos == []
        assert saldo_de(entorno, cemento).cantidad == 7

    def test_solo_se_ajusta_la_diferencia_real(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        vender(entorno, cemento, 2)
        _pausa()
        _contar(toma, cemento, 9)  # debía haber 8 y hay 9: sobra 1
        _pausa()
        vender(entorno, cemento, 1)  # después del conteo: no cambia nada
        _cerrar(toma)
        _, (m,) = tomas.aprobar_toma(toma.pk)
        assert (m.tipo, m.lineas.get().cantidad) == (TipoMovimiento.ENTRADA, D("1"))
        assert saldo_de(entorno, cemento).cantidad == 8  # 10 - 2 + 1 - 1
        assert _detalle(toma, cemento).diferencia_ajuste == D("1")

    def test_una_compra_durante_el_conteo_tampoco_es_un_sobrante(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        comprar(entorno, cemento, 5, 20)
        _pausa()
        _contar(toma, cemento, 15)
        _cerrar(toma)
        _, movimientos = tomas.aprobar_toma(toma.pk)
        assert movimientos == []


class TestSeries:
    def _laptops(self, entorno):
        laptop = entorno.producto("Laptop", lleva_serie=True)
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=entorno.hoy,
            lineas=[LineaNueva(laptop, D("3"), D("1500"), series=("SN-001", "SN-002", "SN-003"))],
        )
        return laptop

    def test_un_faltante_con_serie_exige_cuales_salen(self, entorno):
        laptop = self._laptops(entorno)
        toma = _abrir(entorno)
        _contar(toma, laptop, 2)
        _cerrar(toma)
        with pytest.raises(AjusteImposible) as error:
            tomas.aprobar_toma(toma.pk)
        assert (
            error.value.detalle["total"] == 1
            and "series" in error.value.detalle["productos"][0]["motivo"]
        )
        assert tomas.TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.CERRADA
        tomas.aprobar_toma(toma.pk, series={laptop.pk: ("sn-002",)})
        assert SerieProducto.objects.get(numero="SN-002").estado == EstadoSerie.SALIDO
        assert SerieProducto.objects.filter(estado=EstadoSerie.EN_STOCK).count() == 2
        assert saldo_de(entorno, laptop).cantidad == 2

    def test_un_sobrante_con_serie_exige_los_numeros_que_entran(self, entorno):
        laptop = self._laptops(entorno)
        toma = _abrir(entorno)
        _contar(toma, laptop, 4)
        _cerrar(toma)
        with pytest.raises(AjusteImposible):
            tomas.aprobar_toma(toma.pk, series={laptop.pk: ("SN-004", "SN-005")})  # sobra 1, no 2
        tomas.aprobar_toma(toma.pk, series={laptop.pk: ("SN-004",)})
        assert SerieProducto.objects.get(numero="SN-004").estado == EstadoSerie.EN_STOCK

    def test_series_de_un_producto_que_no_las_lleva_se_rechazan(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 9)
        _cerrar(toma)
        with pytest.raises(AjusteImposible):
            tomas.aprobar_toma(toma.pk, series={cemento.pk: ("SN-001",)})


class TestRechazos:
    def test_si_el_stock_ya_no_alcanza_no_se_guarda_nada(self, entorno):
        raro, normal = entorno.producto("Raro"), entorno.producto("Normal")
        comprar(entorno, raro, 5, 20)
        comprar(entorno, normal, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, raro, 0)  # no hay ninguno
        _contar(toma, normal, 9)
        _cerrar(toma)
        vender(entorno, raro, 5)  # el sistema lo vendió igual, después del conteo
        antes = MovimientoInventario.objects.sin_ambito().count()
        with pytest.raises(AjusteImposible) as error:
            tomas.aprobar_toma(toma.pk)
        assert "Raro" in str(error.value)
        assert MovimientoInventario.objects.sin_ambito().count() == antes
        assert saldo_de(entorno, normal).cantidad == 10  # lo demás tampoco se ajustó
        assert tomas.TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.CERRADA

    def test_solo_se_aprueba_una_toma_cerrada_y_una_sola_vez(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        with pytest.raises(TomaEstadoInvalido):
            tomas.aprobar_toma(toma.pk)
        _contar(toma, cemento, 9)
        _cerrar(toma)
        tomas.aprobar_toma(toma.pk)
        with pytest.raises(TomaEstadoInvalido):
            tomas.aprobar_toma(toma.pk)
        assert saldo_de(entorno, cemento).cantidad == 9

    def test_la_fecha_del_ajuste_no_puede_ser_futura_ni_anterior_al_corte(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 9)
        _cerrar(toma)
        for fecha in (entorno.hoy + timedelta(days=1), entorno.hoy - timedelta(days=1)):
            with pytest.raises(TomaInvalida):
                tomas.aprobar_toma(toma.pk, fecha=fecha)
        _, (m,) = tomas.aprobar_toma(toma.pk, fecha=entorno.hoy)
        assert m.fecha == entorno.hoy

    def test_una_aprobada_ya_no_bloquea_el_almacen(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 9)
        _cerrar(toma)
        with pytest.raises(TomaVigenteExistente):  # cerrada todavía bloquea
            tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk)
        tomas.aprobar_toma(toma.pk)
        assert tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk).numero == 2


class TestLotes:
    def test_los_ajustes_se_reparten_en_movimientos_de_hasta_el_maximo_de_lineas(
        self, entorno, monkeypatch
    ):
        monkeypatch.setattr(tomas, "MAX_LINEAS", 2)
        productos = [entorno.producto(f"Producto {i}") for i in range(5)]
        for producto in productos:
            comprar(entorno, producto, 10, 20)
        toma = _abrir(entorno)
        for producto in productos:
            _contar(toma, producto, 9)
        _cerrar(toma)
        _, movimientos = tomas.aprobar_toma(toma.pk)
        assert [m.lineas.count() for m in movimientos] == [2, 2, 1]
        assert all(m.tipo_operacion == "28" for m in movimientos)
        assert all(_detalle(toma, p).linea_ajuste is not None for p in productos)

    def test_faltantes_y_sobrantes_van_en_movimientos_separados(self, entorno):
        falta, sobra = entorno.producto("Falta"), entorno.producto("Sobra")
        comprar(entorno, falta, 10, 20)
        comprar(entorno, sobra, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, falta, 9)
        _contar(toma, sobra, 11)
        _cerrar(toma)
        _, movimientos = tomas.aprobar_toma(toma.pk)
        assert sorted(m.tipo for m in movimientos) == ["ENTRADA", "SALIDA"]


class TestResumen:
    def test_la_vista_previa_resume_lo_que_se_va_a_ajustar(self, entorno):
        falta, sobra, bien = entorno.producto("A"), entorno.producto("B"), entorno.producto("C")
        for producto in (falta, sobra, bien):
            comprar(entorno, producto, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, falta, 8)
        _contar(toma, sobra, 11)
        _contar(toma, bien, 10)
        _cerrar(toma)
        calculados = tomas.calcular_ajustes(toma)
        resumen = tomas.resumen_ajustes(calculados)
        assert resumen == {
            "productos_contados": 3,
            "productos_a_ajustar": 2,
            "sobrantes": 1,
            "faltantes": 1,
            "unidades_sobrantes": D("1"),
            "unidades_faltantes": D("2"),
            "importe_sobrante": D("20.00"),
            "importe_faltante": D("-40.00"),
            "importe_neto": D("-20.00"),
            "sin_costo": 0,
            "requieren_series": 0,
        }


class TestAnularAprobada:
    def test_anular_extorna_el_ajuste_y_libera_el_almacen(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 9)
        _cerrar(toma)
        tomas.aprobar_toma(toma.pk)
        assert saldo_de(entorno, cemento).cantidad == 9
        anulada = tomas.anular_toma(toma.pk, motivo="Se contó mal")
        assert anulada.estado == EstadoToma.ANULADA
        assert saldo_de(entorno, cemento).cantidad == 10
        (ajuste,) = _ajustes(toma)
        assert ajuste.estado == MovimientoInventario.Estado.ANULADO
        assert MovimientoInventario.objects.filter(extorna=ajuste).count() == 1
        tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk)

    def test_si_el_sobrante_ya_se_vendio_no_se_puede_anular(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abrir(entorno)
        _contar(toma, cemento, 12)
        _cerrar(toma)
        tomas.aprobar_toma(toma.pk)
        vender(entorno, cemento, 12)  # se vendió todo, incluido el sobrante
        with pytest.raises(AnulacionNoPermitida):
            tomas.anular_toma(toma.pk, motivo="Error")
        assert tomas.TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.APROBADA
        (ajuste,) = _ajustes(toma)
        assert ajuste.estado == MovimientoInventario.Estado.EMITIDO
