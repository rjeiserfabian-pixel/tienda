"""Presupuesto (proforma de Ventas), aprobación y el stock de los repuestos de una orden."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.core.exceptions import ErrorDominio
from apps.inventario.models import (
    LineaMovimiento,
    MovimientoInventario,
    OrigenMovimiento,
)
from apps.inventario.tests.conftest import comprar as ingresar_stock
from apps.mantenimiento.models import Personal, TipoAlmacen
from apps.servicio_tecnico import presupuesto, repuestos, servicios
from apps.servicio_tecnico.exceptions import (
    OrdenInvalida,
    PresupuestoInvalido,
    PresupuestoRequerido,
    RepuestosPendientes,
    TransicionInvalida,
)
from apps.servicio_tecnico.models import (
    EstadoOrden,
    EstadoRepuesto,
    PresupuestoOrden,
    RepuestoOrden,
)
from apps.servicio_tecnico.presupuesto import LineaPresupuesto
from apps.ventas.models import Proforma

pytestmark = pytest.mark.django_db

E = EstadoOrden


def _en_aprobacion(banco, *cosas):
    """Una orden con presupuesto armado y enviada a aprobación."""
    orden = banco.orden(
        estado=E.DIAGNOSTICADO, diagnostico="Memoria dañada", trabajos_a_realizar="Cambiar"
    )
    banco.armar(orden, *cosas)
    servicios.cambiar_estado(orden, E.PENDIENTE_APROBACION)
    return orden


class TestArmar:
    def test_arma_la_proforma_con_servicios_y_repuestos(self, banco):
        orden = banco.orden()
        p = banco.armar(orden, (banco.servicio, 1), (banco.ram, 2))
        assert (p.version, p.vigente) == (1, True)
        assert p.proforma.estado == Proforma.Estado.EMITIDO
        assert p.proforma.cliente_id == banco.cliente.pk
        assert p.proforma.total == Decimal("295.00")  # (50 + 2 × 100) con IGV
        assert p.proforma.lineas.count() == 2
        assert orden.codigo in p.proforma.condiciones

    def test_solo_los_productos_con_stock_son_repuestos(self, banco):
        p = banco.armar(banco.orden(), (banco.servicio, 1), (banco.ram, 2))
        assert [(r.producto_id, r.cantidad, r.estado) for r in p.repuestos.all()] == [
            (banco.ram.pk, Decimal("2.000"), EstadoRepuesto.PENDIENTE)
        ]

    def test_rehacerlo_crea_una_version_y_anula_la_anterior(self, banco):
        orden = banco.orden()
        v1 = banco.armar(orden, (banco.ram, 1))
        v2 = banco.armar(orden, (banco.ram, 3))
        v1.refresh_from_db()
        assert (v1.vigente, v2.vigente, v2.version) == (False, True, 2)
        assert Proforma.objects.get(pk=v1.proforma_id).estado == Proforma.Estado.ANULADO
        assert PresupuestoOrden.objects.filter(orden=orden, vigente=True).count() == 1
        assert presupuesto.vigente_de(orden).pk == v2.pk

    def test_sin_lineas(self, banco):
        with pytest.raises(PresupuestoInvalido, match="al menos"):
            presupuesto.armar_presupuesto(banco.orden(), [], vendedor_nombre="Rosa")

    def test_un_repuesto_con_serie_no_se_admite_aun(self, banco):
        con_serie = banco.tienda.producto("Laptop usada", lleva_serie=True, stock={})
        with pytest.raises(PresupuestoInvalido, match="serie"):
            banco.armar(banco.orden(), (con_serie, 1))

    def test_no_se_rehace_una_orden_avanzada(self, banco):
        with pytest.raises(OrdenInvalida, match="avanzada|aprobado"):
            banco.armar(banco.orden(estado=E.EN_REPARACION), (banco.ram, 1))

    def test_el_precio_bajo_el_minimo_necesita_permiso(self, banco):
        linea = [
            LineaPresupuesto(
                producto=banco.ram,
                cantidad=Decimal("1"),
                empresa=banco.empresa,
                precio_unitario=Decimal("1"),
            )
        ]
        with pytest.raises(ErrorDominio):
            presupuesto.armar_presupuesto(banco.orden(), linea, vendedor_nombre="Rosa")

    def test_stock_de_otra_empresa_necesita_permiso(self, banco):
        otro = banco.tienda.producto("Cargador", stock={banco.otra: 5})
        orden = banco.orden()
        with pytest.raises(ErrorDominio):
            banco.armar(orden, (otro, 1, banco.otra), puede_otra_empresa=False)
        assert banco.armar(orden, (otro, 1, banco.otra)).repuestos.get().empresa_id == banco.otra.pk


class TestEnviarYAprobar:
    def test_enviar_a_aprobacion_exige_presupuesto(self, banco):
        orden = banco.orden(
            estado=E.DIAGNOSTICADO, diagnostico="Memoria dañada", trabajos_a_realizar="Cambiar"
        )
        with pytest.raises(PresupuestoRequerido):
            servicios.cambiar_estado(orden, E.PENDIENTE_APROBACION)
        banco.armar(orden, (banco.ram, 1))
        servicios.cambiar_estado(orden, E.PENDIENTE_APROBACION)
        assert orden.estado == E.PENDIENTE_APROBACION

    def test_aprobado_solo_se_alcanza_aprobando_el_presupuesto(self, banco):
        orden = _en_aprobacion(banco, (banco.ram, 1))
        with pytest.raises(TransicionInvalida, match="presupuesto"):
            servicios.cambiar_estado(orden, E.APROBADO, motivo="Aprobó por teléfono")

    def test_aprobar_deja_constancia_y_reserva_los_repuestos(self, banco):
        orden = _en_aprobacion(banco, (banco.servicio, 1), (banco.ram, 2))
        antes = banco.stock(banco.ram, banco.e.alm1)
        p, reserva = presupuesto.aprobar_presupuesto(
            orden, medio="WHATSAPP", nota="Aprobó por WhatsApp"
        )
        orden.refresh_from_db()
        assert orden.estado == E.APROBADO
        assert (p.aprobado, p.aprobacion_medio, p.aprobacion_nota) == (
            True,
            "WHATSAPP",
            "Aprobó por WhatsApp",
        )
        assert p.aprobado_por_id == banco.e.e.usuario_id
        assert reserva.reservados == 1 and reserva.pendientes == []
        repuesto = p.repuestos.get()
        assert repuesto.estado == EstadoRepuesto.RESERVADO
        servicio = repuestos.almacen_servicio(banco.empresa)
        assert servicio.tipo == TipoAlmacen.SERVICIO_TECNICO and servicio.permite_venta is False
        assert banco.stock(banco.ram, banco.e.alm1) == antes - 2  # ya nadie lo puede vender
        assert banco.stock(banco.ram, servicio) == 2
        assert orden.historial.last().motivo.startswith("Aprobó el presupuesto v1")

    def test_el_almacen_de_servicio_se_crea_una_sola_vez(self, banco):
        assert (
            repuestos.almacen_servicio(banco.empresa).pk
            == repuestos.almacen_servicio(banco.empresa).pk
        )

    def test_si_no_alcanza_el_stock_se_aprueba_y_queda_pendiente(self, banco):
        orden = _en_aprobacion(banco, (banco.pantalla, 2))  # hay una sola
        _, reserva = presupuesto.aprobar_presupuesto(
            orden, medio="LLAMADA", nota="Aprobó por llamada"
        )
        orden.refresh_from_db()
        assert orden.estado == E.APROBADO
        assert reserva.reservados == 0
        assert "Pantalla 15.6" in reserva.pendientes[0]
        assert RepuestoOrden.objects.get(producto=banco.pantalla).estado == EstadoRepuesto.PENDIENTE
        assert banco.stock(banco.pantalla, banco.e.alm1) == 1  # nada se movió

    def test_reservar_otra_vez_cuando_llega_el_repuesto(self, banco):
        orden = _en_aprobacion(banco, (banco.pantalla, 2))
        presupuesto.aprobar_presupuesto(orden, medio="LLAMADA", nota="Aprobó por llamada")
        ingresar_stock(
            banco.e, banco.pantalla, 5, "200", empresa=banco.empresa, almacen=banco.e.alm1
        )
        reserva = repuestos.reservar_pendientes(orden)
        assert (reserva.reservados, reserva.pendientes) == (1, [])
        assert RepuestoOrden.objects.get(producto=banco.pantalla).estado == EstadoRepuesto.RESERVADO

    def test_se_puede_repetir_sin_duplicar(self, banco):
        orden = _en_aprobacion(banco, (banco.ram, 1))
        presupuesto.aprobar_presupuesto(orden, medio="OTRO", nota="Aprobó en tienda")
        assert repuestos.reservar_pendientes(orden).reservados == 0
        assert banco.stock(banco.ram, repuestos.almacen_servicio(banco.empresa)) == 1

    def test_valida_estado_medio_y_nota(self, banco):
        orden = banco.orden(estado=E.DIAGNOSTICADO)
        with pytest.raises(TransicionInvalida):
            presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó")
        pendiente = _en_aprobacion(banco, (banco.ram, 1))
        with pytest.raises(OrdenInvalida, match="respondió"):
            presupuesto.aprobar_presupuesto(pendiente, medio="PALOMA", nota="Aprobó")
        with pytest.raises(OrdenInvalida, match="aprobó"):
            presupuesto.aprobar_presupuesto(pendiente, medio="WHATSAPP", nota="  ")

    def test_un_presupuesto_vencido_no_se_aprueba(self, banco):
        orden = _en_aprobacion(banco, (banco.ram, 1))
        ayer = timezone.localdate() - timedelta(days=1)
        with connection.cursor() as cursor:  # los documentos de Ventas no se editan por el ORM
            cursor.execute("UPDATE ventas_proforma SET valida_hasta = %s", [ayer])
        with pytest.raises(PresupuestoInvalido, match="venció"):
            presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó tarde")

    def test_aprobado_ya_no_se_edita(self, banco):
        orden = _en_aprobacion(banco, (banco.ram, 1))
        presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
        with pytest.raises(OrdenInvalida):
            banco.armar(orden, (banco.ram, 5))


class TestStockDelTrabajo:
    def _aprobada(self, banco, *cosas):
        orden = _en_aprobacion(banco, *cosas)
        presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
        return orden

    def test_al_reparar_los_repuestos_salen_del_almacen_de_servicio(self, banco):
        orden = self._aprobada(banco, (banco.ram, 2))
        servicios.cambiar_estado(orden, E.EN_REPARACION)
        servicio = repuestos.almacen_servicio(banco.empresa)
        assert banco.stock(banco.ram, servicio) == 0
        r = RepuestoOrden.objects.get(producto=banco.ram)
        assert r.estado == EstadoRepuesto.CONSUMIDO
        assert r.costo_total == Decimal("100.00")  # 2 × S/ 50 de costo
        mov = MovimientoInventario.objects.get(pk=r.movimiento_consumo_id)
        assert (mov.origen, mov.tipo, mov.referencia_tipo, mov.referencia_id) == (
            OrigenMovimiento.SERVICIO_TECNICO,
            "SALIDA",
            "orden_servicio",
            orden.pk,
        )
        assert LineaMovimiento.objects.get(movimiento=mov).costo_total == Decimal("100.00")

    def test_sin_repuestos_pendientes_no_empieza_el_trabajo(self, banco):
        orden = self._aprobada(banco, (banco.pantalla, 2))
        with pytest.raises(RepuestosPendientes, match="Pantalla 15.6"):
            servicios.cambiar_estado(orden, E.EN_REPARACION)
        orden.refresh_from_db()
        assert orden.estado == E.APROBADO
        servicios.cambiar_estado(orden, E.PENDIENTE_REPUESTO, motivo="Se pidió la pantalla")
        assert orden.estado == E.PENDIENTE_REPUESTO

    def test_un_mantenimiento_tambien_usa_los_repuestos(self, banco):
        orden = self._aprobada(banco, (banco.ram, 1))
        servicios.cambiar_estado(orden, E.EN_MANTENIMIENTO)
        assert RepuestoOrden.objects.get().estado == EstadoRepuesto.CONSUMIDO

    def test_volver_a_reparar_no_descuenta_dos_veces(self, banco):
        orden = self._aprobada(banco, (banco.ram, 1))
        servicios.cambiar_estado(orden, E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.EN_PRUEBAS)
        servicios.cambiar_estado(orden, E.EN_REPARACION, motivo="Falló la prueba")
        assert (
            MovimientoInventario.objects.filter(origen=OrigenMovimiento.SERVICIO_TECNICO).count()
            == 1
        )

    def test_si_el_servicio_no_sigue_el_stock_vuelve_a_su_almacen(self, banco):
        orden = self._aprobada(banco, (banco.ram, 3))
        antes = banco.stock(banco.ram, banco.e.alm1)
        servicios.cambiar_estado(orden, E.NO_APROBADO, motivo="El cliente se arrepintió")
        assert RepuestoOrden.objects.get().estado == EstadoRepuesto.LIBERADO
        assert banco.stock(banco.ram, banco.e.alm1) == antes + 3
        assert banco.stock(banco.ram, repuestos.almacen_servicio(banco.empresa)) == 0

    def test_lo_ya_usado_no_se_devuelve(self, banco):
        orden = self._aprobada(banco, (banco.ram, 1))
        servicios.cambiar_estado(orden, E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.SIN_SOLUCION, motivo="La placa no tiene arreglo")
        assert RepuestoOrden.objects.get().estado == EstadoRepuesto.CONSUMIDO

    def test_repuesto_de_otra_empresa_se_reserva_en_su_propio_stock(self, banco):
        otro = banco.tienda.producto("Cargador", costo="20", stock={banco.otra: 5})
        orden = _en_aprobacion(banco, (otro, 2, banco.otra))
        presupuesto.aprobar_presupuesto(orden, medio="WHATSAPP", nota="Aprobó por WhatsApp")
        servicio_otra = repuestos.almacen_servicio(banco.otra)
        assert servicio_otra.empresa_id == banco.otra.pk
        assert banco.stock(otro, servicio_otra) == 2
        assert banco.stock(otro, banco.e.alm2) == 3


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
BASE = "/api/v1/servicio-tecnico"


def _con_tecnico(banco, orden):
    from apps.seguridad.models import Usuario

    usuario = Usuario.objects.get(username="tecnico")
    personal = Personal.objects.create(
        empresa=banco.empresa,
        tipo_documento="DNI",
        numero_documento="40123456",
        nombres="Mario",
        apellidos="Quispe",
        area="TECNICO",
        usuario=usuario,
    )
    orden.tecnico = personal
    orden.save(update_fields=["tecnico"])


def _cuerpo(banco, *cosas, **extra):
    return {
        "lineas": [{"producto": p.pk, "cantidad": str(c)} for p, c in cosas],
        **extra,
    }


class TestApiPresupuesto:
    def test_recepcion_arma_y_ve_los_precios_el_tecnico_no(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = banco.orden()
        _con_tecnico(banco, orden)
        cuerpo = _cuerpo(banco, (banco.servicio, 1), (banco.ram, 2))
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/presupuesto/", cuerpo, format="json"
        )
        assert r.status_code == 200, r.content
        p = r.json()["presupuesto"]
        assert p["version"] == 1 and p["total"] == "295.00"
        assert p["lineas"][1]["repuesto"]["estado"] == "PENDIENTE"
        assert p["lineas"][1]["precio_unitario"] is not None
        ficha = cliente_de("tecnico").get(f"{BASE}/ordenes/{orden.pk}/").json()
        sin_precios = ficha["presupuesto"]
        assert sin_precios["total"] is None and sin_precios["ve_importes"] is False
        assert all(
            "precio_unitario" not in ln and "total" not in ln for ln in sin_precios["lineas"]
        )
        assert sin_precios["lineas"][1]["descripcion"]

    def test_quien_no_presupuesta_recibe_403(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = banco.orden()
        _con_tecnico(banco, orden)
        cuerpo = _cuerpo(banco, (banco.ram, 1))
        url = f"{BASE}/ordenes/{orden.pk}/presupuesto/"
        assert cliente_de("tecnico").post(url, cuerpo, format="json").status_code == 403
        assert cliente_de("vendedor").post(url, cuerpo, format="json").status_code == 403

    def test_producto_inexistente_o_sin_lineas(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = banco.orden()
        api = cliente_de("admin")
        url = f"{BASE}/ordenes/{orden.pk}/presupuesto/"
        malo = {"lineas": [{"producto": 99999, "cantidad": "1"}]}
        assert api.post(url, malo, format="json").status_code == 400
        assert api.post(url, {"lineas": []}, format="json").status_code == 400

    def test_aprobar_por_la_api_reserva_y_lo_informa(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = _en_aprobacion(banco, (banco.ram, 2), (banco.pantalla, 3))
        _con_tecnico(banco, orden)
        api = cliente_de("admin")
        antes = api.get(f"{BASE}/ordenes/{orden.pk}/").json()
        assert antes["permite"]["aprobar"] is True
        assert "APROBADO" not in {d["estado"] for d in antes["destinos"]}
        r = api.post(
            f"{BASE}/ordenes/{orden.pk}/aprobar/",
            {"medio": "WHATSAPP", "nota": "Aprobó por WhatsApp"},
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["estado"] == "APROBADO"
        assert datos["presupuesto"]["aprobado"] is True
        assert datos["presupuesto"]["aprobacion_medio_nombre"] == "WhatsApp"
        assert datos["reserva"]["reservados"] == 1
        assert "Pantalla 15.6" in datos["reserva"]["pendientes"][0]
        assert datos["presupuesto"]["repuestos_pendientes"] == 1
        assert datos["permite"]["reservar"] is True and datos["permite"]["aprobar"] is False

    def test_el_tecnico_no_aprueba_ni_reserva(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = _en_aprobacion(banco, (banco.ram, 1))
        _con_tecnico(banco, orden)
        api = cliente_de("tecnico")
        cuerpo = {"medio": "WHATSAPP", "nota": "Aprobó por WhatsApp"}
        assert (
            api.post(f"{BASE}/ordenes/{orden.pk}/aprobar/", cuerpo, format="json").status_code
            == 403
        )
        assert (
            api.post(f"{BASE}/ordenes/{orden.pk}/reservar/", {}, format="json").status_code == 403
        )

    def test_aprobar_por_el_cambio_de_estado_se_rechaza(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = _en_aprobacion(banco, (banco.ram, 1))
        r = cliente_de("admin").post(
            f"{BASE}/ordenes/{orden.pk}/estado/",
            {"estado": "APROBADO", "motivo": "Aprobó por teléfono"},
            format="json",
        )
        assert r.status_code == 409

    def test_reservar_desde_la_api(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = _en_aprobacion(banco, (banco.pantalla, 2))
        presupuesto.aprobar_presupuesto(orden, medio="LLAMADA", nota="Aprobó por llamada")
        ingresar_stock(
            banco.e, banco.pantalla, 5, "200", empresa=banco.empresa, almacen=banco.e.alm1
        )
        r = cliente_de("admin").post(f"{BASE}/ordenes/{orden.pk}/reservar/", {}, format="json")
        assert r.status_code == 200, r.content
        assert r.json()["reserva"]["reservados"] == 1
        assert r.json()["presupuesto"]["repuestos_pendientes"] == 0

    def test_reservar_antes_de_aprobar_se_rechaza(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        orden = _en_aprobacion(banco, (banco.ram, 1))
        assert (
            cliente_de("admin")
            .post(f"{BASE}/ordenes/{orden.pk}/reservar/", {}, format="json")
            .status_code
            == 400
        )


class TestApiCatalogo:
    def test_lista_con_precios_y_stock_sin_costos(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        r = cliente_de("admin").get(
            f"{BASE}/catalogo/", {"empresa": banco.empresa.pk, "q": "memoria"}
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        ficha = next(f for f in datos["results"] if f["nombre"] == "Memoria RAM 8GB")
        assert ficha["precios"] and ficha["stock"][0]["cantidad"] == "10.000"
        assert "costo" not in ficha
        assert datos["empresas"]

    def test_solo_para_quien_presupuesta(self, banco):
        from apps.seguridad.tests.conftest import cliente_de

        for usuario in ("tecnico", "vendedor"):
            r = cliente_de(usuario).get(f"{BASE}/catalogo/", {"empresa": banco.empresa.pk})
            assert r.status_code == 403
        assert cliente_de("admin").get(f"{BASE}/catalogo/").status_code == 400
