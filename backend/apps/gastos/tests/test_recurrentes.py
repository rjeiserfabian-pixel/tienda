"""Gastos recurrentes: plantillas, aviso de cuándo toca y avance al registrar u omitir."""

from datetime import date, timedelta

import pytest

from apps.gastos import recurrentes
from apps.gastos.models import GastoRecurrente
from apps.seguridad.tests.conftest import cliente_de

from .test_api import BASE, HOY, crear, cuerpo_factura

pytestmark = pytest.mark.django_db


def cuerpo(escena, **extra):
    base = {
        "empresa": escena.empresa.pk,
        "nombre": "Alquiler del local",
        "categoria": escena.categorias["ALQUILER"].pk,
        "descripcion": "Alquiler mensual del local de Tarapoto",
        "con_comprobante": True,
        "tipo_comprobante": escena.factura.pk,
        "proveedor": escena.proveedor.pk,
        "importe_estimado": "1500.00",
        "periodicidad": escena.compras.mensual.pk,
        "proxima_fecha": str(HOY + timedelta(days=3)),
        "avisar_dias": 5,
    }
    return {**base, **extra}


def nuevo(usuario, escena, **extra):
    return cliente_de(usuario).post(f"{BASE}/recurrentes/", cuerpo(escena, **extra), format="json")


class TestCrear:
    def test_el_contador_crea_el_alquiler(self, escena):
        r = nuevo("contador", escena)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["nombre"], d["importe_estimado"], d["estado"]) == (
            "Alquiler del local",
            "1500.00",
            "ACTIVO",
        )
        assert (d["periodicidad_nombre"], d["categoria_nombre"]) == ("Mensual", "Alquiler")
        assert (d["dias_para_toca"], d["aviso"]) == (3, "PROXIMO")

    def test_el_importe_es_opcional_y_sin_comprobante_no_lleva_proveedor(self, escena):
        assert nuevo("contador", escena, importe_estimado=None).status_code == 201
        r = nuevo("contador", escena, nombre="Taxi", con_comprobante=False)
        assert r.status_code == 400
        sin = nuevo(
            "contador",
            escena,
            nombre="Taxi",
            con_comprobante=False,
            tipo_comprobante=None,
            proveedor=None,
        )
        assert sin.status_code == 201, sin.content
        assert sin.json()["con_comprobante"] is False

    def test_pide_lo_indispensable(self, escena):
        r = cliente_de("contador").post(
            f"{BASE}/recurrentes/", {"empresa": escena.empresa.pk, "nombre": "X"}, format="json"
        )
        assert r.status_code == 400
        texto = r.content.decode()
        assert all(
            c in texto for c in ("categoria", "descripcion", "periodicidad", "proxima_fecha")
        )

    def test_el_nombre_no_se_repite(self, escena):
        assert nuevo("contador", escena).status_code == 201
        assert nuevo("contador", escena, nombre="ALQUILER DEL LOCAL").status_code == 400

    def test_valida_los_datos(self, escena):
        assert nuevo("contador", escena, nombre="ab").status_code == 400
        assert nuevo("contador", escena, importe_estimado="0.00").status_code == 400
        assert nuevo("contador", escena, avisar_dias=31).status_code == 400
        assert nuevo("contador", escena, categoria=999_999).status_code == 400
        assert (
            nuevo("contador", escena, proxima_fecha=str(HOY + timedelta(days=2000))).status_code
            == 400
        )

    def test_sin_permiso(self, escena):
        assert nuevo("vendedor", escena).status_code == 403
        assert (
            cliente_de("vendedor")
            .get(f"{BASE}/recurrentes/", {"empresa": escena.empresa.pk})
            .status_code
            == 403
        )


class TestListadoYAviso:
    def con_fecha(self, escena, nombre, dias, **extra):
        r = nuevo(
            "contador",
            escena,
            nombre=nombre,
            proxima_fecha=str(HOY + timedelta(days=dias)),
            **extra,
        )
        assert r.status_code == 201, r.content
        return r.json()

    def test_el_aviso_segun_la_fecha(self, escena):
        self.con_fecha(escena, "Atrasado", -2)
        self.con_fecha(escena, "De hoy", 0)
        self.con_fecha(escena, "Pronto", 4)
        self.con_fecha(escena, "Lejos", 20)
        lista = (
            cliente_de("contador")
            .get(f"{BASE}/recurrentes/", {"empresa": escena.empresa.pk})
            .json()
        )
        assert {r["nombre"]: r["aviso"] for r in lista["results"]} == {
            "Atrasado": "VENCIDO", "De hoy": "HOY", "Pronto": "PROXIMO", "Lejos": "AL_DIA",
        }  # fmt: skip
        assert [r["nombre"] for r in lista["results"]][0] == "Atrasado"  # el más urgente primero

    def test_pendientes_son_los_que_ya_tocan_o_estan_por_tocar(self, escena):
        self.con_fecha(escena, "Atrasado", -2)
        self.con_fecha(escena, "Pronto", 4)
        self.con_fecha(escena, "Lejos", 20)
        r = cliente_de("contador").get(
            f"{BASE}/recurrentes/", {"empresa": escena.empresa.pk, "pendientes": "1"}
        )
        assert sorted(x["nombre"] for x in r.json()["results"]) == ["Atrasado", "Pronto"]

    def test_editar_desactivar_y_quitar(self, escena):
        d = self.con_fecha(escena, "Internet", 2)
        url = f"{BASE}/recurrentes/{d['id']}/"
        r = cliente_de("contador").patch(
            url, {"importe_estimado": "129.90", "nombre": "Internet y teléfono"}, format="json"
        )
        assert (r.status_code, r.json()["importe_estimado"], r.json()["nombre"]) == (
            200,
            "129.90",
            "Internet y teléfono",
        )
        assert r.json()["categoria"] == d["categoria"]  # lo no enviado se queda igual
        r = cliente_de("contador").patch(url, {"estado": "INACTIVO"}, format="json")
        assert (r.json()["estado"], r.json()["aviso"]) == ("INACTIVO", "INACTIVO")
        pendientes = cliente_de("contador").get(
            f"{BASE}/recurrentes/", {"empresa": escena.empresa.pk, "pendientes": "1"}
        )
        assert pendientes.json()["count"] == 0
        assert cliente_de("contador").delete(url).status_code == 204
        assert cliente_de("contador").get(url).status_code == 404


