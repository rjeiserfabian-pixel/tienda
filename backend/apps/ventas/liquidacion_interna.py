"""Lo que se deben las dos empresas por sus ventas internas, y cómo se liquida.

La venta interna es al contado y al costo, pero el dinero del cliente entró a la caja de la empresa
que facturó. Para que cada empresa vea en sus libros lo que es suyo, se lleva una libreta de
**partidas** (``DeudaInterna``) y se salda de una vez, normalmente al cerrar la caja del día:

* una venta interna suma: la que facturó le debe a la que entregó, al costo;
* una devolución del cliente o una anulación restan: la deuda va en sentido contrario.

Lo que se debe en neto es la suma de las partidas sin liquidar de un local, compensando lo que
cada una le debe a la otra. Se liquida con UNA transferencia entre las cajas o cuentas de las dos
empresas (en el mismo local es solo un asiento: el efectivo no se mueve del cajón). Si las deudas
se compensan exactamente, no hay transferencia y igual queda constancia. Anular la liquidación
deshace la transferencia y suelta las partidas.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja.exceptions import SaldoInsuficiente
from apps.caja.transferencias import anular_transferencia, registrar_transferencia
from apps.inventario import periodos
from apps.mantenimiento.models import (
    Correlativo,
    CuentaFinanciera,
    EstadoRegistro,
    MedioPago,
)
from apps.organizacion.models import Empresa, Sucursal

from .cuentas_web import CUENTA_COBRA, CUENTA_PUENTE, LOCAL_WEB
from .exceptions import CuentaDeCobroNoConfigurada, VentaInvalida
from .models import (
    CERO,
    DeudaInterna,
    LiquidacionInterna,
    MotivoDeuda,
    OrigenDeuda,
    TransferenciaPuente,
    VentaInterna,
)
from .servicios import resolver_cuenta

logger = logging.getLogger(__name__)

MONEDA = "PEN"  # las ventas internas valen su costo, que el Kardex lleva siempre en soles


def _nombre(empresa: Empresa) -> str:
    return empresa.nombre_comercial or empresa.razon_social


def local_de(sucursal: Sucursal | None) -> str:
    """Lo que agrupa las partidas: el local físico (compartido por las dos empresas) o la tienda."""
    if sucursal is None:
        return ""
    return sucursal.local_fisico or f"S{sucursal.pk}"


# ---------------------------------------------------------------------------
# La libreta
# ---------------------------------------------------------------------------
def registrar_partida(
    *,
    interna: VentaInterna,
    deudora: Empresa,
    acreedora: Empresa,
    monto: Decimal,
    motivo: str,
    devolucion=None,
) -> DeudaInterna | None:
    """Anota que ``deudora`` le debe ``monto`` a ``acreedora`` por esta venta interna."""
    if monto <= 0:
        return None  # una devolución de cero céntimos no deja deuda
    # Un traslado sin venta guarda su propia tienda; si no, es la de la venta al cliente.
    sucursal = interna.venta.sucursal if interna.venta_id else interna.sucursal
    return DeudaInterna.objects.create(
        empresa=deudora,
        acreedora=acreedora,
        venta_interna=interna,
        devolucion=devolucion,
        motivo=motivo,
        fecha=timezone.localdate(),
        monto=monto,
        sucursal=sucursal,
        local=local_de(sucursal),
    )


def partida_de_venta(interna: VentaInterna) -> DeudaInterna | None:
    """La que factura le debe a la que entregó lo que costó la mercadería."""
    return registrar_partida(
        interna=interna,
        deudora=interna.empresa_destino,
        acreedora=interna.empresa,
        monto=interna.total_costo,
        motivo=MotivoDeuda.VENTA,
    )


def partida_de_devolucion(interna: VentaInterna, devolucion) -> DeudaInterna | None:
    """Lo devuelto vuelve a la que entregó: ahora ella le debe esa parte a la que facturó."""
    return registrar_partida(
        interna=interna,
        deudora=interna.empresa,
        acreedora=interna.empresa_destino,
        monto=devolucion.costo_total,
        motivo=MotivoDeuda.DEVOLUCION,
        devolucion=devolucion,
    )


def partida_de_anulacion(interna: VentaInterna) -> DeudaInterna | None:
    """La venta interna se anuló: la deuda que dejó se compensa en sentido contrario."""
    return registrar_partida(
        interna=interna,
        deudora=interna.empresa,
        acreedora=interna.empresa_destino,
        monto=interna.total_costo,
        motivo=MotivoDeuda.ANULACION,
    )


def partida_de_cobro_web(
    *,
    cobro_id: int,
    pedido: str,
    cobra: Empresa,
    otra: Empresa,
    monto: Decimal,
    motivo: str = MotivoDeuda.VENTA,
) -> DeudaInterna | None:
    """Un pago de la tienda lo recibió ``cobra`` y una parte era de ``otra``.

    VENTA: quien cobró le debe ``monto`` a la otra empresa. ANULACION: la deuda se revierte (el
    pedido se anuló después de liquidarse): ahora la otra empresa le debe ``monto`` a quien cobró.
    Es idempotente: no se duplica la partida de un mismo cobro y motivo. Devuelve ``None`` si ya
    existía o si el monto es cero.
    """
    if monto <= 0:
        return None
    if motivo not in (MotivoDeuda.VENTA, MotivoDeuda.ANULACION):
        raise ValueError("Un cobro de la tienda solo tiene partida de venta o de anulación.")
    existente = (
        DeudaInterna.objects.sin_ambito()
        .filter(origen=OrigenDeuda.COBRO_TIENDA, origen_id=cobro_id, motivo=motivo)
        .exists()
    )
    if existente:
        return None
    deudora, acreedora = (cobra, otra) if motivo == MotivoDeuda.VENTA else (otra, cobra)
    return DeudaInterna.objects.create(
        empresa=deudora,
        acreedora=acreedora,
        origen=OrigenDeuda.COBRO_TIENDA,
        origen_id=cobro_id,
        referencia=f"Pedido {pedido}"[:60],
        motivo=motivo,
        fecha=timezone.localdate(),
        monto=monto,
        local=LOCAL_WEB,
    )


# ---------------------------------------------------------------------------
# Lo pendiente
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Pendiente:
    """Lo que falta liquidar entre dos empresas en un local, ya compensado."""

    local: str
    sucursal: Sucursal | None
    pagadora: Empresa
    receptora: Empresa
    monto: Decimal
    partidas: list[DeudaInterna] = field(default_factory=list)
    # Lo que cada una le debe a la otra antes de compensar (para mostrarlo).
    debe_pagadora: Decimal = CERO
    debe_receptora: Decimal = CERO


def _orden(empresa: Empresa) -> tuple[bool, int]:
    return (not empresa.es_principal, empresa.pk)


def _agrupar(partidas: list[DeudaInterna]) -> list[Pendiente]:
    grupos: dict[tuple[str, frozenset[int]], list[DeudaInterna]] = {}
    for p in partidas:
        grupos.setdefault((p.local, frozenset({p.empresa_id, p.acreedora_id})), []).append(p)
    resultado = []
    for (local, _), filas in grupos.items():
        empresas = {p.empresa_id: p.empresa for p in filas} | {
            p.acreedora_id: p.acreedora for p in filas
        }
        primera, segunda = sorted(empresas.values(), key=_orden)
        debe_primera = sum((p.monto for p in filas if p.empresa_id == primera.pk), CERO)
        debe_segunda = sum((p.monto for p in filas if p.empresa_id == segunda.pk), CERO)
        neto = debe_primera - debe_segunda
        pagadora, receptora = (primera, segunda) if neto >= 0 else (segunda, primera)
        sucursal = next((p.sucursal for p in filas if p.sucursal is not None), None)
        resultado.append(
            Pendiente(
                local=local,
                sucursal=sucursal,
                pagadora=pagadora,
                receptora=receptora,
                monto=abs(neto),
                partidas=filas,
                debe_pagadora=debe_primera if pagadora.pk == primera.pk else debe_segunda,
                debe_receptora=debe_segunda if pagadora.pk == primera.pk else debe_primera,
            )
        )
    return sorted(resultado, key=lambda g: (g.local, g.pagadora.pk))


def pendientes(
    organizacion_id: int, *, empresa_ids: set[int] | None = None, local: str | None = None
) -> list[Pendiente]:
    """Lo que falta liquidar, por local y par de empresas (``empresa_ids``: las que se ven)."""
    consulta = DeudaInterna.objects.sin_ambito().filter(
        empresa__organizacion_id=organizacion_id, liquidacion__isnull=True
    )
    if local is not None:
        consulta = consulta.filter(local=local)
    if empresa_ids is not None:
        consulta = consulta.filter(empresa_id__in=empresa_ids, acreedora_id__in=empresa_ids)
    return _agrupar(list(consulta.select_related("empresa", "acreedora", "sucursal")))


def cuentas_sugeridas(
    pagadora: Empresa, receptora: Empresa, sucursal: Sucursal | None
) -> tuple[CuentaFinanciera | None, CuentaFinanciera | None, str]:
    """Las cajas de efectivo del local de cada empresa, y por qué no se pudo si falta alguna."""
    efectivo = (
        MedioPago.objects.filter(
            organizacion_id=pagadora.organizacion_id,
            tipo=MedioPago.Tipo.EFECTIVO,
            estado=EstadoRegistro.ACTIVO,
        )
        .order_by("id")
        .first()
    )
    if efectivo is None:
        return None, None, "No hay un método de pago en efectivo."
    encontradas = []
    for empresa in (pagadora, receptora):
        try:
            encontradas.append(resolver_cuenta(empresa, efectivo, sucursal, MONEDA))
        except CuentaDeCobroNoConfigurada as error:
            return None, None, error.mensaje
    return encontradas[0], encontradas[1], ""


def _cuenta_por_nombre(empresa: Empresa, nombre: str) -> CuentaFinanciera | None:
    return (
        CuentaFinanciera.objects.sin_ambito()
        .filter(empresa=empresa, nombre__iexact=nombre, estado=EstadoRegistro.ACTIVO)
        .first()
    )


def cuentas_sugeridas_web(
    pagadora: Empresa, receptora: Empresa
) -> tuple[CuentaFinanciera | None, CuentaFinanciera | None, str]:
    """Para un cobro de la tienda: sale de la cuenta de Culqi de quien cobró y entra a un banco.

    Origen: la cuenta «Culqi (tienda virtual)» de la empresa que paga. Destino: el primer banco en
    soles de la que recibe (si no tiene, no se propone y hay que elegirlo).
    """
    origen = _cuenta_por_nombre(pagadora, CUENTA_COBRA)
    destino = (
        CuentaFinanciera.objects.sin_ambito()
        .filter(
            empresa=receptora,
            tipo=CuentaFinanciera.Tipo.BANCO,
            moneda=MONEDA,
            estado=EstadoRegistro.ACTIVO,
        )
        .order_by("id")
        .first()
    )
    motivos = []
    if origen is None:
        motivos.append(f"{_nombre(pagadora)} no tiene la cuenta «{CUENTA_COBRA}».")
    if destino is None:
        motivos.append(f"{_nombre(receptora)} no tiene una cuenta de banco en soles: elíjala.")
    return origen, destino, " ".join(motivos)


# ---------------------------------------------------------------------------
# Liquidar y anular
# ---------------------------------------------------------------------------
def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"ventas:liquidacion_interna:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _validar_cuenta(cuenta: CuentaFinanciera, empresa: Empresa, rol: str) -> None:
    if cuenta.empresa_id != empresa.pk:
        raise VentaInvalida(f"La cuenta {rol} debe ser de {_nombre(empresa)}.")
    if cuenta.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida(f"«{cuenta.nombre}» está inactiva.")
    if cuenta.moneda != MONEDA:
        raise VentaInvalida(f"«{cuenta.nombre}» no es una cuenta en soles.")


def _movimientos_puente(partidas) -> list[tuple[Empresa, Empresa, Decimal]]:
    """Lo que hay que pasar de las cuentas puente a las cuentas de Culqi de quien cobró.

    Devuelve ``(empresa con cuenta puente, empresa que tiene el dinero, neto)``. Un cobro de la
    tienda (VENTA) deja lo ajeno anotado en la cuenta puente de la otra empresa: se pasa a la
    cuenta de Culqi de quien cobró (``neto`` positivo). Una anulación lo devuelve (``neto``
    negativo). Así, tras liquidar, la cuenta puente queda en cero y el dinero de Culqi cuadra.
    """
    netos: dict[tuple[int, int], list] = {}
    for p in partidas:
        if p.origen != OrigenDeuda.COBRO_TIENDA:
            continue
        if p.motivo == MotivoDeuda.VENTA:
            puente, tiene, signo = p.acreedora, p.empresa, 1
        else:
            puente, tiene, signo = p.empresa, p.acreedora, -1
        fila = netos.setdefault((puente.pk, tiene.pk), [puente, tiene, CERO])
        fila[2] += signo * p.monto
    return [(a, b, n) for a, b, n in netos.values() if n != 0]


def _asientos_de_cobros_web(partidas, *, numero: int, fecha: date) -> list:
    """Hace las transferencias puente → Culqi (o al revés) de los cobros web que se liquidan."""
    transferencias = []
    for puente, tiene, neto in _movimientos_puente(partidas):
        cuenta_puente = _cuenta_por_nombre(puente, CUENTA_PUENTE)
        cuenta_cobra = _cuenta_por_nombre(tiene, CUENTA_COBRA)
        if cuenta_puente is None or cuenta_cobra is None:
            raise VentaInvalida(
                f"Faltan las cuentas «{CUENTA_PUENTE}» de {_nombre(puente)} o "
                f"«{CUENTA_COBRA}» de {_nombre(tiene)}. Se crean al primer pago con Culqi."
            )
        if neto > 0:
            dueña, origen, destino = puente, cuenta_puente, cuenta_cobra
        else:
            dueña, origen, destino = tiene, cuenta_cobra, cuenta_puente
        try:
            transferencias.append(
                registrar_transferencia(
                    empresa=dueña,
                    cuenta_origen=origen,
                    cuenta_destino=destino,
                    monto=abs(neto),
                    fecha=fecha,
                    glosa=f"Cobros web: reconocimiento previo a la liquidación N° {numero:06d}",
                )
            )
        except SaldoInsuficiente as error:
            raise VentaInvalida(f"{error.mensaje} (cuenta «{origen.nombre}»).") from None
    return transferencias


@transaction.atomic
def liquidar(
    *,
    pagadora: Empresa,
    receptora: Empresa,
    local: str,
    cuenta_origen: CuentaFinanciera | None = None,
    cuenta_destino: CuentaFinanciera | None = None,
    fecha: date | None = None,
    referencia: str = "",
    observacion: str = "",
) -> LiquidacionInterna:
    """Salda con una transferencia todo lo pendiente entre las dos empresas en ese local.

    Se vuelve a calcular con las partidas bloqueadas: si desde que se mostró cambió quién le debe
    a quién (entró una devolución, por ejemplo), no se liquida a ciegas.
    """
    periodos.exigir_empresa(pagadora)
    periodos.exigir_empresa(receptora)
    if pagadora.pk == receptora.pk or pagadora.organizacion_id != receptora.organizacion_id:
        raise VentaInvalida("Elija dos empresas distintas de la misma organización.")
    # Se bloquean las partidas (y con ellas la liquidación): dos personas no liquidan lo mismo.
    bloqueadas = list(
        DeudaInterna.objects.sin_ambito()
        .select_for_update(of=("self",))  # solo las partidas: lo demás puede ser nulo
        .filter(
            liquidacion__isnull=True,
            local=local,
            empresa_id__in=[pagadora.pk, receptora.pk],
            acreedora_id__in=[pagadora.pk, receptora.pk],
        )
        .select_related("empresa", "acreedora", "sucursal")
    )
    if not bloqueadas:
        raise VentaInvalida("No hay nada por liquidar entre esas empresas en este local.")
    (actual,) = _agrupar(bloqueadas)
    if actual.monto > 0 and actual.pagadora.pk != pagadora.pk:
        raise VentaInvalida(
            f"Las cuentas cambiaron: ahora {_nombre(actual.pagadora)} es quien debe pagar. "
            "Vuelva a cargar lo pendiente."
        )
    monto = actual.monto
    fecha = fecha or timezone.localdate()
    if fecha > timezone.localdate():
        raise VentaInvalida("La fecha no puede ser futura.")
    referencia = " ".join((referencia or "").split())[:60]
    observacion = " ".join((observacion or "").split())[:250]

    origen = destino = None
    if monto > 0:
        if local == LOCAL_WEB:
            sugerido_origen, sugerido_destino, motivo = cuentas_sugeridas_web(pagadora, receptora)
        else:
            sugerido_origen, sugerido_destino, motivo = cuentas_sugeridas(
                pagadora, receptora, actual.sucursal
            )
        origen, destino = cuenta_origen or sugerido_origen, cuenta_destino or sugerido_destino
        if origen is None or destino is None:
            raise VentaInvalida(f"Elija las cuentas de la liquidación. {motivo}".strip())
        _validar_cuenta(origen, pagadora, "de origen")
        _validar_cuenta(destino, receptora, "de destino")

    numero = _siguiente_numero(pagadora)
    # Cobros de la tienda: primero se pasa lo ajeno de las cuentas puente a las de Culqi.
    puentes = (
        _asientos_de_cobros_web(bloqueadas, numero=numero, fecha=fecha)
        if local == LOCAL_WEB
        else []
    )
    transferencia = None
    if monto > 0:
        try:
            transferencia = registrar_transferencia(
                empresa=pagadora,
                cuenta_origen=origen,
                cuenta_destino=destino,
                monto=monto,
                fecha=fecha,
                glosa=(
                    f"Liquidación de cobros de la tienda N° {numero:06d}"
                    if local == LOCAL_WEB
                    else f"Liquidación de ventas internas N° {numero:06d}"
                ),
                referencia=referencia,
            )
        except SaldoInsuficiente as error:
            raise VentaInvalida(f"{error.mensaje} También puede elegir otra cuenta.") from None
    liquidacion = LiquidacionInterna.objects.create(
        empresa=pagadora,
        empresa_destino=receptora,
        numero=numero,
        sucursal=actual.sucursal,
        local=local,
        fecha=fecha,
        monto=monto,
        transferencia=transferencia,
        referencia=referencia,
        observacion=observacion,
    )
    for orden, t in enumerate(puentes, start=1):
        TransferenciaPuente.objects.create(liquidacion=liquidacion, transferencia=t, orden=orden)
    DeudaInterna.objects.sin_ambito().filter(pk__in=[p.pk for p in bloqueadas]).update(
        liquidacion=liquidacion
    )
    registrar(
        "ventas.liquidacion_interna_hecha",
        recurso_tipo="liquidacion_interna",
        recurso_id=liquidacion.pk,
        empresa_id=pagadora.pk,
        resumen=(
            f"Liquidación interna N° {numero:06d}: {_nombre(pagadora)} → {_nombre(receptora)}, "
            f"S/ {monto}"
        ),
        detalle={"partidas": len(bloqueadas), "local": local, "monto": monto},
    )
    return liquidacion


@transaction.atomic
def anular_liquidacion(liquidacion: LiquidacionInterna, *, motivo: str) -> LiquidacionInterna:
    """Deshace la liquidación: se anula la transferencia y las partidas quedan pendientes."""
    periodos.exigir_empresa(liquidacion.empresa)
    periodos.exigir_empresa(liquidacion.empresa_destino)
    liquidacion.anular(motivo=motivo)  # exige el motivo y bloquea la fila
    if liquidacion.transferencia_id:
        anular_transferencia(liquidacion.transferencia, motivo=f"Liquidación anulada: {motivo}")
    # Las transferencias puente se deshacen al final y en orden inverso al que se hicieron.
    for puente in reversed(list(liquidacion.transferencias_puente.select_related("transferencia"))):
        anular_transferencia(puente.transferencia, motivo=f"Liquidación anulada: {motivo}")
    DeudaInterna.objects.sin_ambito().filter(liquidacion=liquidacion).update(liquidacion=None)
    registrar(
        "ventas.liquidacion_interna_anulada",
        recurso_tipo="liquidacion_interna",
        recurso_id=liquidacion.pk,
        empresa_id=liquidacion.empresa_id,
        resumen=f"Liquidación interna N° {liquidacion.numero:06d} anulada",
        detalle={"motivo": (motivo or "").strip()[:200]},
    )
    return liquidacion


# ---------------------------------------------------------------------------
# Al cerrar la caja
# ---------------------------------------------------------------------------
def pendientes_del_cierre(sesion) -> list[Pendiente]:
    """Lo que se debe liquidar antes de cerrar esta caja: las deudas de su local con dinero."""
    sucursal = sesion.cuenta.sucursal
    local = local_de(sucursal)
    if not local:
        return []
    return [
        p
        for p in pendientes(sesion.empresa.organizacion_id, local=local)
        if p.monto > 0 and sesion.empresa_id in (p.pagadora.pk, p.receptora.pk)
    ]
