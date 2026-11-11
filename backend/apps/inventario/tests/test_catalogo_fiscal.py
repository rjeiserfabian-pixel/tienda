"""Los movimientos usan los tipos de comprobante y la tasa del IGV del catálogo fiscal."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.inventario.tests.ayudas_api import cuerpo, registrar
from apps.mantenimiento.models import TasaImpuesto, TipoComprobante
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

MANT = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def producto(mundo):
    return mundo.producto("Mouse")


def _compra(mundo, producto, **extra):
    return registrar(cliente_de("super"), cuerpo(mundo, producto, **extra))


class TestTipoDeComprobante:
    def test_acepta_un_tipo_del_catalogo(self, mundo, producto):
        r = _compra(
            mundo,
            producto,
            comprobante_tipo="01",
            comprobante_serie="F001",
            comprobante_numero="1245",
        )
        assert r.status_code == 201, r.content

    def test_rechaza_un_tipo_que_no_existe(self, mundo, producto):
        r = _compra(mundo, producto, comprobante_tipo="99", comprobante_numero="1")
        assert r.status_code == 400
        assert "comprobante" in str(r.json()).lower()

    def test_rechaza_un_tipo_desactivado_y_acepta_uno_nuevo(self, mundo, producto):
        TipoComprobante.objects.sin_ambito().filter(organizacion=mundo.e.org_a, codigo="03").update(
            estado="INACTIVO"
        )
        assert (
            _compra(mundo, producto, comprobante_tipo="03", comprobante_numero="1").status_code
            == 400
        )
        api = cliente_de("super")
        nuevo = api.post(
            f"{MANT}/tipos-comprobante/",
            {"codigo": "05", "nombre": "Boleto de viaje", "abreviatura": "BVA"},
            format="json",
        )
        assert nuevo.status_code == 201
        assert (
            _compra(mundo, producto, comprobante_tipo="05", comprobante_numero="7").status_code
            == 201
        )

    def test_cada_organizacion_usa_su_catalogo(self, mundo, producto):
        # El tipo de la organización A no vale si la B lo desactivó: son catálogos separados.
        TipoComprobante.objects.sin_ambito().filter(organizacion=mundo.e.org_b, codigo="01").update(
            estado="INACTIVO"
        )
        r = _compra(
            mundo, producto, comprobante_tipo="01", comprobante_serie="F001", comprobante_numero="1"
        )
        assert r.status_code == 201

    @pytest.mark.parametrize(
        ("serie", "numero", "mensaje"),
        [
            ("B001", "1", "formato"),  # serie de boleta en una factura
            ("X999", "1", "formato"),
            ("F001", "123456789", "8 dígitos"),
            ("F001", "12A", "8 dígitos"),
        ],
    )
    def test_valida_la_serie_y_el_numero_de_un_comprobante_electronico(
        self, mundo, producto, serie, numero, mensaje
    ):
        r = _compra(
            mundo,
            producto,
            comprobante_tipo="01",
            comprobante_serie=serie,
            comprobante_numero=numero,
        )
        assert r.status_code == 400
        assert mensaje in str(r.json())

    def test_sin_comprobante_no_se_exige_nada(self, mundo, producto):
        assert _compra(mundo, producto).status_code == 201

    def test_un_tipo_usado_no_se_elimina(self, mundo, producto):
        api = cliente_de("super")
        assert (
            _compra(
                mundo,
                producto,
                comprobante_tipo="01",
                comprobante_serie="F001",
                comprobante_numero="1",
            ).status_code
            == 201
        )
        factura = api.get(f"{MANT}/tipos-comprobante/", {"q": "Factura"}).json()["results"][0]
        r = api.delete(f"{MANT}/tipos-comprobante/{factura['id']}/")
        assert r.status_code == 409
        assert TipoComprobante.objects.sin_ambito().filter(pk=factura["id"]).exists()
        # Se puede desactivar para que no se siga usando.
        assert (
            api.patch(
                f"{MANT}/tipos-comprobante/{factura['id']}/", {"estado": "INACTIVO"}, format="json"
            ).status_code
            == 200
        )


class TestTasaDelIgv:
    def _movimiento(self, mundo, producto, dias_atras):
        datos = cuerpo(
            mundo,
            producto,
            comprobante_tipo="01",
            comprobante_serie="F001",
            comprobante_numero=str(dias_atras),
        )
        datos["fecha"] = (timezone.localdate() - timedelta(days=dias_atras)).isoformat()
        r = registrar(cliente_de("super"), datos)
        assert r.status_code == 201, r.content
        return r.json()

    def test_usa_la_tasa_de_la_organizacion(self, mundo, producto):
        assert Decimal(self._movimiento(mundo, producto, 2)["igv_porcentaje"]) == Decimal("18")

    def test_cada_movimiento_toma_la_tasa_vigente_en_su_fecha(self, mundo, producto):
        TasaImpuesto.objects.sin_ambito().create(
            organizacion=mundo.e.org_a,
            impuesto="IGV",
            porcentaje=Decimal("19"),
            vigente_desde=timezone.localdate() - timedelta(days=5),
        )
        antes = self._movimiento(mundo, producto, 8)  # anterior al cambio
        despues = self._movimiento(mundo, producto, 2)  # ya con la tasa nueva
        assert (Decimal(antes["igv_porcentaje"]), Decimal(despues["igv_porcentaje"])) == (
            Decimal("18"),
            Decimal("19"),
        )

    def test_si_no_hay_tasa_se_explica_en_vez_de_inventar_una(self, mundo, producto):
        TasaImpuesto.objects.sin_ambito().filter(organizacion=mundo.e.org_a).delete()
        r = _compra(
            mundo, producto, comprobante_tipo="01", comprobante_serie="F001", comprobante_numero="1"
        )
        assert r.status_code == 422
        assert "tasa" in str(r.json()).lower()

    def test_los_movimientos_internos_no_llevan_igv(self, mundo, producto):
        datos = cuerpo(mundo, producto, origen="SALDO_INICIAL")
        r = registrar(cliente_de("super"), datos)
        assert r.status_code == 201, r.content
        assert Decimal(r.json()["igv_porcentaje"]) == 0

    def test_el_porcentaje_indicado_a_mano_sigue_mandando(self, mundo, producto):
        datos = cuerpo(
            mundo, producto, comprobante_tipo="01", comprobante_serie="F001", comprobante_numero="3"
        )
        datos["igv_porcentaje"] = "10"
        r = registrar(cliente_de("super"), datos)
        assert Decimal(r.json()["igv_porcentaje"]) == 10
        assert r.status_code == 201


class TestEditarTasaConDocumentos:
    def _compra(self, mundo, producto):
        r = _compra(
            mundo, producto, comprobante_tipo="01", comprobante_serie="F001", comprobante_numero="1"
        )
        assert r.status_code == 201, r.content

    def _tasa_vigente(self, api):
        return api.get(f"{MANT}/tasas-impuesto/", {"impuesto": "IGV"}).json()["results"][0]

    def test_no_se_edita_una_tasa_que_ya_uso_un_documento(self, mundo, producto):
        api = cliente_de("super")
        self._compra(mundo, producto)
        fila = self._tasa_vigente(api)
        r = api.patch(f"{MANT}/tasas-impuesto/{fila['id']}/", {"porcentaje": "19"}, format="json")
        assert r.status_code == 409
        assert "tasa nueva" in str(r.json())
        assert Decimal(self._tasa_vigente(api)["porcentaje"]) == 18

    def test_tampoco_se_cambia_su_fecha(self, mundo, producto):
        api = cliente_de("super")
        self._compra(mundo, producto)
        fila = self._tasa_vigente(api)
        r = api.patch(
            f"{MANT}/tasas-impuesto/{fila['id']}/", {"vigente_desde": "2012-01-01"}, format="json"
        )
        assert r.status_code == 409

    def test_la_salida_correcta_es_agregar_una_tasa_nueva(self, mundo, producto):
        api = cliente_de("super")
        self._compra(mundo, producto)
        hoy = timezone.localdate()
        r = api.post(
            f"{MANT}/tasas-impuesto/",
            {
                "impuesto": "IGV",
                "porcentaje": "19",
                "vigente_desde": (hoy + timedelta(days=10)).isoformat(),
            },
            format="json",
        )
        assert r.status_code == 201
        # La nueva todavía no la usa nadie: se puede ajustar; la anterior sigue protegida.
        assert (
            api.patch(
                f"{MANT}/tasas-impuesto/{r.json()['id']}/", {"porcentaje": "20"}, format="json"
            ).status_code
            == 200
        )
        antigua = next(
            t
            for t in api.get(f"{MANT}/tasas-impuesto/", {"impuesto": "IGV"}).json()["results"]
            if t["situacion"] != "FUTURA"
        )
        assert (
            api.patch(
                f"{MANT}/tasas-impuesto/{antigua['id']}/", {"porcentaje": "5"}, format="json"
            ).status_code
            == 409
        )

    def test_los_documentos_de_otra_organizacion_no_bloquean(self, mundo, producto):
        self._compra(mundo, producto)
        otra = cliente_de("otra_org")
        fila = otra.get(f"{MANT}/tasas-impuesto/", {"impuesto": "IGV"}).json()["results"][0]
        r = otra.patch(f"{MANT}/tasas-impuesto/{fila['id']}/", {"porcentaje": "19"}, format="json")
        assert r.status_code == 200
