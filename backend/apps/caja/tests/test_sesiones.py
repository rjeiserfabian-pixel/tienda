import pytest

from apps.caja import servicios, sesiones
from apps.caja.exceptions import (
    MovimientoInvalido,
    MovimientoNoAnulable,
    SesionInvalida,
    SesionRequerida,
)
from apps.caja.models import MovimientoCaja, Origen, SesionCaja
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec

pytestmark = pytest.mark.django_db


@pytest.fixture
def escena(nuevo_usuario, compras, conceptos):
    """Un mostrador con sesión obligatoria, la caja principal de la tienda y un banco."""
    e = compras.entorno
    cajera = nuevo_usuario(e.e.org_a, "cajera", [e.e1])
    supervisora = nuevo_usuario(e.e.org_a, "supervisora", [e.e1])
    establecer_contexto(e.e.org_a.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)

    def caja(nombre, **extra):
        return CuentaFinanciera.objects.sin_ambito().create(
            empresa=e.e1, nombre=nombre, tipo="CAJA", moneda="PEN", **extra
        )

    return type(
        "Escena",
        (),
        {
            "empresa": e.e1,
            "mostrador": caja("Mostrador 1", rol_caja="MOSTRADOR", exige_sesion=True),
            "principal": caja("Caja principal", rol_caja="PRINCIPAL"),
            "banco": CuentaFinanciera.objects.sin_ambito().create(
                empresa=e.e1, nombre="BCP", tipo="BANCO", moneda="PEN", banco="BCP"
            ),
            "cajera": cajera,
            "otra": supervisora,
            "conceptos": conceptos,
        },
    )


def abrir(escena, **extra):
    datos = {"empresa": escena.empresa, "cuenta": escena.mostrador, "usuario": escena.cajera}
    return sesiones.abrir_sesion(**{**datos, **extra})


def ingreso(escena, cuenta, monto):
    return servicios.registrar_movimiento(
        empresa=escena.empresa,
        cuenta=cuenta,
        tipo="INGRESO",
        monto=dec(monto),
        concepto=escena.conceptos["APORTE_CAPITAL"],
    )


class TestAbrir:
    def test_abre_con_el_saldo_que_el_sistema_dice(self, escena):
        s = abrir(escena)
        assert (s.estado, s.numero, s.saldo_apertura, s.responsable_id) == (
            "ABIERTA", 1, dec("0"), escena.cajera.pk,
        )  # fmt: skip
        assert s.responsable_nombre

    def test_una_sola_sesion_abierta_por_caja(self, escena):
        abrir(escena)
        with pytest.raises(SesionInvalida, match="ya tiene una sesión abierta"):
            abrir(escena, usuario=escena.otra)

    def test_solo_las_cajas_de_efectivo_tienen_sesion(self, escena):
        with pytest.raises(SesionInvalida):
            abrir(escena, cuenta=escena.banco)

    def test_el_fondo_sale_de_la_caja_principal(self, escena):
        ingreso(escena, escena.principal, "1000")
        s = abrir(escena, fondo=dec("200"), desde_cuenta=escena.principal)
        assert s.fondo_entregado == dec("200")
        assert servicios.saldo_de(escena.mostrador) == dec("200")
        assert servicios.saldo_de(escena.principal) == dec("800")
        # El efectivo que entró al mostrador ya cuenta como de su sesión.
        assert MovimientoCaja.objects.filter(sesion=s, cuenta=escena.mostrador).count() == 1

    def test_el_fondo_pide_de_donde_sale(self, escena):
        with pytest.raises(MovimientoInvalido, match="de qué caja"):
            abrir(escena, fondo=dec("50"))
        assert SesionCaja.objects.count() == 0

    def test_el_fondo_no_sale_de_un_banco(self, escena):
        with pytest.raises(MovimientoInvalido):
            abrir(escena, fondo=dec("50"), desde_cuenta=escena.banco)
        assert SesionCaja.objects.count() == 0


