"""Transporte (empresas, conductores, vehículos), ubigeos del INEI y ubigeo en direcciones."""

import pytest

from apps.auditoria import servicios
from apps.mantenimiento.models import Conductor, EmpresaTransporte, Ubigeo, Vehiculo
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"
RUC_UNO, RUC_DOS = "20100000017", "20100070970"  # RUC con dígito verificador válido


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1], [("SUPERADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "almacen": nuevo_usuario(e.org_a, "almacen", [e.emp_a1], [("ALMACENERO", e.emp_a1)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def texto(respuesta) -> str:
    return str(respuesta.json()).lower()


class TestUbigeos:
    def test_la_lista_oficial_esta_cargada(self, equipo):
        assert Ubigeo.objects.count() == 1893
        assert Ubigeo.objects.values("departamento").distinct().count() == 25
        tarapoto = Ubigeo.objects.get(codigo="220901")
        assert tarapoto.nombre_completo == "SAN MARTÍN - SAN MARTÍN - TARAPOTO"

    def test_busca_sin_tildes_ni_mayusculas_y_por_varias_palabras(self, equipo):
        api = cliente_de("vendedor")
        for q in ("tarapoto", "TARAPOTO", "san martin tarapoto", "san martín tarapoto", "220901"):
            r = api.get(f"{BASE}/ubigeos/", {"q": q})
            assert r.status_code == 200, r.content
            codigos = [u["codigo"] for u in r.json()["results"]]
            assert "220901" in codigos, q
        solo = api.get(f"{BASE}/ubigeos/", {"q": "san martin tarapoto"}).json()
        assert solo["count"] == 1 and solo["results"][0]["nombre_completo"].endswith("TARAPOTO")
        assert api.get(f"{BASE}/ubigeos/", {"q": "zzzz"}).json()["count"] == 0

    def test_por_codigo_exacto_y_con_limite_de_palabras(self, equipo):
        api = cliente_de("cajero")  # cualquiera con sesión: es una lista de referencia
        exacto = api.get(f"{BASE}/ubigeos/", {"codigo": "150101"}).json()
        assert exacto["count"] == 1 and exacto["results"][0]["distrito"] == "Lima"
        r = api.get(f"{BASE}/ubigeos/", {"q": "a b c d e f g"})
        assert r.status_code == 400

    def test_exige_sesion(self, equipo):
        from rest_framework.test import APIClient

        assert APIClient().get(f"{BASE}/ubigeos/", {"q": "lima"}).status_code in (401, 403)

    def test_se_pagina(self, equipo):
        r = cliente_de("vendedor").get(f"{BASE}/ubigeos/", {"q": "lima", "page_size": 10}).json()
        assert len(r["results"]) == 10 and r["count"] > 10


class TestEmpresasDeTransporte:
    def crear(self, api, ruc=RUC_UNO, **extra):
        return api.post(
            f"{BASE}/empresas-transporte/",
            {"nombre": "Transportes  El Rápido SAC", "ruc": ruc, **extra},
            format="json",
        )

    def test_el_almacenero_crea_y_edita(self, equipo):
        api = cliente_de("almacen")
        r = self.crear(api, registro_mtc="mtc 0012", certificado_inspeccion="cert-99")
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["nombre"], d["ruc"], d["registro_mtc"], d["certificado_inspeccion"]) == (
            "Transportes El Rápido SAC",
            RUC_UNO,
            "MTC 0012",
            "CERT-99",
        )
        edit = api.patch(
            f"{BASE}/empresas-transporte/{d['id']}/", {"nombre": "Rápido"}, format="json"
        )
        assert (edit.status_code, edit.json()["nombre"]) == (200, "Rápido")

    def test_el_ruc_se_valida_y_no_se_repite(self, equipo):
        api = cliente_de("almacen")
        assert self.crear(api, ruc="20512345678").status_code == 400  # dígito verificador malo
        assert self.crear(api, ruc="123").status_code == 400
        assert self.crear(api).status_code == 201
        repetido = self.crear(api, ruc="20-100000017")
        assert repetido.status_code in (400, 409) and "ruc" in texto(repetido)
        assert EmpresaTransporte.objects.sin_ambito().count() == 1

    def test_busqueda_y_aislamiento_por_organizacion(self, equipo):
        self.crear(cliente_de("almacen"))
        self.crear(cliente_de("otra_org"), ruc=RUC_DOS)
        lista = cliente_de("vendedor").get(f"{BASE}/empresas-transporte/", {"q": "rápido"}).json()
        assert [e["ruc"] for e in lista["results"]] == [RUC_UNO]
        otra = cliente_de("otra_org").get(f"{BASE}/empresas-transporte/").json()
        assert [e["ruc"] for e in otra["results"]] == [RUC_DOS]
        propia = EmpresaTransporte.objects.sin_ambito().get(ruc=RUC_UNO)
        assert (
            cliente_de("otra_org").get(f"{BASE}/empresas-transporte/{propia.pk}/").status_code
            == 404
        )

    def test_permisos(self, equipo):
        assert self.crear(cliente_de("cajero")).status_code == 403
        assert cliente_de("cajero").get(f"{BASE}/empresas-transporte/").status_code == 403
        creada = self.crear(cliente_de("vendedor"))  # el vendedor puede registrarla...
        assert creada.status_code == 201
        url = f"{BASE}/empresas-transporte/{creada.json()['id']}/"
        assert cliente_de("vendedor").patch(url, {"nombre": "X"}, format="json").status_code == 403
        assert cliente_de("almacen").delete(url).status_code == 403  # ...pero no eliminarla
        assert cliente_de("super").delete(url).status_code == 204


class TestConductores:
    def crear(self, api, numero="43512345", **extra):
        return api.post(
            f"{BASE}/conductores/",
            {
                "nombre": "Luis  Soto Ramírez",
                "tipo_documento": "DNI",
                "numero_documento": numero,
                **extra,
            },
            format="json",
        )

    def test_crea_con_su_dni_y_licencia(self, equipo):
        r = self.crear(cliente_de("vendedor"), licencia="q 4312345")
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["nombre"], d["numero_documento"], d["licencia"]) == (
            "Luis Soto Ramírez",
            "43512345",
            "Q 4312345",
        )

    def test_valida_el_dni_y_no_se_repite(self, equipo):
        api = cliente_de("almacen")
        assert self.crear(api, numero="1234").status_code == 400
        assert self.crear(api).status_code == 201
        repetido = self.crear(api)
        assert repetido.status_code in (400, 409) and "documento" in texto(repetido)
        assert Conductor.objects.sin_ambito().count() == 1

    def test_permisos(self, equipo):
        assert self.crear(cliente_de("cajero")).status_code == 403


