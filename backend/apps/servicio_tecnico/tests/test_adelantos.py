"""Adelantos del cliente: recibo interno, caja, descuento al facturar, devolución y anulación."""

from decimal import Decimal

import pytest

from apps.caja.models import MovimientoCaja, Origen
from apps.core.exceptions import ErrorDominio
from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import adelantos, entrega, presupuesto, servicios
from apps.servicio_tecnico.exceptions import OrdenInvalida
from apps.servicio_tecnico.models import AdelantoServicio, EstadoAdelanto, EstadoOrden
from apps.servicio_tecnico.tests.test_garantia import _terminada
from apps.servicio_tecnico.tests.test_presupuesto import BASE, _en_aprobacion
from apps.ventas.models import CobroVenta
from apps.ventas.servicios import CobroEntrada, anular_venta

pytestmark = pytest.mark.django_db

E = EstadoOrden


def _adelanto(banco, orden, monto="20.00", **extra):
    datos = {"monto": Decimal(monto), "medio_pago": banco.tienda.efectivo}
    datos.update(extra)
    return adelantos.registrar_adelanto(orden, **datos)


def _entregar(banco, orden, monto=None, **extra):
    datos = {"tipo_comprobante": "NV", "vendedor_nombre": "Rosa Pérez"}
    datos["cobros"] = [CobroEntrada(banco.tienda.efectivo, Decimal(monto))] if monto else []
    datos.update(extra)
    return entrega.entregar_equipo(orden, **datos)


def _movimientos(origen, adelanto):
    return MovimientoCaja.objects.filter(origen_tipo=origen, origen_id=adelanto.pk)


class TestRecibir:
    def test_da_un_recibo_interno_y_el_dinero_entra_a_la_caja(self, banco):
        orden = banco.orden()
        a = _adelanto(banco, orden, referencia="")
        assert (a.codigo, a.estado, a.monto) == (
            "RA-0001",
            EstadoAdelanto.VIGENTE,
            Decimal("20.00"),
        )
        ingreso = _movimientos(Origen.ADELANTO_SERVICIO, a).get()
        assert (ingreso.tipo, ingreso.monto, ingreso.cuenta_id) == (
            "INGRESO",
            Decimal("20.00"),
            a.cuenta_id,
        )
        assert adelantos.resumen(orden) == {
            "disponible": Decimal("20.00"),
            "aplicado": Decimal("0"),
            "devuelto": Decimal("0"),
        }

    def test_numera_por_empresa_y_se_puede_dejar_mas_de_uno(self, banco):
        orden = banco.orden()
        otra = banco.orden(empresa=banco.otra)
        assert [_adelanto(banco, orden).codigo, _adelanto(banco, orden, "5.50").codigo] == [
            "RA-0001",
            "RA-0002",
        ]
        assert _adelanto(banco, otra).codigo == "RA-0001"
        assert adelantos.total_disponible(orden) == Decimal("25.50")

    @pytest.mark.parametrize("monto", ["0", "-5", "10.555", "100000"])
    def test_el_monto_se_valida(self, banco, monto):
        with pytest.raises(OrdenInvalida, match="monto"):
            _adelanto(banco, banco.orden(), monto)

    def test_no_en_una_orden_entregada_ni_en_garantia(self, banco):
        with pytest.raises(OrdenInvalida, match="entregada"):
            _adelanto(banco, banco.orden(estado=E.ENTREGADO))
        garantia = banco.orden(reingreso_de=banco.orden(estado=E.ENTREGADO), es_garantia=True)
        with pytest.raises(OrdenInvalida, match="garantía"):
            _adelanto(banco, garantia)

    def test_se_puede_dejar_antes_del_presupuesto_y_despues_tiene_tope(self, banco):
        orden = banco.orden()
        _adelanto(banco, orden, "500.00")  # sin presupuesto no hay tope
        con_presupuesto = _en_aprobacion(banco, (banco.ram, 1))  # 118.00 con IGV
        _adelanto(banco, con_presupuesto, "100.00")
        with pytest.raises(OrdenInvalida, match="hasta S/ 18.00 más"):
            _adelanto(banco, con_presupuesto, "30.00")
        _adelanto(banco, con_presupuesto, "18.00")

    def test_un_medio_con_operacion_la_pide(self, banco):
        yape = banco.tienda.yape
        yape.requiere_referencia = True
        yape.save()
        with pytest.raises(OrdenInvalida, match="operación"):
            _adelanto(banco, banco.orden(), medio_pago=yape)
        assert not AdelantoServicio.objects.exists()

    def test_el_metodo_debe_estar_activo(self, banco):
        efectivo = banco.tienda.efectivo
        efectivo.estado = "INACTIVO"
        efectivo.save()
        with pytest.raises(OrdenInvalida, match="método"):
            _adelanto(banco, banco.orden())


