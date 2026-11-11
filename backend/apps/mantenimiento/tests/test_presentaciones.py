"""Presentaciones de un producto (caja, docena…): equivalencias, precios y conversión a la base."""

from decimal import Decimal

import pytest

from apps.auditoria import servicios
from apps.mantenimiento import presentaciones
from apps.mantenimiento.models import (
    Categoria,
    Familia,
    ListaPrecio,
    PrecioPresentacion,
    PresentacionProducto,
    Producto,
    UnidadMedida,
)
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def mundo(rbac, nuevo_usuario):
    e = rbac
    org = e.org_a
    familia = Familia.objects.sin_ambito().create(organizacion=org, nombre="General")
    categoria = Categoria.objects.sin_ambito().create(
        organizacion=org, familia=familia, nombre="Bebidas"
    )
    unidades = {
        n: UnidadMedida.objects.sin_ambito().create(
            organizacion=org, nombre=n, abreviatura=a, codigo_sunat=c
        )
        for n, a, c in (("Unidad", "UND", "NIU"), ("Caja", "CAJA", "BX"), ("Docena", "DOC", "DZN"))
    }
    listas = {
        n: ListaPrecio.objects.sin_ambito().create(
            organizacion=org, nombre=n, orden=i, es_principal=(i == 1)
        )
        for i, n in enumerate(("Público", "Técnico"), start=1)
    }
    producto = Producto.objects.sin_ambito().create(
        organizacion=org,
        codigo="000001",
        nombre="Gaseosa 500 ml",
        categoria=categoria,
        unidad=unidades["Unidad"],
        costo=Decimal("10"),
    )
    return {
        "e": e,
        "unidades": unidades,
        "listas": listas,
        "producto": producto,
        "categoria": categoria,
        "super": nuevo_usuario(org, "super", [e.emp_a1], [("SUPERADMIN", None)]),
        "almacenero": nuevo_usuario(org, "almacenero", [e.emp_a1], [("ALMACENERO", None)]),
        "vendedor": nuevo_usuario(org, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def _crear(api, mundo, *, unidad="Caja", factor="12", producto=None, **extra):
    return api.post(
        f"{BASE}/presentaciones/",
        {
            "producto": (producto or mundo["producto"]).pk,
            "unidad": mundo["unidades"][unidad].pk,
            "factor": factor,
            **extra,
        },
        format="json",
    )


def _ok(respuesta):
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()


def _precios(mundo, publico, tecnico=None):
    filas = [{"lista": mundo["listas"]["Público"].pk, "precio": publico}]
    if tecnico is not None:
        filas.append({"lista": mundo["listas"]["Técnico"].pk, "precio": tecnico})
    return filas


# ---------------------------------------------------------------------------
# Conversión (cálculo puro)
# ---------------------------------------------------------------------------
class TestConversion:
    def _presentacion(self, mundo, factor="12"):
        return PresentacionProducto.objects.sin_ambito().create(
            organizacion=mundo["e"].org_a,
            producto=mundo["producto"],
            unidad=mundo["unidades"]["Caja"],
            factor=Decimal(factor),
        )

    @pytest.mark.parametrize(
        ("factor", "cantidad", "esperado"),
        [
            ("12", "2", "24"),
            ("12", "0.5", "6"),
            ("12", "1.25", "15"),
            ("0.5", "3", "1.5"),
            ("0.333", "3", "0.999"),
        ],
    )
    def test_convierte_a_la_unidad_base(self, mundo, factor, cantidad, esperado):
        resultado = presentaciones.convertir_a_base(
            self._presentacion(mundo, factor), Decimal(cantidad)
        )
        assert resultado == Decimal(esperado)

    def test_no_acepta_una_cantidad_que_no_cabe_en_3_decimales(self, mundo):
        with pytest.raises(ValueError, match="exacta"):
            presentaciones.convertir_a_base(self._presentacion(mundo, "0.333"), Decimal("0.0001"))

    @pytest.mark.parametrize("cantidad", [Decimal("0"), Decimal("-1"), Decimal("NaN"), 2, "3"])
    def test_cantidad_invalida(self, mundo, cantidad):
        with pytest.raises(ValueError, match="mayor que cero"):
            presentaciones.convertir_a_base(self._presentacion(mundo), cantidad)

    def test_la_utilidad_sale_del_costo_de_la_presentacion(self):
        # Costo base 10 × 12 = 120 por caja; a 150 se gana el 25 %.
        assert presentaciones.utilidad_de_presentacion(
            Decimal("150"), Decimal("10"), Decimal("12")
        ) == Decimal("25.00")
        assert (
            presentaciones.utilidad_de_presentacion(Decimal("150"), Decimal("0"), Decimal("12"))
            is None
        )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class TestApi:
    def test_crea_una_presentacion_con_su_equivalencia(self, mundo):
        p = _ok(_crear(cliente_de("super"), mundo, codigo_barras="7750001234567"))
        assert (p["equivalencia"], p["unidad_abreviatura"], p["factor"], p["codigo_barras"]) == (
            "1 Caja = 12 Unidad",
            "CAJA",
            "12.000",
            "7750001234567",
        )

    def test_los_precios_calculan_la_utilidad_sobre_el_costo_de_la_caja(self, mundo):
        p = _ok(_crear(cliente_de("super"), mundo, precios=_precios(mundo, "150", "135")))
        por_lista = {x["lista_nombre"]: x for x in p["precios"]}
        assert (por_lista["Público"]["precio"], por_lista["Público"]["utilidad"]) == (
            "150.0000",
            "25.00",
        )
        assert por_lista["Técnico"]["utilidad"] == "12.50"

    def test_se_puede_poner_el_precio_por_utilidad(self, mundo):
        filas = [{"lista": mundo["listas"]["Público"].pk, "utilidad": "30"}]
        p = _ok(_crear(cliente_de("super"), mundo, precios=filas))
        assert p["precios"][0]["precio"] == "156.0000"  # 120 × 1,30

    def test_el_producto_trae_sus_presentaciones(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo, unidad="Caja", factor="12", precios=_precios(mundo, "150")))
        _ok(_crear(api, mundo, unidad="Docena", factor="12"))
        detalle = api.get(f"{BASE}/productos/{mundo['producto'].pk}/").json()
        assert sorted(x["unidad_nombre"] for x in detalle["presentaciones"]) == ["Caja", "Docena"]
        assert (
            detalle["precios"] == []
        )  # los precios de la unidad base no se mezclan con los de la caja

    def test_sin_el_permiso_de_precios_no_se_ven_las_utilidades(self, mundo):
        _ok(_crear(cliente_de("super"), mundo, precios=_precios(mundo, "150")))
        vista = cliente_de("vendedor").get(f"{BASE}/productos/{mundo['producto'].pk}/").json()
        assert vista["presentaciones"][0]["precios"][0]["precio"] == "150.0000"
        assert "utilidad" not in vista["presentaciones"][0]["precios"][0]
        assert "costo" not in vista

    def test_edita_el_factor_y_la_utilidad_sigue_siendo_verdad(self, mundo):
        api = cliente_de("super")
        p = _ok(_crear(api, mundo, precios=_precios(mundo, "150")))
        r = api.patch(
            f"{BASE}/presentaciones/{p['id']}/", {"factor": "10"}, format="json"
        )  # ahora la caja cuesta 100
        assert r.status_code == 200, r.content
        assert (r.json()["factor"], r.json()["precios"][0]["utilidad"]) == ("10.000", "50.00")

    def test_al_cambiar_el_costo_del_producto_cambia_la_utilidad_de_la_caja(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo, precios=_precios(mundo, "150")))
        api.patch(
            f"{BASE}/productos/{mundo['producto'].pk}/", {"costo": "12.5"}, format="json"
        )  # caja: 150 → costo 150
        fila = PrecioPresentacion.objects.sin_ambito().get()
        assert fila.utilidad == Decimal("0.00")

    def test_cambia_los_precios_y_quita_los_que_ya_no(self, mundo):
        api = cliente_de("super")
        p = _ok(_crear(api, mundo, precios=_precios(mundo, "150", "135")))
        r = api.patch(
            f"{BASE}/presentaciones/{p['id']}/", {"precios": _precios(mundo, "160")}, format="json"
        )
        assert [x["lista_nombre"] for x in r.json()["precios"]] == ["Público"]
        assert r.json()["precios"][0]["precio"] == "160.0000"

    def test_la_unidad_y_el_producto_no_cambian(self, mundo):
        api = cliente_de("super")
        p = _ok(_crear(api, mundo))
        r = api.patch(
            f"{BASE}/presentaciones/{p['id']}/",
            {"unidad": mundo["unidades"]["Docena"].pk},
            format="json",
        )
        assert r.status_code == 400 and "unidad" in str(r.json()).lower()

    def test_se_desactiva_y_se_elimina(self, mundo):
        api = cliente_de("super")
        p = _ok(_crear(api, mundo, precios=_precios(mundo, "150")))
        assert (
            api.patch(
                f"{BASE}/presentaciones/{p['id']}/", {"estado": "INACTIVO"}, format="json"
            ).json()["estado"]
            == "INACTIVO"
        )
        assert api.delete(f"{BASE}/presentaciones/{p['id']}/").status_code == 204
        assert not PresentacionProducto.objects.sin_ambito().exists()
        assert not PrecioPresentacion.objects.sin_ambito().exists()
        _ok(_crear(api, mundo))  # la unidad queda libre para una nueva

    def test_lista_por_producto(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo))
        otro = Producto.objects.sin_ambito().create(
            organizacion=mundo["e"].org_a,
            codigo="000002",
            nombre="Agua",
            categoria=mundo["categoria"],
            unidad=mundo["unidades"]["Unidad"],
        )
        _ok(_crear(api, mundo, producto=otro))
        r = api.get(f"{BASE}/presentaciones/", {"producto": mundo["producto"].pk}).json()
        assert r["count"] == 1

    def test_queda_auditado(self, mundo):
        from apps.auditoria.models import AuditoriaEvento

        api = cliente_de("super")
        p = _ok(_crear(api, mundo))
        api.patch(f"{BASE}/presentaciones/{p['id']}/", {"factor": "24"}, format="json")
        api.delete(f"{BASE}/presentaciones/{p['id']}/")
        acciones = set(AuditoriaEvento.objects.values_list("accion", flat=True))
        assert {"presentacion.creada", "presentacion.editada", "presentacion.eliminada"} <= acciones


