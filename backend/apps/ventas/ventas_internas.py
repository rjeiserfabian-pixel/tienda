"""Venta interna entre las dos empresas: un solo comprobante para un carrito mixto.

Cuando el carrito mezcla productos de dos empresas y se quiere un solo comprobante, la empresa que
factura (``facturadora``) le «compra» a la otra (``entregadora``) lo que ella tiene en su stock, y
recién entonces se lo vende al cliente. Aquí se hace el primer paso:

1. Se revisa, sin escribir nada, que la entregadora tenga stock y costo de cada producto.
2. La mercadería sale del almacén de la entregadora al costo promedio de allí y entra al almacén de
   la facturadora por ese mismo valor (sin margen entre las empresas). Las series viajan.
3. Las líneas del carrito pasan a ser de la facturadora, con su almacén, y la venta sigue como
   cualquier otra: un solo comprobante, una sola serie, el cobro a su caja.
4. Con la venta ya creada se deja el documento ``VentaInterna`` que une todo, y cada línea queda
   ligada a la línea de la venta que salió de ella.

Deshacerla es lo inverso, siempre en cadena y en una sola transacción:

* **Anular la venta**: se anula el comprobante y, después, la venta interna (la mercadería sale de
  la facturadora y vuelve a la entregadora, al mismo valor con que pasó).
* **Devolución del cliente** (nota de crédito que reingresa al stock): lo devuelto de una línea que
  vino de la otra empresa vuelve a ella, al costo con que salió. Lo que salió del stock propio de
  la facturadora se queda en ella.

Es al contado y no deja deuda entre las empresas (es como un traspaso de mercadería). Solo aplica
cuando el carrito es mixto: si todo sale de una empresa, es una venta normal en ella.

Por ahora el respaldo es el documento interno; la factura electrónica entre las empresas es una
entrega aparte y se rechaza con un mensaje claro hasta que exista.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto_requerido
from apps.inventario import numeracion, periodos
from apps.inventario.costeo import a_dos
from apps.inventario.exceptions import AnulacionNoPermitida, StockInsuficiente
from apps.inventario.models import SaldoStock
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    devolver_traslado_entre_empresas,
    registrar_traslado_entre_empresas,
)
from apps.mantenimiento.models import (
    Almacen,
    Correlativo,
    EstadoRegistro,
    Producto,
    TipoAlmacen,
    TipoProducto,
)
from apps.organizacion.models import Empresa

from . import liquidacion_interna
from .exceptions import VentaInvalida, VentaNoAnulable
from .models import (
    CERO,
    DevolucionInterna,
    DocumentoInterno,
    LineaVenta,
    LineaVentaInterna,
    Venta,
    VentaInterna,
)
from .servicios import LineaEntrada, sucursal_equivalente


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RevisionLinea:
    """Lo que se sabe de una línea de la otra empresa antes de cobrar (solo lectura)."""

    linea: LineaEntrada
    almacen_destino: Almacen | None
    disponible: Decimal
    costo_unitario: Decimal
    problemas: tuple[str, ...] = ()


@dataclass(slots=True)
class _Trasladada:
    linea: LineaEntrada
    almacen_origen: Almacen | None
    almacen_destino: Almacen | None
    movimiento_salida: object = None
    movimiento_entrada: object = None
    costo_unitario: Decimal = CERO
    costo_total: Decimal = CERO
    # La línea del carrito ya como línea de la facturadora (con ella se liga la línea de la venta).
    nueva: LineaEntrada | None = None


@dataclass(slots=True)
class Traslado:
    """Lo que una empresa le pasó a la que factura, ya movido en el Kardex de las dos."""

    entregadora: Empresa
    facturadora: Empresa
    fecha: date
    codigo: uuid.UUID = field(default_factory=uuid.uuid4)
    lineas: list[_Trasladada] = field(default_factory=list)

    @property
    def total_costo(self) -> Decimal:
        return sum((ln.costo_total for ln in self.lineas), CERO)


# ---------------------------------------------------------------------------
# Reglas
# ---------------------------------------------------------------------------
def _nombre(empresa: Empresa) -> str:
    return empresa.nombre_comercial or empresa.razon_social


def _lleva_stock(producto: Producto) -> bool:
    return producto.tipo == TipoProducto.BIEN and producto.controla_stock


def _es_traslado(linea: LineaEntrada, facturadora: Empresa) -> bool:
    return linea.empresa.pk != facturadora.pk


def _es_consumida(linea: LineaEntrada, facturadora: Empresa) -> bool:
    """Un repuesto de la otra empresa que ya salió de su stock (el taller lo usó al reparar).

    No hay mercadería que mover: solo se anota lo que la facturadora le debe por su costo.
    """
    return (
        _es_traslado(linea, facturadora)
        and linea.stock_ya_descontado
        and _lleva_stock(linea.producto)
    )


def documento_no_disponible(documento: str) -> str:
    """Por qué no se puede usar ese respaldo ("" si se puede)."""
    if documento not in DocumentoInterno.values:
        return "El respaldo de la venta interna no es válido."
    if documento == DocumentoInterno.FACTURA:
        return (
            "La factura electrónica entre las empresas todavía no está disponible: "
            "use el documento interno."
        )
    return ""


def _exigir_documento(documento: str) -> None:
    if motivo := documento_no_disponible(documento):
        raise VentaInvalida(motivo)


def _exigir_misma_organizacion(lineas: list[LineaEntrada], facturadora: Empresa) -> None:
    for ln in lineas:
        if ln.empresa.organizacion_id != facturadora.organizacion_id:
            raise VentaInvalida("La empresa que surte no es de la organización.")


def exigir_carrito_mixto(lineas: list[LineaEntrada], facturadora: Empresa) -> None:
    """La venta interna solo existe si el carrito mezcla a la facturadora con otra empresa."""
    if not lineas:
        raise VentaInvalida("Agregue al menos un producto.")
    organizacion = facturadora.organizacion_id
    for ln in lineas:
        if ln.empresa.organizacion_id != organizacion:
            raise VentaInvalida("La empresa que surte no es de la organización.")
    propias = any(not _es_traslado(ln, facturadora) for ln in lineas)
    ajenas = any(_es_traslado(ln, facturadora) for ln in lineas)
    if not ajenas:
        raise VentaInvalida(
            f"Todo el carrito es de {_nombre(facturadora)}: es una venta normal, "
            "no hace falta una venta interna."
        )
    if not propias:
        otras = {_nombre(ln.empresa) for ln in lineas}
        raise VentaInvalida(
            f"Todo el carrito es de {', '.join(sorted(otras))}: se factura con esa empresa, "
            "no hace falta una venta interna."
        )


def almacen_destino(
    facturadora: Empresa, origen: Almacen, elegidos: dict[int, Almacen] | None = None
) -> Almacen:
    """El almacén de la facturadora donde entra lo que sale de ``origen``.

    Si se eligió uno, ese (validado). Si no, el de su misma tienda (el mismo local físico); con
    varios, el principal; si sigue habiendo duda, se pide elegir.
    """
    elegido = (elegidos or {}).get(origen.pk)
    if elegido is not None:
        if elegido.empresa_id != facturadora.pk:
            raise VentaInvalida(f"El almacén {elegido.nombre} no es de {_nombre(facturadora)}.")
        _exigir_almacen_de_venta(elegido)
        return elegido
    candidatos = Almacen.objects.sin_ambito().filter(
        empresa=facturadora, estado=EstadoRegistro.ACTIVO, permite_venta=True
    )
    tienda = sucursal_equivalente(facturadora, origen.sucursal)
    if tienda is not None:
        candidatos = candidatos.filter(sucursal=tienda)
    lista = list(candidatos.order_by("pk"))
    if not lista:
        raise VentaInvalida(
            f"{_nombre(facturadora)} no tiene un almacén de venta donde recibir lo que sale de "
            f"«{origen.nombre}»."
        )
    if len(lista) > 1:
        principales = [a for a in lista if a.tipo == TipoAlmacen.PRINCIPAL]
        if len(principales) != 1:
            raise VentaInvalida(
                f"{_nombre(facturadora)} tiene varios almacenes de venta: elija en cuál recibe "
                f"lo que sale de «{origen.nombre}»."
            )
        return principales[0]
    return lista[0]


def _exigir_almacen_de_venta(almacen: Almacen) -> None:
    if almacen.estado != EstadoRegistro.ACTIVO or not almacen.permite_venta:
        raise VentaInvalida(f"No se vende desde el almacén {almacen.nombre}.")


def revisar(
    lineas: list[LineaEntrada],
    facturadora: Empresa,
    almacenes_destino: dict[int, Almacen] | None = None,
    *,
    exigir_mixto: bool = True,
) -> list[RevisionLinea]:
    """Cada línea de la otra empresa con su stock, su costo y lo que impide pasarla (sin escribir).

    Sirve para avisar ANTES de cobrar y es lo primero que se hace al registrar. Un servicio (sin
    stock) no se traslada: no aparece aquí.
    """
    if exigir_mixto:
        exigir_carrito_mixto(lineas, facturadora)
    ajenas = [
        ln
        for ln in lineas
        if _es_traslado(ln, facturadora)
        and _lleva_stock(ln.producto)
        and not _es_consumida(ln, facturadora)
    ]
    pedido: dict[tuple[int, int], Decimal] = {}
    for ln in ajenas:
        if ln.almacen is not None:
            clave = (ln.almacen.pk, ln.producto.pk)
            pedido[clave] = pedido.get(clave, CERO) + ln.cantidad
    revisadas = []
    for ln in ajenas:
        problemas: list[str] = []
        nombre = " ".join(str(ln.producto.nombre).split())
        origen = ln.almacen
        destino = None
        disponible, costo = CERO, CERO
        if ln.stock_ya_descontado:
            problemas.append(
                f"{nombre}: un repuesto que ya salió del almacén no se puede pasar a otra empresa."
            )
        elif origen is None or origen.empresa_id != ln.empresa.pk:
            problemas.append(f"{nombre}: indique el almacén de {_nombre(ln.empresa)}.")
        else:
            try:
                destino = almacen_destino(facturadora, origen, almacenes_destino)
            except VentaInvalida as error:
                problemas.append(error.mensaje)
            saldo = (
                SaldoStock.objects.sin_ambito()
                .filter(empresa=ln.empresa, almacen=origen, producto=ln.producto)
                .first()
            )
            disponible = saldo.cantidad if saldo else CERO
            costo = saldo.costo_unitario if saldo else CERO
            necesario = pedido[(origen.pk, ln.producto.pk)]
            if disponible < necesario:
                problemas.append(
                    f"{nombre}: {_nombre(ln.empresa)} tiene {disponible:,.3f} y se necesitan "
                    f"{necesario:,.3f}."
                )
            elif costo <= 0:
                problemas.append(
                    f"{nombre}: no tiene costo en {_nombre(ln.empresa)}; la venta interna "
                    "saldría en cero. Registre su compra o ajuste el costo primero."
                )
        revisadas.append(RevisionLinea(ln, destino, disponible, costo, tuple(problemas)))
    return revisadas


def lineas_de_la_facturadora(
    lineas: list[LineaEntrada],
    facturadora: Empresa,
    revisadas: list[RevisionLinea],
) -> list[LineaEntrada]:
    """El carrito como quedará: todo de la facturadora y con el almacén donde recibe."""
    destino_de = {id(r.linea): r.almacen_destino for r in revisadas}
    resultado = []
    for ln in lineas:
        if not _es_traslado(ln, facturadora):
            resultado.append(ln)
        elif id(ln) in destino_de:
            resultado.append(replace(ln, empresa=facturadora, almacen=destino_de[id(ln)]))
        else:  # un servicio: no mueve stock, solo cambia de empresa
            resultado.append(replace(ln, empresa=facturadora))
    return resultado


# ---------------------------------------------------------------------------
# Trasladar (mueve el Kardex) y dejar el documento
# ---------------------------------------------------------------------------
def trasladar(
    lineas: list[LineaEntrada],
    *,
    facturadora: Empresa,
    fecha: date,
    documento: str = DocumentoInterno.INTERNO,
    almacenes_destino: dict[int, Almacen] | None = None,
) -> tuple[list[LineaEntrada], list[Traslado]]:
    """Pasa al stock de la facturadora lo que ella no tiene y devuelve el carrito ya suyo.

    Debe llamarse dentro de la transacción de la venta: si algo falla después, todo se deshace.
    """
    _exigir_documento(documento)
    periodos.exigir_empresa(facturadora)
    consumidas = [ln for ln in lineas if _es_consumida(ln, facturadora)]
    if consumidas:
        _exigir_misma_organizacion(lineas, facturadora)
    revisadas = revisar(lineas, facturadora, almacenes_destino, exigir_mixto=not consumidas)
    problemas = [p for r in revisadas for p in r.problemas]
    if problemas:
        raise VentaInvalida(" ".join(problemas))

    traslados: dict[int, Traslado] = {}
    grupos: dict[tuple[int, int, int], list[_Trasladada]] = {}
    for r in revisadas:
        entregadora = r.linea.empresa
        traslado = traslados.setdefault(
            entregadora.pk, Traslado(entregadora=entregadora, facturadora=facturadora, fecha=fecha)
        )
        item = _Trasladada(r.linea, r.linea.almacen, r.almacen_destino)
        traslado.lineas.append(item)
        grupos.setdefault((entregadora.pk, r.linea.almacen.pk, r.almacen_destino.pk), []).append(
            item
        )

    for (entregadora_id, _, _), items in grupos.items():
        traslado = traslados[entregadora_id]
        salida, entrada = registrar_traslado_entre_empresas(
            origen=items[0].almacen_origen,
            destino=items[0].almacen_destino,
            fecha=fecha,
            lineas=[
                LineaNueva(it.linea.producto, it.linea.cantidad, series=tuple(it.linea.series))
                for it in items
            ],
            codigo=traslado.codigo,
        )
        valores = list(salida.lineas.order_by("orden", "id"))
        for it, valor in zip(items, valores, strict=True):
            if valor.costo_total <= 0:
                raise VentaInvalida(
                    f"{it.linea.producto.nombre}: la venta interna saldría en cero. "
                    "Revise su costo."
                )
            it.movimiento_salida, it.movimiento_entrada = salida, entrada
            it.costo_unitario, it.costo_total = valor.costo_unitario, valor.costo_total
    for ln in consumidas:
        # Ya salió del stock de la otra empresa: solo se anota lo que costó (sin costo, no se debe).
        costo = ln.costo_total or CERO
        if costo <= 0:
            continue
        entregadora = ln.empresa
        traslado = traslados.setdefault(
            entregadora.pk, Traslado(entregadora=entregadora, facturadora=facturadora, fecha=fecha)
        )
        traslado.lineas.append(
            _Trasladada(
                ln,
                None,
                None,
                costo_unitario=a_dos(costo / ln.cantidad) if ln.cantidad else CERO,
                costo_total=costo,
            )
        )
    resultado = lineas_de_la_facturadora(lineas, facturadora, revisadas)
    item_de = {id(it.linea): it for t in traslados.values() for it in t.lineas}
    for original, nueva in zip(lineas, resultado, strict=True):
        if id(original) in item_de:
            item_de[id(original)].nueva = nueva
    return resultado, list(traslados.values())


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"ventas:interna:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def registrar_documentos(
    venta: Venta,
    traslados: list[Traslado],
    documento: str = DocumentoInterno.INTERNO,
    lineas_de_venta: dict[int, LineaVenta] | None = None,
) -> list[VentaInterna]:
    """Deja una venta interna por cada empresa que entregó, atada a la venta al cliente.

    ``lineas_de_venta`` dice qué línea de la venta salió de cada línea trasladada (por la línea
    del carrito ya como línea de la facturadora): con eso una devolución sabe qué vuelve.
    """
    por_entrada = lineas_de_venta or {}
    creadas = []
    for traslado in traslados:
        interna = VentaInterna.objects.create(
            empresa=traslado.entregadora,
            empresa_destino=traslado.facturadora,
            codigo=traslado.codigo,
            numero=_siguiente_numero(traslado.entregadora),
            fecha=traslado.fecha,
            venta=venta,
            documento=documento,
            total_costo=traslado.total_costo,
        )
        LineaVentaInterna.objects.bulk_create(
            [
                LineaVentaInterna(
                    empresa=traslado.entregadora,
                    venta_interna=interna,
                    orden=orden,
                    producto=it.linea.producto,
                    descripcion=" ".join(str(it.linea.producto.nombre).split())[:250],
                    cantidad=it.linea.cantidad,
                    costo_unitario=it.costo_unitario,
                    costo_total=it.costo_total,
                    series=list(it.linea.series),
                    almacen_origen=it.almacen_origen,
                    almacen_destino=it.almacen_destino,
                    movimiento_salida=it.movimiento_salida,
                    movimiento_entrada=it.movimiento_entrada,
                    linea_venta=por_entrada.get(id(it.nueva)),
                )
                for orden, it in enumerate(traslado.lineas)
            ]
        )
        liquidacion_interna.partida_de_venta(interna)
        registrar(
            "ventas.venta_interna_registrada",
            recurso_tipo="venta_interna",
            recurso_id=interna.pk,
            empresa_id=traslado.entregadora.pk,
            resumen=(
                f"Venta interna N° {interna.numero:06d}: {_nombre(traslado.entregadora)} → "
                f"{_nombre(traslado.facturadora)}, costo S/ {traslado.total_costo}"
            ),
            detalle={
                "venta": venta.numero,
                "documento": documento,
                "lineas": len(traslado.lineas),
            },
        )
        creadas.append(interna)
    return creadas


# ---------------------------------------------------------------------------
# Deshacer en cadena
# ---------------------------------------------------------------------------
def _orden(empresa: Empresa) -> tuple[bool, int]:
    """La principal primero y las demás por id: el mismo orden con que Ventas bloquea."""
    return (not empresa.es_principal, empresa.pk)


def _exigir_acceso(empresas, error, accion: str) -> None:
    """Deshacer toca el Kardex de las dos empresas: hace falta acceso a ambas (mensaje claro)."""
    contexto = obtener_contexto_requerido()
    for empresa in sorted(empresas, key=_orden):
        if not contexto.empresa_habilitada(empresa.pk):
            raise error(
                f"Esta venta pasó mercadería entre empresas: para {accion} hace falta tener "
                f"acceso también a {_nombre(empresa)}."
            )


def _bloquear(empresas, error, accion: str) -> None:
    _exigir_acceso(empresas, error, accion)
    for empresa in sorted(empresas, key=_orden):
        numeracion.bloquear(empresa)


def internas_vigentes(comprobante) -> list[VentaInterna]:
    """Las ventas internas vigentes que alimentaron el comprobante de esta venta."""
    return list(
        VentaInterna.objects.sin_ambito()
        .filter(
            venta_id=comprobante.venta_id,
            empresa_destino_id=comprobante.empresa_id,
            estado=VentaInterna.Estado.EMITIDO,
        )
        .select_related("empresa", "empresa_destino")
    )


def empresas_que_entregaron(venta_id: int) -> list[int]:
    """Las empresas que pasaron mercadería en las ventas internas vigentes de una venta."""
    return list(
        VentaInterna.objects.sin_ambito()
        .filter(venta_id=venta_id, estado=VentaInterna.Estado.EMITIDO)
        .values_list("empresa_id", flat=True)
        .distinct()
    )


def empresas_que_entregaron_en(comprobante_id: int, linea_ids: list[int] | None) -> list[int]:
    """Las empresas de las que vino lo que se devuelve de un comprobante (``None`` = todo)."""
    consulta = LineaVentaInterna.objects.sin_ambito().filter(
        linea_venta__comprobante_id=comprobante_id,
        venta_interna__estado=VentaInterna.Estado.EMITIDO,
    )
    if linea_ids is not None:
        consulta = consulta.filter(linea_venta_id__in=linea_ids)
    return list(consulta.values_list("empresa_id", flat=True).distinct())


def bloquear_para_anular(comprobante) -> list[VentaInterna]:
    """Antes de anular: comprueba el acceso a las dos empresas y bloquea sus correlativos.

    Se hace lo primero, en el orden de siempre, para que anular y una venta interna simultánea no
    se esperen entre sí. Devuelve las ventas internas que habrá que deshacer (puede no haber).
    """
    internas = internas_vigentes(comprobante)
    if internas:
        empresas = {i.empresa for i in internas} | {comprobante.empresa}
        _bloquear(empresas, VentaNoAnulable, "anularla")
    return internas


def anular(interna: VentaInterna, *, motivo: str) -> None:
    """Deshace la venta interna: sale de la facturadora y vuelve a la entregadora, al mismo valor.

    Se llama con la venta al cliente ya anulada (la mercadería ya volvió al almacén de la
    facturadora). Si esa mercadería ya salió por otra venta, no se puede y se dice claro.
    """
    nota = f"Anulación de la venta interna N° {interna.numero:06d}: {motivo}"
    lineas = list(
        interna.lineas.select_related("movimiento_entrada", "movimiento_salida").order_by("orden")
    )
    # Los repuestos del taller ya consumidos no tienen movimientos: solo se compensa la deuda.
    entradas = {
        ln.movimiento_entrada.pk: ln.movimiento_entrada for ln in lineas if ln.movimiento_entrada_id
    }
    salidas = {
        ln.movimiento_salida.pk: ln.movimiento_salida for ln in lineas if ln.movimiento_salida_id
    }
    try:
        # Primero se saca lo que recibió la facturadora y después se devuelve a la entregadora.
        for pk in sorted(entradas):
            anular_movimiento(entradas[pk], motivo=nota, _interno=True)
        for pk in sorted(salidas):
            anular_movimiento(salidas[pk], motivo=nota, _interno=True)
    except (AnulacionNoPermitida, StockInsuficiente) as error:
        raise VentaNoAnulable(
            f"No se puede deshacer la venta interna: la mercadería que recibió "
            f"{_nombre(interna.empresa_destino)} ya no está en su almacén ({error.mensaje})"
        ) from None
    interna.anular(motivo=motivo)
    liquidacion_interna.partida_de_anulacion(interna)
    registrar(
        "ventas.venta_interna_anulada",
        recurso_tipo="venta_interna",
        recurso_id=interna.pk,
        empresa_id=interna.empresa_id,
        resumen=f"Se anuló la venta interna N° {interna.numero:06d}",
        detalle={"motivo": motivo, "venta": interna.venta_id},
    )


def anular_de_comprobante(internas: list[VentaInterna], *, motivo: str) -> None:
    """Deshace las ventas internas de un comprobante que se acaba de anular."""
    for interna in sorted(internas, key=lambda i: i.pk):
        anular(interna, motivo=motivo)


def bloquear_para_devolver(comprobante, linea_ids: list[int] | None = None) -> bool:
    """Antes de una nota de crédito que reingresa al stock: acceso y bloqueo de las dos empresas.

    Solo si entre lo que se devuelve (``linea_ids``; todo el comprobante si es ``None``) hay
    mercadería que vino de otra empresa. Devuelve si la hay.
    """
    consulta = LineaVentaInterna.objects.sin_ambito().filter(
        linea_venta__comprobante_id=comprobante.pk,
        venta_interna__estado=VentaInterna.Estado.EMITIDO,
    )
    if linea_ids is not None:
        consulta = consulta.filter(linea_venta_id__in=linea_ids)
    empresas = {ln.empresa for ln in consulta.select_related("empresa")}
    if not empresas:
        return False
    _bloquear(empresas | {comprobante.empresa}, VentaInvalida, "devolverla")
    return True


def devolver_a_quien_entrego(nota, calculo, lineas_nota, fecha: date) -> None:
    """Lo que el cliente devolvió y vino de la otra empresa vuelve a ella, al costo con que salió.

    Va después de reingresar la devolución al almacén de la facturadora: de ahí sale ahora, por el
    valor exacto con que había salido de la entregadora (lo que una pierde es lo que la otra
    recupera). Lo que salió del stock propio de la facturadora se queda en ella.
    """
    por_linea = {
        li.linea_venta_id: li
        for li in LineaVentaInterna.objects.sin_ambito()
        .filter(
            linea_venta_id__in=[d.linea.pk for d in calculo.lineas],
            venta_interna__estado=VentaInterna.Estado.EMITIDO,
            # Lo ya consumido en un servicio no vuelve a la otra empresa (no hay mercadería).
            movimiento_salida__isnull=False,
        )
        .select_related("venta_interna", "almacen_origen", "almacen_destino", "producto")
    }
    # El valor que la facturadora tiene ahora en cada producto: de ahí no puede salir más. La nota
    # reingresa cada devolución redondeada a céntimos y a veces queda un céntimo menos que lo que
    # había salido de la entregadora: en ese caso vuelve ese céntimo menos (no se inventa valor).
    tiene = {
        (sa.almacen_id, sa.producto_id): sa.costo_total
        for sa in SaldoStock.objects.sin_ambito().filter(
            empresa_id=nota.empresa_id,
            almacen_id__in={li.almacen_destino_id for li in por_linea.values()},
            producto_id__in={li.producto_id for li in por_linea.values()},
        )
    }
    grupos: dict[tuple[int, int, int], list[tuple]] = {}
    for d, nota_linea in zip(calculo.lineas, lineas_nota, strict=True):
        li = por_linea.get(d.linea.pk)
        if li is None:
            continue
        if d.linea.almacen_id != li.almacen_destino_id:
            raise VentaInvalida(
                f"{li.descripcion}: la devolución no entra al almacén donde la recibió la "
                "venta interna."
            )
        antes = (
            DevolucionInterna.objects.sin_ambito()
            .filter(linea=li)
            .aggregate(cantidad=Sum("cantidad"), costo=Sum("costo_total"))
        )
        resta_cantidad = li.cantidad - (antes["cantidad"] or CERO)
        resta_costo = li.costo_total - (antes["costo"] or CERO)
        if d.cantidad > resta_cantidad:
            raise VentaInvalida(f"{li.descripcion}: ya se devolvió a quien lo entregó.")
        if d.cantidad == resta_cantidad:
            importe = resta_costo  # lo último que queda: exactamente lo que faltaba
        else:
            importe = min(a_dos(li.costo_total * d.cantidad / li.cantidad), resta_costo)
        reserva = (li.almacen_destino_id, li.producto_id)
        importe = min(importe, tiene.get(reserva, CERO))
        tiene[reserva] = tiene.get(reserva, CERO) - importe
        clave = (li.venta_interna_id, li.almacen_destino_id, li.almacen_origen_id)
        grupos.setdefault(clave, []).append((d, nota_linea, li, importe))

    for items in grupos.values():
        primero = items[0][2]
        salida, entrada = devolver_traslado_entre_empresas(
            origen=primero.almacen_destino,
            destino=primero.almacen_origen,
            fecha=fecha,
            lineas=[
                LineaNueva(li.producto, d.cantidad, importe=importe, series=tuple(d.series))
                for d, _, li, importe in items
            ],
            codigo=primero.venta_interna.codigo,
            observacion=f"Devolución {nota.numero_completo}.",
        )
        valores = list(salida.lineas.order_by("orden", "id"))
        for (d, _, li, _), valor in zip(items, valores, strict=True):
            importe = valor.costo_total  # lo que de verdad salió y entró
            devolucion = DevolucionInterna.objects.create(
                empresa=li.empresa,
                venta_interna=li.venta_interna,
                nota=nota,
                linea=li,
                cantidad=d.cantidad,
                costo_total=importe,
                series=list(d.series),
                movimiento_salida=salida,
                movimiento_entrada=entrada,
            )
            # Lo devuelto vuelve a la que entregó: ahora ella le debe esa parte a la que facturó.
            liquidacion_interna.partida_de_devolucion(li.venta_interna, devolucion)
        registrar(
            "ventas.venta_interna_devuelta",
            recurso_tipo="venta_interna",
            recurso_id=primero.venta_interna_id,
            empresa_id=primero.empresa_id,
            resumen=(
                f"Venta interna N° {primero.venta_interna.numero:06d}: devolución de "
                f"{nota.numero_completo} a {_nombre(primero.empresa)}"
            ),
            detalle={"nota": nota.pk, "lineas": len(items)},
        )