class TestSesionObligatoria:
    def test_sin_sesion_no_se_mueve_efectivo(self, escena):
        with pytest.raises(SesionRequerida, match="Abra la sesión"):
            ingreso(escena, escena.mostrador, "10")

    def test_con_sesion_el_movimiento_queda_en_ella(self, escena):
        s = abrir(escena)
        m = ingreso(escena, escena.mostrador, "10")
        assert m.sesion_id == s.pk

    def test_una_caja_sin_exigencia_no_la_pide(self, escena):
        assert ingreso(escena, escena.principal, "10").sesion_id is None

    def test_un_banco_nunca_la_pide(self, escena):
        assert ingreso(escena, escena.banco, "10").sesion_id is None

    def test_si_la_caja_sin_exigencia_tiene_sesion_se_liga(self, escena):
        s = abrir(escena, cuenta=escena.principal)
        assert ingreso(escena, escena.principal, "10").sesion_id == s.pk

    def test_cerrada_la_sesion_se_vuelve_a_pedir(self, escena):
        s = abrir(escena)
        sesiones.cerrar_sesion(s, conteo={}, usuario=escena.cajera)
        with pytest.raises(SesionRequerida):
            ingreso(escena, escena.mostrador, "10")


class TestConteo:
    def test_suma_billetes_y_monedas(self):
        limpio, total = sesiones.contar({"200": 1, "50": 2, "0.5": 3, "0.1": 0}, "PEN")
        assert total == dec("301.50")
        assert limpio == {"200": 1, "50": 2, "0.5": 3}

    def test_las_denominaciones_dependen_de_la_moneda(self):
        assert sesiones.contar({"100": 2}, "USD")[1] == dec("200")
        with pytest.raises(MovimientoInvalido, match="No existe la denominación"):
            sesiones.contar({"0.5": 1}, "USD")

    @pytest.mark.parametrize("malo", [{"7": 1}, {"abc": 1}, {"10": -1}, {"10": 1.5}, {"10": True}])
    def test_rechaza_conteos_invalidos(self, malo):
        with pytest.raises(MovimientoInvalido):
            sesiones.contar(malo, "PEN")


class TestArqueo:
    def test_compara_lo_contado_con_lo_esperado_sin_cerrar(self, escena):
        s = abrir(escena)
        ingreso(escena, escena.mostrador, "300")
        a = sesiones.arquear_sesion(s, conteo={"100": 2}, usuario=escena.cajera)
        assert (a.tipo, a.esperado, a.contado, a.diferencia) == (
            "PARCIAL", dec("300"), dec("200"), dec("-100"),
        )  # fmt: skip
        s.refresh_from_db()
        assert s.estado == "ABIERTA"
        assert not MovimientoCaja.objects.filter(origen_tipo=Origen.ARQUEO).exists()

    def test_solo_el_responsable_o_un_supervisor_cuenta(self, escena):
        s = abrir(escena)
        with pytest.raises(SesionInvalida, match="solo esa persona"):
            sesiones.arquear_sesion(s, conteo={}, usuario=escena.otra)
        sesiones.arquear_sesion(s, conteo={}, usuario=escena.otra, supervisor=True)