class TestAlFacturar:
    """Ejemplo del taller: servicio de S/ 118 (100 + IGV) y S/ 20 de adelanto → paga S/ 98."""

    def test_el_comprobante_sale_por_el_total_y_el_cliente_paga_el_saldo(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        a = _adelanto(banco, orden, "20.00")
        _, venta = _entregar(banco, orden, "98.00")
        assert venta.total == Decimal("118.00")
        assert venta.comprobantes.get().total == Decimal("118.00")
        cobros = list(CobroVenta.objects.filter(venta=venta).order_by("id"))
        assert [(c.monto, c.es_adelanto) for c in cobros] == [
            (Decimal("20.00"), True),
            (Decimal("98.00"), False),
        ]
        assert sum(c.monto for c in cobros) == venta.total
        a.refresh_from_db()
        assert a.comprobante_id == venta.comprobantes.get().pk and a.aplicado_en is not None
        assert adelantos.resumen(orden)["aplicado"] == Decimal("20.00")

    def test_el_adelanto_no_entra_dos_veces_a_la_caja(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        a = _adelanto(banco, orden, "20.00")
        _, venta = _entregar(banco, orden, "98.00")
        cobro = CobroVenta.objects.get(venta=venta, es_adelanto=False)
        assert _movimientos(Origen.ADELANTO_SERVICIO, a).count() == 1
        assert (
            MovimientoCaja.objects.filter(
                origen_tipo=Origen.COBRO_VENTA, origen_id=cobro.pk
            ).count()
            == 1
        )
        adelanto_cobro = CobroVenta.objects.get(venta=venta, es_adelanto=True)
        assert not MovimientoCaja.objects.filter(
            origen_tipo=Origen.COBRO_VENTA, origen_id=adelanto_cobro.pk
        ).exists()
        ingresos = sum(
            m.monto for m in MovimientoCaja.objects.filter(tipo="INGRESO", estado="EMITIDO")
        )
        assert ingresos == Decimal("118.00")  # 20 del adelanto + 98 del saldo

    def test_pagar_el_total_de_nuevo_se_rechaza(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _adelanto(banco, orden, "20.00")
        with pytest.raises(ErrorDominio, match="sumar"):
            _entregar(banco, orden, "118.00")
        orden.refresh_from_db()
        assert orden.estado == E.LISTO_ENTREGA
        assert adelantos.total_disponible(orden) == Decimal("20.00")

    def test_si_el_adelanto_cubre_todo_no_se_cobra_nada_mas(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _adelanto(banco, orden, "118.00")
        _, venta = _entregar(banco, orden)
        assert [c.es_adelanto for c in CobroVenta.objects.filter(venta=venta)] == [True]
        orden.refresh_from_db()
        assert orden.estado == E.ENTREGADO

    def test_dos_recibos_se_descuentan_juntos(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _adelanto(banco, orden, "20.00")
        _adelanto(banco, orden, "30.00")
        _, venta = _entregar(banco, orden, "68.00")
        assert CobroVenta.objects.filter(venta=venta, es_adelanto=True).count() == 2

    def test_con_dos_empresas_cobra_la_de_la_orden_y_descuenta_el_adelanto(self, banco):
        otro = banco.tienda.producto("Cargador", costo="20", stock={banco.otra: 5})
        orden = _terminada(banco, (banco.servicio, 1), (otro, 2, banco.otra))
        _adelanto(banco, orden, "20.00")
        _, venta = _entregar(banco, orden, "275.00")  # 295 - 20
        comprobantes = list(venta.comprobantes.all())
        assert [c.empresa_id for c in comprobantes] == [banco.empresa.pk]
        adelanto = CobroVenta.objects.get(venta=venta, es_adelanto=True)
        assert adelanto.comprobante_id == comprobantes[0].pk

    def test_el_adelanto_puede_llegar_al_total_del_presupuesto(self, banco):
        otro = banco.tienda.producto("Cargador", costo="20", stock={banco.otra: 5})
        orden = banco.orden(
            estado=E.DIAGNOSTICADO, diagnostico="Memoria dañada", trabajos_a_realizar="Cambiar"
        )
        _adelanto(banco, orden, "100.00")  # sin presupuesto no había tope
        banco.armar(orden, (banco.servicio, 1), (otro, 2, banco.otra))  # total 295
        servicios.cambiar_estado(orden, E.PENDIENTE_APROBACION)
        presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
        for estado in (E.EN_REPARACION, E.EN_PRUEBAS, E.TERMINADO, E.LISTO_ENTREGA):
            servicios.cambiar_estado(orden, estado)
        _, venta = _entregar(banco, orden, "195.00")  # 295 - 100
        assert venta.total == Decimal("295.00")


class TestDevolver:
    def test_sale_de_la_caja_sin_nota_de_credito(self, banco):
        a = _adelanto(banco, banco.orden(), "20.00")
        adelantos.devolver(a, motivo="El cliente ya no quiere el servicio")
        a.refresh_from_db()
        assert a.estado == EstadoAdelanto.DEVUELTO and a.devuelto_en is not None
        egreso = _movimientos(Origen.DEVOLUCION_ADELANTO, a).get()
        assert (egreso.tipo, egreso.monto, egreso.cuenta_id) == (
            "EGRESO",
            Decimal("20.00"),
            a.cuenta_id,
        )
        assert adelantos.resumen(a.orden)["devuelto"] == Decimal("20.00")
        assert adelantos.total_disponible(a.orden) == Decimal("0")

    def test_pide_motivo_y_no_se_devuelve_dos_veces(self, banco):
        a = _adelanto(banco, banco.orden(), "20.00")
        with pytest.raises(OrdenInvalida, match="motivo"):
            adelantos.devolver(a, motivo=" ")
        adelantos.devolver(a, motivo="El cliente ya no quiere el servicio")
        with pytest.raises(OrdenInvalida, match="devuelto"):
            adelantos.devolver(a, motivo="El cliente ya no quiere el servicio")

    def test_uno_ya_descontado_no_se_devuelve(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        a = _adelanto(banco, orden, "20.00")
        _entregar(banco, orden, "98.00")
        with pytest.raises(OrdenInvalida, match="ya se descontó"):
            adelantos.devolver(a, motivo="Quiero devolverlo")

    def test_si_se_anula_el_comprobante_el_adelanto_vuelve_a_estar_a_favor(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        a = _adelanto(banco, orden, "20.00")
        _, venta = _entregar(banco, orden, "98.00")
        anular_venta(venta, motivo="Error al emitir el comprobante")
        assert adelantos.total_disponible(orden) == Decimal("20.00")
        adelantos.devolver(a, motivo="Se anuló el comprobante")  # ahora sí se puede devolver


class TestAnular:
    def test_deshace_el_ingreso_de_la_caja(self, banco):
        a = _adelanto(banco, banco.orden(), "20.00")
        adelantos.anular(a, motivo="Lo registré con otro monto")
        a.refresh_from_db()
        assert a.estado == EstadoAdelanto.ANULADO
        assert _movimientos(Origen.ADELANTO_SERVICIO, a).get().estado == "ANULADO"
        assert adelantos.resumen(a.orden)["disponible"] == Decimal("0")


class TestEntregarConAdelantosSinCobro:
    def test_un_adelanto_sin_devolver_bloquea_la_entrega_sin_cobro(self, banco):
        orden = _en_aprobacion(banco, (banco.ram, 1))
        a = _adelanto(banco, orden, "20.00")
        presupuesto.aprobar_presupuesto(orden, medio="LLAMADA", nota="Aprobó por llamada")
        servicios.cambiar_estado(orden, E.NO_APROBADO, motivo="El cliente se arrepintió")
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        with pytest.raises(OrdenInvalida, match="por devolver"):
            entrega.entregar_equipo(orden, vendedor_nombre="Rosa")
        adelantos.devolver(a, motivo="El cliente se arrepintió")
        entrega.entregar_equipo(orden, vendedor_nombre="Rosa")
        orden.refresh_from_db()
        assert orden.estado == E.ENTREGADO

    def test_tampoco_se_entrega_sin_cobrar_dejando_un_adelanto(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _adelanto(banco, orden, "20.00")
        with pytest.raises(OrdenInvalida, match="por devolver"):
            entrega.entregar_equipo(
                orden, vendedor_nombre="Rosa", sin_cobro=True, motivo_sin_cobro="Cortesía"
            )


class TestApi:
    def _cuerpo(self, banco, monto="20.00"):
        return {"monto": monto, "medio_pago": banco.tienda.efectivo.pk}

    def test_recibe_devuelve_y_anula_por_la_api(self, banco):
        orden = banco.orden()
        api = cliente_de("admin")
        url = f"{BASE}/ordenes/{orden.pk}/adelantos/"
        r = api.post(url, self._cuerpo(banco), format="json")
        assert r.status_code == 200, r.content
        datos = r.json()["adelantos"]
        assert (
            datos["recibos"][0]["codigo"] == "RA-0001" and datos["resumen"]["disponible"] == "20.00"
        )
        assert datos["recibos"][0]["estado_nombre"] == "Por devolver"
        assert r.json()["permite"]["adelantos"] is True
        adelanto = datos["recibos"][0]["id"]
        r = api.post(
            f"{url}devolver/",
            {"adelanto": adelanto, "motivo": "El cliente ya no quiere"},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert r.json()["adelantos"]["resumen"]["devuelto"] == "20.00"
        r = api.post(url, self._cuerpo(banco, "5.00"), format="json")
        nuevo = r.json()["adelantos"]["recibos"][-1]["id"]
        r = api.post(
            f"{url}anular/", {"adelanto": nuevo, "motivo": "Monto mal escrito"}, format="json"
        )
        assert r.status_code == 200 and r.json()["adelantos"]["recibos"][-1]["estado"] == "ANULADO"

    def test_solo_quien_maneja_adelantos(self, banco):
        orden = banco.orden()
        url = f"{BASE}/ordenes/{orden.pk}/adelantos/"
        assert (
            cliente_de("vendedor").post(url, self._cuerpo(banco), format="json").status_code == 403
        )
        assert cliente_de("tecnico").post(url, self._cuerpo(banco), format="json").status_code in (
            403,
            404,
        )

    def test_datos_invalidos(self, banco):
        orden = banco.orden()
        api = cliente_de("admin")
        url = f"{BASE}/ordenes/{orden.pk}/adelantos/"
        assert (
            api.post(
                url, {"monto": "0", "medio_pago": banco.tienda.efectivo.pk}, format="json"
            ).status_code
            == 400
        )
        assert api.post(url, {"monto": "10", "medio_pago": 99999}, format="json").status_code == 400
        assert (
            api.post(
                f"{url}devolver/", {"adelanto": 99999, "motivo": "No existe"}, format="json"
            ).status_code
            == 404
        )

    def test_la_ficha_dice_cuanto_hay_que_cobrar_con_el_adelanto(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _adelanto(banco, orden, "20.00")
        ficha = cliente_de("admin").get(f"{BASE}/ordenes/{orden.pk}/").json()
        assert ficha["entrega"]["adelantos"] == {
            "total": "20.00",
            "aplicables": "20.00",
            "exceso": "0.00",
            "por_cobrar": "98.00",
        }
        assert ficha["adelanto_disponible"] == "20.00"

    def test_entrega_por_la_api_cobrando_solo_el_saldo(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _adelanto(banco, orden, "20.00")
        efectivo = banco.tienda.efectivo.pk
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/entregar/",
            {"tipo_comprobante": "NV", "cobros": [{"medio_pago": efectivo, "monto": "98.00"}]},
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["estado"] == "ENTREGADO"
        assert datos["adelantos"]["recibos"][0]["aplicado"] is True
        assert datos["adelantos"]["recibos"][0]["comprobante"]

    def test_el_listado_marca_los_adelantos_por_devolver(self, banco):
        con = banco.orden()
        _adelanto(banco, con, "20.00")
        sin = banco.orden()
        r = cliente_de("admin").get(f"{BASE}/ordenes/", {"empresa": banco.empresa.pk})
        filas = {o["id"]: o for o in r.json()["results"]}
        assert filas[con.pk]["adelanto_disponible"] == "20.00"
        assert filas[sin.pk]["adelanto_disponible"] == "0.00"