class TestVehiculos:
    def crear(self, api, placa="abc-123", **extra):
        return api.post(
            f"{BASE}/vehiculos/",
            {"placa": placa, "marca": "Yamaha", "modelo": "XTZ150", **extra},
            format="json",
        )

    def test_la_placa_se_normaliza_y_se_describe(self, equipo):
        r = self.crear(cliente_de("vendedor"))
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["placa"], d["descripcion"]) == ("ABC123", "ABC123 · Yamaha XTZ150")

    def test_valida_la_placa_y_no_se_repite(self, equipo):
        api = cliente_de("vendedor")
        assert self.crear(api, placa="A1").status_code == 400
        assert self.crear(api, placa="ab#123").status_code == 400
        assert self.crear(api).status_code == 201
        repetido = self.crear(api, placa="ABC 123")
        assert repetido.status_code in (400, 409) and "placa" in texto(repetido)
        assert Vehiculo.objects.sin_ambito().count() == 1

    def test_lo_eliminado_libera_la_placa(self, equipo):
        creado = self.crear(cliente_de("super")).json()
        assert cliente_de("super").delete(f"{BASE}/vehiculos/{creado['id']}/").status_code == 204
        assert self.crear(cliente_de("super")).status_code == 201


class TestUbigeoEnLasDirecciones:
    def cliente(self, api, **extra):
        return api.post(
            f"{BASE}/clientes/",
            {
                "tipo_documento": "DNI",
                "numero_documento": "71234567",
                "nombre": "Ana Ruiz",
                **extra,
            },
            format="json",
        )

    def test_el_cliente_guarda_su_ubigeo_y_se_valida(self, equipo):
        api = cliente_de("vendedor")
        r = self.cliente(api, direccion="Jr. Grau 242", ubigeo="220901")
        assert r.status_code == 201, r.content
        assert r.json()["ubigeo"] == "220901"
        malo = self.cliente(api, numero_documento="71234568", ubigeo="999999")
        assert malo.status_code == 400 and "ubigeo" in texto(malo)
        # Opcional: sin ubigeo se guarda vacío y se puede quitar.
        sin = self.cliente(api, numero_documento="71234569")
        assert sin.status_code == 201 and sin.json()["ubigeo"] == ""
        quitado = api.patch(f"{BASE}/clientes/{r.json()['id']}/", {"ubigeo": ""}, format="json")
        assert quitado.status_code == 200 and quitado.json()["ubigeo"] == ""

    def test_el_proveedor_y_el_almacen_tambien(self, equipo):
        super_ = cliente_de("super")
        p = super_.post(
            f"{BASE}/proveedores/",
            {
                "tipo_documento": "RUC",
                "numero_documento": RUC_UNO,
                "nombre": "Distribuidora SAC",
                "ubigeo": "150101",
            },
            format="json",
        )
        assert p.status_code == 201, p.content
        assert p.json()["ubigeo"] == "150101"
        sucursal = Sucursal.objects.sin_ambito().create(
            empresa=equipo["e"].emp_a1, nombre="Principal", codigo="001"
        )
        a = super_.post(
            f"{BASE}/almacenes/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "codigo": "alm-01",
                "nombre": "Principal",
                "sucursal": sucursal.pk,
                "ubigeo": "220901",
            },
            format="json",
        )
        assert a.status_code == 201, a.content
        assert a.json()["ubigeo"] == "220901"
        mal = super_.patch(f"{BASE}/almacenes/{a.json()['id']}/", {"ubigeo": "12"}, format="json")
        assert mal.status_code == 400

    def test_la_sucursal_guarda_su_ubigeo(self, equipo):
        super_ = cliente_de("super")
        r = super_.post(
            "/api/v1/organizacion/sucursales/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "nombre": "Tarapoto",
                "codigo": "TAR",
                "ubigeo": "220901",
            },
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["ubigeo"] == "220901"
        editada = super_.patch(
            f"/api/v1/organizacion/sucursales/{r.json()['id']}/",
            {"ubigeo": "150101"},
            format="json",
        )
        assert editada.status_code == 200 and editada.json()["ubigeo"] == "150101"
        malo = super_.patch(
            f"/api/v1/organizacion/sucursales/{r.json()['id']}/",
            {"ubigeo": "000000"},
            format="json",
        )
        assert malo.status_code == 400
