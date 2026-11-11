"""Métodos de pago, periodicidades de cuotas y el cálculo del cronograma."""

from datetime import date
from decimal import Decimal

import pytest

from apps.auditoria import servicios
from apps.mantenimiento import pagos
from apps.mantenimiento.models import MedioPago, Periodicidad
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    pagos.sembrar_catalogos_pago(e.org_a.pk)
    pagos.sembrar_catalogos_pago(e.org_b.pk)
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "tecnico": nuevo_usuario(e.org_a, "tecnico", [e.emp_a1], [("TECNICO", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def _periodicidad(unidad, cantidad):
    return Periodicidad(nombre="x", unidad=unidad, cantidad=cantidad)


SEMANAL = _periodicidad("DIAS", 7)
MENSUAL = _periodicidad("MESES", 1)


# ---------------------------------------------------------------------------
# Cronograma (cálculo puro)
# ---------------------------------------------------------------------------
class TestCronograma:
    def test_el_ejemplo_de_su_sistema_actual(self):
        cuotas = pagos.generar_cronograma(Decimal("1390.99"), 4, date(2026, 10, 29), SEMANAL)
        assert [(c.numero, c.fecha.isoformat(), str(c.monto)) for c in cuotas] == [
            (1, "2026-10-29", "347.75"),
            (2, "2026-11-05", "347.75"),
            (3, "2026-11-12", "347.75"),
            (4, "2026-11-19", "347.74"),  # la última absorbe el redondeo
        ]

    def test_una_sola_cuota_es_el_monto_completo(self):
        (cuota,) = pagos.generar_cronograma(Decimal("100.00"), 1, date(2026, 1, 1), SEMANAL)
        assert (cuota.monto, cuota.fecha) == (Decimal("100.00"), date(2026, 1, 1))

    def test_division_exacta(self):
        cuotas = pagos.generar_cronograma(Decimal("300.00"), 3, date(2026, 1, 1), SEMANAL)
        assert [c.monto for c in cuotas] == [Decimal("100.00")] * 3

    def test_los_centavos_sobrantes_van_a_las_primeras_cuotas(self):
        cuotas = pagos.generar_cronograma(Decimal("100.00"), 3, date(2026, 1, 1), SEMANAL)
        assert [str(c.monto) for c in cuotas] == ["33.34", "33.33", "33.33"]

    def test_montos_chicos_en_muchas_cuotas_no_dejan_cuotas_en_cero_ni_negativas(self):
        # Con redondeo por cuota, 1,00 en 60 dejaba la última en -0,18.
        cuotas = pagos.generar_cronograma(Decimal("1.00"), 60, date(2026, 1, 1), SEMANAL)
        assert sum(c.monto for c in cuotas) == Decimal("1.00")
        assert min(c.monto for c in cuotas) == Decimal("0.01")
        pequeno = pagos.generar_cronograma(Decimal("0.10"), 6, date(2026, 1, 1), SEMANAL)
        assert [str(c.monto) for c in pequeno] == ["0.02", "0.02", "0.02", "0.02", "0.01", "0.01"]

    @pytest.mark.parametrize("monto", ["0.03", "1.00", "99.99", "1000.01", "12345.67", "0.10"])
    @pytest.mark.parametrize("cuotas", [1, 2, 3, 6, 7, 12, 60])
    def test_la_suma_siempre_da_exactamente_el_monto(self, monto, cuotas):
        total = Decimal(monto)
        if total < Decimal("0.01") * cuotas:
            pytest.skip("monto demasiado pequeño para esas cuotas")
        lista = pagos.generar_cronograma(total, cuotas, date(2026, 1, 1), SEMANAL)
        assert sum(c.monto for c in lista) == total
        assert all(c.monto > 0 for c in lista)

    def test_quincenal_son_15_dias(self):
        quincenal = _periodicidad("DIAS", 15)
        fechas = [
            c.fecha
            for c in pagos.generar_cronograma(Decimal("90"), 3, date(2026, 1, 20), quincenal)
        ]
        assert fechas == [date(2026, 1, 20), date(2026, 2, 4), date(2026, 2, 19)]

    def test_mensual_conserva_el_dia(self):
        fechas = [
            c.fecha
            for c in pagos.generar_cronograma(Decimal("300"), 4, date(2026, 10, 15), MENSUAL)
        ]
        assert fechas == [
            date(2026, 10, 15),
            date(2026, 11, 15),
            date(2026, 12, 15),
            date(2027, 1, 15),
        ]

    def test_mensual_a_fin_de_mes_no_se_corre(self):
        fechas = [
            c.fecha for c in pagos.generar_cronograma(Decimal("400"), 4, date(2026, 1, 31), MENSUAL)
        ]
        # Febrero no tiene 31: usa su último día, y marzo vuelve al 31 (no se arrastra el 28).
        assert fechas == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 30),
        ]

    def test_mensual_en_anio_bisiesto(self):
        fechas = [
            c.fecha for c in pagos.generar_cronograma(Decimal("200"), 2, date(2028, 1, 31), MENSUAL)
        ]
        assert fechas[1] == date(2028, 2, 29)

    def test_cada_dos_meses(self):
        bimestral = _periodicidad("MESES", 2)
        fechas = [
            c.fecha
            for c in pagos.generar_cronograma(Decimal("300"), 3, date(2026, 11, 30), bimestral)
        ]
        assert fechas == [date(2026, 11, 30), date(2027, 1, 30), date(2027, 3, 30)]

    @pytest.mark.parametrize(
        ("monto", "cuotas", "mensaje"),
        [
            (Decimal("0"), 3, "mayor que cero"),
            (Decimal("-5.00"), 3, "mayor que cero"),
            (Decimal("10.005"), 3, "2 decimales"),
            (Decimal("NaN"), 3, "2 decimales"),
            (Decimal("100"), 0, "de 1 a 60"),
            (Decimal("100"), 61, "de 1 a 60"),
            (Decimal("0.02"), 5, "muy pequeño"),
            (100.5, 3, "2 decimales"),  # un número flotante no es un monto válido
        ],
    )
    def test_datos_invalidos(self, monto, cuotas, mensaje):
        with pytest.raises(ValueError, match=mensaje):
            pagos.generar_cronograma(monto, cuotas, date(2026, 1, 1), SEMANAL)


# ---------------------------------------------------------------------------
# Carga inicial
# ---------------------------------------------------------------------------
class TestCargaInicial:
    def test_cada_organizacion_trae_lo_basico(self, equipo):
        org = equipo["e"].org_a
        medios = MedioPago.objects.sin_ambito().filter(organizacion=org)
        assert sorted(medios.values_list("nombre", flat=True)) == [
            "Efectivo",
            "Plin",
            "Tarjeta",
            "Transferencia o depósito",
            "Yape",
        ]
        efectivo = medios.get(nombre="Efectivo")
        assert (efectivo.tipo, efectivo.requiere_referencia) == ("EFECTIVO", False)
        assert medios.get(nombre="Yape").requiere_referencia is True
        periodos = {
            p.nombre: (p.unidad, p.cantidad)
            for p in Periodicidad.objects.sin_ambito().filter(organizacion=org)
        }
        assert periodos == {
            "Semanal": ("DIAS", 7),
            "Quincenal": ("DIAS", 15),
            "Mensual": ("MESES", 1),
        }

    def test_volver_a_cargar_no_repite_ni_pisa_lo_editado(self, equipo):
        org = equipo["e"].org_a
        MedioPago.objects.sin_ambito().filter(organizacion=org, nombre="Yape").update(
            nombre="Yape Perú"
        )
        assert pagos.sembrar_catalogos_pago(org.pk) == {
            "medios_pago": 1,
            "periodicidades": 0,
        }  # vuelve «Yape»
        # Segunda vez: ya está todo.
        assert pagos.sembrar_catalogos_pago(org.pk) == {"medios_pago": 0, "periodicidades": 0}

    def test_lo_eliminado_no_se_vuelve_a_crear(self, equipo):
        org = equipo["e"].org_a
        MedioPago.objects.sin_ambito().get(organizacion=org, nombre="Plin").delete()
        Periodicidad.objects.sin_ambito().get(organizacion=org, nombre="Quincenal").delete()
        assert pagos.sembrar_catalogos_pago(org.pk) == {"medios_pago": 0, "periodicidades": 0}

    def test_cada_organizacion_tiene_los_suyos(self, equipo):
        e = equipo["e"]
        assert MedioPago.objects.sin_ambito().filter(organizacion=e.org_b).count() == 5
        assert MedioPago.objects.sin_ambito().filter(organizacion=e.org_a).count() == 5


# ---------------------------------------------------------------------------
# API: métodos de pago
# ---------------------------------------------------------------------------
class TestApiMediosPago:
    def test_lista_filtra_y_busca(self, equipo):
        api = cliente_de("cajero")
        todos = api.get(f"{BASE}/medios-pago/", {"page_size": 50}).json()
        assert todos["count"] == 5
        billeteras = api.get(f"{BASE}/medios-pago/", {"tipo": "BILLETERA"}).json()["results"]
        assert sorted(m["nombre"] for m in billeteras) == ["Plin", "Yape"]
        assert api.get(f"{BASE}/medios-pago/", {"q": "tarje"}).json()["count"] == 1

    def test_el_contador_agrega_los_suyos(self, equipo):
        api = cliente_de("contador")
        r = api.post(
            f"{BASE}/medios-pago/",
            {"nombre": "  Izipay   POS ", "tipo": "TARJETA", "requiere_referencia": True},
            format="json",
        )
        assert r.status_code == 201, r.content
        creado = r.json()
        assert (creado["nombre"], creado["tipo_nombre"], creado["estado"]) == (
            "Izipay POS",
            "Tarjeta",
            "ACTIVO",
        )
        assert api.get(f"{BASE}/medios-pago/", {"page_size": 50}).json()["count"] == 6

    def test_el_nombre_no_se_repite_aunque_cambien_las_mayusculas(self, equipo):
        r = cliente_de("contador").post(f"{BASE}/medios-pago/", {"nombre": "yape"}, format="json")
        assert r.status_code == 400 and "nombre" in str(r.json()).lower()

    def test_edita_y_desactiva(self, equipo):
        api = cliente_de("contador")
        yape = api.get(f"{BASE}/medios-pago/", {"q": "Yape"}).json()["results"][0]
        r = api.patch(
            f"{BASE}/medios-pago/{yape['id']}/",
            {"nombre": "Yape BCP", "estado": "INACTIVO"},
            format="json",
        )
        assert r.status_code == 200
        assert (r.json()["nombre"], r.json()["estado"]) == ("Yape BCP", "INACTIVO")
        activos = api.get(f"{BASE}/medios-pago/", {"estado": "ACTIVO"}).json()["count"]
        assert activos == 4

    @pytest.mark.parametrize("malo", [{"nombre": ""}, {"nombre": "x" * 61}, {"tipo": "CRIPTO"}])
    def test_datos_invalidos(self, equipo, malo):
        r = cliente_de("contador").post(
            f"{BASE}/medios-pago/", {"nombre": "Nuevo", **malo}, format="json"
        )
        assert r.status_code == 400

    def test_permisos(self, equipo):
        cajero = cliente_de("cajero")
        assert cajero.get(f"{BASE}/medios-pago/").status_code == 200
        assert (
            cajero.post(f"{BASE}/medios-pago/", {"nombre": "Otro"}, format="json").status_code
            == 403
        )
        assert cliente_de("tecnico").get(f"{BASE}/medios-pago/").status_code == 403

    def test_solo_el_administrador_elimina(self, equipo):
        yape = cliente_de("cajero").get(f"{BASE}/medios-pago/", {"q": "Yape"}).json()["results"][0]
        assert cliente_de("contador").delete(f"{BASE}/medios-pago/{yape['id']}/").status_code == 403
        assert cliente_de("super").delete(f"{BASE}/medios-pago/{yape['id']}/").status_code == 204

    def test_cada_organizacion_ve_los_suyos(self, equipo):
        otra = cliente_de("otra_org")
        assert otra.get(f"{BASE}/medios-pago/").json()["count"] == 5
        yape_a = MedioPago.objects.sin_ambito().get(organizacion=equipo["e"].org_a, nombre="Yape")
        assert otra.get(f"{BASE}/medios-pago/{yape_a.pk}/").status_code == 404


# ---------------------------------------------------------------------------
# API: periodicidades
# ---------------------------------------------------------------------------
class TestApiPeriodicidades:
    def test_lista_en_orden_de_frecuencia(self, equipo):
        filas = cliente_de("cajero").get(f"{BASE}/periodicidades/").json()["results"]
        assert [(f["nombre"], f["descripcion"]) for f in filas] == [
            ("Semanal", "Cada 7 días"),
            ("Quincenal", "Cada 15 días"),
            ("Mensual", "Cada 1 mes"),
        ]

    def test_crea_una_cada_dos_meses(self, equipo):
        r = cliente_de("contador").post(
            f"{BASE}/periodicidades/",
            {"nombre": "Bimestral", "unidad": "MESES", "cantidad": 2},
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["descripcion"] == "Cada 2 meses"

    @pytest.mark.parametrize(
        "malo",
        [
            {"cantidad": 0},
            {"cantidad": 366},
            {"unidad": "MESES", "cantidad": 13},  # el tope de meses es 12
            {"unidad": "AÑOS"},
            {"nombre": ""},
        ],
    )
    def test_datos_invalidos(self, equipo, malo):
        cuerpo = {"nombre": "Nueva", "unidad": "DIAS", "cantidad": 10, **malo}
        assert (
            cliente_de("contador")
            .post(f"{BASE}/periodicidades/", cuerpo, format="json")
            .status_code
            == 400
        )

    def test_nombre_unico(self, equipo):
        r = cliente_de("contador").post(
            f"{BASE}/periodicidades/", {"nombre": "semanal", "cantidad": 7}, format="json"
        )
        assert r.status_code == 400

    def test_edita_los_dias(self, equipo):
        api = cliente_de("contador")
        semanal = api.get(f"{BASE}/periodicidades/", {"q": "Semanal"}).json()["results"][0]
        r = api.patch(f"{BASE}/periodicidades/{semanal['id']}/", {"cantidad": 10}, format="json")
        assert r.status_code == 200 and r.json()["descripcion"] == "Cada 10 días"

    def test_permisos(self, equipo):
        assert cliente_de("cajero").get(f"{BASE}/periodicidades/").status_code == 200
        assert (
            cliente_de("cajero")
            .post(f"{BASE}/periodicidades/", {"nombre": "X", "cantidad": 3}, format="json")
            .status_code
            == 403
        )
        assert cliente_de("tecnico").get(f"{BASE}/periodicidades/").status_code == 403


# ---------------------------------------------------------------------------
# API: cronograma
# ---------------------------------------------------------------------------
class TestApiCronograma:
    def _pedir(self, usuario="cajero", **extra):
        api = cliente_de(usuario)
        semanal = api.get(f"{BASE}/periodicidades/", {"q": "Semanal"}).json()["results"][0]
        params = {
            "periodicidad": semanal["id"],
            "monto": "1390.99",
            "cuotas": 4,
            "primera_fecha": "2026-10-29",
            **extra,
        }
        return api.get(f"{BASE}/periodicidades/cronograma/", params)

    def test_arma_el_cronograma_de_su_ejemplo(self, equipo):
        r = self._pedir()
        assert r.status_code == 200, r.content
        datos = r.json()
        assert (datos["cuotas"], datos["total"]) == (4, "1390.99")
        assert [(c["fecha"], c["monto"]) for c in datos["cronograma"]] == [
            ("2026-10-29", "347.75"),
            ("2026-11-05", "347.75"),
            ("2026-11-12", "347.75"),
            ("2026-11-19", "347.74"),
        ]
        assert datos["periodicidad"]["nombre"] == "Semanal"

    @pytest.mark.parametrize(
        "malo",
        [
            {"monto": "abc"},
            {"monto": "-5"},
            {"monto": "10.005"},
            {"cuotas": 0},
            {"cuotas": 99},
            {"cuotas": "x"},
            {"primera_fecha": "ayer"},
            {"primera_fecha": "1900-01-01"},
            {"periodicidad": "9999"},
            {"periodicidad": "x"},
        ],
    )
    def test_datos_invalidos(self, equipo, malo):
        assert self._pedir(**malo).status_code == 400

    def test_faltan_datos(self, equipo):
        r = cliente_de("cajero").get(f"{BASE}/periodicidades/cronograma/", {"monto": "100"})
        assert r.status_code == 400

    def test_una_periodicidad_inactiva_no_sirve(self, equipo):
        cajero = cliente_de("cajero")
        semanal = cajero.get(f"{BASE}/periodicidades/", {"q": "Semanal"}).json()["results"][0]
        cliente_de("contador").patch(
            f"{BASE}/periodicidades/{semanal['id']}/", {"estado": "INACTIVO"}, format="json"
        )
        assert self._pedir().status_code == 400

    def test_sin_permiso_de_ver_no_se_calcula(self, equipo):
        assert (
            cliente_de("tecnico")
            .get(f"{BASE}/periodicidades/cronograma/", {"monto": "1"})
            .status_code
            == 403
        )

    def test_no_usa_periodicidades_de_otra_organizacion(self, equipo):
        ajena = Periodicidad.objects.sin_ambito().filter(organizacion=equipo["e"].org_b).first()
        r = cliente_de("cajero").get(
            f"{BASE}/periodicidades/cronograma/",
            {"periodicidad": ajena.pk, "monto": "100", "cuotas": 2, "primera_fecha": "2026-10-29"},
        )
        assert r.status_code == 400
