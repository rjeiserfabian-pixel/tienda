"""Órdenes de compra: cálculo, estados, aprobación por monto y tolerancia de recepción."""

from datetime import timedelta

import pytest

from apps.compras.exceptions import OrdenCompraInvalida, OrdenCompraNoModificable
from apps.compras.models import LineaOrdenCompra, OrdenCompra
from apps.compras.ordenes import (
    LineaOrden,
    anular_orden,
    aprobar_orden,
    cerrar_orden,
    crear_orden,
    editar_orden,
    emitir_orden,
    monto_de_aprobacion,
    pendiente_de_recibir,
    preparar_orden,
    reabrir_orden,
    recalcular_estado,
    rechazar_orden,
    requiere_aprobacion,
    tolerancia_de_recepcion,
)
from apps.organizacion.models import ConfiguracionEmpresa

from .conftest import dec

pytestmark = pytest.mark.django_db

Estado = OrdenCompra.Estado


@pytest.fixture
def pedir(compras):
    """Crea una orden de 10 unidades a 10 + IGV (118,00) salvo que se indique otra cosa."""

    def _pedir(lineas=None, **extra):
        datos = {
            "empresa": compras.empresa,
            "proveedor": compras.proveedor,
            "almacen": compras.almacen,
            "fecha_emision": compras.entorno.hoy,
            "lineas": lineas or [LineaOrden(compras.entorno.producto(), dec(10), dec(10))],
        }
        datos.update(extra)
        return crear_orden(**datos)

    return _pedir


def configurar(compras, *, monto=None, tolerancia="0"):
    fila, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=compras.empresa)
    fila.orden_compra_monto_aprobacion = None if monto is None else dec(monto)
    fila.orden_compra_tolerancia = dec(tolerancia)
    fila.save()


def recibir(orden, cantidad, linea=0):
    """Simula una recepción: sube lo recibido de una línea."""
    ln = list(LineaOrdenCompra.objects.filter(orden=orden).order_by("orden_linea"))[linea]
    ln.cantidad_recibida = dec(cantidad)
    ln.save(update_fields=["cantidad_recibida"])


class TestCrear:
    def test_calcula_los_importes_como_una_compra(self, pedir):
        o = pedir()
        assert (o.numero, o.codigo, o.estado) == (1, "OC-000001", Estado.BORRADOR)
        assert (o.op_gravada, o.igv, o.total, o.total_soles) == (
            dec("100"),
            dec("18"),
            dec("118"),
            dec("118"),
        )
        ln = o.lineas.get()
        assert (ln.orden_linea, ln.cantidad, ln.cantidad_base, ln.cantidad_recibida) == (
            1,
            dec(10),
            dec(10),
            0,
        )
        assert (ln.valor_venta, ln.impuesto, ln.total, ln.afectacion_codigo) == (
            dec("100"),
            dec("18"),
            dec("118"),
            "10",
        )

    def test_el_correlativo_avanza_por_empresa(self, pedir):
        assert [pedir().numero for _ in range(3)] == [1, 2, 3]

    def test_precios_con_igv(self, pedir, compras):
        o = pedir(precios_incluyen_igv=True)
        assert (o.op_gravada, o.igv, o.total) == (dec("84.75"), dec("15.25"), dec("100"))

    def test_afectacion_exonerada_elegida(self, pedir, compras):
        linea = LineaOrden(
            compras.entorno.producto(), dec(10), dec(10), afectacion=compras.afectacion("20")
        )
        o = pedir([linea])
        assert (o.op_exonerada, o.igv, o.total) == (dec("100"), 0, dec("100"))

    def test_en_dolares_el_total_en_soles_usa_el_tipo_de_cambio(self, pedir):
        o = pedir(moneda="USD", tipo_cambio=dec("3.7500"))
        assert (o.moneda, o.total, o.total_soles) == ("USD", dec("118"), dec("442.50"))

    def test_presentacion_por_caja(self, pedir, compras):
        from apps.mantenimiento.models import PresentacionProducto, UnidadMedida

        producto = compras.entorno.producto()
        caja = UnidadMedida.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, nombre="Caja", abreviatura="CJ", codigo_sunat="BX"
        )
        pres = PresentacionProducto.objects.sin_ambito().create(
            organizacion=compras.entorno.e.org_a, producto=producto, unidad=caja, factor=dec(12)
        )
        o = pedir([LineaOrden(producto, dec(2), dec("120"), presentacion=pres)])
        ln = o.lineas.get()
        assert (ln.unidad, ln.factor, ln.cantidad, ln.cantidad_base) == (
            "Caja",
            dec(12),
            dec(2),
            dec(24),
        )

    def test_credito_con_plazo_y_entrega(self, pedir, compras):
        entrega = compras.entorno.hoy + timedelta(days=7)
        o = pedir(
            forma_pago="CREDITO", plazo_dias=30, fecha_entrega=entrega, observacion="  Urgente  "
        )
        assert (o.forma_pago, o.plazo_dias, o.fecha_entrega, o.observacion) == (
            "CREDITO",
            30,
            entrega,
            "Urgente",
        )

    def test_vista_previa_no_escribe(self, compras):
        p = preparar_orden(
            empresa=compras.empresa,
            proveedor=compras.proveedor,
            almacen=compras.almacen,
            fecha_emision=compras.entorno.hoy,
            lineas=[LineaOrden(compras.entorno.producto(), dec(10), dec(10))],
        )
        assert p.resultado.total == dec("118") and p.total_soles == dec("118")
        assert not OrdenCompra.objects.exists()


