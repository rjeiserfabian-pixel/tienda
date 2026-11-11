"""Gastos generales: con y sin comprobante, al contado y por pagar, repartidos y anulados."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.caja import servicios as caja
from apps.caja.exceptions import SesionRequerida
from apps.caja.models import MovimientoCaja, Origen
from apps.compras.servicios import PagoEntrada
from apps.core.exceptions import DocumentoYaAnulado, MotivoObligatorio
from apps.gastos import servicios
from apps.gastos.exceptions import GastoInvalido, GastoNoModificable
from apps.gastos.models import Gasto, GastoReparto, PagoGasto
from apps.gastos.servicios import RepartoEntrada
from apps.mantenimiento.models import TipoComprobante
from apps.organizacion.models import ConfiguracionEmpresa

from .conftest import dec

pytestmark = pytest.mark.django_db

HOY = timezone.localdate()


@pytest.fixture
def escena(compras, categorias):
    e = compras.entorno
    org = e.e.org_a

    def tipo(codigo):
        return TipoComprobante.objects.sin_ambito().get(organizacion=org, codigo=codigo)

    return type(
        "Escena",
        (),
        {
            "compras": compras,
            "empresa": e.e1,
            "otra": e.e2,
            "caja": compras.caja,
            "caja_usd": compras.caja_usd,
            "proveedor": e.proveedor,
            "efectivo": compras.efectivo,
            "transferencia": compras.transferencia,
            "categorias": categorias,
            "factura": tipo("01"),
            "boleta": tipo("03"),
            "honorarios": tipo("02"),
            "recibo": tipo("14"),
            "ajena": e.e.emp_b1,
        },
    )


def pago(escena, monto, medio=None, cuenta=None, **extra):
    return PagoEntrada(medio or escena.efectivo, cuenta or escena.caja, dec(monto), **extra)


def gasto(escena, **extra):
    """Un taxi de S/ 15 sin comprobante, pagado en efectivo (se cambia con ``extra``)."""
    datos = {
        "empresa": escena.empresa,
        "categoria": escena.categorias["MOVILIDAD"],
        "fecha": HOY,
        "descripcion": "Taxi a la oficina de SUNAT",
        "con_comprobante": False,
        "gastado_por": "Rosa Quispe",
        "no_gravado": dec("15"),
        "pagos": [pago(escena, "15")],
    }
    return servicios.registrar_gasto(**{**datos, **extra})


def factura(escena, **extra):
    """Un recibo de luz con factura: base 100 + IGV 18, pagado en efectivo."""
    datos = {
        "categoria": escena.categorias["SERVICIOS"],
        "descripcion": "Luz de octubre",
        "con_comprobante": True,
        "tipo_comprobante": escena.factura,
        "comprobante_serie": "F001",
        "comprobante_numero": "123",
        "proveedor": escena.proveedor,
        "base_gravada": dec("100"),
        "igv": dec("18"),
        "no_gravado": dec("0"),
        "gastado_por": "",
        "pagos": [pago(escena, "118")],
    }
    return gasto(escena, **{**datos, **extra})


class TestConComprobante:
    def test_factura_al_contado_sale_de_la_caja(self, escena):
        g = factura(escena)
        assert (g.numero, g.total, g.igv, g.estado, g.sin_sustento) == (
            1, dec("118"), dec("18"), "EMITIDO", False,
        )  # fmt: skip
        assert g.comprobante == "F001-123"
        [p] = g.pagos.all()
        [m] = MovimientoCaja.objects.filter(origen_tipo=Origen.PAGO_GASTO)
        assert (m.tipo, m.monto, m.origen_id, m.concepto.codigo) == (
            "EGRESO", dec("118"), p.pk, "PAGO_GASTO",
        )  # fmt: skip
        assert m.medio_pago_id == escena.efectivo.pk
        assert f"Gasto N° {g.numero:06d}" in m.glosa
        assert caja.saldo_de(escena.caja) == dec("-118")
        assert g.saldo() == dec("0")

    def test_boleta_y_recibo_sin_proveedor(self, escena):
        g = factura(
            escena,
            tipo_comprobante=escena.boleta,
            comprobante_serie="B001",
            proveedor=None,
        )
        assert g.proveedor_id is None

    def test_recibo_de_servicios_publicos(self, escena):
        g = gasto(
            escena,
            categoria=escena.categorias["SERVICIOS"],
            con_comprobante=True,
            tipo_comprobante=escena.recibo,
            comprobante_serie="",
            comprobante_numero="0007-45",
            no_gravado=dec("0"),
            base_gravada=dec("84.75"),
            igv=dec("15.25"),
            pagos=[pago(escena, "100")],
        )
        assert (g.total, g.comprobante) == (dec("100"), "0007-45")

    def test_honorarios_no_detallan_igv(self, escena):
        g = gasto(
            escena,
            con_comprobante=True,
            tipo_comprobante=escena.honorarios,
            comprobante_serie="E001",
            comprobante_numero="9",
            proveedor=escena.proveedor,
            no_gravado=dec("500"),
            pagos=[pago(escena, "500")],
        )
        assert (g.base_gravada, g.igv, g.no_gravado) == (dec("0"), dec("0"), dec("500"))
        with pytest.raises(GastoInvalido, match="no detalla el IGV"):
            gasto(
                escena,
                con_comprobante=True,
                tipo_comprobante=escena.honorarios,
                comprobante_numero="10",
                base_gravada=dec("100"),
                igv=dec("18"),
                no_gravado=dec("0"),
                pagos=[pago(escena, "118")],
            )

    def test_el_igv_debe_corresponder_a_la_base(self, escena):
        with pytest.raises(GastoInvalido, match="IGV no corresponde"):
            factura(escena, igv=dec("10"), pagos=[pago(escena, "110")])
        assert not Gasto.objects.exists()

    def test_la_factura_pide_proveedor(self, escena):
        with pytest.raises(GastoInvalido, match="necesita el proveedor"):
            factura(escena, proveedor=None)

    def test_pide_el_comprobante(self, escena):
        with pytest.raises(GastoInvalido, match="tipo de comprobante"):
            factura(escena, tipo_comprobante=None)
        with pytest.raises(GastoInvalido, match="número del comprobante"):
            factura(escena, comprobante_numero="")
        with pytest.raises(GastoInvalido, match="serie"):
            factura(escena, comprobante_serie="F 001!")

    def test_el_mismo_comprobante_no_se_registra_dos_veces(self, escena):
        primero = factura(escena)
        with pytest.raises(GastoInvalido, match="ya está registrado"):
            factura(escena)
        servicios.anular_gasto(primero, motivo="Se cargó por error")
        assert factura(escena).numero == 2  # anulado, el comprobante queda libre

    def test_sin_el_tope_de_los_gastos_sin_comprobante(self, escena):
        assert factura(
            escena,
            base_gravada=dec("5000"),
            igv=dec("900"),
            pagos=[pago(escena, "5900")],
            comprobante_numero="55",
        ).total == dec("5900")


class TestSinComprobante:
    def test_un_taxi(self, escena):
        g = gasto(escena)
        assert (g.con_comprobante, g.sin_sustento, g.total, g.no_gravado) == (
            False, True, dec("15"), dec("15"),
        )  # fmt: skip
        assert (g.tipo_comprobante_id, g.proveedor_id, g.comprobante) == (None, None, "")
        assert g.gastado_por == "Rosa Quispe"

    def test_pide_quien_lo_gasto_y_que_fue(self, escena):
        with pytest.raises(GastoInvalido, match="quién hizo el gasto"):
            gasto(escena, gastado_por="")
        with pytest.raises(GastoInvalido, match="Describa el gasto"):
            gasto(escena, descripcion="ab")

    def test_no_lleva_datos_de_comprobante_ni_igv(self, escena):
        with pytest.raises(GastoInvalido, match="no lleva datos de comprobante"):
            gasto(escena, tipo_comprobante=escena.boleta)
        with pytest.raises(GastoInvalido, match="solo el importe total"):
            gasto(escena, igv=dec("2"))

    def test_el_tope_se_respeta(self, escena):
        with pytest.raises(GastoInvalido, match="no puede pasar de S/ 100.00"):
            gasto(escena, no_gravado=dec("150"), pagos=[pago(escena, "150")])
        assert not Gasto.objects.exists()

    def test_con_permiso_se_pasa_del_tope(self, escena):
        g = gasto(
            escena, no_gravado=dec("150"), pagos=[pago(escena, "150")], puede_exceder_tope=True
        )
        assert g.total == dec("150")

    def test_el_tope_es_configurable_por_empresa(self, escena):
        configuracion, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(
            empresa=escena.empresa
        )
        configuracion.gasto_sin_comprobante_maximo = dec("300")
        configuracion.save()
        assert gasto(escena, no_gravado=dec("250"), pagos=[pago(escena, "250")]).total == dec("250")
        with pytest.raises(GastoInvalido, match="S/ 300.00"):
            gasto(escena, no_gravado=dec("301"), pagos=[pago(escena, "301")])

    def test_el_tope_se_mide_en_soles(self, escena):
        # US$ 30 a 3.75 son S/ 112.50: pasa del tope de S/ 100.
        with pytest.raises(GastoInvalido, match="no puede pasar"):
            gasto(
                escena,
                moneda="USD",
                tipo_cambio=dec("3.75"),
                no_gravado=dec("30"),
                pagos=[pago(escena, "30", cuenta=escena.caja_usd)],
            )


class TestPagos:
    def test_los_pagos_deben_sumar_el_total(self, escena):
        with pytest.raises(GastoInvalido, match="sumar exactamente"):
            gasto(escena, pagos=[pago(escena, "14")])
        with pytest.raises(GastoInvalido, match="con qué se pagó"):
            gasto(escena, pagos=[])
        assert not MovimientoCaja.objects.exists()

    def test_dos_metodos_son_dos_egresos(self, escena):
        banco = escena.compras.caja  # el mismo escenario: dos movimientos de la misma caja
        g = gasto(
            escena,
            no_gravado=dec("90"),
            pagos=[
                pago(escena, "60"),
                pago(escena, "30", medio=escena.transferencia, cuenta=banco, referencia="OP-3"),
            ],
        )
        movimientos = MovimientoCaja.objects.filter(origen_tipo=Origen.PAGO_GASTO)
        assert sorted(m.monto for m in movimientos) == [dec("30"), dec("60")]
        assert g.pagado() == dec("90")

    def test_pagar_desde_una_cuenta_en_dolares_usa_el_tipo_de_cambio(self, escena):
        g = gasto(
            escena,
            no_gravado=dec("75"),
            pagos=[pago(escena, "75", cuenta=escena.caja_usd, tipo_cambio=dec("3.75"))],
            puede_exceder_tope=True,
        )
        [p] = g.pagos.all()
        assert (p.monto, p.monto_cuenta, p.tipo_cambio) == (dec("75"), dec("20"), dec("3.75"))
        assert caja.saldo_de(escena.caja_usd) == dec("-20")

    def test_otra_moneda_sin_tipo_de_cambio_se_rechaza(self, escena):
        with pytest.raises(GastoInvalido, match="tipo de cambio"):
            gasto(escena, pagos=[pago(escena, "15", cuenta=escena.caja_usd)])

    def test_un_gasto_en_dolares_pide_su_tipo_de_cambio(self, escena):
        with pytest.raises(GastoInvalido, match="tipo de cambio"):
            gasto(escena, moneda="USD", pagos=[pago(escena, "15", cuenta=escena.caja_usd)])

    def test_la_caja_con_sesion_obligatoria_la_exige(self, escena):
        escena.caja.exige_sesion = True
        escena.caja.save()
        with pytest.raises(SesionRequerida):
            gasto(escena)
        assert not Gasto.objects.exists() and not PagoGasto.objects.exists()

    def test_validaciones_generales(self, escena):
        with pytest.raises(GastoInvalido, match="futura"):
            gasto(escena, fecha=HOY + timedelta(days=1))
        escena.categorias["OTROS"].estado = "INACTIVO"
        escena.categorias["OTROS"].save()
        with pytest.raises(GastoInvalido, match="inactiva"):
            gasto(escena, categoria=escena.categorias["OTROS"])
        with pytest.raises(GastoInvalido, match="moneda"):
            gasto(escena, moneda="EUR")
        with pytest.raises(GastoInvalido, match="mayor que cero"):
            gasto(escena, no_gravado=dec("0"), pagos=[pago(escena, "1")])
        with pytest.raises(GastoInvalido, match="2 decimales"):
            gasto(escena, no_gravado=dec("10.123"), pagos=[pago(escena, "10.12")])


class TestPorPagar:
    def por_pagar(self, escena, **extra):
        datos = {
            "forma_pago": "POR_PAGAR",
            "fecha_vencimiento": HOY + timedelta(days=10),
            "pagos": [],
        }
        return factura(escena, **{**datos, **extra})

    def test_queda_pendiente_sin_mover_dinero(self, escena):
        g = self.por_pagar(escena)
        assert (g.forma_pago, g.saldo(), g.pagado()) == ("POR_PAGAR", dec("118"), dec("0"))
        assert not MovimientoCaja.objects.exists()

    def test_pide_vencimiento_y_no_admite_pagos_al_registrar(self, escena):
        with pytest.raises(GastoInvalido, match="vencimiento"):
            self.por_pagar(escena, fecha_vencimiento=None)
        with pytest.raises(GastoInvalido, match="vencimiento"):
            self.por_pagar(escena, fecha_vencimiento=HOY - timedelta(days=1))
        with pytest.raises(GastoInvalido, match="se paga después"):
            self.por_pagar(escena, pagos=[pago(escena, "118")])

    def test_pagar_en_partes(self, escena):
        g = self.por_pagar(escena)
        servicios.pagar_gasto(g, [pago(escena, "50")])
        assert g.saldo() == dec("68")
        servicios.pagar_gasto(
            g, [pago(escena, "68", medio=escena.transferencia, referencia="OP-1")]
        )
        assert (g.saldo(), g.pagado()) == (dec("0"), dec("118"))
        assert MovimientoCaja.objects.filter(origen_tipo=Origen.PAGO_GASTO).count() == 2
        with pytest.raises(GastoNoModificable, match="ya está pagado"):
            servicios.pagar_gasto(g, [pago(escena, "1")])

    def test_no_se_paga_de_mas(self, escena):
        g = self.por_pagar(escena)
        with pytest.raises(GastoInvalido, match="pasan de lo que falta"):
            servicios.pagar_gasto(g, [pago(escena, "119")])
        with pytest.raises(GastoInvalido, match="con qué se paga"):
            servicios.pagar_gasto(g, [])
        assert g.pagado() == dec("0")

    def test_anular_un_pago_devuelve_el_dinero_y_la_deuda(self, escena):
        g = self.por_pagar(escena)
        [p] = servicios.pagar_gasto(g, [pago(escena, "118")])
        assert caja.saldo_de(escena.caja) == dec("-118")
        servicios.anular_pago(p, motivo="Se pagó a la cuenta equivocada")
        p.refresh_from_db()
        assert p.anulado and "equivocada" in p.motivo_anulacion
        assert (g.saldo(), caja.saldo_de(escena.caja)) == (dec("118"), dec("0"))
        with pytest.raises(GastoNoModificable, match="ya está anulado"):
            servicios.anular_pago(p, motivo="Otra vez")

    def test_un_gasto_al_contado_se_corrige_anulandolo(self, escena):
        [p] = gasto(escena).pagos.all()
        with pytest.raises(GastoNoModificable, match="anulando el gasto"):
            servicios.anular_pago(p, motivo="Error")

    def test_el_motivo_es_obligatorio(self, escena):
        g = self.por_pagar(escena)
        [p] = servicios.pagar_gasto(g, [pago(escena, "10")])
        with pytest.raises(GastoInvalido, match="motivo"):
            servicios.anular_pago(p, motivo="  ")


class TestAnular:
    def test_anular_un_gasto_devuelve_el_dinero_a_la_caja(self, escena):
        g = gasto(escena)
        servicios.anular_gasto(g, motivo="Era un viaje personal")
        g.refresh_from_db()
        assert (g.estado, g.saldo(), caja.saldo_de(escena.caja)) == ("ANULADO", dec("0"), dec("0"))
        assert all(p.anulado for p in g.pagos.all())
        assert MovimientoCaja.objects.get().estado == "ANULADO"

    def test_anular_pide_motivo_y_no_se_hace_dos_veces(self, escena):
        g = gasto(escena)
        with pytest.raises(MotivoObligatorio):
            servicios.anular_gasto(g, motivo="  ")
        servicios.anular_gasto(g, motivo="Error")
        with pytest.raises(DocumentoYaAnulado):
            servicios.anular_gasto(g, motivo="Otra vez")

    def test_un_gasto_anulado_no_se_paga(self, escena):
        g = factura(escena, forma_pago="POR_PAGAR", fecha_vencimiento=HOY, pagos=[])
        servicios.anular_gasto(g, motivo="Error")
        with pytest.raises(GastoNoModificable, match="anulado"):
            servicios.pagar_gasto(g, [pago(escena, "10")])

    def test_el_movimiento_del_gasto_solo_se_anula_desde_el_gasto(self, escena):
        from apps.caja.exceptions import MovimientoNoAnulable

        g = gasto(escena)
        [m] = MovimientoCaja.objects.filter(origen_id=g.pagos.get().pk)
        with pytest.raises(MovimientoNoAnulable, match="otro documento"):
            caja.anular_movimiento(m, motivo="Error")


class TestReparto:
    def test_se_reparte_entre_dos_empresas(self, escena):
        g = factura(
            escena,
            reparto=[
                RepartoEntrada(escena.empresa, dec("60")),
                RepartoEntrada(escena.otra, dec("40")),
            ],
        )
        partes = {
            r.empresa_id: (r.porcentaje, r.monto) for r in GastoReparto.objects.filter(gasto=g)
        }
        assert partes == {
            escena.empresa.pk: (dec("60"), dec("70.80")),
            escena.otra.pk: (dec("40"), dec("47.20")),
        }
        # El dinero y el comprobante son de la empresa titular.
        assert g.empresa_id == escena.empresa.pk
        assert caja.saldo_de(escena.caja) == dec("-118")

    def test_el_redondeo_se_lo_lleva_la_mayor_parte(self, escena):
        g = gasto(
            escena,
            no_gravado=dec("10"),
            pagos=[pago(escena, "10")],
            reparto=[
                RepartoEntrada(escena.empresa, dec("33.33")),
                RepartoEntrada(escena.otra, dec("66.67")),
            ],
        )
        montos = [r.monto for r in GastoReparto.objects.filter(gasto=g)]
        assert sum(montos) == dec("10")

    def test_todo_para_la_titular_es_no_repartir(self, escena):
        g = gasto(escena, reparto=[RepartoEntrada(escena.empresa, dec("100"))])
        assert not GastoReparto.objects.filter(gasto=g).exists()

    def test_debe_sumar_cien(self, escena):
        with pytest.raises(GastoInvalido, match="debe sumar exactamente 100%"):
            gasto(
                escena,
                reparto=[
                    RepartoEntrada(escena.empresa, dec("50")),
                    RepartoEntrada(escena.otra, dec("40")),
                ],
            )

    def test_validaciones_del_reparto(self, escena):
        with pytest.raises(GastoInvalido, match="dos veces"):
            gasto(
                escena,
                reparto=[
                    RepartoEntrada(escena.otra, dec("50")),
                    RepartoEntrada(escena.otra, dec("50")),
                ],
            )
        with pytest.raises(GastoInvalido, match="Cada porcentaje"):
            gasto(
                escena,
                reparto=[
                    RepartoEntrada(escena.empresa, dec("0")),
                    RepartoEntrada(escena.otra, dec("100")),
                ],
            )
        with pytest.raises(GastoInvalido, match="no es válida"):
            gasto(
                escena,
                reparto=[
                    RepartoEntrada(escena.empresa, dec("50")),
                    RepartoEntrada(escena.ajena, dec("50")),
                ],
            )
        assert not Gasto.objects.exists()
