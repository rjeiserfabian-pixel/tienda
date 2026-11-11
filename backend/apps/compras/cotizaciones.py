"""Cotizaciones de compra: pedir precio a varios proveedores, compararlos y elegir ganadores.

Una solicitud nace en BORRADOR. Mientras no se adjudica se pueden agregar proveedores y registrar
sus respuestas (a mano o desde un archivo); al llegar la primera respuesta queda ABIERTA. Al
adjudicar se elige, producto por producto, qué proveedor gana (puede ser uno distinto por
producto) y se crea UNA orden de compra en borrador por cada proveedor ganador. Después la
solicitud queda ADJUDICADA y ya no cambia. Una solicitud sin adjudicar se puede ANULAR.

Todos los precios se piden en la misma moneda y con la misma base de IGV (la de la solicitud), así
la comparación es justa. Una cotización no mueve stock ni deudas: solo es información de precios.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto
from apps.inventario import periodos
from apps.mantenimiento.models import (
    Almacen,
    Correlativo,
    EstadoRegistro,
    PresentacionProducto,
    Producto,
    Proveedor,
    TipoProducto,
)
from apps.mantenimiento.presentaciones import convertir_a_base
from apps.organizacion.models import Empresa

from . import ordenes
from .exceptions import CotizacionInvalida, CotizacionNoModificable, OrdenCompraInvalida
from .models import (
    FormaPago,
    LineaRespuestaCotizacion,
    LineaSolicitudCotizacion,
    Moneda,
    RespuestaCotizacion,
    SolicitudCotizacion,
)
from .servicios import MAX_LINEAS, MAX_TOTAL, _texto

logger = logging.getLogger(__name__)

CERO = Decimal("0")
MAX_PROVEEDORES = 15
MAX_PLAZO_DIAS = 365
MAX_DIAS_ENTREGA = 365
SEIS_DECIMALES = Decimal("0.000001")
TRES_DECIMALES = Decimal("0.001")
Estado = SolicitudCotizacion.Estado
EstadoRespuesta = RespuestaCotizacion.Estado


# ---------------------------------------------------------------------------
# Lo que pide quien crea o edita la solicitud
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LineaPedida:
    producto: Producto
    cantidad: Decimal
    presentacion: PresentacionProducto | None = None


@dataclass(frozen=True, slots=True)
class PrecioDado:
    """Lo que un proveedor contestó por una línea: precio (None = no la cotiza)."""

    linea_id: int
    precio_unitario: Decimal | None
    cantidad_ofrecida: Decimal | None = None
    observacion: str = ""


@dataclass(frozen=True, slots=True)
class Asignacion:
    """El proveedor ganador de una línea y cuánto se le pide (None = toda la cantidad)."""

    linea_id: int
    respuesta_id: int
    cantidad: Decimal | None = None


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _usuario_id():
    contexto = obtener_contexto()
    return contexto.usuario_id if contexto else None


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"compras:cotizacion:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _bloquear(solicitud: SolicitudCotizacion) -> SolicitudCotizacion:
    periodos.exigir_empresa(solicitud.empresa)
    return SolicitudCotizacion.objects.select_for_update().get(pk=solicitud.pk)


def _exigir_estado(solicitud: SolicitudCotizacion, permitidos: tuple[str, ...], accion: str):
    if solicitud.estado not in permitidos:
        raise CotizacionNoModificable(
            f"No se puede {accion} una cotización en estado «{solicitud.get_estado_display()}»."
        )


def _auditar(accion: str, solicitud: SolicitudCotizacion, resumen: str, **detalle) -> None:
    registrar(
        accion,
        recurso_tipo="solicitud_cotizacion",
        recurso_id=solicitud.pk,
        empresa_id=solicitud.empresa_id,
        resumen=f"Cotización {solicitud.codigo} {resumen}",
        detalle=detalle,
    )


def _decimal(valor, campo: str, *, decimales: Decimal, positivo: bool) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise CotizacionInvalida(f"{campo}: indique un número válido.")
    if valor != valor.quantize(decimales):
        raise CotizacionInvalida(
            f"{campo}: admite hasta {abs(decimales.as_tuple().exponent)} decimales."
        )
    if valor > MAX_TOTAL or valor < 0 or (positivo and valor == 0):
        raise CotizacionInvalida(f"{campo}: el valor no es válido.")
    return valor


# ---------------------------------------------------------------------------
# Validación de la solicitud
# ---------------------------------------------------------------------------
def _validar_proveedores(empresa: Empresa, proveedores: list[Proveedor]) -> list[Proveedor]:
    if len(proveedores) > MAX_PROVEEDORES:
        raise CotizacionInvalida(f"Se puede cotizar con hasta {MAX_PROVEEDORES} proveedores.")
    vistos: set[int] = set()
    for proveedor in proveedores:
        if proveedor.organizacion_id != empresa.organizacion_id:
            raise CotizacionInvalida("Un proveedor no pertenece a la organización.")
        if proveedor.estado != EstadoRegistro.ACTIVO:
            raise CotizacionInvalida(f"{proveedor.nombre} está inactivo.")
        if proveedor.pk in vistos:
            raise CotizacionInvalida(f"{proveedor.nombre} está repetido.")
        vistos.add(proveedor.pk)
    return proveedores


def _validar_lineas(
    empresa: Empresa, lineas: list[LineaPedida]
) -> list[tuple[LineaPedida, str, Decimal]]:
    """Revisa cada producto y devuelve (línea, unidad, factor)."""
    if not lineas:
        raise CotizacionInvalida("Agregue al menos un producto.")
    if len(lineas) > MAX_LINEAS:
        raise CotizacionInvalida(f"Una cotización admite hasta {MAX_LINEAS} productos.")
    vistos: set[tuple[int, int | None]] = set()
    salida = []
    for ln in lineas:
        p = ln.producto
        if p.organizacion_id != empresa.organizacion_id:
            raise CotizacionInvalida("Un producto no pertenece a la organización.")
        if p.tipo != TipoProducto.BIEN or not p.controla_stock:
            raise CotizacionInvalida(f"{p.nombre} no lleva control de stock.")
        clave = (p.pk, ln.presentacion.pk if ln.presentacion else None)
        if clave in vistos:
            raise CotizacionInvalida(f"{p.nombre} está repetido: súmalo en una sola línea.")
        vistos.add(clave)
        if not isinstance(ln.cantidad, Decimal) or not ln.cantidad.is_finite() or ln.cantidad <= 0:
            raise CotizacionInvalida(f"{p.nombre}: la cantidad debe ser mayor que cero.")
        if ln.presentacion is not None:
            pres = ln.presentacion
            if pres.producto_id != p.pk or pres.estado != EstadoRegistro.ACTIVO:
                raise CotizacionInvalida(f"{p.nombre}: la presentación no es válida.")
            try:
                convertir_a_base(pres, ln.cantidad)
            except ValueError as error:
                raise CotizacionInvalida(f"{p.nombre}: {error}") from None
            salida.append((ln, pres.unidad.nombre, pres.factor))
        else:
            if ln.cantidad != ln.cantidad.quantize(TRES_DECIMALES):
                raise CotizacionInvalida(f"{p.nombre}: la cantidad admite hasta 3 decimales.")
            salida.append((ln, p.unidad.nombre, Decimal("1")))
    return salida


def _validar_cabecera(
    empresa: Empresa,
    almacen: Almacen,
    fecha: date,
    fecha_limite: date | None,
    moneda: str,
) -> None:
    periodos.exigir_empresa(empresa)
    if almacen.empresa_id != empresa.pk:
        raise CotizacionInvalida("El almacén no pertenece a la empresa.")
    if almacen.estado != EstadoRegistro.ACTIVO:
        raise CotizacionInvalida("El almacén está inactivo.")
    if moneda not in Moneda.values:
        raise CotizacionInvalida("La moneda no es válida.")
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise CotizacionInvalida("La fecha no es válida.")
    if fecha > timezone.localdate():
        raise CotizacionInvalida("La fecha no puede ser futura.")
    if fecha_limite is not None and fecha_limite < fecha:
        raise CotizacionInvalida("La fecha límite no puede ser anterior a la fecha.")


# ---------------------------------------------------------------------------
# Crear y editar
# ---------------------------------------------------------------------------
def _crear_lineas(solicitud: SolicitudCotizacion, validadas) -> list[LineaSolicitudCotizacion]:
    return LineaSolicitudCotizacion.objects.bulk_create(
        [
            LineaSolicitudCotizacion(
                empresa=solicitud.empresa,
                solicitud=solicitud,
                posicion=posicion,
                producto=ln.producto,
                presentacion=ln.presentacion,
                unidad=unidad,
                factor=factor,
                cantidad=ln.cantidad,
            )
            for posicion, (ln, unidad, factor) in enumerate(validadas, start=1)
        ]
    )


def _lineas_vacias(respuesta: RespuestaCotizacion, lineas) -> None:
    LineaRespuestaCotizacion.objects.bulk_create(
        [
            LineaRespuestaCotizacion(empresa=respuesta.empresa, respuesta=respuesta, linea=ln)
            for ln in lineas
        ]
    )


def _agregar_respuesta(solicitud: SolicitudCotizacion, proveedor: Proveedor, lineas):
    respuesta = RespuestaCotizacion.objects.create(
        empresa=solicitud.empresa, solicitud=solicitud, proveedor=proveedor
    )
    _lineas_vacias(respuesta, lineas)
    return respuesta


@transaction.atomic
def crear_solicitud(
    *,
    empresa: Empresa,
    almacen: Almacen,
    fecha: date,
    lineas: list[LineaPedida],
    proveedores: list[Proveedor],
    moneda: str = Moneda.PEN,
    precios_incluyen_igv: bool = False,
    fecha_limite: date | None = None,
    observacion: str = "",
) -> SolicitudCotizacion:
    """Crea la solicitud en borrador, con los proveedores a los que se les pedirá precio."""
    _validar_cabecera(empresa, almacen, fecha, fecha_limite, moneda)
    validadas = _validar_lineas(empresa, lineas)
    proveedores = _validar_proveedores(empresa, proveedores)
    solicitud = SolicitudCotizacion.objects.create(
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        almacen=almacen,
        fecha=fecha,
        fecha_limite=fecha_limite,
        moneda=moneda,
        precios_incluyen_igv=bool(precios_incluyen_igv),
        observacion=_texto(observacion, 250),
    )
    creadas = _crear_lineas(solicitud, validadas)
    for proveedor in proveedores:
        _agregar_respuesta(solicitud, proveedor, creadas)
    _auditar(
        "compras.cotizacion_creada",
        solicitud,
        "creada",
        lineas=len(creadas),
        proveedores=len(proveedores),
    )
    logger.info("cotizacion_creada", extra={"empresa_id": empresa.pk, "solicitud_id": solicitud.pk})
    return solicitud


@transaction.atomic
def editar_solicitud(
    solicitud: SolicitudCotizacion,
    *,
    almacen: Almacen,
    fecha: date,
    lineas: list[LineaPedida],
    proveedores: list[Proveedor],
    moneda: str = Moneda.PEN,
    precios_incluyen_igv: bool = False,
    fecha_limite: date | None = None,
    observacion: str = "",
) -> SolicitudCotizacion:
    """Cambia una solicitud en borrador. Si ya hay respuestas con precios no se puede editar:
    anúlala y crea otra, para no dejar precios que ya no corresponden a lo pedido."""
    actual = _bloquear(solicitud)
    _exigir_estado(actual, (Estado.BORRADOR,), "editar")
    if RespuestaCotizacion.objects.filter(
        solicitud=actual, estado=EstadoRespuesta.RESPONDIDA
    ).exists():
        raise CotizacionNoModificable(
            "Ya hay respuestas con precios: no se puede editar. Anula la cotización y crea otra."
        )
    _validar_cabecera(actual.empresa, almacen, fecha, fecha_limite, moneda)
    validadas = _validar_lineas(actual.empresa, lineas)
    proveedores = _validar_proveedores(actual.empresa, proveedores)
    actual.almacen, actual.fecha, actual.fecha_limite = almacen, fecha, fecha_limite
    actual.moneda, actual.precios_incluyen_igv = moneda, bool(precios_incluyen_igv)
    actual.observacion = _texto(observacion, 250)
    actual.save()
    # Borrado lógico de lo anterior (queda el rastro) y se arma de nuevo.
    LineaRespuestaCotizacion.objects.filter(respuesta__solicitud=actual).delete()
    RespuestaCotizacion.objects.filter(solicitud=actual).delete()
    LineaSolicitudCotizacion.objects.filter(solicitud=actual).delete()
    creadas = _crear_lineas(actual, validadas)
    for proveedor in proveedores:
        _agregar_respuesta(actual, proveedor, creadas)
    _auditar("compras.cotizacion_editada", actual, "editada", lineas=len(creadas))
    return actual


@transaction.atomic
def agregar_proveedor(solicitud: SolicitudCotizacion, proveedor: Proveedor) -> RespuestaCotizacion:
    """Suma un proveedor a una solicitud que todavía no se adjudicó."""
    actual = _bloquear(solicitud)
    _exigir_estado(actual, (Estado.BORRADOR, Estado.ABIERTA), "agregar proveedores a")
    _validar_proveedores(actual.empresa, [proveedor])
    if RespuestaCotizacion.objects.filter(solicitud=actual, proveedor=proveedor).exists():
        raise CotizacionInvalida(f"{proveedor.nombre} ya está en esta cotización.")
    if RespuestaCotizacion.objects.filter(solicitud=actual).count() >= MAX_PROVEEDORES:
        raise CotizacionInvalida(f"Se puede cotizar con hasta {MAX_PROVEEDORES} proveedores.")
    lineas = list(LineaSolicitudCotizacion.objects.filter(solicitud=actual))
    respuesta = _agregar_respuesta(actual, proveedor, lineas)
    _auditar(
        "compras.cotizacion_proveedor_agregado",
        actual,
        f"suma a {proveedor.nombre}",
        proveedor=proveedor.pk,
    )
    return respuesta


@transaction.atomic
def quitar_proveedor(respuesta: RespuestaCotizacion) -> None:
    """Saca un proveedor que todavía no respondió."""
    actual = _bloquear(respuesta.solicitud)
    _exigir_estado(actual, (Estado.BORRADOR, Estado.ABIERTA), "quitar proveedores de")
    fila = RespuestaCotizacion.objects.select_for_update().get(pk=respuesta.pk)
    if fila.estado != EstadoRespuesta.PENDIENTE:
        raise CotizacionNoModificable("Solo se puede quitar a un proveedor que no ha respondido.")
    LineaRespuestaCotizacion.objects.filter(respuesta=fila).delete()
    fila.delete()
    _auditar(
        "compras.cotizacion_proveedor_quitado",
        actual,
        "quita un proveedor",
        proveedor=fila.proveedor_id,
    )


# ---------------------------------------------------------------------------
# Respuestas de los proveedores
# ---------------------------------------------------------------------------
def _abrir_si_hace_falta(solicitud: SolicitudCotizacion) -> None:
    if solicitud.estado == Estado.BORRADOR:
        solicitud.estado, solicitud.enviada_en = Estado.ABIERTA, timezone.now()
        solicitud.save(update_fields=["estado", "enviada_en"])


def _validar_condiciones(forma_pago: str, plazo_dias: int, plazo_entrega_dias: int) -> str:
    forma = forma_pago or FormaPago.CONTADO
    if forma not in FormaPago.values:
        raise CotizacionInvalida("La forma de pago no es válida.")
    if forma == FormaPago.CONTADO and plazo_dias != 0:
        raise CotizacionInvalida("Al contado no hay plazo de crédito.")
    if forma == FormaPago.CREDITO and not 1 <= plazo_dias <= MAX_PLAZO_DIAS:
        raise CotizacionInvalida(f"El plazo de crédito es de 1 a {MAX_PLAZO_DIAS} días.")
    if not 0 <= plazo_entrega_dias <= MAX_DIAS_ENTREGA:
        raise CotizacionInvalida(f"El plazo de entrega es de 0 a {MAX_DIAS_ENTREGA} días.")
    return forma


@transaction.atomic
def registrar_respuesta(
    respuesta: RespuestaCotizacion,
    *,
    precios: list[PrecioDado],
    forma_pago: str = FormaPago.CONTADO,
    plazo_dias: int = 0,
    plazo_entrega_dias: int = 0,
    validez_hasta: date | None = None,
    observacion: str = "",
    origen: str = RespuestaCotizacion.Origen.MANUAL,
) -> RespuestaCotizacion:
    """Guarda lo que contestó un proveedor. Reemplaza lo anterior (se puede corregir)."""
    solicitud = _bloquear(respuesta.solicitud)
    _exigir_estado(solicitud, (Estado.BORRADOR, Estado.ABIERTA), "responder")
    fila = RespuestaCotizacion.objects.select_for_update().get(pk=respuesta.pk)
    if fila.orden_id:
        raise CotizacionNoModificable("De esta respuesta ya salió una orden de compra.")
    forma = _validar_condiciones(forma_pago, plazo_dias, plazo_entrega_dias)
    if validez_hasta is not None and validez_hasta < solicitud.fecha:
        raise CotizacionInvalida("La validez de los precios no puede ser anterior a la cotización.")

    lineas = {ln.pk: ln for ln in LineaSolicitudCotizacion.objects.filter(solicitud=solicitud)}
    dados: dict[int, PrecioDado] = {}
    for dato in precios:
        linea = lineas.get(dato.linea_id)
        if linea is None:
            raise CotizacionInvalida("Hay un producto que no es de esta cotización.")
        if dato.linea_id in dados:
            raise CotizacionInvalida("Un producto aparece dos veces en la respuesta.")
        precio = dato.precio_unitario
        if precio is not None:
            precio = _decimal(
                precio,
                f"{linea.producto.nombre}: precio",
                decimales=SEIS_DECIMALES,
                positivo=False,
            )
        ofrecida = dato.cantidad_ofrecida
        if ofrecida is not None:
            ofrecida = _decimal(
                ofrecida,
                f"{linea.producto.nombre}: cantidad ofrecida",
                decimales=TRES_DECIMALES,
                positivo=True,
            )
            if ofrecida > linea.cantidad:
                raise CotizacionInvalida(
                    f"{linea.producto.nombre}: no puede ofrecer más de lo pedido."
                )
        dados[dato.linea_id] = PrecioDado(
            dato.linea_id, precio, ofrecida, _texto(dato.observacion, 120)
        )
    if not any(d.precio_unitario is not None for d in dados.values()):
        raise CotizacionInvalida(
            "Indique el precio de al menos un producto, o marque que el proveedor no cotiza."
        )

    existentes = {lr.linea_id: lr for lr in LineaRespuestaCotizacion.objects.filter(respuesta=fila)}
    for linea_id in lineas:
        dato = dados.get(linea_id, PrecioDado(linea_id, None))
        lr = existentes.get(linea_id)
        if lr is None:
            lr = LineaRespuestaCotizacion(empresa=fila.empresa, respuesta=fila, linea_id=linea_id)
        lr.precio_unitario = dato.precio_unitario
        lr.cantidad_ofrecida = dato.cantidad_ofrecida if dato.precio_unitario is not None else None
        lr.observacion = dato.observacion
        lr.save()

    fila.estado = EstadoRespuesta.RESPONDIDA
    fila.origen = origen
    fila.forma_pago, fila.plazo_dias, fila.plazo_entrega_dias = (
        forma,
        plazo_dias,
        plazo_entrega_dias,
    )
    fila.validez_hasta, fila.observacion = validez_hasta, _texto(observacion, 250)
    fila.respondida_en = timezone.now()
    fila.save()
    _abrir_si_hace_falta(solicitud)
    _auditar(
        "compras.cotizacion_respondida",
        solicitud,
        f"respondida por {fila.proveedor.nombre}",
        proveedor=fila.proveedor_id,
        origen=origen,
        precios=sum(1 for d in dados.values() if d.precio_unitario is not None),
    )
    return fila


@transaction.atomic
def declinar_respuesta(respuesta: RespuestaCotizacion, *, motivo: str = "") -> RespuestaCotizacion:
    """El proveedor avisó que no cotiza: queda fuera de la comparación."""
    solicitud = _bloquear(respuesta.solicitud)
    _exigir_estado(solicitud, (Estado.BORRADOR, Estado.ABIERTA), "responder")
    fila = RespuestaCotizacion.objects.select_for_update().get(pk=respuesta.pk)
    if fila.orden_id:
        raise CotizacionNoModificable("De esta respuesta ya salió una orden de compra.")
    LineaRespuestaCotizacion.objects.filter(respuesta=fila).update(
        precio_unitario=None, cantidad_ofrecida=None
    )
    fila.estado, fila.origen = EstadoRespuesta.DECLINADA, RespuestaCotizacion.Origen.MANUAL
    fila.observacion, fila.respondida_en = _texto(motivo, 250), timezone.now()
    fila.save(update_fields=["estado", "origen", "observacion", "respondida_en"])
    _auditar(
        "compras.cotizacion_declinada",
        solicitud,
        f"no cotizada por {fila.proveedor.nombre}",
        proveedor=fila.proveedor_id,
    )
    return fila


# ---------------------------------------------------------------------------
# Comparativo
# ---------------------------------------------------------------------------
def cantidad_efectiva(linea: LineaSolicitudCotizacion, oferta: LineaRespuestaCotizacion) -> Decimal:
    """Lo que el proveedor puede dar: lo que ofreció, o todo lo pedido si no dijo otra cosa."""
    return oferta.cantidad_ofrecida if oferta.cantidad_ofrecida is not None else linea.cantidad


def comparativo(solicitud: SolicitudCotizacion) -> dict:
    """Cuadro de precios lado a lado, con el mejor precio de cada producto y el total por proveedor.

    * ``mejor`` de una línea: el precio más bajo entre quienes la cotizaron.
    * ``total`` de un proveedor: suma de precio × cantidad que puede dar, de lo que cotizó.
    * ``completa``: cotizó todos los productos y por toda la cantidad; solo entre esas respuestas
      se marca el total más bajo (comparar totales de ofertas incompletas engaña).
    """
    lineas = list(
        LineaSolicitudCotizacion.objects.filter(solicitud=solicitud)
        .select_related("producto")
        .order_by("posicion")
    )
    respuestas = list(
        RespuestaCotizacion.objects.filter(solicitud=solicitud)
        .select_related("proveedor")
        .order_by("id")
    )
    ofertas: dict[tuple[int, int], LineaRespuestaCotizacion] = {
        (lr.respuesta_id, lr.linea_id): lr
        for lr in LineaRespuestaCotizacion.objects.filter(respuesta__in=respuestas)
    }

    filas = []
    for ln in lineas:
        precios = []
        for r in respuestas:
            oferta = ofertas.get((r.pk, ln.pk))
            if (
                r.estado == EstadoRespuesta.RESPONDIDA
                and oferta
                and oferta.precio_unitario is not None
            ):
                precios.append((oferta.precio_unitario, r.pk))
        mejor = min(precios)[0] if precios else None
        filas.append(
            {
                "linea": ln.pk,
                "posicion": ln.posicion,
                "producto": ln.producto_id,
                "producto_codigo": ln.producto.codigo,
                "producto_nombre": ln.producto.nombre,
                "unidad": ln.unidad,
                "cantidad": ln.cantidad,
                "mejor_precio": mejor,
                "mas_caro": max(precios)[0] if precios else None,
                "adjudicada_a": ln.adjudicada_a_id,
                "cantidad_adjudicada": ln.cantidad_adjudicada,
                "ofertas": [_oferta(ln, r, ofertas.get((r.pk, ln.pk)), mejor) for r in respuestas],
            }
        )

    proveedores = []
    for r in respuestas:
        total, cotiza, completa = CERO, 0, r.estado == EstadoRespuesta.RESPONDIDA
        for ln in lineas:
            oferta = ofertas.get((r.pk, ln.pk))
            if (
                r.estado == EstadoRespuesta.RESPONDIDA
                and oferta
                and oferta.precio_unitario is not None
            ):
                cantidad = cantidad_efectiva(ln, oferta)
                total += oferta.precio_unitario * cantidad
                cotiza += 1
                if cantidad < ln.cantidad:
                    completa = False
            else:
                completa = False
        proveedores.append(
            {
                "respuesta": r.pk,
                "proveedor": r.proveedor_id,
                "proveedor_nombre": r.proveedor.nombre,
                "estado": r.estado,
                "origen": r.origen,
                "forma_pago": r.forma_pago,
                "plazo_dias": r.plazo_dias,
                "plazo_entrega_dias": r.plazo_entrega_dias,
                "validez_hasta": r.validez_hasta,
                "vencida": bool(r.validez_hasta and r.validez_hasta < timezone.localdate()),
                "observacion": r.observacion,
                "orden": r.orden_id,
                "productos_cotizados": cotiza,
                "total": total.quantize(Decimal("0.01")) if cotiza else None,
                "completa": completa,
            }
        )
    completos = [p["total"] for p in proveedores if p["completa"]]
    mejor_total = min(completos) if completos else None
    for p in proveedores:
        p["mejor_total"] = bool(p["completa"] and p["total"] == mejor_total)
    return {
        "moneda": solicitud.moneda,
        "precios_incluyen_igv": solicitud.precios_incluyen_igv,
        "mejor_total": mejor_total,
        "proveedores": proveedores,
        "lineas": filas,
        "ahorro": _ahorro(lineas, ofertas) if solicitud.estado == Estado.ADJUDICADA else None,
    }


def _oferta(ln, r, oferta, mejor) -> dict:
    cotizada = (
        r.estado == EstadoRespuesta.RESPONDIDA
        and oferta is not None
        and oferta.precio_unitario is not None
    )
    precio = oferta.precio_unitario if cotizada else None
    return {
        "respuesta": r.pk,
        "precio_unitario": precio,
        "cantidad_ofrecida": oferta.cantidad_ofrecida if cotizada else None,
        "observacion": oferta.observacion if oferta else "",
        "es_mejor": bool(cotizada and precio == mejor),
        "parcial": bool(
            cotizada
            and oferta.cantidad_ofrecida is not None
            and oferta.cantidad_ofrecida < ln.cantidad
        ),
        "importe": (precio * cantidad_efectiva(ln, oferta)).quantize(Decimal("0.01"))
        if cotizada
        else None,
    }


def _ahorro(lineas, ofertas) -> Decimal:
    """Cuánto se ahorró frente al precio más alto cotizado, solo en lo adjudicado."""
    total = CERO
    for ln in lineas:
        if ln.adjudicada_a_id is None or ln.cantidad_adjudicada is None:
            continue
        precios = [
            o.precio_unitario
            for (rid, lid), o in ofertas.items()
            if lid == ln.pk and o.precio_unitario is not None
        ]
        ganador = ofertas.get((ln.adjudicada_a_id, ln.pk))
        if precios and ganador and ganador.precio_unitario is not None:
            total += (max(precios) - ganador.precio_unitario) * ln.cantidad_adjudicada
    return total.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Adjudicar: elegir ganadores y crear las órdenes de compra
# ---------------------------------------------------------------------------
@transaction.atomic
def adjudicar(
    solicitud: SolicitudCotizacion, *, asignaciones: list[Asignacion]
) -> list[RespuestaCotizacion]:
    """Elige el proveedor ganador de cada producto y crea una orden en borrador por proveedor.

    No hace falta adjudicar todos los productos: lo que no se asigne queda sin comprar. Cada
    producto solo puede asignarse a un proveedor que haya cotizado ese producto, y por no más de lo
    que ofreció. La orden sale con los precios y condiciones de pago de esa respuesta.
    """
    actual = _bloquear(solicitud)
    _exigir_estado(actual, (Estado.ABIERTA,), "adjudicar")
    if not asignaciones:
        raise CotizacionInvalida("Elija al menos un producto y su proveedor.")
    lineas = {ln.pk: ln for ln in LineaSolicitudCotizacion.objects.filter(solicitud=actual)}
    respuestas = {
        r.pk: r
        for r in RespuestaCotizacion.objects.select_related("proveedor").filter(solicitud=actual)
    }
    ofertas = {
        (lr.respuesta_id, lr.linea_id): lr
        for lr in LineaRespuestaCotizacion.objects.filter(respuesta__in=respuestas)
    }
    vistas: set[int] = set()
    por_respuesta: dict[int, list[tuple[LineaSolicitudCotizacion, Decimal, Decimal]]] = {}
    for a in asignaciones:
        linea, respuesta = lineas.get(a.linea_id), respuestas.get(a.respuesta_id)
        if linea is None or respuesta is None:
            raise CotizacionInvalida("Hay una asignación que no es de esta cotización.")
        if a.linea_id in vistas:
            raise CotizacionInvalida(f"{linea.producto.nombre} tiene dos ganadores.")
        vistas.add(a.linea_id)
        oferta = ofertas.get((respuesta.pk, linea.pk))
        if (
            respuesta.estado != EstadoRespuesta.RESPONDIDA
            or oferta is None
            or oferta.precio_unitario is None
        ):
            raise CotizacionInvalida(
                f"{respuesta.proveedor.nombre} no cotizó {linea.producto.nombre}."
            )
        maximo = cantidad_efectiva(linea, oferta)
        cantidad = a.cantidad if a.cantidad is not None else maximo
        if not isinstance(cantidad, Decimal) or cantidad <= 0 or cantidad > maximo:
            raise CotizacionInvalida(
                f"{linea.producto.nombre}: la cantidad debe ser mayor que cero y no pasar de "
                f"{maximo.normalize():f}."
            )
        por_respuesta.setdefault(respuesta.pk, []).append((linea, cantidad, oferta.precio_unitario))

    hoy = timezone.localdate()
    for respuesta_id, items in por_respuesta.items():
        respuesta = respuestas[respuesta_id]
        try:
            orden = ordenes.crear_orden(
                empresa=actual.empresa,
                proveedor=respuesta.proveedor,
                almacen=actual.almacen,
                fecha_emision=hoy,
                fecha_entrega=(
                    hoy + timedelta(days=respuesta.plazo_entrega_dias)
                    if respuesta.plazo_entrega_dias
                    else None
                ),
                moneda=actual.moneda,
                precios_incluyen_igv=actual.precios_incluyen_igv,
                forma_pago=respuesta.forma_pago or FormaPago.CONTADO,
                plazo_dias=respuesta.plazo_dias,
                observacion=f"Cotización {actual.codigo}",
                lineas=[
                    ordenes.LineaOrden(
                        producto=ln.producto,
                        cantidad=cantidad,
                        precio_unitario=precio,
                        presentacion=ln.presentacion,
                    )
                    for ln, cantidad, precio in items
                ],
            )
        except OrdenCompraInvalida as error:
            raise CotizacionInvalida(f"{respuesta.proveedor.nombre}: {error.mensaje}") from None
        orden.cotizacion = actual
        orden.save(update_fields=["cotizacion"])
        respuesta.orden = orden
        respuesta.save(update_fields=["orden"])
        for ln, cantidad, _precio in items:
            ln.adjudicada_a, ln.cantidad_adjudicada = respuesta, cantidad
            ln.save(update_fields=["adjudicada_a", "cantidad_adjudicada"])

    actual.estado = Estado.ADJUDICADA
    actual.adjudicada_por_id, actual.adjudicada_en = _usuario_id(), timezone.now()
    actual.save(update_fields=["estado", "adjudicada_por_id", "adjudicada_en"])
    _auditar(
        "compras.cotizacion_adjudicada",
        actual,
        "adjudicada",
        ordenes=len(por_respuesta),
        productos=len(asignaciones),
    )
    return [respuestas[i] for i in por_respuesta]


@transaction.atomic
def anular_solicitud(solicitud: SolicitudCotizacion, *, motivo: str) -> SolicitudCotizacion:
    """Anula una cotización que todavía no se adjudicó. El motivo es obligatorio."""
    motivo = _texto(motivo, 250)
    if len(motivo) < 3:
        raise CotizacionInvalida("Indique el motivo de la anulación.")
    actual = _bloquear(solicitud)
    _exigir_estado(actual, (Estado.BORRADOR, Estado.ABIERTA), "anular")
    actual.estado, actual.motivo_anulacion = Estado.ANULADA, motivo
    actual.anulada_por_id, actual.anulada_en = _usuario_id(), timezone.now()
    actual.save(update_fields=["estado", "motivo_anulacion", "anulada_por_id", "anulada_en"])
    _auditar("compras.cotizacion_anulada", actual, "anulada", motivo=motivo[:200])
    return actual
