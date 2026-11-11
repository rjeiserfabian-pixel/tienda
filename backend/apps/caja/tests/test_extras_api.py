"""API de los extras de caja: avisos, bancarización, vouchers y caja chica."""

import io
import itertools

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

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
HOY = timezone.localdate()
_claves = itertools.count(1)


@pytest.fixture
def datos(mundo, nuevo_usuario, settings, tmp_path):  # noqa: F811
    settings.MEDIA_ROOT = tmp_path
    e = mundo.e
    nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", e.emp_a1)])
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_conceptos_caja(e.org_a.pk)

    def cuenta(nombre, **extra):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.emp_a1, nombre=nombre, tipo="CAJA", moneda="PEN", **extra
        )

    conceptos = {
        c.codigo: c for c in ConceptoCaja.objects.sin_ambito().filter(organizacion=e.org_a)
    }
    return type(
        "Datos",
        (),
        {
            "mundo": mundo,
            "caja": cuenta("Caja soles"),
            "chica": cuenta("Caja chica", rol_caja="CAJA_CHICA", fondo_inicial=500),
            "principal": cuenta("Principal", rol_caja="PRINCIPAL"),
            "conceptos": conceptos,
        },
    )


def movimiento(datos, cuenta, tipo, monto, concepto="APORTE_CAPITAL"):
    r = cliente_de("admin").post(
        f"{BASE}/movimientos/",
        {
            "empresa": datos.mundo.e1.pk,
            "cuenta": cuenta.pk,
            "tipo": tipo,
            "concepto": datos.conceptos[concepto].pk,
            "monto": monto,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"extras-de-prueba-{next(_claves):06d}",
    )
    assert r.status_code == 201, r.content
    return r.json()


def foto() -> SimpleUploadedFile:
    salida = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 200)).save(salida, format="PNG")
    return SimpleUploadedFile("voucher.png", salida.getvalue(), content_type="image/png")


class TestAvisosYBancarizacion:
    def test_avisos(self, datos):
        movimiento(datos, datos.caja, "EGRESO", "40.00", "GASTOS_VARIOS")
        r = cliente_de("cajero").get(f"{BASE}/alertas/", {"empresa": datos.mundo.e1.pk})
        assert r.status_code == 200
        assert [a["codigo"] for a in r.json()] == ["saldo_negativo"]

    def test_los_movimientos_traen_su_marca(self, datos):
        grande = movimiento(datos, datos.caja, "INGRESO", "2500.00")
        chico = movimiento(datos, datos.caja, "INGRESO", "10.00")
        assert (grande["sin_bancarizar"], chico["sin_bancarizar"]) == (True, False)
        r = cliente_de("contador").get(
            f"{BASE}/movimientos/", {"empresa": datos.mundo.e1.pk, "sin_bancarizar": "1"}
        )
        assert [m["id"] for m in r.json()["results"]] == [grande["id"]]

    def test_el_reporte_de_bancarizacion(self, datos):
        movimiento(datos, datos.caja, "INGRESO", "2500.00")
        r = cliente_de("contador").get(
            f"{BASE}/reportes/bancarizacion/", {"empresa": datos.mundo.e1.pk}
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["total"], d["truncado"], d["umbrales"]["PEN"]) == (1, False, "2000.00")
        assert (
            cliente_de("cajero")
            .get(f"{BASE}/reportes/bancarizacion/", {"empresa": datos.mundo.e1.pk})
            .status_code
            == 403
        )

    def test_saldos_traen_el_minimo_y_los_umbrales(self, datos):
        datos.caja.saldo_minimo = 300
        datos.caja.save()
        d = cliente_de("admin").get(f"{BASE}/saldos/", {"empresa": datos.mundo.e1.pk}).json()
        assert d["umbral_bancarizacion"] == {"PEN": "2000.00", "USD": "500.00"}
        assert {c["nombre"]: c["saldo_minimo"] for c in d["cuentas"]}["Caja soles"] == "300.00"


