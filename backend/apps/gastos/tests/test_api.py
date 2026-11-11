"""API de gastos: permisos, registro con y sin comprobante, filtros, anulación y comprobantes."""

import io
import itertools
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.caja.models import MovimientoCaja
from apps.seguridad.tests.conftest import cliente_de

pytestmark = pytest.mark.django_db

BASE = "/api/v1/gastos"
HOY = timezone.localdate()
_claves = itertools.count(1)


def cuerpo_taxi(escena, **extra):
    base = {
        "empresa": escena.empresa.pk,
        "categoria": escena.categorias["MOVILIDAD"].pk,
        "fecha": str(HOY),
        "descripcion": "Taxi a SUNAT",
        "con_comprobante": False,
        "gastado_por": "Rosa Quispe",
        "no_gravado": "15.00",
        "pagos": [{"medio_pago": escena.efectivo.pk, "cuenta": escena.caja.pk, "monto": "15.00"}],
    }
    return {**base, **extra}


def cuerpo_factura(escena, **extra):
    base = {
        "empresa": escena.empresa.pk,
        "categoria": escena.categorias["SERVICIOS"].pk,
        "fecha": str(HOY),
        "descripcion": "Luz de octubre",
        "con_comprobante": True,
        "tipo_comprobante": escena.factura.pk,
        "comprobante_serie": "F001",
        "comprobante_numero": "123",
        "proveedor": escena.proveedor.pk,
        "base_gravada": "100.00",
        "igv": "18.00",
        "no_gravado": "0.00",
        "pagos": [{"medio_pago": escena.efectivo.pk, "cuenta": escena.caja.pk, "monto": "118.00"}],
    }
    return {**base, **extra}


def crear(usuario, cuerpo, llave=None):
    return cliente_de(usuario).post(
        f"{BASE}/",
        cuerpo,
        format="json",
        HTTP_IDEMPOTENCY_KEY=llave or f"gasto-de-prueba-{next(_claves):06d}",
    )


class TestConfiguracion:
    def test_trae_la_tasa_el_tope_y_los_permisos(self, escena):
        r = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": escena.empresa.pk})
        assert r.status_code == 200, r.content
        assert r.json() == {
            "igv_porcentaje": "18.00",
            "tope_sin_comprobante": "100.00",
            "puede_exceder_tope": True,
            "puede_repartir": True,
        }

    def test_el_cajero_no_excede_ni_reparte(self, escena):
        d = (
            cliente_de("cajero")
            .get(f"{BASE}/configuracion/", {"empresa": escena.empresa.pk})
            .json()
        )
        assert (d["puede_exceder_tope"], d["puede_repartir"]) == (False, False)

    def test_un_vendedor_no_ve_gastos(self, escena):
        r = cliente_de("vendedor").get(f"{BASE}/configuracion/", {"empresa": escena.empresa.pk})
        assert r.status_code == 403


