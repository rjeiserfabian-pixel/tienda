"""Entregar el equipo: cobrar el presupuesto (un comprobante por empresa) y cerrar la orden."""

from decimal import Decimal

import pytest

from apps.core.exceptions import ErrorDominio
from apps.inventario.models import MovimientoInventario, OrigenMovimiento
from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import entrega, presupuesto, servicios
from apps.servicio_tecnico.exceptions import OrdenInvalida, TransicionInvalida
from apps.servicio_tecnico.models import EstadoOrden
from apps.servicio_tecnico.tests.test_presupuesto import BASE, _con_tecnico, _en_aprobacion
from apps.ventas.models import LineaVenta
from apps.ventas.servicios import CobroEntrada

pytestmark = pytest.mark.django_db

E = EstadoOrden


def _lista_para_entregar(banco, *cosas):
    """Una orden con el trabajo terminado: aprobada, reparada, probada y lista."""
    orden = _en_aprobacion(banco, *cosas)
    presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
    servicios.cambiar_estado(orden, E.EN_REPARACION)
    servicios.cambiar_estado(orden, E.EN_PRUEBAS)
    servicios.cambiar_estado(orden, E.TERMINADO)
    servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
    return orden


def _entregar(banco, orden, monto, **extra):
    datos = {
        "tipo_comprobante": "NV",
        "cobros": [CobroEntrada(banco.tienda.efectivo, Decimal(monto))],
        "vendedor_nombre": "Rosa Pérez",
    }
    datos.update(extra)
    return entrega.entregar_equipo(orden, **datos)


