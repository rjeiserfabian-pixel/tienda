"""Devolver mercadería a un proveedor (nota de crédito de la compra).

Una devolución nace SIEMPRE de una compra vigente. Aquí se decide cuánto se puede devolver de cada
línea, qué importes y qué IGV corresponden, y se saca la mercadería del almacén al costo con que
entró en esa compra (no al promedio). Todo ocurre en UNA transacción: o queda la devolución con su
salida de inventario, o no queda nada.

Reglas de importes (iguales a las de ``calculo.py``: un solo redondeo, sin inventar céntimos):

* Lo devuelto de una línea es proporcional a su cantidad: ``importe × devuelto ÷ comprado``,
  redondeado a céntimos. Cuando se devuelve TODO lo que faltaba de la línea, se toma el resto
  exacto (lo comprado menos lo ya devuelto), así varias devoluciones suman justo la línea.
* El ajuste de redondeo de la nota (hasta ±0,10) forma parte del total, nunca del costo.

El dinero de la nota se reparte siempre en este orden, todo en la moneda de la compra:

1. Baja lo que se debe de la compra (si fue a crédito), de la cuota más antigua a la más nueva.
2. Lo que ya estaba pagado vuelve en dinero a una caja o cuenta (reembolso), por lo que se indique.
3. Lo que falte queda como saldo a favor con el proveedor.

Anular la devolución deshace todo: las cuotas recuperan su monto, el reembolso sale de la caja y el
saldo a favor se anula (si todavía no se usó).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.inventario import periodos
from apps.inventario.costeo import a_dos
from apps.inventario.exceptions import AnulacionNoPermitida
from apps.inventario.models import (
    EstadoSerie,
    OrigenMovimiento,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import LineaNueva, anular_movimiento
from apps.inventario.movimientos import registrar_movimiento as registrar_salida
from apps.mantenimiento import fiscal
from apps.mantenimiento.models import AfectacionIGV, EstadoRegistro, TipoComprobante
from apps.organizacion.models import Empresa

from .cuentas_por_pagar import _cuotas_bloqueadas, repartir
from .exceptions import DevolucionInvalida, DevolucionNoAnulable
from .models import (
    AplicacionDevolucion,
    Compra,
    CreditoProveedor,
    CuotaCompra,
    DevolucionCompra,
    FormaPago,
    LineaCompra,
    LineaDevolucionCompra,
    ReembolsoCompra,
)
from .servicios import PagoEntrada, _detalle_cambio, _validar_pago

logger = logging.getLogger(__name__)

CERO = Decimal("0")
TRES = Decimal("0.001")
CENTIMO = Decimal("0.01")
TOPE_AJUSTE = Decimal("0.10")
MAX_LINEAS = 200
TIPO_NOTA_DE_CREDITO = "07"


# ---------------------------------------------------------------------------
# Cálculo puro
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Previo:
    """Lo que ya se devolvió de una línea de la compra (devoluciones vigentes)."""

    cantidad: Decimal = CERO
    cantidad_base: Decimal = CERO
    valor_venta: Decimal = CERO
    impuesto: Decimal = CERO
    costo_soles: Decimal = CERO


@dataclass(frozen=True, slots=True)
class ParteLinea:
    """Una línea de la compra, lo ya devuelto y lo que ahora se quiere devolver."""

    cantidad: Decimal  # comprada, en la unidad de la línea
    cantidad_base: Decimal
    factor: Decimal
    valor_venta: Decimal
    impuesto: Decimal
    costo_soles: Decimal
    grupo: str  # GRAVADO | EXONERADO | INAFECTO
    tipo_impuesto: str  # IGV | IVAP | NINGUNO
    previo: Previo
    pedida: Decimal  # cantidad a devolver ahora, en la unidad de la línea


@dataclass(frozen=True, slots=True)
class ResultadoLineaDevuelta:
    cantidad: Decimal
    cantidad_base: Decimal
    valor_venta: Decimal
    impuesto: Decimal
    total: Decimal
    costo_soles: Decimal


@dataclass(frozen=True, slots=True)
class ResultadoDevolucion:
    lineas: tuple[ResultadoLineaDevuelta, ...]
    op_gravada: Decimal
    igv: Decimal
    op_ivap: Decimal
    ivap: Decimal
    op_exonerada: Decimal
    op_inafecta: Decimal
    ajuste_redondeo: Decimal
    total: Decimal
    costo_soles: Decimal
    queda_pendiente: bool  # si después de ésta todavía queda algo por devolver de la compra


def _parte(total_linea: Decimal, previo: Decimal, comprada: Decimal, pedida: Decimal) -> Decimal:
    """La parte de un importe de la línea que corresponde a ``pedida`` unidades."""
    resto = total_linea - previo
    proporcional = a_dos(total_linea * pedida / comprada)
    return min(max(proporcional, CERO), max(resto, CERO))


def calcular_devolucion(
    partes: Sequence[ParteLinea], *, ajuste_redondeo: Decimal = CERO
) -> ResultadoDevolucion:
    """Importes, IGV y costo de una devolución. No toca la base de datos."""
    if not partes:
        raise DevolucionInvalida("Indique al menos un producto a devolver.")
    if ajuste_redondeo != a_dos(ajuste_redondeo) or abs(ajuste_redondeo) > TOPE_AJUSTE:
        raise DevolucionInvalida("El ajuste de redondeo es de hasta 0.10, con dos decimales.")
    lineas: list[ResultadoLineaDevuelta] = []
    queda = False
    for p in partes:
        pendiente = p.cantidad - p.previo.cantidad
        if p.pedida <= 0:
            raise DevolucionInvalida("La cantidad a devolver debe ser mayor que cero.")
        if p.pedida > pendiente:
            raise DevolucionInvalida(
                f"Solo se puede devolver {pendiente:f} (se compró {p.cantidad:f} "
                f"y ya se devolvió {p.previo.cantidad:f})."
            )
        completa = p.pedida == pendiente
        if completa:
            base = p.cantidad_base - p.previo.cantidad_base
            valor = p.valor_venta - p.previo.valor_venta
            impuesto = p.impuesto - p.previo.impuesto
            costo = p.costo_soles - p.previo.costo_soles
        else:
            queda = True
            base = (p.pedida * p.factor).quantize(TRES)
            if base != p.pedida * p.factor:
                raise DevolucionInvalida("La cantidad devuelta no es válida para la unidad.")
            valor = _parte(p.valor_venta, p.previo.valor_venta, p.cantidad, p.pedida)
            impuesto = _parte(p.impuesto, p.previo.impuesto, p.cantidad, p.pedida)
            costo = _parte(p.costo_soles, p.previo.costo_soles, p.cantidad, p.pedida)
        lineas.append(
            ResultadoLineaDevuelta(p.pedida, base, valor, impuesto, valor + impuesto, costo)
        )

    # Si alguna otra línea de la compra aún tiene saldo, la nota es «por ítem»; el servicio lo ve.
    def base_de(grupo: str, tipo: str | None = None) -> Decimal:
        return sum(
            (
                r.valor_venta
                for r, p in zip(lineas, partes, strict=True)
                if p.grupo == grupo and (tipo is None or p.tipo_impuesto == tipo)
            ),
            CERO,
        )

    def impuesto_de(tipo: str) -> Decimal:
        return sum(
            (r.impuesto for r, p in zip(lineas, partes, strict=True) if p.tipo_impuesto == tipo),
            CERO,
        )

    total = sum((r.total for r in lineas), CERO) + ajuste_redondeo
    if total < 0:
        raise DevolucionInvalida("El total de la devolución no puede ser negativo.")
    return ResultadoDevolucion(
        lineas=tuple(lineas),
        op_gravada=base_de(AfectacionIGV.Grupo.GRAVADO, AfectacionIGV.Impuesto.IGV),
        igv=impuesto_de(AfectacionIGV.Impuesto.IGV),
        op_ivap=base_de(AfectacionIGV.Grupo.GRAVADO, AfectacionIGV.Impuesto.IVAP),
        ivap=impuesto_de(AfectacionIGV.Impuesto.IVAP),
        op_exonerada=base_de(AfectacionIGV.Grupo.EXONERADO),
        op_inafecta=base_de(AfectacionIGV.Grupo.INAFECTO),
        ajuste_redondeo=ajuste_redondeo,
        total=total,
        costo_soles=sum((r.costo_soles for r in lineas), CERO),
        queda_pendiente=queda,
    )


# ---------------------------------------------------------------------------
# Lo que ya se devolvió y lo que falta
# ---------------------------------------------------------------------------
def devuelto_antes(compra: Compra) -> dict[int, Previo]:
    """Por línea de la compra, lo devuelto en devoluciones vigentes (las anuladas no cuentan)."""
    filas = (
        LineaDevolucionCompra.objects.filter(
            linea_compra__compra=compra, devolucion__estado=DevolucionCompra.Estado.EMITIDO
        )
        .values("linea_compra_id")
        .annotate(
            cantidad=Sum("cantidad"),
            cantidad_base=Sum("cantidad_base"),
            valor_venta=Sum("valor_venta"),
            impuesto=Sum("impuesto"),
            costo_soles=Sum("costo_soles"),
        )
    )
    return {
        f["linea_compra_id"]: Previo(
            f["cantidad"], f["cantidad_base"], f["valor_venta"], f["impuesto"], f["costo_soles"]
        )
        for f in filas
    }


def pendiente_de_devolver(compra: Compra) -> list[dict]:
    """Por línea: lo comprado, lo ya devuelto y lo que todavía se puede devolver."""
    previos = devuelto_antes(compra)
    salida = []
    for linea in compra.lineas.select_related("producto").order_by("orden"):
        previo = previos.get(linea.pk, Previo())
        salida.append(
            {
                "linea": linea.pk,
                "orden": linea.orden,
                "producto": linea.producto_id,
                "unidad": linea.unidad,
                "comprado": linea.cantidad,
                "devuelto": previo.cantidad,
                "pendiente": linea.cantidad - previo.cantidad,
                "lleva_serie": linea.producto.lleva_serie,
            }
        )
    return salida


def series_disponibles(compra: Compra, linea: LineaCompra) -> list[str]:
    """Las series de esta línea de la compra que siguen en el almacén y se pueden devolver."""
    return list(
        SerieProducto.objects.filter(
            empresa_id=compra.empresa_id,
            producto_id=linea.producto_id,
            almacen_id=compra.almacen_id,
            entrada__movimiento_id=compra.movimiento_id,
            estado=EstadoSerie.EN_STOCK,
        )
        .order_by("numero")
        .values_list("numero", flat=True)
    )


def deuda_pendiente(compra: Compra) -> Decimal:
    """Lo que todavía se debe de la compra (cero si fue al contado)."""
    if compra.forma_pago != FormaPago.CREDITO:
        return CERO
    return sum((c.monto - c.pagado for c in CuotaCompra.objects.filter(compra=compra)), CERO)


def con_devoluciones_vigentes(compra: Compra) -> bool:
    return DevolucionCompra.objects.filter(
        compra=compra, estado=DevolucionCompra.Estado.EMITIDO
    ).exists()


# ---------------------------------------------------------------------------
# Lo que pide quien registra
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LineaDevuelta:
    linea_compra_id: int
    cantidad: Decimal  # en la unidad de la línea de la compra
    series: tuple[str, ...] = ()


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _validar_nota(
    empresa: Empresa,
    compra: Compra,
    tipo: TipoComprobante,
    serie: str,
    numero: str,
    fecha: date,
) -> tuple[str, str]:
    if (
        tipo.organizacion_id != empresa.organizacion_id
        or tipo.estado != EstadoRegistro.ACTIVO
        or tipo.codigo != TIPO_NOTA_DE_CREDITO
    ):
        raise DevolucionInvalida("El comprobante de una devolución es una nota de crédito (07).")
    try:
        serie, numero = fiscal.validar_serie_numero(tipo, serie, numero)
    except ValueError as error:
        raise DevolucionInvalida(str(error)) from None
    if not numero:
        raise DevolucionInvalida("Indique el número de la nota de crédito del proveedor.")
    if len(serie) > 10 or len(numero) > 20:
        raise DevolucionInvalida("La serie admite hasta 10 caracteres y el número hasta 20.")
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise DevolucionInvalida("La fecha de la nota de crédito no es válida.")
    if fecha > timezone.localdate():
        raise DevolucionInvalida("La fecha de la nota de crédito no puede ser futura.")
    if fecha < compra.fecha_emision:
        raise DevolucionInvalida("La nota de crédito no puede ser anterior a la compra.")
    return serie, numero


def _series_de_la_compra(compra: Compra, linea: LineaCompra, series: tuple[str, ...]) -> None:
    """Las series devueltas deben ser de esta compra y seguir en el almacén."""
    existentes = set(
        SerieProducto.objects.filter(
            empresa_id=compra.empresa_id,
            producto_id=linea.producto_id,
            entrada__movimiento_id=compra.movimiento_id,
            numero__in=series,
        ).values_list("numero", flat=True)
    )
    for numero in series:
        if numero not in existentes:
            raise DevolucionInvalida(
                f"La serie {numero} no pertenece a esta compra de {linea.producto.nombre}."
            )
    en_stock = set(
        SerieProducto.objects.filter(
            empresa_id=compra.empresa_id,
            producto_id=linea.producto_id,
            almacen_id=compra.almacen_id,
            estado=EstadoSerie.EN_STOCK,
            numero__in=series,
        ).values_list("numero", flat=True)
    )
    for numero in series:
        if numero not in en_stock:
            raise DevolucionInvalida(
                f"La serie {numero} de {linea.producto.nombre} ya no está en el almacén."
            )


def _siguiente_numero(empresa: Empresa) -> int:
    from apps.mantenimiento.models import Correlativo

    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"compras:devolucion:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _tasa_igv(lineas: Sequence[LineaCompra]) -> Decimal:
    return max(
        (ln.tasa for ln in lineas if ln.afectacion.impuesto == AfectacionIGV.Impuesto.IGV),
        default=CERO,
    )


def _calcular_pedido(
    compra: Compra, lineas: Sequence[LineaDevuelta], ajuste_redondeo: Decimal
) -> tuple[dict, dict, list, ResultadoDevolucion]:
    """Valida las líneas pedidas contra la compra y calcula los importes de la devolución.

    Devuelve las líneas de la compra, lo pedido por línea, el orden de las líneas elegidas y el
    resultado. No escribe nada.
    """
    de_la_compra = {
        ln.pk: ln for ln in compra.lineas.select_related("producto", "afectacion").order_by("orden")
    }
    pedidas: dict[int, LineaDevuelta] = {}
    for pedida in lineas:
        if pedida.linea_compra_id not in de_la_compra:
            raise DevolucionInvalida("Una de las líneas no pertenece a la compra.")
        if pedida.linea_compra_id in pedidas:
            raise DevolucionInvalida("Una línea de la compra se repite en la devolución.")
        if not isinstance(pedida.cantidad, Decimal) or not pedida.cantidad.is_finite():
            raise DevolucionInvalida("La cantidad a devolver no es válida.")
        if pedida.cantidad != pedida.cantidad.quantize(TRES):
            raise DevolucionInvalida("La cantidad admite hasta 3 decimales.")
        pedidas[pedida.linea_compra_id] = pedida

    previos = devuelto_antes(compra)
    elegidas = sorted(pedidas, key=lambda pk: de_la_compra[pk].orden)
    partes = []
    for pk in elegidas:
        ln = de_la_compra[pk]
        partes.append(
            ParteLinea(
                cantidad=ln.cantidad,
                cantidad_base=ln.cantidad_base,
                factor=ln.factor,
                valor_venta=ln.valor_venta,
                impuesto=ln.impuesto,
                costo_soles=ln.costo_soles,
                grupo=ln.afectacion.grupo,
                tipo_impuesto=ln.afectacion.impuesto,
                previo=previos.get(pk, Previo()),
                pedida=pedidas[pk].cantidad,
            )
        )
    return (
        de_la_compra,
        pedidas,
        elegidas,
        calcular_devolucion(partes, ajuste_redondeo=ajuste_redondeo),
    )


def previsualizar_devolucion(
    compra: Compra, lineas: Sequence[LineaDevuelta], ajuste_redondeo: Decimal = CERO
) -> dict:
    """Lo que valdría una devolución y a dónde iría el dinero, sin registrar nada.

    Es el MISMO cálculo con el que se registra: lo que se ve es lo que se guarda.
    """
    if compra.estado != Compra.Estado.EMITIDO:
        raise DevolucionInvalida("No se puede devolver una compra anulada.")
    if not lineas:
        raise DevolucionInvalida("Indique al menos un producto a devolver.")
    if len(lineas) > MAX_LINEAS:
        raise DevolucionInvalida(f"Una devolución admite hasta {MAX_LINEAS} productos.")
    de_la_compra, _, elegidas, r = _calcular_pedido(compra, lineas, ajuste_redondeo)
    aplicado = min(r.total, deuda_pendiente(compra))
    previos = devuelto_antes(compra)
    queda_otra = any(
        (de_la_compra[pk].cantidad - previos.get(pk, Previo()).cantidad) > 0
        for pk in de_la_compra
        if pk not in elegidas
    )
    return {
        "resultado": r,
        "elegidas": elegidas,
        "aplicado_a_deuda": aplicado,
        "por_recuperar": r.total - aplicado,
        "motivo": (
            DevolucionCompra.Motivo.POR_ITEM
            if r.queda_pendiente or queda_otra
            else DevolucionCompra.Motivo.TOTAL
        ),
    }


# ---------------------------------------------------------------------------
# A dónde va el valor de la nota
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PlanDinero:
    """Cómo se reparte el total de la nota entre deuda, reembolso y saldo a favor."""

    aplicaciones: list  # [(cuota bloqueada, monto que cancela)]
    reembolsos: list  # [PagoEntrada ya validado]
    aplicado: Decimal
    reembolsado: Decimal
    saldo_a_favor: Decimal


def _plan_del_dinero(
    empresa: Empresa,
    compra: Compra,
    total: Decimal,
    reembolsos: Sequence[PagoEntrada],
    fecha_nota: date,
) -> PlanDinero:
    """Valida el dinero y lo reparte, sin escribir nada. Bloquea las cuotas de la compra."""
    cuotas: list[CuotaCompra] = []
    pendiente = CERO
    if compra.forma_pago == FormaPago.CREDITO:
        cuotas = _cuotas_bloqueadas(compra)
        pendiente = sum((c.monto - c.pagado for c in cuotas), CERO)
    aplicado = min(total, pendiente)
    por_recuperar = total - aplicado

    validados = []
    for i, pago in enumerate(reembolsos, start=1):
        etiqueta = "Reembolso" if len(reembolsos) == 1 else f"Reembolso {i}"
        if pago.aporte_socio:
            raise DevolucionInvalida(f"{etiqueta}: un reembolso no puede ser aporte de un socio.")
        validado = _validar_pago(empresa, pago, compra.moneda, fecha_nota, etiqueta)
        if validado.fecha < fecha_nota:
            raise DevolucionInvalida(
                f"{etiqueta}: la fecha no puede ser anterior a la nota de crédito."
            )
        validados.append(validado)
    reembolsado = sum((v.monto for v in validados), CERO)
    if reembolsado > por_recuperar:
        detalle = f" ({aplicado} de la nota rebajan lo que aún se debe)" if aplicado > 0 else ""
        raise DevolucionInvalida(
            f"El reembolso no puede pasar de {por_recuperar}{detalle}: es lo que ya estaba pagado."
        )
    aplicaciones = repartir(cuotas, aplicado, None) if aplicado > 0 else []
    return PlanDinero(aplicaciones, validados, aplicado, reembolsado, por_recuperar - reembolsado)


def _aplicar_dinero(
    empresa: Empresa, compra: Compra, devolucion: DevolucionCompra, plan: PlanDinero
) -> None:
    """Baja las cuotas, registra los reembolsos en caja y deja el saldo a favor."""
    for cuota, parte in plan.aplicaciones:
        cuota.monto -= parte
        cuota.save(update_fields=["monto"])
    AplicacionDevolucion.objects.bulk_create(
        [
            AplicacionDevolucion(empresa=empresa, devolucion=devolucion, cuota=c, monto=m)
            for c, m in plan.aplicaciones
        ]
    )
    for validado in plan.reembolsos:
        reembolso = ReembolsoCompra.objects.create(
            empresa=empresa,
            devolucion=devolucion,
            medio_pago=validado.medio_pago,
            cuenta=validado.cuenta,
            fecha=validado.fecha,
            monto=validado.monto,
            referencia=validado.referencia,
            tipo_cambio=validado.tipo_cambio,
            monto_cuenta=validado.monto_cuenta,
        )
        caja.registrar_reembolso_de_compra(
            empresa=empresa,
            cuenta=validado.cuenta,
            monto=reembolso.monto_en_cuenta,
            fecha=validado.fecha,
            referencia=validado.referencia,
            glosa=(
                f"Reembolso de la devolución N° {devolucion.numero:06d} · "
                f"{devolucion.comprobante} · {compra.proveedor.nombre}"
                f"{_detalle_cambio(reembolso, compra.moneda)}"
            ),
            reembolso_id=reembolso.pk,
            medio_pago=validado.medio_pago,
        )
    if plan.saldo_a_favor > 0:
        CreditoProveedor.objects.create(
            empresa=empresa,
            proveedor=compra.proveedor,
            devolucion=devolucion,
            moneda=compra.moneda,
            monto=plan.saldo_a_favor,
        )


# ---------------------------------------------------------------------------
# Registrar y anular
# ---------------------------------------------------------------------------
@transaction.atomic
def registrar_devolucion(
    *,
    empresa: Empresa,
    compra: Compra,
    tipo_comprobante: TipoComprobante,
    comprobante_serie: str,
    comprobante_numero: str,
    fecha_emision: date,
    razon: str,
    lineas: Sequence[LineaDevuelta],
    ajuste_redondeo: Decimal = CERO,
    reembolsos: Sequence[PagoEntrada] = (),
) -> DevolucionCompra:
    """Registra la devolución y saca del almacén lo devuelto, al costo de la compra de origen.

    ``reembolsos`` es el dinero que el proveedor devuelve (a qué caja o cuenta entra). Va primero
    la deuda pendiente de la compra; de lo ya pagado, lo que no se reembolse queda como saldo a
    favor con el proveedor.

    Errores de dominio con mensaje claro: ``DevolucionInvalida``, ``StockInsuficiente``,
    ``ComprobanteDuplicado``, ``PeriodoCerrado``, ``MovimientoInvalido``…
    """
    periodos.exigir_empresa(empresa)
    # Se bloquea la compra: dos devoluciones a la vez no pueden devolver lo mismo dos veces.
    compra = Compra.objects.select_for_update().get(pk=compra.pk)
    if compra.empresa_id != empresa.pk:
        raise DevolucionInvalida("La compra no pertenece a la empresa.")
    if compra.estado != Compra.Estado.EMITIDO:
        raise DevolucionInvalida("No se puede devolver una compra anulada.")
    razon = _texto(razon, 250)
    if len(razon) < 3:
        raise DevolucionInvalida("Indique por qué se devuelve la mercadería.")
    serie, numero = _validar_nota(
        empresa, compra, tipo_comprobante, comprobante_serie, comprobante_numero, fecha_emision
    )
    if not lineas:
        raise DevolucionInvalida("Indique al menos un producto a devolver.")
    if len(lineas) > MAX_LINEAS:
        raise DevolucionInvalida(f"Una devolución admite hasta {MAX_LINEAS} productos.")
    if not isinstance(ajuste_redondeo, Decimal):
        raise DevolucionInvalida("El ajuste de redondeo no es válido.")

    de_la_compra, pedidas, elegidas, resultado = _calcular_pedido(compra, lineas, ajuste_redondeo)
    plan = _plan_del_dinero(empresa, compra, resultado.total, reembolsos, fecha_emision)

    series_por_linea = {}
    for pk, r in zip(elegidas, resultado.lineas, strict=True):
        ln = de_la_compra[pk]
        series = tuple(" ".join(str(s).split()).upper() for s in pedidas[pk].series)
        if ln.producto.lleva_serie:
            if r.cantidad_base != r.cantidad_base.to_integral_value():
                raise DevolucionInvalida(
                    f"{ln.producto.nombre}: con serie, la cantidad es un número entero."
                )
            if len(series) != int(r.cantidad_base):
                raise DevolucionInvalida(
                    f"{ln.producto.nombre}: indique {int(r.cantidad_base)} serie(s) a devolver."
                )
            _series_de_la_compra(compra, ln, series)
        elif series:
            raise DevolucionInvalida(f"{ln.producto.nombre} no lleva serie o IMEI.")
        series_por_linea[pk] = series

    # ¿Queda algo por devolver en otras líneas de la compra?
    previos = devuelto_antes(compra)
    queda_otra = any(
        (de_la_compra[pk].cantidad - previos.get(pk, Previo()).cantidad) > 0
        for pk in de_la_compra
        if pk not in pedidas
    )
    motivo = (
        DevolucionCompra.Motivo.POR_ITEM
        if resultado.queda_pendiente or queda_otra
        else DevolucionCompra.Motivo.TOTAL
    )

    movimiento = registrar_salida(
        empresa=empresa,
        almacen=compra.almacen,
        tipo=TipoMovimiento.SALIDA,
        origen=OrigenMovimiento.DEVOLUCION_PROVEEDOR,
        fecha=fecha_emision,
        lineas=[
            LineaNueva(
                producto=de_la_compra[pk].producto,
                cantidad=r.cantidad_base,
                importe=r.costo_soles,
                series=series_por_linea[pk],
            )
            for pk, r in zip(elegidas, resultado.lineas, strict=True)
        ],
        proveedor=compra.proveedor,
        comprobante_tipo=tipo_comprobante.codigo,
        comprobante_serie=serie,
        comprobante_numero=numero,
        comprobante_fecha=fecha_emision,
        moneda=compra.moneda,
        tipo_cambio=compra.tipo_cambio,
        igv_porcentaje=_tasa_igv(list(de_la_compra.values())),
        observacion=f"Devolución de la compra N° {compra.numero:06d}: {razon}",
        referencia_tipo="devolucion_compra",
        totales=(
            resultado.op_gravada
            + resultado.op_ivap
            + resultado.op_exonerada
            + resultado.op_inafecta,
            resultado.igv + resultado.ivap,
            resultado.total,
        ),
        salida_con_costo=True,
    )

    devolucion = DevolucionCompra.objects.create(
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        compra=compra,
        proveedor=compra.proveedor,
        almacen=compra.almacen,
        tipo_comprobante=tipo_comprobante,
        comprobante_serie=serie,
        comprobante_numero=numero,
        fecha_emision=fecha_emision,
        motivo=motivo,
        razon=razon,
        moneda=compra.moneda,
        tipo_cambio=compra.tipo_cambio,
        op_gravada=resultado.op_gravada,
        igv=resultado.igv,
        op_ivap=resultado.op_ivap,
        ivap=resultado.ivap,
        op_exonerada=resultado.op_exonerada,
        op_inafecta=resultado.op_inafecta,
        ajuste_redondeo=resultado.ajuste_redondeo,
        total=resultado.total,
        costo_soles=resultado.costo_soles,
        aplicado_a_deuda=plan.aplicado,
        reembolsado=plan.reembolsado,
        saldo_a_favor=plan.saldo_a_favor,
        movimiento=movimiento,
    )
    LineaDevolucionCompra.objects.bulk_create(
        [
            LineaDevolucionCompra(
                empresa=empresa,
                devolucion=devolucion,
                linea_compra=de_la_compra[pk],
                orden=orden,
                producto=de_la_compra[pk].producto,
                cantidad=r.cantidad,
                cantidad_base=r.cantidad_base,
                valor_venta=r.valor_venta,
                impuesto=r.impuesto,
                total=r.total,
                costo_soles=r.costo_soles,
            )
            for orden, (pk, r) in enumerate(zip(elegidas, resultado.lineas, strict=True), start=1)
        ]
    )
    _aplicar_dinero(empresa, compra, devolucion, plan)
    registrar(
        "compras.devolucion_registrada",
        recurso_tipo="devolucion_compra",
        recurso_id=devolucion.pk,
        empresa_id=empresa.pk,
        resumen=(
            f"Devolución N° {devolucion.numero:06d} · compra N° {compra.numero:06d} "
            f"· {tipo_comprobante.codigo} {devolucion.comprobante}"
        ),
        detalle={
            "compra": compra.pk,
            "proveedor": compra.proveedor_id,
            "total": devolucion.total,
            "moneda": devolucion.moneda,
            "motivo": motivo,
            "aplicado_a_deuda": plan.aplicado,
            "reembolsado": plan.reembolsado,
            "saldo_a_favor": plan.saldo_a_favor,
            "lineas": len(elegidas),
            "movimiento": movimiento.pk,
        },
    )
    logger.info(
        "devolucion_compra_registrada",
        extra={"empresa_id": empresa.pk, "devolucion_id": devolucion.pk, "compra_id": compra.pk},
    )
    return devolucion


@transaction.atomic
def anular_devolucion(devolucion: DevolucionCompra, *, motivo: str) -> DevolucionCompra:
    """Anula la devolución: la mercadería vuelve al almacén por el mismo valor con que salió.

    También deshace el dinero: las cuotas recuperan lo que la nota les había rebajado, el
    reembolso sale de la caja donde entró y el saldo a favor se anula (si no se usó). Si algo no se
    puede deshacer (una unidad que ya no se puede reingresar, una caja cerrada o conciliada, un
    saldo a favor ya usado), no se anula nada y la devolución sigue vigente.
    """
    periodos.exigir_empresa(devolucion.empresa)
    # Primero la compra y luego la devolución, igual que al devolver o al anular la compra.
    Compra.objects.select_for_update().get(pk=devolucion.compra_id)
    actual = DevolucionCompra.objects.select_for_update().get(pk=devolucion.pk)
    if actual.estado == DevolucionCompra.Estado.ANULADO:
        devolucion.anular(motivo=motivo)  # lanza DocumentoYaAnulado / MotivoObligatorio
    if not (motivo or "").strip():
        devolucion.anular(motivo=motivo)  # lanza MotivoObligatorio antes de tocar nada
    credito = CreditoProveedor.objects.select_for_update().filter(devolucion=actual).first()
    if credito is not None and credito.usado > 0:
        raise DevolucionNoAnulable(
            "El saldo a favor de esta devolución ya se usó: deshaga primero ese uso."
        )
    razon = f"Devolución anulada: {motivo.strip()}"
    for reembolso in ReembolsoCompra.objects.select_for_update().filter(
        devolucion=actual, anulado=False
    ):
        caja.anular_por_origen(Origen.REEMBOLSO_COMPRA, reembolso.pk, motivo=razon)
        reembolso.anulado = True
        reembolso.anulado_en = timezone.now()
        reembolso.save(update_fields=["anulado", "anulado_en"])
    cuotas = {c.pk: c for c in _cuotas_bloqueadas(Compra.objects.get(pk=actual.compra_id))}
    for aplicacion in AplicacionDevolucion.objects.filter(devolucion=actual):
        cuota = cuotas[aplicacion.cuota_id]
        cuota.monto += aplicacion.monto
        cuota.save(update_fields=["monto"])
    if credito is not None:
        credito.anulado = True
        credito.save(update_fields=["anulado"])
    try:
        anular_movimiento(actual.movimiento, motivo=motivo)
    except AnulacionNoPermitida as error:
        raise DevolucionNoAnulable(error.mensaje) from None
    devolucion.anular(motivo=motivo)
    registrar(
        "compras.devolucion_anulada",
        recurso_tipo="devolucion_compra",
        recurso_id=devolucion.pk,
        empresa_id=devolucion.empresa_id,
        resumen=f"Devolución N° {devolucion.numero:06d} anulada",
        detalle={"motivo": motivo.strip()[:200], "total": devolucion.total},
    )
    return devolucion
