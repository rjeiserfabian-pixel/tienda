"""Qué puede hacer una persona con una orden concreta.

El permiso solo dice «puede ejecutar servicios»; su alcance dice sobre cuáles. Quien ejecuta lo
asignado solo trabaja las órdenes cuyo técnico es él. Lo usan la API (para negar) y la ficha (para
mostrar solo los botones que sirven).
"""

from dataclasses import dataclass

from apps.seguridad.services import permisos_engine as motor

from . import flujo
from .models import EstadoOrden, OrdenServicio

CAMBIAR_ESTADO = "SERVICIOS.CAMBIAR_ESTADO"
EJECUTAR = "SERVICIOS.EJECUTAR"
ENTREGAR = "SERVICIOS.ENTREGAR"
GESTIONAR = "SERVICIOS.GESTIONAR"
PRESUPUESTAR = "SERVICIOS.PRESUPUESTAR"
RECEPCIONAR = "SERVICIOS.RECEPCIONAR"

AMPLIOS = {"EMPRESA", "ORGANIZACION"}


@dataclass(frozen=True, slots=True)
class Capacidades:
    recepcion: bool  # mueve cualquier estado (aprobar, avisar, cerrar)
    trabaja: bool  # diagnostica y repara esta orden
    entrega: bool
    asigna: bool
    presupuesta: bool  # arma presupuestos y ve los precios
    recibe: bool  # recibe equipos (y los reingresos por garantía)

    @property
    def ve_importes(self) -> bool:
        """Quien trabaja el equipo no ve precios; recepción y quien presupuesta, sí."""
        return self.presupuesta or self.recepcion

    @property
    def cambia_estado(self) -> bool:
        return self.recepcion or self.trabaja


def _trabaja(usuario, orden: OrdenServicio) -> bool:
    alcance = motor.alcance_de(usuario, EJECUTAR, orden.empresa_id)
    if alcance in AMPLIOS:
        return True
    if alcance == "ASIGNADO":
        return bool(orden.tecnico_id) and orden.tecnico.usuario_id == usuario.pk
    if alcance == "PROPIO":
        return orden.creado_por_id == usuario.pk
    return False  # un alcance que no se sabe resolver no concede nada


def capacidades_de(usuario, orden: OrdenServicio) -> Capacidades:
    empresa = orden.empresa_id
    return Capacidades(
        recepcion=motor.tiene_permiso(usuario, CAMBIAR_ESTADO, empresa),
        trabaja=_trabaja(usuario, orden),
        entrega=motor.tiene_permiso(usuario, ENTREGAR, empresa),
        asigna=motor.tiene_permiso(usuario, GESTIONAR, empresa),
        presupuesta=motor.tiene_permiso(usuario, PRESUPUESTAR, empresa),
        recibe=motor.tiene_permiso(usuario, RECEPCIONAR, empresa),
    )


def destinos_para(usuario, orden: OrdenServicio) -> list[dict]:
    """Los estados a los que ESTA persona puede pasar la orden, con lo que pide cada paso."""
    poder = capacidades_de(usuario, orden)
    if orden.estado == EstadoOrden.ENTREGADO or not poder.cambia_estado:
        return []
    categoria = orden.tipo_servicio.categoria if orden.tipo_servicio_id else ""
    destinos = []
    for estado in flujo.destinos_posibles(
        orden.estado,
        estado_previo=orden.estado_previo,
        categoria=categoria,
        es_garantia=orden.es_garantia,
    ):
        if estado == EstadoOrden.APROBADO:
            continue  # se aprueba desde el presupuesto: ahí queda cómo respondió el cliente
        if estado == EstadoOrden.ENTREGADO:
            continue  # se entrega con «Entregar equipo»: cobra los comprobantes y cierra la orden
        # Lo que no es del técnico lo mueve recepción.
        if estado not in flujo.ESTADOS_DE_TECNICO and not poder.recepcion:
            continue
        destinos.append(
            {
                "estado": estado,
                "nombre": EstadoOrden(estado).label,
                "pide_motivo": flujo.exige_motivo(orden.estado, estado),
            }
        )
    return destinos
