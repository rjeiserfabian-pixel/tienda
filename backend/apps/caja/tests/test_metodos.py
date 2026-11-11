"""Método de pago en los movimientos: se guarda, se muestra, se filtra y se compara."""

import io
import itertools
from datetime import timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.caja import reportes, servicios, transferencias
from apps.caja.exceptions import MovimientoInvalido
from apps.caja.models import MovimientoCaja, Origen
from apps.compras.servicios import LineaEntrada, PagoEntrada
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import CuentaFinanciera, MedioPago
from apps.seguridad.tests.conftest import cliente_de

from .conftest import dec

pytestmark = pytest.mark.django_db

HOY = timezone.localdate()
BASE = "/api/v1/caja"
_claves = itertools.count(1)


@pytest.fixture
def escena(nuevo_usuario, compras, conceptos):
    e = compras.entorno
    for nombre, rol in (("admin", "ADMIN"), ("contador", "CONTADOR"), ("cajero", "CAJERO")):
        nuevo_usuario(e.e.org_a, nombre, [e.e1], [(rol, e.e1)])
    establecer_contexto(e.e.org_a.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)
    org = e.e.org_a
    banco = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.e1, nombre="BCP", tipo="BANCO", moneda="PEN", banco="BCP"
    )
    yape = CuentaFinanciera.objects.sin_ambito().create(
        empresa=e.e1, nombre="Yape tienda", tipo="BILLETERA", moneda="PEN", banco="Yape"
    )
    return type(
        "Escena",
        (),
        {
            "compras": compras,
            "empresa": e.e1,
            "caja": compras.caja,
            "banco": banco,
            "yape": yape,
            "conceptos": conceptos,
            "plin": MedioPago.objects.sin_ambito().get(organizacion=org, nombre="Plin"),
            "efectivo": compras.efectivo,
            "transferencia": compras.transferencia,
            "org": org,
        },
    )


def mover(escena, cuenta, tipo, monto, medio=None, codigo=None, dias=0):
    codigo = codigo or ("DEPOSITO_RECIBIDO" if tipo == "INGRESO" else "GASTOS_VARIOS")
    return servicios.registrar_movimiento(
        empresa=escena.empresa,
        cuenta=cuenta,
        tipo=tipo,
        monto=dec(monto),
        concepto=escena.conceptos[codigo],
        fecha=HOY - timedelta(days=dias),
        medio_pago=medio,
    )


class TestServicio:
    def test_el_movimiento_guarda_su_metodo(self, escena):
        m = mover(escena, escena.caja, "EGRESO", "80", medio=escena.plin)
        m.refresh_from_db()
        assert m.medio_pago_id == escena.plin.pk

    def test_el_metodo_es_opcional(self, escena):
        assert mover(escena, escena.caja, "EGRESO", "80").medio_pago_id is None

    def test_rechaza_un_metodo_inactivo_o_de_otra_organizacion(self, escena):
        escena.plin.estado = "INACTIVO"
        escena.plin.save()
        with pytest.raises(MovimientoInvalido, match="método de pago"):
            mover(escena, escena.caja, "EGRESO", "80", medio=escena.plin)
        assert not MovimientoCaja.objects.exists()

    def test_el_pago_de_una_compra_lleva_el_metodo_con_que_se_pago(self, escena):
        c = escena.compras
        linea = LineaEntrada(c.entorno.producto(), dec(1), dec(100))
        c.comprar(
            [linea],
            pagos=[
                PagoEntrada(escena.efectivo, escena.caja, dec("100")),
                PagoEntrada(escena.plin, escena.caja, dec("18"), referencia="OP-9"),
            ],
        )
        por_monto = {
            m.monto: m.medio_pago_id
            for m in MovimientoCaja.objects.filter(origen_tipo=Origen.PAGO_COMPRA)
        }
        assert por_monto == {dec("100"): escena.efectivo.pk, dec("18"): escena.plin.pk}


