"""Avisos de garantía por vencer, baja del correo y reportes de garantías."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.core import mail

from apps.garantias import avisos, reclamos
from apps.garantias.models import (
    AvisoGarantia,
    ConfiguracionGarantias,
    EstadoAviso,
    Garantia,
)
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/garantias"


def _vender(tienda, producto, cantidad=1, correo="cliente@ejemplo.pe", numero="20100000017"):
    cli = tienda.cliente(numero=numero, correo=correo)
    tienda.vender(
        [tienda.linea(producto, cantidad)],
        [tienda.cobro(tienda.efectivo, f"{118 * cantidad}.00")],
        tipo_comprobante="01",
        cliente=cli,
    )
    return cli


def _por_vencer(garantia, dias):
    Garantia.objects.sin_ambito().filter(pk=garantia.pk).update(
        vence_el=garantia.fecha_inicio + timedelta(days=dias)
    )


def _activar(tienda, dias=30):
    return ConfiguracionGarantias.objects.sin_ambito().create(
        organizacion_id=tienda.entorno.e.org_a.pk, avisos_activos=True, dias_antes=dias
    )


class TestAvisos:
    def test_apagados_no_escriben_a_nadie(self, tienda):
        _vender(tienda, tienda.producto(garantia_meses=12))
        g = Garantia.objects.sin_ambito().get()
        _por_vencer(g, 10)
        assert avisos.avisar_todas() == 0
        assert mail.outbox == []

    def test_avisa_una_sola_vez_con_serie_y_enlace_de_baja(self, tienda):
        _activar(tienda)
        _vender(tienda, tienda.producto(garantia_meses=12))
        g = Garantia.objects.sin_ambito().get()
        _por_vencer(g, 10)
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 1
        (correo,) = mail.outbox
        assert correo.to == ["cliente@ejemplo.pe"]
        assert "/garantia/baja?t=" in correo.body and f"/garantia/{g.token_publico}" in correo.body
        assert AvisoGarantia.objects.sin_ambito().get().estado == EstadoAviso.ENVIADO
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 0  # no se repite
        assert len(mail.outbox) == 1

    def test_lo_que_vence_lejos_o_ya_no_esta_activo_no_se_avisa(self, tienda):
        _activar(tienda, dias=30)
        _vender(tienda, tienda.producto(garantia_meses=12))
        g = Garantia.objects.sin_ambito().get()
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 0  # vence en un año
        _por_vencer(g, 60)
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 0  # vence en 60 días: aún lejos
        _por_vencer(g, 10)
        Garantia.objects.sin_ambito().filter(pk=g.pk).update(estado="ANULADA")
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 0

    def test_un_solo_correo_por_cliente_aunque_tenga_varias(self, tienda):
        _activar(tienda)
        cli = _vender(tienda, tienda.producto("Mouse", garantia_meses=12))
        tienda.vender(
            [tienda.linea(tienda.producto("Teclado", garantia_meses=12), 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            tipo_comprobante="01",
            cliente=cli,
        )
        for g in Garantia.objects.sin_ambito().all():
            _por_vencer(g, 10)
        hoy = Garantia.objects.sin_ambito().first().fecha_inicio
        assert avisos.avisar_todas(hoy=hoy) == 1
        assert len(mail.outbox) == 1
        assert "Mouse" in mail.outbox[0].body and "Teclado" in mail.outbox[0].body

    def test_sin_correo_no_se_escribe(self, tienda):
        _activar(tienda)
        _vender(tienda, tienda.producto(garantia_meses=12), correo="")
        g = Garantia.objects.sin_ambito().get()
        _por_vencer(g, 10)
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 0
        aviso = AvisoGarantia.objects.sin_ambito().get()
        assert aviso.estado == EstadoAviso.OMITIDO and "correo" in aviso.detalle

    def test_quien_se_dio_de_baja_no_recibe_mas(self, tienda):
        _activar(tienda)
        _vender(tienda, tienda.producto(garantia_meses=12))
        g = Garantia.objects.sin_ambito().get()
        _por_vencer(g, 10)
        org = tienda.entorno.e.org_a.pk
        assert avisos.dar_de_baja(avisos.token_de_baja(org, " Cliente@Ejemplo.pe "))
        assert avisos.dar_de_baja(avisos.token_de_baja(org, "cliente@ejemplo.pe"))  # repetido
        assert avisos.avisar_todas(hoy=g.fecha_inicio) == 0
        assert mail.outbox == []
        assert AvisoGarantia.objects.sin_ambito().get().estado == EstadoAviso.OMITIDO

    def test_un_enlace_de_baja_falso_se_rechaza(self, tienda):
        with pytest.raises(avisos.EnlaceInvalido):
            avisos.dar_de_baja("esto-no-es-un-token")


class TestApiAvisos:
    def test_el_administrador_activa_y_el_vendedor_solo_mira(self, tienda):
        r = cliente_de("vendedor").get(f"{BASE}/configuracion/", {"empresa": tienda.a.pk})
        assert r.status_code == 200, r.content
        assert r.json()["avisos_activos"] is False and r.json()["dias_antes"] == 30
        r = cliente_de("vendedor").patch(
            f"{BASE}/configuracion/", {"avisos_activos": True}, format="json"
        )
        assert r.status_code == 403
        r = cliente_de("admin").patch(
            f"{BASE}/configuracion/", {"avisos_activos": True, "dias_antes": 15}, format="json"
        )
        assert r.status_code == 200, r.content
        assert (r.json()["avisos_activos"], r.json()["dias_antes"]) == (True, 15)

    def test_los_dias_tienen_limite(self, tienda):
        r = cliente_de("admin").patch(f"{BASE}/configuracion/", {"dias_antes": 400}, format="json")
        assert r.status_code == 400

    def test_la_baja_por_la_ruta_publica_de_la_tienda(self, tienda):
        from rest_framework.test import APIClient

        token = avisos.token_de_baja(tienda.entorno.e.org_a.pk, "cliente@ejemplo.pe")
        for ruta in (f"{BASE}/publico/baja/", "/api/v1/tienda/garantia/baja"):
            r = APIClient().post(ruta, {"token": token}, format="json")
            assert r.status_code == 200, (ruta, r.content)
        assert (
            APIClient().post(f"{BASE}/publico/baja/", {"token": "falso"}, format="json").status_code
            == 400
        )


class TestReportes:
    def test_resume_situacion_falla_por_marca_y_reclamos(self, tienda):
        p = tienda.producto("Audífonos", garantia_meses=12, stock={tienda.a: 20})
        _vender(tienda, p, 3)
        g = Garantia.objects.sin_ambito().get()
        r = reclamos.abrir(garantia_id=g.pk, descripcion="Suenan mal", cantidad=1)
        reclamos.resolver(r.pk, resolucion="REPARADO")
        d = cliente_de("vendedor").get(f"{BASE}/reportes/", {"empresa": tienda.a.pk}).json()
        assert d["situacion"]["vigentes"] == 1 and d["vendidas"] == 3
        assert d["reclamos"]["total"] == 1 and d["reclamos"]["abiertos"] == 0
        assert d["reclamos"]["por_resolucion"] == {"REPARADO": 1}
        (marca,) = d["por_marca"]
        assert (marca["vendidas"], marca["reclamadas"], marca["tasa"]) == (3, 1, 33.3)
        assert d["por_producto"][0]["producto"] == "Audífonos"
        assert d["reclamos"]["dias_promedio"] == 0.0

    def test_el_costo_de_los_cambios_solo_lo_ve_quien_puede_ver_costos(self, tienda):
        p = tienda.producto(
            "Celular",
            costo="500",
            precios={"PUBLICO": "800"},
            stock={},
            lleva_serie=True,
            garantia_meses=12,
        )
        registrar_movimiento(
            empresa=tienda.a,
            almacen=tienda.almacen(tienda.a),
            tipo=TipoMovimiento.ENTRADA,
            origen="COMPRA",
            fecha=tienda.entorno.hoy,
            lineas=[LineaNueva(p, D("2"), D("500"), series=("IMEI-1", "IMEI-2"))],
        )
        cli = tienda.cliente(correo="c@x.pe")
        tienda.vender(
            [tienda.linea(p, 1, series=("IMEI-1",))],
            [tienda.cobro(tienda.efectivo, "944.00")],
            tipo_comprobante="01",
            cliente=cli,
        )
        g = Garantia.objects.sin_ambito().get(numero_serie="IMEI-1")
        r = reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        reclamos.resolver(
            r.pk,
            resolucion="CAMBIADO",
            detalle="Cambio",
            cambio=reclamos.Cambio(almacen_id=tienda.almacen(tienda.a).pk, series=("IMEI-2",)),
        )
        admin = cliente_de("admin").get(f"{BASE}/reportes/", {"empresa": tienda.a.pk}).json()
        vendedor = cliente_de("vendedor").get(f"{BASE}/reportes/", {"empresa": tienda.a.pk}).json()
        assert admin["cambios"] == {"cantidad": 1, "costo": "500.00"}
        assert vendedor["cambios"] == {"cantidad": 1, "costo": None}

    def test_pide_empresa_y_periodo_valido(self, tienda):
        assert cliente_de("vendedor").get(f"{BASE}/reportes/").status_code == 400
        r = cliente_de("vendedor").get(
            f"{BASE}/reportes/",
            {"empresa": tienda.a.pk, "desde": "2026-12-01", "hasta": "2026-01-01"},
        )
        assert r.status_code == 400
