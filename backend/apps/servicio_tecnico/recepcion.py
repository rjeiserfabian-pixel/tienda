"""Recibir un equipo: crea la orden de servicio en «Equipo recibido», con su historial.

Todo ocurre en una sola transacción: si algo falla no queda ni el equipo ni la orden.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Area, Cliente, EstadoRegistro, Personal
from apps.organizacion.models import Empresa, Estado, Sucursal

from . import notificaciones
from .exceptions import OrdenInvalida
from .models import (
    AccesorioEquipo,
    Equipo,
    EstadoOrden,
    HistorialEstado,
    ItemChecklist,
    OrdenAccesorio,
    OrdenRevision,
    OrdenServicio,
    Prioridad,
    ResultadoRevision,
    TipoEquipo,
    TipoServicio,
)
from .servicios import siguiente_numero

logger = logging.getLogger(__name__)

FALLA_MINIMA = 5
FALLA_MAXIMA = 1000
MAXIMO_ACCESORIOS = 30


@dataclass(frozen=True, slots=True)
class EquipoEntrada:
    """El equipo que llega: uno ya registrado (``existente``) o los datos de uno nuevo."""

    existente: Equipo | None = None
    tipo: TipoEquipo | None = None
    marca: str = ""
    modelo: str = ""
    numero_serie: str = ""
    color: str = ""
    descripcion: str = ""


@dataclass(frozen=True, slots=True)
class AccesorioEntrada:
    """Un accesorio que deja el cliente: del catálogo (``accesorio``) o escrito a mano."""

    accesorio: AccesorioEquipo | None = None
    nombre: str = ""
    cantidad: int = 1
    detalle: str = ""


@dataclass(frozen=True, slots=True)
class RevisionEntrada:
    """Cómo se encontró una de las revisiones de ingreso."""

    item: ItemChecklist
    resultado: str = ResultadoRevision.NO_PROBADO
    observacion: str = ""


def _limpio(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _equipo_para(empresa: Empresa, cliente: Cliente, entrada: EquipoEntrada) -> Equipo:
    if entrada.existente is not None:
        equipo = entrada.existente
        if equipo.organizacion_id != empresa.organizacion_id or equipo.cliente_id != cliente.pk:
            raise OrdenInvalida("El equipo elegido no es de este cliente.")
        return equipo
    tipo = entrada.tipo
    if tipo is None or tipo.organizacion_id != empresa.organizacion_id:
        raise OrdenInvalida("Elija el tipo de equipo.")
    if tipo.estado != EstadoRegistro.ACTIVO:
        raise OrdenInvalida("El tipo de equipo está inactivo.")
    marca, modelo = _limpio(entrada.marca, 60), _limpio(entrada.modelo, 80)
    if not marca and not modelo:
        raise OrdenInvalida("Indique al menos la marca o el modelo del equipo.")
    return Equipo.objects.create(
        organizacion_id=empresa.organizacion_id,
        cliente=cliente,
        tipo=tipo,
        marca=marca,
        modelo=modelo,
        numero_serie=_limpio(entrada.numero_serie, 80).upper(),
        color=_limpio(entrada.color, 40),
        descripcion=_limpio(entrada.descripcion, 250),
    )


def _accesorios_de(orden: OrdenServicio, entradas, organizacion_id: int) -> list[OrdenAccesorio]:
    if len(entradas) > MAXIMO_ACCESORIOS:
        raise OrdenInvalida(f"Se pueden anotar hasta {MAXIMO_ACCESORIOS} accesorios.")
    filas = []
    for e in entradas:
        catalogo = e.accesorio
        if catalogo is not None and (
            catalogo.organizacion_id != organizacion_id or catalogo.estado != EstadoRegistro.ACTIVO
        ):
            raise OrdenInvalida("Hay accesorios que no están disponibles.")
        nombre = catalogo.nombre if catalogo else _limpio(e.nombre, 80)
        if not nombre:
            raise OrdenInvalida("Escriba el nombre del accesorio.")
        if not isinstance(e.cantidad, int) or not 1 <= e.cantidad <= 99:
            raise OrdenInvalida(f"La cantidad de «{nombre}» debe estar entre 1 y 99.")
        filas.append(
            OrdenAccesorio(
                empresa_id=orden.empresa_id,
                orden=orden,
                accesorio=catalogo,
                nombre=nombre,
                cantidad=e.cantidad,
                detalle=_limpio(e.detalle, 150),
            )
        )
    return filas


def _revisiones_de(orden: OrdenServicio, entradas, organizacion_id: int) -> list[OrdenRevision]:
    vistas: set[int] = set()
    filas = []
    for e in entradas:
        item = e.item
        if item.organizacion_id != organizacion_id or item.estado != EstadoRegistro.ACTIVO:
            raise OrdenInvalida("Hay revisiones que no están disponibles.")
        if item.pk in vistas:
            raise OrdenInvalida(f"«{item.nombre}» está repetida.")
        vistas.add(item.pk)
        if e.resultado not in ResultadoRevision.values:
            raise OrdenInvalida(f"El resultado de «{item.nombre}» no es válido.")
        filas.append(
            OrdenRevision(
                empresa_id=orden.empresa_id,
                orden=orden,
                item=item,
                nombre=item.nombre,
                resultado=e.resultado,
                observacion=_limpio(e.observacion, 250),
            )
        )
    return filas


def _validar_orden(
    empresa, cliente, falla, prioridad, fecha_promesa, tecnico, sucursal, tipo_servicio
) -> None:
    org = empresa.organizacion_id
    if empresa.estado != Estado.ACTIVO:
        raise OrdenInvalida("La empresa no está activa.")
    if cliente.organizacion_id != org or cliente.estado != EstadoRegistro.ACTIVO:
        raise OrdenInvalida("Elija un cliente activo.")
    if len(falla) < FALLA_MINIMA:
        raise OrdenInvalida("Describa la falla que reporta el cliente.")
    if prioridad not in Prioridad.values:
        raise OrdenInvalida("La prioridad no es válida.")
    if fecha_promesa is not None and (
        not isinstance(fecha_promesa, date)
        or isinstance(fecha_promesa, datetime)
        or fecha_promesa < timezone.localdate()
    ):
        raise OrdenInvalida("La fecha prometida no puede ser anterior a hoy.")
    if tecnico is not None and (
        tecnico.empresa_id != empresa.pk
        or tecnico.area != Area.TECNICO
        or tecnico.estado != EstadoRegistro.ACTIVO
    ):
        raise OrdenInvalida("El técnico debe ser personal técnico activo de esta empresa.")
    if sucursal is not None and (
        sucursal.empresa_id != empresa.pk or sucursal.estado != Estado.ACTIVO
    ):
        raise OrdenInvalida("La sucursal no es de esta empresa.")
    if tipo_servicio is not None and (
        tipo_servicio.organizacion_id != org or tipo_servicio.estado != EstadoRegistro.ACTIVO
    ):
        raise OrdenInvalida("El tipo de servicio no está disponible.")


@transaction.atomic
def recibir_equipo(
    *,
    empresa: Empresa,
    cliente: Cliente,
    equipo: EquipoEntrada,
    falla_reportada: str,
    estado_fisico: str = "",
    clave_equipo: str = "",
    accesorios=(),
    revisiones=(),
    tecnico: Personal | None = None,
    sucursal: Sucursal | None = None,
    tipo_servicio: TipoServicio | None = None,
    prioridad: str = Prioridad.NORMAL,
    fecha_promesa: date | None = None,
    reingreso_de: OrdenServicio | None = None,
    acepta_whatsapp: bool = False,
    motivo_inicial: str = "Equipo recibido",
) -> OrdenServicio:
    """Registra el ingreso de un equipo: crea la orden en «Equipo recibido» con su historial.

    Un reingreso por garantía (``reingreso_de``) queda ligado a la orden anterior y no se cobra.
    """
    falla = _limpio(falla_reportada, FALLA_MAXIMA)
    _validar_orden(
        empresa, cliente, falla, prioridad, fecha_promesa, tecnico, sucursal, tipo_servicio
    )
    org = empresa.organizacion_id

    equipo_orden = _equipo_para(empresa, cliente, equipo)
    orden = OrdenServicio.objects.create(
        empresa=empresa,
        numero=siguiente_numero(empresa),
        sucursal=sucursal,
        cliente=cliente,
        equipo=equipo_orden,
        tipo_servicio=tipo_servicio,
        tecnico=tecnico,
        prioridad=prioridad,
        falla_reportada=falla,
        estado_fisico=_limpio(estado_fisico, 1000),
        clave_equipo=str(clave_equipo or "").strip()[:100],
        fecha_promesa=fecha_promesa,
        reingreso_de=reingreso_de,
        es_garantia=reingreso_de is not None,
        acepta_whatsapp=bool(acepta_whatsapp),
    )
    OrdenAccesorio.objects.bulk_create(_accesorios_de(orden, list(accesorios), org))
    OrdenRevision.objects.bulk_create(_revisiones_de(orden, list(revisiones), org))
    HistorialEstado.objects.create(
        empresa=empresa,
        orden=orden,
        estado_anterior="",
        estado_nuevo=EstadoOrden.RECIBIDO,
        motivo=_limpio(motivo_inicial, 500) or "Equipo recibido",
    )
    notificaciones.avisar_por_estado(orden, EstadoOrden.RECIBIDO)
    registrar(
        "servicio_tecnico.orden_recibida",
        recurso_tipo="orden_servicio",
        recurso_id=orden.pk,
        empresa_id=empresa.pk,
        resumen=f"{orden.codigo}: {equipo_orden} de {cliente.nombre}",
        detalle={"equipo": equipo_orden.pk, "tecnico": getattr(tecnico, "pk", None)},
    )
    logger.info("orden_servicio_recibida", extra={"orden_id": orden.pk, "empresa_id": empresa.pk})
    return orden
