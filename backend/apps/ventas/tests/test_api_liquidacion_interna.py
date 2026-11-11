"""API de la liquidación interna y su paso por el cierre del mostrador compartido."""

import itertools
from decimal import Decimal as D

import pytest

from apps.caja import sesiones
from apps.caja.models import SesionCaja
from apps.caja.servicios import saldo_de
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import CuentaFinanciera
from apps.organizacion.models import Sucursal
from apps.seguridad.models import Usuario
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas.models import DeudaInterna, LiquidacionInterna

from .test_venta_interna import vender_interna

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas/liquidaciones-internas"
CAJA = "/api/v1/caja/sesiones"
_claves = itertools.count(1)


@pytest.fixture
def dueno(tienda, nuevo_usuario):
    return nuevo_usuario(
        tienda.a.organizacion, "dueno", [tienda.a, tienda.b], [("SUPERADMIN", None)]
    )


@pytest.fixture
def local(tienda, nuevo_usuario):
    """Un local compartido: una sucursal y una caja de mostrador por empresa, y una cajera."""
    sucursal_de = {e.pk: tienda.almacen(e).sucursal for e in (tienda.a, tienda.b)}
    Sucursal.objects.sin_ambito().filter(pk__in=[s.pk for s in sucursal_de.values()]).update(
        local_fisico="TARAPOTO"
    )
    for e in (tienda.a, tienda.b):
        CuentaFinanciera.objects.sin_ambito().filter(pk=tienda.cajas[e.pk].pk).update(
            sucursal=sucursal_de[e.pk], rol_caja="MOSTRADOR"
        )
    nuevo_usuario(
        tienda.a.organizacion,
        "cajera",
        [tienda.a, tienda.b],
        [("CAJERO", tienda.a), ("CAJERO", tienda.b)],
    )
    # Se vuelve a leer: la sucursal en memoria no sabe todavía que ahora comparte local.
    sucursal_a = Sucursal.objects.sin_ambito().get(pk=sucursal_de[tienda.a.pk].pk)
    return type("Local", (), {"sucursal_a": sucursal_a})


def saldo(tienda, empresa):
    """El saldo de la caja de la empresa (la API deja sin contexto la sesión de la prueba)."""
    establecer_contexto(
        tienda.a.organizacion_id, [tienda.a.pk, tienda.b.pk], tienda.entorno.e.usuario_id
    )
    return saldo_de(tienda.cajas[empresa.pk])


def vender_en_el_local(tienda, mixto, local, cantidad_b=2, cobro="354.00"):
    de_a, de_b = mixto
    return vender_interna(
        tienda,
        [tienda.linea(de_a, 1), tienda.linea(de_b, cantidad_b, empresa=tienda.b)],
        [tienda.cobro(tienda.efectivo, cobro)],
        sucursal=local.sucursal_a,
    )


def abrir_ambas(tienda):
    cajera = Usuario.objects.get(username="cajera")
    return [
        sesiones.abrir_sesion(
            empresa=e,
            cuenta=CuentaFinanciera.objects.sin_ambito().get(pk=tienda.cajas[e.pk].pk),
            usuario=cajera,
        )
        for e in (tienda.a, tienda.b)
    ]


def liquidar(usuario, tienda, **extra):
    cuerpo = {
        "pagadora": tienda.a.pk,
        "receptora": tienda.b.pk,
        "local": "TARAPOTO",
        **extra,
    }
    return cliente_de(usuario).post(
        f"{BASE}/?empresa={tienda.a.pk}",
        cuerpo,
        format="json",
        HTTP_IDEMPOTENCY_KEY=extra.pop("llave", f"liquidar-interna-{next(_claves):05d}"),
    )