class TestValidaciones:
    def _datos(self, compras, **extra):
        datos = {
            "empresa": compras.empresa,
            "proveedor": compras.proveedor,
            "almacen": compras.almacen,
            "fecha_emision": compras.entorno.hoy,
            "lineas": [LineaOrden(compras.entorno.producto(), dec(1), dec(1))],
        }
        datos.update(extra)
        return datos

    def test_sin_lineas(self, compras):
        with pytest.raises(OrdenCompraInvalida, match="al menos un producto"):
            crear_orden(**self._datos(compras, lineas=[]))

    def test_producto_repetido(self, compras):
        producto = compras.entorno.producto()
        lineas = [LineaOrden(producto, dec(1), dec(1)), LineaOrden(producto, dec(2), dec(1))]
        with pytest.raises(OrdenCompraInvalida, match="repetido"):
            crear_orden(**self._datos(compras, lineas=lineas))

    def test_cantidad_y_precio(self, compras):
        producto = compras.entorno.producto()
        for cantidad, precio, texto in (
            (dec(0), dec(1), "mayor que cero"),
            (dec("1.0001"), dec(1), "3 decimales"),
            (dec(1), dec(-1), "precio válido"),
        ):
            with pytest.raises(OrdenCompraInvalida, match=texto):
                crear_orden(**self._datos(compras, lineas=[LineaOrden(producto, cantidad, precio)]))

    def test_servicio_no_se_pide(self, compras):
        with pytest.raises(OrdenCompraInvalida, match="control de stock"):
            crear_orden(
                **self._datos(
                    compras, lineas=[LineaOrden(compras.entorno.servicio, dec(1), dec(1))]
                )
            )

    def test_fechas(self, compras):
        hoy = compras.entorno.hoy
        with pytest.raises(OrdenCompraInvalida, match="futura"):
            crear_orden(**self._datos(compras, fecha_emision=hoy + timedelta(days=1)))
        with pytest.raises(OrdenCompraInvalida, match="anterior a la emisión"):
            crear_orden(**self._datos(compras, fecha_entrega=hoy - timedelta(days=1)))

    def test_forma_de_pago_y_plazo(self, compras):
        with pytest.raises(OrdenCompraInvalida, match="al contado no lleva plazo"):
            crear_orden(**self._datos(compras, plazo_dias=15))
        for plazo in (0, 366):
            with pytest.raises(OrdenCompraInvalida, match="1 a 365"):
                crear_orden(**self._datos(compras, forma_pago="CREDITO", plazo_dias=plazo))
        with pytest.raises(OrdenCompraInvalida, match="forma de pago"):
            crear_orden(**self._datos(compras, forma_pago="TRUEQUE"))

    def test_almacen_de_otra_empresa_y_proveedor_inactivo(self, compras):
        with pytest.raises(OrdenCompraInvalida, match="almacén no pertenece"):
            crear_orden(**self._datos(compras, almacen=compras.entorno.alm2))
        compras.proveedor.estado = "INACTIVO"
        compras.proveedor.save()
        with pytest.raises(OrdenCompraInvalida, match="inactivo"):
            crear_orden(**self._datos(compras))

    def test_nada_queda_a_medias(self, compras):
        with pytest.raises(OrdenCompraInvalida):
            crear_orden(
                **self._datos(compras, fecha_entrega=compras.entorno.hoy - timedelta(days=1))
            )
        assert not OrdenCompra.objects.exists() and not LineaOrdenCompra.objects.exists()