# ---------------------------------------------------------------------------
# Reglas
# ---------------------------------------------------------------------------
class TestReglas:
    @pytest.mark.parametrize("factor", ["1", "0", "-3", "1000001", "abc"])
    def test_factor_invalido(self, mundo, factor):
        assert _crear(cliente_de("super"), mundo, factor=factor).status_code == 400

    def test_la_unidad_base_no_es_una_presentacion(self, mundo):
        assert _crear(cliente_de("super"), mundo, unidad="Unidad").status_code == 400

    def test_una_unidad_no_se_repite_en_el_producto(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo))
        r = _crear(api, mundo, factor="6")
        assert r.status_code == 400 and "unidad" in str(r.json()).lower()

    def test_un_servicio_no_tiene_presentaciones(self, mundo):
        Producto.objects.sin_ambito().filter(pk=mundo["producto"].pk).update(
            tipo="SERVICIO", controla_stock=False
        )
        assert _crear(cliente_de("super"), mundo).status_code == 400

    def test_un_producto_con_serie_solo_va_en_su_unidad_base(self, mundo):
        Producto.objects.sin_ambito().filter(pk=mundo["producto"].pk).update(lleva_serie=True)
        r = _crear(cliente_de("super"), mundo)
        assert r.status_code == 400 and "serie" in str(r.json()).lower()

    def test_el_codigo_de_barras_no_se_repite(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo, unidad="Caja", codigo_barras="7750001234567"))
        r = _crear(api, mundo, unidad="Docena", codigo_barras="7750001234567")
        assert r.status_code == 400 and "codigo_barras" in str(r.json())

    def test_el_codigo_de_barras_no_puede_ser_el_de_un_producto(self, mundo):
        Producto.objects.sin_ambito().filter(pk=mundo["producto"].pk).update(
            codigo_barras="7750009999999"
        )
        r = _crear(cliente_de("super"), mundo, codigo_barras="7750009999999")
        assert r.status_code == 400

    def test_y_un_producto_tampoco_puede_tomar_el_codigo_de_una_presentacion(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo, codigo_barras="7750001234567"))
        otro = Producto.objects.sin_ambito().create(
            organizacion=mundo["e"].org_a,
            codigo="000002",
            nombre="Agua",
            categoria=mundo["categoria"],
            unidad=mundo["unidades"]["Unidad"],
        )
        r = api.patch(
            f"{BASE}/productos/{otro.pk}/", {"codigo_barras": "7750001234567"}, format="json"
        )
        assert r.status_code == 400

    def test_codigo_de_barras_con_formato_incorrecto(self, mundo):
        assert _crear(cliente_de("super"), mundo, codigo_barras="ab").status_code == 400

    def test_una_unidad_inactiva_o_de_otra_organizacion_no_sirve(self, mundo):
        UnidadMedida.objects.sin_ambito().filter(pk=mundo["unidades"]["Caja"].pk).update(
            estado="INACTIVO"
        )
        assert _crear(cliente_de("super"), mundo, unidad="Caja").status_code == 400
        ajena = UnidadMedida.objects.sin_ambito().create(
            organizacion=mundo["e"].org_b, nombre="Bulto", abreviatura="BLT", codigo_sunat="NIU"
        )
        r = cliente_de("super").post(
            f"{BASE}/presentaciones/",
            {"producto": mundo["producto"].pk, "unidad": ajena.pk, "factor": "5"},
            format="json",
        )
        assert r.status_code == 400

    def test_la_lista_de_otra_organizacion_no_sirve(self, mundo):
        ajena = ListaPrecio.objects.sin_ambito().create(
            organizacion=mundo["e"].org_b, nombre="Ajena", orden=1
        )
        r = _crear(cliente_de("super"), mundo, precios=[{"lista": ajena.pk, "precio": "10"}])
        assert r.status_code == 400

    def test_precio_negativo_y_lista_repetida(self, mundo):
        api = cliente_de("super")
        pid = mundo["listas"]["Público"].pk
        assert _crear(api, mundo, precios=[{"lista": pid, "precio": "-1"}]).status_code == 400
        assert (
            _crear(
                api, mundo, precios=[{"lista": pid, "precio": "5"}, {"lista": pid, "precio": "6"}]
            ).status_code
            == 400
        )

    def test_el_producto_con_presentaciones_no_cambia_de_unidad_base_ni_pasa_a_serie(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo))
        url = f"{BASE}/productos/{mundo['producto'].pk}/"
        assert (
            api.patch(url, {"unidad": mundo["unidades"]["Docena"].pk}, format="json").status_code
            == 400
        )
        assert api.patch(url, {"lleva_serie": True}, format="json").status_code == 400
        assert api.patch(url, {"nombre": "Gaseosa 500 ml PET"}, format="json").status_code == 200

    def test_sin_presentaciones_la_unidad_base_si_cambia(self, mundo):
        url = f"{BASE}/productos/{mundo['producto'].pk}/"
        r = cliente_de("super").patch(
            url, {"unidad": mundo["unidades"]["Docena"].pk}, format="json"
        )
        assert r.status_code == 200

    def test_una_unidad_o_una_lista_en_uso_no_se_eliminan(self, mundo):
        api = cliente_de("super")
        _ok(_crear(api, mundo, unidad="Caja", precios=_precios(mundo, "150")))
        assert api.delete(f"{BASE}/unidades/{mundo['unidades']['Caja'].pk}/").status_code == 409
        assert (
            api.delete(f"{BASE}/listas-precio/{mundo['listas']['Público'].pk}/").status_code == 409
        )