class TestReporte:
    def test_compara_los_metodos(self, escena):
        mover(escena, escena.caja, "EGRESO", "50")  # sin método: caja → Efectivo
        mover(escena, escena.caja, "EGRESO", "30", medio=escena.efectivo)
        mover(escena, escena.caja, "EGRESO", "80", medio=escena.plin)  # Plin desde la caja
        mover(escena, escena.banco, "EGRESO", "500")  # sin método: banco → Banco
        mover(escena, escena.banco, "INGRESO", "900", medio=escena.transferencia)
        mover(escena, escena.yape, "INGRESO", "40")  # sin método: billetera
        datos = reportes.por_medio(escena.empresa, HOY - timedelta(days=5), HOY)
        por_medio = {
            f["medio"]: (f["ingresos"], f["egresos"], f["cantidad"]) for f in datos["filas"]
        }
        assert por_medio == {
            "Efectivo": (dec("0"), dec("80"), 2),
            "Plin": (dec("0"), dec("80"), 1),
            "Banco": (dec("0"), dec("500"), 1),
            "Transferencia o depósito": (dec("900"), dec("0"), 1),
            "Billetera digital": (dec("40"), dec("0"), 1),
        }

    def test_no_cuenta_los_pasos_entre_cuentas_propias_ni_lo_anulado(self, escena):
        mover(escena, escena.caja, "INGRESO", "1000")
        transferencias.registrar_transferencia(
            empresa=escena.empresa,
            cuenta_origen=escena.caja,
            cuenta_destino=escena.banco,
            monto=dec("400"),
        )
        anulado = mover(escena, escena.caja, "EGRESO", "25")
        servicios.anular_movimiento(anulado, motivo="Error")
        datos = reportes.por_medio(escena.empresa, HOY - timedelta(days=5), HOY)
        assert [(f["medio"], f["ingresos"], f["egresos"]) for f in datos["filas"]] == [
            ("Efectivo", dec("1000"), dec("0"))
        ]

    def test_excel(self, escena):
        mover(escena, escena.caja, "EGRESO", "50")
        datos = reportes.por_medio(escena.empresa, HOY - timedelta(days=5), HOY)
        libro = load_workbook(io.BytesIO(reportes.medios_excel(escena.empresa, datos)))
        assert libro.active.title == "Por método"
        assert any(c.value == "Efectivo" for fila in libro.active.iter_rows() for c in fila)


def llamar(usuario, ruta, **parametros):
    return cliente_de(usuario).get(f"{BASE}/{ruta}", parametros)


class TestApi:
    def crear(self, usuario, escena, **extra):
        cuerpo = {
            "empresa": escena.empresa.pk,
            "cuenta": escena.caja.pk,
            "tipo": "EGRESO",
            "concepto": escena.conceptos["GASTOS_VARIOS"].pk,
            "monto": "12.50",
            **extra,
        }
        return cliente_de(usuario).post(
            f"{BASE}/movimientos/",
            cuerpo,
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"metodos-de-prueba-{next(_claves):06d}",
        )

    def test_el_movimiento_muestra_su_metodo_y_el_tipo_de_cuenta(self, escena):
        r = self.crear("admin", escena, medio_pago=escena.plin.pk)
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["medio_nombre"], d["cuenta_tipo"], d["cuenta_tipo_nombre"]) == (
            "Plin", "CAJA", "Caja de efectivo",
        )  # fmt: skip

    def test_sin_metodo_se_deduce_de_la_cuenta(self, escena):
        d = self.crear("admin", escena).json()
        assert (d["medio_pago"], d["medio_nombre"]) == (None, "Efectivo")

    def test_un_metodo_que_no_existe_se_rechaza(self, escena):
        assert self.crear("admin", escena, medio_pago=999_999).status_code == 400

    def test_filtros_por_metodo_y_por_tipo_de_cuenta(self, escena):
        con_plin = self.crear("admin", escena, medio_pago=escena.plin.pk).json()
        self.crear("admin", escena)
        url = {"empresa": escena.empresa.pk}
        por_medio = llamar("contador", "movimientos/", **url, medio=escena.plin.pk).json()
        assert [m["id"] for m in por_medio["results"]] == [con_plin["id"]]
        efectivo = llamar("contador", "movimientos/", **url, tipo_cuenta="CAJA").json()
        assert efectivo["count"] == 2
        assert llamar("contador", "movimientos/", **url, tipo_cuenta="BANCO").json()["count"] == 0

    def test_reporte_por_metodo_y_su_excel(self, escena):
        self.crear("admin", escena, medio_pago=escena.plin.pk)
        rango = {
            "empresa": escena.empresa.pk,
            "desde": str(HOY - timedelta(days=3)),
            "hasta": str(HOY),
        }
        r = llamar("contador", "reportes/medios/", **rango)
        assert r.status_code == 200, r.content
        assert [(f["medio"], f["egresos"]) for f in r.json()["filas"]] == [("Plin", "12.50")]
        assert llamar("contador", "reportes/medios/excel/", **rango).status_code == 200
        assert llamar("cajero", "reportes/medios/", **rango).status_code == 403
