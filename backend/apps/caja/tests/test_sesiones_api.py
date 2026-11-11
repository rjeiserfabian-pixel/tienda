"""API de sesiones de caja: permisos, abrir, contar, cerrar, reabrir y su efecto en los saldos."""

import itertools

import pytest
from django.core.exceptions import ValidationError

from apps.core.tenant import establecer_contexto
from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja
from apps.mantenimiento.models import ConceptoCaja, CuentaFinanciera
from apps.seguridad.tests.conftest import cliente_de

from .conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    mundo,
    nuevo_usuario,
    rbac,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/caja"
_claves = itertools.count(1)


@pytest.fixture
def datos(mundo, nuevo_usuario):  # noqa: F811
    e = mundo.e
    nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", e.emp_a1)])
    nuevo_usuario(e.org_a, "cajero2", [e.emp_a1], [("CAJERO", e.emp_a1)])
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_conceptos_caja(e.org_a.pk)
    mostrador = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1, nombre="Mostrador 1", tipo="CAJA", rol_caja="MOSTRADOR", exige_sesion=True
    )
    conceptos = {
        c.codigo: c for c in ConceptoCaja.objects.sin_ambito().filter(organizacion=e.org_a)
    }
    return type("Datos", (), {"mundo": mundo, "caja": mostrador, "conceptos": conceptos})


def abrir(usuario, datos, **extra):
    cuerpo = {"empresa": datos.mundo.e1.pk, "cuenta": datos.caja.pk, **extra}
    return cliente_de(usuario).post(f"{BASE}/sesiones/", cuerpo, format="json")


def accion(usuario, sesion_id, nombre, cuerpo):
    return cliente_de(usuario).post(f"{BASE}/sesiones/{sesion_id}/{nombre}/", cuerpo, format="json")


def ingreso(datos, monto="250.00"):
    return cliente_de("admin").post(
        f"{BASE}/movimientos/",
        {
            "empresa": datos.mundo.e1.pk,
            "cuenta": datos.caja.pk,
            "tipo": "INGRESO",
            "concepto": datos.conceptos["APORTE_CAPITAL"].pk,
            "monto": monto,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"sesion-de-prueba-{next(_claves):06d}",
    )


class TestPermisos:
    def test_el_cajero_abre_su_sesion(self, datos):
        r = abrir("cajero", datos)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["estado"], d["numero"], d["cuenta_nombre"], d["moneda"]) == (
            "ABIERTA", 1, "Mostrador 1", "PEN",
        )  # fmt: skip
        assert d["responsable_nombre"] == "cajero"

    def test_el_contador_ve_pero_no_abre(self, datos):
        assert abrir("contador", datos).status_code == 403
        assert abrir("cajero", datos).status_code == 201
        r = cliente_de("contador").get(f"{BASE}/sesiones/?empresa={datos.mundo.e1.pk}")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_un_vendedor_no_ve_las_sesiones(self, datos):
        r = cliente_de("vendedor").get(f"{BASE}/sesiones/?empresa={datos.mundo.e1.pk}")
        assert r.status_code == 403

    def test_el_listado_pide_la_empresa(self, datos):
        assert cliente_de("cajero").get(f"{BASE}/sesiones/").status_code == 400


class TestAbrir:
    def test_no_hay_dos_sesiones_abiertas_en_una_caja(self, datos):
        assert abrir("cajero", datos).status_code == 201
        r = abrir("cajero2", datos)
        assert r.status_code == 409
        assert "ya tiene una sesión abierta" in r.content.decode()

    def test_una_caja_inexistente_se_rechaza(self, datos):
        r = cliente_de("cajero").post(
            f"{BASE}/sesiones/", {"empresa": datos.mundo.e1.pk, "cuenta": 999_999}, format="json"
        )
        assert r.status_code == 400

    def test_el_fondo_sale_de_otra_caja(self, datos):
        principal = CuentaFinanciera.objects.sin_ambito().create(
            empresa=datos.mundo.e1, nombre="Principal", tipo="CAJA", rol_caja="PRINCIPAL"
        )
        r = abrir("cajero", datos, fondo="100.00", desde_cuenta=principal.pk)
        assert r.status_code == 201, r.content
        assert r.json()["fondo_entregado"] == "100.00"
        assert abrir("admin", datos).status_code == 409


class TestMoverEfectivo:
    def test_sin_sesion_el_movimiento_se_rechaza_con_su_codigo(self, datos):
        r = ingreso(datos)
        assert r.status_code == 409
        assert "Abra la sesión" in r.content.decode()

    def test_con_sesion_se_registra_y_queda_ligado(self, datos):
        sesion_id = abrir("cajero", datos).json()["id"]
        r = ingreso(datos)
        assert r.status_code == 201, r.content
        assert r.json()["sesion"] == sesion_id

    def test_el_libro_se_filtra_por_sesion(self, datos):
        primera = abrir("cajero", datos).json()["id"]
        assert ingreso(datos, "100.00").status_code == 201
        assert accion("cajero", primera, "cerrar", {"conteo": {"100": 1}}).status_code == 200
        segunda = abrir("cajero", datos).json()["id"]
        assert ingreso(datos, "40.00").status_code == 201

        def montos(sesion):
            r = cliente_de("admin").get(
                f"{BASE}/movimientos/",
                {"empresa": datos.mundo.e1.pk, "cuenta": datos.caja.pk, "sesion": sesion},
            )
            assert r.status_code == 200, r.content
            return [m["monto"] for m in r.json()["results"]]

        assert montos(segunda) == ["40.00"]
        assert montos(primera) == ["100.00"]


