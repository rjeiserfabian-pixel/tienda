"""Ubicaciones de los almacenes y dónde está cada producto (catálogo + asignación + stock)."""

import pytest

from apps.auditoria import servicios
from apps.inventario.tests.ayudas_api import BASE, cuerpo, registrar
from apps.mantenimiento.models import Ubicacion, UbicacionProducto
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

MANT = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


def _crear(api, mundo, codigo="V1", nombre="Vitrina 1", empresa=1):
    emp = mundo.e1 if empresa == 1 else mundo.e2
    r = api.post(
        f"{MANT}/ubicaciones/",
        {"empresa": emp.pk, "almacen": mundo.alm[empresa].pk, "codigo": codigo, "nombre": nombre},
        format="json",
    )
    assert r.status_code == 201, r.content
    return r.json()


def _asignar(api, mundo, producto, ubicacion, empresa=1):
    emp = mundo.e1 if empresa == 1 else mundo.e2
    return api.post(
        f"{BASE}/ubicaciones/asignar/",
        {
            "empresa": emp.pk,
            "almacen": mundo.alm[empresa].pk,
            "producto": producto.pk,
            "ubicacion": ubicacion,
        },
        format="json",
    )


class TestCatalogo:
    def test_alta_normaliza_el_codigo(self, mundo):
        api = cliente_de("super")
        u = _crear(api, mundo, codigo=" a-03 ", nombre="  Estante   A nivel 3 ")
        assert (u["codigo"], u["nombre"], u["estado"], u["n_productos"]) == (
            "A-03",
            "Estante A nivel 3",
            "ACTIVO",
            0,
        )

    def test_el_codigo_no_se_repite_en_el_mismo_almacen(self, mundo):
        api = cliente_de("super")
        _crear(api, mundo)
        r = api.post(
            f"{MANT}/ubicaciones/",
            {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk, "codigo": "v1", "nombre": "Otra"},
            format="json",
        )
        assert r.status_code == 400
        assert "codigo" in str(r.json()).lower()

    def test_el_almacen_debe_ser_de_la_empresa(self, mundo):
        api = cliente_de("super")
        r = api.post(
            f"{MANT}/ubicaciones/",
            {"empresa": mundo.e1.pk, "almacen": mundo.alm[2].pk, "codigo": "V1", "nombre": "X"},
            format="json",
        )
        assert r.status_code == 400

    def test_no_se_mueve_de_almacen(self, mundo):
        api = cliente_de("super")
        u = _crear(api, mundo)
        r = api.patch(
            f"{MANT}/ubicaciones/{u['id']}/",
            {"almacen": mundo.alm[2].pk, "codigo": "V1", "nombre": "X"},
            format="json",
        )
        assert r.status_code == 400

    def test_el_almacenero_gestiona_las_de_su_empresa(self, mundo):
        api = cliente_de("almacenero")
        _crear(api, mundo)
        r = api.get(f"{MANT}/ubicaciones/", {"empresa": mundo.e1.pk})
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_el_vendedor_no_las_administra(self, mundo):
        api = cliente_de("vendedor")
        r = api.post(
            f"{MANT}/ubicaciones/",
            {"empresa": mundo.e1.pk, "almacen": mundo.alm[1].pk, "codigo": "V1", "nombre": "X"},
            format="json",
        )
        assert r.status_code == 403

    def test_una_ubicacion_en_uso_no_se_elimina(self, mundo):
        api = cliente_de("super")
        producto = mundo.producto()
        u = _crear(api, mundo)
        assert _asignar(api, mundo, producto, u["id"]).status_code == 200
        r = api.delete(f"{MANT}/ubicaciones/{u['id']}/")
        assert r.status_code == 409
        assert Ubicacion.objects.sin_ambito().filter(pk=u["id"]).exists()


