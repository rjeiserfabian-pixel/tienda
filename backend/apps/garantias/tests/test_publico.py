"""Consulta pública de la garantía (QR o serie + documento) y datos del certificado."""

from decimal import Decimal as D

import pytest
from rest_framework.test import APIClient

from apps.garantias import publico, reclamos
from apps.garantias.models import EstadoGarantia, Garantia
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import LineaNueva, registrar_movimiento
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/garantias"


def _celular_vendido(tienda, serie="IMEI-1"):
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
        lineas=[LineaNueva(p, D("2"), D("500"), series=(serie, "IMEI-2"))],
    )
    tienda.vender(
        [tienda.linea(p, 1, series=(serie,))],
        [tienda.cobro(tienda.efectivo, "944.00")],
        tipo_comprobante="01",
        cliente=tienda.cliente(),
    )
    return Garantia.objects.sin_ambito().get(numero_serie=serie)


class TestToken:
    def test_cada_garantia_tiene_su_propio_codigo(self, tienda):
        g = _celular_vendido(tienda)
        assert len(g.token_publico) >= 12
        otra = Garantia.objects.sin_ambito().exclude(pk=g.pk).first()
        assert otra is None or otra.token_publico != g.token_publico


class TestEstadoPublico:
    def test_con_el_codigo_se_ve_lo_que_corresponde_y_nada_privado(self, tienda):
        g = _celular_vendido(tienda)
        r = APIClient().get(f"{BASE}/publico/{g.token_publico}/")
        assert r.status_code == 200, r.content
        assert r["Cache-Control"] == "no-store" and "noindex" in r["X-Robots-Tag"]
        d = r.json()
        assert d["producto"]["numero_serie"] == "IMEI-1"
        assert d["garantia"]["situacion"] == "VIGENTE" and d["garantia"]["meses"] == 12
        assert d["reclamo"] is None
        cuerpo = r.content.decode()
        # Nada del cliente ni de los importes.
        assert "Ferretería El Sol" not in cuerpo and "20100000017" not in cuerpo
        assert "944" not in cuerpo and "costo" not in cuerpo

    def test_un_codigo_que_no_existe_o_mal_formado_da_404(self, tienda):
        _celular_vendido(tienda)
        assert APIClient().get(f"{BASE}/publico/NoExisteElCodigo1/").status_code == 404
        assert APIClient().get(f"{BASE}/publico/a/").status_code == 404

    def test_muestra_el_reclamo_en_curso(self, tienda):
        g = _celular_vendido(tienda)
        reclamos.abrir(garantia_id=g.pk, descripcion="No enciende la pantalla")
        d = APIClient().get(f"{BASE}/publico/{g.token_publico}/").json()
        assert d["reclamo"]["numero"] == "RG-000001" and d["reclamo"]["estado"] == "ABIERTO"

    def test_una_garantia_anulada_lo_dice(self, tienda):
        g = _celular_vendido(tienda)
        Garantia.objects.sin_ambito().filter(pk=g.pk).update(estado=EstadoGarantia.ANULADA)
        d = APIClient().get(f"{BASE}/publico/{g.token_publico}/").json()
        assert d["garantia"]["situacion"] == "ANULADA" and not d["garantia"]["vigente"]


class TestBuscarPorSerie:
    def _buscar(self, serie, documento):
        return APIClient().post(
            f"{BASE}/publico/buscar/", {"serie": serie, "documento": documento}, format="json"
        )

    def test_serie_y_documento_correctos_devuelven_el_codigo(self, tienda):
        g = _celular_vendido(tienda)
        r = self._buscar(" imei-1 ", "20100000017")
        assert r.status_code == 200, r.content
        assert r.json() == {"token": g.token_publico}

    def test_hay_que_acertar_las_dos_cosas(self, tienda):
        _celular_vendido(tienda)
        assert self._buscar("IMEI-1", "20999999999").status_code == 404
        assert self._buscar("IMEI-9", "20100000017").status_code == 404
        assert self._buscar("IMEI-1", "12").status_code == 404  # documento demasiado corto

    def test_el_mensaje_no_distingue_serie_de_documento(self, tienda):
        _celular_vendido(tienda)
        a = self._buscar("IMEI-1", "20999999999").json()["error"]
        b = self._buscar("IMEI-9", "20100000017").json()["error"]
        assert (a["codigo"], a["mensaje"]) == (b["codigo"], b["mensaje"])

    def test_tambien_responde_por_la_ruta_de_la_tienda_con_o_sin_barra(self, tienda):
        g = _celular_vendido(tienda)
        cuerpo = {"serie": "IMEI-1", "documento": "20100000017"}
        for ruta in ("/api/v1/tienda/garantia/buscar", "/api/v1/tienda/garantia/buscar/"):
            r = APIClient().post(ruta, cuerpo, format="json")
            assert r.status_code == 200, (ruta, r.content)
            assert r.json() == {"token": g.token_publico}

    def test_faltan_datos(self, tienda):
        assert self._buscar("", "").status_code == 400


class TestCertificado:
    def test_trae_emisor_cliente_condiciones_y_el_enlace_del_qr(self, tienda):
        g = _celular_vendido(tienda)
        r = cliente_de("vendedor").get(f"{BASE}/{g.pk}/certificado/")
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["emisor"]["ruc"] and d["emisor"]["nombre"]
        assert d["cliente_documento"] == "20100000017"
        assert d["numero_serie"] == "IMEI-1" and d["vence_el"] == g.vence_el.isoformat()
        assert d["url_publica"].endswith(f"/garantia/{g.token_publico}")
        assert d["condiciones"] == list(publico.CONDICIONES)

    def test_exige_sesion(self, tienda):
        g = _celular_vendido(tienda)
        assert APIClient().get(f"{BASE}/{g.pk}/certificado/").status_code in (401, 403)