class TestContarYCerrar:
    def abierta_con_250(self, datos):
        sesion_id = abrir("cajero", datos).json()["id"]
        assert ingreso(datos).status_code == 201
        return sesion_id

    def test_el_detalle_trae_lo_esperado_y_los_arqueos(self, datos):
        sesion_id = self.abierta_con_250(datos)
        accion("cajero", sesion_id, "arquear", {"conteo": {"200": 1, "50": 1}})
        d = cliente_de("cajero").get(f"{BASE}/sesiones/{sesion_id}/").json()
        assert d["esperado_actual"] == "250.00"
        [arqueo] = d["arqueos"]
        assert (arqueo["tipo"], arqueo["contado"], arqueo["diferencia"]) == (
            "PARCIAL", "250.00", "0.00",
        )  # fmt: skip

    def test_cerrar_cuadrado(self, datos):
        sesion_id = self.abierta_con_250(datos)
        r = accion("cajero", sesion_id, "cerrar", {"conteo": {"200": 1, "50": 1}})
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["estado"], d["diferencia"], d["contado_cierre"]) == ("CERRADA", "0.00", "250.00")
        assert ingreso(datos).status_code == 409  # la caja volvió a quedar cerrada

    def test_la_diferencia_pide_explicacion(self, datos):
        sesion_id = self.abierta_con_250(datos)
        assert accion("cajero", sesion_id, "cerrar", {"conteo": {"200": 1}}).status_code == 400
        r = accion(
            "cajero", sesion_id, "cerrar", {"conteo": {"200": 1}, "observacion": "Vuelto mal dado"}
        )
        assert r.status_code == 200
        assert r.json()["diferencia"] == "-50.00"

    def test_un_conteo_invalido_se_rechaza(self, datos):
        sesion_id = self.abierta_con_250(datos)
        assert accion("cajero", sesion_id, "arquear", {"conteo": {"7": 1}}).status_code == 400
        assert accion("cajero", sesion_id, "arquear", {"conteo": {"10": -1}}).status_code == 400
        assert accion("cajero", sesion_id, "arquear", {}).status_code == 400

    def test_otro_cajero_no_cierra_la_caja_ajena(self, datos):
        sesion_id = self.abierta_con_250(datos)
        r = accion("cajero2", sesion_id, "cerrar", {"conteo": {"200": 1, "50": 1}})
        assert r.status_code == 409
        # Un supervisor (reapertura) sí puede cerrarla.
        assert (
            accion("admin", sesion_id, "cerrar", {"conteo": {"200": 1, "50": 1}}).status_code == 200
        )


class TestReabrir:
    def cerrada(self, datos):
        sesion_id = abrir("cajero", datos).json()["id"]
        ingreso(datos)
        accion("cajero", sesion_id, "cerrar", {"conteo": {"200": 1, "50": 1}})
        return sesion_id

    def test_solo_un_supervisor_reabre(self, datos):
        sesion_id = self.cerrada(datos)
        assert accion("cajero", sesion_id, "reabrir", {"motivo": "Error"}).status_code == 403
        r = accion("admin", sesion_id, "reabrir", {"motivo": "Faltó registrar un cobro"})
        assert r.status_code == 200, r.content
        assert (r.json()["estado"], r.json()["reaperturas"]) == ("ABIERTA", 1)

    def test_el_motivo_es_obligatorio(self, datos):
        sesion_id = self.cerrada(datos)
        assert accion("admin", sesion_id, "reabrir", {}).status_code == 400


class TestSaldos:
    def test_las_cajas_traen_su_rol_y_la_sesion_abierta(self, datos):
        url = f"{BASE}/saldos/?empresa={datos.mundo.e1.pk}"
        [antes] = cliente_de("admin").get(url).json()["cuentas"]
        assert (antes["rol_caja"], antes["exige_sesion"], antes["sesion"]) == (
            "MOSTRADOR", True, None,
        )  # fmt: skip
        abrir("cajero", datos)
        [despues] = cliente_de("admin").get(url).json()["cuentas"]
        assert despues["sesion"]["responsable_nombre"] == "cajero"


class TestCuentas:
    def test_una_sola_caja_principal_por_tienda(self, datos):
        e1 = datos.mundo.e1
        CuentaFinanciera.objects.sin_ambito().create(
            empresa=e1, nombre="Principal 1", tipo="CAJA", rol_caja="PRINCIPAL"
        )
        otra = CuentaFinanciera(empresa=e1, nombre="Principal 2", tipo="CAJA", rol_caja="PRINCIPAL")
        with pytest.raises(ValidationError, match="ya es la caja principal"):
            otra.full_clean()

    def test_solo_las_cajas_de_efectivo_llevan_rol_y_sesion(self, datos):
        banco = CuentaFinanciera(
            empresa=datos.mundo.e1,
            nombre="BCP",
            tipo="BANCO",
            banco="BCP",
            exige_sesion=True,
        )
        with pytest.raises(ValidationError, match="Solo las cajas de efectivo"):
            banco.full_clean()