class TestEditar:
    def test_cambia_cabecera_y_lineas_y_recalcula(self, pedir, compras):
        o = pedir()
        nuevo = compras.entorno.producto("Otro")
        editada = editar_orden(
            o,
            proveedor=compras.proveedor,
            almacen=compras.almacen,
            fecha_emision=compras.entorno.hoy,
            lineas=[LineaOrden(nuevo, dec(5), dec(20))],
            observacion="Cambió el pedido",
        )
        assert (editada.numero, editada.total, editada.observacion) == (
            1,
            dec("118"),
            "Cambió el pedido",
        )
        lineas = list(editada.lineas.all())
        assert [ln.producto_id for ln in lineas] == [nuevo.pk]
        assert LineaOrdenCompra.objects.filter(orden=o).count() == 1

    def test_solo_en_borrador(self, pedir, compras):
        o = emitir_orden(pedir(), puede_aprobar=True)
        with pytest.raises(OrdenCompraNoModificable, match="editar"):
            editar_orden(
                o,
                proveedor=compras.proveedor,
                almacen=compras.almacen,
                fecha_emision=compras.entorno.hoy,
                lineas=[LineaOrden(compras.entorno.producto(), dec(1), dec(1))],
            )

    def test_una_edicion_invalida_no_cambia_nada(self, pedir, compras):
        o = pedir()
        with pytest.raises(OrdenCompraInvalida):
            editar_orden(
                o,
                proveedor=compras.proveedor,
                almacen=compras.almacen,
                fecha_emision=compras.entorno.hoy,
                lineas=[],
            )
        o.refresh_from_db()
        assert o.total == dec("118") and o.lineas.count() == 1


class TestAprobacion:
    def test_sin_monto_configurado_nunca_pide_aprobacion(self, pedir, compras):
        assert monto_de_aprobacion(compras.empresa) is None
        o = emitir_orden(pedir(), puede_aprobar=False)
        assert o.estado == Estado.EMITIDA and o.emitida_en and o.aprobada_por_id is None

    def test_por_debajo_del_monto_se_emite_directo(self, pedir, compras):
        configurar(compras, monto="500")
        o = emitir_orden(pedir(), puede_aprobar=False)
        assert o.estado == Estado.EMITIDA and not requiere_aprobacion(o)

    def test_por_encima_sin_permiso_queda_por_aprobar(self, pedir, compras):
        configurar(compras, monto="100")
        o = emitir_orden(pedir(), puede_aprobar=False)
        assert o.estado == Estado.PENDIENTE and o.emitida_en is None

    def test_el_monto_exacto_no_pide_aprobacion(self, pedir, compras):
        configurar(compras, monto="118")
        assert emitir_orden(pedir(), puede_aprobar=False).estado == Estado.EMITIDA

    def test_por_encima_con_permiso_queda_aprobada_por_quien_la_emite(self, pedir, compras):
        configurar(compras, monto="100")
        o = emitir_orden(pedir(), puede_aprobar=True)
        assert o.estado == Estado.EMITIDA and o.aprobada_en is not None

    def test_el_monto_se_compara_en_soles(self, pedir, compras):
        configurar(compras, monto="400")
        # 118 dólares son 442,50 soles: pasa de 400 aunque 118 < 400
        o = emitir_orden(pedir(moneda="USD", tipo_cambio=dec("3.75")), puede_aprobar=False)
        assert o.estado == Estado.PENDIENTE

    def test_aprobar_deja_emitida(self, pedir, compras):
        configurar(compras, monto="100")
        o = emitir_orden(pedir(), puede_aprobar=False)
        o = aprobar_orden(o)
        assert o.estado == Estado.EMITIDA and o.aprobada_en and o.emitida_en

    def test_rechazar_vuelve_a_borrador_con_motivo(self, pedir, compras):
        configurar(compras, monto="100")
        o = emitir_orden(pedir(), puede_aprobar=False)
        with pytest.raises(OrdenCompraInvalida, match="motivo"):
            rechazar_orden(o, motivo=" ")
        o = rechazar_orden(o, motivo="Pide un precio mejor")
        assert o.estado == Estado.BORRADOR and o.motivo_rechazo == "Pide un precio mejor"

    def test_aprobar_o_rechazar_solo_lo_pendiente(self, pedir):
        o = pedir()
        with pytest.raises(OrdenCompraNoModificable):
            aprobar_orden(o)
        with pytest.raises(OrdenCompraNoModificable):
            rechazar_orden(o, motivo="No corresponde")

    def test_no_se_emite_dos_veces_ni_con_total_cero(self, pedir, compras):
        o = emitir_orden(pedir(), puede_aprobar=True)
        with pytest.raises(OrdenCompraNoModificable):
            emitir_orden(o, puede_aprobar=True)
        gratis = pedir([LineaOrden(compras.entorno.producto(), dec(1), dec(0))])
        with pytest.raises(OrdenCompraInvalida, match="total cero"):
            emitir_orden(gratis, puede_aprobar=True)