class TestEntrega:
    def test_cobra_el_presupuesto_y_cierra_la_orden(self, banco):
        orden = _lista_para_entregar(banco, (banco.servicio, 1), (banco.ram, 2))
        _, venta = _entregar(banco, orden, "295.00")
        orden.refresh_from_db()
        assert orden.estado == E.ENTREGADO and orden.fecha_entrega is not None
        assert venta.total == Decimal("295.00") and venta.comprobantes.count() == 1
        assert venta.proforma_id == presupuesto.vigente_de(orden).proforma_id
        assert presupuesto.vigente_de(orden).venta_id == venta.pk
        assert venta.comprobantes.get().cobros.count() == 1

    def test_los_repuestos_no_se_descuentan_dos_veces(self, banco):
        orden = _lista_para_entregar(banco, (banco.servicio, 1), (banco.ram, 2))
        _entregar(banco, orden, "295.00")
        assert banco.stock(banco.ram, banco.e.alm1) == 8  # 10 menos los 2 del servicio, una vez
        assert not MovimientoInventario.objects.filter(origen=OrigenMovimiento.VENTA).exists()

    def test_el_costo_de_la_venta_es_el_real_del_repuesto(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 2))
        _, venta = _entregar(banco, orden, "236.00")
        linea = LineaVenta.objects.get(venta=venta)
        assert (linea.costo_total, linea.almacen_id, linea.movimiento_id) == (
            Decimal("100.00"),
            None,
            None,
        )

    def test_con_repuestos_de_dos_empresas_cobra_la_de_la_orden_y_queda_deuda(self, banco):
        from apps.ventas.models import DeudaInterna, VentaInterna

        otro = banco.tienda.producto("Cargador", costo="20", stock={banco.otra: 5})
        orden = _lista_para_entregar(banco, (banco.servicio, 1), (otro, 2, banco.otra))
        _, venta = _entregar(banco, orden, "295.00")
        comprobantes = list(venta.comprobantes.all())
        assert [c.empresa_id for c in comprobantes] == [banco.empresa.pk]
        assert comprobantes[0].total == Decimal("295.00")
        interna = VentaInterna.objects.sin_ambito().get(venta=venta)
        assert (interna.empresa_id, interna.empresa_destino_id) == (banco.otra.pk, banco.empresa.pk)
        assert interna.total_costo == Decimal("40.00")  # 2 cargadores al costo de 20
        deuda = DeudaInterna.objects.sin_ambito().get(venta_interna=interna)
        assert (deuda.empresa_id, deuda.acreedora_id) == (banco.empresa.pk, banco.otra.pk)
        assert deuda.monto == Decimal("40.00")

    def test_si_todo_lo_surtio_la_otra_empresa_igual_cobra_la_de_la_orden(self, banco):
        from apps.ventas.models import DeudaInterna

        otro = banco.tienda.producto("Teclado", costo="90", stock={banco.otra: 3})
        orden = _lista_para_entregar(banco, (otro, 1, banco.otra))
        _, venta = _entregar(banco, orden, "118.00")
        assert {c.empresa_id for c in venta.comprobantes.all()} == {banco.empresa.pk}
        assert DeudaInterna.objects.sin_ambito().get().monto == Decimal("90.00")

    def test_el_cobro_incompleto_no_deja_nada_a_medias(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        with pytest.raises(ErrorDominio):
            _entregar(banco, orden, "10.00")
        orden.refresh_from_db()
        assert orden.estado == E.LISTO_ENTREGA
        assert presupuesto.vigente_de(orden).venta_id is None

    def test_pide_el_tipo_de_comprobante(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        with pytest.raises(OrdenInvalida, match="comprobante"):
            _entregar(banco, orden, "118.00", tipo_comprobante="")

    def test_una_vez_entregada_no_se_entrega_otra_vez(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        _entregar(banco, orden, "118.00")
        with pytest.raises(TransicionInvalida):
            _entregar(banco, orden, "118.00")

    def test_entregar_sin_cobrar_pide_motivo_y_queda_anotado(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        with pytest.raises(OrdenInvalida, match="sin cobrar"):
            entrega.entregar_equipo(
                orden, vendedor_nombre="Rosa", sin_cobro=True, motivo_sin_cobro=" "
            )
        _, venta = entrega.entregar_equipo(
            orden,
            vendedor_nombre="Rosa",
            sin_cobro=True,
            motivo_sin_cobro="Reparación por garantía",
        )
        assert venta is None
        assert presupuesto.vigente_de(orden).entregado_sin_cobro == "Reparación por garantía"
        orden.refresh_from_db()
        assert orden.estado == E.ENTREGADO

    def test_un_equipo_devuelto_sin_reparar_no_cobra(self, banco):
        orden = _en_aprobacion(banco, (banco.ram, 1))
        presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
        servicios.cambiar_estado(orden, E.NO_APROBADO, motivo="El cliente se arrepintió")
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        assert entrega.a_cobrar(orden) is None
        with pytest.raises(OrdenInvalida, match="no cobra"):
            entrega.entregar_equipo(
                orden, vendedor_nombre="Rosa", sin_cobro=True, motivo_sin_cobro="Cortesía"
            )
        _, venta = entrega.entregar_equipo(orden, vendedor_nombre="Rosa")
        assert venta is None
        orden.refresh_from_db()
        assert orden.estado == E.ENTREGADO

    def test_solo_se_entrega_lo_que_esta_listo(self, banco):
        orden = banco.orden(estado=E.TERMINADO)
        with pytest.raises(TransicionInvalida, match="listo"):
            entrega.entregar_equipo(orden, vendedor_nombre="Rosa")


class TestApiEntrega:
    def test_la_ficha_dice_que_hay_que_cobrar_y_cuanto(self, banco):
        orden = _lista_para_entregar(banco, (banco.servicio, 1), (banco.ram, 2))
        _con_tecnico(banco, orden)
        ficha = cliente_de("admin").get(f"{BASE}/ordenes/{orden.pk}/").json()
        assert ficha["entrega"]["cobra"] is True and ficha["entrega"]["total"] == "295.00"
        assert ficha["entrega"]["por_empresa"][0]["total"] == "295.00"
        assert cliente_de("tecnico").get(f"{BASE}/ordenes/{orden.pk}/").json()["entrega"] is None

    def test_entrega_y_devuelve_la_venta_para_imprimir(self, banco):
        orden = _lista_para_entregar(banco, (banco.servicio, 1), (banco.ram, 2))
        efectivo = banco.tienda.efectivo.pk
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/entregar/",
            {"tipo_comprobante": "NV", "cobros": [{"medio_pago": efectivo, "monto": "295.00"}]},
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["estado"] == "ENTREGADO"
        assert len(datos["venta"]["comprobantes"]) == 1
        assert datos["presupuesto"]["venta"]["id"] == datos["venta"]["id"]
        assert datos["historial"][-1]["motivo"].startswith("Equipo entregado y cobrado")

    def test_el_tecnico_y_el_vendedor_no_entregan(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        _con_tecnico(banco, orden)
        efectivo = banco.tienda.efectivo.pk
        cuerpo = {"tipo_comprobante": "NV", "cobros": [{"medio_pago": efectivo, "monto": "118.00"}]}
        url = f"{BASE}/ordenes/{orden.pk}/entregar/"
        assert cliente_de("tecnico").post(url, cuerpo, format="json").status_code == 403
        assert cliente_de("vendedor").post(url, cuerpo, format="json").status_code == 403

    def test_sin_cobrar_con_permiso_y_motivo(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        cuerpo = {"sin_cobro": True, "motivo": "Garantía del servicio anterior"}
        r = cliente_de("admin").post(f"{BASE}/ordenes/{orden.pk}/entregar/", cuerpo, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["presupuesto"]["entregado_sin_cobro"] == "Garantía del servicio anterior"

    def test_metodo_de_pago_inexistente(self, banco):
        orden = _lista_para_entregar(banco, (banco.ram, 1))
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/entregar/",
            {"tipo_comprobante": "NV", "cobros": [{"medio_pago": 99999, "monto": "118.00"}]},
            format="json",
        )
        assert r.status_code == 400