class TestAsignacion:
    def test_asigna_cambia_y_quita(self, mundo):
        api = cliente_de("almacenero")
        producto = mundo.producto()
        v1 = _crear(api, mundo)
        a3 = _crear(api, mundo, codigo="A-03", nombre="Estante A3")

        r = _asignar(api, mundo, producto, v1["id"])
        assert r.status_code == 200, r.content
        assert r.json()["ubicacion_codigo"] == "V1"

        r = _asignar(api, mundo, producto, a3["id"])  # cambia: sigue siendo UNA por almacén
        assert r.json()["ubicacion_codigo"] == "A-03"
        assert UbicacionProducto.objects.sin_ambito().filter(producto=producto).count() == 1

        r = _asignar(api, mundo, producto, None)  # quita
        assert r.status_code == 204
        assert not UbicacionProducto.objects.sin_ambito().filter(producto=producto).exists()

    def test_se_puede_reasignar_despues_de_quitar(self, mundo):
        api = cliente_de("almacenero")
        producto = mundo.producto()
        v1 = _crear(api, mundo)
        _asignar(api, mundo, producto, v1["id"])
        _asignar(api, mundo, producto, None)
        assert _asignar(api, mundo, producto, v1["id"]).status_code == 200

    def test_la_ubicacion_debe_ser_del_almacen(self, mundo):
        api = cliente_de("super")
        producto = mundo.producto()
        del_a2 = _crear(api, mundo, empresa=2)
        r = _asignar(api, mundo, producto, del_a2["id"])
        assert r.status_code == 400

    def test_una_ubicacion_inactiva_no_se_asigna(self, mundo):
        api = cliente_de("super")
        producto = mundo.producto()
        u = _crear(api, mundo)
        api.patch(
            f"{MANT}/ubicaciones/{u['id']}/",
            {"codigo": "V1", "nombre": "Vitrina 1", "estado": "INACTIVO"},
            format="json",
        )
        assert _asignar(api, mundo, producto, u["id"]).status_code == 400

    def test_un_servicio_no_lleva_ubicacion(self, mundo):
        api = cliente_de("super")
        servicio = mundo.producto("Instalación", tipo="SERVICIO")
        u = _crear(api, mundo)
        assert _asignar(api, mundo, servicio, u["id"]).status_code == 400

    def test_el_vendedor_no_asigna(self, mundo):
        producto = mundo.producto()
        u = _crear(cliente_de("super"), mundo)
        assert _asignar(cliente_de("vendedor"), mundo, producto, u["id"]).status_code == 403

    def test_no_se_asigna_en_una_empresa_ajena(self, mundo):
        producto = mundo.producto()
        u = _crear(cliente_de("super"), mundo, empresa=2)
        r = _asignar(cliente_de("almacenero"), mundo, producto, u["id"], empresa=2)
        assert r.status_code in (400, 403)
        assert not UbicacionProducto.objects.sin_ambito().exists()

    def test_el_cambio_queda_auditado(self, mundo):
        from apps.auditoria.models import AuditoriaEvento

        api = cliente_de("super")
        producto = mundo.producto()
        u = _crear(api, mundo)
        _asignar(api, mundo, producto, u["id"])
        assert AuditoriaEvento.objects.filter(accion="producto.ubicacion").count() == 1

    def test_el_listado_filtra_por_producto(self, mundo):
        api = cliente_de("super")
        uno, otro = mundo.producto("Uno"), mundo.producto("Otro")
        u = _crear(api, mundo)
        _asignar(api, mundo, uno, u["id"])
        _asignar(api, mundo, otro, u["id"])
        r = api.get(f"{BASE}/ubicaciones/", {"empresa": mundo.e1.pk, "producto": uno.pk})
        assert [f["producto"] for f in r.json()["results"]] == [uno.pk]
        n = api.get(f"{MANT}/ubicaciones/", {"empresa": mundo.e1.pk}).json()["results"][0][
            "n_productos"
        ]
        assert n == 2


class TestStock:
    def test_el_stock_trae_la_ubicacion_y_filtra_por_ella(self, mundo):
        api = cliente_de("super")
        con, sin = mundo.producto("Con ubicación"), mundo.producto("Sin ubicación")
        assert registrar(api, cuerpo(mundo, con)).status_code == 201
        assert registrar(api, cuerpo(mundo, sin)).status_code == 201
        u = _crear(api, mundo)
        _asignar(api, mundo, con, u["id"])

        r = api.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk})
        filas = {f["producto_nombre"]: f for f in r.json()["results"]}
        assert filas["Con ubicación"]["ubicacion_codigo"] == "V1"
        assert filas["Sin ubicación"]["ubicacion_codigo"] is None

        r = api.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk, "ubicacion": u["id"]})
        assert [f["producto_nombre"] for f in r.json()["results"]] == ["Con ubicación"]


def _en_movimiento(mundo, producto, ubicacion, **extra):
    datos = cuerpo(mundo, producto, **extra)
    datos["lineas"][0]["ubicacion"] = ubicacion
    return datos