class TestRegistrar:
    def test_el_cajero_registra_un_taxi(self, escena):
        r = crear("cajero", cuerpo_taxi(escena))
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["total"], d["con_comprobante"], d["sin_sustento"]) == (
            1, "15.00", False, True,
        )  # fmt: skip
        assert (d["estado_pago"], d["pagado"], d["saldo"]) == ("PAGADO", "15.00", "0.00")
        assert [p["medio_nombre"] for p in d["pagos"]] == ["Efectivo"]
        assert MovimientoCaja.objects.sin_ambito().filter(origen_tipo="PAGO_GASTO").count() == 1

    def test_el_contador_registra_una_factura(self, escena):
        r = crear("contador", cuerpo_factura(escena))
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["comprobante"], d["igv"], d["proveedor_nombre"]) == (
            "F001-123", "18.00", escena.proveedor.nombre,
        )  # fmt: skip
        assert d["tipo_comprobante_nombre"] == "Factura"

    def test_un_reintento_no_duplica(self, escena):
        llave = "gasto-reintento-000001"
        primera = crear("cajero", cuerpo_taxi(escena), llave)
        segunda = crear("cajero", cuerpo_taxi(escena), llave)
        assert (primera.status_code, segunda.status_code) == (201, 201)
        assert segunda["Idempotency-Replayed"] == "true"
        assert MovimientoCaja.objects.sin_ambito().count() == 1

    def test_pide_la_clave_de_idempotencia(self, escena):
        r = cliente_de("cajero").post(f"{BASE}/", cuerpo_taxi(escena), format="json")
        assert r.status_code == 400

    def test_el_tope_lo_pasa_solo_quien_tiene_el_permiso(self, escena):
        grande = cuerpo_taxi(
            escena,
            no_gravado="150.00",
            pagos=[{"medio_pago": escena.efectivo.pk, "cuenta": escena.caja.pk, "monto": "150.00"}],
        )
        assert crear("cajero", grande).status_code == 400
        assert crear("admin", grande).status_code == 201

    def test_reglas_del_servicio_llegan_como_errores_claros(self, escena):
        r = crear("contador", cuerpo_factura(escena, igv="10.00"))
        assert r.status_code == 400
        assert "IGV no corresponde" in r.content.decode()
        assert crear("contador", cuerpo_factura(escena, categoria=999_999)).status_code == 400
        assert crear("contador", cuerpo_factura(escena, proveedor=999_999)).status_code == 400
        assert crear("contador", cuerpo_taxi(escena, pagos=[])).status_code == 400

    def test_sin_permiso_de_registrar(self, escena):
        assert crear("vendedor", cuerpo_taxi(escena)).status_code == 403

    def test_por_pagar_no_mueve_dinero(self, escena):
        r = crear(
            "contador",
            cuerpo_factura(
                escena,
                forma_pago="POR_PAGAR",
                fecha_vencimiento=str(HOY + timedelta(days=5)),
                pagos=[],
            ),
        )
        assert r.status_code == 201, r.content
        assert (r.json()["estado_pago"], r.json()["saldo"]) == ("PENDIENTE", "118.00")
        assert not MovimientoCaja.objects.sin_ambito().exists()


class TestReparto:
    reparto = [{"empresa": None, "porcentaje": "60.00"}, {"empresa": None, "porcentaje": "40.00"}]

    def con_reparto(self, escena):
        partes = [dict(self.reparto[0]), dict(self.reparto[1])]
        partes[0]["empresa"], partes[1]["empresa"] = escena.empresa.pk, escena.otra.pk
        return partes

    def test_quien_tiene_el_permiso_reparte(self, escena):
        r = crear("contador", cuerpo_factura(escena, reparto=self.con_reparto(escena)))
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["repartido"] is True
        assert sorted((x["porcentaje"], x["monto"]) for x in d["repartos"]) == [
            ("40.00", "47.20"), ("60.00", "70.80"),
        ]  # fmt: skip

    def test_el_cajero_no_reparte(self, escena):
        r = crear("cajero", cuerpo_taxi(escena, reparto=self.con_reparto(escena)))
        assert r.status_code == 403
        assert not MovimientoCaja.objects.sin_ambito().exists()

    def test_el_reparto_debe_sumar_cien(self, escena):
        partes = self.con_reparto(escena)
        partes[1]["porcentaje"] = "30.00"
        assert crear("contador", cuerpo_factura(escena, reparto=partes)).status_code == 400


