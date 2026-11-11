"""Reembolsos de los pedidos pagados con Culqi: anular o devolver, y devolver el dinero.

Hay tres caminos, según en qué punto está el pedido:

* ANULACIÓN (pagado, en preparación, listo para recoger o enviado): se anula la venta (cada
  comprobante vuelve el stock y las series y extorna su cobro), se revierte la deuda entre
  empresas y se devuelve en Culqi el TOTAL cobrado.
* NOTA DE CRÉDITO (entregado, o ya reembolsado en parte): el cliente devuelve el equipo; se emite
  una nota de crédito por comprobante (con reingreso al stock si se confirma) y se devuelve en
  Culqi lo que suman. Puede ser TOTAL o PARCIAL (solo pedidos de una sola empresa).
* SOLO DINERO (cobrado sin comprobante o fuera de plazo): no hubo venta ni salió stock; solo se
  devuelve el cargo.

ORDEN SEGURO. Primero lo interno, en UNA transacción atómica (si algo falla, no cambia nada y el
dinero no se toca); queda un ``ReembolsoPedido`` SOLICITADO y el pedido en REEMBOLSO_PENDIENTE.
Después, fuera de toda transacción, se llama a Culqi. Si Culqi falla o no responde, lo interno ya
está hecho y el reembolso queda pendiente: una tarea lo reintenta y el panel lo muestra como
«requiere atención». Nunca se devuelve dinero sin haber deshecho lo interno ni se deshace lo
interno sin un camino para devolver el dinero.

NUNCA DOS VECES. Antes de pedir un reembolso se consulta el cargo en Culqi (``amount_refunded``): si
ya devolvió lo esperado, se da por hecho sin crear otro. Además cada reembolso lleva una clave de
idempotencia estable, y el monto devuelto nunca supera lo cobrado.

Lo que NO hace: la comunicación de baja o el envío de la nota de crédito a SUNAT (la integración
con SUNAT es una etapa aparte; los comprobantes quedan anulados o con nota en el sistema).
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import contexto_tenant
from apps.mantenimiento.models import MedioPago
from apps.organizacion.models import Empresa
from apps.ventas import notas_credito
from apps.ventas import servicios as ventas
from apps.ventas.exceptions import VentaInvalida
from apps.ventas.models import ComprobanteVenta, LineaVenta, MotivoNota
from apps.ventas.servicios import CobroEntrada

from . import catalogo, culqi, deuda_web, pedidos, series_pedido
from .exceptions import PedidoInvalido, PedidoNoEncontrado, ReembolsoNoPermitido
from .models import (
    ConfiguracionPago,
    DeudaCobroTienda,
    HistorialPedido,
    LineaPedido,
    PedidoTienda,
    ReembolsoPedido,
)

logger = logging.getLogger(__name__)

Estado = PedidoTienda.Estado
Tipo = ReembolsoPedido.Tipo
CERO = Decimal("0")
MAX_REINTENTOS = 12  # cada 5 minutos: una hora
MAX_TEXTO = 250

RUTA_ANULACION = (
    Estado.PAGADO,
    Estado.EN_PREPARACION,
    Estado.LISTO_PARA_RECOJO,
    Estado.ENVIADO,
)
RUTA_NOTA = (Estado.ENTREGADO, Estado.REEMBOLSADO_PARCIAL)
RUTA_SOLO_DINERO = (Estado.PAGADO_SIN_COMPROBANTE, Estado.PAGADO_FUERA_DE_PLAZO)

# Motivo del negocio → motivo que entiende Culqi.
MOTIVO_CULQI = {
    ReembolsoPedido.Motivo.SOLICITUD_CLIENTE: "solicitud_comprador",
    ReembolsoPedido.Motivo.DUPLICADO: "duplicado",
    ReembolsoPedido.Motivo.FRAUDE: "fraudulento",
    ReembolsoPedido.Motivo.SIN_STOCK: "solicitud_comprador",
    ReembolsoPedido.Motivo.OTRO: "solicitud_comprador",
}


def _centimos(monto: Decimal) -> int:
    return int((monto * 100).to_integral_value())


def _quien(usuario) -> dict:
    nombre = (usuario.get_full_name() or usuario.get_username())[:150]
    return {"usuario_id": usuario.pk, "usuario_nombre": nombre}


def _pedido_de(organizacion_id: int, numero: str, *, bloquear: bool = False) -> PedidoTienda:
    consulta = PedidoTienda.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, numero=numero
    )
    if bloquear:
        consulta = consulta.select_for_update()
    pedido = consulta.first()
    if pedido is None:
        raise PedidoNoEncontrado()
    return pedido


def _empresas(organizacion_id: int) -> list[int]:
    return list(
        Empresa.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id)
        .values_list("pk", flat=True)
    )


def ruta_de(pedido: PedidoTienda) -> str:
    """Qué camino sigue el reembolso de este pedido, o ``ReembolsoNoPermitido``."""
    if pedido.estado == Estado.REEMBOLSO_PENDIENTE:
        raise ReembolsoNoPermitido(
            "Ya hay un reembolso por confirmar en Culqi: usa «Reintentar reembolso»."
        )
    if pedido.estado == Estado.REEMBOLSADO:
        raise ReembolsoNoPermitido("Este pedido ya se reembolsó por completo.")
    if not pedido.culqi_cargo_id:
        raise ReembolsoNoPermitido("Este pedido no tiene un cobro de Culqi que devolver.")
    if pedido.estado in RUTA_ANULACION:
        return Tipo.ANULACION
    if pedido.estado in RUTA_NOTA:
        return Tipo.NOTA_CREDITO
    if pedido.estado in RUTA_SOLO_DINERO:
        return Tipo.SOLO_DINERO
    raise ReembolsoNoPermitido("Un pedido sin pagar no se reembolsa: cancélalo.")


def _restante(pedido: PedidoTienda) -> Decimal:
    return pedido.total - pedido.monto_reembolsado


def _hay_deuda(pedido: PedidoTienda) -> bool:
    return (
        DeudaCobroTienda.objects.sin_ambito()
        .filter(pedido=pedido, revertida_en__isnull=True)
        .exists()
    )


# ---------------------------------------------------------------------------
# Vista previa: qué pasará (para el modal del panel)
# ---------------------------------------------------------------------------
def plan(organizacion_id: int, numero: str) -> dict:
    """Describe EXACTAMENTE qué haría un reembolso, sin cambiar nada."""
    pedido = _pedido_de(organizacion_id, numero)
    ruta = ruta_de(pedido)
    comprobantes = []
    if pedido.venta_id:
        comprobantes = [
            f"{c.numero_completo} ({c.empresa.razon_social})"
            for c in ComprobanteVenta.objects.sin_ambito()
            .filter(venta_id=pedido.venta_id, estado=ComprobanteVenta.Estado.EMITIDO)
            .select_related("empresa")
            .order_by("pk")
        ]
    avisos = []
    pasos = []
    monto = _restante(pedido)
    if ruta == Tipo.ANULACION:
        pasos = [
            f"Se anula(n) el/los comprobante(s): {', '.join(comprobantes) or '—'}.",
            "El stock y las series vuelven al almacén y los cobros se extornan.",
        ]
        if pedido.estado == Estado.ENVIADO:
            avisos.append("El pedido ya salió: asegúrate de recuperar el equipo.")
    elif ruta == Tipo.NOTA_CREDITO:
        pasos = [
            f"Se emite una nota de crédito por cada comprobante: {', '.join(comprobantes) or '—'}.",
            "Si confirmas que el equipo regresó, el stock y las series vuelven al almacén.",
        ]
    else:
        pasos = ["No hubo venta ni salida de stock: solo se devuelve el dinero."]
        if pedido.estado == Estado.PAGADO_SIN_COMPROBANTE:
            pasos.append("Se libera el stock apartado y se deja de reintentar el comprobante.")
    mixto = _hay_deuda(pedido)
    if mixto and ruta != Tipo.SOLO_DINERO:
        pasos.append("Se revierte la deuda entre empresas de este pedido (cobro mixto).")
    pasos.append(f"Se devuelven S/ {monto:,.2f} al cliente por Culqi (tarjeta o Yape).")
    avisos.append("El plazo en que el dinero llega al cliente depende de su banco.")
    return {
        "numero": pedido.numero,
        "ruta": ruta,
        "monto": format(monto, "f"),
        "total": format(pedido.total, "f"),
        "ya_reembolsado": format(pedido.monto_reembolsado, "f"),
        "comprobantes": comprobantes,
        "pasos": pasos,
        "avisos": avisos,
        "permite_parcial": ruta == Tipo.NOTA_CREDITO and not mixto and bool(pedido.venta_id),
        "pide_confirmar_stock": ruta == Tipo.NOTA_CREDITO,
        "motivos": [{"valor": v, "texto": t} for v, t in ReembolsoPedido.Motivo.choices],
    }


# ---------------------------------------------------------------------------
# Paso 1: deshacer lo interno (una transacción)
# ---------------------------------------------------------------------------
def _anular_venta(pedido: PedidoTienda, motivo: str) -> None:
    if pedido.venta_id is None:
        raise ReembolsoNoPermitido("El pedido no tiene una venta que anular.")
    series_pedido.deshacer_cambios(pedido)
    ventas.anular_venta(pedido.venta, motivo=f"Reembolso del pedido {pedido.numero}: {motivo}")
    deuda_web.revertir_deuda_de_pedido(pedido, motivo=motivo)
    pedidos.liberar_reservas(pedido)


def _lineas_devueltas(pedido: PedidoTienda, comprobantes, lineas) -> dict[int, list]:
    """Las líneas de pedido elegidas → líneas de venta por comprobante (devolución por ítem)."""
    por_comprobante: dict[int, list] = {}
    vistas: set[int] = set()
    for pedida in lineas:
        linea = (
            LineaPedido.objects.sin_ambito()
            .filter(pk=pedida["linea"], pedido=pedido)
            .select_related("producto")
            .first()
        )
        if linea is None or linea.pk in vistas:
            raise PedidoInvalido("Una de las líneas elegidas no es de este pedido.")
        vistas.add(linea.pk)
        cantidad = Decimal(str(pedida["cantidad"]))
        venta_linea = (
            LineaVenta.objects.sin_ambito()
            .filter(
                venta_id=pedido.venta_id,
                producto_id=linea.producto_id,
                empresa_id=linea.empresa_id,
                comprobante__in=comprobantes,
            )
            .order_by("pk")
            .first()
        )
        if venta_linea is None:
            raise PedidoInvalido(f"No encontramos «{linea.descripcion}» en los comprobantes.")
        series = tuple(venta_linea.series[: int(cantidad)]) if venta_linea.series else ()
        por_comprobante.setdefault(venta_linea.comprobante_id, []).append(
            notas_credito.LineaDevuelta(venta_linea, cantidad, series)
        )
    return por_comprobante


def _emitir_nota(pedido, comprobante, devueltas, motivo_nota, *, reingresa, motivo, usuario):
    """Una nota de crédito de un comprobante; devuelve (nota, dinero a devolver)."""
    if devueltas is None:
        devueltas_calculo = notas_credito.devueltas_de_motivo(comprobante, motivo_nota)
    else:
        devueltas_calculo = devueltas
    calculo = notas_credito.calcular_nota(comprobante, devueltas_calculo)
    filas, sin_asignar = notas_credito.sugerir_reembolso(comprobante, calculo.a_reembolsar)
    if sin_asignar > 0:
        raise ReembolsoNoPermitido(
            f"El comprobante {comprobante.numero_completo} no tiene cobros suficientes para "
            "devolver ese monto."
        )
    medios = {
        m.pk: m
        for m in MedioPago.objects.sin_ambito().filter(pk__in=[f["medio_pago"] for f in filas])
    }
    reembolsos = [
        CobroEntrada(medio_pago=medios[f["medio_pago"]], monto=f["monto"], referencia=pedido.numero)
        for f in filas
    ]
    nota = notas_credito.crear_nota_credito(
        comprobante,
        motivo=motivo_nota,
        devueltas=devueltas,
        reembolsos=reembolsos,
        reingresa_stock=reingresa,
        descripcion=f"Reembolso del pedido {pedido.numero}: {motivo}"[:250],
        usuario_id=usuario.pk,
        usuario_nombre=(usuario.get_full_name() or usuario.get_username())[:150],
    )
    return nota, calculo.a_reembolsar


def _notas(pedido, lineas, *, reingresa, motivo, usuario) -> tuple[Decimal, list[int]]:
    comprobantes = list(
        ComprobanteVenta.objects.select_related("empresa")
        .filter(venta_id=pedido.venta_id, estado=ComprobanteVenta.Estado.EMITIDO)
        .order_by("pk")
    )
    if not comprobantes:
        raise ReembolsoNoPermitido("El pedido no tiene comprobantes vigentes que devolver.")
    notas: list[int] = []
    dinero = CERO
    if lineas is None:
        series_pedido.deshacer_cambios(pedido)
        for comprobante in comprobantes:
            try:
                nota, monto = _emitir_nota(
                    pedido,
                    comprobante,
                    None,
                    MotivoNota.DEVOLUCION_TOTAL,
                    reingresa=reingresa,
                    motivo=motivo,
                    usuario=usuario,
                )
            except VentaInvalida as error:
                if "ya se devolvió por completo" in str(error.mensaje):
                    continue  # ese comprobante ya estaba devuelto
                raise
            notas.append(nota.pk)
            dinero += monto
        deuda_web.revertir_deuda_de_pedido(pedido, motivo=motivo)
    else:
        if _hay_deuda(pedido):
            raise ReembolsoNoPermitido(
                "En un pedido con productos de las dos empresas la devolución es total: "
                "así la deuda entre empresas queda bien."
            )
        por_comprobante = _lineas_devueltas(pedido, comprobantes, lineas)
        for comprobante in comprobantes:
            devueltas = por_comprobante.get(comprobante.pk)
            if not devueltas:
                continue
            nota, monto = _emitir_nota(
                pedido,
                comprobante,
                devueltas,
                MotivoNota.DEVOLUCION_ITEM,
                reingresa=reingresa,
                motivo=motivo,
                usuario=usuario,
            )
            notas.append(nota.pk)
            dinero += monto
    if dinero <= 0:
        raise ReembolsoNoPermitido("No hay nada que devolver en dinero.")
    return dinero, notas


def _limpio(texto: str | None) -> str:
    texto = " ".join((texto or "").split())
    if len(texto) < 3:
        raise PedidoInvalido("Escribe el motivo del reembolso.")
    if len(texto) > MAX_TEXTO:
        raise PedidoInvalido(f"El motivo admite hasta {MAX_TEXTO} caracteres.")
    return texto


def reembolsar(
    organizacion_id: int,
    numero: str,
    *,
    motivo_tipo: str,
    motivo: str,
    usuario,
    lineas: list[dict] | None = None,
    reingresa_stock: bool = True,
) -> ReembolsoPedido:
    """Deshace lo interno del pedido y devuelve el dinero por Culqi (ver el módulo)."""
    if motivo_tipo not in ReembolsoPedido.Motivo.values:
        raise PedidoInvalido("Elige el tipo de motivo del reembolso.")
    motivo = _limpio(motivo)
    with transaction.atomic():
        pedido = _pedido_de(organizacion_id, numero, bloquear=True)
        ruta = ruta_de(pedido)
        if lineas is not None and ruta != Tipo.NOTA_CREDITO:
            raise ReembolsoNoPermitido("Solo se puede devolver en parte un pedido ya entregado.")
        if lineas is not None and not lineas:
            raise PedidoInvalido("Elige qué se devuelve.")
        estado_previo = pedido.estado
        with contexto_tenant(organizacion_id, _empresas(organizacion_id), usuario.pk):
            if ruta == Tipo.ANULACION:
                monto, notas = _restante(pedido), []
                _anular_venta(pedido, motivo)
            elif ruta == Tipo.NOTA_CREDITO:
                monto, notas = _notas(
                    pedido, lineas, reingresa=reingresa_stock, motivo=motivo, usuario=usuario
                )
            else:
                monto, notas = _restante(pedido), []
                pedidos.liberar_reservas(pedido)
        if monto > _restante(pedido):
            raise ReembolsoNoPermitido("El monto a devolver supera lo cobrado.")
        secuencia = ReembolsoPedido.objects.sin_ambito().filter(pedido=pedido).count() + 1
        reembolso = ReembolsoPedido.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            pedido=pedido,
            tipo=ruta,
            estado_previo=estado_previo,
            motivo_tipo=motivo_tipo,
            motivo=motivo,
            monto=monto,
            clave=f"rf-{pedido.numero}-{secuencia}-{_centimos(monto)}",
            notas_credito=notas,
            venta_anulada=ruta == Tipo.ANULACION,
            **_quien(usuario),
        )
        pedido.estado = Estado.REEMBOLSO_PENDIENTE
        pedido.save(update_fields=["estado", "actualizado_en"])
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=Estado.REEMBOLSO_PENDIENTE,
            texto=f"Reembolso de S/ {monto:,.2f} solicitado: {motivo}"[:500],
            **_quien(usuario),
        )
        registrar(
            "tienda.reembolso_solicitado",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=organizacion_id,
            resumen=f"Pedido {pedido.numero}: reembolso de S/ {monto:,.2f} ({ruta})"[:250],
            detalle={"motivo_tipo": motivo_tipo, "estado_previo": estado_previo},
            inmediato=True,
        )
        transaction.on_commit(catalogo.invalidar)
    # Lo interno ya quedó firme: ahora el dinero, fuera de toda transacción.
    return completar(reembolso.pk, usuario=usuario)


# ---------------------------------------------------------------------------
# Paso 2: devolver el dinero en Culqi
# ---------------------------------------------------------------------------
def _alerta(pedido: PedidoTienda, resumen: str) -> None:
    logger.error("tienda_reembolso_pendiente", extra={"pedido": pedido.numero, "motivo": resumen})
    registrar(
        "tienda.reembolso_requiere_atencion",
        recurso_tipo="pedido_tienda",
        recurso_id=pedido.pk,
        organizacion_id=pedido.organizacion_id,
        resumen=f"ALERTA: reembolso del pedido {pedido.numero} sin confirmar en Culqi. {resumen}"[
            :250
        ],
        exito=False,
        inmediato=True,
    )


def _anotar(reembolso: ReembolsoPedido, mensaje: str) -> None:
    ReembolsoPedido.objects.sin_ambito().filter(pk=reembolso.pk).update(
        mensaje=mensaje[:250], actualizado_en=timezone.now()
    )


def completar(reembolso_id: int, *, usuario=None, manual: bool = False) -> ReembolsoPedido:
    """Pide el reembolso a Culqi (o lo da por hecho si Culqi ya lo devolvió). Se puede repetir."""
    clave_bloqueo = f"tienda:reembolso:{reembolso_id}"
    if not cache.add(clave_bloqueo, 1, 120):
        # Otro proceso lo está haciendo en este momento.
        return ReembolsoPedido.objects.sin_ambito().select_related("pedido").get(pk=reembolso_id)
    try:
        return _completar(reembolso_id, usuario=usuario, manual=manual)
    finally:
        cache.delete(clave_bloqueo)


def _completar(reembolso_id: int, *, usuario, manual: bool) -> ReembolsoPedido:
    with transaction.atomic():
        reembolso = ReembolsoPedido.objects.sin_ambito().select_for_update().get(pk=reembolso_id)
        if reembolso.estado == ReembolsoPedido.Estado.APROBADO:
            return reembolso
        if not manual and reembolso.intentos >= MAX_REINTENTOS:
            return reembolso
        reembolso.intentos += 1
        reembolso.save(update_fields=["intentos", "actualizado_en"])
        pedido = PedidoTienda.objects.sin_ambito().get(pk=reembolso.pedido_id)
    config = (
        ConfiguracionPago.objects.sin_ambito()
        .filter(organizacion_id=pedido.organizacion_id)
        .first()
    )
    if config is None or not config.culqi_llave_secreta:
        _anotar(reembolso, "Falta la llave secreta de Culqi para devolver el dinero.")
        _alerta(pedido, "Falta la llave secreta de Culqi.")
        return ReembolsoPedido.objects.sin_ambito().get(pk=reembolso_id)
    llave = config.culqi_llave_secreta
    try:
        # Antes de pedir nada: ¿Culqi ya devolvió esto? (un intento anterior pudo cortarse).
        cargo = culqi.obtener_cargo(llave, pedido.culqi_cargo_id)
        esperado = _centimos(pedido.monto_reembolsado) + _centimos(reembolso.monto)
        if cargo.reembolsado_centimos >= esperado:
            referencia = reembolso.culqi_reembolso_id or "ya_reembolsado"
        else:
            if cargo.reembolsado_centimos > _centimos(pedido.monto_reembolsado):
                # Culqi devolvió algo más que lo que sabemos (¿otro reembolso hecho en su panel?).
                _anotar(
                    reembolso,
                    "El cargo ya tiene reembolsos en Culqi que no están en el sistema: revísalo.",
                )
                _alerta(pedido, "El cargo tiene reembolsos desconocidos en Culqi.")
                return ReembolsoPedido.objects.sin_ambito().get(pk=reembolso_id)
            hecho = culqi.crear_reembolso(
                llave,
                cargo_id=pedido.culqi_cargo_id,
                monto_centimos=_centimos(reembolso.monto),
                motivo=MOTIVO_CULQI.get(reembolso.motivo_tipo, "solicitud_comprador"),
                pedido=pedido.numero,
                idempotencia=reembolso.clave,
            )
            if not hecho.aprobado:
                _anotar(reembolso, hecho.mensaje)
                _alerta(pedido, hecho.mensaje)
                return ReembolsoPedido.objects.sin_ambito().get(pk=reembolso_id)
            referencia = hecho.id
    except culqi.ErrorCulqi as error:
        _anotar(reembolso, error.mensaje)
        _alerta(pedido, error.mensaje)
        return ReembolsoPedido.objects.sin_ambito().get(pk=reembolso_id)
    return _cerrar(reembolso_id, referencia, usuario)


def _cerrar(reembolso_id: int, referencia: str, usuario) -> ReembolsoPedido:
    """Culqi devolvió el dinero: el reembolso queda aprobado y el pedido en su estado final."""
    with transaction.atomic():
        reembolso = ReembolsoPedido.objects.sin_ambito().select_for_update().get(pk=reembolso_id)
        if reembolso.estado == ReembolsoPedido.Estado.APROBADO:
            return reembolso
        pedido = PedidoTienda.objects.sin_ambito().select_for_update().get(pk=reembolso.pedido_id)
        ahora = timezone.now()
        reembolso.estado = ReembolsoPedido.Estado.APROBADO
        reembolso.culqi_reembolso_id = referencia[:40]
        reembolso.aprobado_en = ahora
        reembolso.mensaje = ""
        reembolso.save()
        pedido.monto_reembolsado = min(pedido.monto_reembolsado + reembolso.monto, pedido.total)
        pedido.estado = (
            Estado.REEMBOLSADO
            if pedido.monto_reembolsado >= pedido.total
            else Estado.REEMBOLSADO_PARCIAL
        )
        pedido.motivo_atencion = ""
        pedido.save()
        HistorialPedido.objects.create(
            pedido=pedido,
            tipo=HistorialPedido.Tipo.ESTADO,
            estado=pedido.estado,
            texto=f"Culqi devolvió S/ {reembolso.monto:,.2f} al cliente.",
            **(_quien(usuario) if usuario is not None else {}),
        )
        registrar(
            "tienda.reembolso_aprobado",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=f"Pedido {pedido.numero}: Culqi devolvió S/ {reembolso.monto:,.2f}"[:250],
            detalle={"reembolso": reembolso.pk, "tipo": reembolso.tipo},
            inmediato=True,
        )
        transaction.on_commit(catalogo.invalidar)
        transaction.on_commit(lambda: _encolar_correo(reembolso.pk))
    return reembolso


def reintentar(organizacion_id: int, numero: str, *, usuario) -> ReembolsoPedido:
    """Botón «Reintentar reembolso» del panel: vuelve a intentar devolver el dinero."""
    pedido = _pedido_de(organizacion_id, numero)
    if pedido.estado != Estado.REEMBOLSO_PENDIENTE:
        raise ReembolsoNoPermitido("Este pedido no tiene un reembolso pendiente.")
    reembolso = (
        ReembolsoPedido.objects.sin_ambito()
        .filter(pedido=pedido, estado=ReembolsoPedido.Estado.SOLICITADO)
        .order_by("-id")
        .first()
    )
    if reembolso is None:
        raise ReembolsoNoPermitido("No encontramos el reembolso pendiente.")
    return completar(reembolso.pk, usuario=usuario, manual=True)


def reintentar_pendientes() -> int:
    """Tarea periódica: reintenta los reembolsos que Culqi no confirmó. Devuelve cuántos cerró."""
    ids = list(
        ReembolsoPedido.objects.sin_ambito()
        .filter(estado=ReembolsoPedido.Estado.SOLICITADO, intentos__lt=MAX_REINTENTOS)
        .values_list("pk", flat=True)[:100]
    )
    cerrados = 0
    for pk in ids:
        cerrados += completar(pk).estado == ReembolsoPedido.Estado.APROBADO
    return cerrados


# ---------------------------------------------------------------------------
# Correo al cliente
# ---------------------------------------------------------------------------
def _encolar_correo(reembolso_id: int) -> None:
    from .tasks import enviar_correo_reembolso

    enviar_correo_reembolso.delay(reembolso_id)


def enviar_correo(reembolso_id: int) -> bool:
    """Avisa al cliente que se le devuelve su dinero (sin datos de tarjeta ni promesas de fecha)."""
    reembolso = (
        ReembolsoPedido.objects.sin_ambito().select_related("pedido__cuenta").get(pk=reembolso_id)
    )
    if reembolso.estado != ReembolsoPedido.Estado.APROBADO:
        return False
    pedido = reembolso.pedido
    cuerpo = (
        f"Hola {pedido.cuenta.nombres},\n\n"
        f"Te devolvimos S/ {reembolso.monto:,.2f} del pedido {pedido.numero}.\n"
        "El dinero vuelve al mismo medio con el que pagaste. Cuánto demora en verse depende de "
        "tu banco o de tu billetera.\n\n"
        f"Puedes ver el pedido en {settings.TIENDA_URL.rstrip('/')}/cuenta/pedidos\n"
        "Si tienes dudas, escríbenos y con gusto te ayudamos."
    )
    send_mail(f"Reembolso del pedido {pedido.numero}", cuerpo, None, [pedido.cuenta.correo])
    return True