class TestEnMovimientos:
    def test_la_entrada_deja_el_producto_en_su_ubicacion(self, mundo):
        api = cliente_de("almacenero")
        producto = mundo.producto()
        u = _crear(api, mundo)
        r = registrar(api, _en_movimiento(mundo, producto, u["id"]))
        assert r.status_code == 201, r.content
        asignada = UbicacionProducto.objects.sin_ambito().get(producto=producto)
        assert asignada.ubicacion_id == u["id"]

    def test_sin_ubicacion_no_toca_la_que_ya_tenia(self, mundo):
        api = cliente_de("almacenero")
        producto = mundo.producto()
        u = _crear(api, mundo)
        _asignar(api, mundo, producto, u["id"])
        assert registrar(api, cuerpo(mundo, producto)).status_code == 201
        assert UbicacionProducto.objects.sin_ambito().get(producto=producto).ubicacion_id == u["id"]

    def test_una_ubicacion_invalida_no_registra_el_movimiento(self, mundo):
        from apps.inventario.models import MovimientoInventario

        api = cliente_de("super")
        producto = mundo.producto()
        ajena = _crear(api, mundo, empresa=2)
        r = registrar(api, _en_movimiento(mundo, producto, ajena["id"]))
        assert r.status_code == 400, r.content
        assert not MovimientoInventario.objects.sin_ambito().exists()

    def test_en_una_salida_no_se_indica(self, mundo):
        api = cliente_de("super")
        producto = mundo.producto()
        u = _crear(api, mundo)
        assert registrar(api, cuerpo(mundo, producto)).status_code == 201
        salida = _en_movimiento(
            mundo, producto, u["id"], cantidad="1", tipo="SALIDA", origen="MERMA"
        )
        salida["lineas"][0].pop("precio_unitario")
        assert registrar(api, salida).status_code == 400

    def test_sin_el_permiso_de_asignar_se_rechaza(self, mundo):
        u = _crear(cliente_de("super"), mundo)
        producto = mundo.producto()
        # El contador puede ver pero no registrar: se frena antes. Se prueba con un rol que
        # registre sin asignar quitándole el permiso al almacenero.
        from apps.seguridad.models import Permiso, RolPermiso

        permiso = Permiso.objects.get(codigo="INVENTARIO.UBICACIONES.ASIGNAR")
        for rp in RolPermiso.objects.sin_ambito().filter(permiso=permiso, rol__codigo="ALMACENERO"):
            rp.delete()
        r = registrar(cliente_de("almacenero"), _en_movimiento(mundo, producto, u["id"]))
        assert r.status_code == 403
        assert not UbicacionProducto.objects.sin_ambito().exists()


class TestImportacion:
    def _archivo(self, mundo, producto, ubicacion):
        from apps.inventario.tests.test_importacion import TITULOS, xlsx

        return xlsx(
            [[producto.codigo, "x", "ALM1", 5, 10, ubicacion]],
            titulos=[*TITULOS, "Ubicación (opcional)"],
        )

    def test_el_saldo_inicial_asigna_la_ubicacion(self, mundo):
        from apps.inventario.tests.test_importacion import subir

        producto = mundo.producto()
        _crear(cliente_de("super"), mundo, codigo="A-03", nombre="Estante A3")
        r = subir(mundo, self._archivo(mundo, producto, "a-03"), modo="importar")
        assert r.status_code == 200, r.content
        asignada = UbicacionProducto.objects.sin_ambito().get(producto=producto)
        assert asignada.ubicacion.codigo == "A-03"

    def test_una_ubicacion_inexistente_es_error_de_fila(self, mundo):
        from apps.inventario.tests.test_importacion import subir

        producto = mundo.producto()
        r = subir(mundo, self._archivo(mundo, producto, "NOEXISTE"))
        datos = r.json()
        assert (datos["validas"], datos["con_error"]) == (0, 1)
        assert "NOEXISTE" in datos["errores"][0]["mensaje"]

    def test_la_columna_es_opcional(self, mundo):
        from apps.inventario.tests.test_importacion import TITULOS, subir, xlsx

        producto = mundo.producto()
        r = subir(mundo, xlsx([[producto.codigo, "x", "ALM1", 5, 10]], titulos=TITULOS))
        assert r.json()["validas"] == 1


class TestStockReciente:
    def test_orden_reciente_pone_primero_lo_ultimo_que_se_movio(self, mundo):
        api = cliente_de("super")
        viejo, nuevo = mundo.producto("Aaa viejo"), mundo.producto("Zzz nuevo")
        assert registrar(api, cuerpo(mundo, viejo)).status_code == 201
        assert registrar(api, cuerpo(mundo, nuevo)).status_code == 201
        r = api.get(f"{BASE}/stock/", {"empresa": mundo.e1.pk, "orden": "reciente"})
        assert [f["producto_nombre"] for f in r.json()["results"]] == ["Zzz nuevo", "Aaa viejo"]