class TestPendientesYLiquidar:
    def test_muestra_lo_pendiente_con_las_cuentas_propuestas(self, tienda, dueno, mixto, local):
        vender_en_el_local(tienda, mixto, local)

        r = cliente_de("dueno").get(f"{BASE}/pendientes/", {"empresa": tienda.a.pk})

        assert r.status_code == 200, r.content
        (grupo,) = r.json()
        assert (grupo["pagadora"], grupo["receptora"], grupo["monto"]) == (
            tienda.a.pk,
            tienda.b.pk,
            "60.00",
        )
        assert grupo["local"] == "TARAPOTO"
        assert grupo["cuenta_origen"]["id"] == tienda.cajas[tienda.a.pk].pk
        assert grupo["cuenta_destino"]["id"] == tienda.cajas[tienda.b.pk].pk
        assert [p["motivo"] for p in grupo["partidas"]] == ["VENTA"]
        assert "costo" not in str(grupo["partidas"]).lower()

    def test_liquida_con_una_transferencia_y_queda_en_el_historial(
        self, tienda, dueno, mixto, local
    ):
        vender_en_el_local(tienda, mixto, local)

        r = liquidar("dueno", tienda, observacion="Cierre del día")

        assert r.status_code == 201, r.content
        datos = r.json()
        assert datos["monto"] == "60.00" and datos["numero"] == 1
        assert datos["paga"] and datos["recibe"] and datos["desde"] and datos["hacia"]
        assert [p["motivo"] for p in datos["partidas"]] == ["VENTA"]
        assert saldo(tienda, tienda.b) == D("60.00")
        lista = cliente_de("dueno").get(f"{BASE}/", {"empresa": tienda.b.pk}).json()
        assert [x["id"] for x in lista["results"]] == [datos["id"]]
        pendiente = cliente_de("dueno").get(f"{BASE}/pendientes/", {"empresa": tienda.a.pk}).json()
        assert pendiente == []

    def test_un_reintento_con_la_misma_clave_no_liquida_dos_veces(
        self, tienda, dueno, mixto, local
    ):
        vender_en_el_local(tienda, mixto, local)
        cuerpo = {"pagadora": tienda.a.pk, "receptora": tienda.b.pk, "local": "TARAPOTO"}

        def intento():
            return cliente_de("dueno").post(
                f"{BASE}/?empresa={tienda.a.pk}",
                cuerpo,
                format="json",
                HTTP_IDEMPOTENCY_KEY="liquidar-interna-repetida",
            )

        primera, segunda = intento(), intento()

        assert primera.status_code == 201 and segunda.status_code == 201
        assert segunda["Idempotency-Replayed"] == "true"
        assert LiquidacionInterna.objects.sin_ambito().count() == 1

    def test_anular_la_liquidacion_deja_las_partidas_pendientes_otra_vez(
        self, tienda, dueno, mixto, local
    ):
        vender_en_el_local(tienda, mixto, local)
        liquidacion = liquidar("dueno", tienda).json()

        r = cliente_de("dueno").post(
            f"{BASE}/{liquidacion['id']}/anular/",
            {"motivo": "Se hizo por error"},
            format="json",
        )

        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "ANULADO"
        assert saldo(tienda, tienda.b) == D("0")
        pendiente = cliente_de("dueno").get(f"{BASE}/pendientes/", {"empresa": tienda.a.pk}).json()
        assert pendiente[0]["monto"] == "60.00"

    def test_el_permiso_se_exige_en_las_dos_empresas(
        self, tienda, dueno, mixto, local, nuevo_usuario
    ):
        vender_en_el_local(tienda, mixto, local)
        nuevo_usuario(
            tienda.a.organizacion, "jefe_de_a", [tienda.a, tienda.b], [("SUPERADMIN", tienda.a)]
        )

        for usuario in ("vendedor", "jefe_de_a"):
            assert liquidar(usuario, tienda).status_code == 403, usuario
        assert not LiquidacionInterna.objects.sin_ambito().exists()

    def test_la_cajera_ve_y_puede_liquidar_porque_cierra_la_caja(self, tienda, mixto, local):
        vender_en_el_local(tienda, mixto, local)

        r = cliente_de("cajera").get(f"{BASE}/pendientes/", {"empresa": tienda.a.pk})

        assert r.status_code == 200 and len(r.json()) == 1


