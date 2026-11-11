"""API de la conciliación bancaria: permisos, importación por archivo y el flujo completo."""

import itertools
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

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


def f(atras: int) -> str:
    return (HOY - timedelta(days=atras)).strftime("%d/%m/%Y")


def archivo(*filas) -> SimpleUploadedFile:
    texto = "\n".join(["Fecha;Descripción;Operación;Cargo;Abono", *filas]) + "\n"
    return SimpleUploadedFile("extracto.csv", texto.encode("utf-8"), content_type="text/csv")


@pytest.fixture
def datos(mundo, nuevo_usuario):  # noqa: F811
    e = mundo.e
    nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", e.emp_a1)])
    establecer_contexto(e.org_a.pk, [e.emp_a1.pk, e.emp_a2.pk], e.usuario_id)
    sembrar_conceptos_caja(e.org_a.pk)
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.emp_a1, nombre="BCP soles", tipo="BANCO", moneda="PEN", banco="BCP"
    )
    conceptos = {
        c.codigo: c for c in ConceptoCaja.objects.sin_ambito().filter(organizacion=e.org_a)
    }
    return type("Datos", (), {"mundo": mundo, "banco": banco, "conceptos": conceptos})


def importar(usuario, datos, *filas, **extra):
    cuerpo = {
        "empresa": datos.mundo.e1.pk,
        "cuenta": datos.banco.pk,
        "archivo": archivo(*filas),
        **extra,
    }
    return cliente_de(usuario).post(f"{BASE}/extractos/", cuerpo, format="multipart")


def movimiento(datos, tipo, monto, atras, concepto):
    return (
        cliente_de("admin")
        .post(
            f"{BASE}/movimientos/",
            {
                "empresa": datos.mundo.e1.pk,
                "cuenta": datos.banco.pk,
                "tipo": tipo,
                "concepto": datos.conceptos[concepto].pk,
                "monto": monto,
                "fecha": str(HOY - timedelta(days=atras)),
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"conciliacion-de-prueba-{next(_claves):06d}",
        )
        .json()
    )


def accion(usuario, url, cuerpo=None, metodo="post"):
    cliente = cliente_de(usuario)
    if metodo == "get":
        return cliente.get(f"{BASE}/{url}")
    return cliente.post(f"{BASE}/{url}", cuerpo or {}, format="json")


class TestPermisos:
    def test_el_contador_importa(self, datos):
        r = importar("contador", datos, f"{f(3)};Depósito;OP1;;100.00")
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["numero"], d["estado"], d["cuenta_nombre"], d["moneda"]) == (
            1, "ABIERTO", "BCP soles", "PEN",
        )  # fmt: skip
        assert (d["lineas_total"], d["lineas_pendientes"]) == (1, 1)

    def test_un_cajero_no_concilia(self, datos):
        assert importar("cajero", datos, f"{f(3)};Depósito;OP1;;100.00").status_code == 403
        r = cliente_de("cajero").get(f"{BASE}/extractos/?empresa={datos.mundo.e1.pk}")
        assert r.status_code == 403

    def test_un_vendedor_tampoco_ve_la_conciliacion(self, datos):
        r = cliente_de("vendedor").get(f"{BASE}/extractos/?empresa={datos.mundo.e1.pk}")
        assert r.status_code == 403

    def test_cerrar_exige_el_permiso_de_cierre(self, datos):
        estado = importar("contador", datos, f"{f(3)};Depósito;OP1;;100.00").json()
        assert accion("cajero", f"extractos/{estado['id']}/cerrar/").status_code == 403


class TestImportar:
    def test_previsualizar_no_guarda(self, datos):
        r = cliente_de("contador").post(
            f"{BASE}/extractos/previsualizar/",
            {
                "empresa": datos.mundo.e1.pk,
                "cuenta": datos.banco.pk,
                "archivo": archivo(f"{f(3)};Depósito;OP1;;100.00", f"{f(2)};Pago;OP2;30.00;"),
            },
            format="multipart",
        )
        assert r.status_code == 200, r.content
        d = r.json()
        assert (d["total"], d["nuevas"], d["repetidas"], d["con_error"]) == (2, 2, 0, 0)
        assert (d["abonos"], d["cargos"]) == ("100.00", "30.00")
        listado = (
            cliente_de("contador").get(f"{BASE}/extractos/?empresa={datos.mundo.e1.pk}").json()
        )
        assert listado["count"] == 0

    def test_un_archivo_invalido_se_explica(self, datos):
        r = importar("contador", datos, "esto no es un extracto")
        assert r.status_code == 400
        assert "archivo" in r.json()["error"]["detalle"] if "detalle" in r.json()["error"] else True

    def test_los_saldos_que_no_cuadran_se_rechazan(self, datos):
        r = importar(
            "contador", datos, f"{f(3)};Depósito;OP1;;100.00", saldo_inicial="0", saldo_final="50"
        )
        assert r.status_code == 400
        assert "no cuadran" in r.content.decode()

    def test_una_cuenta_ajena_se_rechaza(self, datos):
        r = cliente_de("contador").post(
            f"{BASE}/extractos/",
            {"empresa": datos.mundo.e1.pk, "cuenta": 999_999, "archivo": archivo(f"{f(3)};X;1;;5")},
            format="multipart",
        )
        assert r.status_code == 400


