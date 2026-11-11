"""Toma de inventario físico (entrega 1): crear, abrir, contar, reconteo y cerrar."""

from decimal import Decimal

import pytest

from apps.core.exceptions import MotivoObligatorio
from apps.inventario import tomas
from apps.inventario.exceptions import (
    ConteoInvalido,
    ConteoRequiereConfirmacion,
    TomaEstadoInvalido,
    TomaIncompleta,
    TomaInvalida,
    TomaVigenteExistente,
)
from apps.inventario.models import (
    AlcanceToma,
    ConteoToma,
    DetalleToma,
    EstadoToma,
    MovimientoInventario,
    OrigenMovimiento,
    ResultadoToma,
    SaldoStock,
    TipoMovimiento,
    TomaInventario,
)
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.mantenimiento.models import Categoria, Familia, Producto, UnidadMedida

from .conftest import comprar, saldo_de

pytestmark = pytest.mark.django_db

D = Decimal


def _crear(entorno, **extra):
    return tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm1.pk, **extra)


def _abierta(entorno, **extra):
    toma = _crear(entorno, **extra)
    return tomas.abrir_toma(toma.pk)


def _contar(toma, producto, cantidad, **extra):
    return tomas.registrar_conteo(
        toma_id=toma.pk, producto_id=producto.pk, cantidad=D(str(cantidad)), **extra
    )


def _detalle(toma, producto) -> DetalleToma:
    return DetalleToma.objects.get(toma=toma, producto=producto)


# ---------------------------------------------------------------------------
class TestCrear:
    def test_nace_en_borrador_con_conteo_a_ciegas_y_numero_correlativo(self, entorno):
        primera = _crear(entorno)
        assert (primera.estado, primera.numero, primera.conteo_ciego) == (
            EstadoToma.BORRADOR,
            1,
            True,
        )
        assert primera.umbral_monto == 500 and primera.umbral_porcentaje == 10
        tomas.anular_toma(primera.pk, motivo="Prueba")
        assert _crear(entorno).numero == 2

    def test_un_almacen_no_admite_dos_tomas_en_curso(self, entorno):
        _crear(entorno)
        with pytest.raises(TomaVigenteExistente):
            _crear(entorno)

    def test_anular_libera_el_almacen(self, entorno):
        toma = _crear(entorno)
        tomas.anular_toma(toma.pk, motivo="Se eligió mal el alcance")
        assert _crear(entorno).estado == EstadoToma.BORRADOR

    def test_el_almacen_debe_ser_de_la_empresa(self, entorno):
        with pytest.raises(TomaInvalida):
            tomas.crear_toma(empresa=entorno.e1, almacen_id=entorno.alm2.pk)

    def test_por_categorias_exige_categorias_y_todo_las_rechaza(self, entorno):
        categoria = entorno.producto().categoria
        with pytest.raises(TomaInvalida):
            _crear(entorno, alcance=AlcanceToma.CATEGORIAS)
        with pytest.raises(TomaInvalida):
            _crear(entorno, alcance=AlcanceToma.TODO, categorias_ids=[categoria.pk])
        toma = _crear(entorno, alcance=AlcanceToma.CATEGORIAS, categorias_ids=[categoria.pk])
        assert list(toma.categorias.all()) == [categoria]

    def test_no_acepta_categorias_ni_productos_inexistentes(self, entorno):
        with pytest.raises(TomaInvalida):
            _crear(entorno, alcance=AlcanceToma.CATEGORIAS, categorias_ids=[999999])
        with pytest.raises(TomaInvalida):
            _crear(entorno, excluidos_ids=[999999])
        with pytest.raises(TomaInvalida):  # producto de otra organización
            _crear(entorno, excluidos_ids=[entorno.ajeno.pk])