class TestListado:
    def preparar(self, escena):
        taxi = crear("cajero", cuerpo_taxi(escena)).json()
        luz = crear("contador", cuerpo_factura(escena)).json()
        alquiler = crear(
            "contador",
            cuerpo_factura(
                escena,
                categoria=escena.categorias["ALQUILER"].pk,
                descripcion="Alquiler del local",
                comprobante_numero="777",
                forma_pago="POR_PAGAR",
                fecha_vencimiento=str(HOY + timedelta(days=3)),
                pagos=[],
            ),
        ).json()
        return taxi, luz, alquiler

    def lista(self, escena, **filtros):
        r = cliente_de("contador").get(f"{BASE}/", {"empresa": escena.empresa.pk, **filtros})
        assert r.status_code == 200, r.content
        return [g["id"] for g in r.json()["results"]]

    def test_filtros(self, escena):
        taxi, luz, alquiler = self.preparar(escena)
        assert set(self.lista(escena)) == {taxi["id"], luz["id"], alquiler["id"]}
        assert self.lista(escena, con_comprobante="0") == [taxi["id"]]
        assert set(self.lista(escena, con_comprobante="1")) == {luz["id"], alquiler["id"]}
        assert self.lista(escena, categoria=escena.categorias["ALQUILER"].pk) == [alquiler["id"]]
        assert self.lista(escena, pago="pendiente") == [alquiler["id"]]
        assert set(self.lista(escena, pago="pagado")) == {taxi["id"], luz["id"]}
        assert self.lista(escena, pago="vencido") == []
        assert self.lista(escena, q="taxi") == [taxi["id"]]
        assert self.lista(escena, q="777") == [alquiler["id"]]
        assert self.lista(escena, proveedor=escena.proveedor.pk, q="Luz") == [luz["id"]]
        assert self.lista(escena, desde=str(HOY + timedelta(days=1))) == []

    def test_lo_anulado_se_filtra_por_estado(self, escena):
        taxi, luz, _ = self.preparar(escena)
        cliente_de("admin").post(f"{BASE}/{taxi['id']}/anular/", {"motivo": "Error"}, format="json")
        assert self.lista(escena, estado="ANULADO") == [taxi["id"]]
        assert taxi["id"] not in self.lista(escena, estado="EMITIDO")

    def test_la_empresa_es_obligatoria_y_no_se_ve_la_ajena(self, escena):
        assert cliente_de("contador").get(f"{BASE}/").status_code == 400
        ajena = escena.compras.entorno.e.emp_b1.pk
        assert cliente_de("contador").get(f"{BASE}/", {"empresa": ajena}).status_code in (400, 403)


class TestDetalleYAnular:
    def test_el_detalle_trae_pagos_y_reparto(self, escena):
        g = crear("contador", cuerpo_factura(escena)).json()
        d = cliente_de("cajero").get(f"{BASE}/{g['id']}/").json()
        assert d["pagos"][0]["monto"] == "118.00"
        assert (d["repartos"], d["adjuntos"]) == ([], [])

    def test_anular_exige_el_permiso_y_devuelve_el_dinero(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        url = f"{BASE}/{g['id']}/anular/"
        assert cliente_de("cajero").post(url, {"motivo": "Error"}, format="json").status_code == 403
        assert (
            cliente_de("contador").post(url, {"motivo": "Error"}, format="json").status_code == 403
        )
        r = cliente_de("admin").post(url, {"motivo": "Era personal"}, format="json")
        assert r.status_code == 200, r.content
        assert (r.json()["estado"], r.json()["estado_pago"]) == ("ANULADO", "ANULADO")
        assert MovimientoCaja.objects.sin_ambito().get().estado == "ANULADO"
        assert (
            cliente_de("admin").post(url, {"motivo": "Otra vez"}, format="json").status_code == 409
        )

    def test_anular_pide_motivo(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        r = cliente_de("admin").post(f"{BASE}/{g['id']}/anular/", {"motivo": ""}, format="json")
        assert r.status_code == 400


def foto() -> SimpleUploadedFile:
    salida = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 120, 200)).save(salida, format="PNG")
    return SimpleUploadedFile("recibo.png", salida.getvalue(), content_type="image/png")