class TestFlujo:
    def preparar(self, datos):
        movimiento(datos, "INGRESO", "1000.00", 5, "DEPOSITO_RECIBIDO")
        movimiento(datos, "EGRESO", "200.00", 3, "GASTOS_VARIOS")
        return importar(
            "contador",
            datos,
            f"{f(5)};Depósito;OP1;;1000.00",
            f"{f(3)};Pago;OP2;200.00;",
            f"{f(2)};Comisión;OP3;5.00;",
            saldo_inicial="0",
            saldo_final="795",
        ).json()

    def test_conciliar_registrar_y_cerrar(self, datos):
        estado = self.preparar(datos)
        base = f"extractos/{estado['id']}"

        r = accion("contador", f"{base}/automatica/")
        assert (r.status_code, r.json()) == (200, {"unidas": 2})

        pendientes = accion("contador", f"{base}/lineas/?estado=pendiente", metodo="get").json()
        assert pendientes["count"] == 1
        [linea] = pendientes["results"]
        assert (linea["monto"], linea["referencia"], linea["movimiento"]) == ("-5.00", "OP3", None)

        # Sin registrar la comisión no se puede cerrar.
        assert accion("contador", f"{base}/cerrar/").status_code == 409

        r = accion(
            "contador",
            f"lineas-extracto/{linea['id']}/registrar/",
            {"concepto": datos.conceptos["COMISION_BANCARIA"].pk},
        )
        assert r.status_code == 200, r.content
        assert (r.json()["union"], r.json()["movimiento_concepto"]) == (
            "REGISTRADA", "Comisión bancaria",
        )  # fmt: skip

        detalle = accion("contador", f"{base}/", metodo="get").json()
        assert detalle["resumen"]["pendientes"] == 0
        assert detalle["resumen"]["diferencia"] == "0.00"

        r = accion("contador", f"{base}/cerrar/", {"nota": ""})
        assert r.status_code == 200, r.content
        assert r.json()["estado"] == "CERRADO"
        # Cerrado: ya no se deshace nada.
        r = accion("contador", f"lineas-extracto/{linea['id']}/deshacer/")
        assert r.status_code == 409
        # Hasta que se reabra.
        assert accion("contador", f"{base}/reabrir/", {}).status_code == 400
        r = accion("contador", f"{base}/reabrir/", {"motivo": "Revisar la comisión"})
        assert (r.status_code, r.json()["estado"]) == (200, "ABIERTO")
        assert accion("contador", f"lineas-extracto/{linea['id']}/deshacer/").status_code == 200

    def test_candidatos_y_union_manual(self, datos):
        propio = movimiento(datos, "EGRESO", "50.00", 9, "GASTOS_VARIOS")
        estado = importar("contador", datos, f"{f(2)};Pago;OP9;50.00;").json()
        [linea] = accion("contador", f"extractos/{estado['id']}/lineas/", metodo="get").json()[
            "results"
        ]
        # Siete días de diferencia: fuera del margen normal, dentro de 10.
        assert (
            accion("contador", f"lineas-extracto/{linea['id']}/candidatos/", metodo="get").json()
            == []
        )
        lejos = accion(
            "contador", f"lineas-extracto/{linea['id']}/candidatos/?dias=10", metodo="get"
        )
        assert [m["id"] for m in lejos.json()] == [propio["id"]]
        r = accion(
            "contador", f"lineas-extracto/{linea['id']}/conciliar/", {"movimiento": propio["id"]}
        )
        assert (r.status_code, r.json()["union"]) == (200, "MANUAL")
        # El movimiento conciliado ya no se puede anular desde Movimientos.
        r = accion("admin", f"movimientos/{propio['id']}/anular/", {"motivo": "Error"})
        assert r.status_code == 409

    def test_el_concepto_automatico_no_se_ofrece(self, datos):
        estado = importar("contador", datos, f"{f(2)};Pago;OP9;50.00;").json()
        [linea] = accion("contador", f"extractos/{estado['id']}/lineas/", metodo="get").json()[
            "results"
        ]
        r = accion(
            "contador",
            f"lineas-extracto/{linea['id']}/registrar/",
            {"concepto": datos.conceptos["PAGO_PROVEEDOR"].pk},
        )
        assert r.status_code == 400

    def test_descartar(self, datos):
        estado = importar("contador", datos, f"{f(2)};Pago;OP9;50.00;").json()
        assert accion("contador", f"extractos/{estado['id']}/descartar/").status_code == 204
        r = cliente_de("contador").get(f"{BASE}/extractos/?empresa={datos.mundo.e1.pk}")
        assert r.json()["count"] == 0

    def test_filtros_del_listado(self, datos):
        importar("contador", datos, f"{f(2)};Pago;OP9;50.00;")
        url = f"{BASE}/extractos/?empresa={datos.mundo.e1.pk}"
        assert cliente_de("contador").get(url + "&estado=CERRADO").json()["count"] == 0
        assert cliente_de("contador").get(url + f"&cuenta={datos.banco.pk}").json()["count"] == 1
        assert cliente_de("contador").get(url).json()["results"][0]["lineas_pendientes"] == 1
