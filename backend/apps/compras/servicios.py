"""Registrar y anular compras.

``preparar_compra`` valida todo y calcula los totales sin escribir nada: lo usa la vista previa
de la pantalla y también el registro, así lo que se ve es exactamente lo que se guarda.
``registrar_compra`` crea, en UNA transacción, la entrada de inventario y la compra con sus
líneas, pagos y cuotas: o queda todo, o no queda nada.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.caja.transferencias import convertir
from apps.inventario import periodos, ubicaciones
from apps.inventario.models import MovimientoInventario, OrigenMovimiento, TipoMovimiento
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    resolver_tipo_cambio,
)
from apps.inventario.movimientos import registrar_movimiento as registrar_entrada
from apps.mantenimiento import fiscal
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    Correlativo,
    CuentaFinanciera,
    EstadoRegistro,
    MedioPago,
    Periodicidad,
    PresentacionProducto,
    Producto,
    Proveedor,
    TipoComprobante,
    TipoProducto,
)
from apps.mantenimiento.pagos import generar_cronograma
from apps.mantenimiento.presentaciones import convertir_a_base
from apps.organizacion.models import ConfiguracionEmpresa, Empresa

from . import calculo, recepcion
from .exceptions import CompraInvalida, CompraNoAnulable
from .models import (
    Compra,
    CuotaCompra,
    DevolucionCompra,
    FormaPago,
    LineaCompra,
    Moneda,
    OrdenCompra,
    PagoCompra,
)

logger = logging.getLogger(__name__)

MAX_LINEAS = 200
MAX_TOTAL = Decimal("9999999999999.99")  # lo que cabe holgado en los campos de 16 dígitos
CENTAVO = Decimal("0.01")
ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Lo que pide quien registra
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LineaEntrada:
    producto: Producto
    cantidad: Decimal  # en la unidad comprada
    precio_unitario: Decimal  # por unidad comprada, tal como figura en el comprobante
    presentacion: PresentacionProducto | None = None
    afectacion: AfectacionIGV | None = None  # None = la que propone el sistema
    series: tuple[str, ...] = ()
    datos_series: tuple[str, ...] = ()
    ubicacion_id: int | None = None
    lote: str = ""
    # Si la compra recibe una orden: la línea de la orden a la que corresponde (None = la del
    # mismo producto y presentación).
    linea_orden: int | None = None


@dataclass(frozen=True, slots=True)
class PagoEntrada:
    medio_pago: MedioPago
    cuenta: CuentaFinanciera
    monto: Decimal
    fecha: date | None = None  # por defecto, la fecha de emisión
    referencia: str = ""
    # Solo si la caja o cuenta es de otra moneda que la compra (soles ↔ dólares).
    tipo_cambio: Decimal | None = None
    monto_cuenta: Decimal | None = None  # lo calcula el sistema: lo que sale de la cuenta
    # El socio pagó de su bolsillo: se registra su aporte a la caja y el pago lo gasta.
    aporte_socio: bool = False


@dataclass(frozen=True, slots=True)
class CuotasEntrada:
    cantidad: int
    primera_fecha: date
    periodicidad: Periodicidad


@dataclass(frozen=True, slots=True)
class FleteEntrada:
    monto: Decimal  # en soles
    al_costo: bool = True
    comprobante_tipo: str = ""
    comprobante_serie: str = ""
    comprobante_numero: str = ""
    pagos: tuple[PagoEntrada, ...] = ()


@dataclass(slots=True)
class CompraPreparada:
    """Compra validada y calculada, lista para guardarse."""

    empresa: Empresa
    proveedor: Proveedor
    almacen: Almacen
    tipo_comprobante: TipoComprobante
    comprobante_serie: str
    comprobante_numero: str
    fecha_emision: date
    nro_guia: str
    observacion: str
    moneda: str
    tipo_cambio: Decimal
    precios_incluyen_igv: bool
    igv_al_costo: bool
    forma_pago: str
    entradas: list[LineaEntrada]
    afectaciones: list[tuple[AfectacionIGV, Decimal]]  # (afectación, tasa) por línea
    cantidades_base: list[Decimal]
    resultado: calculo.ResultadoCompra
    flete: FleteEntrada
    pagos: list[PagoEntrada]
    cuotas: list = field(default_factory=list)
    # Recepción de una orden de compra (vacío si la compra no viene de una orden).
    orden: OrdenCompra | None = None
    vinculos: list = field(default_factory=list)  # línea de la orden de cada línea de la compra
    avisos_precio: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _dos_decimales(valor, campo: str) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise CompraInvalida(f"{campo}: indique un número válido.")
    if valor != valor.quantize(CENTAVO):
        raise CompraInvalida(f"{campo}: admite hasta 2 decimales.")
    if valor > MAX_TOTAL:
        raise CompraInvalida(f"{campo}: el valor es demasiado grande.")
    return valor


def _fecha(valor, campo: str) -> date:
    if not isinstance(valor, date) or isinstance(valor, datetime):
        raise CompraInvalida(f"{campo}: la fecha no es válida.")
    return valor


def _igv_al_costo(empresa: Empresa) -> bool:
    return bool(
        ConfiguracionEmpresa.objects.sin_ambito()
        .filter(empresa=empresa)
        .values_list("igv_compras_al_costo", flat=True)
        .first()
    )


def _validar_cabecera(
    empresa: Empresa,
    proveedor: Proveedor,
    almacen: Almacen,
    tipo_comprobante: TipoComprobante,
    serie: str,
    numero: str,
    fecha_emision: date,
) -> tuple[str, str]:
    if proveedor.organizacion_id != empresa.organizacion_id:
        raise CompraInvalida("El proveedor no pertenece a la organización.")
    if proveedor.estado != EstadoRegistro.ACTIVO:
        raise CompraInvalida("El proveedor está inactivo.")
    if almacen.empresa_id != empresa.pk:
        raise CompraInvalida("El almacén no pertenece a la empresa.")
    if almacen.estado != EstadoRegistro.ACTIVO:
        raise CompraInvalida("El almacén está inactivo.")
    if (
        tipo_comprobante.organizacion_id != empresa.organizacion_id
        or tipo_comprobante.estado != EstadoRegistro.ACTIVO
        or not tipo_comprobante.aplica_compras
    ):
        raise CompraInvalida("El tipo de comprobante no se puede usar en compras.")
    try:
        serie, numero = fiscal.validar_serie_numero(tipo_comprobante, serie, numero)
    except ValueError as error:
        raise CompraInvalida(str(error)) from None
    if not numero:
        raise CompraInvalida("Indique el número del comprobante.")
    if len(serie) > 10 or len(numero) > 20:
        raise CompraInvalida("La serie admite hasta 10 caracteres y el número hasta 20.")
    if fecha_emision > timezone.localdate():
        raise CompraInvalida("La fecha de emisión no puede ser futura.")
    return serie, numero


def _preparar_linea(
    empresa: Empresa, proveedor: Proveedor, fecha: date, entrada: LineaEntrada
) -> tuple[calculo.EntradaLinea, AfectacionIGV, Decimal, Decimal]:
    producto = entrada.producto
    if producto.organizacion_id != empresa.organizacion_id:
        raise CompraInvalida("Un producto no pertenece a la organización.")
    if producto.tipo != TipoProducto.BIEN or not producto.controla_stock:
        raise CompraInvalida(f"{producto.nombre} no lleva control de stock.")
    if not isinstance(entrada.cantidad, Decimal) or not entrada.cantidad.is_finite():
        raise CompraInvalida(f"{producto.nombre}: indique la cantidad.")
    if entrada.cantidad <= 0:
        raise CompraInvalida(f"{producto.nombre}: la cantidad debe ser mayor que cero.")
    precio = entrada.precio_unitario
    if not isinstance(precio, Decimal) or not precio.is_finite() or precio < 0:
        raise CompraInvalida(f"{producto.nombre}: indique un precio válido.")
    if precio != precio.quantize(Decimal("0.000001")) or precio > MAX_TOTAL:
        raise CompraInvalida(f"{producto.nombre}: el precio admite hasta 6 decimales.")

    if entrada.presentacion is not None:
        pres = entrada.presentacion
        if pres.producto_id != producto.pk or pres.estado != EstadoRegistro.ACTIVO:
            raise CompraInvalida(f"{producto.nombre}: la presentación no es válida.")
        try:
            base = convertir_a_base(pres, entrada.cantidad)
        except ValueError as error:
            raise CompraInvalida(f"{producto.nombre}: {error}") from None
    else:
        if entrada.cantidad != entrada.cantidad.quantize(Decimal("0.001")):
            raise CompraInvalida(f"{producto.nombre}: la cantidad admite hasta 3 decimales.")
        base = entrada.cantidad

    afectacion = entrada.afectacion
    if afectacion is None:
        sugerida = fiscal.sugerir_afectacion(
            empresa=empresa,
            operacion=fiscal.COMPRA,
            zona=proveedor.zona,
            producto=producto,
            fecha=fecha,
        )
        afectacion, tasa = sugerida.afectacion, sugerida.porcentaje
    else:
        if (
            afectacion.organizacion_id != empresa.organizacion_id
            or afectacion.estado != EstadoRegistro.ACTIVO
            or not afectacion.aplica_compras
            or afectacion.gratuita
            or afectacion.grupo == AfectacionIGV.Grupo.EXPORTACION
        ):
            raise CompraInvalida(f"{producto.nombre}: la afectación del IGV no se usa en compras.")
        tasa = (
            fiscal.tasa_vigente(empresa.organizacion_id, afectacion.impuesto, fecha)
            if afectacion.paga_impuesto
            else ZERO
        )
    linea = calculo.EntradaLinea(
        cantidad=entrada.cantidad,
        precio_unitario=precio,
        grupo=afectacion.grupo,
        impuesto=afectacion.impuesto,
        tasa=tasa,
    )
    return linea, afectacion, tasa, base


def _validar_pago(
    empresa: Empresa, pago: PagoEntrada, moneda: str, fecha_emision: date, etiqueta: str
) -> PagoEntrada:
    monto = _dos_decimales(pago.monto, f"{etiqueta}: monto")
    if monto <= 0:
        raise CompraInvalida(f"{etiqueta}: el monto debe ser mayor que cero.")
    medio, cuenta = pago.medio_pago, pago.cuenta
    if medio.organizacion_id != empresa.organizacion_id or medio.estado != EstadoRegistro.ACTIVO:
        raise CompraInvalida(f"{etiqueta}: el método de pago no es válido.")
    if cuenta.empresa_id != empresa.pk or cuenta.estado != EstadoRegistro.ACTIVO:
        raise CompraInvalida(f"{etiqueta}: la caja o cuenta no es válida.")
    cambio = monto_cuenta = None
    if cuenta.moneda != moneda:
        cambio = pago.tipo_cambio
        if not isinstance(cambio, Decimal) or not cambio.is_finite() or cambio <= 0:
            raise CompraInvalida(
                f"{etiqueta}: la cuenta es de otra moneda que la compra, indique el tipo de cambio."
            )
        if cambio != cambio.quantize(Decimal("0.0001")) or cambio > Decimal("9999.9999"):
            raise CompraInvalida(f"{etiqueta}: el tipo de cambio admite hasta 4 decimales.")
        monto_cuenta = convertir(monto, moneda, cuenta.moneda, cambio)
        if monto_cuenta <= 0:
            raise CompraInvalida(f"{etiqueta}: el monto es muy pequeño para convertirlo.")
    referencia = _texto(pago.referencia, 60)
    if medio.requiere_referencia and not referencia:
        raise CompraInvalida(f"{etiqueta}: indique el número de operación.")
    fecha = _fecha(pago.fecha or fecha_emision, f"{etiqueta}: fecha")
    if fecha > timezone.localdate():
        raise CompraInvalida(f"{etiqueta}: la fecha del pago no puede ser futura.")
    return PagoEntrada(
        medio, cuenta, monto, fecha, referencia, cambio, monto_cuenta, bool(pago.aporte_socio)
    )


def preparar_compra(
    *,
    empresa: Empresa,
    proveedor: Proveedor,
    almacen: Almacen,
    tipo_comprobante: TipoComprobante,
    comprobante_serie: str,
    comprobante_numero: str,
    fecha_emision: date,
    lineas: list[LineaEntrada],
    forma_pago: str,
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    precios_incluyen_igv: bool = False,
    ajuste_redondeo: Decimal = ZERO,
    nro_guia: str = "",
    observacion: str = "",
    pagos: list[PagoEntrada] | None = None,
    cuotas: CuotasEntrada | None = None,
    flete: FleteEntrada | None = None,
    completa: bool = True,
    orden: OrdenCompra | None = None,
) -> CompraPreparada:
    """Valida la compra y calcula todo. No escribe en la base de datos.

    Con ``completa=False`` (vista previa) no se exige que los pagos, las cuotas o los pagos del
    flete estén ya indicados: sirve para ver los totales mientras se llena la pantalla.
    """
    periodos.exigir_empresa(empresa)
    if moneda not in Moneda.values:
        raise CompraInvalida("La moneda no es válida.")
    if forma_pago not in FormaPago.values:
        raise CompraInvalida("La forma de pago no es válida.")
    _fecha(fecha_emision, "Fecha de emisión")
    serie, numero = _validar_cabecera(
        empresa, proveedor, almacen, tipo_comprobante, comprobante_serie, comprobante_numero,
        fecha_emision,
    )  # fmt: skip
    if not lineas:
        raise CompraInvalida("Agregue al menos un producto.")
    if len(lineas) > MAX_LINEAS:
        raise CompraInvalida(f"Una compra admite hasta {MAX_LINEAS} productos.")
    cambio = resolver_tipo_cambio(
        empresa, moneda, tipo_cambio, TipoMovimiento.ENTRADA, fecha_emision
    )

    flete = flete or FleteEntrada(monto=ZERO)
    monto_flete = _dos_decimales(flete.monto, "Flete")
    if monto_flete < 0:
        raise CompraInvalida("El flete no puede ser negativo.")
    flete_tipo = flete_serie = flete_numero = ""
    if monto_flete > 0:
        flete_tipo = _texto(flete.comprobante_tipo, 2)
        flete_serie = _texto(flete.comprobante_serie, 10).upper()
        flete_numero = _texto(flete.comprobante_numero, 20).upper()

    preparadas = [_preparar_linea(empresa, proveedor, fecha_emision, ln) for ln in lineas]
    vinculos: list = []
    avisos_precio: list = []
    if orden is not None:
        vinculos = recepcion.vincular_lineas(
            orden,
            empresa=empresa,
            proveedor=proveedor,
            moneda=moneda,
            fecha_emision=fecha_emision,
            entradas=lineas,
        )
        avisos_precio = recepcion.avisos_de_precio(
            orden, vinculos, lineas, [p[2] for p in preparadas], precios_incluyen_igv
        )
    elif any(ln.linea_orden is not None for ln in lineas):
        raise CompraInvalida("Se indicó una línea de orden de compra pero no la orden.")
    igv_costo = _igv_al_costo(empresa)
    resultado = calculo.calcular_compra(
        [p[0] for p in preparadas],
        precios_incluyen_igv=precios_incluyen_igv,
        igv_al_costo=igv_costo,
        tipo_cambio=cambio,
        flete=monto_flete,
        flete_al_costo=flete.al_costo,
        ajuste_redondeo=_dos_decimales(ajuste_redondeo, "Ajuste de redondeo"),
    )
    if resultado.total > MAX_TOTAL:
        raise CompraInvalida("El total de la compra es demasiado grande.")

    # Series: una por unidad y solo de productos que las llevan (lo exige también el inventario).
    for ln, (_, _, _, base) in zip(lineas, preparadas, strict=True):
        if ln.series and not ln.producto.lleva_serie:
            raise CompraInvalida(f"{ln.producto.nombre} no lleva serie o IMEI.")
        if completa and ln.producto.lleva_serie and len(ln.series) != int(base):
            raise CompraInvalida(
                f"{ln.producto.nombre}: indique {int(base)} serie(s) y recibió {len(ln.series)}."
            )

    pagos_compra: list[PagoEntrada] = []
    cronograma: list = []
    if forma_pago == FormaPago.CONTADO:
        if cuotas is not None:
            raise CompraInvalida("Una compra al contado no lleva cuotas.")
        pagos_compra = [
            _validar_pago(empresa, p, moneda, fecha_emision, f"Pago {i}")
            for i, p in enumerate(pagos or [], start=1)
        ]
        if completa and sum((p.monto for p in pagos_compra), ZERO) != resultado.total:
            raise CompraInvalida("Los pagos deben sumar exactamente el total de la compra.")
    else:
        if pagos:
            raise CompraInvalida("Una compra a crédito no lleva pagos: se paga por sus cuotas.")
        if cuotas is None:
            if completa:
                raise CompraInvalida("Indique las cuotas de la compra a crédito.")
        else:
            if resultado.total <= 0:
                raise CompraInvalida("Una compra con total cero no puede ser a crédito.")
            if cuotas.primera_fecha < fecha_emision:
                raise CompraInvalida("La primera cuota no puede vencer antes de la emisión.")
            if (
                cuotas.periodicidad.organizacion_id != empresa.organizacion_id
                or cuotas.periodicidad.estado != EstadoRegistro.ACTIVO
            ):
                raise CompraInvalida("La periodicidad no es válida.")
            try:
                cronograma = generar_cronograma(
                    resultado.total, cuotas.cantidad, cuotas.primera_fecha, cuotas.periodicidad
                )
            except ValueError as error:
                raise CompraInvalida(str(error)) from None

    pagos_flete: list[PagoEntrada] = []
    if monto_flete > 0:
        pagos_flete = [
            _validar_pago(empresa, p, Moneda.PEN, fecha_emision, f"Pago del flete {i}")
            for i, p in enumerate(flete.pagos, start=1)
        ]
        if completa and sum((p.monto for p in pagos_flete), ZERO) != monto_flete:
            raise CompraInvalida("Los pagos del flete deben sumar exactamente el flete.")
    elif flete.pagos:
        raise CompraInvalida("Hay pagos de flete pero el flete es cero.")

    return CompraPreparada(
        empresa=empresa,
        proveedor=proveedor,
        almacen=almacen,
        tipo_comprobante=tipo_comprobante,
        comprobante_serie=serie,
        comprobante_numero=numero,
        fecha_emision=fecha_emision,
        nro_guia=_texto(nro_guia, 30),
        observacion=_texto(observacion, 250),
        moneda=moneda,
        tipo_cambio=cambio,
        precios_incluyen_igv=precios_incluyen_igv,
        igv_al_costo=igv_costo,
        forma_pago=forma_pago,
        entradas=list(lineas),
        afectaciones=[(p[1], p[2]) for p in preparadas],
        cantidades_base=[p[3] for p in preparadas],
        resultado=resultado,
        flete=FleteEntrada(
            monto_flete, flete.al_costo, flete_tipo, flete_serie, flete_numero, tuple(pagos_flete)
        ),
        pagos=pagos_compra,
        cuotas=cronograma,
        orden=orden,
        vinculos=vinculos,
        avisos_precio=avisos_precio,
    )


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"compras:compra:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _detalle_cambio(pago: PagoCompra, moneda_compra: str) -> str:
    """« · US$ 740.00 a 3.6000» cuando el pago salió de una cuenta de otra moneda."""
    if pago.tipo_cambio is None:
        return ""
    simbolo = "US$" if moneda_compra == "USD" else "S/"
    return f" · {simbolo} {pago.monto:.2f} a {pago.tipo_cambio:.4f}"


def _tasa_igv_de(p: CompraPreparada) -> Decimal:
    tasas = [t for (a, t) in p.afectaciones if a.impuesto == AfectacionIGV.Impuesto.IGV]
    return max(tasas, default=ZERO)


@transaction.atomic
def registrar_compra(**datos) -> Compra:
    """Registra la compra y su entrada al inventario, todo o nada.

    Recibe los mismos argumentos que ``preparar_compra``. Errores de dominio con mensaje claro:
    ``CompraInvalida``, ``ComprobanteDuplicado``, ``PeriodoCerrado``, ``MovimientoInvalido``…
    """
    if datos.get("orden") is not None:
        # Primero la orden: dos recepciones a la vez no pueden recibir lo mismo dos veces.
        datos["orden"] = OrdenCompra.objects.select_for_update().get(pk=datos["orden"].pk)
    p = preparar_compra(**datos)
    r = p.resultado

    # La entrada de inventario va primero: ella bloquea al empresa y valida periodo y duplicados.
    movimiento = registrar_entrada(
        empresa=p.empresa,
        almacen=p.almacen,
        tipo=TipoMovimiento.ENTRADA,
        origen=OrigenMovimiento.COMPRA,
        fecha=p.fecha_emision,
        lineas=[
            LineaNueva(
                producto=entrada.producto,
                cantidad=base,
                importe=resultado.costo_soles,
                series=entrada.series,
                datos_series=entrada.datos_series,
            )
            for entrada, base, resultado in zip(
                p.entradas, p.cantidades_base, r.lineas, strict=True
            )
        ],
        proveedor=p.proveedor,
        comprobante_tipo=p.tipo_comprobante.codigo,
        comprobante_serie=p.comprobante_serie,
        comprobante_numero=p.comprobante_numero,
        comprobante_fecha=p.fecha_emision,
        moneda=p.moneda,
        tipo_cambio=p.tipo_cambio,
        precios_incluyen_igv=p.precios_incluyen_igv,
        igv_porcentaje=_tasa_igv_de(p),
        observacion=p.observacion,
        referencia_tipo="compra",
        totales=(
            r.op_gravada + r.op_ivap + r.op_exonerada + r.op_inafecta,
            r.igv + r.ivap,
            r.total,
        ),
    )

    compra = Compra.objects.create(
        empresa=p.empresa,
        numero=_siguiente_numero(p.empresa),
        proveedor=p.proveedor,
        almacen=p.almacen,
        tipo_comprobante=p.tipo_comprobante,
        comprobante_serie=p.comprobante_serie,
        comprobante_numero=p.comprobante_numero,
        fecha_emision=p.fecha_emision,
        nro_guia=p.nro_guia,
        observacion=p.observacion,
        moneda=p.moneda,
        tipo_cambio=p.tipo_cambio,
        precios_incluyen_igv=p.precios_incluyen_igv,
        igv_al_costo=p.igv_al_costo,
        op_gravada=r.op_gravada,
        igv=r.igv,
        op_ivap=r.op_ivap,
        ivap=r.ivap,
        op_exonerada=r.op_exonerada,
        op_inafecta=r.op_inafecta,
        ajuste_redondeo=r.ajuste_redondeo,
        total=r.total,
        forma_pago=p.forma_pago,
        flete=p.flete.monto,
        flete_al_costo=p.flete.al_costo,
        flete_comprobante_tipo=p.flete.comprobante_tipo,
        flete_comprobante_serie=p.flete.comprobante_serie,
        flete_comprobante_numero=p.flete.comprobante_numero,
        movimiento=movimiento,
        orden=p.orden,
    )
    LineaCompra.objects.bulk_create(
        [
            LineaCompra(
                empresa=p.empresa,
                compra=compra,
                orden=orden,
                producto=entrada.producto,
                presentacion=entrada.presentacion,
                unidad=(
                    entrada.presentacion.unidad.nombre
                    if entrada.presentacion
                    else entrada.producto.unidad.nombre
                ),
                factor=entrada.presentacion.factor if entrada.presentacion else Decimal("1"),
                cantidad=entrada.cantidad,
                cantidad_base=base,
                afectacion=afectacion,
                afectacion_codigo=afectacion.codigo,
                tasa=tasa,
                precio_unitario=entrada.precio_unitario,
                lote=_texto(entrada.lote, 40),
                valor_venta=linea.valor_venta,
                impuesto=linea.impuesto,
                total=linea.total,
                costo_soles=linea.costo_soles,
                flete_asignado=linea.flete_asignado,
                linea_orden=vinculo,
                precio_pactado=vinculo.precio_unitario if vinculo else None,
            )
            for orden, (entrada, base, (afectacion, tasa), linea, vinculo) in enumerate(
                zip(
                    p.entradas,
                    p.cantidades_base,
                    p.afectaciones,
                    r.lineas,
                    p.vinculos or [None] * len(p.entradas),
                    strict=True,
                ),
                start=1,
            )
        ]
    )
    if p.orden is not None:
        recepcion.aplicar_recepcion(p.orden, p.vinculos, p.entradas)
    pagos_creados = PagoCompra.objects.bulk_create(
        [
            PagoCompra(
                empresa=p.empresa,
                compra=compra,
                tipo=tipo,
                medio_pago=pago.medio_pago,
                cuenta=pago.cuenta,
                fecha=pago.fecha,
                monto=pago.monto,
                referencia=pago.referencia,
                tipo_cambio=pago.tipo_cambio,
                monto_cuenta=pago.monto_cuenta,
            )
            for tipo, pagos in (
                (PagoCompra.Tipo.COMPRA, p.pagos),
                (PagoCompra.Tipo.FLETE, p.flete.pagos),
            )
            for pago in pagos
        ]
    )
    entradas_de_pago = [*p.pagos, *p.flete.pagos]  # en el mismo orden en que se crearon
    for pago, entrada in zip(pagos_creados, entradas_de_pago, strict=True):
        # el dinero sale de su caja o cuenta: queda en el libro
        concepto_pago = "Flete de la" if pago.tipo == PagoCompra.Tipo.FLETE else "Pago de la"
        caja.registrar_pago_de_compra(
            empresa=p.empresa,
            cuenta=pago.cuenta,
            monto=pago.monto_en_cuenta,
            fecha=pago.fecha,
            referencia=pago.referencia,
            glosa=(
                f"{concepto_pago} compra N° {compra.numero:06d} · {compra.comprobante} "
                f"· {p.proveedor.nombre}{_detalle_cambio(pago, compra.moneda)}"
            ),
            pago_id=pago.pk,
            medio_pago=pago.medio_pago,
            aporte_socio=entrada.aporte_socio,
        )
    CuotaCompra.objects.bulk_create(
        [
            CuotaCompra(
                empresa=p.empresa,
                compra=compra,
                numero=c.numero,
                fecha_vencimiento=c.fecha,
                monto=c.monto,
            )
            for c in p.cuotas
        ]
    )
    for entrada in p.entradas:
        if entrada.ubicacion_id:
            ubicaciones.asignar_ubicacion(
                empresa=p.empresa,
                almacen_id=p.almacen.pk,
                producto_id=entrada.producto.pk,
                ubicacion_id=entrada.ubicacion_id,
            )
    registrar(
        "compras.compra_registrada",
        recurso_tipo="compra",
        recurso_id=compra.pk,
        empresa_id=p.empresa.pk,
        resumen=f"Compra N° {compra.numero:06d} · {p.tipo_comprobante.codigo} {compra.comprobante}",
        detalle={
            "proveedor": p.proveedor.pk,
            "total": compra.total,
            "moneda": compra.moneda,
            "forma_pago": compra.forma_pago,
            "lineas": len(p.entradas),
            "movimiento": movimiento.pk,
            **(
                {"orden": p.orden.pk, "diferencias_de_precio": len(p.avisos_precio)}
                if p.orden is not None
                else {}
            ),
        },
    )
    logger.info(
        "compra_registrada",
        extra={"empresa_id": p.empresa.pk, "compra_id": compra.pk, "forma_pago": compra.forma_pago},
    )
    return compra


@transaction.atomic
def anular_compra(compra: Compra, *, motivo: str) -> Compra:
    """Anula la compra: devuelve su entrada al inventario y marca sus pagos como anulados.

    No se puede si la mercadería ya salió (lo valida el inventario) ni si ya se pagó alguna cuota
    (primero hay que revertir ese pago). La devolución del dinero de un pago al contado la
    registrará el módulo de Caja y bancos.
    """
    periodos.exigir_empresa(compra.empresa)
    actual = Compra.objects.select_for_update().get(pk=compra.pk)
    if actual.estado == Compra.Estado.ANULADO:
        compra.anular(motivo=motivo)  # lanza DocumentoYaAnulado / MotivoObligatorio
    if CuotaCompra.objects.filter(compra=actual, pagado__gt=0).exists():
        raise CompraNoAnulable("La compra tiene cuotas pagadas: revierta primero esos pagos.")
    if DevolucionCompra.objects.filter(
        compra=actual, estado=DevolucionCompra.Estado.EMITIDO
    ).exists():
        raise CompraNoAnulable("La compra tiene devoluciones: anúlelas primero.")
    anular_movimiento(MovimientoInventario.objects.get(pk=actual.movimiento_id), motivo=motivo)
    if actual.orden_id is not None:
        recepcion.revertir_recepcion(actual)
    for pago_id in PagoCompra.objects.filter(compra=actual, anulado=False).values_list(
        "pk", flat=True
    ):
        caja.anular_por_origen(
            Origen.PAGO_COMPRA, pago_id, motivo=f"Compra anulada: {motivo.strip()}"
        )
    PagoCompra.objects.filter(compra=actual, anulado=False).update(
        anulado=True, anulado_en=timezone.now(), motivo_anulacion="Compra anulada"
    )
    compra.anular(motivo=motivo)
    registrar(
        "compras.compra_anulada",
        recurso_tipo="compra",
        recurso_id=compra.pk,
        empresa_id=compra.empresa_id,
        resumen=f"Compra N° {compra.numero:06d} anulada",
        detalle={"motivo": motivo.strip()[:200], "total": compra.total},
    )
    return compra
