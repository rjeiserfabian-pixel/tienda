"""Pedidos de la tienda: cálculo con el motor de Ventas, reserva de stock y vencimiento.

* Los IMPORTES salen del mismo motor que usa Ventas (``preparar_venta``): el precio de la lista
  de la tienda más IGV cuando se cobra IGV. El IGV lo decide ``fiscal.sugerir_afectacion`` con el
  régimen de cada empresa y la ZONA del cliente. Para la tienda esa zona es el LUGAR DE ENTREGA
  (ver ``AMAZONIA_DEPARTAMENTOS``): una entrega en la Amazonía, con una empresa de régimen
  Amazonía, sale exonerada y el total es MENOR que el precio que se ve en el catálogo.
* Cada línea la surte UNA sola empresa y UN almacén (la principal si tiene todo; si no, la otra).
  Un carrito mixto da un comprobante por empresa (lo arma ``preparar_venta``).
* El envío entra como una línea de servicio de la empresa principal; su tarifa es el monto FINAL.
* El pedido APARTA el stock (``ReservaStock``) mientras se paga y lo suelta si se cancela o vence.
  Aquí NO se crean comprobantes ni se descuenta el stock: eso ocurre al cobrar.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.compras.calculo import EXONERADO, GRAVADO
from apps.core.tenant import contexto_tenant
from apps.inventario import series as inv_series
from apps.inventario.models import SaldoStock
from apps.mantenimiento import fiscal
from apps.mantenimiento.models import (
    Almacen,
    Categoria,
    Cliente,
    Correlativo,
    EstadoRegistro,
    Familia,
    ListaPrecio,
    PrecioProducto,
    Producto,
    TipoProducto,
    Ubigeo,
    UnidadMedida,
    ZonaFiscal,
)
from apps.mantenimiento.productos import sembrar_unidades, siguiente_codigo
from apps.mantenimiento.validators import validar_documento
from apps.organizacion.models import Empresa
from apps.ventas import servicios as ventas
from apps.ventas.exceptions import VentaInvalida

from . import carrito, catalogo, envios, reservas, series_pedido
from .catalogo import Contexto
from .exceptions import (
    CorreoSinConfirmar,
    PedidoInvalido,
    PedidoNoCancelable,
    PedidoNoEncontrado,
)
from .models import (
    CuentaCliente,
    DireccionCuenta,
    IntentoPago,
    LineaPedido,
    PedidoTienda,
    PuntoRecojo,
    ReembolsoPedido,
    ReservaStock,
)

logger = logging.getLogger(__name__)

CENTIMO = Decimal("0.01")
CERO = Decimal("0")
ENVIO, RECOJO = "ENVIO", "RECOJO"
BOLETA, FACTURA = ventas.BOLETA, ventas.FACTURA
CLAVE_CONTADOR = "pedido_tienda"
NOMBRE_ENVIO = "Envío a domicilio (tienda virtual)"

#: Departamentos con el beneficio de la Amazonía (Ley 27037): Amazonas, Loreto, Madre de Dios,
#: San Martín y Ucayali (los 2 primeros dígitos del ubigeo); el resto del país es «fuera de la
#: región». Es el ÚNICO lugar donde se define; la afectación final depende además del régimen de
#: cada empresa.
AMAZONIA_DEPARTAMENTOS = frozenset({"01", "16", "17", "22", "25"})
MOTIVO_EXONERADO = "Tu entrega está en la Amazonía: la compra está exonerada de IGV."


def _q(valor: Decimal) -> Decimal:
    return valor.quantize(CENTIMO, rounding=ROUND_HALF_UP)


def zona_fiscal_de(ubigeo: str) -> str:
    """DENTRO de la región con beneficio de la Amazonía, o FUERA."""
    if len(ubigeo or "") == 6 and ubigeo[:2] in AMAZONIA_DEPARTAMENTOS:
        return ZonaFiscal.DENTRO
    return ZonaFiscal.FUERA


# ---------------------------------------------------------------------------
# Datos que pide el comprobante
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DatosComprobante:
    tipo: str = BOLETA  # 03 boleta, 01 factura
    documento_tipo: str = ""
    documento_numero: str = ""
    nombre: str = ""
    direccion_fiscal: str = ""


def _validar_comprobante(datos: DatosComprobante) -> DatosComprobante:
    if datos.tipo not in (BOLETA, FACTURA):
        raise PedidoInvalido("Elige boleta o factura.")
    nombre = " ".join((datos.nombre or "").split())
    numero = "".join((datos.documento_numero or "").split())
    tipo_doc = datos.documento_tipo or ""
    if datos.tipo == FACTURA:
        if tipo_doc != "RUC" or len(numero) != 11:
            raise PedidoInvalido("Para una factura necesitamos el RUC (11 dígitos).")
        if not nombre:
            raise PedidoInvalido("Escribe la razón social para la factura.")
        if not (datos.direccion_fiscal or "").strip():
            raise PedidoInvalido("Escribe la dirección fiscal para la factura.")
    elif numero and tipo_doc not in ("DNI", "CE", "PASAPORTE"):
        raise PedidoInvalido("Para la boleta usa DNI, carné de extranjería o pasaporte.")
    if numero:
        try:
            validar_documento(tipo_doc, numero)
        except Exception:  # noqa: BLE001 - cualquier error de validación se muestra igual al cliente
            raise PedidoInvalido("El número de documento no es válido.") from None
    return DatosComprobante(
        datos.tipo, tipo_doc, numero, nombre, " ".join((datos.direccion_fiscal or "").split())
    )


# ---------------------------------------------------------------------------
# Producto de servicio «Envío»
# ---------------------------------------------------------------------------
def producto_envio(organizacion_id: int, lista_id: int) -> Producto:
    """El producto interno con que el envío entra al comprobante (se crea una sola vez).

    Es un servicio activo, SIN publicar en la web y sin stock. El motor de Ventas exige que todo
    producto tenga un precio en la lista; aquí vale S/ 1.00 de referencia: el monto real del envío
    se pasa siempre como precio de la línea.
    """
    producto = (
        Producto.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, nombre=NOMBRE_ENVIO, tipo=TipoProducto.SERVICIO)
        .first()
    )
    if producto is None:
        with transaction.atomic():
            unidad = (
                UnidadMedida.objects.sin_ambito()
                .filter(organizacion_id=organizacion_id, abreviatura="SERV")
                .first()
            )
            if unidad is None:
                sembrar_unidades(organizacion_id)
                unidad = UnidadMedida.objects.sin_ambito().get(
                    organizacion_id=organizacion_id, abreviatura="SERV"
                )
            familia, _ = Familia.objects.sin_ambito().get_or_create(
                organizacion_id=organizacion_id, nombre="Servicios"
            )
            categoria, _ = Categoria.objects.sin_ambito().get_or_create(
                organizacion_id=organizacion_id, familia=familia, nombre="Servicios"
            )
            producto = Producto.objects.sin_ambito().create(
                organizacion_id=organizacion_id,
                codigo=siguiente_codigo(organizacion_id),
                nombre=NOMBRE_ENVIO,
                tipo=TipoProducto.SERVICIO,
                categoria=categoria,
                unidad=unidad,
                controla_stock=False,
                publicado_web=False,
            )
    if (
        not PrecioProducto.objects.sin_ambito()
        .filter(producto=producto, lista_id=lista_id)
        .exists()
    ):
        PrecioProducto.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            producto=producto,
            lista_id=lista_id,
            precio=Decimal("1.00"),
        )
    return producto


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Calculo:
    modalidad: str
    entrega: dict
    comprobante: DatosComprobante
    zona_fiscal: str
    lineas: list[dict]  # lo que se guarda en LineaPedido
    por_empresa: list[dict]
    subtotal_productos: Decimal
    costo_envio: Decimal
    igv: Decimal
    total: Decimal
    subtotal_mostrado: Decimal  # lo que decía el catálogo (para detectar la exoneración)
    igv_exonerado: bool
    motivo_igv: str
    punto: PuntoRecojo | None = None
    avisos: list[str] = field(default_factory=list)


def _empresas_de(organizacion_id: int) -> list[Empresa]:
    return list(
        Empresa.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO)
        .order_by("pk")
    )


def _orden(empresas: list[Empresa]) -> list[Empresa]:
    """La principal primero y las demás por su id (siempre el mismo orden)."""
    return sorted(empresas, key=lambda e: (not e.es_principal, e.pk))


def _almacenes_de_recojo(
    ctx: Contexto, punto_id: int | None, pares
) -> tuple[PuntoRecojo, set[int]]:
    puntos = envios.puntos_de_recojo(ctx, pares)
    elegido = next((p for p in puntos if p["id"] == punto_id), None)
    if elegido is None:
        raise PedidoInvalido("Elige la tienda donde recogerás tu pedido.")
    if not elegido["disponible"]:
        raise PedidoInvalido(
            "Esa tienda no tiene todo tu pedido. Elige otra o cambia las cantidades."
        )
    punto = PuntoRecojo.objects.sin_ambito().get(pk=punto_id, organizacion_id=ctx.organizacion_id)
    enlace = PuntoRecojo.almacenes.through.objects.filter(puntorecojo_id=punto.pk)
    ids = set(enlace.values_list("almacen_id", flat=True)) & set(ctx.almacen_ids)
    return punto, ids


def _precio_de_oferta(producto) -> Decimal | None:
    """El precio de oferta vigente del producto (sin IGV), o ``None`` si no está en oferta."""
    oferta = getattr(producto, "precio_oferta", None)
    normal = getattr(producto, "precio_web", None)
    if oferta is not None and normal is not None and oferta < normal:
        return oferta
    return None


def _asignar(pares, almacen_ids: set[int], empresas: dict[int, Empresa], *, bloquear: bool):
    """Quién surte cada línea: ``[(producto, cantidad, empresa_id, almacén | None)]``.

    Cada línea sale COMPLETA de un solo almacén. Con ``bloquear`` se bloquean los saldos
    (``select_for_update``) para que dos pedidos a la vez no aparten el mismo stock.
    """
    con_stock = [(p, c) for p, c in pares if p.controla_stock and p.tipo == TipoProducto.BIEN]
    saldos: dict[int, list] = {}
    if con_stock:
        consulta = SaldoStock.objects.sin_ambito().filter(
            producto_id__in=[p.pk for p, _ in con_stock],
            almacen_id__in=almacen_ids,
            almacen__permite_venta=True,
            almacen__estado=EstadoRegistro.ACTIVO,
        )
        if bloquear:
            consulta = consulta.select_for_update(of=("self",)).order_by("pk")
        for s in consulta:
            saldos.setdefault(s.producto_id, []).append(s)
    apartado = reservas.apartado(almacen_ids, [p.pk for p, _ in con_stock])
    # Los productos con serie solo se surten de donde hay series EN STOCK (no basta el saldo).
    con_serie = [p.pk for p, _ in con_stock if p.lleva_serie]
    series_en_stock = inv_series.en_stock_por_almacen(con_serie, almacen_ids) if con_serie else {}
    almacenes = {a.pk: a for a in Almacen.objects.sin_ambito().filter(pk__in=almacen_ids)}
    llevan_stock = {p.pk for p, _ in con_stock}
    resultado = []
    for producto, cantidad in pares:
        cant = Decimal(cantidad)
        if producto.pk not in llevan_stock:
            resultado.append((producto, cant, None, None))
            continue
        mejor: dict[int, tuple[Decimal, int]] = {}  # empresa -> (disponible, almacén)
        for s in saldos.get(producto.pk, []):
            libre = s.cantidad - apartado.get((s.almacen_id, s.producto_id), CERO)
            if producto.lleva_serie:
                en_series = Decimal(series_en_stock.get((s.almacen_id, s.producto_id), 0))
                libre = min(libre, en_series - apartado.get((s.almacen_id, s.producto_id), CERO))
            if libre >= cant and (s.empresa_id not in mejor or libre > mejor[s.empresa_id][0]):
                mejor[s.empresa_id] = (libre, s.almacen_id)
        elegida = next((e for e in _orden(list(empresas.values())) if e.pk in mejor), None)
        if elegida is None:
            raise PedidoInvalido(
                f"No hay una tienda que tenga las {cantidad} unidades de «{producto.nombre}». "
                "Baja la cantidad o inténtalo más tarde."
            )
        resultado.append((producto, cant, elegida.pk, almacenes[mejor[elegida.pk][1]]))
    return resultado


def _ubigeo_de_recojo(punto: PuntoRecojo, almacen_ids: set[int]) -> str:
    if punto.ubigeo:
        return punto.ubigeo
    for a in Almacen.objects.sin_ambito().filter(pk__in=almacen_ids).select_related("sucursal"):
        if a.ubigeo or a.sucursal.ubigeo:
            return a.ubigeo or a.sucursal.ubigeo
    return ""


def _calcular(
    ctx: Contexto,
    entradas: list[dict],
    *,
    modalidad: str,
    ubigeo: str = "",
    punto_id: int | None = None,
    comprobante: DatosComprobante | None = None,
    exigir_documento: bool = True,
    bloquear: bool = False,
) -> Calculo:
    if modalidad not in (ENVIO, RECOJO):
        raise PedidoInvalido("Elige envío a domicilio o recojo en tienda.")
    comp = _validar_comprobante(comprobante or DatosComprobante())
    lineas_vista, pares, quitados = carrito.resolver(ctx, entradas)
    if quitados:
        raise PedidoInvalido(
            "Algunos productos de tu carrito ya no están a la venta. Revisa el carrito."
        )
    if not pares:
        raise PedidoInvalido("Tu carrito está vacío.")
    for linea in lineas_vista:
        if linea["problema"]:
            raise PedidoInvalido(f"{linea['nombre']}: {linea['problema']}")
    mostrado = sum((Decimal(ln["subtotal"]) for ln in lineas_vista), CERO)

    # --- Entrega ---
    punto = None
    if modalidad == ENVIO:
        envio = envios.cotizar_envio(
            ctx, ubigeo=ubigeo, peso=envios.peso_total(pares, ctx), subtotal=mostrado
        )
        if not envio["disponible"]:
            raise PedidoInvalido(envio["motivo"])
        almacen_ids = set(ctx.almacen_ids)
    else:
        envio = None
        punto, almacen_ids = _almacenes_de_recojo(ctx, punto_id, pares)
    empresas = {e.pk: e for e in _empresas_de(ctx.organizacion_id)}
    asignadas = _asignar(pares, almacen_ids, empresas, bloquear=bloquear)
    principal = _orden(list(empresas.values()))[0] if empresas else None
    if principal is None:
        raise PedidoInvalido("La tienda no tiene una empresa que facture.")
    zona = zona_fiscal_de(ubigeo if modalidad == ENVIO else _ubigeo_de_recojo(punto, almacen_ids))
    lista = ListaPrecio.objects.sin_ambito().get(pk=ctx.lista_id)

    entradas_venta = [
        ventas.LineaEntrada(
            producto=p,
            cantidad=c,
            empresa=empresas[eid] if eid else principal,
            almacen=alm,
            # Con una oferta vigente se vende a ese precio (sin IGV); queda congelado en el pedido.
            precio_unitario=_precio_de_oferta(p),
        )
        for p, c, eid, alm in asignadas
    ]
    costo_envio = CERO
    producto_de_envio = None
    if envio and envio["modalidad"] == "TIENDA" and Decimal(envio["costo"]) > 0:
        producto_de_envio = producto_envio(ctx.organizacion_id, ctx.lista_id)
        costo_envio = Decimal(envio["costo"])
        sugerencia = fiscal.sugerir_afectacion(
            empresa=principal,
            operacion=fiscal.VENTA,
            zona=zona,
            producto=producto_de_envio,
        )
        base = costo_envio
        if sugerencia.afectacion.grupo == GRAVADO:
            base = costo_envio / (Decimal(1) + sugerencia.porcentaje / Decimal(100))
        entradas_venta.append(
            ventas.LineaEntrada(
                producto=producto_de_envio,
                cantidad=Decimal(1),
                empresa=principal,
                almacen=None,
                precio_unitario=_q(base),
            )
        )

    cliente = Cliente(
        organizacion_id=ctx.organizacion_id,
        nombre=comp.nombre or "Cliente de la tienda",
        tipo_documento=comp.documento_tipo or "OTRO",
        numero_documento=comp.documento_numero or "0",
        zona=zona,
        estado=EstadoRegistro.ACTIVO,
    )
    try:
        with contexto_tenant(ctx.organizacion_id, empresas.keys(), None):
            preparada = ventas.preparar_venta(
                empresa=principal,
                fecha=timezone.localdate(),
                tipo_comprobante=comp.tipo,
                lineas=entradas_venta,
                cliente=cliente,
                lista=lista,
                puede_descontar=True,
                puede_vender_stock_otra_empresa=True,
                estricto=False,
                revisar_series=False,
            )
    except VentaInvalida as error:
        raise PedidoInvalido(error.mensaje) from None
    if preparada.avisos:
        raise PedidoInvalido(preparada.avisos[0])

    lineas, por_empresa = [], []
    exonera = False
    for c in preparada.comprobantes:
        t = c.totales
        por_empresa.append(
            {
                "empresa": c.empresa.pk,
                "razon_social": c.empresa.razon_social,
                "base": format(t.op_gravada + t.op_exonerada + t.op_inafecta, "f"),
                "igv": format(t.igv, "f"),
                "total": format(t.total, "f"),
            }
        )
        for ln, importes in zip(c.lineas, t.lineas, strict=True):
            es_envio = (
                producto_de_envio is not None and ln.entrada.producto.pk == producto_de_envio.pk
            )
            if not es_envio and ln.afectacion.grupo == EXONERADO:
                exonera = True
            lineas.append(
                {
                    "producto": ln.entrada.producto,
                    "empresa": c.empresa,
                    "almacen": ln.entrada.almacen,
                    "descripcion": ln.descripcion,
                    "cantidad": ln.entrada.cantidad,
                    "precio_unitario": _q(importes.total / ln.entrada.cantidad),
                    "base": importes.valor_venta,
                    "igv": importes.igv,
                    "total": importes.total,
                    "es_envio": es_envio,
                }
            )
    total = preparada.total
    envio_total = sum((ln["total"] for ln in lineas if ln["es_envio"]), CERO)
    productos_total = total - envio_total
    if (
        exigir_documento
        and comp.tipo == BOLETA
        and not comp.documento_numero
        and total > ventas.TOPE_BOLETA_SIN_IDENTIFICAR
    ):
        raise PedidoInvalido(
            f"Para compras de más de S/ {ventas.TOPE_BOLETA_SIN_IDENTIFICAR:,.2f} la boleta "
            "lleva tu DNI."
        )
    exonerado = exonera and productos_total < mostrado - CENTIMO / 2
    return Calculo(
        modalidad=modalidad,
        entrega=envio or {},
        comprobante=comp,
        zona_fiscal=zona,
        lineas=lineas,
        por_empresa=por_empresa,
        subtotal_productos=productos_total,
        costo_envio=envio_total,
        igv=sum((c.totales.igv for c in preparada.comprobantes), CERO),
        total=total,
        subtotal_mostrado=mostrado,
        igv_exonerado=exonerado,
        motivo_igv=MOTIVO_EXONERADO if exonerado else "",
        punto=punto,
    )


def calcular(ctx: Contexto, entradas: list[dict], **kwargs) -> Calculo:
    """Arma el pedido completo con los importes del motor de Ventas. No escribe pedidos.

    Se activa el contexto de la organización de la tienda (no hay sesión de usuario del sistema):
    el motor de Ventas y los catálogos lo exigen.
    """
    empresas = [e.pk for e in _empresas_de(ctx.organizacion_id)]
    with contexto_tenant(ctx.organizacion_id, empresas, None):
        return _calcular(ctx, entradas, **kwargs)


def totales_exactos(ctx: Contexto, entradas, **kwargs) -> dict:
    """Los totales del motor para la vista previa de la compra (sin crear nada)."""
    c = calcular(ctx, entradas, exigir_documento=False, **kwargs)
    return {
        "por_empresa": c.por_empresa,
        "subtotal_productos": format(_q(c.subtotal_productos), "f"),
        "costo_envio": format(_q(c.costo_envio), "f"),
        "igv": format(_q(c.igv), "f"),
        "total": format(_q(c.total), "f"),
        "igv_exonerado": c.igv_exonerado,
        "motivo_igv": c.motivo_igv,
        "zona_fiscal": c.zona_fiscal,
    }


# ---------------------------------------------------------------------------
# Crear, cancelar y vencer
# ---------------------------------------------------------------------------
def _siguiente_numero(organizacion_id: int) -> str:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=organizacion_id, clave=CLAVE_CONTADOR
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return f"T-{fila.ultimo:06d}"


def _pedidos(organizacion_id: int):
    return PedidoTienda.objects.sin_ambito().filter(organizacion_id=organizacion_id)


def _destino(cuenta: CuentaCliente, direccion_id: int | None) -> DireccionCuenta:
    direccion = None
    if direccion_id:
        direccion = (
            DireccionCuenta.objects.sin_ambito().filter(pk=direccion_id, cuenta=cuenta).first()
        )
    if direccion is None:
        raise PedidoInvalido("Elige una de tus direcciones para el envío.")
    return direccion


def crear_pedido(
    cuenta: CuentaCliente,
    ctx: Contexto,
    entradas: list[dict],
    *,
    modalidad: str,
    direccion_id: int | None,
    punto_id: int | None,
    comprobante: DatosComprobante,
    clave,
) -> tuple[PedidoTienda, bool]:
    """Crea el pedido y aparta el stock. Devuelve ``(pedido, creado)``; con la misma ``clave``
    devuelve el pedido ya creado (un reintento del navegador no duplica nada)."""
    if not cuenta.verificada:
        raise CorreoSinConfirmar()
    existente = (
        _pedidos(ctx.organizacion_id).filter(cuenta=cuenta, clave_idempotencia=clave).first()
    )
    if existente is not None:
        return existente, False
    try:
        with transaction.atomic():
            # Se bloquea la cuenta: sus pedidos se crean de a uno (clave y tope de pendientes).
            CuentaCliente.objects.sin_ambito().select_for_update().get(pk=cuenta.pk)
            existente = (
                _pedidos(ctx.organizacion_id)
                .filter(cuenta=cuenta, clave_idempotencia=clave)
                .first()
            )
            if existente is not None:
                return existente, False
            ahora = timezone.now()
            pendientes = (
                _pedidos(ctx.organizacion_id)
                .filter(
                    cuenta=cuenta, estado=PedidoTienda.Estado.PENDIENTE_PAGO, expira_en__gt=ahora
                )
                .count()
            )
            if pendientes >= settings.TIENDA_PEDIDOS_PENDIENTES_MAX:
                raise PedidoInvalido(
                    "Ya tienes pedidos esperando pago. Págalos o cancélalos antes de hacer otro."
                )
            direccion = _destino(cuenta, direccion_id) if modalidad == ENVIO else None
            calculo = calcular(
                ctx,
                entradas,
                modalidad=modalidad,
                ubigeo=direccion.ubigeo if direccion else "",
                punto_id=punto_id,
                comprobante=comprobante,
                bloquear=True,
            )
            return _guardar(cuenta, ctx, calculo, direccion, clave, ahora), True
    except IntegrityError:
        # Dos pedidos con la misma clave a la vez: gana el primero.
        existente = (
            _pedidos(ctx.organizacion_id).filter(cuenta=cuenta, clave_idempotencia=clave).first()
        )
        if existente is None:
            raise
        return existente, False


def _guardar(cuenta, ctx, c: Calculo, direccion, clave, ahora) -> PedidoTienda:
    envio = c.entrega or {}
    ubicacion = ""
    if direccion is not None:
        u = Ubigeo.objects.filter(codigo=direccion.ubigeo).first()
        ubicacion = u.nombre_completo if u else ""
    pedido = PedidoTienda.objects.sin_ambito().create(
        organizacion_id=ctx.organizacion_id,
        numero=_siguiente_numero(ctx.organizacion_id),
        cuenta=cuenta,
        modalidad=c.modalidad,
        clave_idempotencia=clave,
        expira_en=ahora + timedelta(minutes=settings.TIENDA_PEDIDO_MINUTOS),
        ubigeo_entrega=direccion.ubigeo if direccion else "",
        ubicacion_entrega=ubicacion,
        direccion_entrega=direccion.direccion if direccion else "",
        referencia_entrega=direccion.referencia if direccion else "",
        receptor=direccion.receptor if direccion else "",
        celular_receptor=direccion.celular if direccion else "",
        punto=c.punto,
        punto_nombre=c.punto.nombre if c.punto else "",
        envio_zona=(envio.get("zona") or {}).get("nombre", ""),
        envio_paga_en_destino=bool(envio.get("paga_en_destino")),
        envio_plazo=envio.get("plazo", ""),
        envio_detalle=envio.get("detalle", ""),
        comprobante_tipo=c.comprobante.tipo,
        documento_tipo=c.comprobante.documento_tipo,
        documento_numero=c.comprobante.documento_numero,
        nombre_comprobante=c.comprobante.nombre,
        direccion_fiscal=c.comprobante.direccion_fiscal,
        zona_fiscal=c.zona_fiscal,
        subtotal_productos=_q(c.subtotal_productos),
        costo_envio=_q(c.costo_envio),
        igv=_q(c.igv),
        total=_q(c.total),
        igv_exonerado=c.igv_exonerado,
        motivo_igv=c.motivo_igv,
    )
    for ln in c.lineas:
        linea = LineaPedido.objects.sin_ambito().create(
            organizacion_id=ctx.organizacion_id,
            pedido=pedido,
            producto=ln["producto"],
            empresa=ln["empresa"],
            almacen=ln["almacen"],
            descripcion=ln["descripcion"],
            cantidad=ln["cantidad"],
            precio_unitario=ln["precio_unitario"],
            base=_q(ln["base"]),
            igv=_q(ln["igv"]),
            total=_q(ln["total"]),
            es_envio=ln["es_envio"],
        )
        if ln["almacen"] is not None:
            ReservaStock.objects.sin_ambito().create(
                organizacion_id=ctx.organizacion_id,
                pedido=pedido,
                linea=linea,
                producto=ln["producto"],
                almacen=ln["almacen"],
                cantidad=ln["cantidad"],
            )
    registrar(
        "tienda.pedido_creado",
        recurso_tipo="pedido_tienda",
        recurso_id=pedido.pk,
        organizacion_id=ctx.organizacion_id,
        resumen=f"Pedido {pedido.numero} creado en la tienda",
        detalle={"total": str(pedido.total), "modalidad": c.modalidad},
    )
    transaction.on_commit(catalogo.invalidar)
    return pedido


def _con_pago_en_camino(ahora=None):
    """Pedidos con un cobro en curso o sin confirmar (reciente): no se vencen ni se cancelan."""
    ahora = ahora or timezone.now()
    return IntentoPago.objects.sin_ambito().filter(
        estado__in=[IntentoPago.Estado.EN_CURSO, IntentoPago.Estado.INCIERTO],
        actualizado_en__gt=ahora - timedelta(minutes=30),
    )


def liberar_reservas(pedido: PedidoTienda) -> int:
    """Suelta el stock apartado del pedido (cancelar, vencer)."""
    return (
        ReservaStock.objects.sin_ambito()
        .filter(pedido=pedido, liberada_en__isnull=True)
        .update(liberada_en=timezone.now())
    )


def pedido_de(cuenta: CuentaCliente, numero: str) -> PedidoTienda:
    pedido = _pedidos(cuenta.organizacion_id).filter(cuenta=cuenta, numero=numero).first()
    if pedido is None:
        raise PedidoNoEncontrado()
    return pedido


def cancelar(cuenta: CuentaCliente, numero: str) -> PedidoTienda:
    with transaction.atomic():
        pedido = (
            _pedidos(cuenta.organizacion_id)
            .select_for_update()
            .filter(cuenta=cuenta, numero=numero)
            .first()
        )
        if pedido is None:
            raise PedidoNoEncontrado()
        if pedido.estado != PedidoTienda.Estado.PENDIENTE_PAGO:
            raise PedidoNoCancelable()
        if _con_pago_en_camino().filter(pedido=pedido).exists():
            raise PedidoNoCancelable("Tu pago se está procesando: espera a que termine.")
        pedido.estado = PedidoTienda.Estado.CANCELADO
        pedido.save(update_fields=["estado", "actualizado_en"])
        liberar_reservas(pedido)
        registrar(
            "tienda.pedido_cancelado",
            recurso_tipo="pedido_tienda",
            recurso_id=pedido.pk,
            organizacion_id=pedido.organizacion_id,
            resumen=f"Pedido {pedido.numero} cancelado por el cliente",
        )
        transaction.on_commit(catalogo.invalidar)
    return pedido


def expirar_vencidos() -> int:
    """Marca como vencidos los pedidos sin pagar cuyo plazo pasó y suelta su stock."""
    ahora = timezone.now()
    ids = list(
        PedidoTienda.objects.sin_ambito()
        .filter(estado=PedidoTienda.Estado.PENDIENTE_PAGO, expira_en__lt=ahora)
        .exclude(pk__in=_con_pago_en_camino(ahora).values("pedido_id"))
        .values_list("pk", flat=True)[:500]
    )
    vencidos = 0
    for pk in ids:
        with transaction.atomic():
            pedido = (
                PedidoTienda.objects.sin_ambito()
                .select_for_update(skip_locked=True)
                .filter(pk=pk, estado=PedidoTienda.Estado.PENDIENTE_PAGO, expira_en__lt=ahora)
                .first()
            )
            if pedido is None:  # otro proceso lo tomó o lo pagaron entre tanto
                continue
            pedido.estado = PedidoTienda.Estado.EXPIRADO
            pedido.save(update_fields=["estado", "actualizado_en"])
            liberar_reservas(pedido)
            transaction.on_commit(catalogo.invalidar)
            vencidos += 1
    if vencidos:
        logger.info("tienda_pedidos_vencidos", extra={"cantidad": vencidos})
    return vencidos


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
def pedido_salida(p: PedidoTienda, *, detalle: bool = True) -> dict:
    base = {
        "numero": p.numero,
        "estado": p.estado,
        "estado_texto": p.get_estado_display(),
        "modalidad": p.modalidad,
        "creado_en": p.creado_en.isoformat(),
        "expira_en": p.expira_en.isoformat(),
        "total": format(p.total, "f"),
        "pagado_en": p.pagado_en.isoformat() if p.pagado_en else None,
        "requiere_atencion": p.estado
        in (
            PedidoTienda.Estado.PAGADO_SIN_COMPROBANTE,
            PedidoTienda.Estado.PAGADO_FUERA_DE_PLAZO,
            PedidoTienda.Estado.REEMBOLSO_PENDIENTE,
        ),
        "monto_reembolsado": format(p.monto_reembolsado, "f"),
    }
    if not detalle:
        return base
    lineas = list(LineaPedido.objects.sin_ambito().filter(pedido=p).order_by("id"))
    comprobantes = []
    if p.venta_id:
        from apps.ventas.models import ComprobanteVenta

        comprobantes = [
            {"numero": c.numero_completo, "empresa": c.empresa.razon_social}
            for c in ComprobanteVenta.objects.sin_ambito()
            .filter(venta_id=p.venta_id)
            .select_related("empresa")
            .order_by("id")
        ]
    return {
        **base,
        "comprobantes": comprobantes,
        "entrega": {
            "ubicacion": p.ubicacion_entrega,
            "direccion": p.direccion_entrega,
            "referencia": p.referencia_entrega,
            "receptor": p.receptor,
            "celular": p.celular_receptor,
            "punto": p.punto_nombre,
            "zona": p.envio_zona,
            "paga_en_destino": p.envio_paga_en_destino,
            "plazo": p.envio_plazo,
            "detalle": p.envio_detalle,
        },
        "comprobante": {
            "tipo": p.comprobante_tipo,
            "documento_tipo": p.documento_tipo,
            "documento_numero": p.documento_numero,
            "nombre": p.nombre_comprobante,
            "direccion_fiscal": p.direccion_fiscal,
        },
        "importes": {
            "subtotal_productos": format(p.subtotal_productos, "f"),
            "costo_envio": format(p.costo_envio, "f"),
            "igv": format(p.igv, "f"),
            "total": format(p.total, "f"),
            "igv_exonerado": p.igv_exonerado,
            "motivo_igv": p.motivo_igv,
        },
        "lineas": [
            {
                "producto": ln.producto_id,
                "descripcion": ln.descripcion,
                "cantidad": format(ln.cantidad.normalize(), "f"),
                "precio_unitario": format(ln.precio_unitario, "f"),
                "total": format(ln.total, "f"),
                "es_envio": ln.es_envio,
                # Solo cuando el equipo ya va hacia el cliente; antes la serie puede cambiar.
                "series": series_pedido.series_para_cliente(p, ln),
            }
            for ln in lineas
        ],
        # Lo que el cliente necesita saber: cuánto se le devolvió y cuándo (nada interno).
        "reembolsos": [
            {
                "monto": format(r.monto, "f"),
                "estado": r.estado,
                "fecha": (r.aprobado_en or r.creado_en).isoformat(),
            }
            for r in ReembolsoPedido.objects.sin_ambito().filter(pedido=p).order_by("id")
        ],
    }
