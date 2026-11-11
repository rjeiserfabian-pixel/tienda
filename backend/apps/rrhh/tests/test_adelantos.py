"""RR.HH. (RH4): adelantos de sueldo y préstamos, salida de Caja, cuotas y anulación."""

import itertools
from datetime import date
from decimal import Decimal as D

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.caja import servicios as caja
from apps.caja.models import MovimientoCaja, Origen
from apps.core.tenant import establecer_contexto, limpiar_contexto
from apps.mantenimiento.models import CuentaFinanciera, MedioPago, Personal
from apps.mantenimiento.pagos import sembrar_catalogos_pago
from apps.rrhh import adelantos, catalogos
from apps.rrhh.models import AdelantoPersonal, CuotaAdelanto, RegimenLaboral
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/rrhh"
_claves = itertools.count(1)


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    for org in (e.org_a, e.org_b):
        catalogos.sembrar_catalogos_rrhh(org.pk)
    sembrar_catalogos_pago(e.org_a.pk)
    trabajador = Personal.objects.sin_ambito().create(
        empresa=e.emp_a1,
        tipo_documento="DNI",
        numero_documento="45678912",
        nombres="Rosa",
        apellidos="Quispe",
        area="VENTAS",
    )
    regimen = RegimenLaboral.objects.sin_ambito().get(organizacion=e.org_a, codigo="PEQUENA")
    caja_soles = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1,
        nombre="Caja soles",
        tipo="CAJA",
        moneda="PEN",
        saldo_inicial=D("5000"),
        fecha_saldo_inicial=date(2026, 1, 1),
    )
    equipo = {
        "e": e,
        "trabajador": trabajador,
        "caja": caja_soles,
        "caja_usd": CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre="Caja dólares", tipo="CAJA", moneda="USD"
        ),
        "caja_otra": CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.emp_a2, nombre="Caja otra", tipo="CAJA", moneda="PEN"
        ),
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "rrhh": nuevo_usuario(e.org_a, "rrhh", [e.emp_a1], [("RRHH", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }
    cliente_de("super").post(
        f"{BASE}/trabajadores/{trabajador.pk}/contratos/",
        {
            "regimen": regimen.pk,
            "cargo": "Vendedora",
            "fecha_inicio": "2026-01-02",
            "sueldo": "1500.00",
        },
        format="json",
    )
    return equipo


def entregar(api, equipo, clave=None, **extra):
    cuerpo = {
        "empresa": equipo["e"].emp_a1.pk,
        "personal": equipo["trabajador"].pk,
        "tipo": "ADELANTO",
        "fecha": timezone.localdate().isoformat(),
        "monto": "500.00",
        "cuenta": equipo["caja"].pk,
        **extra,
    }
    clave = clave or f"clave-{next(_claves):08d}"
    return api.post(f"{BASE}/adelantos/", cuerpo, format="json", HTTP_IDEMPOTENCY_KEY=clave)


def saldo(equipo):
    """El saldo de la caja (las lecturas directas necesitan el contexto de la organización)."""
    e = equipo["e"]
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], None)
    try:
        return caja.saldo_de(equipo["caja"])
    finally:
        limpiar_contexto()