# ---------------------------------------------------------------------------
class TestAbrir:
    def test_congela_stock_y_costo_de_lo_que_tiene_existencias(self, entorno):
        cemento, fierro, sin_stock = (
            entorno.producto(),
            entorno.producto("Fierro"),
            entorno.producto("X"),
        )
        comprar(entorno, cemento, 10, 20)
        comprar(entorno, fierro, 5, 8)
        toma = _abierta(entorno)
        assert toma.estado == EstadoToma.ABIERTA and toma.fecha_corte is not None
        assert DetalleToma.objects.filter(toma=toma, producto=sin_stock).count() == 0
        d = _detalle(toma, cemento)
        assert (d.stock_sistema, d.costo_unitario, d.cantidad_contada) == (D("10"), D("20"), None)
        assert d.resultado == ResultadoToma.PENDIENTE

    def test_la_foto_no_cambia_si_el_stock_se_mueve_despues(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abierta(entorno)
        comprar(entorno, cemento, 5, 30)
        assert saldo_de(entorno, cemento).cantidad == 15
        d = _detalle(toma, cemento)
        assert (d.stock_sistema, d.costo_unitario) == (D("10"), D("20"))

    def test_respeta_las_categorias_y_las_exclusiones_y_no_incluye_servicios(self, entorno):
        cemento, tercero = entorno.producto(), entorno.producto("Mercadería de terceros")
        familia = Familia.objects.sin_ambito().create(organizacion=entorno.e.org_a, nombre="Otra")
        otra_cat = Categoria.objects.sin_ambito().create(
            organizacion=entorno.e.org_a, familia=familia, nombre="Cables"
        )
        cable = Producto.objects.sin_ambito().create(
            organizacion=entorno.e.org_a,
            codigo="000900",
            nombre="Cable UTP",
            categoria=otra_cat,
            unidad=cemento.unidad,
        )
        for producto in (cemento, tercero, cable):
            comprar(entorno, producto, 3, 10)
        solo_cables = _abierta(
            entorno, alcance=AlcanceToma.CATEGORIAS, categorias_ids=[otra_cat.pk]
        )
        assert list(solo_cables.detalles.values_list("producto_id", flat=True)) == [cable.pk]
        tomas.anular_toma(solo_cables.pk, motivo="Prueba")

        sin_terceros = _abierta(entorno, excluidos_ids=[tercero.pk])
        assert set(sin_terceros.detalles.values_list("producto_id", flat=True)) == {
            cemento.pk,
            cable.pk,
        }

    def test_sin_nada_que_contar_no_se_abre(self, entorno):
        toma = _crear(entorno)
        with pytest.raises(TomaInvalida):
            tomas.abrir_toma(toma.pk)
        assert TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.BORRADOR

    def test_solo_se_abre_desde_borrador(self, entorno):
        comprar(entorno, entorno.producto(), 1, 10)
        toma = _abierta(entorno)
        with pytest.raises(TomaEstadoInvalido):
            tomas.abrir_toma(toma.pk)


# ---------------------------------------------------------------------------
class TestContar:
    @pytest.fixture
    def montaje(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        return entorno, cemento, _abierta(entorno)

    def test_el_primer_conteo_pasa_a_en_conteo_y_calcula_la_diferencia_al_costo(self, montaje):
        _, cemento, toma = montaje
        d = _contar(toma, cemento, 9)
        assert TomaInventario.objects.get(pk=toma.pk).estado == EstadoToma.EN_CONTEO
        assert (d.cantidad_contada, d.diferencia, d.importe_diferencia) == (
            D("9"),
            D("-1"),
            D("-20.00"),
        )
        assert d.resultado == ResultadoToma.FALTANTE and d.numero_conteos == 1

    def test_sobrante_y_conforme(self, montaje):
        _, cemento, toma = montaje
        assert _contar(toma, cemento, 10).resultado == ResultadoToma.CONFORME
        d = _contar(toma, cemento, 11)
        assert (d.resultado, d.importe_diferencia) == (ResultadoToma.SOBRANTE, D("20.00"))

    def test_cada_conteo_deja_su_rastro_y_el_ultimo_manda(self, montaje):
        _, cemento, toma = montaje
        _contar(toma, cemento, 9)
        d = _contar(toma, cemento, 10)
        assert d.cantidad_contada == 10 and d.numero_conteos == 2
        assert list(ConteoToma.objects.filter(detalle=d).values_list("numero", "cantidad")) == [
            (1, D("9")),
            (2, D("10")),
        ]

    def test_cero_con_poco_valor_se_acepta_y_con_mucho_pide_confirmacion(self, entorno):
        barato, caro = entorno.producto("Tornillo"), entorno.producto("Laptop")
        comprar(entorno, barato, 2, 1)
        comprar(entorno, caro, 4, 2000)
        toma = _abierta(entorno)
        assert _contar(toma, barato, 0).cantidad_contada == 0  # contado y no hay
        with pytest.raises(ConteoRequiereConfirmacion):
            _contar(toma, caro, 0)
        assert _detalle(toma, caro).cantidad_contada is None  # no se guardó nada
        assert _contar(toma, caro, 0, confirmar_cero=True).cantidad_contada == 0

    def test_sin_conteo_el_producto_sigue_pendiente_y_no_es_lo_mismo_que_cero(self, montaje):
        _, cemento, toma = montaje
        d = _detalle(toma, cemento)
        assert d.cantidad_contada is None and d.diferencia is None
        assert d.resultado == ResultadoToma.PENDIENTE

    def test_rechaza_negativos_decimales_en_unidades_enteras_y_productos_ajenos(self, montaje):
        entorno, cemento, toma = montaje
        for malo in (D("-1"), D("2.5")):
            with pytest.raises(ConteoInvalido):
                _contar(toma, cemento, malo)
        with pytest.raises(ConteoInvalido):
            _contar(toma, entorno.producto("No está en la toma"), 1)
        assert not ConteoToma.objects.sin_ambito().exists()

    def test_en_metros_admite_decimales(self, entorno):
        metro = UnidadMedida.objects.sin_ambito().create(
            organizacion=entorno.e.org_a, nombre="Metro", abreviatura="M", codigo_sunat="MTR"
        )
        cable = entorno.producto("Cable UTP")
        cable.unidad = metro
        cable.save()
        comprar(entorno, cable, 100, 1)
        toma = _abierta(entorno)
        assert _contar(toma, cable, "99.5").cantidad_contada == D("99.5")

    def test_un_producto_con_serie_se_cuenta_en_enteros(self, entorno):
        laptop = entorno.producto("Laptop", lleva_serie=True)
        registrar_movimiento(
            empresa=entorno.e1,
            almacen=entorno.alm1,
            tipo=TipoMovimiento.ENTRADA,
            origen=OrigenMovimiento.COMPRA,
            fecha=entorno.hoy,
            lineas=[LineaNueva(laptop, D("2"), D("1500"), series=("SN-001", "SN-002"))],
        )
        toma = _abierta(entorno)
        with pytest.raises(ConteoInvalido):
            _contar(toma, laptop, "1.5")

    def test_estado_fisico_y_nota(self, montaje):
        _, cemento, toma = montaje
        d = _contar(toma, cemento, 9, estado_fisico="DEFECTUOSO", nota="  falta  1  ")
        assert (d.estado_fisico, d.nota) == ("DEFECTUOSO", "falta 1")
        with pytest.raises(ConteoInvalido):
            _contar(toma, cemento, 9, estado_fisico="ROTO")

    def test_no_se_cuenta_en_una_toma_en_borrador(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        borrador = _crear(entorno)
        with pytest.raises(TomaEstadoInvalido):
            _contar(borrador, cemento, 10)

    def test_contar_no_toca_el_kardex_ni_el_stock(self, montaje):
        entorno, cemento, toma = montaje
        antes = MovimientoInventario.objects.sin_ambito().count()
        _contar(toma, cemento, 3)
        assert MovimientoInventario.objects.sin_ambito().count() == antes
        assert SaldoStock.objects.get(producto=cemento).cantidad == 10


# ---------------------------------------------------------------------------
class TestReconteo:
    @pytest.fixture
    def montaje(self, entorno):
        laptop, tornillo = entorno.producto("Laptop"), entorno.producto("Tornillo")
        comprar(entorno, laptop, 4, 2000)  # 1 de diferencia = S/ 2,000: relevante
        comprar(entorno, tornillo, 100, 1)  # 1 de diferencia = 1 %: no relevante
        return entorno, laptop, tornillo, _abierta(entorno)

    def test_el_primer_conteo_relevante_marca_reconteo_y_el_menor_no(self, montaje):
        _, laptop, tornillo, toma = montaje
        assert _contar(toma, laptop, 3).requiere_reconteo is True
        assert _contar(toma, tornillo, 99).requiere_reconteo is False

    def test_por_porcentaje_tambien_es_relevante(self, entorno):
        cinta = entorno.producto("Cinta")
        comprar(entorno, cinta, 8, 1)  # 1 de 8 = 12.5 % pero solo S/ 1
        toma = _abierta(entorno)
        assert _contar(toma, cinta, 7).requiere_reconteo is True

    def test_reconteo_solo_admite_los_marcados_y_lo_resuelve(self, montaje):
        _, laptop, tornillo, toma = montaje
        _contar(toma, laptop, 3)
        _contar(toma, tornillo, 99)
        assert tomas.iniciar_reconteo(toma.pk) == 1
        with pytest.raises(ConteoInvalido):
            _contar(toma, tornillo, 100)
        d = _contar(toma, laptop, 4)
        assert (d.requiere_reconteo, d.resultado, d.numero_conteos) == (
            False,
            ResultadoToma.CONFORME,
            2,
        )

    def test_sin_marcados_no_hay_reconteo(self, montaje):
        _, _, tornillo, toma = montaje
        _contar(toma, tornillo, 99)
        with pytest.raises(TomaInvalida):
            tomas.iniciar_reconteo(toma.pk)


# ---------------------------------------------------------------------------
class TestCerrar:
    @pytest.fixture
    def montaje(self, entorno):
        laptop, tornillo = entorno.producto("Laptop"), entorno.producto("Tornillo")
        comprar(entorno, laptop, 4, 2000)
        comprar(entorno, tornillo, 100, 1)
        return entorno, laptop, tornillo, _abierta(entorno)

    def test_no_se_cierra_sin_conteos(self, montaje):
        *_, toma = montaje
        with pytest.raises(TomaEstadoInvalido):
            tomas.cerrar_toma(toma.pk)

    def test_pendientes_piden_confirmacion_y_quedan_fuera(self, montaje):
        _, laptop, tornillo, toma = montaje
        _contar(toma, laptop, 4)
        with pytest.raises(TomaIncompleta) as error:
            tomas.cerrar_toma(toma.pk)
        assert error.value.detalle == {"pendientes": 1}
        cerrada = tomas.cerrar_toma(toma.pk, confirmar_pendientes=True)
        assert cerrada.estado == EstadoToma.CERRADA and cerrada.cerrada_en is not None
        assert _detalle(toma, tornillo).resultado == ResultadoToma.PENDIENTE

    def test_no_se_cierra_con_reconteos_pendientes(self, montaje):
        _, laptop, tornillo, toma = montaje
        _contar(toma, laptop, 3)
        _contar(toma, tornillo, 100)
        with pytest.raises(TomaIncompleta) as error:
            tomas.cerrar_toma(toma.pk)
        assert error.value.detalle == {"por_recontar": 1}

    def test_una_diferencia_importante_necesita_nota_para_cerrar(self, montaje):
        _, laptop, tornillo, toma = montaje
        _contar(toma, laptop, 3)
        _contar(toma, tornillo, 100)
        tomas.iniciar_reconteo(toma.pk)
        _contar(toma, laptop, 3)  # el reconteo confirma la falta
        with pytest.raises(TomaIncompleta) as error:
            tomas.cerrar_toma(toma.pk)
        assert error.value.detalle == {"sin_nota": 1}
        tomas.registrar_nota(toma_id=toma.pk, producto_id=laptop.pk, nota="Se vendió sin registrar")
        assert tomas.cerrar_toma(toma.pk).estado == EstadoToma.CERRADA

    def test_la_nota_exige_un_producto_ya_contado(self, montaje):
        _, laptop, _, toma = montaje
        with pytest.raises(ConteoInvalido):
            tomas.registrar_nota(toma_id=toma.pk, producto_id=laptop.pk, nota="Algo")
        _contar(toma, laptop, 4)
        with pytest.raises(ConteoInvalido):
            tomas.registrar_nota(toma_id=toma.pk, producto_id=laptop.pk, nota="  ")

    def test_con_nota_se_cierra_y_ya_no_se_cuenta(self, montaje):
        _, laptop, tornillo, toma = montaje
        _contar(toma, laptop, 3, nota="Revisado con el cliente")
        _contar(toma, tornillo, 100)
        tomas.iniciar_reconteo(toma.pk)
        _contar(toma, laptop, 3)
        tomas.cerrar_toma(toma.pk)
        with pytest.raises(TomaEstadoInvalido):
            _contar(toma, laptop, 4)

    def test_cerrada_sigue_bloqueando_el_almacen_pero_anulada_no(self, montaje):
        entorno, laptop, tornillo, toma = montaje
        _contar(toma, laptop, 4)
        _contar(toma, tornillo, 100)
        tomas.cerrar_toma(toma.pk)
        with pytest.raises(TomaVigenteExistente):
            _crear(entorno)
        tomas.anular_toma(toma.pk, motivo="Conteo equivocado")
        assert _crear(entorno).estado == EstadoToma.BORRADOR


class TestAnular:
    def test_el_motivo_es_obligatorio_y_no_se_anula_dos_veces(self, entorno):
        toma = _crear(entorno)
        with pytest.raises(MotivoObligatorio):
            tomas.anular_toma(toma.pk, motivo="  ")
        tomas.anular_toma(toma.pk, motivo="Error")
        anulada = TomaInventario.objects.get(pk=toma.pk)
        assert anulada.estado == EstadoToma.ANULADA and anulada.motivo_anulacion == "Error"
        with pytest.raises(TomaEstadoInvalido):
            tomas.anular_toma(toma.pk, motivo="Otra vez")

    def test_anular_conserva_los_conteos(self, entorno):
        cemento = entorno.producto()
        comprar(entorno, cemento, 10, 20)
        toma = _abierta(entorno)
        _contar(toma, cemento, 9)
        tomas.anular_toma(toma.pk, motivo="Se repite mañana")
        assert ConteoToma.objects.filter(detalle__toma=toma).count() == 1


class TestAvance:
    def test_avance_y_resultado_al_costo(self, entorno):
        a, b, c = entorno.producto("A"), entorno.producto("B"), entorno.producto("C")
        for producto, cantidad in ((a, 10), (b, 10), (c, 10)):
            comprar(entorno, producto, cantidad, 10)
        toma = _abierta(entorno)
        _contar(toma, a, 8)  # falta 2 -> -20
        _contar(toma, b, 11)  # sobra 1 -> +10
        datos = tomas.avance(toma)
        assert (datos["total"], datos["contados"], datos["por_contar"]) == (3, 2, 1)
        assert datos["porcentaje_avance"] == D("66.7")
        assert datos["resultado"] == {
            "conformes": 0,
            "faltantes": 1,
            "sobrantes": 1,
            "unidades_faltantes": D("-2"),
            "unidades_sobrantes": D("1"),
            "importe_faltante": D("-20.00"),
            "importe_sobrante": D("10.00"),
            "importe_neto": D("-10.00"),
        }
        assert datos["por_categoria"] == [
            {
                "categoria_id": a.categoria_id,
                "categoria": "Cemento",
                "total": 3,
                "contados": 2,
                "por_contar": 1,
            }
        ]


class TestPorAnotar:
    def test_lista_y_cuenta_a_los_que_necesitan_nota_por_monto_o_por_porcentaje(self, entorno):
        laptop, tornillo, cinta = (entorno.producto(n) for n in ("Laptop", "Tornillo", "Cinta"))
        comprar(entorno, laptop, 4, 2000)  # 1 de diferencia = S/ 2,000 (monto)
        comprar(entorno, tornillo, 100, 1)  # 1 de diferencia = 1 % (nada)
        comprar(entorno, cinta, 8, 1)  # 1 de 8 = 12.5 % (porcentaje)
        toma = _abierta(entorno)
        _contar(toma, laptop, 3)
        _contar(toma, tornillo, 99)
        _contar(toma, cinta, 7)
        assert tomas.avance(toma)["por_anotar"] == 2
        assert {d.producto_id for d in tomas.sin_nota(toma)} == {laptop.pk, cinta.pk}
        tomas.registrar_nota(toma_id=toma.pk, producto_id=laptop.pk, nota="Revisado")
        assert [d.producto_id for d in tomas.sin_nota(toma)] == [cinta.pk]
        assert tomas.avance(toma)["por_anotar"] == 1

    def test_lo_pendiente_y_lo_conforme_no_piden_nota(self, entorno):
        cemento, sin_contar = entorno.producto(), entorno.producto("Otro")
        comprar(entorno, cemento, 10, 20)
        comprar(entorno, sin_contar, 10, 20)
        toma = _abierta(entorno)
        _contar(toma, cemento, 10)
        assert tomas.avance(toma)["por_anotar"] == 0
