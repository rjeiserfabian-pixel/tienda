"""Numeración y cambio de estado: historial, pausas, motivos y aislamiento por empresa."""

import pytest
from django.db import IntegrityError, transaction

from apps.auditoria.models import AuditoriaEvento
from apps.core.exceptions import DocumentoInmutableError
from apps.servicio_tecnico import servicios
from apps.servicio_tecnico.exceptions import MotivoRequerido, TransicionInvalida
from apps.servicio_tecnico.models import EstadoOrden, HistorialEstado, OrdenServicio

pytestmark = pytest.mark.django_db

E = EstadoOrden


class TestNumeracion:
    def test_cada_empresa_lleva_su_propia_cuenta(self, taller):
        a1 = [taller.orden().numero for _ in range(3)]
        a2 = [taller.orden(empresa=taller.otra_empresa).numero for _ in range(2)]
        assert a1 == [1, 2, 3]
        assert a2 == [1, 2]

    def test_el_codigo_se_muestra_con_ceros(self, taller):
        assert taller.orden().codigo == "OS-000001"

    def test_el_numero_no_se_repite_en_la_empresa(self, taller):
        orden = taller.orden()
        with pytest.raises(IntegrityError), transaction.atomic():
            taller.orden(numero=orden.numero)

    def test_cada_orden_tiene_su_codigo_publico_distinto(self, taller):
        a, b = taller.orden(), taller.orden()
        assert a.token_publico != b.token_publico
        assert len(a.token_publico) >= 12


class TestCambioDeEstado:
    def test_un_paso_valido_cambia_la_orden_y_deja_historial(self, taller):
        orden = taller.orden()
        servicios.cambiar_estado(orden, E.EN_DIAGNOSTICO)
        orden.refresh_from_db()
        assert orden.estado == E.EN_DIAGNOSTICO
        cambio = HistorialEstado.objects.get(orden=orden)
        assert (cambio.estado_anterior, cambio.estado_nuevo) == (E.RECIBIDO, E.EN_DIAGNOSTICO)
        assert cambio.creado_por_id == taller.e.usuario_id
        assert cambio.empresa_id == orden.empresa_id

    def test_deja_rastro_en_la_auditoria(self, taller):
        orden = taller.orden()
        servicios.cambiar_estado(orden, E.EN_DIAGNOSTICO)
        assert AuditoriaEvento.objects.filter(
            accion="servicio_tecnico.estado_cambiado", recurso_id=str(orden.pk)
        ).exists()

    def test_un_salto_no_permitido_se_rechaza_sin_tocar_nada(self, taller):
        orden = taller.orden()
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(orden, E.ENTREGADO)
        orden.refresh_from_db()
        assert orden.estado == E.RECIBIDO
        assert not HistorialEstado.objects.filter(orden=orden).exists()

    def test_un_estado_que_no_existe_se_rechaza(self, taller):
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(taller.orden(), "INVENTADO")

    def test_entregar_registra_la_fecha(self, taller):
        orden = taller.orden(estado=E.LISTO_ENTREGA)
        servicios.cambiar_estado(orden, E.ENTREGADO, via_entrega=True)
        orden.refresh_from_db()
        assert orden.fecha_entrega is not None
        assert orden.cerrada

    def test_entregado_solo_se_alcanza_entregando(self, taller):
        orden = taller.orden(estado=E.LISTO_ENTREGA)
        with pytest.raises(TransicionInvalida, match="Entregar equipo"):
            servicios.cambiar_estado(orden, E.ENTREGADO)

    def test_una_orden_entregada_no_se_mueve_mas(self, taller):
        orden = taller.orden(estado=E.ENTREGADO)
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(orden, E.LISTO_ENTREGA)


