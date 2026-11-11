"""Mostrador compartido: un cajón físico, contado una sola vez, para las cajas de dos empresas."""

from decimal import Decimal as D

import pytest

from apps.caja import mostrador, servicios, sesiones
from apps.caja.exceptions import MovimientoInvalido, SesionInvalida
from apps.caja.models import ArqueoCaja, MovimientoCaja, Origen, SesionCaja
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import CuentaFinanciera
from apps.organizacion.models import Sucursal
from apps.seguridad.tests.conftest import cliente_de

from .conftest import dec

pytestmark = pytest.mark.django_db

BASE = "/api/v1/caja"


class TestRepartirDiferencia:
    def test_en_proporcion_y_sin_perder_centimos(self):
        assert mostrador.repartir_diferencia(D("3.00"), [D("100"), D("50")]) == [
            D("2.00"),
            D("1.00"),
        ]
        assert mostrador.repartir_diferencia(D("-10.00"), [D("100"), D("50")]) == [
            D("-6.67"),
            D("-3.33"),
        ]
        partes = mostrador.repartir_diferencia(D("0.01"), [D("1"), D("1"), D("1")])
        assert sum(partes) == D("0.01") and sorted(partes) == [D("0"), D("0"), D("0.01")]

    def test_la_suma_siempre_es_exacta(self):
        for dif in ("12.34", "-99.99", "0.07"):
            partes = mostrador.repartir_diferencia(D(dif), [D("33.33"), D("66.67"), D("10")])
            assert sum(partes) == D(dif)

    def test_sin_pesos_positivos_todo_va_a_la_primera(self):
        assert mostrador.repartir_diferencia(D("5.00"), [D("0"), D("0")]) == [D("5.00"), D("0")]
        assert mostrador.repartir_diferencia(D("-5.00"), [D("-3"), D("0")]) == [D("-5.00"), D("0")]

    def test_una_diferencia_en_cero(self):
        assert mostrador.repartir_diferencia(D("0"), [D("10"), D("20")]) == [D("0"), D("0")]


@pytest.fixture
def local(nuevo_usuario, compras, conceptos):
    """Un local compartido (una sucursal por empresa) con una caja de mostrador por empresa."""
    e = compras.entorno
    org = e.e.org_a
    nuevo_usuario(org, "cajera", [e.e1, e.e2], [("CAJERO", e.e1), ("CAJERO", e.e2)])
    nuevo_usuario(org, "cajera_a", [e.e1], [("CAJERO", e.e1)])
    establecer_contexto(org.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)
    suc_a = e.alm1.sucursal
    suc_b = e.alm2.sucursal
    Sucursal.objects.sin_ambito().filter(pk__in=[suc_a.pk, suc_b.pk]).update(
        local_fisico="TARAPOTO"
    )

    def caja(empresa, nombre, sucursal):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=empresa, nombre=nombre, tipo="CAJA", rol_caja="MOSTRADOR", sucursal=sucursal
        )

    return type(
        "Local",
        (),
        {
            "e1": e.e1,
            "e2": e.e2,
            "caja1": caja(e.e1, "Mostrador A", suc_a),
            "caja2": caja(e.e2, "Mostrador B", suc_b),
            "conceptos": conceptos,
            "usuario": e.e.usuario_id,
            "org": org,
        },
    )


def usuario(nombre):
    from apps.seguridad.models import Usuario

    return Usuario.objects.get(username=nombre)


def abrir_ambas(local, quien="cajera"):
    u = usuario(quien)
    a = sesiones.abrir_sesion(empresa=local.e1, cuenta=local.caja1, usuario=u)
    b = sesiones.abrir_sesion(empresa=local.e2, cuenta=local.caja2, usuario=u)
    return a, b


def ingreso(local, empresa, cuenta, monto):
    return servicios.registrar_movimiento(
        empresa=empresa,
        cuenta=cuenta,
        tipo="INGRESO",
        monto=dec(monto),
        concepto=local.conceptos["APORTE_CAPITAL"],
    )


def efectivo(**billetes):
    """``efectivo(b100=1, b50=1)`` → ``{"100": 1, "50": 1}``."""
    return {k[1:]: v for k, v in billetes.items()}


