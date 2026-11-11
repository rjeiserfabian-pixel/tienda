"""API del trabajo sobre la orden: estados, diagnóstico, asignación, avisos y «mis órdenes»."""

import pytest

from apps.mantenimiento.models import Personal
from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico.models import EstadoOrden

pytestmark = pytest.mark.django_db

BASE = "/api/v1/servicio-tecnico/ordenes"
E = EstadoOrden


def _estado(api, orden, estado, motivo=""):
    return api.post(
        f"{BASE}/{orden.pk}/estado/", {"estado": estado, "motivo": motivo}, format="json"
    )


def _otro_tecnico(taller):
    return Personal.objects.create(
        empresa=taller.empresa,
        tipo_documento="DNI",
        numero_documento="42345678",
        nombres="Luz",
        apellidos="Vega",
        area="TECNICO",
    )


class TestCambiarEstado:
    def test_recepcion_mueve_a_cualquier_estado_permitido(self, taller):
        orden = taller.orden(estado=E.PENDIENTE_APROBACION)
        api = cliente_de("admin")
        assert _estado(api, orden, E.NO_APROBADO).status_code == 400  # falta el motivo
        r = _estado(api, orden, E.NO_APROBADO, "El cliente decidió no repararlo")
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "NO_APROBADO"
        assert r.json()["historial"][-1]["motivo"] == "El cliente decidió no repararlo"
        assert r.json()["historial"][-1]["usuario_nombre"]

    def test_el_tecnico_mueve_solo_los_estados_tecnicos(self, taller):
        orden = taller.orden(estado=E.PENDIENTE_DIAGNOSTICO)
        api = cliente_de("tecnico")
        r = _estado(api, orden, E.EN_DIAGNOSTICO)
        assert (r.status_code, r.json()["estado"]) == (200, "EN_DIAGNOSTICO")
        assert _estado(api, orden, E.NO_APROBADO, "Cancelar").status_code == 409

    def test_el_tecnico_no_entrega(self, taller):
        orden = taller.orden(estado=E.LISTO_ENTREGA)
        assert _estado(cliente_de("tecnico"), orden, E.ENTREGADO).status_code == 403

    def test_entregado_no_se_alcanza_con_el_cambio_de_estado(self, taller):
        orden = taller.orden(estado=E.LISTO_ENTREGA)
        assert _estado(cliente_de("admin"), orden, E.ENTREGADO).status_code == 409

    def test_un_paso_que_no_existe_se_rechaza(self, taller):
        orden = taller.orden()
        assert _estado(cliente_de("admin"), orden, E.ENTREGADO).status_code == 409
        r = cliente_de("admin").post(
            f"{BASE}/{orden.pk}/estado/", {"estado": "INVENTADO"}, format="json"
        )
        assert r.status_code == 400

    def test_el_tecnico_no_toca_la_orden_de_otro(self, taller):
        ajena = taller.orden(tecnico=_otro_tecnico(taller), estado=E.PENDIENTE_DIAGNOSTICO)
        assert _estado(cliente_de("tecnico"), ajena, E.EN_DIAGNOSTICO).status_code == 404

    def test_quien_solo_ve_no_cambia_nada(self, taller):
        orden = taller.orden(estado=E.PENDIENTE_DIAGNOSTICO)
        assert _estado(cliente_de("vendedor"), orden, E.EN_DIAGNOSTICO).status_code == 403

    def test_la_ficha_ofrece_solo_los_pasos_de_cada_quien(self, taller):
        orden = taller.orden(estado=E.EN_REPARACION)
        listo = taller.orden(estado=E.LISTO_ENTREGA)
        listo_del_tecnico = taller.orden(estado=E.LISTO_ENTREGA)
        del_tecnico = cliente_de("tecnico").get(f"{BASE}/{orden.pk}/").json()
        estados = {d["estado"] for d in del_tecnico["destinos"]}
        assert estados == {"EN_PRUEBAS", "PENDIENTE_REPUESTO", "SIN_SOLUCION"}
        assert {d["estado"]: d["pide_motivo"] for d in del_tecnico["destinos"]}["SIN_SOLUCION"]
        de_recepcion = cliente_de("admin").get(f"{BASE}/{listo.pk}/").json()
        assert {d["estado"] for d in de_recepcion["destinos"]} == {"ABANDONADO"}
        del_tecnico = cliente_de("tecnico").get(f"{BASE}/{listo_del_tecnico.pk}/").json()
        assert del_tecnico["destinos"] == []
        assert cliente_de("vendedor").get(f"{BASE}/{orden.pk}/").json()["destinos"] == []


