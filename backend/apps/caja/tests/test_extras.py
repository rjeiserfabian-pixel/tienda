"""Extras de caja: bancarización, avisos, vouchers y caja chica."""

import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.caja import adjuntos, alertas, bancarizacion, caja_chica, conciliacion, servicios
from apps.caja.exceptions import (
    AdjuntoInvalido,
    MovimientoNoAnulable,
    RendicionInvalida,
)
from apps.caja.models import (
    AdjuntoMovimiento,
    EstadoCuenta,
    MovimientoCaja,
    RendicionCaja,
    SesionCaja,
)
from apps.compras.servicios import CuotasEntrada, LineaEntrada
from apps.core.exceptions import DocumentoYaAnulado
from apps.core.tenant import establecer_contexto
from apps.mantenimiento.models import CuentaFinanciera

from .conftest import dec

pytestmark = pytest.mark.django_db

HOY = timezone.localdate()


@pytest.fixture
def escena(nuevo_usuario, compras, conceptos, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    e = compras.entorno
    usuario = nuevo_usuario(e.e.org_a, "extras", [e.e1])
    establecer_contexto(e.e.org_a.pk, [e.e1.pk, e.e2.pk], e.e.usuario_id)

    def cuenta(nombre, **extra):
        datos = {"tipo": "CAJA", "moneda": "PEN", **extra}
        return CuentaFinanciera.objects.sin_ambito().create(empresa=e.e1, nombre=nombre, **datos)

    return type(
        "Escena",
        (),
        {
            "compras": compras,
            "empresa": e.e1,
            "usuario": usuario,
            "conceptos": conceptos,
            "caja": compras.caja,
            "caja_usd": compras.caja_usd,
            "banco": cuenta("BCP", tipo="BANCO", banco="BCP"),
            "chica": cuenta("Caja chica", rol_caja="CAJA_CHICA", fondo_inicial=dec("500")),
            "principal": cuenta("Principal", rol_caja="PRINCIPAL"),
            "cuenta": cuenta,
        },
    )


def mover(escena, cuenta, tipo, monto, codigo=None, fecha=None, **extra):
    codigo = codigo or ("DEPOSITO_RECIBIDO" if tipo == "INGRESO" else "GASTOS_VARIOS")
    return servicios.registrar_movimiento(
        empresa=escena.empresa,
        cuenta=cuenta,
        tipo=tipo,
        monto=dec(monto),
        concepto=escena.conceptos[codigo],
        fecha=fecha or HOY,
        **extra,
    )


class TestBancarizacion:
    def test_los_umbrales_en_soles_y_dolares(self, escena):
        assert not bancarizacion.supera_umbral(dec("1999.99"), "PEN")
        assert bancarizacion.supera_umbral(dec("2000"), "PEN")
        assert not bancarizacion.supera_umbral(dec("499.99"), "USD")
        assert bancarizacion.supera_umbral(dec("500"), "USD")

    def test_solo_el_efectivo_grande_cuenta(self, escena):
        grande = mover(escena, escena.caja, "EGRESO", "2000")
        mover(escena, escena.caja, "EGRESO", "1999.99")
        mover(escena, escena.banco, "EGRESO", "5000")  # por banco: bancarizado
        mover(escena, escena.caja_usd, "INGRESO", "400")
        dolares = mover(escena, escena.caja_usd, "INGRESO", "500")
        lista = list(bancarizacion.sin_bancarizar(escena.empresa, HOY, HOY))
        assert {m.pk for m in lista} == {grande.pk, dolares.pk}
        assert bancarizacion.es_sin_bancarizar(grande)
        assert not bancarizacion.es_sin_bancarizar(mover(escena, escena.caja, "EGRESO", "10"))

    def test_los_pasos_internos_no_cuentan(self, escena):
        mover(escena, escena.caja, "INGRESO", "9000")
        from apps.caja import transferencias

        transferencias.registrar_transferencia(
            empresa=escena.empresa,
            cuenta_origen=escena.caja,
            cuenta_destino=escena.banco,
            monto=dec("5000"),
        )
        # Solo queda el ingreso de 9000, no la salida de 5000 hacia el banco.
        assert [m.monto for m in bancarizacion.sin_bancarizar(escena.empresa, HOY, HOY)] == [
            dec("9000")
        ]

    def test_respeta_el_rango(self, escena):
        mover(escena, escena.caja, "EGRESO", "3000", fecha=HOY - timedelta(days=40))
        assert not bancarizacion.sin_bancarizar(escena.empresa, HOY - timedelta(days=30), HOY)


class TestAlertas:
    def codigos(self, escena):
        return [a["codigo"] for a in alertas.alertas(escena.empresa)]

    def test_sin_novedades_no_hay_avisos(self, escena):
        assert alertas.alertas(escena.empresa) == []

    def test_saldo_negativo_es_critico(self, escena):
        mover(escena, escena.caja, "EGRESO", "50")
        [aviso] = [a for a in alertas.alertas(escena.empresa) if a["codigo"] == "saldo_negativo"]
        assert aviso["nivel"] == "critica"
        assert "Caja soles" in aviso["titulo"] and "-50.00" in aviso["detalle"]

    def test_saldo_bajo_solo_si_hay_minimo(self, escena):
        mover(escena, escena.caja, "INGRESO", "100")
        assert "saldo_bajo" not in self.codigos(escena)
        escena.caja.saldo_minimo = dec("300")
        escena.caja.save()
        assert "saldo_bajo" in self.codigos(escena)
        mover(escena, escena.caja, "INGRESO", "250")
        assert "saldo_bajo" not in self.codigos(escena)

    def test_sesion_abierta_hace_mucho(self, escena):
        from apps.caja import sesiones

        s = sesiones.abrir_sesion(
            empresa=escena.empresa, cuenta=escena.caja, usuario=escena.usuario
        )
        assert "sesion_larga" not in self.codigos(escena)
        SesionCaja.objects.filter(pk=s.pk).update(abierta_en=timezone.now() - timedelta(hours=20))
        assert "sesion_larga" in self.codigos(escena)

    def test_extracto_abierto_hace_dias(self, escena):
        texto = f"Fecha;Descripción;Cargo;Abono\n{HOY:%d/%m/%Y};Comisión;5.00;\n"
        archivo = SimpleUploadedFile("e.csv", texto.encode())
        e = conciliacion.importar(
            empresa=escena.empresa, cuenta=escena.banco, archivo=archivo, usuario=escena.usuario
        )
        assert "extracto_sin_conciliar" not in self.codigos(escena)
        EstadoCuenta.objects.filter(pk=e.pk).update(creado_en=timezone.now() - timedelta(days=9))
        assert "extracto_sin_conciliar" in self.codigos(escena)

    def test_efectivo_grande_y_cuotas_vencidas(self, escena):
        mover(escena, escena.caja, "INGRESO", "5000")
        assert "sin_bancarizar" in self.codigos(escena)
        c = escena.compras
        linea = LineaEntrada(c.entorno.producto(), dec(1), dec(100))
        compra = c.comprar(
            [linea], forma_pago="CREDITO", cuotas=CuotasEntrada(2, c.entorno.hoy, c.mensual)
        )
        assert "cuotas_vencidas" not in self.codigos(escena)
        compra.cuotas.update(fecha_vencimiento=HOY - timedelta(days=3))
        assert "cuotas_vencidas" in self.codigos(escena)

    def test_van_primero_los_criticos(self, escena):
        mover(escena, escena.caja, "EGRESO", "10")
        mover(escena, escena.caja_usd, "INGRESO", "600")
        niveles = [a["nivel"] for a in alertas.alertas(escena.empresa)]
        assert niveles == sorted(niveles, key={"critica": 0, "aviso": 1, "info": 2}.get)


def imagen(formato="PNG", tamano=(40, 30), **extra) -> SimpleUploadedFile:
    salida = io.BytesIO()
    Image.new("RGB", tamano, (200, 30, 30)).save(salida, format=formato, **extra)
    return SimpleUploadedFile(f"foto.{formato.lower()}", salida.getvalue())


class TestAdjuntos:
    def test_una_foto_se_guarda_como_webp_sin_metadatos(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        a = adjuntos.agregar(m, imagen("JPEG"), escena.usuario)
        assert (a.tipo_contenido, a.nombre_original) == ("image/webp", "foto.jpeg")
        assert a.archivo.name.endswith(".webp") and "foto" not in a.archivo.name
        with Image.open(a.archivo.path) as guardada:
            assert guardada.format == "WEBP" and not guardada.getexif()

    def test_una_foto_grande_se_reduce(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        a = adjuntos.agregar(m, imagen("PNG", (4000, 1000)), escena.usuario)
        with Image.open(a.archivo.path) as guardada:
            assert max(guardada.size) == adjuntos.LADO_MAXIMO

    def test_un_pdf_se_guarda_tal_cual(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        pdf = SimpleUploadedFile("recibo.pdf", b"%PDF-1.4\n%contenido\n")
        a = adjuntos.agregar(m, pdf, escena.usuario)
        assert (a.tipo_contenido, a.archivo.name.endswith(".pdf")) == ("application/pdf", True)

    @pytest.mark.parametrize(
        "contenido",
        [b"<script>alert(1)</script>", b"MZ\x90\x00 ejecutable", b"", b"\x89PNG\r\n\x1a\nroto"],
    )
    def test_rechaza_lo_que_no_es_foto_ni_pdf(self, escena, contenido):
        m = mover(escena, escena.banco, "EGRESO", "30")
        archivo = SimpleUploadedFile("voucher.png", contenido or b"x")
        with pytest.raises(AdjuntoInvalido):
            adjuntos.agregar(m, archivo, escena.usuario)
        assert not AdjuntoMovimiento.objects.exists()

    def test_rechaza_lo_demasiado_pesado(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        grande = SimpleUploadedFile("a.pdf", b"%PDF-" + b"0" * adjuntos.TAMANO_MAXIMO)
        with pytest.raises(AdjuntoInvalido, match="5 MB"):
            adjuntos.agregar(m, grande, escena.usuario)

    def test_tope_por_movimiento(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        for _ in range(adjuntos.MAX_POR_MOVIMIENTO):
            adjuntos.agregar(m, imagen(), escena.usuario)
        with pytest.raises(AdjuntoInvalido, match="hasta"):
            adjuntos.agregar(m, imagen(), escena.usuario)

    def test_un_movimiento_anulado_no_recibe_adjuntos(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        servicios.anular_movimiento(m, motivo="Error")
        with pytest.raises(MovimientoNoAnulable):
            adjuntos.agregar(m, imagen(), escena.usuario)

    def test_quitar_borra_el_archivo(self, escena):
        m = mover(escena, escena.banco, "EGRESO", "30")
        a = adjuntos.agregar(m, imagen(), escena.usuario)
        ruta = a.archivo.path
        adjuntos.eliminar(a, escena.usuario)
        import os

        assert not os.path.exists(ruta)
        assert not AdjuntoMovimiento.objects.filter(movimiento=m).exists()


class TestCajaChica:
    def preparar(self, escena):
        """Fondo de 500 con tres gastos (100 en total) y 1000 en la caja principal."""
        mover(escena, escena.chica, "INGRESO", "500", codigo="APORTE_CAPITAL")
        mover(escena, escena.principal, "INGRESO", "1000", codigo="APORTE_CAPITAL")
        return [mover(escena, escena.chica, "EGRESO", m) for m in ("30", "45", "25")]

    def rendir(self, escena, **extra):
        datos = {
            "empresa": escena.empresa,
            "cuenta": escena.chica,
            "cuenta_origen": escena.principal,
            "movimientos_ids": None,
            "usuario": escena.usuario,
        }
        return caja_chica.rendir(**{**datos, **extra})

    def test_el_resumen_dice_cuanto_falta_reponer(self, escena):
        self.preparar(escena)
        [fila] = caja_chica.resumen(escena.empresa)
        assert (fila["fondo"], fila["saldo"], fila["faltante"]) == (
            dec("500"), dec("400"), dec("100"),
        )  # fmt: skip
        assert (fila["por_rendir_cantidad"], fila["por_rendir_total"]) == (3, dec("100"))

    def test_rendir_repone_el_fondo(self, escena):
        self.preparar(escena)
        r = self.rendir(escena, glosa="Octubre")
        assert (r.numero, r.total, r.cantidad, r.estado) == (1, dec("100"), 3, "EMITIDO")
        assert servicios.saldo_de(escena.chica) == dec("500")
        assert servicios.saldo_de(escena.principal) == dec("900")
        assert not caja_chica.gastos_por_rendir(escena.chica).exists()
        assert r.transferencia.monto_origen == dec("100")
        with pytest.raises(RendicionInvalida, match="No hay gastos"):
            self.rendir(escena)

    def test_rendir_solo_algunos_gastos(self, escena):
        gastos = self.preparar(escena)
        r = self.rendir(escena, movimientos_ids=[gastos[0].pk, gastos[2].pk])
        assert (r.total, r.cantidad) == (dec("55"), 2)
        quedan = list(caja_chica.gastos_por_rendir(escena.chica))
        assert [g.pk for g in quedan] == [gastos[1].pk]

    def test_un_gasto_se_rinde_una_sola_vez(self, escena):
        gastos = self.preparar(escena)
        self.rendir(escena, movimientos_ids=[gastos[0].pk])
        with pytest.raises(RendicionInvalida, match="ya se rindió"):
            self.rendir(escena, movimientos_ids=[gastos[0].pk, gastos[1].pk])

    def test_valida_los_gastos_y_las_cuentas(self, escena):
        gastos = self.preparar(escena)
        ajeno = mover(escena, escena.principal, "EGRESO", "10")
        with pytest.raises(RendicionInvalida, match="no es de esta caja chica"):
            self.rendir(escena, movimientos_ids=[ajeno.pk])
        with pytest.raises(RendicionInvalida, match="repetidos"):
            self.rendir(escena, movimientos_ids=[gastos[0].pk, gastos[0].pk])
        with pytest.raises(RendicionInvalida, match="otra caja"):
            self.rendir(escena, cuenta_origen=escena.chica)
        with pytest.raises(RendicionInvalida, match="misma moneda"):
            self.rendir(escena, cuenta_origen=escena.caja_usd)
        with pytest.raises(RendicionInvalida, match="caja chica"):
            self.rendir(escena, cuenta=escena.principal, cuenta_origen=escena.chica)
        assert not RendicionCaja.objects.exists()

    def test_anular_libera_los_gastos_y_deshace_la_reposicion(self, escena):
        self.preparar(escena)
        r = self.rendir(escena)
        caja_chica.anular(r, motivo="Faltó un comprobante")
        r.refresh_from_db()
        assert r.estado == "ANULADO"
        assert servicios.saldo_de(escena.chica) == dec("400")
        assert servicios.saldo_de(escena.principal) == dec("1000")
        assert caja_chica.gastos_por_rendir(escena.chica).count() == 3
        again = self.rendir(escena)  # se puede rendir de nuevo
        assert (again.numero, again.total) == (2, dec("100"))
        with pytest.raises(DocumentoYaAnulado):
            caja_chica.anular(r, motivo="Otra vez")

    def test_los_ingresos_no_son_gastos(self, escena):
        self.preparar(escena)
        assert all(g.tipo == "EGRESO" for g in caja_chica.gastos_por_rendir(escena.chica))
        assert MovimientoCaja.objects.filter(cuenta=escena.chica, tipo="INGRESO").count() == 1