class TestReabrirAnularCerrar:
    def test_reabrir_una_emitida_sin_recepciones(self, pedir):
        o = reabrir_orden(emitir_orden(pedir(), puede_aprobar=True))
        assert o.estado == Estado.BORRADOR and o.emitida_en is None and o.aprobada_en is None

    def test_reabrir_una_por_aprobar(self, pedir, compras):
        configurar(compras, monto="100")
        o = reabrir_orden(emitir_orden(pedir(), puede_aprobar=False))
        assert o.estado == Estado.BORRADOR

    def test_no_se_reabre_ni_anula_con_recepciones(self, pedir):
        o = emitir_orden(pedir(), puede_aprobar=True)
        recibir(o, 3)
        with pytest.raises(OrdenCompraNoModificable, match="ya recibió"):
            reabrir_orden(o)
        with pytest.raises(OrdenCompraNoModificable, match="ciérrala"):
            anular_orden(o, motivo="Error")

    def test_anular_con_motivo(self, pedir):
        o = pedir()
        with pytest.raises(OrdenCompraInvalida, match="motivo"):
            anular_orden(o, motivo="")
        o = anular_orden(o, motivo="El proveedor ya no vende")
        assert (o.estado, o.motivo_anulacion) == (Estado.ANULADA, "El proveedor ya no vende")
        assert o.anulada_en is not None
        with pytest.raises(OrdenCompraNoModificable):
            anular_orden(o, motivo="Otra vez")

    def test_anular_una_emitida(self, pedir):
        o = anular_orden(emitir_orden(pedir(), puede_aprobar=True), motivo="Ya no se necesita")
        assert o.estado == Estado.ANULADA

    def test_cerrar_solo_una_recibida_en_parte(self, pedir):
        o = emitir_orden(pedir(), puede_aprobar=True)
        with pytest.raises(OrdenCompraNoModificable, match="cerrar"):
            cerrar_orden(o, motivo="No entrega más")
        recibir(o, 4)
        o = recalcular_estado(o)
        assert o.estado == Estado.PARCIAL
        with pytest.raises(OrdenCompraInvalida, match="motivo"):
            cerrar_orden(o, motivo="")
        o = cerrar_orden(o, motivo="El proveedor no entregará el resto")
        assert (o.estado, o.cerrada_en is not None) == (Estado.CERRADA, True)

    def test_una_orden_anulada_o_cerrada_no_vuelve_a_cambiar(self, pedir):
        o = anular_orden(pedir(), motivo="Error")
        for accion in (
            lambda: emitir_orden(o, puede_aprobar=True),
            lambda: reabrir_orden(o),
            lambda: cerrar_orden(o, motivo="No aplica"),
        ):
            with pytest.raises(OrdenCompraNoModificable):
                accion()