class TestEntrega:
    def test_adelanto_de_sueldo_sale_de_caja_y_deja_una_cuota(self, equipo):
        r = entregar(cliente_de("super"), equipo, motivo="Emergencia familiar")
        assert r.status_code == 201, r.content
        cuerpo = r.json()
        assert cuerpo["numero"] == 1 and cuerpo["num_cuotas"] == 1
        assert D(cuerpo["saldo_pendiente"]) == D("500.00")
        assert [c["monto"] for c in cuerpo["cuotas"]] == ["500.00"]
        hoy = timezone.localdate()
        assert cuerpo["cuotas"][0]["periodo"] == hoy.replace(day=1).isoformat()
        assert saldo(equipo) == D("4500.00")
        mov = MovimientoCaja.objects.sin_ambito().get(origen_tipo=Origen.ADELANTO_PERSONAL)
        assert mov.tipo == "EGRESO" and mov.monto == D("500.00")
        assert mov.origen_id == cuerpo["id"]
        assert "Rosa" in mov.glosa

    def test_prestamo_en_cuotas_que_suman_el_monto(self, equipo):
        r = entregar(cliente_de("super"), equipo, tipo="PRESTAMO", monto="100.00", num_cuotas=3)
        assert r.status_code == 201, r.content
        montos = [D(c["monto"]) for c in r.json()["cuotas"]]
        assert montos == [D("33.33"), D("33.33"), D("33.34")]
        assert sum(montos) == D("100.00")
        hoy = timezone.localdate()
        # El préstamo empieza a descontarse el mes siguiente a la entrega.
        primero = adelantos.sumar_meses(hoy.replace(day=1), 1)
        assert r.json()["cuotas"][0]["periodo"] == primero.isoformat()
        assert r.json()["cuotas"][2]["periodo"] == adelantos.sumar_meses(primero, 2).isoformat()

    def test_repartir_no_pierde_centavos(self):
        for monto, n in ((D("100.00"), 7), (D("0.05"), 3), (D("1234.56"), 12)):
            partes = adelantos.repartir(monto, n)
            assert len(partes) == n and sum(partes) == monto
            assert all(p > 0 for p in partes)

    def test_los_numeros_son_correlativos(self, equipo):
        api = cliente_de("super")
        assert entregar(api, equipo, monto="100").json()["numero"] == 1
        assert entregar(api, equipo, monto="100").json()["numero"] == 2


class TestReglas:
    def test_no_puede_pasar_del_sueldo_mensual(self, equipo):
        assert entregar(cliente_de("super"), equipo, monto="1600.00").status_code == 400
        assert AdelantoPersonal.objects.sin_ambito().count() == 0

    def test_lo_pendiente_del_mismo_mes_cuenta(self, equipo):
        api = cliente_de("super")
        assert entregar(api, equipo, monto="1000.00").status_code == 201
        assert entregar(api, equipo, monto="600.00").status_code == 400
        assert entregar(api, equipo, monto="500.00").status_code == 201

    def test_el_prestamo_largo_si_cabe_porque_se_reparte(self, equipo):
        r = entregar(cliente_de("super"), equipo, tipo="PRESTAMO", monto="4800.00", num_cuotas=12)
        assert r.status_code == 201, r.content

    def test_sin_saldo_en_caja_no_se_guarda_nada(self, equipo, settings):
        settings.CAJA_BLOQUEA_SALDO_NEGATIVO = True
        # La caja tiene 5 000: un préstamo de 6 000 (400 por mes cabe en el sueldo) no sale.
        r = entregar(cliente_de("super"), equipo, tipo="PRESTAMO", monto="6000", num_cuotas=15)
        assert r.status_code >= 400
        assert AdelantoPersonal.objects.sin_ambito().count() == 0
        assert CuotaAdelanto.objects.sin_ambito().count() == 0
        assert saldo(equipo) == D("5000.00")

    def test_trabajador_sin_contrato_o_inactivo(self, equipo):
        otro = Personal.objects.sin_ambito().create(
            empresa=equipo["e"].emp_a1,
            tipo_documento="DNI",
            numero_documento="11111111",
            nombres="Luis",
            apellidos="Vega",
            area="VENTAS",
        )
        r = entregar(cliente_de("super"), equipo, personal=otro.pk)
        assert r.status_code == 400
        equipo["trabajador"].estado = "INACTIVO"
        equipo["trabajador"].save()
        assert entregar(cliente_de("super"), equipo).status_code == 400

    def test_la_caja_debe_ser_en_soles_y_de_la_empresa(self, equipo):
        api = cliente_de("super")
        assert entregar(api, equipo, cuenta=equipo["caja_usd"].pk).status_code == 400
        assert entregar(api, equipo, cuenta=equipo["caja_otra"].pk).status_code == 400

    def test_fecha_futura_y_periodo_invalido(self, equipo):
        api = cliente_de("super")
        assert entregar(api, equipo, fecha="2099-01-01").status_code == 400
        hoy = timezone.localdate()
        antes = adelantos.sumar_meses(hoy.replace(day=1), -1).isoformat()
        assert entregar(api, equipo, primer_periodo=antes).status_code == 400
        lejos = adelantos.sumar_meses(hoy.replace(day=1), 30).isoformat()
        assert entregar(api, equipo, primer_periodo=lejos).status_code == 400

    def test_monto_cero_o_con_muchos_decimales(self, equipo):
        api = cliente_de("super")
        assert entregar(api, equipo, monto="0").status_code == 400
        assert entregar(api, equipo, monto="10.555").status_code == 400
        assert entregar(api, equipo, tipo="PRESTAMO", num_cuotas=40).status_code == 400