class TestDiagnostico:
    def test_el_tecnico_diagnostica_su_orden(self, taller):
        orden = taller.orden(estado=E.EN_DIAGNOSTICO)
        servicio = taller.tipo_servicio("REPARACION_HW").pk
        api = cliente_de("tecnico")
        r = api.post(
            f"{BASE}/{orden.pk}/diagnostico/",
            {
                "diagnostico": "Fuente de poder quemada",
                "trabajos_a_realizar": "Cambiar la fuente",
                "horas_estimadas": "2.0",
                "nota_cliente": "Se cambia una pieza",
                "tipo_servicio": servicio,
            },
            format="json",
        )
        assert r.status_code == 200, r.content
        datos = r.json()
        assert datos["diagnostico"] == "Fuente de poder quemada"
        assert datos["tipo_servicio_categoria"] == "REPARACION"
        assert datos["permite"]["diagnosticar"] is True
        assert _estado(api, orden, E.DIAGNOSTICADO).status_code == 200

    def test_dar_por_realizado_sin_escribirlo_se_rechaza(self, taller):
        orden = taller.orden(estado=E.EN_DIAGNOSTICO)
        r = _estado(cliente_de("tecnico"), orden, E.DIAGNOSTICADO)
        assert r.status_code == 400

    def test_no_diagnostica_quien_no_es_tecnico_ni_la_orden_ajena(self, taller):
        orden = taller.orden()
        ajena = taller.orden(tecnico=_otro_tecnico(taller))
        cuerpo = {"diagnostico": "Algo que no debería guardarse"}
        assert (
            cliente_de("vendedor")
            .post(f"{BASE}/{orden.pk}/diagnostico/", cuerpo, format="json")
            .status_code
            == 403
        )
        assert (
            cliente_de("tecnico")
            .post(f"{BASE}/{ajena.pk}/diagnostico/", cuerpo, format="json")
            .status_code
            == 404
        )

    def test_datos_invalidos(self, taller):
        orden = taller.orden()
        api = cliente_de("tecnico")
        assert (
            api.post(
                f"{BASE}/{orden.pk}/diagnostico/", {"horas_estimadas": "-3"}, format="json"
            ).status_code
            == 400
        )
        assert (
            api.post(
                f"{BASE}/{orden.pk}/diagnostico/", {"tipo_servicio": 99999}, format="json"
            ).status_code
            == 400
        )


class TestAsignarYAvisar:
    def test_recepcion_reasigna_el_tecnico(self, taller):
        otro = _otro_tecnico(taller)
        orden = taller.orden()
        api = cliente_de("admin")
        r = api.post(f"{BASE}/{orden.pk}/asignar/", {"tecnico": otro.pk}, format="json")
        assert (r.status_code, r.json()["tecnico_nombre"]) == (200, "Luz Vega")
        sin = api.post(f"{BASE}/{orden.pk}/asignar/", {"tecnico": None}, format="json")
        assert sin.json()["tecnico_nombre"] == ""

    def test_tecnico_de_otra_empresa_o_inexistente(self, taller):
        orden = taller.orden()
        api = cliente_de("admin")
        assert (
            api.post(f"{BASE}/{orden.pk}/asignar/", {"tecnico": 99999}, format="json").status_code
            == 400
        )

    def test_el_tecnico_no_asigna(self, taller):
        orden = taller.orden()
        r = cliente_de("tecnico").post(
            f"{BASE}/{orden.pk}/asignar/", {"tecnico": None}, format="json"
        )
        assert r.status_code == 403

    def test_registra_un_aviso_manual(self, taller):
        orden = taller.orden(estado=E.LISTO_ENTREGA)
        api = cliente_de("admin")
        r = api.post(
            f"{BASE}/{orden.pk}/avisos/",
            {"medio": "WHATSAPP", "mensaje": "Se le avisó que ya puede recogerlo"},
            format="json",
        )
        assert r.status_code == 200, r.content
        aviso = r.json()["avisos"][0]
        assert (aviso["medio"], aviso["medio_nombre"]) == ("WHATSAPP", "WhatsApp")
        assert aviso["usuario_nombre"]
        assert r.json()["permite"]["avisar"] is True

    def test_aviso_invalido_o_sin_permiso(self, taller):
        orden = taller.orden()
        cuerpo = {"medio": "WHATSAPP", "mensaje": "Se le avisó"}
        assert (
            cliente_de("admin")
            .post(f"{BASE}/{orden.pk}/avisos/", {"medio": "X", "mensaje": "hola"}, format="json")
            .status_code
            == 400
        )
        assert (
            cliente_de("tecnico")
            .post(f"{BASE}/{orden.pk}/avisos/", cuerpo, format="json")
            .status_code
            == 403
        )
        assert (
            cliente_de("vendedor")
            .post(f"{BASE}/{orden.pk}/avisos/", cuerpo, format="json")
            .status_code
            == 403
        )


class TestMisOrdenes:
    def test_filtra_las_del_usuario(self, taller):
        suya = taller.orden()
        taller.orden(tecnico=_otro_tecnico(taller))
        taller.orden(tecnico=None)
        filtro = {"empresa": taller.empresa.pk, "mias": "1"}
        r = cliente_de("tecnico").get(f"{BASE}/", filtro)
        assert [o["id"] for o in r.json()["results"]] == [suya.pk]
        # Quien ve todas las de la empresa, con «mias» ve solo las que le tocan a él.
        assert cliente_de("admin").get(f"{BASE}/", filtro).json()["count"] == 0
        assert (
            cliente_de("admin").get(f"{BASE}/", {"empresa": taller.empresa.pk}).json()["count"] == 3
        )