class TestCierreDelMostrador:
    def cerrar(self, usuario, sesion_id, conteo, **extra):
        return cliente_de(usuario).post(
            f"{CAJA}/{sesion_id}/cerrar/",
            {"conteo": conteo, "mostrador": True, **extra},
            format="json",
        )

    def test_no_deja_cerrar_con_ventas_internas_sin_liquidar(self, tienda, mixto, local):
        abierta_a, _ = abrir_ambas(tienda)
        vender_en_el_local(tienda, mixto, local)

        r = self.cerrar("cajera", abierta_a.pk, {"200": 1, "100": 1, "50": 1, "2": 2})

        assert r.status_code == 409, r.content
        assert r.json()["error"]["codigo"] == "liquidacion_interna_pendiente"
        assert r.json()["error"]["detalle"][0]["monto"] == "60.00"
        assert SesionCaja.objects.sin_ambito().filter(estado="ABIERTA").count() == 2

    def test_liquida_y_cierra_en_una_sola_operacion_con_un_solo_conteo(self, tienda, mixto, local):
        abierta_a, _ = abrir_ambas(tienda)
        vender_en_el_local(tienda, mixto, local)

        r = self.cerrar(
            "cajera", abierta_a.pk, {"200": 1, "100": 1, "50": 1, "2": 2}, liquidar_interna=True
        )

        assert r.status_code == 200, r.content
        assert SesionCaja.objects.sin_ambito().filter(estado="CERRADA").count() == 2
        assert LiquidacionInterna.objects.sin_ambito().get().monto == D("60.00")
        # El cajón se contó una vez (354) y cada caja cuadra con lo que de verdad es suyo.
        assert saldo(tienda, tienda.a) == D("294.00")
        assert saldo(tienda, tienda.b) == D("60.00")
        cerradas = SesionCaja.objects.sin_ambito().filter(estado="CERRADA")
        assert all(s.diferencia == D("0") for s in cerradas)

    def test_si_el_cierre_falla_la_liquidacion_tampoco_queda(self, tienda, mixto, local):
        abierta_a, _ = abrir_ambas(tienda)
        vender_en_el_local(tienda, mixto, local)

        # Falta un sol en el conteo y no se explicó la diferencia: el cierre se rechaza.
        r = self.cerrar(
            "cajera", abierta_a.pk, {"200": 1, "100": 1, "50": 1, "1": 3}, liquidar_interna=True
        )

        assert r.status_code == 400, r.content
        assert not LiquidacionInterna.objects.sin_ambito().exists()
        assert not DeudaInterna.objects.sin_ambito().filter(liquidacion__isnull=False).exists()
        assert SesionCaja.objects.sin_ambito().filter(estado="ABIERTA").count() == 2

    def test_sin_ventas_internas_el_cierre_no_cambia(self, tienda, local):
        abierta_a, _ = abrir_ambas(tienda)

        r = self.cerrar("cajera", abierta_a.pk, {})

        assert r.status_code == 200, r.content


class TestInformeDeLaLiquidacion:
    def test_se_descarga_el_informe_de_una_liquidacion(self, tienda, dueno, mixto, local):
        vender_en_el_local(tienda, mixto, local)
        liquidacion = liquidar("dueno", tienda).json()

        r = cliente_de("dueno").get(f"{BASE}/{liquidacion['id']}/excel/", {"empresa": tienda.a.pk})

        assert r.status_code == 200, r.content
        assert "spreadsheetml" in r["Content-Type"]
        assert r.content[:2] == b"PK"  # un .xlsx es un zip
        assert "liquidacion-interna-000001" in r["Content-Disposition"]

    def test_quien_no_puede_liquidar_no_descarga_el_informe(self, tienda, dueno, mixto, local):
        vender_en_el_local(tienda, mixto, local)
        liquidacion = liquidar("dueno", tienda).json()

        r = cliente_de("vendedor").get(
            f"{BASE}/{liquidacion['id']}/excel/", {"empresa": tienda.a.pk}
        )

        assert r.status_code == 403