class TestIdempotencia:
    def test_el_mismo_intento_no_entrega_dos_veces(self, equipo):
        api = cliente_de("super")
        primero = entregar(api, equipo, clave="intento-unico-001")
        segundo = entregar(api, equipo, clave="intento-unico-001")
        assert primero.status_code == segundo.status_code == 201
        assert segundo["Idempotency-Replayed"] == "true"
        assert AdelantoPersonal.objects.sin_ambito().count() == 1
        assert (
            MovimientoCaja.objects.sin_ambito().filter(origen_tipo=Origen.ADELANTO_PERSONAL).count()
            == 1
        )

    def test_sin_clave_se_rechaza(self, equipo):
        r = cliente_de("super").post(
            f"{BASE}/adelantos/",
            {
                "empresa": equipo["e"].emp_a1.pk,
                "personal": equipo["trabajador"].pk,
                "tipo": "ADELANTO",
                "fecha": timezone.localdate().isoformat(),
                "monto": "100",
                "cuenta": equipo["caja"].pk,
            },
            format="json",
        )
        assert r.status_code == 400 or r.status_code == 428
        assert AdelantoPersonal.objects.sin_ambito().count() == 0


class TestAnular:
    def anular(self, api, adelanto_id, motivo="Error de digitación"):
        return api.post(
            f"{BASE}/adelantos/{adelanto_id}/anular/", {"motivo": motivo}, format="json"
        )

    def test_devuelve_el_dinero_y_anula_las_cuotas(self, equipo):
        api = cliente_de("super")
        creado = entregar(api, equipo, tipo="PRESTAMO", monto="300.00", num_cuotas=3).json()
        assert saldo(equipo) == D("4700.00")
        r = self.anular(api, creado["id"])
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "ANULADO"
        assert D(r.json()["saldo_pendiente"]) == D("0")
        assert saldo(equipo) == D("5000.00")
        assert set(CuotaAdelanto.objects.sin_ambito().values_list("estado", flat=True)) == {
            "ANULADA"
        }

    def test_exige_motivo_y_no_se_anula_dos_veces(self, equipo):
        api = cliente_de("super")
        creado = entregar(api, equipo).json()
        assert self.anular(api, creado["id"], "  ").status_code == 400
        assert self.anular(api, creado["id"]).status_code == 200
        assert self.anular(api, creado["id"]).status_code == 400

    def test_si_ya_se_descuenta_una_cuota_no_se_anula(self, equipo):
        api = cliente_de("super")
        creado = entregar(api, equipo, tipo="PRESTAMO", monto="300.00", num_cuotas=3).json()
        CuotaAdelanto.objects.sin_ambito().filter(adelanto_id=creado["id"], numero=1).update(
            estado="DESCONTADA"
        )
        r = self.anular(api, creado["id"])
        assert r.status_code == 400
        assert saldo(equipo) == D("4700.00")

    def test_el_saldo_pendiente_baja_con_lo_descontado(self, equipo):
        creado = entregar(
            cliente_de("super"), equipo, tipo="PRESTAMO", monto="300.00", num_cuotas=3
        ).json()
        CuotaAdelanto.objects.sin_ambito().filter(adelanto_id=creado["id"], numero=1).update(
            estado="DESCONTADA"
        )
        r = cliente_de("super").get(f"{BASE}/adelantos/{creado['id']}/")
        assert D(r.json()["saldo_pendiente"]) == D("200.00")