class TestEstadoPorRecepcion:
    def test_pasa_a_parcial_y_a_recibida_y_vuelve(self, pedir):
        o = emitir_orden(pedir(), puede_aprobar=True)
        assert recalcular_estado(o).estado == Estado.EMITIDA
        recibir(o, 4)
        assert recalcular_estado(o).estado == Estado.PARCIAL
        recibir(o, 10)
        assert recalcular_estado(o).estado == Estado.RECIBIDA
        recibir(o, 0)  # se anuló la recepción
        assert recalcular_estado(o).estado == Estado.EMITIDA

    def test_todas_las_lineas_deben_llegar(self, pedir, compras):
        a, b = compras.entorno.producto("A"), compras.entorno.producto("B")
        o = emitir_orden(
            pedir([LineaOrden(a, dec(5), dec(1)), LineaOrden(b, dec(5), dec(1))]),
            puede_aprobar=True,
        )
        recibir(o, 5, linea=0)
        assert recalcular_estado(o).estado == Estado.PARCIAL
        recibir(o, 5, linea=1)
        assert recalcular_estado(o).estado == Estado.RECIBIDA

    def test_no_toca_otros_estados(self, pedir):
        o = pedir()
        assert recalcular_estado(o).estado == Estado.BORRADOR


class TestPendiente:
    def test_pendiente_y_maximo_sin_tolerancia(self, pedir):
        o = emitir_orden(pedir(), puede_aprobar=True)
        recibir(o, 4)
        fila = pendiente_de_recibir(o)[0]
        assert (fila["pedido"], fila["recibido"], fila["pendiente"], fila["maximo_recibible"]) == (
            dec(10),
            dec(4),
            dec(6),
            dec(6),
        )

    def test_la_tolerancia_amplia_el_maximo(self, pedir, compras):
        configurar(compras, tolerancia="10")
        assert tolerancia_de_recepcion(compras.empresa) == dec("10")
        o = emitir_orden(pedir(), puede_aprobar=True)
        recibir(o, 4)
        fila = pendiente_de_recibir(o)[0]
        assert (fila["pendiente"], fila["maximo_recibible"]) == (dec(6), dec(7))

    def test_lo_recibido_de_mas_no_da_pendiente_negativo(self, pedir, compras):
        configurar(compras, tolerancia="10")
        o = emitir_orden(pedir(), puede_aprobar=True)
        recibir(o, 11)
        fila = pendiente_de_recibir(o)[0]
        assert (fila["pendiente"], fila["maximo_recibible"]) == (0, 0)
        assert recalcular_estado(o).estado == Estado.RECIBIDA


class TestPermisosDelCatalogo:
    def test_estan_los_permisos_y_los_roles(self):
        from apps.seguridad import permisos_catalogo as cat

        codigos = {p.codigo: p for p in cat.PERMISOS}
        for c in ("VER", "CREAR", "EDITAR", "APROBAR", "ANULAR", "CERRAR"):
            assert f"ORDENES_COMPRA.{c}" in codigos
        assert all(codigos[f"ORDENES_COMPRA.{c}"].critico for c in ("APROBAR", "ANULAR", "CERRAR"))
        roles = {r.codigo: r.permisos for r in cat.ROLES_PLANTILLA}
        assert {"ORDENES_COMPRA.VER", "ORDENES_COMPRA.CREAR", "ORDENES_COMPRA.EDITAR"} <= set(
            roles["ALMACENERO"]
        )
        assert "ORDENES_COMPRA.APROBAR" not in roles["ALMACENERO"]
        assert "ORDENES_COMPRA.VER" in roles["CONTADOR"]
        assert "ORDENES_COMPRA.CREAR" not in roles["CONTADOR"]
        assert all(f"ORDENES_COMPRA.{c}" in roles["ADMIN"] for c in ("VER", "APROBAR", "CERRAR"))