class TestCierre:
    def test_cierre_cuadrado_no_genera_movimientos(self, escena):
        s = abrir(escena)
        ingreso(escena, escena.mostrador, "250")
        cerrada = sesiones.cerrar_sesion(s, conteo={"200": 1, "50": 1}, usuario=escena.cajera)
        assert (cerrada.estado, cerrada.diferencia, cerrada.contado_cierre) == (
            "CERRADA", dec("0"), dec("250"),
        )  # fmt: skip
        assert cerrada.cerrada_por_id == escena.cajera.pk
        assert not MovimientoCaja.objects.filter(origen_tipo=Origen.ARQUEO).exists()

    def test_el_faltante_se_asienta_como_egreso(self, escena):
        s = abrir(escena)
        ingreso(escena, escena.mostrador, "250")
        sesiones.cerrar_sesion(
            s, conteo={"200": 1}, usuario=escena.cajera, observacion="Vuelto mal dado"
        )
        m = MovimientoCaja.objects.get(origen_tipo=Origen.ARQUEO)
        assert (m.tipo, m.monto, m.concepto.codigo, m.sesion_id) == (
            "EGRESO", dec("50"), "FALTANTE_CAJA", s.pk,
        )  # fmt: skip
        assert servicios.saldo_de(escena.mostrador) == dec("200")  # lo que se contó

    def test_el_sobrante_se_asienta_como_ingreso(self, escena):
        s = abrir(escena)
        ingreso(escena, escena.mostrador, "250")
        sesiones.cerrar_sesion(
            s, conteo={"200": 2}, usuario=escena.cajera, observacion="Cliente dejó propina"
        )
        m = MovimientoCaja.objects.get(origen_tipo=Origen.ARQUEO)
        assert (m.tipo, m.monto, m.concepto.codigo) == ("INGRESO", dec("150"), "SOBRANTE_CAJA")
        assert servicios.saldo_de(escena.mostrador) == dec("400")

    def test_una_diferencia_exige_explicarla(self, escena):
        s = abrir(escena)
        ingreso(escena, escena.mostrador, "250")
        with pytest.raises(MovimientoInvalido, match="Explique la diferencia"):
            sesiones.cerrar_sesion(s, conteo={"200": 1}, usuario=escena.cajera)
        s.refresh_from_db()
        assert s.estado == "ABIERTA"

    def test_no_se_cierra_dos_veces(self, escena):
        s = abrir(escena)
        sesiones.cerrar_sesion(s, conteo={}, usuario=escena.cajera)
        with pytest.raises(SesionInvalida, match="ya está cerrada"):
            sesiones.cerrar_sesion(s, conteo={}, usuario=escena.cajera)

    def test_otra_persona_no_cierra_la_caja_ajena(self, escena):
        s = abrir(escena)
        with pytest.raises(SesionInvalida):
            sesiones.cerrar_sesion(s, conteo={}, usuario=escena.otra)
        sesiones.cerrar_sesion(s, conteo={}, usuario=escena.otra, supervisor=True)

    def test_un_movimiento_de_sesion_cerrada_no_se_anula(self, escena):
        s = abrir(escena)
        m = ingreso(escena, escena.mostrador, "100")
        sesiones.cerrar_sesion(s, conteo={"100": 1}, usuario=escena.cajera)
        with pytest.raises(MovimientoNoAnulable, match="sesión de caja ya cerrada"):
            servicios.anular_movimiento(m, motivo="Error")


class TestReabrir:
    def cerrada_con_faltante(self, escena):
        s = abrir(escena)
        ingreso(escena, escena.mostrador, "250")
        sesiones.cerrar_sesion(s, conteo={"200": 1}, usuario=escena.cajera, observacion="Falta")
        return s

    def test_reabrir_deshace_la_diferencia_del_cierre(self, escena):
        s = self.cerrada_con_faltante(escena)
        r = sesiones.reabrir_sesion(s, motivo="Se olvidó un cobro", usuario=escena.otra)
        assert (r.estado, r.reaperturas, r.diferencia, r.cerrada_en) == ("ABIERTA", 1, None, None)
        assert MovimientoCaja.objects.get(origen_tipo=Origen.ARQUEO).estado == "ANULADO"
        assert servicios.saldo_de(escena.mostrador) == dec("250")
        ingreso(escena, escena.mostrador, "10")  # vuelve a admitir movimientos

    def test_pide_motivo(self, escena):
        s = self.cerrada_con_faltante(escena)
        with pytest.raises(MovimientoInvalido, match="motivo"):
            sesiones.reabrir_sesion(s, motivo="  ", usuario=escena.otra)

    def test_solo_la_ultima_y_si_no_hay_otra_abierta(self, escena):
        primera = self.cerrada_con_faltante(escena)
        segunda = abrir(escena)
        with pytest.raises(SesionInvalida, match="otra sesión abierta"):
            sesiones.reabrir_sesion(primera, motivo="Error", usuario=escena.otra)
        sesiones.cerrar_sesion(segunda, conteo={"200": 1}, usuario=escena.cajera)
        with pytest.raises(SesionInvalida, match="Solo se puede reabrir la última"):
            sesiones.reabrir_sesion(primera, motivo="Error", usuario=escena.otra)

    def test_una_abierta_no_se_reabre(self, escena):
        s = abrir(escena)
        with pytest.raises(SesionInvalida, match="no está cerrada"):
            sesiones.reabrir_sesion(s, motivo="Error", usuario=escena.otra)


def test_un_pago_de_compra_en_efectivo_exige_la_sesion_de_la_caja(compras):
    """La regla vale para todo el sistema: pagar una compra con la caja cerrada se rechaza."""
    compras.caja.exige_sesion = True
    compras.caja.save()
    with pytest.raises(SesionRequerida):
        compras.comprar()
    assert not MovimientoCaja.objects.exists()
