"""Entrega con quién recoge, garantía del servicio, reingreso por garantía y equipos abandonados."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import entrega, garantia, presupuesto, servicios, trabajo
from apps.servicio_tecnico.exceptions import (
    AbandonoNoPermitido,
    OrdenInvalida,
    PresupuestoInvalido,
)
from apps.servicio_tecnico.models import (
    EstadoOrden,
    EstadoRepuesto,
    HistorialEstado,
    RepuestoOrden,
    TipoServicio,
)
from apps.servicio_tecnico.tests.test_presupuesto import BASE, _en_aprobacion
from apps.ventas.servicios import CobroEntrada

pytestmark = pytest.mark.django_db

E = EstadoOrden


def _terminada(banco, *cosas, codigo="REPARACION_HW", **extra):
    """Una orden de un servicio con garantía, terminada y lista para entregar."""
    tipo = TipoServicio.objects.get(codigo=codigo)
    orden = banco.orden(
        estado=E.DIAGNOSTICADO,
        diagnostico="Memoria dañada",
        trabajos_a_realizar="Cambiar",
        tipo_servicio=tipo,
        **extra,
    )
    banco.armar(orden, *cosas)
    servicios.cambiar_estado(orden, E.PENDIENTE_APROBACION)
    presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
    for estado in (E.EN_REPARACION, E.EN_PRUEBAS, E.TERMINADO, E.LISTO_ENTREGA):
        servicios.cambiar_estado(orden, estado)
    return orden


def _entregar(banco, orden, monto="118.00", **extra):
    datos = {
        "tipo_comprobante": "NV",
        "cobros": [CobroEntrada(banco.tienda.efectivo, Decimal(monto))],
        "vendedor_nombre": "Rosa Pérez",
    }
    datos.update(extra)
    return entrega.entregar_equipo(orden, **datos)


def _envejecer(orden, dias):
    """Retrocede la fecha en que la orden entró a su estado (el historial no se edita por ORM)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE servicio_tecnico_historialestado SET creado_en = %s "
            "WHERE orden_id = %s AND estado_nuevo = %s",
            [timezone.now() - timedelta(days=dias), orden.pk, orden.estado],
        )


