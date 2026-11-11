"""Cotizaciones de compra: pedir precios, registrar respuestas, comparar y adjudicar."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.compras.cotizaciones import (
    Asignacion,
    LineaPedida,
    PrecioDado,
    adjudicar,
    agregar_proveedor,
    anular_solicitud,
    comparativo,
    crear_solicitud,
    declinar_respuesta,
    editar_solicitud,
    quitar_proveedor,
    registrar_respuesta,
)
from apps.compras.exceptions import CotizacionInvalida, CotizacionNoModificable
from apps.compras.models import (
    LineaOrdenCompra,
    OrdenCompra,
    RespuestaCotizacion,
    SolicitudCotizacion,
)

from .conftest import dec

pytestmark = pytest.mark.django_db

Estado = SolicitudCotizacion.Estado


@pytest.fixture
def escena(compras):
    """Dos productos (10 y 5 unidades) y dos proveedores para cotizar."""
    e = compras.entorno
    p1, p2 = e.producto("Cemento Sol"), e.producto("Fierro 1/2")

    def pedir(**extra):
        datos = {
            "empresa": compras.empresa,
            "almacen": compras.almacen,
            "fecha": e.hoy,
            "lineas": [LineaPedida(p1, dec(10)), LineaPedida(p2, dec(5))],
            "proveedores": [e.proveedor, e.otro_proveedor],
        }
        datos.update(extra)
        return crear_solicitud(**datos)

    def respuesta(solicitud, proveedor):
        return RespuestaCotizacion.objects.get(solicitud=solicitud, proveedor=proveedor)

    def lineas_de(solicitud):
        return list(solicitud.lineas.order_by("posicion"))

    return type(
        "Escena",
        (),
        {
            "compras": compras,
            "e": e,
            "p1": p1,
            "p2": p2,
            "pedir": staticmethod(pedir),
            "respuesta": staticmethod(respuesta),
            "lineas": staticmethod(lineas_de),
        },
    )


def precios(solicitud, *valores):
    """Un PrecioDado por línea, en orden; None = no cotiza ese producto."""
    return [
        PrecioDado(ln.pk, None if v is None else dec(v))
        for ln, v in zip(solicitud.lineas.order_by("posicion"), valores, strict=True)
    ]


class TestCrear:
    def test_nace_en_borrador_con_una_respuesta_pendiente_por_proveedor(self, escena):
        s = escena.pedir()
        assert (s.numero, s.codigo, s.estado) == (1, "COT-000001", Estado.BORRADOR)
        assert s.lineas.count() == 2
        respuestas = RespuestaCotizacion.objects.filter(solicitud=s)
        assert respuestas.count() == 2
        assert {r.estado for r in respuestas} == {RespuestaCotizacion.Estado.PENDIENTE}
        assert all(r.lineas.count() == 2 for r in respuestas)

    def test_el_correlativo_sigue(self, escena):
        assert [escena.pedir().numero, escena.pedir().numero] == [1, 2]

    def test_sin_productos_no_se_crea(self, escena):
        with pytest.raises(CotizacionInvalida, match="al menos un producto"):
            escena.pedir(lineas=[])

    def test_un_producto_repetido_se_rechaza(self, escena):
        with pytest.raises(CotizacionInvalida, match="repetido"):
            escena.pedir(lineas=[LineaPedida(escena.p1, dec(1)), LineaPedida(escena.p1, dec(2))])

    def test_un_servicio_no_se_cotiza(self, escena):
        with pytest.raises(CotizacionInvalida, match="control de stock"):
            escena.pedir(lineas=[LineaPedida(escena.e.servicio, dec(1))])

    def test_un_proveedor_repetido_se_rechaza(self, escena):
        with pytest.raises(CotizacionInvalida, match="repetido"):
            escena.pedir(proveedores=[escena.e.proveedor, escena.e.proveedor])

    def test_una_fecha_limite_anterior_se_rechaza(self, escena):
        with pytest.raises(CotizacionInvalida, match="fecha límite"):
            escena.pedir(fecha_limite=escena.e.hoy - timedelta(days=1))

    def test_se_puede_crear_sin_proveedores_y_sumarlos_despues(self, escena):
        s = escena.pedir(proveedores=[])
        agregar_proveedor(s, escena.e.proveedor)
        assert RespuestaCotizacion.objects.filter(solicitud=s).count() == 1
        with pytest.raises(CotizacionInvalida, match="ya está"):
            agregar_proveedor(s, escena.e.proveedor)

    def test_un_proveedor_que_no_ha_respondido_se_puede_quitar(self, escena):
        s = escena.pedir()
        quitar_proveedor(escena.respuesta(s, escena.e.otro_proveedor))
        assert RespuestaCotizacion.objects.filter(solicitud=s).count() == 1

    def test_no_se_quita_a_quien_ya_respondio(self, escena):
        s = escena.pedir()
        r = escena.respuesta(s, escena.e.proveedor)
        registrar_respuesta(r, precios=precios(s, "10", "20"))
        with pytest.raises(CotizacionNoModificable, match="no ha respondido"):
            quitar_proveedor(r)


class TestResponder:
    def test_la_primera_respuesta_abre_la_solicitud(self, escena):
        s = escena.pedir()
        r = registrar_respuesta(
            escena.respuesta(s, escena.e.proveedor),
            precios=precios(s, "10", "20"),
            plazo_entrega_dias=3,
        )
        s.refresh_from_db()
        assert s.estado == Estado.ABIERTA and s.enviada_en is not None
        assert (r.estado, r.origen, r.plazo_entrega_dias) == (
            RespuestaCotizacion.Estado.RESPONDIDA,
            "MANUAL",
            3,
        )

    def test_se_puede_corregir_una_respuesta(self, escena):
        s = escena.pedir()
        r = escena.respuesta(s, escena.e.proveedor)
        registrar_respuesta(r, precios=precios(s, "10", "20"))
        registrar_respuesta(r, precios=precios(s, "9", None))
        c = comparativo(s)
        oferta = c["lineas"][0]["ofertas"][0]
        assert oferta["precio_unitario"] == dec("9")
        assert c["lineas"][1]["ofertas"][0]["precio_unitario"] is None

    def test_sin_ningun_precio_se_rechaza(self, escena):
        s = escena.pedir()
        with pytest.raises(CotizacionInvalida, match="al menos un producto"):
            registrar_respuesta(
                escena.respuesta(s, escena.e.proveedor), precios=precios(s, None, None)
            )

    def test_no_puede_ofrecer_mas_de_lo_pedido(self, escena):
        s = escena.pedir()
        l1 = escena.lineas(s)[0]
        with pytest.raises(CotizacionInvalida, match="más de lo pedido"):
            registrar_respuesta(
                escena.respuesta(s, escena.e.proveedor),
                precios=[PrecioDado(l1.pk, dec("10"), dec("11"))],
            )

    def test_el_precio_admite_seis_decimales_y_no_es_negativo(self, escena):
        s = escena.pedir()
        r = escena.respuesta(s, escena.e.proveedor)
        l1 = escena.lineas(s)[0]
        with pytest.raises(CotizacionInvalida, match="6 decimales"):
            registrar_respuesta(r, precios=[PrecioDado(l1.pk, dec("1.1234567"))])
        with pytest.raises(CotizacionInvalida, match="no es válido"):
            registrar_respuesta(r, precios=[PrecioDado(l1.pk, dec("-1"))])

    def test_una_linea_de_otra_cotizacion_se_rechaza(self, escena):
        s, otra = escena.pedir(), escena.pedir()
        ajena = escena.lineas(otra)[0]
        with pytest.raises(CotizacionInvalida, match="no es de esta cotización"):
            registrar_respuesta(
                escena.respuesta(s, escena.e.proveedor), precios=[PrecioDado(ajena.pk, dec("5"))]
            )

    def test_el_credito_pide_plazo_y_el_contado_no(self, escena):
        s = escena.pedir()
        r = escena.respuesta(s, escena.e.proveedor)
        with pytest.raises(CotizacionInvalida, match="plazo de crédito"):
            registrar_respuesta(r, precios=precios(s, "1", "1"), forma_pago="CREDITO")
        with pytest.raises(CotizacionInvalida, match="Al contado"):
            registrar_respuesta(r, precios=precios(s, "1", "1"), forma_pago="CONTADO", plazo_dias=5)

    def test_un_proveedor_que_no_cotiza_queda_fuera_de_la_comparacion(self, escena):
        s = escena.pedir()
        declinar_respuesta(escena.respuesta(s, escena.e.otro_proveedor), motivo="No tiene stock")
        d = [
            p for p in comparativo(s)["proveedores"] if p["proveedor"] == escena.e.otro_proveedor.pk
        ]
        assert d[0]["estado"] == "DECLINADA" and d[0]["total"] is None


class TestComparativo:
    def _dos_respuestas(self, escena, a, b, **extra_b):
        s = escena.pedir()
        registrar_respuesta(escena.respuesta(s, escena.e.proveedor), precios=precios(s, *a))
        registrar_respuesta(
            escena.respuesta(s, escena.e.otro_proveedor), precios=precios(s, *b), **extra_b
        )
        return s

    def test_marca_el_mejor_precio_de_cada_producto(self, escena):
        s = self._dos_respuestas(escena, ("10", "20"), ("9", "25"))
        c = comparativo(s)
        l1, l2 = c["lineas"]
        assert (l1["mejor_precio"], l1["mas_caro"]) == (dec("9"), dec("10"))
        assert [o["es_mejor"] for o in l1["ofertas"]] == [False, True]
        assert [o["es_mejor"] for o in l2["ofertas"]] == [True, False]

    def test_el_total_es_precio_por_cantidad_y_se_marca_el_menor(self, escena):
        s = self._dos_respuestas(escena, ("10", "20"), ("9", "25"))
        c = comparativo(s)
        totales = [p["total"] for p in c["proveedores"]]
        assert totales == [dec("200.00"), dec("215.00")]  # 10*10+20*5 ; 9*10+25*5
        assert [p["mejor_total"] for p in c["proveedores"]] == [True, False]
        assert c["mejor_total"] == dec("200.00")

    def test_una_oferta_incompleta_no_gana_el_total_aunque_sea_mas_barata(self, escena):
        s = self._dos_respuestas(escena, ("10", "20"), ("1", None))
        c = comparativo(s)
        assert [p["completa"] for p in c["proveedores"]] == [True, False]
        assert [p["mejor_total"] for p in c["proveedores"]] == [True, False]

    def test_una_oferta_parcial_en_cantidad_cuenta_solo_lo_que_ofrece(self, escena):
        s = escena.pedir()
        l1, l2 = escena.lineas(s)
        registrar_respuesta(
            escena.respuesta(s, escena.e.proveedor),
            precios=[PrecioDado(l1.pk, dec("10"), dec("4")), PrecioDado(l2.pk, dec("20"))],
        )
        p = comparativo(s)["proveedores"][0]
        assert p["total"] == dec("140.00") and p["completa"] is False  # 10*4 + 20*5
        oferta = comparativo(s)["lineas"][0]["ofertas"][0]
        assert oferta["parcial"] is True

    def test_una_respuesta_vencida_se_senala(self, escena):
        s = escena.pedir(fecha=escena.e.hace(10))
        registrar_respuesta(
            escena.respuesta(s, escena.e.proveedor),
            precios=precios(s, "1", "1"),
            validez_hasta=escena.e.hace(5),
        )
        assert comparativo(s)["proveedores"][0]["vencida"] is True


class TestAdjudicar:
    def _lista(self, escena):
        s = escena.pedir()
        registrar_respuesta(
            escena.respuesta(s, escena.e.proveedor),
            precios=precios(s, "10", "20"),
            forma_pago="CREDITO",
            plazo_dias=30,
            plazo_entrega_dias=5,
        )
        registrar_respuesta(
            escena.respuesta(s, escena.e.otro_proveedor), precios=precios(s, "9", "25")
        )
        return s

    def test_una_orden_por_proveedor_ganador_con_sus_precios_y_condiciones(self, escena):
        s = self._lista(escena)
        l1, l2 = escena.lineas(s)
        ra = escena.respuesta(s, escena.e.proveedor)
        rb = escena.respuesta(s, escena.e.otro_proveedor)
        adjudicar(
            s,
            asignaciones=[Asignacion(l1.pk, rb.pk), Asignacion(l2.pk, ra.pk)],
        )
        s.refresh_from_db()
        assert s.estado == Estado.ADJUDICADA and s.adjudicada_en is not None
        ordenes = OrdenCompra.objects.filter(cotizacion=s).order_by("proveedor__nombre")
        assert ordenes.count() == 2
        por_proveedor = {o.proveedor_id: o for o in ordenes}
        orden_a, orden_b = (
            por_proveedor[escena.e.proveedor.pk],
            por_proveedor[escena.e.otro_proveedor.pk],
        )
        assert orden_a.estado == "BORRADOR" and orden_a.observacion == "Cotización COT-000001"
        assert (orden_a.forma_pago, orden_a.plazo_dias) == ("CREDITO", 30)
        assert orden_a.fecha_entrega == escena.e.hoy + timedelta(days=5)
        la = LineaOrdenCompra.objects.get(orden=orden_a)
        lb = LineaOrdenCompra.objects.get(orden=orden_b)
        assert (la.producto_id, la.cantidad, la.precio_unitario) == (
            escena.p2.pk,
            dec(5),
            dec("20"),
        )
        assert (lb.producto_id, lb.cantidad, lb.precio_unitario) == (
            escena.p1.pk,
            dec(10),
            dec("9"),
        )
        assert ra.__class__.objects.get(pk=ra.pk).orden_id == orden_a.pk

    def test_un_solo_proveedor_se_lleva_todo_en_una_orden(self, escena):
        s = self._lista(escena)
        l1, l2 = escena.lineas(s)
        ra = escena.respuesta(s, escena.e.proveedor)
        adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk), Asignacion(l2.pk, ra.pk)])
        orden = OrdenCompra.objects.get(cotizacion=s)
        assert LineaOrdenCompra.objects.filter(orden=orden).count() == 2

    def test_se_puede_pedir_menos_de_lo_cotizado_pero_no_mas(self, escena):
        s = self._lista(escena)
        l1, _ = escena.lineas(s)
        ra = escena.respuesta(s, escena.e.proveedor)
        with pytest.raises(CotizacionInvalida, match="no pasar de"):
            adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk, dec(11))])
        adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk, dec(6))])
        assert LineaOrdenCompra.objects.get(orden__cotizacion=s).cantidad == dec(6)

    def test_no_se_adjudica_a_quien_no_cotizo_ese_producto(self, escena):
        s = escena.pedir()
        l1, l2 = escena.lineas(s)
        registrar_respuesta(escena.respuesta(s, escena.e.proveedor), precios=precios(s, "10", None))
        ra = escena.respuesta(s, escena.e.proveedor)
        with pytest.raises(CotizacionInvalida, match="no cotizó"):
            adjudicar(s, asignaciones=[Asignacion(l2.pk, ra.pk)])

    def test_un_producto_no_puede_tener_dos_ganadores(self, escena):
        s = self._lista(escena)
        l1, _ = escena.lineas(s)
        ra, rb = (
            escena.respuesta(s, escena.e.proveedor),
            escena.respuesta(s, escena.e.otro_proveedor),
        )
        with pytest.raises(CotizacionInvalida, match="dos ganadores"):
            adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk), Asignacion(l1.pk, rb.pk)])

    def test_sin_asignaciones_se_rechaza_y_no_deja_nada_a_medias(self, escena):
        s = self._lista(escena)
        l1, l2 = escena.lineas(s)
        ra = escena.respuesta(s, escena.e.proveedor)
        with pytest.raises(CotizacionInvalida):
            adjudicar(s, asignaciones=[])
        with pytest.raises(CotizacionInvalida):
            adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk), Asignacion(l2.pk, 999999)])
        s.refresh_from_db()
        assert s.estado == Estado.ABIERTA and not OrdenCompra.objects.filter(cotizacion=s).exists()

    def test_una_adjudicada_no_se_adjudica_ni_se_anula_ni_se_edita(self, escena):
        s = self._lista(escena)
        l1, _ = escena.lineas(s)
        ra = escena.respuesta(s, escena.e.proveedor)
        adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk)])
        s.refresh_from_db()
        with pytest.raises(CotizacionNoModificable):
            adjudicar(s, asignaciones=[Asignacion(l1.pk, ra.pk)])
        with pytest.raises(CotizacionNoModificable):
            anular_solicitud(s, motivo="Ya no")
        with pytest.raises(CotizacionNoModificable):
            registrar_respuesta(ra, precios=precios(s, "1", "1"))

    def test_el_ahorro_es_contra_el_precio_mas_caro(self, escena):
        s = self._lista(escena)
        l1, l2 = escena.lineas(s)
        rb = escena.respuesta(s, escena.e.otro_proveedor)
        ra = escena.respuesta(s, escena.e.proveedor)
        adjudicar(s, asignaciones=[Asignacion(l1.pk, rb.pk), Asignacion(l2.pk, ra.pk)])
        s.refresh_from_db()
        # l1: (10-9)*10 = 10 ; l2: (25-20)*5 = 25
        assert comparativo(s)["ahorro"] == dec("35.00")

    def test_antes_de_adjudicar_no_hay_ahorro_que_mostrar(self, escena):
        s = self._lista(escena)
        assert comparativo(s)["ahorro"] is None


class TestAnularYEditar:
    def test_se_anula_con_motivo(self, escena):
        s = escena.pedir()
        with pytest.raises(CotizacionInvalida, match="motivo"):
            anular_solicitud(s, motivo=" ")
        anular_solicitud(s, motivo="Ya no se necesita")
        s.refresh_from_db()
        assert s.estado == Estado.ANULADA and s.motivo_anulacion == "Ya no se necesita"

    def test_se_edita_en_borrador_y_se_rearma_todo(self, escena):
        s = escena.pedir()
        editar_solicitud(
            s,
            almacen=escena.compras.almacen,
            fecha=escena.e.hoy,
            lineas=[LineaPedida(escena.p1, dec(3))],
            proveedores=[escena.e.proveedor],
        )
        assert s.lineas.count() == 1 and s.lineas.get().cantidad == dec(3)
        assert RespuestaCotizacion.objects.filter(solicitud=s).count() == 1

    def test_con_precios_ya_registrados_no_se_edita(self, escena):
        s = escena.pedir()
        registrar_respuesta(escena.respuesta(s, escena.e.proveedor), precios=precios(s, "1", "1"))
        s.refresh_from_db()  # ya está abierta
        with pytest.raises(CotizacionNoModificable):
            editar_solicitud(
                s,
                almacen=escena.compras.almacen,
                fecha=escena.e.hoy,
                lineas=[LineaPedida(escena.p1, dec(3))],
                proveedores=[escena.e.proveedor],
            )

    def test_las_cantidades_decimales_se_respetan(self, escena):
        s = escena.pedir(lineas=[LineaPedida(escena.p1, Decimal("2.5"))])
        assert s.lineas.get().cantidad == Decimal("2.500")
