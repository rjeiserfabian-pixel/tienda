"""Series con «otros datos»: se guardan al entrar, viajan en traspasos y se corrigen."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.inventario.models import SerieProducto
from apps.mantenimiento.models import Almacen
from apps.seguridad.tests.conftest import cliente_de

from .ayudas_api import BASE, clave, cuerpo, registrar

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def celular(mundo):
    return mundo.producto("Celular X", lleva_serie=True)


@pytest.fixture
def alm_b(mundo):
    return Almacen.objects.sin_ambito().create(
        empresa=mundo.e1, sucursal=mundo.alm[1].sucursal, codigo="ALM2", nombre="Almacén 2"
    )


def _entrada(mundo, producto, series, usuario="super"):
    datos = cuerpo(mundo, producto, cantidad=str(len(series)), precio="500")
    datos["lineas"][0]["series"] = series
    return registrar(cliente_de(usuario), datos)


def _serie(numero):
    return SerieProducto.objects.sin_ambito().get(numero=numero)


def _traspaso(mundo, origen, destino, producto, series):
    return cliente_de("super").post(
        f"{BASE}/movimientos/traspaso/",
        {
            "empresa": mundo.e1.pk,
            "almacen_origen": origen.pk,
            "almacen_destino": destino.pk,
            "fecha": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "lineas": [{"producto": producto.pk, "cantidad": str(len(series)), "series": series}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=clave(),
    )


class TestRegistro:
    def test_la_serie_guarda_sus_otros_datos(self, mundo, celular):
        r = _entrada(
            mundo, celular, [{"numero": "imei111", "otros_datos": "  Negro,   128 GB "}, "imei222"]
        )
        assert r.status_code == 201, r.content
        assert _serie("IMEI111").otros_datos == "Negro, 128 GB"
        assert _serie("IMEI222").otros_datos == ""

    def test_el_detalle_del_movimiento_trae_los_otros_datos(self, mundo, celular):
        r = _entrada(
            mundo,
            celular,
            [
                {"numero": "imei111", "otros_datos": "Negro"},
                {"numero": "imei222", "otros_datos": "Blanco"},
            ],
        )
        linea = r.json()["lineas"][0]
        assert linea["series"] == ["IMEI111", "IMEI222"]  # el formato de antes sigue igual
        assert linea["series_detalle"] == [
            {"numero": "IMEI111", "otros_datos": "Negro"},
            {"numero": "IMEI222", "otros_datos": "Blanco"},
        ]

    def test_se_pueden_mezclar_textos_y_objetos(self, mundo, celular):
        assert (
            _entrada(
                mundo, celular, ["imei111", {"numero": "imei222", "otros_datos": "Rojo"}]
            ).status_code
            == 201
        )

    @pytest.mark.parametrize(
        "mala",
        [
            [{"numero": "imei111", "otros_datos": "x" * 121}],
            [{"otros_datos": "sin número"}],
            [{"numero": ""}],
            [{"numero": "imei111", "otros_datos": 5}],
            [123],
            [{"numero": "i" * 41}],
        ],
    )
    def test_series_mal_formadas(self, mundo, celular, mala):
        assert _entrada(mundo, celular, mala).status_code == 400

    def test_otros_datos_para_un_producto_sin_serie_se_rechazan(self, mundo):
        normal = mundo.producto("Mouse")
        assert (
            _entrada(mundo, normal, [{"numero": "abc123", "otros_datos": "x"}]).status_code == 400
        )


class TestTraspasosYAnulaciones:
    def test_los_otros_datos_viajan_con_la_serie_al_traspasar(self, mundo, celular, alm_b):
        _entrada(mundo, celular, [{"numero": "imei111", "otros_datos": "Garantía hasta 2027"}])
        r = _traspaso(mundo, mundo.alm[1], alm_b, celular, ["imei111"])
        assert r.status_code == 201, r.content
        # La serie ahora está en el otro almacén y conserva su dato.
        en_destino = SerieProducto.objects.sin_ambito().get(numero="IMEI111", estado="EN_STOCK")
        assert (en_destino.almacen_id, en_destino.otros_datos) == (alm_b.pk, "Garantía hasta 2027")

    def test_al_anular_la_salida_la_unidad_vuelve_con_sus_datos(self, mundo, celular):
        from apps.inventario.models import MovimientoInventario

        _entrada(mundo, celular, [{"numero": "imei111", "otros_datos": "Caja abierta"}])
        salida = cuerpo(mundo, celular, cantidad="1", tipo="SALIDA", origen="MERMA")
        salida["lineas"][0].pop("precio_unitario")
        salida["lineas"][0]["series"] = ["imei111"]
        r = registrar(cliente_de("super"), salida)
        assert r.status_code == 201, r.content
        movimiento = MovimientoInventario.objects.sin_ambito().get(pk=r.json()["id"])
        anulada = cliente_de("super").post(
            f"{BASE}/movimientos/{movimiento.pk}/anular/",
            {"motivo": "Error de digitación"},
            format="json",
        )
        assert anulada.status_code in (200, 201), anulada.content
        vigente = SerieProducto.objects.sin_ambito().get(numero="IMEI111", estado="EN_STOCK")
        assert vigente.otros_datos == "Caja abierta"


class TestCorreccion:
    def _serie_con_datos(self, mundo, celular):
        _entrada(mundo, celular, [{"numero": "imei111", "otros_datos": "Negro"}])
        return _serie("IMEI111")

    def _patch(self, mundo, serie, datos, usuario="super"):
        return cliente_de(usuario).patch(
            f"{BASE}/series/{serie.pk}/",
            datos,
            format="json",
            QUERY_STRING=f"empresa={mundo.e1.pk}",
        )

    def test_corrige_los_otros_datos_y_deja_rastro(self, mundo, celular):
        from apps.auditoria.models import AuditoriaEvento

        serie = self._serie_con_datos(mundo, celular)
        r = self._patch(mundo, serie, {"otros_datos": "  Negro, con funda "})
        assert r.status_code == 200, r.content
        assert r.json()["otros_datos"] == "Negro, con funda"
        evento = AuditoriaEvento.objects.get(accion="serie.datos_corregidos")
        assert evento.detalle["otros_datos"] == ["Negro", "Negro, con funda"]

    def test_se_puede_dejar_vacio(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        assert self._patch(mundo, serie, {"otros_datos": ""}).json()["otros_datos"] == ""

    def test_sin_cambios_no_deja_rastro(self, mundo, celular):
        from apps.auditoria.models import AuditoriaEvento

        serie = self._serie_con_datos(mundo, celular)
        self._patch(mundo, serie, {"otros_datos": "Negro"})
        assert not AuditoriaEvento.objects.filter(accion="serie.datos_corregidos").exists()

    def test_el_numero_no_se_edita(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        self._patch(mundo, serie, {"otros_datos": "x", "numero": "OTRO999"})
        serie.refresh_from_db()
        assert serie.numero == "IMEI111"

    def test_datos_demasiado_largos(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        assert self._patch(mundo, serie, {"otros_datos": "x" * 121}).status_code == 400

    def test_quien_solo_ve_inventario_no_corrige(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        assert (
            self._patch(mundo, serie, {"otros_datos": "x"}, usuario="vendedor").status_code == 403
        )
        assert (
            self._patch(mundo, serie, {"otros_datos": "x"}, usuario="contador").status_code == 403
        )

    def test_el_almacenero_si_corrige(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        assert (
            self._patch(mundo, serie, {"otros_datos": "Revisado"}, usuario="almacenero").status_code
            == 200
        )

    def test_otra_organizacion_no_la_toca(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        r = cliente_de("otra_org").patch(
            f"{BASE}/series/{serie.pk}/",
            {"otros_datos": "x"},
            format="json",
            QUERY_STRING=f"empresa={mundo.e1.pk}",
        )
        assert r.status_code in (403, 404)
        serie.refresh_from_db()
        assert serie.otros_datos == "Negro"

    def test_no_se_borra_ni_se_reemplaza(self, mundo, celular):
        serie = self._serie_con_datos(mundo, celular)
        api = cliente_de("super")
        url = f"{BASE}/series/{serie.pk}/?empresa={mundo.e1.pk}"
        assert api.delete(url).status_code in (403, 405)
        assert api.put(url, {"otros_datos": "x"}, format="json").status_code in (403, 405)
        assert SerieProducto.objects.sin_ambito().filter(pk=serie.pk).exists()
        serie.refresh_from_db()
        assert serie.otros_datos == "Negro"


class TestBusqueda:
    def test_la_busqueda_encuentra_por_los_otros_datos(self, mundo, celular):
        _entrada(
            mundo,
            celular,
            [
                {"numero": "imei111", "otros_datos": "Negro 128 GB"},
                {"numero": "imei222", "otros_datos": "Blanco"},
            ],
        )
        api = cliente_de("super")

        def buscar(q):
            r = api.get(f"{BASE}/series/", {"empresa": mundo.e1.pk, "q": q})
            return sorted(s["numero"] for s in r.json()["results"])

        assert buscar("negro") == ["IMEI111"]
        assert buscar("BLANCO") == ["IMEI222"]
        assert buscar("imei") == ["IMEI111", "IMEI222"]  # el número sigue funcionando
        assert buscar("128") == ["IMEI111"]

    def test_el_listado_trae_los_otros_datos(self, mundo, celular):
        _entrada(mundo, celular, [{"numero": "imei111", "otros_datos": "Negro"}])
        fila = (
            cliente_de("super")
            .get(f"{BASE}/series/", {"empresa": mundo.e1.pk})
            .json()["results"][0]
        )
        assert fila["otros_datos"] == "Negro"