class TestRegistrarDesdeLaPlantilla:
    def plantilla(self, escena, dias=0):
        return nuevo("contador", escena, proxima_fecha=str(HOY + timedelta(days=dias))).json()

    def test_registrar_el_gasto_adelanta_la_plantilla_un_ciclo(self, escena):
        p = self.plantilla(escena)
        r = crear(
            "contador",
            cuerpo_factura(escena, recurrente=p["id"], descripcion="Alquiler de noviembre"),
        )
        assert r.status_code == 201, r.content
        assert (r.json()["recurrente"], r.json()["recurrente_nombre"]) == (
            p["id"],
            "Alquiler del local",
        )
        despues = cliente_de("contador").get(f"{BASE}/recurrentes/{p['id']}/").json()
        siguiente = recurrentes.fecha_de_cuota(HOY, escena.compras.mensual, 1)
        assert (despues["proxima_fecha"], despues["ultima_registrada"]) == (
            str(siguiente),
            str(HOY),
        )

    def test_si_el_registro_falla_la_plantilla_no_avanza(self, escena):
        p = self.plantilla(escena)
        malo = cuerpo_factura(escena, recurrente=p["id"], igv="10.00")
        assert crear("contador", malo).status_code == 400
        despues = cliente_de("contador").get(f"{BASE}/recurrentes/{p['id']}/").json()
        assert (despues["proxima_fecha"], despues["ultima_registrada"]) == (
            p["proxima_fecha"],
            None,
        )

    def test_una_plantilla_atrasada_se_registra_ciclo_por_ciclo(self, escena):
        p = self.plantilla(escena, dias=-70)
        crear("contador", cuerpo_factura(escena, recurrente=p["id"]))
        despues = cliente_de("contador").get(f"{BASE}/recurrentes/{p['id']}/").json()
        assert despues["aviso"] == "VENCIDO"  # aún falta otro ciclo atrasado

    def test_una_plantilla_inactiva_o_ajena_no_sirve(self, escena):
        p = self.plantilla(escena)
        cliente_de("contador").patch(
            f"{BASE}/recurrentes/{p['id']}/", {"estado": "INACTIVO"}, format="json"
        )
        r = crear("contador", cuerpo_factura(escena, recurrente=p["id"]))
        assert r.status_code == 400
        assert "inactivo" in r.content.decode()
        assert crear("contador", cuerpo_factura(escena, recurrente=999_999)).status_code == 400

    def test_omitir_salta_el_ciclo_sin_registrar_nada(self, escena):
        p = self.plantilla(escena)
        r = cliente_de("contador").post(f"{BASE}/recurrentes/{p['id']}/omitir/")
        assert r.status_code == 200, r.content
        siguiente = recurrentes.fecha_de_cuota(HOY, escena.compras.mensual, 1)
        assert (r.json()["proxima_fecha"], r.json()["ultima_registrada"]) == (str(siguiente), None)
        assert (
            cliente_de("contador").get(f"{BASE}/", {"empresa": escena.empresa.pk}).json()["count"]
            == 0
        )
        cliente_de("contador").patch(
            f"{BASE}/recurrentes/{p['id']}/", {"estado": "INACTIVO"}, format="json"
        )
        assert (
            cliente_de("contador").post(f"{BASE}/recurrentes/{p['id']}/omitir/").status_code == 409
        )


class TestAvisoEnCaja:
    def test_la_caja_avisa_y_deja_de_avisar_al_registrar(self, escena):
        p = nuevo("contador", escena, proxima_fecha=str(HOY - timedelta(days=1))).json()
        url = "/api/v1/caja/alertas/"
        avisos = {
            a["codigo"]: a
            for a in cliente_de("admin").get(url, {"empresa": escena.empresa.pk}).json()
        }
        aviso = avisos["gastos_recurrentes"]
        assert (aviso["nivel"], aviso["enlace"]) == ("aviso", "/gastos/recurrentes")
        assert "Alquiler del local" in aviso["detalle"]
        crear("contador", cuerpo_factura(escena, recurrente=p["id"]))
        despues = [
            a["codigo"] for a in cliente_de("admin").get(url, {"empresa": escena.empresa.pk}).json()
        ]
        assert "gastos_recurrentes" not in despues


def test_la_siguiente_fecha_respeta_el_fin_de_mes(escena):
    mensual = escena.compras.mensual
    plantilla = GastoRecurrente(proxima_fecha=date(2026, 1, 31), periodicidad=mensual)
    assert recurrentes.siguiente_fecha(plantilla) == date(2026, 2, 28)
