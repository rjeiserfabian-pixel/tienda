"""El stock de los repuestos de una orden: reservar al aprobar, usar al trabajar, devolver.

No hay un «stock reservado» aparte: reservar es un traspaso real del almacén de venta al almacén
«Servicio técnico» de la empresa que surte el repuesto. Así el Kardex lo registra, el costo viaja
con la mercadería y nadie puede venderlo por error. Usarlo es una salida de ese almacén; devolverlo
es anular el traspaso (el stock vuelve al almacén de origen).
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.inventario import movimientos
from apps.inventario.exceptions import AnulacionNoPermitida, StockInsuficiente
from apps.inventario.models import OrigenMovimiento, SaldoStock, TipoMovimiento
from apps.inventario.movimientos import LineaNueva
from apps.mantenimiento.models import Almacen, EstadoRegistro, TipoAlmacen
from apps.organizacion.models import Empresa, Estado, Sucursal

from .exceptions import PresupuestoInvalido, RepuestosPendientes
from .models import EstadoRepuesto, OrdenServicio, RepuestoOrden

logger = logging.getLogger(__name__)

CODIGO_ALMACEN = "SERV"
NOMBRE_ALMACEN = "Servicio técnico"


@dataclass
class ResultadoReserva:
    reservados: int = 0
    pendientes: list[str] = field(default_factory=list)  # lo que no alcanzó, con el motivo


def almacen_servicio(empresa: Empresa) -> Almacen:
    """El almacén donde la empresa guarda lo reservado para el taller (lo crea si no existe)."""
    existente = (
        Almacen.objects.sin_ambito()
        .filter(empresa=empresa, tipo=TipoAlmacen.SERVICIO_TECNICO, estado=EstadoRegistro.ACTIVO)
        .order_by("id")
        .first()
    )
    if existente is not None:
        return existente
    sucursal = (
        Sucursal.objects.sin_ambito()
        .filter(empresa=empresa, estado=Estado.ACTIVO)
        .order_by("id")
        .first()
    )
    if sucursal is None:
        raise PresupuestoInvalido(
            f"{empresa.razon_social} no tiene una sucursal activa para crear su almacén "
            "de Servicio técnico."
        )
    usados = set(
        Almacen.objects.sin_ambito(incluir_eliminados=True)
        .filter(empresa=empresa)
        .values_list("codigo", flat=True)
    )
    codigo, n = CODIGO_ALMACEN, 1
    while codigo.lower() in {u.lower() for u in usados}:
        n += 1
        codigo = f"{CODIGO_ALMACEN}{n}"
    nombres = {
        a.lower()
        for a in Almacen.objects.sin_ambito(incluir_eliminados=True)
        .filter(empresa=empresa)
        .values_list("nombre", flat=True)
    }
    nombre = NOMBRE_ALMACEN
    while nombre.lower() in nombres:
        nombre = f"{nombre} (taller)"
    almacen = Almacen.objects.sin_ambito().create(
        empresa=empresa,
        codigo=codigo,
        nombre=nombre,
        sucursal=sucursal,
        tipo=TipoAlmacen.SERVICIO_TECNICO,
        permite_venta=False,
    )
    registrar(
        "servicio_tecnico.almacen_creado",
        recurso_tipo="almacen",
        recurso_id=almacen.pk,
        empresa_id=empresa.pk,
        resumen=f"Almacén «{almacen.nombre}» creado para los repuestos del taller",
    )
    return almacen


def _almacen_de_origen(r: RepuestoOrden) -> Almacen | None:
    """El almacén de venta de la empresa con más stock de ese producto, si alcanza para todo."""
    saldo = (
        SaldoStock.objects.sin_ambito()
        .filter(
            empresa_id=r.empresa_id,
            producto_id=r.producto_id,
            cantidad__gte=r.cantidad,
            almacen__permite_venta=True,
            almacen__estado=EstadoRegistro.ACTIVO,
        )
        .exclude(almacen__tipo=TipoAlmacen.SERVICIO_TECNICO)
        .select_related("almacen")
        .order_by("-cantidad", "almacen_id")
        .first()
    )
    return saldo.almacen if saldo else None


def _pendientes(orden: OrdenServicio) -> list[RepuestoOrden]:
    return list(
        RepuestoOrden.objects.select_for_update(of=("self",))
        .select_related("producto", "empresa")
        .filter(
            presupuesto__orden=orden,
            presupuesto__vigente=True,
            estado=EstadoRepuesto.PENDIENTE,
        )
        .order_by("id")
    )


def reservar_pendientes(orden: OrdenServicio) -> ResultadoReserva:
    """Reserva lo que se pueda del presupuesto vigente; lo que no alcance queda pendiente.

    Es seguro repetirla: por ejemplo cuando llega el repuesto que faltaba.
    """
    resultado = ResultadoReserva()
    hoy = timezone.localdate()
    with transaction.atomic():
        for r in _pendientes(orden):
            origen = _almacen_de_origen(r)
            if origen is None:
                resultado.pendientes.append(f"{r.producto.nombre}: no hay stock suficiente")
                continue
            destino = almacen_servicio(r.empresa)
            try:
                with transaction.atomic():  # un faltante no deshace lo ya reservado
                    salida, _ = movimientos.registrar_traspaso(
                        empresa=r.empresa,
                        origen=origen,
                        destino=destino,
                        fecha=hoy,
                        lineas=[LineaNueva(producto=r.producto, cantidad=r.cantidad)],
                        observacion=f"Reserva para {orden.codigo}",
                    )
            except StockInsuficiente:
                resultado.pendientes.append(f"{r.producto.nombre}: no hay stock suficiente")
                continue
            r.estado = EstadoRepuesto.RESERVADO
            r.almacen_origen = origen
            r.traspaso_reserva = salida
            r.save(update_fields=["estado", "almacen_origen", "traspaso_reserva"])
            resultado.reservados += 1
    if resultado.reservados or resultado.pendientes:
        registrar(
            "servicio_tecnico.repuestos_reservados",
            recurso_tipo="orden_servicio",
            recurso_id=orden.pk,
            empresa_id=orden.empresa_id,
            resumen=f"{orden.codigo}: {resultado.reservados} repuesto(s) reservado(s)",
            detalle={"pendientes": resultado.pendientes},
        )
    return resultado


def exigir_reservados(orden: OrdenServicio) -> None:
    """Para empezar el trabajo no puede faltar ningún repuesto del presupuesto."""
    faltan = list(
        RepuestoOrden.objects.filter(
            presupuesto__orden=orden,
            presupuesto__vigente=True,
            estado=EstadoRepuesto.PENDIENTE,
        ).select_related("producto")
    )
    if faltan:
        nombres = ", ".join(r.producto.nombre for r in faltan)
        raise RepuestosPendientes(
            f"Faltan repuestos por reservar: {nombres}. Si espera que lleguen, "
            "pase la orden a «Pendiente de repuesto»."
        )


def consumir_reservados(orden: OrdenServicio) -> int:
    """Saca del almacén de Servicio técnico los repuestos reservados: ya se van a usar."""
    exigir_reservados(orden)
    reservados = list(
        RepuestoOrden.objects.select_for_update(of=("self",))
        .select_related("producto", "empresa")
        .filter(
            presupuesto__orden=orden,
            presupuesto__vigente=True,
            estado=EstadoRepuesto.RESERVADO,
        )
        .order_by("id")
    )
    if not reservados:
        return 0
    hoy = timezone.localdate()
    por_empresa: dict[int, list[RepuestoOrden]] = {}
    for r in reservados:
        por_empresa.setdefault(r.empresa_id, []).append(r)
    for grupo in por_empresa.values():
        empresa = grupo[0].empresa
        salida = movimientos.registrar_movimiento(
            empresa=empresa,
            almacen=almacen_servicio(empresa),
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.SERVICIO_TECNICO,
            fecha=hoy,
            lineas=[LineaNueva(producto=r.producto, cantidad=r.cantidad) for r in grupo],
            cliente=orden.cliente,
            observacion=f"Repuestos de la orden {orden.codigo}",
            referencia_tipo="orden_servicio",
            referencia_id=orden.pk,
        )
        valores = list(salida.lineas.order_by("orden", "id"))
        for r, valor in zip(grupo, valores, strict=True):
            r.estado = EstadoRepuesto.CONSUMIDO
            r.movimiento_consumo = salida
            r.costo_total = valor.costo_total
            r.save(update_fields=["estado", "movimiento_consumo", "costo_total"])
    registrar(
        "servicio_tecnico.repuestos_usados",
        recurso_tipo="orden_servicio",
        recurso_id=orden.pk,
        empresa_id=orden.empresa_id,
        resumen=f"{orden.codigo}: {len(reservados)} repuesto(s) usado(s)",
    )
    return len(reservados)


def liberar_reservados(orden: OrdenServicio, motivo: str) -> int:
    """Devuelve a su almacén de origen lo reservado y todavía sin usar."""
    reservados = list(
        RepuestoOrden.objects.select_for_update(of=("self",))
        .select_related("traspaso_reserva")
        .filter(
            presupuesto__orden=orden,
            presupuesto__vigente=True,
            estado=EstadoRepuesto.RESERVADO,
        )
    )
    for r in reservados:
        try:
            movimientos.anular_movimiento(
                r.traspaso_reserva, motivo=f"Se libera la reserva de {orden.codigo}: {motivo}"
            )
        except AnulacionNoPermitida as error:
            raise PresupuestoInvalido(
                f"No se pudo devolver un repuesto reservado al almacén: {error.mensaje}"
            ) from None
        r.estado = EstadoRepuesto.LIBERADO
        r.save(update_fields=["estado"])
    if reservados:
        registrar(
            "servicio_tecnico.repuestos_liberados",
            recurso_tipo="orden_servicio",
            recurso_id=orden.pk,
            empresa_id=orden.empresa_id,
            resumen=f"{orden.codigo}: {len(reservados)} repuesto(s) devuelto(s) al almacén",
        )
    return len(reservados)