class TestQuienRecoge:
    def test_el_titular_basta_marcarlo(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _entregar(banco, orden)
        orden.refresh_from_db()
        assert (orden.recogio_nombre, orden.recogio_documento, orden.recogio_es_titular) == (
            "Luis Ramos",
            "45871236",
            True,
        )

    def test_otra_persona_deja_su_nombre_y_documento(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _entregar(
            banco,
            orden,
            recoge_es_titular=False,
            recoge_nombre="  Rosa   Díaz ",
            recoge_documento=" 40123 456 ",
        )
        orden.refresh_from_db()
        assert (orden.recogio_nombre, orden.recogio_documento, orden.recogio_es_titular) == (
            "Rosa Díaz",
            "40123456",
            False,
        )
        assert "Recogió Rosa Díaz (DNI 40123456)" in orden.historial.last().motivo

    def test_otra_persona_sin_datos_no_se_entrega(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        with pytest.raises(OrdenInvalida, match="nombre"):
            _entregar(banco, orden, recoge_es_titular=False)
        with pytest.raises(OrdenInvalida, match="documento"):
            _entregar(banco, orden, recoge_es_titular=False, recoge_nombre="Rosa Díaz")
        orden.refresh_from_db()
        assert orden.estado == E.LISTO_ENTREGA


class TestGarantia:
    def test_corre_desde_la_entrega_segun_el_tipo_de_servicio(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _entregar(banco, orden)
        orden.refresh_from_db()
        assert orden.garantia_dias == 30
        assert orden.garantia_hasta == timezone.localdate() + timedelta(days=30)
        estado = garantia.estado_de(orden)
        assert (estado.vigente, estado.dias_restantes) == (True, 30)

    def test_sin_garantia_si_el_servicio_no_la_tiene(self, banco):
        orden = _terminada(banco, (banco.ram, 1), codigo="DIAGNOSTICO")
        _entregar(banco, orden)
        orden.refresh_from_db()
        assert (orden.garantia_dias, orden.garantia_hasta) == (0, None)
        assert garantia.estado_de(orden).vigente is False

    def test_un_equipo_devuelto_sin_reparar_no_lleva_garantia(self, banco):
        tipo = TipoServicio.objects.get(codigo="REPARACION_HW")
        orden = _en_aprobacion(banco, (banco.ram, 1))
        orden.tipo_servicio = tipo
        orden.save(update_fields=["tipo_servicio"])
        presupuesto.aprobar_presupuesto(orden, medio="LLAMADA", nota="Aprobó por llamada")
        servicios.cambiar_estado(orden, E.NO_APROBADO, motivo="El cliente se arrepintió")
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        entrega.entregar_equipo(orden, vendedor_nombre="Rosa")
        orden.refresh_from_db()
        assert orden.garantia_dias == 0


class TestReingreso:
    def _entregada(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _entregar(banco, orden)
        return orden

    def test_crea_una_orden_ligada_para_el_mismo_equipo(self, banco):
        original = self._entregada(banco)
        nueva = garantia.reingreso_por_garantia(original, falla_reportada="Vuelve a no dar video")
        assert nueva.estado == E.RECIBIDO and nueva.es_garantia is True
        assert nueva.reingreso_de_id == original.pk
        assert (nueva.equipo_id, nueva.cliente_id) == (original.equipo_id, original.cliente_id)
        assert nueva.tipo_servicio_id == original.tipo_servicio_id
        assert nueva.historial.get().motivo == f"Reingreso por garantía de {original.codigo}"
        assert list(original.reingresos.all()) == [nueva]

    def test_no_se_reingresa_sin_garantia_vigente(self, banco):
        sin = _terminada(banco, (banco.ram, 1), codigo="DIAGNOSTICO")
        _entregar(banco, sin)
        with pytest.raises(OrdenInvalida, match="no tiene garantía"):
            garantia.reingreso_por_garantia(sin, falla_reportada="Vuelve a fallar")
        vencida = self._entregada(banco)
        vencida.garantia_hasta = timezone.localdate() - timedelta(days=1)
        vencida.save(update_fields=["garantia_hasta"])
        with pytest.raises(OrdenInvalida, match="venció"):
            garantia.reingreso_por_garantia(vencida, falla_reportada="Vuelve a fallar")

    def test_solo_un_equipo_entregado(self, banco):
        orden = banco.orden(estado=E.LISTO_ENTREGA)
        with pytest.raises(OrdenInvalida, match="ya se entregó"):
            garantia.reingreso_por_garantia(orden, falla_reportada="Vuelve a fallar")

    def test_un_solo_reingreso_abierto_y_la_garantia_no_se_encadena(self, banco):
        original = self._entregada(banco)
        nueva = garantia.reingreso_por_garantia(original, falla_reportada="Vuelve a fallar")
        with pytest.raises(OrdenInvalida, match="en curso"):
            garantia.reingreso_por_garantia(original, falla_reportada="Otra vez la falla")
        nueva.estado = E.ENTREGADO
        nueva.save(update_fields=["estado"])
        with pytest.raises(OrdenInvalida, match="reingreso por garantía"):
            garantia.reingreso_por_garantia(nueva, falla_reportada="Y otra vez más")

    def test_la_falla_es_obligatoria(self, banco):
        original = self._entregada(banco)
        with pytest.raises(OrdenInvalida, match="falla"):
            garantia.reingreso_por_garantia(original, falla_reportada=" no ")

    def test_la_garantia_se_trabaja_y_se_entrega_sin_cobrar(self, banco):
        original = self._entregada(banco)
        nueva = garantia.reingreso_por_garantia(original, falla_reportada="Vuelve a no dar video")
        servicios.cambiar_estado(nueva, E.EN_DIAGNOSTICO)
        trabajo.registrar_diagnostico(
            nueva, diagnostico="La memoria nueva venía fallada", trabajos_a_realizar="Cambiarla"
        )
        servicios.cambiar_estado(nueva, E.DIAGNOSTICADO)
        # Sin esperar la aprobación del cliente: es garantía.
        servicios.cambiar_estado(nueva, E.EN_REPARACION)
        for estado in (E.EN_PRUEBAS, E.TERMINADO, E.LISTO_ENTREGA):
            servicios.cambiar_estado(nueva, estado)
        assert entrega.a_cobrar(nueva) is None
        with pytest.raises(OrdenInvalida, match="no cobra"):
            entrega.entregar_equipo(
                nueva, vendedor_nombre="Rosa", sin_cobro=True, motivo_sin_cobro="Cortesía"
            )
        _, venta = entrega.entregar_equipo(nueva, vendedor_nombre="Rosa")
        nueva.refresh_from_db()
        assert venta is None and nueva.estado == E.ENTREGADO and nueva.garantia_dias == 0

    def test_la_garantia_puede_usar_repuestos_del_stock(self, banco):
        original = self._entregada(banco)
        nueva = garantia.reingreso_por_garantia(original, falla_reportada="Vuelve a no dar video")
        nueva.diagnostico, nueva.trabajos_a_realizar = "Memoria fallada", "Cambiarla"
        nueva.estado = E.DIAGNOSTICADO
        nueva.save(update_fields=["diagnostico", "trabajos_a_realizar", "estado"])
        banco.armar(nueva, (banco.ram, 1))
        presupuesto.aprobar_presupuesto(
            nueva, medio="OTRO", nota="Garantía: no necesita aprobación"
        )
        servicios.cambiar_estado(nueva, E.EN_REPARACION)
        assert (
            RepuestoOrden.objects.get(presupuesto__orden=nueva).estado == EstadoRepuesto.CONSUMIDO
        )


class TestAbandono:
    def _esperando(self, banco):
        return _terminada(banco, (banco.ram, 1))

    def test_exige_haber_avisado_al_cliente(self, banco):
        orden = self._esperando(banco)
        _envejecer(orden, 60)
        with pytest.raises(AbandonoNoPermitido, match="avisar"):
            servicios.cambiar_estado(orden, E.ABANDONADO, motivo="No responde ni viene")

    def test_exige_esperar_el_plazo(self, banco):
        orden = self._esperando(banco)
        trabajo.registrar_aviso(orden, medio="WHATSAPP", mensaje="Ya puede recoger su equipo")
        _envejecer(orden, 10)
        with pytest.raises(AbandonoNoPermitido, match="30 días"):
            servicios.cambiar_estado(orden, E.ABANDONADO, motivo="No responde ni viene")

    def test_con_aviso_y_plazo_cumplido_se_da_por_abandonado(self, banco):
        orden = self._esperando(banco)
        trabajo.registrar_aviso(orden, medio="LLAMADA", mensaje="Se le llamó dos veces")
        _envejecer(orden, 45)
        servicios.cambiar_estado(orden, E.ABANDONADO, motivo="No responde ni viene")
        orden.refresh_from_db()
        assert orden.estado == E.ABANDONADO

    def test_un_abandonado_aun_se_puede_entregar_si_aparece(self, banco):
        orden = self._esperando(banco)
        trabajo.registrar_aviso(orden, medio="LLAMADA", mensaje="Se le llamó dos veces")
        _envejecer(orden, 45)
        servicios.cambiar_estado(orden, E.ABANDONADO, motivo="No responde ni viene")
        servicios.cambiar_estado(orden, E.LISTO_ENTREGA)
        assert entrega.a_cobrar(orden) is None  # ya no vino de «terminado»

    def test_los_dias_se_cuentan_desde_que_entro_al_estado(self, banco):
        orden = self._esperando(banco)
        assert servicios.dias_esperando(orden) == 0
        _envejecer(orden, 12)
        assert servicios.dias_esperando(orden) == 12


class TestApi:
    def _entregada(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _entregar(banco, orden)
        return orden

    def test_la_ficha_de_una_entregada_muestra_garantia_y_permite_el_reingreso(self, banco):
        orden = self._entregada(banco)
        ficha = cliente_de("admin").get(f"{BASE}/ordenes/{orden.pk}/").json()
        assert ficha["garantia"]["vigente"] is True and ficha["garantia"]["dias"] == 30
        assert ficha["recogio_nombre"] == "Luis Ramos" and ficha["recogio_es_titular"] is True
        assert ficha["permite"]["reingreso"] is True
        assert ficha["presupuesto"]["venta"]["comprobantes"][0]["numero_completo"]

    def test_reingreso_por_la_api(self, banco):
        orden = self._entregada(banco)
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/reingreso/",
            {"falla_reportada": "Vuelve a no dar video", "estado_fisico": "Sin golpes nuevos"},
            format="json",
        )
        assert r.status_code == 201, r.content
        datos = r.json()
        assert datos["es_garantia"] is True and datos["reingreso_de"] == orden.pk
        assert datos["reingreso_de_codigo"] == orden.codigo
        original = cliente_de("admin").get(f"{BASE}/ordenes/{orden.pk}/").json()
        assert [x["id"] for x in original["reingresos"]] == [datos["id"]]
        assert original["permite"]["reingreso"] is False  # ya hay un reingreso abierto

    def test_reingreso_solo_para_quien_recibe_equipos(self, banco):
        orden = self._entregada(banco)
        cuerpo = {"falla_reportada": "Vuelve a no dar video"}
        url = f"{BASE}/ordenes/{orden.pk}/reingreso/"
        # El técnico no ve las órdenes ajenas (404); el vendedor las ve pero no puede (403).
        assert cliente_de("tecnico").post(url, cuerpo, format="json").status_code in (403, 404)
        assert cliente_de("vendedor").post(url, cuerpo, format="json").status_code == 403

    def test_reingreso_vencido_se_rechaza(self, banco):
        orden = self._entregada(banco)
        orden.garantia_hasta = timezone.localdate() - timedelta(days=1)
        orden.save(update_fields=["garantia_hasta"])
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/reingreso/",
            {"falla_reportada": "Vuelve a no dar video"},
            format="json",
        )
        assert r.status_code == 400
        ficha = cliente_de("admin").get(f"{BASE}/ordenes/{orden.pk}/").json()
        assert ficha["permite"]["reingreso"] is False and ficha["garantia"]["vigente"] is False

    def test_entregar_con_otra_persona_por_la_api(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        otra = _terminada(banco, (banco.ram, 1))
        efectivo = banco.tienda.efectivo.pk
        cuerpo = {
            "tipo_comprobante": "NV",
            "cobros": [{"medio_pago": efectivo, "monto": "118.00"}],
            "recoge_es_titular": False,
            "recoge_nombre": "Rosa Díaz",
            "recoge_documento": "40123456",
        }
        r = cliente_de("admin").post(f"{BASE}/ordenes/{orden.pk}/entregar/", cuerpo, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["recogio_nombre"] == "Rosa Díaz" and r.json()["recogio_es_titular"] is False
        malo = {**cuerpo, "recoge_nombre": ""}
        r = cliente_de("admin").post(f"{BASE}/ordenes/{otra.pk}/entregar/", malo, format="json")
        assert r.status_code == 400

    def test_los_equipos_sin_recoger_se_listan_y_se_marcan(self, banco):
        vieja = _terminada(banco, (banco.ram, 1))
        reciente = _terminada(banco, (banco.ram, 1))
        trabajo.registrar_aviso(vieja, medio="LLAMADA", mensaje="Se le llamó dos veces")
        _envejecer(vieja, 45)
        api = cliente_de("admin")
        base = {"empresa": banco.empresa.pk}
        lista = api.get(f"{BASE}/ordenes/", {**base, "sin_recoger": "1"}).json()["results"]
        assert [o["id"] for o in lista] == [vieja.pk]
        assert lista[0]["por_abandonar"] is True and lista[0]["dias_en_estado"] >= 45
        todas = {o["id"]: o for o in api.get(f"{BASE}/ordenes/", base).json()["results"]}
        assert todas[reciente.pk]["por_abandonar"] is False
        ficha = api.get(f"{BASE}/ordenes/{vieja.pk}/").json()
        assert ficha["abandono"]["puede"] is True and ficha["abandono"]["avisos"] == 1
        assert api.get(f"{BASE}/ordenes/{reciente.pk}/").json()["abandono"]["puede"] is False

    def test_dar_por_abandonado_por_la_api_pide_aviso_y_plazo(self, banco):
        orden = _terminada(banco, (banco.ram, 1))
        _envejecer(orden, 60)
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/estado/",
            {"estado": "ABANDONADO", "motivo": "No responde ni viene"},
            format="json",
        )
        assert r.status_code == 409


class TestServiciosSonDeLaEmpresaDeLaOrden:
    def test_un_servicio_de_la_otra_empresa_se_rechaza(self, banco):
        with pytest.raises(PresupuestoInvalido, match="lo factura la empresa de la orden"):
            banco.armar(banco.orden(), (banco.servicio, 1, banco.otra))

    def test_un_repuesto_si_puede_ser_de_la_otra_empresa(self, banco):
        cargador = banco.tienda.producto("Cargador", stock={banco.otra: 3})
        assert banco.armar(banco.orden(), (cargador, 1, banco.otra)).repuestos.count() == 1


def test_el_historial_de_la_entrega_queda_completo(banco):
    orden = _terminada(banco, (banco.ram, 1))
    _entregar(banco, orden)
    ultimo = HistorialEstado.objects.filter(orden=orden).latest("id")
    assert ultimo.estado_nuevo == E.ENTREGADO
    assert "Garantía de 30 días" in ultimo.motivo