class TestHermanas:
    def test_encuentra_las_cajas_del_mismo_local(self, local):
        a, b = abrir_ambas(local)
        assert [h.pk for h in mostrador.hermanas_de(a)] == [b.pk]
        assert [h.pk for h in mostrador.hermanas_de(b)] == [a.pk]

    def test_sin_local_fisico_o_con_la_hermana_cerrada_no_hay_mostrador_compartido(self, local):
        a, b = abrir_ambas(local)
        sesiones.cerrar_sesion(b, conteo={}, usuario=usuario("cajera"))
        assert mostrador.hermanas_de(a) == []
        Sucursal.objects.sin_ambito().filter(pk=local.caja1.sucursal_id).update(local_fisico="")
        local.caja1.refresh_from_db()
        a.cuenta.refresh_from_db()
        assert mostrador.hermanas_de(SesionCaja.objects.get(pk=a.pk)) == []

    def test_una_caja_sola_no_se_cierra_como_mostrador(self, local):
        u = usuario("cajera")
        a = sesiones.abrir_sesion(empresa=local.e1, cuenta=local.caja1, usuario=u)
        with pytest.raises(SesionInvalida, match="no comparte mostrador"):
            mostrador.cerrar_mostrador(a, conteo={}, usuario=u)


class TestCerrar:
    def test_el_cajon_cuadra_contra_la_suma_de_las_dos_cajas(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        ingreso(local, local.e2, local.caja2, "50")
        cerradas = mostrador.cerrar_mostrador(
            a, conteo=efectivo(b100=1, b50=1), usuario=usuario("cajera")
        )
        assert [s.estado for s in cerradas] == ["CERRADA", "CERRADA"]
        assert [s.diferencia for s in cerradas] == [D("0"), D("0")]
        arqueos = list(ArqueoCaja.objects.sin_ambito().order_by("id"))
        assert len(arqueos) == 2 and arqueos[0].grupo == arqueos[1].grupo
        assert arqueos[0].conteo == {"100": 1, "50": 1} and arqueos[1].conteo == {}
        assert [(x.esperado, x.contado) for x in arqueos] == [
            (D("100"), D("100")),
            (D("50"), D("50")),
        ]

    def test_lo_que_sobra_se_reparte_segun_lo_que_esperaba_cada_caja(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        ingreso(local, local.e2, local.caja2, "50")
        # En el cajón hay 153: sobran 3.
        mostrador.cerrar_mostrador(
            a,
            conteo=efectivo(b100=1, b50=1, b2=1, b1=1),
            usuario=usuario("cajera"),
            observacion="Un cliente dejó cambio de más",
        )
        assert servicios.saldo_de(local.caja1) == D("102.00")
        assert servicios.saldo_de(local.caja2) == D("51.00")
        movimientos = MovimientoCaja.objects.sin_ambito().filter(origen_tipo=Origen.ARQUEO)
        assert sorted(m.monto for m in movimientos) == [D("1.00"), D("2.00")]
        assert all(m.tipo == "INGRESO" for m in movimientos)

    def test_lo_que_falta_tambien_se_reparte_con_centimos_exactos(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        ingreso(local, local.e2, local.caja2, "50")
        # Hay 140: faltan 10.
        mostrador.cerrar_mostrador(
            a,
            conteo=efectivo(b100=1, b20=2),
            usuario=usuario("cajera"),
            observacion="Vuelto mal dado",
        )
        assert servicios.saldo_de(local.caja1) == D("93.33")
        assert servicios.saldo_de(local.caja2) == D("46.67")
        assert servicios.saldo_de(local.caja1) + servicios.saldo_de(local.caja2) == D("140.00")
        sesion = SesionCaja.objects.sin_ambito().get(pk=a.pk)
        assert sesion.diferencia == D("-6.67") and sesion.contado_cierre == D("93.33")

    def test_si_hay_diferencia_hay_que_explicarla_y_no_se_cierra_nada(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        with pytest.raises(MovimientoInvalido, match="Explique la diferencia"):
            mostrador.cerrar_mostrador(a, conteo=efectivo(b50=1), usuario=usuario("cajera"))
        assert {s.estado for s in SesionCaja.objects.sin_ambito()} == {"ABIERTA"}
        assert not ArqueoCaja.objects.sin_ambito().exists()

    def test_solo_el_responsable_o_un_supervisor_cuenta_el_cajon(self, local):
        a, b = abrir_ambas(local)
        with pytest.raises(SesionInvalida, match="solo esa persona"):
            mostrador.cerrar_mostrador(a, conteo={}, usuario=usuario("cajera_a"))
        cerradas = mostrador.cerrar_mostrador(
            a, conteo={}, usuario=usuario("cajera_a"), supervisor=True
        )
        assert len(cerradas) == 2

    def test_se_puede_empezar_otro_turno_despues_de_cerrar(self, local):
        a, b = abrir_ambas(local)
        mostrador.cerrar_mostrador(a, conteo={}, usuario=usuario("cajera"))
        nueva, _ = abrir_ambas(local)
        assert nueva.numero == 2


class TestAbrirJuntas:
    def test_abre_la_caja_y_las_de_las_otras_empresas_del_local(self, local):
        u = usuario("cajera")
        abiertas = mostrador.abrir_mostrador(empresa=local.e1, cuenta=local.caja1, usuario=u)
        assert [s.cuenta_id for s in abiertas] == [local.caja1.pk, local.caja2.pk]
        assert {s.estado for s in SesionCaja.objects.sin_ambito()} == {"ABIERTA"}
        assert {s.responsable_nombre for s in abiertas} == {"cajera"}

    def test_no_reabre_la_que_ya_estaba_abierta(self, local):
        u = usuario("cajera")
        sesiones.abrir_sesion(empresa=local.e2, cuenta=local.caja2, usuario=u)
        abiertas = mostrador.abrir_mostrador(empresa=local.e1, cuenta=local.caja1, usuario=u)
        assert len(abiertas) == 1
        assert SesionCaja.objects.sin_ambito().count() == 2

    def test_por_la_api_exige_permiso_en_las_otras_empresas(self, local):
        r = cliente_de("cajera_a").post(
            f"{BASE}/sesiones/",
            {"empresa": local.e1.pk, "cuenta": local.caja1.pk, "con_hermanas": True},
            format="json",
        )
        assert r.status_code == 403
        assert not SesionCaja.objects.sin_ambito().exists()
        r = cliente_de("cajera").post(
            f"{BASE}/sesiones/",
            {"empresa": local.e1.pk, "cuenta": local.caja1.pk, "con_hermanas": True},
            format="json",
        )
        assert r.status_code == 201, r.content
        assert SesionCaja.objects.sin_ambito().count() == 2


class TestArquear:
    def test_el_conteo_parcial_no_cierra_las_cajas(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        ingreso(local, local.e2, local.caja2, "50")
        arqueos = mostrador.arquear_mostrador(
            a, conteo=efectivo(b100=1, b50=2), usuario=usuario("cajera")
        )
        assert [x.tipo for x in arqueos] == ["PARCIAL", "PARCIAL"]
        assert sum(x.diferencia for x in arqueos) == D("50")
        assert {s.estado for s in SesionCaja.objects.sin_ambito()} == {"ABIERTA"}
        # No se asentó nada en el libro: solo se registró lo contado.
        assert servicios.saldo_de(local.caja1) == D("100")


class TestApi:
    def cuerpo(self, **extra):
        return {"conteo": {"100": 1, "50": 1}, "mostrador": True, **extra}

    def test_el_detalle_muestra_las_cajas_que_se_cuentan_juntas(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        ingreso(local, local.e2, local.caja2, "50")
        d = cliente_de("cajera").get(f"{BASE}/sesiones/{a.pk}/").json()
        assert d["mostrador"]["esperado_total"] == "150.00"
        (hermana,) = d["mostrador"]["hermanas"]
        assert hermana["sesion"] == b.pk and hermana["esperado"] == "50.00"
        assert hermana["cuenta_nombre"] == "Mostrador B"

    def test_el_listado_no_trae_el_mostrador_ni_las_sesiones_cerradas(self, local):
        a, b = abrir_ambas(local)
        mostrador.cerrar_mostrador(a, conteo={}, usuario=usuario("cajera"))
        d = cliente_de("cajera").get(f"{BASE}/sesiones/{a.pk}/").json()
        assert d["mostrador"] is None
        lista = cliente_de("cajera").get(f"{BASE}/sesiones/", {"empresa": local.e1.pk}).json()
        assert lista["results"][0]["mostrador"] is None

    def test_cierra_las_dos_cajas_con_un_solo_conteo(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        ingreso(local, local.e2, local.caja2, "50")
        r = cliente_de("cajera").post(
            f"{BASE}/sesiones/{a.pk}/cerrar/", self.cuerpo(), format="json"
        )
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "CERRADA" and r.json()["diferencia"] == "0.00"
        assert {s.estado for s in SesionCaja.objects.sin_ambito()} == {"CERRADA"}

    def test_quien_no_opera_la_caja_de_la_otra_empresa_no_cierra_el_mostrador(self, local):
        a, b = abrir_ambas(local, quien="cajera_a")
        # cajera_a solo tiene la empresa A: no puede contar ni cerrar la caja de B.
        r = cliente_de("cajera_a").post(
            f"{BASE}/sesiones/{a.pk}/cerrar/", self.cuerpo(), format="json"
        )
        assert r.status_code in (400, 403)
        assert {s.estado for s in SesionCaja.objects.sin_ambito()} == {"ABIERTA"}

    def test_arquear_con_mostrador_deja_las_cajas_abiertas(self, local):
        a, b = abrir_ambas(local)
        ingreso(local, local.e1, local.caja1, "100")
        r = cliente_de("cajera").post(
            f"{BASE}/sesiones/{a.pk}/arquear/", self.cuerpo(), format="json"
        )
        assert r.status_code == 200, r.content
        assert r.json()["tipo"] == "PARCIAL" and r.json()["grupo"]
        assert {s.estado for s in SesionCaja.objects.sin_ambito()} == {"ABIERTA"}
