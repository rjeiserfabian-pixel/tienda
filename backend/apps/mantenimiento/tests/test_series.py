"""Series de comprobantes de venta: alta, reglas de formato, numeración y su edición."""

import pytest

from apps.auditoria import servicios
from apps.mantenimiento import series
from apps.mantenimiento.exceptions import SerieAgotada, SerieInactiva, SerieNoDisponible
from apps.mantenimiento.models import SerieComprobante, TipoComprobante
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", e.emp_a1)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", e.emp_a1)]),
        "almacenero": nuevo_usuario(e.org_a, "almacenero", [e.emp_a1], [("ALMACENERO", e.emp_a1)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
        "suc": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre="Tienda centro", codigo="002"
        ),
        "suc2": Sucursal.objects.sin_ambito().create(
            empresa=e.emp_a2, nombre="Sucursal B", codigo="001"
        ),
    }


def _tipo(equipo, codigo):
    return TipoComprobante.objects.sin_ambito().get(organizacion=equipo["e"].org_a, codigo=codigo)


def _crear(api, equipo, *, tipo="01", serie="F001", empresa=1, **extra):
    emp = equipo["e"].emp_a1 if empresa == 1 else equipo["e"].emp_a2
    return api.post(
        f"{BASE}/series-comprobante/",
        {"empresa": emp.pk, "tipo_comprobante": _tipo(equipo, tipo).pk, "serie": serie, **extra},
        format="json",
    )


def _ok(respuesta):
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()


