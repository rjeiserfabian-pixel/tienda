"""Reglas de la orden de servicio: numerarla y cambiarle el estado.

Cada operación va en una sola transacción: si algo falla, no queda nada a medias.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Correlativo
from apps.organizacion.models import Empresa

from . import flujo, notificaciones, repuestos
from .exceptions import (
    AbandonoNoPermitido,
    DiagnosticoIncompleto,
    MotivoRequerido,
    PresupuestoRequerido,
    TransicionInvalida,
)
from .models import AvisoCliente, EstadoOrden, HistorialEstado, OrdenServicio, PresupuestoOrden

logger = logging.getLogger(__name__)

MOTIVO_MINIMO = 5
MOTIVO_MAXIMO = 500
DIAGNOSTICO_MINIMO = 10
DIAS_PARA_ABANDONO = 30  # sin recoger (o sin respuesta) antes de poder darlo por abandonado
USAN_REPUESTOS = frozenset({EstadoOrden.EN_REPARACION, EstadoOrden.EN_MANTENIMIENTO})
LIBERAN_REPUESTOS = frozenset(
    {EstadoOrden.NO_APROBADO, EstadoOrden.SIN_SOLUCION, EstadoOrden.ABANDONADO}
)
TRABAJOS_MINIMO = 5


def siguiente_numero(empresa: Empresa) -> int:
    """El próximo número de orden de la empresa. Debe llamarse dentro de una transacción."""
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"servicio_tecnico:orden:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def esperando_desde(orden: OrdenServicio):
    """Desde cuándo está la orden en su estado actual (la última vez que entró a él)."""
    ultimo = (
        HistorialEstado.objects.filter(orden=orden, estado_nuevo=orden.estado)
        .order_by("-id")
        .first()
    )
    return ultimo.creado_en if ultimo else orden.fecha_ingreso


def dias_esperando(orden: OrdenServicio) -> int:
    return max((timezone.now() - esperando_desde(orden)).days, 0)


def exigir_aviso_y_espera(orden: OrdenServicio) -> None:
    """Dar por abandonado un equipo exige haber avisado al cliente y haber esperado el plazo."""
    if not AvisoCliente.objects.filter(orden=orden).exists():
        raise AbandonoNoPermitido(
            "Antes de darlo por abandonado hay que avisar al cliente y dejar el aviso registrado."
        )
    dias = dias_esperando(orden)
    if dias < DIAS_PARA_ABANDONO:
        raise AbandonoNoPermitido(
            f"Lleva {dias} días en «{orden.get_estado_display()}»: se puede dar por abandonado "
            f"desde los {DIAS_PARA_ABANDONO} días."
        )


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


@transaction.atomic
def cambiar_estado(
    orden: OrdenServicio,
    nuevo: str,
    *,
    motivo: str = "",
    como_tecnico: bool = False,
    via_aprobacion: bool = False,
    via_entrega: bool = False,
) -> OrdenServicio:
    """Pasa la orden a ``nuevo`` si el flujo lo permite y deja el cambio en el historial.

    «Aprobado» solo se alcanza al registrar la aprobación del presupuesto (``via_aprobacion``) y
    «Entregado», al entregar el equipo y cobrar (``via_entrega``).
    ``como_tecnico`` limita los destinos a los que el técnico marca por su cuenta (diagnosticar,
    reparar, probar…); aprobar, avisar o entregar es de recepción.
    """
    # Se bloquea la fila: dos personas moviendo la misma orden a la vez no se pisan.
    actual = (
        OrdenServicio.objects.select_for_update(of=("self",))
        .select_related("tipo_servicio", "cliente", "empresa")
        .get(pk=orden.pk)
    )
    if nuevo not in EstadoOrden.values:
        raise TransicionInvalida("El estado indicado no existe.")
    categoria = actual.tipo_servicio.categoria if actual.tipo_servicio_id else ""
    posibles = flujo.destinos_posibles(
        actual.estado,
        estado_previo=actual.estado_previo,
        categoria=categoria,
        es_garantia=actual.es_garantia,
    )
    if nuevo not in posibles:
        raise TransicionInvalida(
            f"Una orden «{actual.get_estado_display()}» no puede pasar a "
            f"«{EstadoOrden(nuevo).label}»."
        )
    if como_tecnico and nuevo not in flujo.ESTADOS_DE_TECNICO:
        raise TransicionInvalida(
            f"Pasar a «{EstadoOrden(nuevo).label}» lo hace recepción, no el técnico."
        )
    motivo = _texto(motivo, MOTIVO_MAXIMO)
    if flujo.exige_motivo(actual.estado, nuevo) and len(motivo) < MOTIVO_MINIMO:
        raise MotivoRequerido("Explique el motivo de este cambio de estado.")
    if nuevo == EstadoOrden.DIAGNOSTICADO and (
        len(actual.diagnostico.strip()) < DIAGNOSTICO_MINIMO
        or len(actual.trabajos_a_realizar.strip()) < TRABAJOS_MINIMO
    ):
        raise DiagnosticoIncompleto(
            "Para dar el diagnóstico por realizado, escriba el diagnóstico y los trabajos."
        )

    if nuevo == EstadoOrden.APROBADO and not via_aprobacion:
        raise TransicionInvalida("La aprobación se registra desde el presupuesto de la orden.")
    if nuevo == EstadoOrden.ABANDONADO:
        exigir_aviso_y_espera(actual)
    if nuevo == EstadoOrden.ENTREGADO and not via_entrega:
        raise TransicionInvalida("La entrega se registra con «Entregar equipo» (cobra y cierra).")
    if (
        nuevo == EstadoOrden.PENDIENTE_APROBACION
        and not PresupuestoOrden.objects.filter(orden=actual, vigente=True).exists()
    ):
        raise PresupuestoRequerido("Arme el presupuesto antes de enviarlo a aprobación.")

    anterior = actual.estado
    # El stock acompaña al trabajo: los repuestos se usan al empezar y se devuelven si no sigue.
    if nuevo in USAN_REPUESTOS:
        repuestos.consumir_reservados(actual)
    elif nuevo in LIBERAN_REPUESTOS:
        repuestos.liberar_reservados(actual, motivo or EstadoOrden(nuevo).label)
    actual.estado = nuevo
    # La pausa recuerda de dónde viene; al reanudar o cerrarse, se olvida.
    actual.estado_previo = anterior if nuevo == EstadoOrden.PENDIENTE_REPUESTO else ""
    campos = ["estado", "estado_previo"]
    if nuevo == EstadoOrden.ENTREGADO:
        actual.fecha_entrega = timezone.now()
        campos.append("fecha_entrega")
    actual.save(update_fields=campos)

    notificaciones.avisar_por_estado(actual, nuevo)
    HistorialEstado.objects.create(
        empresa_id=actual.empresa_id,
        orden=actual,
        estado_anterior=anterior,
        estado_nuevo=nuevo,
        motivo=motivo,
    )
    registrar(
        "servicio_tecnico.estado_cambiado",
        recurso_tipo="orden_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo}: {EstadoOrden(anterior).label} → {EstadoOrden(nuevo).label}",
        detalle={"desde": anterior, "hacia": nuevo, "motivo": motivo},
    )
    logger.info(
        "orden_servicio_estado_cambiado",
        extra={"orden_id": actual.pk, "desde": anterior, "hacia": nuevo},
    )
    # Quien llamó sigue viendo la orden actualizada sin tener que volver a leerla.
    orden.estado, orden.estado_previo = actual.estado, actual.estado_previo
    orden.fecha_entrega = actual.fecha_entrega
    return actual