class TestListadoYPermisos:
    def lista(self, api, equipo, **filtros):
        return api.get(f"{BASE}/adelantos/", {"empresa": equipo["e"].emp_a1.pk, **filtros})

    def test_filtros_y_total_pendiente(self, equipo):
        api = cliente_de("super")
        a = entregar(api, equipo, monto="200").json()
        entregar(api, equipo, tipo="PRESTAMO", monto="300", num_cuotas=3)
        r = self.lista(api, equipo)
        assert r.json()["count"] == 2
        assert D(str(r.json()["pendiente_total"])) == D("500.00")
        assert self.lista(api, equipo, tipo="PRESTAMO").json()["count"] == 1
        assert self.lista(api, equipo, q="quispe").json()["count"] == 2
        assert self.lista(api, equipo, q="zzz").json()["count"] == 0
        api.post(f"{BASE}/adelantos/{a['id']}/anular/", {"motivo": "Prueba"}, format="json")
        assert self.lista(api, equipo, con_saldo="1").json()["count"] == 1
        assert self.lista(api, equipo, estado="ANULADO").json()["count"] == 1

    def test_opciones_solo_trae_cajas_en_soles_de_la_empresa(self, equipo):
        r = cliente_de("super").get(
            f"{BASE}/adelantos/opciones/", {"empresa": equipo["e"].emp_a1.pk}
        )
        assert r.status_code == 200, r.content
        nombres = {c["nombre"] for c in r.json()["cuentas"]}
        assert nombres == {"Caja soles"}
        assert [t["id"] for t in r.json()["trabajadores"]] == [equipo["trabajador"].pk]

    def test_el_contador_ve_pero_no_entrega_ni_anula(self, equipo):
        creado = entregar(cliente_de("super"), equipo).json()
        api = cliente_de("contador")
        assert self.lista(api, equipo).status_code == 200
        assert entregar(api, equipo).status_code == 403
        r = api.post(f"{BASE}/adelantos/{creado['id']}/anular/", {"motivo": "x"}, format="json")
        assert r.status_code == 403

    def test_el_rol_rrhh_puede_todo(self, equipo):
        api = cliente_de("rrhh")
        creado = entregar(api, equipo)
        assert creado.status_code == 201, creado.content
        r = api.post(
            f"{BASE}/adelantos/{creado.json()['id']}/anular/", {"motivo": "x"}, format="json"
        )
        assert r.status_code == 200

    def test_sin_permiso_u_otra_organizacion_no_ven_nada(self, equipo):
        creado = entregar(cliente_de("super"), equipo).json()
        assert self.lista(cliente_de("cajero"), equipo).status_code == 403
        otra = cliente_de("otra_org")
        assert self.lista(otra, equipo).status_code in (400, 403, 404)
        assert otra.get(f"{BASE}/adelantos/{creado['id']}/").status_code in (403, 404)
        assert entregar(otra, equipo).status_code in (400, 403, 404)
        assert AdelantoPersonal.objects.sin_ambito().count() == 1


def test_medio_de_pago_de_la_organizacion(equipo):
    medio = MedioPago.objects.sin_ambito().filter(organizacion=equipo["e"].org_a).first()
    r = entregar(cliente_de("super"), equipo, medio_pago=medio.pk)
    assert r.status_code == 201, r.content
    assert r.json()["medio_pago_nombre"] == medio.nombre