# ---------------------------------------------------------------------------
# Alta y formato
# ---------------------------------------------------------------------------
class TestAlta:
    def test_cada_empresa_tiene_sus_series(self, equipo):
        api = cliente_de("super")
        a = _ok(_crear(api, equipo, tipo="01", serie="F001", empresa=1))
        _ok(_crear(api, equipo, tipo="03", serie="B001", empresa=1))
        b = _ok(_crear(api, equipo, tipo="01", serie="F002", empresa=2))
        assert (a["serie"], a["ultimo_numero"], a["proximo"], a["usada"]) == (
            "F001",
            0,
            "F001-00000001",
            False,
        )
        assert b["empresa"] != a["empresa"]
        e = equipo["e"]
        lista = api.get(f"{BASE}/series-comprobante/", {"empresa": e.emp_a1.pk}).json()["results"]
        assert [s["serie"] for s in lista] == [
            "F001",
            "B001",
        ]  # por tipo: factura (01), boleta (03)

    def test_dos_empresas_pueden_usar_la_misma_serie(self, equipo):
        api = cliente_de("super")
        _ok(_crear(api, equipo, serie="F001", empresa=1))
        _ok(_crear(api, equipo, serie="F001", empresa=2))  # cada RUC numera por separado

    def test_varios_puntos_de_venta_de_la_misma_empresa(self, equipo):
        api = cliente_de("super")
        principal = _ok(_crear(api, equipo, serie="F001", nombre="Tienda principal"))
        centro = _ok(
            _crear(api, equipo, serie="F003", nombre="Tienda centro", sucursal=equipo["suc"].pk)
        )
        assert principal["sucursal"] is None
        assert (centro["sucursal"], centro["sucursal_nombre"]) == (
            equipo["suc"].pk,
            "Tienda centro",
        )

    def test_normaliza_la_serie(self, equipo):
        assert _ok(_crear(cliente_de("super"), equipo, serie=" f 001 "))["serie"] == "F001"

    @pytest.mark.parametrize(
        ("tipo", "serie"),
        [
            ("03", "F001"),  # una boleta no usa serie de factura
            ("01", "B001"),  # ni una factura la de boleta
            ("01", "0001"),  # una serie electrónica no es solo números
            ("01", "F0001"),  # demasiado larga
            ("01", "F1"),  # demasiado corta
            ("01", "F#01"),
        ],
    )
    def test_rechaza_series_con_formato_incorrecto(self, equipo, tipo, serie):
        r = _crear(cliente_de("super"), equipo, tipo=tipo, serie=serie)
        assert r.status_code == 400, r.content
        assert "serie" in str(r.json()).lower()

    def test_una_serie_fisica_puede_ser_numerica(self, equipo):
        assert (
            _ok(_crear(cliente_de("super"), equipo, serie="0001", es_electronica=False))[
                "es_electronica"
            ]
            is False
        )

    def test_no_se_repite_en_la_misma_empresa(self, equipo):
        api = cliente_de("super")
        _ok(_crear(api, equipo))
        r = _crear(api, equipo)
        assert r.status_code == 400 and "serie" in str(r.json()).lower()

    def test_solo_tipos_de_ventas_activos(self, equipo):
        api = cliente_de("super")
        assert (
            _crear(api, equipo, tipo="02", serie="E001").status_code == 400
        )  # recibo: solo compras
        TipoComprobante.objects.sin_ambito().filter(
            organizacion=equipo["e"].org_a, codigo="01"
        ).update(estado="INACTIVO")
        assert _crear(api, equipo, tipo="01", serie="F001").status_code == 400

    def test_la_sucursal_debe_ser_de_la_empresa(self, equipo):
        r = _crear(cliente_de("super"), equipo, sucursal=equipo["suc2"].pk)
        assert r.status_code == 400 and "sucursal" in str(r.json()).lower()

    def test_el_numero_inicial_se_puede_fijar(self, equipo):
        s = _ok(_crear(cliente_de("super"), equipo, ultimo_numero=244))
        assert (s["ultimo_numero"], s["proximo"]) == (244, "F001-00000245")

    @pytest.mark.parametrize("numero", [-1, 100_000_000])
    def test_numero_fuera_de_rango(self, equipo, numero):
        assert _crear(cliente_de("super"), equipo, ultimo_numero=numero).status_code == 400

    def test_el_tipo_es_obligatorio(self, equipo):
        e = equipo["e"]
        r = cliente_de("super").post(
            f"{BASE}/series-comprobante/", {"empresa": e.emp_a1.pk, "serie": "F001"}, format="json"
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Permisos y aislamiento
# ---------------------------------------------------------------------------
class TestPermisos:
    def test_el_vendedor_las_ve_pero_no_las_cambia(self, equipo):
        _ok(_crear(cliente_de("super"), equipo))
        api = cliente_de("vendedor")
        e = equipo["e"]
        assert api.get(f"{BASE}/series-comprobante/", {"empresa": e.emp_a1.pk}).json()["count"] == 1
        assert _crear(api, equipo, serie="F009").status_code == 403

    def test_el_almacenero_no_las_ve(self, equipo):
        e = equipo["e"]
        r = cliente_de("almacenero").get(f"{BASE}/series-comprobante/", {"empresa": e.emp_a1.pk})
        assert r.status_code == 403

    def test_el_contador_crea_y_edita_las_de_su_empresa(self, equipo):
        api = cliente_de("contador")
        s = _ok(_crear(api, equipo, serie="F001"))
        r = api.patch(f"{BASE}/series-comprobante/{s['id']}/", {"nombre": "Caja 1"}, format="json")
        assert r.status_code == 200 and r.json()["nombre"] == "Caja 1"

    def test_no_se_toca_una_empresa_sin_acceso(self, equipo):
        # El contador solo tiene acceso a la empresa 1.
        assert _crear(cliente_de("contador"), equipo, serie="F002", empresa=2).status_code == 403

    def test_otra_organizacion_no_las_ve(self, equipo):
        s = _ok(_crear(cliente_de("super"), equipo))
        otra = cliente_de("otra_org")
        assert otra.get(f"{BASE}/series-comprobante/{s['id']}/").status_code == 404
        e = equipo["e"]
        assert (
            otra.get(f"{BASE}/series-comprobante/", {"empresa": e.emp_b1.pk}).json()["count"] == 0
        )


# ---------------------------------------------------------------------------
# Numeración
# ---------------------------------------------------------------------------
class TestNumeracion:
    def _serie(self, equipo, **extra):
        s = _ok(_crear(cliente_de("super"), equipo, **extra))
        return SerieComprobante.objects.sin_ambito().get(pk=s["id"])

    def test_entrega_numeros_seguidos(self, equipo):
        emp = equipo["e"].emp_a1
        serie = self._serie(equipo)
        numeros = [series.siguiente_numero(emp, serie.pk) for _ in range(3)]
        assert numeros == [("F001", 1), ("F001", 2), ("F001", 3)]
        serie.refresh_from_db()
        assert (serie.ultimo_numero, serie.emitidos) == (3, 3)
        assert series.formatear("F001", 3) == "F001-00000003"

    def test_continua_desde_el_numero_inicial(self, equipo):
        emp = equipo["e"].emp_a1
        serie = self._serie(equipo, ultimo_numero=244)
        assert series.siguiente_numero(emp, serie.pk) == ("F001", 245)

    def test_cada_serie_numera_por_separado(self, equipo):
        emp = equipo["e"].emp_a1
        factura = self._serie(equipo, tipo="01", serie="F001")
        boleta = self._serie(equipo, tipo="03", serie="B001")
        series.siguiente_numero(emp, factura.pk)
        series.siguiente_numero(emp, factura.pk)
        assert series.siguiente_numero(emp, boleta.pk) == ("B001", 1)

    def test_una_serie_desactivada_no_emite(self, equipo):
        emp = equipo["e"].emp_a1
        serie = self._serie(equipo)
        serie.estado = "INACTIVO"
        serie.save()
        with pytest.raises(SerieInactiva):
            series.siguiente_numero(emp, serie.pk)

    def test_la_serie_de_otra_empresa_no_sirve(self, equipo):
        e = equipo["e"]
        serie = self._serie(equipo, empresa=2, serie="F002")
        with pytest.raises(SerieNoDisponible):
            series.siguiente_numero(e.emp_a1, serie.pk)

    def test_al_llegar_al_ultimo_numero_se_detiene(self, equipo):
        emp = equipo["e"].emp_a1
        serie = self._serie(equipo, ultimo_numero=99_999_998)
        assert series.siguiente_numero(emp, serie.pk)[1] == 99_999_999
        with pytest.raises(SerieAgotada):
            series.siguiente_numero(emp, serie.pk)


# ---------------------------------------------------------------------------
# Edición del número y de la serie
# ---------------------------------------------------------------------------
class TestEdicion:
    def _con_emitidos(self, equipo, cuantos=3):
        s = _ok(_crear(cliente_de("super"), equipo))
        for _ in range(cuantos):
            series.siguiente_numero(equipo["e"].emp_a1, s["id"])
        return s["id"]

    def _patch(self, serie_id, datos, usuario="super"):
        return cliente_de(usuario).patch(
            f"{BASE}/series-comprobante/{serie_id}/", datos, format="json"
        )

    def test_sin_emisiones_el_numero_es_libre(self, equipo):
        s = _ok(_crear(cliente_de("super"), equipo, ultimo_numero=50))
        assert self._patch(s["id"], {"ultimo_numero": 10}).json()["ultimo_numero"] == 10
        assert self._patch(s["id"], {"ultimo_numero": 0}).json()["ultimo_numero"] == 0

    def test_despues_de_emitir_solo_puede_subir(self, equipo):
        sid = self._con_emitidos(equipo)
        assert self._patch(sid, {"ultimo_numero": 2}).status_code == 409
        assert self._patch(sid, {"ultimo_numero": 3}).status_code == 200  # igual: sin cambio
        r = self._patch(sid, {"ultimo_numero": 10})
        assert r.status_code == 200 and r.json()["proximo"] == "F001-00000011"

    def test_el_ajuste_queda_auditado(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        s = _ok(_crear(cliente_de("super"), equipo))
        self._patch(s["id"], {"ultimo_numero": 244})
        evento = AuditoriaEvento.objects.get(accion="serie_comprobante.editado")
        assert evento.detalle["ultimo_numero"] == ["0", "244"] or evento.detalle[
            "ultimo_numero"
        ] == [0, 244]

    def test_una_serie_que_emitio_no_cambia_de_codigo_ni_de_tipo(self, equipo):
        sid = self._con_emitidos(equipo)
        assert self._patch(sid, {"serie": "F009"}).status_code == 400
        assert self._patch(sid, {"tipo_comprobante": _tipo(equipo, "07").pk}).status_code == 400
        assert self._patch(sid, {"es_electronica": False}).status_code == 400
        assert self._patch(sid, {"nombre": "Caja 2"}).status_code == 200

    def test_sin_emisiones_si_se_corrige_el_codigo(self, equipo):
        s = _ok(_crear(cliente_de("super"), equipo, serie="F001"))
        r = self._patch(s["id"], {"serie": "F004"})
        assert r.status_code == 200 and r.json()["serie"] == "F004"

    def test_se_puede_desactivar_y_reactivar(self, equipo):
        sid = self._con_emitidos(equipo, 1)
        assert self._patch(sid, {"estado": "INACTIVO"}).json()["estado"] == "INACTIVO"
        assert self._patch(sid, {"estado": "ACTIVO"}).json()["estado"] == "ACTIVO"

    def test_borrado(self, equipo):
        api = cliente_de("super")
        libre = _ok(_crear(api, equipo, serie="F001"))
        assert api.delete(f"{BASE}/series-comprobante/{libre['id']}/").status_code == 204
        usada = self._con_emitidos(equipo)
        assert api.delete(f"{BASE}/series-comprobante/{usada}/").status_code == 409
        assert SerieComprobante.objects.sin_ambito().filter(pk=usada).exists()