class TestMotivo:
    def test_una_salida_sin_motivo_se_rechaza(self, taller):
        orden = taller.orden(estado=E.EN_REPARACION)
        with pytest.raises(MotivoRequerido):
            servicios.cambiar_estado(orden, E.SIN_SOLUCION)
        with pytest.raises(MotivoRequerido):
            servicios.cambiar_estado(orden, E.SIN_SOLUCION, motivo="  ab ")

    def test_con_motivo_se_guarda_limpio(self, taller):
        orden = taller.orden(estado=E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.SIN_SOLUCION, motivo="  Placa   quemada, sin repuesto ")
        assert HistorialEstado.objects.get(orden=orden).motivo == "Placa quemada, sin repuesto"

    def test_volver_atras_pide_motivo(self, taller):
        orden = taller.orden(estado=E.EN_PRUEBAS)
        with pytest.raises(MotivoRequerido):
            servicios.cambiar_estado(orden, E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.EN_REPARACION, motivo="Falló la prueba de carga")
        assert orden.estado == E.EN_REPARACION


class TestPausaPorRepuesto:
    def test_pausa_y_reanuda_en_el_mismo_estado(self, taller):
        orden = taller.orden(estado=E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.PENDIENTE_REPUESTO, motivo="Falta la memoria RAM")
        orden.refresh_from_db()
        assert (orden.estado, orden.estado_previo) == (E.PENDIENTE_REPUESTO, E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.EN_REPARACION)
        orden.refresh_from_db()
        assert (orden.estado, orden.estado_previo) == (E.EN_REPARACION, "")

    def test_no_reanuda_en_otro_estado(self, taller):
        orden = taller.orden(estado=E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.PENDIENTE_REPUESTO, motivo="Falta la memoria RAM")
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(orden, E.EN_PRUEBAS)

    def test_un_mantenimiento_no_se_reanuda_como_reparacion(self, taller):
        orden = taller.orden(
            estado=E.APROBADO, tipo_servicio=taller.tipo_servicio("MANT_PREVENTIVO")
        )
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(orden, E.EN_REPARACION)
        servicios.cambiar_estado(orden, E.EN_MANTENIMIENTO)


class TestComoTecnico:
    def test_el_tecnico_diagnostica_y_repara(self, taller):
        orden = taller.orden(
            estado=E.PENDIENTE_DIAGNOSTICO,
            diagnostico="Fuente de poder quemada",
            trabajos_a_realizar="Cambiar la fuente",
        )
        servicios.cambiar_estado(orden, E.EN_DIAGNOSTICO, como_tecnico=True)
        servicios.cambiar_estado(orden, E.DIAGNOSTICADO, como_tecnico=True)
        assert orden.estado == E.DIAGNOSTICADO

    def test_el_tecnico_no_entrega_ni_aprueba(self, taller):
        listo = taller.orden(estado=E.LISTO_ENTREGA)
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(listo, E.ENTREGADO, como_tecnico=True)
        pendiente = taller.orden(estado=E.PENDIENTE_APROBACION)
        with pytest.raises(TransicionInvalida):
            servicios.cambiar_estado(pendiente, E.APROBADO, como_tecnico=True)


class TestHistorialInmutable:
    def test_no_se_edita_ni_se_borra(self, taller):
        orden = taller.orden()
        servicios.cambiar_estado(orden, E.EN_DIAGNOSTICO)
        cambio = HistorialEstado.objects.get(orden=orden)
        cambio.motivo = "cambiado"
        with pytest.raises(DocumentoInmutableError):
            cambio.save()
        with pytest.raises(DocumentoInmutableError):
            cambio.delete()


class TestAislamiento:
    def test_una_orden_de_otra_empresa_no_es_visible_sin_acceso(self, taller):
        from apps.core.tenant import establecer_contexto

        orden = taller.orden(empresa=taller.otra_empresa)
        establecer_contexto(taller.org.pk, [taller.empresa.pk], taller.e.usuario_id)
        assert not OrdenServicio.objects.filter(pk=orden.pk).exists()

    def test_la_clave_del_equipo_se_guarda_cifrada(self, taller):
        from django.db import connection

        orden = taller.orden(clave_equipo="patrón L")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT clave_equipo FROM servicio_tecnico_ordenservicio WHERE id = %s", [orden.pk]
            )
            guardado = cursor.fetchone()[0]
        assert "patrón" not in guardado
        orden.refresh_from_db()
        assert orden.clave_equipo == "patrón L"