class TestComprobantes:
    def subir(self, usuario, gasto_id, archivo=None):
        return cliente_de(usuario).post(
            f"{BASE}/adjuntos/",
            {"gasto": gasto_id, "archivo": archivo or foto()},
            format="multipart",
        )

    def test_subir_ver_y_quitar(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        r = self.subir("cajero", g["id"])
        assert r.status_code == 201, r.content
        a = r.json()
        assert (a["tipo_contenido"], a["nombre_original"]) == ("image/webp", "recibo.png")
        lista = cliente_de("contador").get(f"{BASE}/adjuntos/", {"gasto": g["id"]}).json()
        assert [x["id"] for x in lista["results"]] == [a["id"]]
        archivo = cliente_de("contador").get(f"{BASE}/adjuntos/{a['id']}/archivo/")
        assert archivo.status_code == 200
        assert archivo["Content-Disposition"].startswith("inline")
        assert archivo["X-Content-Type-Options"] == "nosniff"
        assert (
            cliente_de("contador").get(f"{BASE}/{g['id']}/").json()["adjuntos"][0]["id"] == a["id"]
        )
        assert cliente_de("cajero").delete(f"{BASE}/adjuntos/{a['id']}/").status_code == 204
        assert cliente_de("cajero").get(f"{BASE}/adjuntos/{a['id']}/archivo/").status_code == 404

    def test_un_pdf_se_descarga(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        a = self.subir("cajero", g["id"], SimpleUploadedFile("a.pdf", b"%PDF-1.4\nx")).json()
        r = cliente_de("cajero").get(f"{BASE}/adjuntos/{a['id']}/archivo/")
        assert r["Content-Disposition"].startswith("attachment")

    def test_un_archivo_falso_se_rechaza(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        falso = SimpleUploadedFile("a.png", b"<html>no soy una foto</html>")
        assert self.subir("cajero", g["id"], falso).status_code == 400

    def test_sin_permiso_o_gasto_inexistente(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        assert self.subir("vendedor", g["id"]).status_code == 403
        assert self.subir("cajero", 999_999).status_code == 404

    def test_un_gasto_anulado_no_recibe_comprobantes(self, escena):
        g = crear("cajero", cuerpo_taxi(escena)).json()
        cliente_de("admin").post(f"{BASE}/{g['id']}/anular/", {"motivo": "Error"}, format="json")
        assert self.subir("cajero", g["id"]).status_code == 409


class TestPagar:
    def por_pagar(self, escena, **extra):
        cuerpo = cuerpo_factura(
            escena,
            forma_pago="POR_PAGAR",
            fecha_vencimiento=str(HOY + timedelta(days=5)),
            pagos=[],
            **extra,
        )
        r = crear("contador", cuerpo)
        assert r.status_code == 201, r.content
        return r.json()

    def pagar(self, usuario, gasto_id, monto, llave=None, **extra):
        pago = {
            "medio_pago": self.escena.efectivo.pk,
            "cuenta": self.escena.caja.pk,
            "monto": monto,
            **extra,
        }
        return cliente_de(usuario).post(
            f"{BASE}/{gasto_id}/pagar/",
            {"pagos": [pago]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=llave or f"pago-de-prueba-{next(_claves):06d}",
        )

    @pytest.fixture(autouse=True)
    def _escena(self, escena):
        self.escena = escena

    def test_pagar_en_partes_hasta_saldar(self, escena):
        g = self.por_pagar(escena)
        r = self.pagar("contador", g["id"], "50.00")
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["pagado"], d["saldo"], d["estado_pago"]) == ("50.00", "68.00", "PARCIAL")
        d = self.pagar("contador", g["id"], "68.00").json()
        assert (d["saldo"], d["estado_pago"], len(d["pagos"])) == ("0.00", "PAGADO", 2)
        assert MovimientoCaja.objects.sin_ambito().filter(origen_tipo="PAGO_GASTO").count() == 2

    def test_un_reintento_no_paga_dos_veces(self, escena):
        g = self.por_pagar(escena)
        llave = "pago-reintento-000001"
        assert self.pagar("contador", g["id"], "40.00", llave).status_code == 200
        segunda = self.pagar("contador", g["id"], "40.00", llave)
        assert segunda["Idempotency-Replayed"] == "true"
        assert segunda.json()["pagado"] == "40.00"

    def test_no_se_paga_de_mas_ni_sin_permiso(self, escena):
        g = self.por_pagar(escena)
        assert self.pagar("contador", g["id"], "119.00").status_code == 400
        assert self.pagar("cajero", g["id"], "10.00").status_code == 403
        assert self.pagar("vendedor", g["id"], "10.00").status_code == 403
        sin_pagos = cliente_de("contador").post(
            f"{BASE}/{g['id']}/pagar/", {"pagos": []}, format="json", HTTP_IDEMPOTENCY_KEY="x" * 20
        )
        assert sin_pagos.status_code == 400

    def test_anular_un_pago_devuelve_la_deuda(self, escena):
        g = self.por_pagar(escena)
        pago_id = self.pagar("contador", g["id"], "118.00").json()["pagos"][0]["id"]
        url = f"{BASE}/{g['id']}/pagos/{pago_id}/anular/"
        assert (
            cliente_de("contador").post(url, {"motivo": "Error"}, format="json").status_code == 403
        )
        r = cliente_de("admin").post(url, {"motivo": "Cuenta equivocada"}, format="json")
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["saldo"], d["estado_pago"]) == ("118.00", "PENDIENTE")
        assert d["pagos"][0]["anulado"] is True
        assert (
            cliente_de("admin").post(url, {"motivo": "Otra vez"}, format="json").status_code == 409
        )

    def test_el_pago_de_un_gasto_al_contado_no_se_anula_suelto(self, escena):
        g = crear("contador", cuerpo_factura(escena)).json()
        url = f"{BASE}/{g['id']}/pagos/{g['pagos'][0]['id']}/anular/"
        assert cliente_de("admin").post(url, {"motivo": "Error"}, format="json").status_code == 409

    def test_un_pago_de_otro_gasto_no_se_anula_por_esta_ruta(self, escena):
        a, b = self.por_pagar(escena), self.por_pagar(escena, comprobante_numero="124")
        pago_de_a = self.pagar("contador", a["id"], "10.00").json()["pagos"][0]["id"]
        url = f"{BASE}/{b['id']}/pagos/{pago_de_a}/anular/"
        assert cliente_de("admin").post(url, {"motivo": "Error"}, format="json").status_code == 404


class TestVencidosEnCaja:
    def vencido(self, escena):
        r = crear(
            "contador",
            cuerpo_factura(
                escena,
                fecha=str(HOY - timedelta(days=20)),
                forma_pago="POR_PAGAR",
                fecha_vencimiento=str(HOY - timedelta(days=3)),
                pagos=[],
            ),
        )
        assert r.status_code == 201, r.content
        return r.json()

    def test_el_listado_filtra_los_vencidos(self, escena):
        g = self.vencido(escena)
        r = cliente_de("contador").get(
            f"{BASE}/", {"empresa": escena.empresa.pk, "pago": "vencido"}
        )
        assert [x["id"] for x in r.json()["results"]] == [g["id"]]
        assert r.json()["results"][0]["estado_pago"] == "VENCIDO"

    def test_la_caja_avisa_de_los_vencidos(self, escena):
        self.vencido(escena)
        r = cliente_de("admin").get("/api/v1/caja/alertas/", {"empresa": escena.empresa.pk})
        avisos = {a["codigo"]: a for a in r.json()}
        assert avisos["gastos_vencidos"]["enlace"] == "/gastos/registro?pago=vencido"
        assert "1 gastos" in avisos["gastos_vencidos"]["titulo"]

    def test_pagado_el_gasto_el_aviso_desaparece(self, escena):
        g = self.vencido(escena)
        cliente_de("contador").post(
            f"{BASE}/{g['id']}/pagar/",
            {
                "pagos": [
                    {"medio_pago": escena.efectivo.pk, "cuenta": escena.caja.pk, "monto": "118.00"}
                ]
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="pago-vencido-000001",
        )
        r = cliente_de("admin").get("/api/v1/caja/alertas/", {"empresa": escena.empresa.pk})
        assert "gastos_vencidos" not in [a["codigo"] for a in r.json()]

    def test_la_proyeccion_de_caja_suma_los_gastos_por_pagar(self, escena):
        g = self.vencido(escena)
        crear(
            "contador",
            cuerpo_factura(
                escena,
                comprobante_numero="900",
                forma_pago="POR_PAGAR",
                fecha_vencimiento=str(HOY + timedelta(days=2)),
                pagos=[],
            ),
        )
        r = cliente_de("admin").get(
            "/api/v1/caja/reportes/proyeccion/", {"empresa": escena.empresa.pk, "meses": 2}
        )
        assert r.status_code == 200, r.content
        filas = r.json()["filas"]
        assert filas[0]["periodo"] == "vencido"
        assert (filas[0]["por_pagar"], filas[0]["de_gastos"]) == ("118.00", "118.00")
        assert g["id"]
        assert sum(float(f["por_pagar"]) for f in filas) == 236.0
