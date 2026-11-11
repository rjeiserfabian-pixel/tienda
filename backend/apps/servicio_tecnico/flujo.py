"""Los estados de una orden de servicio y a cuáles puede pasar cada uno.

Es solo la regla (sin base de datos), para que la pantalla muestre los pasos posibles y el servidor
rechace los demás con la misma lógica. Los 13 estados del taller más tres de salida que evitan
órdenes que nunca se pueden cerrar: no aprobado o cancelado, sin solución y abandonado.

«Pendiente de repuesto» es una pausa: al reanudar, la orden vuelve al estado desde el que se pausó.
"""

from .models import CategoriaServicio, EstadoOrden

E = EstadoOrden

TRANSICIONES: dict[str, frozenset[str]] = {
    E.RECIBIDO: frozenset({E.PENDIENTE_DIAGNOSTICO, E.EN_DIAGNOSTICO, E.NO_APROBADO}),
    E.PENDIENTE_DIAGNOSTICO: frozenset({E.EN_DIAGNOSTICO, E.NO_APROBADO}),
    E.EN_DIAGNOSTICO: frozenset(
        {E.DIAGNOSTICADO, E.PENDIENTE_REPUESTO, E.SIN_SOLUCION, E.NO_APROBADO}
    ),
    E.DIAGNOSTICADO: frozenset({E.PENDIENTE_APROBACION, E.EN_DIAGNOSTICO, E.SIN_SOLUCION}),
    E.PENDIENTE_APROBACION: frozenset({E.APROBADO, E.NO_APROBADO, E.DIAGNOSTICADO, E.ABANDONADO}),
    E.APROBADO: frozenset(
        {E.EN_MANTENIMIENTO, E.EN_REPARACION, E.PENDIENTE_REPUESTO, E.NO_APROBADO}
    ),
    E.EN_MANTENIMIENTO: frozenset({E.EN_PRUEBAS, E.PENDIENTE_REPUESTO, E.SIN_SOLUCION}),
    E.EN_REPARACION: frozenset({E.EN_PRUEBAS, E.PENDIENTE_REPUESTO, E.SIN_SOLUCION}),
    # Al reanudar solo puede volver a su estado previo (ver ``destinos_posibles``) o cerrarse.
    E.PENDIENTE_REPUESTO: frozenset({E.SIN_SOLUCION}),
    E.EN_PRUEBAS: frozenset({E.TERMINADO, E.EN_REPARACION, E.EN_MANTENIMIENTO}),
    E.TERMINADO: frozenset({E.LISTO_ENTREGA, E.EN_PRUEBAS}),
    E.LISTO_ENTREGA: frozenset({E.ENTREGADO, E.ABANDONADO}),
    E.SIN_SOLUCION: frozenset({E.LISTO_ENTREGA, E.ABANDONADO}),
    E.NO_APROBADO: frozenset({E.LISTO_ENTREGA, E.ABANDONADO}),
    E.ABANDONADO: frozenset({E.LISTO_ENTREGA}),
    E.ENTREGADO: frozenset(),
}

# Estados en los que la orden espera al cliente: su respuesta o que venga a recoger el equipo.
ESTADOS_QUE_ESPERAN = frozenset(
    {E.PENDIENTE_APROBACION, E.LISTO_ENTREGA, E.NO_APROBADO, E.SIN_SOLUCION}
)

# Estados desde los que el equipo ya no se trabaja: la orden está cerrada o por cerrarse.
ESTADOS_FINALES = frozenset({E.ENTREGADO})

# Lo que puede marcar el técnico por su cuenta; el resto (aprobación, entrega…) es de recepción.
ESTADOS_DE_TECNICO = frozenset(
    {
        E.EN_DIAGNOSTICO,
        E.DIAGNOSTICADO,
        E.EN_MANTENIMIENTO,
        E.EN_REPARACION,
        E.PENDIENTE_REPUESTO,
        E.EN_PRUEBAS,
        E.TERMINADO,
        E.SIN_SOLUCION,
    }
)

# Llegar a estos estados siempre se explica: algo no salió como se esperaba (o, al aprobar, cómo
# respondió el cliente: WhatsApp, llamada, firma…).
DESTINOS_CON_MOTIVO = frozenset(
    {E.NO_APROBADO, E.SIN_SOLUCION, E.ABANDONADO, E.PENDIENTE_REPUESTO, E.APROBADO}
)
# Volver atrás en el proceso también.
RETROCESOS = frozenset(
    {
        (E.DIAGNOSTICADO, E.EN_DIAGNOSTICO),
        (E.PENDIENTE_APROBACION, E.DIAGNOSTICADO),
        (E.EN_PRUEBAS, E.EN_REPARACION),
        (E.EN_PRUEBAS, E.EN_MANTENIMIENTO),
        (E.TERMINADO, E.EN_PRUEBAS),
    }
)


def destinos_posibles(
    estado: str, *, estado_previo: str = "", categoria: str = "", es_garantia: bool = False
) -> list[str]:
    """Estados a los que puede pasar una orden, en el orden del proceso.

    ``categoria`` es la del tipo de servicio: un mantenimiento no pasa por «En reparación» ni al
    revés. Si aún no se sabe el tipo de servicio, se ofrecen ambos. Un reingreso por garantía no
    espera la aprobación del cliente: tras el diagnóstico puede empezar a trabajarse.
    """
    permitidos = set(TRANSICIONES.get(estado, ()))
    if es_garantia and estado == E.DIAGNOSTICADO:
        permitidos |= {E.APROBADO, E.EN_REPARACION, E.EN_MANTENIMIENTO}
    if categoria == CategoriaServicio.MANTENIMIENTO:
        permitidos.discard(E.EN_REPARACION)
    elif categoria == CategoriaServicio.REPARACION:
        permitidos.discard(E.EN_MANTENIMIENTO)
    if estado == E.PENDIENTE_REPUESTO and estado_previo:
        permitidos.add(estado_previo)  # reanudar siempre es posible, aunque cambie el tipo
    return [e for e in EstadoOrden.values if e in permitidos]


def exige_motivo(desde: str, hacia: str) -> bool:
    return hacia in DESTINOS_CON_MOTIVO or (desde, hacia) in RETROCESOS
