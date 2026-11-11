"""La garantía de un servicio entregado y el reingreso del equipo cuando falla de nuevo.

La garantía sale del tipo de servicio (días) y corre desde la entrega. Un reingreso por garantía es
una orden nueva ligada a la anterior: el equipo vuelve a pasar por diagnóstico y reparación, pero no
se le cobra al cliente.
"""

import logging
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import EstadoRegistro, Personal

from .exceptions import OrdenInvalida
from .models import EstadoOrden, OrdenServicio
from .recepcion import AccesorioEntrada, EquipoEntrada, recibir_equipo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EstadoGarantia:
    dias: int
    hasta: date | None
    vigente: bool
    dias_restantes: int


def estado_de(orden: OrdenServicio, hoy: date | None = None) -> EstadoGarantia:
    """Si la garantía sigue vigente y cuántos días le quedan (hoy incluido)."""
    hoy = hoy or timezone.localdate()
    if orden.garantia_hasta is None or orden.garantia_dias <= 0:
        return EstadoGarantia(orden.garantia_dias, orden.garantia_hasta, False, 0)
    restantes = (orden.garantia_hasta - hoy).days
    return EstadoGarantia(
        orden.garantia_dias, orden.garantia_hasta, restantes >= 0, max(restantes, 0)
    )


@transaction.atomic
def reingreso_por_garantia(
    original: OrdenServicio,
    *,
    falla_reportada: str,
    estado_fisico: str = "",
    clave_equipo: str = "",
    accesorios: list[AccesorioEntrada] | None = None,
    tecnico: Personal | None = None,
) -> OrdenServicio:
    """Recibe de nuevo el equipo de una orden entregada, dentro de su garantía."""
    base = (
        OrdenServicio.objects.select_for_update(of=("self",))
        .select_related("empresa", "cliente", "equipo", "sucursal", "tipo_servicio")
        .get(pk=original.pk)
    )
    if base.estado != EstadoOrden.ENTREGADO:
        raise OrdenInvalida("Solo se reingresa por garantía un equipo que ya se entregó.")
    if base.es_garantia:
        # La garantía no se encadena: el reingreso original es el que corresponde reabrir.
        raise OrdenInvalida("Esta orden ya es un reingreso por garantía: use la orden original.")
    garantia = estado_de(base)
    if garantia.dias <= 0:
        raise OrdenInvalida("Este servicio no tiene garantía.")
    if not garantia.vigente:
        raise OrdenInvalida(
            f"La garantía venció el {garantia.hasta:%d/%m/%Y}. "
            "Registre un ingreso normal si el cliente quiere que se revise."
        )
    if base.reingresos.exclude(estado=EstadoOrden.ENTREGADO).exists():
        raise OrdenInvalida("Ya hay un reingreso por garantía en curso para esta orden.")
    servicio = base.tipo_servicio
    if servicio is not None and servicio.estado != EstadoRegistro.ACTIVO:
        servicio = None  # el servicio ya no se ofrece: la orden nueva parte sin tipo

    orden = recibir_equipo(
        empresa=base.empresa,
        cliente=base.cliente,
        equipo=EquipoEntrada(existente=base.equipo),
        falla_reportada=falla_reportada,
        estado_fisico=estado_fisico,
        clave_equipo=clave_equipo,
        accesorios=accesorios or [],
        tecnico=tecnico,
        sucursal=base.sucursal,
        tipo_servicio=servicio,
        reingreso_de=base,
        acepta_whatsapp=base.acepta_whatsapp,
        motivo_inicial=f"Reingreso por garantía de {base.codigo}",
    )
    registrar(
        "servicio_tecnico.reingreso_garantia",
        recurso_tipo="orden_servicio",
        recurso_id=orden.pk,
        empresa_id=orden.empresa_id,
        resumen=f"{orden.codigo}: reingreso por garantía de {base.codigo}",
        detalle={"original": base.pk, "garantia_hasta": str(base.garantia_hasta)},
    )
    return orden