class TestVouchers:
    def subir(self, usuario, movimiento_id, archivo=None):
        return cliente_de(usuario).post(
            f"{BASE}/adjuntos/",
            {"movimiento": movimiento_id, "archivo": archivo or foto()},
            format="multipart",
        )

    def test_subir_ver_y_quitar(self, datos):
        m = movimiento(datos, datos.caja, "INGRESO", "10.00")
        r = self.subir("contador", m["id"])
        assert r.status_code == 201, r.content
        a = r.json()
        assert (a["tipo_contenido"], a["nombre_original"]) == ("image/webp", "voucher.png")

        lista = cliente_de("cajero").get(f"{BASE}/adjuntos/", {"movimiento": m["id"]}).json()
        assert [x["id"] for x in lista["results"]] == [a["id"]]

        archivo = cliente_de("cajero").get(f"{BASE}/adjuntos/{a['id']}/archivo/")
        assert archivo.status_code == 200
        assert archivo["Content-Type"] == "image/webp"
        assert archivo["Content-Disposition"].startswith("inline")
        assert archivo["X-Content-Type-Options"] == "nosniff"
        assert "sandbox" in archivo["Content-Security-Policy"]

        movimientos = (
            cliente_de("contador")
            .get(f"{BASE}/movimientos/", {"empresa": datos.mundo.e1.pk})
            .json()["results"]
        )
        assert movimientos[0]["adjuntos_cantidad"] == 1

        assert cliente_de("contador").delete(f"{BASE}/adjuntos/{a['id']}/").status_code == 204
        assert cliente_de("cajero").get(f"{BASE}/adjuntos/{a['id']}/archivo/").status_code == 404

    def test_un_pdf_siempre_se_descarga(self, datos):
        m = movimiento(datos, datos.caja, "INGRESO", "10.00")
        pdf = SimpleUploadedFile("recibo.pdf", b"%PDF-1.4\nhola")
        a = self.subir("contador", m["id"], pdf).json()
        r = cliente_de("contador").get(f"{BASE}/adjuntos/{a['id']}/archivo/")
        assert r["Content-Type"] == "application/pdf"
        assert r["Content-Disposition"].startswith("attachment")

    def test_el_cajero_ve_pero_no_sube(self, datos):
        m = movimiento(datos, datos.caja, "INGRESO", "10.00")
        assert self.subir("cajero", m["id"]).status_code == 403

    def test_un_archivo_falso_se_rechaza(self, datos):
        m = movimiento(datos, datos.caja, "INGRESO", "10.00")
        falso = SimpleUploadedFile("voucher.png", b"<html>no soy una foto</html>")
        assert self.subir("contador", m["id"], falso).status_code == 400

    def test_un_movimiento_inexistente(self, datos):
        assert self.subir("contador", 999_999).status_code == 404


class TestCajaChicaApi:
    def preparar(self, datos):
        movimiento(datos, datos.chica, "INGRESO", "500.00")
        movimiento(datos, datos.principal, "INGRESO", "1000.00")
        return [
            movimiento(datos, datos.chica, "EGRESO", m, "GASTOS_VARIOS")
            for m in ("30.00", "45.00", "25.00")
        ]

    def rendir(self, usuario, datos, **extra):
        cuerpo = {
            "empresa": datos.mundo.e1.pk,
            "cuenta": datos.chica.pk,
            "cuenta_origen": datos.principal.pk,
            **extra,
        }
        return cliente_de(usuario).post(f"{BASE}/rendiciones/", cuerpo, format="json")

    def test_el_resumen_y_los_gastos_por_rendir(self, datos):
        gastos = self.preparar(datos)
        resumen = cliente_de("contador").get(f"{BASE}/caja-chica/", {"empresa": datos.mundo.e1.pk})
        assert resumen.status_code == 200, resumen.content
        [fila] = resumen.json()
        assert (fila["fondo"], fila["saldo"], fila["faltante"], fila["por_rendir_cantidad"]) == (
            "500.00", "400.00", "100.00", 3,
        )  # fmt: skip
        r = cliente_de("contador").get(
            f"{BASE}/caja-chica/gastos/", {"empresa": datos.mundo.e1.pk, "cuenta": datos.chica.pk}
        )
        assert [g["id"] for g in r.json()] == [g["id"] for g in gastos]

    def test_rendir_y_anular(self, datos):
        gastos = self.preparar(datos)
        r = self.rendir(
            "contador", datos, movimientos=[gastos[0]["id"], gastos[1]["id"]], glosa="Octubre"
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["total"], d["cantidad"], d["estado"]) == (1, "75.00", 2, "EMITIDO")
        lista = cliente_de("contador").get(f"{BASE}/rendiciones/", {"empresa": datos.mundo.e1.pk})
        assert lista.json()["count"] == 1

        # Un gasto ya rendido no se rinde otra vez.
        assert self.rendir("contador", datos, movimientos=[gastos[0]["id"]]).status_code == 409

        # Anular exige el permiso de anular (el contador no lo tiene; el administrador sí).
        assert (
            cliente_de("contador")
            .post(f"{BASE}/rendiciones/{d['id']}/anular/", {"motivo": "Error"}, format="json")
            .status_code
            == 403
        )
        r = cliente_de("admin").post(
            f"{BASE}/rendiciones/{d['id']}/anular/",
            {"motivo": "Falta un comprobante"},
            format="json",
        )
        assert (r.status_code, r.json()["estado"]) == (200, "ANULADO")
        [fila] = (
            cliente_de("contador").get(f"{BASE}/caja-chica/", {"empresa": datos.mundo.e1.pk}).json()
        )
        assert fila["por_rendir_cantidad"] == 3

    def test_el_cajero_no_ve_ni_rinde(self, datos):
        self.preparar(datos)
        assert (
            cliente_de("cajero")
            .get(f"{BASE}/caja-chica/", {"empresa": datos.mundo.e1.pk})
            .status_code
            == 403
        )
        assert self.rendir("cajero", datos).status_code == 403

    def test_cuentas_invalidas(self, datos):
        self.preparar(datos)
        assert self.rendir("contador", datos, cuenta_origen=999_999).status_code == 400
        assert self.rendir("contador", datos, cuenta=999_999).status_code == 400
        assert self.rendir("contador", datos, cuenta=datos.caja.pk).status_code == 409