# ---------------------------------------------------------------------------
# Permisos y aislamiento
# ---------------------------------------------------------------------------
class TestPermisos:
    def test_el_vendedor_las_ve_pero_no_las_cambia(self, mundo):
        p = _ok(_crear(cliente_de("super"), mundo))
        api = cliente_de("vendedor")
        assert (
            api.get(f"{BASE}/presentaciones/", {"producto": mundo["producto"].pk}).json()["count"]
            == 1
        )
        assert _crear(api, mundo, unidad="Docena").status_code == 403
        assert (
            api.patch(
                f"{BASE}/presentaciones/{p['id']}/", {"factor": "6"}, format="json"
            ).status_code
            == 403
        )
        assert api.delete(f"{BASE}/presentaciones/{p['id']}/").status_code == 403

    def test_quien_edita_productos_crea_presentaciones_pero_sin_precios_necesita_el_permiso(
        self, mundo
    ):
        api = cliente_de("almacenero")
        assert _crear(api, mundo).status_code == 201  # puede editar productos
        r = _crear(api, mundo, unidad="Docena", precios=_precios(mundo, "150"))
        assert r.status_code == 403  # pero poner precios es otro permiso

    def test_otra_organizacion_no_ve_ni_toca(self, mundo):
        p = _ok(_crear(cliente_de("super"), mundo))
        otra = cliente_de("otra_org")
        assert otra.get(f"{BASE}/presentaciones/{p['id']}/").status_code == 404
        assert (
            otra.patch(
                f"{BASE}/presentaciones/{p['id']}/", {"factor": "6"}, format="json"
            ).status_code
            == 404
        )
        assert otra.get(f"{BASE}/presentaciones/").json()["count"] == 0
        r = otra.post(
            f"{BASE}/presentaciones/",
            {
                "producto": mundo["producto"].pk,
                "unidad": mundo["unidades"]["Docena"].pk,
                "factor": "2",
            },
            format="json",
        )
        assert r.status_code == 400
