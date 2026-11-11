"""El mapa de estados: cada paso permitido, las pausas y los pasos que piden motivo."""

import pytest

from apps.servicio_tecnico import flujo
from apps.servicio_tecnico.models import CategoriaServicio, EstadoOrden

E = EstadoOrden


def test_todos_los_estados_tienen_sus_destinos():
    assert set(flujo.TRANSICIONES) == set(EstadoOrden.values)


def test_los_13_estados_del_taller_y_las_3_salidas():
    assert len(EstadoOrden.values) == 16
    assert {E.NO_APROBADO, E.SIN_SOLUCION, E.ABANDONADO} <= set(EstadoOrden.values)


def test_el_camino_feliz_se_puede_recorrer_de_punta_a_punta():
    camino = [
        E.RECIBIDO,
        E.PENDIENTE_DIAGNOSTICO,
        E.EN_DIAGNOSTICO,
        E.DIAGNOSTICADO,
        E.PENDIENTE_APROBACION,
        E.APROBADO,
        E.EN_REPARACION,
        E.EN_PRUEBAS,
        E.TERMINADO,
        E.LISTO_ENTREGA,
        E.ENTREGADO,
    ]
    for desde, hacia in zip(camino, camino[1:], strict=False):
        assert hacia in flujo.destinos_posibles(desde), (desde, hacia)


def test_no_se_salta_de_recibido_a_entregado():
    assert E.ENTREGADO not in flujo.destinos_posibles(E.RECIBIDO)
    assert E.EN_REPARACION not in flujo.destinos_posibles(E.RECIBIDO)


def test_entregado_cierra_la_orden():
    assert flujo.destinos_posibles(E.ENTREGADO) == []


def test_toda_orden_tiene_salida_hacia_la_entrega():
    """Ningún estado intermedio deja la orden sin poder cerrarse."""
    for estado in EstadoOrden.values:
        visitados, pendientes = set(), [estado]
        while pendientes:
            actual = pendientes.pop()
            if actual in visitados:
                continue
            visitados.add(actual)
            pendientes.extend(flujo.TRANSICIONES[actual])
            if actual == E.PENDIENTE_REPUESTO:
                pendientes.extend(EstadoOrden.values)  # vuelve al estado desde el que se pausó
        assert E.ENTREGADO in visitados, estado


class TestPausaPorRepuesto:
    def test_se_puede_pausar_desde_diagnostico_mantenimiento_y_reparacion(self):
        for estado in (E.EN_DIAGNOSTICO, E.EN_MANTENIMIENTO, E.EN_REPARACION):
            assert E.PENDIENTE_REPUESTO in flujo.destinos_posibles(estado)

    def test_al_reanudar_solo_vuelve_al_estado_previo_o_se_cierra(self):
        destinos = flujo.destinos_posibles(E.PENDIENTE_REPUESTO, estado_previo=E.EN_REPARACION)
        assert destinos == [E.EN_REPARACION, E.SIN_SOLUCION]

    def test_reanudar_sigue_posible_aunque_el_tipo_de_servicio_cambie(self):
        destinos = flujo.destinos_posibles(
            E.PENDIENTE_REPUESTO,
            estado_previo=E.EN_REPARACION,
            categoria=CategoriaServicio.MANTENIMIENTO,
        )
        assert E.EN_REPARACION in destinos


class TestCategoriaDelServicio:
    def test_un_mantenimiento_no_pasa_por_reparacion(self):
        destinos = flujo.destinos_posibles(E.APROBADO, categoria=CategoriaServicio.MANTENIMIENTO)
        assert E.EN_MANTENIMIENTO in destinos
        assert E.EN_REPARACION not in destinos

    def test_una_reparacion_no_pasa_por_mantenimiento(self):
        destinos = flujo.destinos_posibles(E.APROBADO, categoria=CategoriaServicio.REPARACION)
        assert E.EN_REPARACION in destinos
        assert E.EN_MANTENIMIENTO not in destinos

    def test_sin_tipo_de_servicio_se_ofrecen_ambos(self):
        destinos = flujo.destinos_posibles(E.APROBADO)
        assert {E.EN_MANTENIMIENTO, E.EN_REPARACION} <= set(destinos)


class TestMotivo:
    @pytest.mark.parametrize(
        "hacia", [E.NO_APROBADO, E.SIN_SOLUCION, E.ABANDONADO, E.PENDIENTE_REPUESTO, E.APROBADO]
    )
    def test_las_salidas_y_pausas_piden_motivo(self, hacia):
        assert flujo.exige_motivo(E.EN_REPARACION, hacia)

    def test_volver_atras_pide_motivo(self):
        assert flujo.exige_motivo(E.EN_PRUEBAS, E.EN_REPARACION)
        assert flujo.exige_motivo(E.TERMINADO, E.EN_PRUEBAS)

    def test_avanzar_no_pide_motivo(self):
        assert not flujo.exige_motivo(E.EN_REPARACION, E.EN_PRUEBAS)
        assert not flujo.exige_motivo(E.LISTO_ENTREGA, E.ENTREGADO)


def test_el_tecnico_no_aprueba_ni_entrega():
    assert E.APROBADO not in flujo.ESTADOS_DE_TECNICO
    assert E.ENTREGADO not in flujo.ESTADOS_DE_TECNICO
    assert E.EN_REPARACION in flujo.ESTADOS_DE_TECNICO
