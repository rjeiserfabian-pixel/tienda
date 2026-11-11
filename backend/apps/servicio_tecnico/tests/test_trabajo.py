"""Diagnóstico, asignación del técnico y avisos al cliente (reglas, sin pasar por la API)."""

from decimal import Decimal

import pytest

from apps.core.exceptions import DocumentoInmutableError
from apps.mantenimiento.models import EstadoRegistro, Personal
from apps.servicio_tecnico import servicios, trabajo
from apps.servicio_tecnico.exceptions import (
    DiagnosticoIncompleto,
    OrdenInvalida,
    TransicionInvalida,
)
from apps.servicio_tecnico.models import AvisoCliente, EstadoOrden

pytestmark = pytest.mark.django_db

E = EstadoOrden


class TestDiagnostico:
    def test_guarda_lo_que_concluye_el_tecnico(self, taller):
        orden = taller.orden(estado=E.EN_DIAGNOSTICO)
        trabajo.registrar_diagnostico(
            orden,
            diagnostico="  Fuente   de poder\n\n quemada ",
            trabajos_a_realizar="Cambiar la fuente",
            horas_estimadas="1.5",
            nota_interna="Pedir la fuente a Lima",
            nota_cliente="Se cambia una pieza",
            tipo_servicio=taller.tipo_servicio("REPARACION_HW"),
        )
        orden.refresh_from_db()
        assert orden.diagnostico == "Fuente de poder\n\nquemada"
        assert orden.horas_estimadas == Decimal("1.5")
        assert orden.tipo_servicio.codigo == "REPARACION_HW"

    def test_solo_cambia_lo_que_viene(self, taller):
        orden = taller.orden(diagnostico="Uno", nota_interna="Interna")
        trabajo.registrar_diagnostico(orden, nota_cliente="Hola")
        orden.refresh_from_db()
        assert (orden.diagnostico, orden.nota_interna, orden.nota_cliente) == (
            "Uno",
            "Interna",
            "Hola",
        )

    def test_las_horas_se_validan(self, taller):
        orden = taller.orden()
        for malo in ("abc", "-1", "1000", "1.55", "NaN"):
            with pytest.raises(OrdenInvalida, match="horas"):
                trabajo.registrar_diagnostico(orden, horas_estimadas=malo)
        trabajo.registrar_diagnostico(orden, horas_estimadas="")
        orden.refresh_from_db()
        assert orden.horas_estimadas is None

    def test_dato_desconocido(self, taller):
        with pytest.raises(OrdenInvalida, match="no válido"):
            trabajo.registrar_diagnostico(taller.orden(), estado="ENTREGADO")

    def test_una_orden_entregada_no_se_toca(self, taller):
        orden = taller.orden(estado=E.ENTREGADO)
        with pytest.raises(OrdenInvalida, match="entregada"):
            trabajo.registrar_diagnostico(orden, diagnostico="Tarde")

    def test_el_tipo_de_servicio_debe_estar_activo(self, taller):
        inactivo = taller.tipo_servicio("FORMATEO")
        inactivo.estado = EstadoRegistro.INACTIVO
        inactivo.save()
        with pytest.raises(OrdenInvalida, match="tipo de servicio"):
            trabajo.registrar_diagnostico(taller.orden(), tipo_servicio=inactivo)

    def test_para_dar_el_diagnostico_por_realizado_hay_que_escribirlo(self, taller):
        orden = taller.orden(estado=E.EN_DIAGNOSTICO)
        with pytest.raises(DiagnosticoIncompleto):
            servicios.cambiar_estado(orden, E.DIAGNOSTICADO)
        trabajo.registrar_diagnostico(orden, diagnostico="Fuente de poder quemada")
        with pytest.raises(DiagnosticoIncompleto):  # faltan los trabajos
            servicios.cambiar_estado(orden, E.DIAGNOSTICADO)
        trabajo.registrar_diagnostico(orden, trabajos_a_realizar="Cambiar la fuente")
        servicios.cambiar_estado(orden, E.DIAGNOSTICADO)
        assert orden.estado == E.DIAGNOSTICADO

    def test_aprobar_solo_se_registra_desde_el_presupuesto(self, taller):
        orden = taller.orden(estado=E.PENDIENTE_APROBACION)
        with pytest.raises(TransicionInvalida, match="presupuesto"):
            servicios.cambiar_estado(orden, E.APROBADO, motivo="Aprobó por WhatsApp")


class TestAsignar:
    def test_asigna_y_quita_al_tecnico(self, taller):
        otro = Personal.objects.create(
            empresa=taller.empresa,
            tipo_documento="DNI",
            numero_documento="42345678",
            nombres="Luz",
            apellidos="Vega",
            area="TECNICO",
        )
        orden = taller.orden()
        trabajo.asignar_tecnico(orden, otro)
        orden.refresh_from_db()
        assert orden.tecnico_id == otro.pk
        trabajo.asignar_tecnico(orden, None)
        orden.refresh_from_db()
        assert orden.tecnico_id is None

    def test_el_tecnico_debe_ser_de_la_empresa_y_del_area_tecnica(self, taller):
        orden = taller.orden(empresa=taller.otra_empresa, tecnico=None)
        with pytest.raises(OrdenInvalida, match="técnico"):
            trabajo.asignar_tecnico(orden, taller.personal)  # es de la otra empresa
        administrativo = Personal.objects.create(
            empresa=taller.empresa,
            tipo_documento="DNI",
            numero_documento="41234567",
            nombres="Eva",
            apellidos="Ríos",
            area="ADMINISTRACION",
        )
        with pytest.raises(OrdenInvalida, match="técnico"):
            trabajo.asignar_tecnico(taller.orden(), administrativo)


class TestAvisos:
    def test_deja_constancia_con_quien_y_cuando(self, taller):
        orden = taller.orden()
        aviso = trabajo.registrar_aviso(
            orden, medio="WHATSAPP", mensaje="  Ya está listo   su equipo "
        )
        assert aviso.mensaje == "Ya está listo su equipo"
        assert aviso.creado_por_id == taller.e.usuario_id
        assert AvisoCliente.objects.filter(orden=orden).count() == 1

    def test_valida_medio_y_mensaje(self, taller):
        orden = taller.orden()
        with pytest.raises(OrdenInvalida, match="medio"):
            trabajo.registrar_aviso(orden, medio="PALOMA", mensaje="Hola cliente")
        with pytest.raises(OrdenInvalida, match="qué se le dijo"):
            trabajo.registrar_aviso(orden, medio="LLAMADA", mensaje=" ab ")

    def test_no_se_edita_ni_se_borra(self, taller):
        aviso = trabajo.registrar_aviso(taller.orden(), medio="LLAMADA", mensaje="Se le llamó")
        aviso.mensaje = "otro"
        with pytest.raises(DocumentoInmutableError):
            aviso.save()
        with pytest.raises(DocumentoInmutableError):
            aviso.delete()

    def test_una_orden_entregada_no_recibe_avisos(self, taller):
        with pytest.raises(OrdenInvalida, match="entregada"):
            trabajo.registrar_aviso(
                taller.orden(estado=E.ENTREGADO), medio="LLAMADA", mensaje="Gracias por venir"
            )
