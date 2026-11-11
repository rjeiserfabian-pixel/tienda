"""Registrar y anular ventas de una o de dos empresas.

Una venta es un carrito cobrado. Cada línea la surte una empresa (la que tiene el stock) y cada
empresa emite SU comprobante, con su serie, su numeración y su IGV. Todo ocurre en una sola
transacción: si algo falla (no hay stock, la caja no está abierta, el precio está bajo el mínimo),
no queda nada a medias.

Para cada empresa que surte:

1. Se numera su comprobante con su serie (bloqueada, sin saltos ni repetidos).
2. Salen las existencias de su almacén al costo promedio; ese costo se guarda en cada línea.
3. El cobro que le toca entra a su caja o cuenta según el método de pago.

Los permisos de la persona (descontar, precio técnico, vender bajo el mínimo, vender stock de otra
empresa) los decide quien llama, que ya los verificó; aquí solo se aplican.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.compras.calculo import EntradaLinea
from apps.inventario import periodos
from apps.inventario.costeo import a_dos, a_seis
from apps.inventario.models import (
    EstadoSerie,
    OrigenMovimiento,
    SaldoStock,
    SerieProducto,
    TipoMovimiento,
)
from apps.inventario.movimientos import (
    LineaNueva,
    anular_movimiento,
    resolver_tipo_cambio,
)
from apps.inventario.movimientos import registrar_movimiento as registrar_salida
from apps.mantenimiento import fiscal
from apps.mantenimiento.exceptions import AfectacionNoDisponible
from apps.mantenimiento.models import (
    AfectacionIGV,
    Almacen,
    Cliente,
    Correlativo,
    CuentaFinanciera,
    EstadoRegistro,
    ListaPrecio,
    MedioPago,
    Periodicidad,
    Producto,
    SerieComprobante,
    TipoComprobante,
    TipoProducto,
    UsoLista,
)
from apps.mantenimiento.pagos import Cuota, generar_cronograma
from apps.mantenimiento.series import siguiente_numero
from apps.organizacion.models import Empresa, Sucursal

from . import calculo, cobros, credito, precios
from .exceptions import (
    CuentaDeCobroNoConfigurada,
    PrecioBajoElMinimo,
    VentaInvalida,
    VentaNoAnulable,
)
from .models import (
    CERO,
    CobroVenta,
    ComprobanteVenta,
    CuentaDeCobro,
    CuotaVenta,
    FormaPago,
    LineaVenta,
    Moneda,
    Proforma,
    Venta,
)

# Los comprobantes que ya se pueden emitir. Las notas de crédito y las guías llegan después.
TIPOS_DE_VENTA = ("01", "03", "NV")
FACTURA, BOLETA = "01", "03"
# Una boleta de más de este monto (en soles) debe llevar al cliente identificado.
# A confirmar con el contador.
MAX_CUOTAS = 60
TOPE_BOLETA_SIN_IDENTIFICAR = Decimal("700.00")
AUTORIZADO = "AUTORIZADO"  # bajo el mínimo, con el permiso de un administrador
MAX_LINEAS = 100
MAX_COBROS = 10
CLIENTE_VARIOS = "CLIENTES VARIOS"
TRES = Decimal("0.001")
SEIS = Decimal("0.000001")
MAXIMO = Decimal("9999999999.99")


@dataclass(frozen=True, slots=True)
class LineaEntrada:
    """Un producto del carrito y la empresa que lo surte."""

    producto: Producto
    cantidad: Decimal
    empresa: Empresa
    # Obligatorio para lo que lleva stock; los servicios no tienen almacén.
    almacen: Almacen | None = None
    # Sin IGV y en la moneda de la venta. Vacío = el precio de la lista elegida.
    precio_unitario: Decimal | None = None
    series: tuple[str, ...] = ()
    # Código de la afectación del IGV elegida a mano; vacío = la que corresponde según el producto.
    afectacion: str = ""
    # Un repuesto que el servicio técnico ya sacó del almacén: se cobra, pero no vuelve a descontar
    # stock (ni lleva almacén) y su costo es el que tuvo al salir (``costo_total``, en soles).
    stock_ya_descontado: bool = False
    costo_total: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CobroEntrada:
    """Lo que el cliente pagó con un método; ``recibido`` (solo efectivo) permite dar vuelto."""

    medio_pago: MedioPago
    monto: Decimal
    referencia: str = ""
    recibido: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CobroPrevio:
    """Dinero que el cliente ya dejó antes (un adelanto): se aplica al comprobante de su empresa.

    No entra a caja otra vez: ya entró cuando se recibió. ``empresa`` es la que lo recibió.
    """

    empresa: Empresa
    monto: Decimal
    medio_pago: MedioPago
    cuenta: CuentaFinanciera
    referencia: str = ""


@dataclass(frozen=True, slots=True)
class CuotasEntrada:
    """En cuántas cuotas se paga lo que queda a crédito, desde cuándo y cada cuánto."""

    cantidad: int
    primera_fecha: date
    periodicidad: Periodicidad


@dataclass(slots=True)
class _Linea:
    entrada: LineaEntrada
    descripcion: str
    afectacion: AfectacionIGV
    tasa: Decimal
    precio_lista: Decimal
    precio: Decimal
    minimo: Decimal
    bajo_minimo: bool
    costo_estimado: Decimal
    estado_precio: str = "OK"
    minimo_oculto: bool = False
    importes: calculo.LineaCalculada | None = None
    costo_unitario: Decimal = CERO
    costo_total: Decimal = CERO
    movimiento: object = None
    linea_venta: object = None  # la LineaVenta que se creó con esta línea


@dataclass(slots=True)
class _Comprobante:
    empresa: Empresa
    serie: SerieComprobante
    lineas: list[_Linea] = field(default_factory=list)
    totales: calculo.TotalesComprobante | None = None


# ---------------------------------------------------------------------------
# Validaciones
# ---------------------------------------------------------------------------
def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _decimal(valor, campo: str, *, decimales: Decimal, minimo: Decimal = CERO) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise VentaInvalida(f"{campo}: indique un número válido.")
    if valor != valor.quantize(decimales):
        raise VentaInvalida(f"{campo}: admite menos decimales.")
    if valor < minimo or valor > MAXIMO:
        raise VentaInvalida(f"{campo}: el valor no es válido.")
    return valor


def _fecha(valor) -> date:
    if not isinstance(valor, date) or isinstance(valor, datetime):
        raise VentaInvalida("La fecha de la venta no es válida.")
    if valor > timezone.localdate():
        raise VentaInvalida("La fecha de la venta no puede ser futura.")
    return valor


def _tipo_de_venta(empresa: Empresa, codigo: str) -> TipoComprobante:
    tipo = (
        TipoComprobante.objects.sin_ambito()
        .filter(organizacion_id=empresa.organizacion_id, codigo=codigo)
        .first()
    )
    if (
        codigo not in TIPOS_DE_VENTA
        or tipo is None
        or tipo.estado != EstadoRegistro.ACTIVO
        or not tipo.aplica_ventas
    ):
        raise VentaInvalida("Ese tipo de comprobante no se puede emitir en una venta.")
    return tipo


def _cliente_para(
    cliente: Cliente | None, tipo: TipoComprobante, empresa: Empresa, avisos: list[str]
) -> None:
    """Valida al cliente; con ``avisos`` (vista previa) lo que falta se avisa en vez de fallar."""
    if cliente is not None:
        if cliente.organizacion_id != empresa.organizacion_id:
            raise VentaInvalida("El cliente no pertenece a la organización.")
        if cliente.estado != EstadoRegistro.ACTIVO:
            raise VentaInvalida("El cliente está inactivo.")
    if tipo.codigo == FACTURA and (
        cliente is None or cliente.tipo_documento != "RUC" or len(cliente.numero_documento) != 11
    ):
        _faltante("Para una factura indique un cliente con RUC.", avisos)


def _faltante(mensaje: str, avisos: list[str] | None) -> None:
    """En la venta definitiva falla; en la vista previa solo se avisa."""
    if avisos is None:
        raise VentaInvalida(mensaje)
    avisos.append(mensaje)


def _lista_de_venta(
    listas: precios.ListasDeVenta,
    lista: ListaPrecio | None,
    *,
    puede_descontar: bool,
    puede_precio_tecnico: bool,
) -> ListaPrecio:
    if lista is None:
        if listas.principal is None:
            raise VentaInvalida("No hay una lista de precios principal. Cárguela en Mantenimiento.")
        return listas.principal
    elegida = listas.por_id.get(lista.pk)
    if elegida is None:
        raise VentaInvalida("La lista de precios no es válida.")
    if elegida.uso == UsoLista.CREDITO:
        raise VentaInvalida("La lista de crédito solo se usa en las ventas a crédito.")
    if elegida.uso == UsoLista.DESCUENTO and not puede_descontar:
        raise VentaInvalida("No tiene permiso para vender con la lista de descuento.")
    if elegida.uso == UsoLista.TECNICO and not puede_precio_tecnico:
        raise VentaInvalida("No tiene permiso para vender con el precio técnico.")
    return elegida


def _lista_de_credito(listas: precios.ListasDeVenta) -> ListaPrecio:
    """La venta a crédito usa el precio de crédito."""
    candidatas = sorted(listas.de_uso(UsoLista.CREDITO), key=lambda lista: (lista.orden, lista.pk))
    if not candidatas:
        raise VentaInvalida(
            "No hay una lista de precios de crédito. Márcala en Mantenimiento → Listas de precios."
        )
    return candidatas[0]


def _nombre_de(producto: Producto) -> str:
    return _texto(producto.nombre, 250)


def _preparar_linea(
    entrada: LineaEntrada,
    *,
    empresa_mostrador: Empresa,
    lista: ListaPrecio,
    listas: precios.ListasDeVenta,
    precios_producto: dict[int, Decimal],
    cliente: Cliente | None,
    moneda: str,
    cambio: Decimal,
    fecha: date,
    puede_bajo_minimo: bool,
    puede_otra_empresa: bool,
    estricto: bool = True,
    a_credito: bool = False,
    exigir_almacen: bool = True,
    revisar_series: bool = True,
) -> _Linea:
    producto, surte = entrada.producto, entrada.empresa
    nombre = _nombre_de(producto)
    periodos.exigir_empresa(surte)
    if surte.organizacion_id != empresa_mostrador.organizacion_id:
        raise VentaInvalida("La empresa que surte no es de la organización.")
    if surte.pk != empresa_mostrador.pk and not puede_otra_empresa:
        raise VentaInvalida(f"No tiene permiso para vender stock de {surte.razon_social}.")
    if producto.organizacion_id != empresa_mostrador.organizacion_id:
        raise VentaInvalida("Un producto no pertenece a la organización.")
    if producto.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida(f"{nombre} está inactivo.")
    cantidad = _decimal(entrada.cantidad, f"{nombre}: cantidad", decimales=TRES)
    if cantidad <= 0:
        raise VentaInvalida(f"{nombre}: la cantidad debe ser mayor que cero.")

    lleva_stock = producto.tipo == TipoProducto.BIEN and producto.controla_stock
    if entrada.stock_ya_descontado:
        if not lleva_stock or entrada.almacen is not None or entrada.series:
            raise VentaInvalida(f"{nombre}: el stock ya descontado no lleva almacén ni series.")
        if entrada.costo_total is None or entrada.costo_total < 0:
            raise VentaInvalida(f"{nombre}: falta el costo del repuesto ya descontado.")
    elif lleva_stock and not exigir_almacen:
        pass  # una cotización no reserva ni descuenta stock: no necesita almacén
    elif lleva_stock:
        almacen = entrada.almacen
        if almacen is None or almacen.empresa_id != surte.pk:
            raise VentaInvalida(f"{nombre}: indique el almacén de {surte.razon_social}.")
        if almacen.estado != EstadoRegistro.ACTIVO or not almacen.permite_venta:
            raise VentaInvalida(f"{nombre}: no se vende desde el almacén {almacen.nombre}.")
        if entrada.series and revisar_series:
            _revisar_series(producto, surte, almacen, entrada.series, nombre)
    elif entrada.almacen is not None or entrada.series:
        raise VentaInvalida(f"{nombre} no lleva control de stock: no lleva almacén ni series.")

    precio_lista_soles = precios_producto.get(lista.pk, CERO)
    if precio_lista_soles <= 0:
        raise VentaInvalida(f"{nombre} no tiene precio en la lista «{lista.nombre}».")
    costo = producto.costo
    minimo_soles, oculto = precios.minimo_del_producto(
        listas, precios_producto, precio_lista=precio_lista_soles, costo=costo
    )
    absoluto_soles = precios.precio_absoluto(precio_lista=precio_lista_soles, costo=costo)
    precio_lista = precios.a_moneda(precio_lista_soles, moneda, cambio)
    minimo = precios.a_moneda(minimo_soles, moneda, cambio)
    absoluto = precios.a_moneda(absoluto_soles, moneda, cambio)
    if a_credito:
        # A crédito el precio de crédito es la base: se puede subir, nunca bajar (ni con permiso).
        minimo, absoluto, oculto, puede_bajo_minimo = precio_lista, CERO, False, False

    if entrada.precio_unitario is None:
        precio = precio_lista
    else:
        precio = _decimal(entrada.precio_unitario, f"{nombre}: precio", decimales=SEIS)
        if precio <= 0:
            raise VentaInvalida(f"{nombre}: el precio debe ser mayor que cero.")
    estado = precios.evaluar_precio(precio, minimo=minimo, absoluto=absoluto)
    if estricto:
        if estado == precios.BAJO_COSTO:
            raise PrecioBajoElMinimo(f"{nombre}: el precio no puede estar por debajo del costo.")
        if estado == precios.BAJO_MINIMO and a_credito:
            raise PrecioBajoElMinimo(
                f"{nombre}: a crédito el precio no puede ser menor que el precio de crédito "
                f"({minimo:,.2f})."
            )
        if estado == precios.BAJO_MINIMO and not puede_bajo_minimo:
            # El mínimo se dice solo si sale de las listas: si es el costo, no se revela.
            cuanto = "" if oculto else f" ({minimo:,.2f})"
            raise PrecioBajoElMinimo(
                f"{nombre}: el precio está por debajo del mínimo permitido{cuanto}. "
                "Pida a un administrador que autorice vender por debajo."
            )
    autorizado = estado == precios.BAJO_MINIMO and puede_bajo_minimo

    if entrada.afectacion:
        try:
            sugerencia = fiscal.elegir_afectacion(
                empresa=surte, operacion=fiscal.VENTA, codigo=entrada.afectacion, fecha=fecha
            )
        except AfectacionNoDisponible as e:
            raise VentaInvalida(f"{nombre}: {e.mensaje}") from e
    else:
        sugerencia = fiscal.sugerir_afectacion(
            empresa=surte,
            operacion=fiscal.VENTA,
            zona=cliente.zona if cliente else "",
            producto=producto,
            fecha=fecha,
        )
    if sugerencia.afectacion.gratuita:
        raise VentaInvalida(f"{nombre}: las ventas gratuitas todavía no están disponibles.")
    return _Linea(
        entrada=entrada,
        descripcion=nombre,
        afectacion=sugerencia.afectacion,
        tasa=sugerencia.porcentaje,
        precio_lista=precio_lista,
        precio=precio,
        minimo=minimo,
        bajo_minimo=estado == precios.BAJO_MINIMO,
        costo_estimado=costo,
        estado_precio=AUTORIZADO if autorizado else estado,
        minimo_oculto=oculto,
    )


def _nombre_empresa(empresa: Empresa) -> str:
    return empresa.nombre_comercial or empresa.razon_social


def _revisar_series(
    producto: Producto, surte: Empresa, almacen: Almacen, numeros: tuple[str, ...], nombre: str
) -> None:
    """Cada serie debe estar en el almacén que surte; si no, dice dónde está y qué hacer."""
    en_este = set(
        SerieProducto.objects.sin_ambito()
        .filter(
            producto=producto,
            empresa=surte,
            almacen=almacen,
            estado=EstadoSerie.EN_STOCK,
            numero__in=numeros,
        )
        .values_list("numero", flat=True)
    )
    for numero in numeros:
        if numero in en_este:
            continue
        fila = (
            SerieProducto.objects.sin_ambito()
            .filter(producto=producto, numero=numero)
            .select_related("empresa", "almacen")
            .order_by("-id")
            .first()
        )
        quien = _nombre_empresa(surte)
        if fila is None:
            raise VentaInvalida(
                f"La serie {numero} no existe para {nombre}. Revisa que esté bien escrita."
            )
        if fila.estado != EstadoSerie.EN_STOCK:
            raise VentaInvalida(
                f"La serie {numero} de {nombre} ya salió del almacén (se vendió o se dio de "
                "baja): no se puede vender otra vez."
            )
        if fila.empresa_id != surte.pk:
            raise VentaInvalida(
                f"La serie {numero} de {nombre} está en el stock de {_nombre_empresa(fila.empresa)}"
                f", pero esta línea la surte {quien}. Cambia la empresa de la línea (la letra "
                f"A/B) o usa una serie de {quien}."
            )
        raise VentaInvalida(
            f"La serie {numero} de {nombre} está en el almacén «{fila.almacen.nombre}», no en "
            f"«{almacen.nombre}», que es el que surte esta línea."
        )


def sucursal_equivalente(empresa: Empresa, sucursal: Sucursal | None) -> Sucursal | None:
    """La sucursal de ``empresa`` que es el mismo local físico que ``sucursal``.

    Un local compartido por dos empresas tiene una sucursal en cada una, marcadas con el mismo
    ``local_fisico``. Así la tienda donde se vende sirve para elegir, en cada empresa, su serie y
    la cuenta donde entra cada método de pago.
    """
    if sucursal is None:
        return None
    if sucursal.empresa_id == empresa.pk:
        return sucursal
    if not sucursal.local_fisico:
        return None
    return (
        Sucursal.objects.sin_ambito()
        .filter(
            empresa=empresa,
            local_fisico=sucursal.local_fisico,
            estado=EstadoRegistro.ACTIVO,
        )
        .first()
    )


def serie_sugerida(
    empresa: Empresa, sucursal: Sucursal | None, series: list[SerieComprobante]
) -> SerieComprobante | None:
    """La serie que corresponde sola: la de la tienda de la venta o la general, si es una sola.

    Con varias posibles (o ninguna que encaje) devuelve ``None``: la persona debe elegir.
    """
    sucursal = sucursal_equivalente(empresa, sucursal)
    propias = [s for s in series if sucursal is not None and s.sucursal_id == sucursal.pk]
    generales = [s for s in series if s.sucursal_id is None]
    for grupo in (propias, generales, series):
        if grupo:
            return grupo[0] if len(grupo) == 1 else None
    return None


def _serie_de(
    empresa: Empresa,
    tipo: TipoComprobante,
    sucursal: Sucursal | None,
    elegidas: dict[int, int] | None,
) -> SerieComprobante:
    """La serie con que la empresa emite este tipo: la elegida o la única que corresponde."""
    sucursal = sucursal_equivalente(empresa, sucursal)
    base = SerieComprobante.objects.sin_ambito().filter(
        empresa=empresa, tipo_comprobante=tipo, estado=EstadoRegistro.ACTIVO
    )
    elegida = (elegidas or {}).get(empresa.pk)
    if elegida is not None:
        serie = base.filter(pk=elegida).first()
        if serie is None:
            raise VentaInvalida(f"La serie elegida para {empresa.razon_social} no es válida.")
        return serie
    candidatas = []
    if sucursal is not None:
        candidatas = list(base.filter(sucursal=sucursal))
    if not candidatas:
        candidatas = list(base.filter(sucursal__isnull=True))
    if not candidatas:
        raise VentaInvalida(
            f"{empresa.razon_social} no tiene una serie activa de {tipo.nombre}. "
            "Créela en Mantenimiento."
        )
    if len(candidatas) > 1:
        raise VentaInvalida(
            f"{empresa.razon_social} tiene varias series de {tipo.nombre}: elija una."
        )
    return candidatas[0]


def resolver_cuenta(
    empresa: Empresa, medio: MedioPago, sucursal: Sucursal | None, moneda: str
) -> CuentaFinanciera:
    """La caja o cuenta de la empresa donde entra lo cobrado con este método de pago.

    Primero la configurada para esa tienda, después la general de la empresa y, en efectivo, su
    caja de mostrador. La tienda se traduce a la de cada empresa (ver ``sucursal_equivalente``).
    """
    sucursal = sucursal_equivalente(empresa, sucursal)
    configuradas = CuentaDeCobro.objects.sin_ambito().filter(empresa=empresa, medio_pago=medio)
    cuenta = None
    if sucursal is not None:
        fila = configuradas.filter(sucursal=sucursal).select_related("cuenta").first()
        cuenta = fila.cuenta if fila else None
    if cuenta is None:
        fila = configuradas.filter(sucursal__isnull=True).select_related("cuenta").first()
        cuenta = fila.cuenta if fila else None
    if cuenta is None and medio.tipo == MedioPago.Tipo.EFECTIVO:
        cuenta = _unica_caja(empresa, sucursal, moneda)
    if cuenta is None:
        raise CuentaDeCobroNoConfigurada(
            f"{empresa.razon_social}: indique en qué caja o cuenta entra «{medio.nombre}»."
        )
    if cuenta.estado != EstadoRegistro.ACTIVO or cuenta.empresa_id != empresa.pk:
        raise CuentaDeCobroNoConfigurada(
            f"{empresa.razon_social}: la cuenta de «{medio.nombre}» no está disponible."
        )
    if cuenta.moneda != moneda:
        raise CuentaDeCobroNoConfigurada(
            f"{empresa.razon_social}: «{cuenta.nombre}» no es de la moneda de la venta."
        )
    return cuenta


def _unica_caja(
    empresa: Empresa, sucursal: Sucursal | None, moneda: str
) -> CuentaFinanciera | None:
    cajas = list(
        CuentaFinanciera.objects.sin_ambito()
        .filter(
            empresa=empresa,
            tipo=CuentaFinanciera.Tipo.CAJA,
            moneda=moneda,
            estado=EstadoRegistro.ACTIVO,
        )
        .exclude(rol_caja=CuentaFinanciera.RolCaja.CAJA_CHICA)
    )
    mostradores = [c for c in cajas if c.rol_caja == CuentaFinanciera.RolCaja.MOSTRADOR]
    for grupo in (
        [c for c in mostradores if sucursal and c.sucursal_id == sucursal.pk],
        mostradores,
        cajas,
    ):
        if len(grupo) == 1:
            return grupo[0]
    return None


def _siguiente_numero_interno(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"ventas:venta:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _orden_de_empresas(empresas: list[Empresa]) -> list[Empresa]:
    """La empresa principal primero y las demás por su id: siempre el mismo orden al bloquear."""
    return sorted(empresas, key=lambda e: (not e.es_principal, e.pk))


def sugerir_surtidor(
    producto: Producto, cantidad: Decimal, empresas: list[Empresa]
) -> tuple[Empresa, Almacen] | None:
    """Qué empresa y almacén surten un producto: la principal si tiene stock, si no la que lo tenga.

    Solo cuentan los almacenes activos desde los que se vende y que tienen la cantidad completa.
    ``None`` si ninguna empresa puede surtirlo.
    """
    saldos = (
        SaldoStock.objects.sin_ambito()
        .filter(
            empresa__in=empresas,
            producto=producto,
            cantidad__gte=cantidad,
            almacen__permite_venta=True,
            almacen__estado=EstadoRegistro.ACTIVO,
        )
        .select_related("almacen")
        .order_by("-cantidad", "almacen_id")
    )
    por_empresa: dict[int, Almacen] = {}
    for saldo in saldos:
        por_empresa.setdefault(saldo.empresa_id, saldo.almacen)
    for empresa in _orden_de_empresas(empresas):
        if empresa.pk in por_empresa:
            return empresa, por_empresa[empresa.pk]
    return None


# ---------------------------------------------------------------------------
# Registrar
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class VentaPreparada:
    """Una venta validada y calculada, lista para guardarse (o solo para mostrarse)."""

    empresa: Empresa
    fecha: date
    tipo: TipoComprobante
    cliente: Cliente | None
    moneda: str
    cambio: Decimal
    lista: ListaPrecio
    sucursal: Sucursal | None
    comprobantes: list[_Comprobante]
    total: Decimal
    avisos: list[str] = field(default_factory=list)
    forma_pago: str = FormaPago.CONTADO
    # A crédito: cuánto de cada comprobante queda por cobrar y su cronograma de cuotas.
    creditos: list[Decimal] = field(default_factory=list)
    cronogramas: list[list[Cuota]] = field(default_factory=list)


def _cronogramas(
    comprobantes: list[_Comprobante],
    total: Decimal,
    inicial: Decimal,
    cuotas: CuotasEntrada,
    fecha: date,
) -> tuple[list[Decimal], list[list[Cuota]]]:
    """Lo que queda a crédito en cada comprobante y sus cuotas (con las mismas fechas)."""
    if not isinstance(cuotas.cantidad, int) or not (1 <= cuotas.cantidad <= MAX_CUOTAS):
        raise VentaInvalida(f"Las cuotas deben ser de 1 a {MAX_CUOTAS}.")
    if not isinstance(cuotas.primera_fecha, date) or cuotas.primera_fecha < fecha:
        raise VentaInvalida("La primera cuota no puede vencer antes de la venta.")
    if cuotas.periodicidad.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida("La periodicidad de las cuotas no está disponible.")
    creditos = cobros.repartir_credito([c.totales.total for c in comprobantes], total - inicial)
    try:
        cronogramas = [
            generar_cronograma(monto, cuotas.cantidad, cuotas.primera_fecha, cuotas.periodicidad)
            for monto in creditos
        ]
    except ValueError as error:
        raise VentaInvalida(str(error)) from None
    return creditos, cronogramas


def preparar_venta(
    *,
    empresa: Empresa,
    fecha: date,
    tipo_comprobante: str,
    lineas: list[LineaEntrada],
    cliente: Cliente | None = None,
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    lista: ListaPrecio | None = None,
    sucursal: Sucursal | None = None,
    series: dict[int, int] | None = None,
    puede_descontar: bool = False,
    puede_precio_tecnico: bool = False,
    puede_vender_bajo_minimo: bool = False,
    puede_vender_stock_otra_empresa: bool = False,
    forma_pago: str = FormaPago.CONTADO,
    cuotas: CuotasEntrada | None = None,
    inicial: Decimal = CERO,
    puede_credito: bool = False,
    estricto: bool = True,
    revisar_series: bool = True,
) -> VentaPreparada:
    """Valida el carrito y calcula los comprobantes de cada empresa. No escribe nada.

    Con ``estricto=False`` (la vista previa de la pantalla) un precio bajo el mínimo o un cliente
    que falta no detienen el cálculo: se marcan en la línea o en ``avisos``. Con
    ``revisar_series=False`` no se mira dónde están las series (la vista previa de una venta
    interna: la mercadería de la otra empresa todavía no pasó).

    A crédito (``forma_pago``) se usa la lista de crédito, se exige un cliente identificado y
    ``cuotas``; ``inicial`` es lo que el cliente paga al momento (puede ser cero).
    """
    periodos.exigir_empresa(empresa)
    fecha = _fecha(fecha)
    if moneda not in Moneda.values:
        raise VentaInvalida("La moneda no es válida.")
    if not lineas:
        raise VentaInvalida("Agregue al menos un producto.")
    if len(lineas) > MAX_LINEAS:
        raise VentaInvalida(f"Una venta admite hasta {MAX_LINEAS} productos.")
    if sucursal is not None and sucursal.empresa_id != empresa.pk:
        raise VentaInvalida("La sucursal no pertenece a la empresa.")
    if forma_pago not in FormaPago.values:
        raise VentaInvalida("La forma de pago no es válida.")
    a_credito = forma_pago == FormaPago.CREDITO
    if a_credito and not puede_credito:
        raise VentaInvalida("No tiene permiso para vender a crédito.")

    avisos: list[str] = []
    ante_falta = None if estricto else avisos
    tipo = _tipo_de_venta(empresa, tipo_comprobante)
    _cliente_para(cliente, tipo, empresa, ante_falta)
    cambio = resolver_tipo_cambio(empresa, moneda, tipo_cambio, TipoMovimiento.SALIDA, fecha)
    listas = precios.cargar_listas(empresa.organizacion_id)
    if a_credito:
        lista = _lista_de_credito(listas)
        if cliente is None:
            _faltante("Una venta a crédito necesita un cliente identificado.", ante_falta)
        elif not credito.tiene_credito(cliente):
            _faltante(f"{cliente.nombre} no tiene crédito autorizado.", ante_falta)
    else:
        lista = _lista_de_venta(
            listas,
            lista,
            puede_descontar=puede_descontar,
            puede_precio_tecnico=puede_precio_tecnico,
        )
    por_producto = precios.precios_de([ln.producto.pk for ln in lineas])

    preparadas = [
        _preparar_linea(
            ln,
            empresa_mostrador=empresa,
            lista=lista,
            listas=listas,
            precios_producto=por_producto.get(ln.producto.pk, {}),
            cliente=cliente,
            moneda=moneda,
            cambio=cambio,
            fecha=fecha,
            puede_bajo_minimo=puede_vender_bajo_minimo,
            puede_otra_empresa=puede_vender_stock_otra_empresa,
            estricto=estricto,
            a_credito=a_credito,
            revisar_series=revisar_series,
        )
        for ln in lineas
    ]

    comprobantes = _armar_comprobantes(preparadas, tipo, sucursal, series)
    for c in comprobantes:
        c.totales = calculo.calcular_comprobante(
            [
                EntradaLinea(
                    ln.entrada.cantidad,
                    ln.precio,
                    ln.afectacion.grupo,
                    ln.afectacion.impuesto,
                    ln.tasa,
                )
                for ln in c.lineas
            ]
        )
        for ln, importes in zip(c.lineas, c.totales.lineas, strict=True):
            ln.importes = importes
        _exigir_boleta_identificada(tipo, cliente, c.totales.total * cambio, ante_falta)

    total = sum((c.totales.total for c in comprobantes), CERO)
    creditos: list[Decimal] = []
    cronogramas: list[list[Cuota]] = []
    if a_credito:
        if not (CERO <= inicial < total):
            _faltante("El pago inicial debe ser menor que el total (o cero).", ante_falta)
        elif cuotas is None:
            _faltante("Indique en cuántas cuotas paga el cliente.", ante_falta)
        else:
            creditos, cronogramas = _cronogramas(comprobantes, total, inicial, cuotas, fecha)
    return VentaPreparada(
        empresa,
        fecha,
        tipo,
        cliente,
        moneda,
        cambio,
        lista,
        sucursal,
        comprobantes,
        total,
        avisos,
        forma_pago,
        creditos,
        cronogramas,
    )


@transaction.atomic
def registrar_venta(
    *,
    empresa: Empresa,
    fecha: date,
    tipo_comprobante: str,
    lineas: list[LineaEntrada],
    cobros_entrada: list[CobroEntrada],
    vendedor_nombre: str,
    vendedor_id: uuid.UUID | None = None,
    cliente: Cliente | None = None,
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    lista: ListaPrecio | None = None,
    sucursal: Sucursal | None = None,
    observacion: str = "",
    series: dict[int, int] | None = None,
    puede_descontar: bool = False,
    puede_precio_tecnico: bool = False,
    puede_vender_bajo_minimo: bool = False,
    puede_vender_stock_otra_empresa: bool = False,
    forma_pago: str = FormaPago.CONTADO,
    cuotas: CuotasEntrada | None = None,
    puede_credito: bool = False,
    puede_exceder_limite: bool = False,
    proforma: Proforma | None = None,
    cobros_previos: list[CobroPrevio] | None = None,
    facturar_por: Empresa | None = None,
    documento_interno: str = "INTERNO",
    puede_venta_interna: bool = False,
    almacenes_internos: dict[int, Almacen] | None = None,
) -> Venta:
    """Registra una venta y emite un comprobante por cada empresa que surte.

    Con ``facturar_por`` (un carrito mixto) se emite UN solo comprobante, de esa empresa: lo que
    surte la otra empresa se le pasa antes con una venta interna, al costo (ver
    ``ventas_internas``). Exige ``puede_venta_interna``, que decide quien llama.

    Al contado los cobros deben sumar el total. A crédito los cobros son el pago inicial (puede
    no haber ninguno) y el resto queda en cuotas por cobrar; se exige un cliente con límite.

    ``cobros_previos`` son adelantos que el cliente ya dejó: se aplican al comprobante de la
    empresa que los recibió y no vuelven a entrar a caja (solo al contado).

    ``empresa`` es donde se hace la venta (el mostrador). ``series`` permite elegir la serie de
    cada empresa (``{id de empresa: id de serie}``); sin ella se usa la que corresponde.
    """
    a_credito = forma_pago == FormaPago.CREDITO
    previos = list(cobros_previos or [])
    if not cobros_entrada and not a_credito and not previos:
        raise VentaInvalida("Indique cómo pagó el cliente.")
    if len(cobros_entrada) > MAX_COBROS:
        raise VentaInvalida(f"Una venta admite hasta {MAX_COBROS} cobros.")
    vendedor = _texto(vendedor_nombre, 150)
    if len(vendedor) < 2:
        raise VentaInvalida("Indique quién vende.")
    # Import tardío: el módulo de ventas internas usa cosas de este.
    from . import ventas_internas

    traslados = []
    if facturar_por is not None:
        if not puede_venta_interna:
            raise VentaInvalida("No tiene permiso para hacer una venta interna entre empresas.")
        if facturar_por.organizacion_id != empresa.organizacion_id:
            raise VentaInvalida("La empresa que factura no es de la organización.")
        # Antes de la venta: la mercadería de la otra empresa pasa al stock de la que factura.
        lineas, traslados = ventas_internas.trasladar(
            lineas,
            facturadora=facturar_por,
            fecha=_fecha(fecha),
            documento=documento_interno,
            almacenes_destino=almacenes_internos,
        )
    preparada = preparar_venta(
        empresa=empresa,
        fecha=fecha,
        tipo_comprobante=tipo_comprobante,
        lineas=lineas,
        cliente=cliente,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        lista=lista,
        sucursal=sucursal,
        series=series,
        puede_descontar=puede_descontar,
        puede_precio_tecnico=puede_precio_tecnico,
        puede_vender_bajo_minimo=puede_vender_bajo_minimo,
        puede_vender_stock_otra_empresa=puede_vender_stock_otra_empresa,
        forma_pago=forma_pago,
        cuotas=cuotas,
        inicial=sum((c.monto for c in cobros_entrada if isinstance(c.monto, Decimal)), CERO),
        puede_credito=puede_credito,
    )
    fecha, tipo, cambio, lista = preparada.fecha, preparada.tipo, preparada.cambio, preparada.lista
    comprobantes, total = preparada.comprobantes, preparada.total
    if a_credito:
        if cliente is None:
            raise VentaInvalida("Una venta a crédito necesita un cliente identificado.")
        cobros_validos = _cobros_validos(cobros_entrada)
        inicial = sum((c.monto for c in cobros_validos), CERO)
        if cuotas is None:
            raise VentaInvalida("Indique en cuántas cuotas paga el cliente.")
        if not (CERO <= inicial < total):
            raise VentaInvalida("El pago inicial debe ser menor que el total (o cero).")
        creditos, cronogramas = _cronogramas(comprobantes, total, inicial, cuotas, fecha)
        # Se bloquea al cliente: dos ventas a crédito a la vez no pasan su límite entre las dos.
        cliente = Cliente.objects.sin_ambito().select_for_update().get(pk=cliente.pk)
        credito.exigir_limite(
            cliente, (total - inicial) * cambio, puede_exceder=puede_exceder_limite
        )
        pagado = [c.totales.total - monto for c, monto in zip(comprobantes, creditos, strict=True)]
        fragmentos = cobros.repartir_cobros(pagado, [c.monto for c in cobros_validos])
    else:
        creditos, cronogramas = [], []
        debidos = _debidos_tras_adelantos(comprobantes, previos, moneda)
        fragmentos, cobros_validos = _validar_cobros(cobros_entrada, debidos, sum(debidos, CERO))
    cuentas = {
        (f.comprobante, f.cobro): resolver_cuenta(
            comprobantes[f.comprobante].empresa,
            cobros_validos[f.cobro].medio_pago,
            sucursal,
            moneda,
        )
        for f in fragmentos
    }

    if proforma is not None:
        # Se bloquea la proforma: dos ventas a la vez no la cumplen las dos.
        proforma = Proforma.objects.sin_ambito().select_for_update().get(pk=proforma.pk)
        if proforma.empresa.organizacion_id != empresa.organizacion_id:
            raise VentaInvalida("La proforma no pertenece a la organización.")
        if proforma.estado != Proforma.Estado.EMITIDO:
            raise VentaInvalida("La proforma está anulada: no se puede vender.")
        if (
            Venta.objects.sin_ambito()
            .filter(proforma=proforma, estado=Venta.Estado.EMITIDO)
            .exists()
        ):
            raise VentaInvalida("Esa proforma ya se vendió.")
    venta = Venta.objects.create(
        empresa=empresa,
        numero=_siguiente_numero_interno(empresa),
        fecha=fecha,
        sucursal=sucursal,
        cliente=cliente,
        cliente_nombre=_texto(cliente.nombre, 250) if cliente else CLIENTE_VARIOS,
        cliente_tipo_documento=cliente.tipo_documento if cliente else "",
        cliente_documento=cliente.numero_documento if cliente else "",
        vendedor_id=vendedor_id,
        vendedor_nombre=vendedor,
        moneda=moneda,
        tipo_cambio=cambio,
        lista=lista,
        forma_pago=forma_pago,
        observacion=_texto(observacion, 250),
        total=total,
        proforma=proforma,
    )

    creados = [_emitir(venta, c, tipo, fecha, cliente, moneda, cambio, lista) for c in comprobantes]
    if traslados:
        # Con las líneas de la venta ya creadas, cada línea trasladada queda ligada a la suya.
        ventas_internas.registrar_documentos(
            venta,
            traslados,
            documento_interno,
            {id(ln.entrada): ln.linea_venta for c in comprobantes for ln in c.lineas},
        )
    for comprobante, cronograma in zip(creados, cronogramas, strict=False):
        CuotaVenta.objects.bulk_create(
            [
                CuotaVenta(
                    empresa=comprobante.empresa,
                    comprobante=comprobante,
                    numero=cuota.numero,
                    fecha_vencimiento=cuota.fecha,
                    monto=cuota.monto,
                )
                for cuota in cronograma
            ]
        )
    por_empresa = {c.empresa.pk: creados[i] for i, c in enumerate(comprobantes)}
    for previo in previos:
        CobroVenta.objects.create(
            empresa=previo.empresa,
            venta=venta,
            comprobante=por_empresa[previo.empresa.pk],
            medio_pago=previo.medio_pago,
            cuenta=previo.cuenta,
            monto=previo.monto,
            monto_cuenta=previo.monto,
            referencia=_texto(previo.referencia, 60),
            es_adelanto=True,
        )
    for fragmento in fragmentos:
        c, comprobante = comprobantes[fragmento.comprobante], creados[fragmento.comprobante]
        _cobrar(
            venta,
            comprobante,
            c.empresa,
            cobros_validos[fragmento.cobro],
            fragmento,
            cuentas[(fragmento.comprobante, fragmento.cobro)],
            es_primero=_es_primer_fragmento(fragmentos, fragmento),
            fecha=fecha,
        )
    registrar(
        "ventas.venta_registrada",
        recurso_tipo="venta",
        recurso_id=venta.pk,
        empresa_id=empresa.pk,
        resumen=(
            f"Venta N° {venta.numero:06d}: {moneda} {total} "
            f"({len(creados)} comprobante{'s' if len(creados) > 1 else ''})"
        ),
        detalle={
            "comprobantes": [c.numero_completo for c in creados],
            "vendedor": vendedor,
            "bajo_minimo": any(ln.bajo_minimo for c in comprobantes for ln in c.lineas),
            "forma_pago": forma_pago,
            "a_credito": sum(creditos, CERO),
        },
    )
    return venta


def _debidos_tras_adelantos(
    comprobantes: list[_Comprobante], previos: list[CobroPrevio], moneda: str
) -> list[Decimal]:
    """Lo que falta cobrar de cada comprobante después de descontar los adelantos de su empresa."""
    if not previos:
        return [c.totales.total for c in comprobantes]
    if moneda != Moneda.PEN:
        raise VentaInvalida("Los adelantos solo se aplican a ventas en soles.")
    empresas = {c.empresa.pk for c in comprobantes}
    for p in previos:
        if p.empresa.pk not in empresas:
            raise VentaInvalida("Hay un adelanto de una empresa que no emite comprobante aquí.")
        if not isinstance(p.monto, Decimal) or p.monto <= 0:
            raise VentaInvalida("El monto de un adelanto no es válido.")
    debidos = []
    for c in comprobantes:
        adelantos = sum((p.monto for p in previos if p.empresa.pk == c.empresa.pk), CERO)
        if adelantos > c.totales.total:
            raise VentaInvalida(
                f"Los adelantos de {_nombre_empresa(c.empresa)} ({adelantos:,.2f}) pasan de su "
                f"comprobante ({c.totales.total:,.2f}): devuelve la diferencia al cliente primero."
            )
        debidos.append(c.totales.total - adelantos)
    return debidos


def _es_primer_fragmento(fragmentos: list[cobros.Fragmento], fragmento: cobros.Fragmento) -> bool:
    """El recibido y el vuelto de un cobro se anotan solo en su primer pedazo."""
    return next(f for f in fragmentos if f.cobro == fragmento.cobro) is fragmento


def _armar_comprobantes(
    preparadas: list[_Linea],
    tipo: TipoComprobante,
    sucursal: Sucursal | None,
    series: dict[int, int] | None,
) -> list[_Comprobante]:
    empresas = {ln.entrada.empresa.pk: ln.entrada.empresa for ln in preparadas}
    comprobantes = []
    for surte in _orden_de_empresas(list(empresas.values())):
        c = _Comprobante(surte, _serie_de(surte, tipo, sucursal, series))
        c.lineas = [ln for ln in preparadas if ln.entrada.empresa.pk == surte.pk]
        comprobantes.append(c)
    return comprobantes


def _exigir_boleta_identificada(
    tipo: TipoComprobante, cliente: Cliente | None, total_soles: Decimal, avisos: list[str] | None
) -> None:
    if tipo.codigo == BOLETA and cliente is None and total_soles > TOPE_BOLETA_SIN_IDENTIFICAR:
        _faltante(
            f"Una boleta de más de S/ {TOPE_BOLETA_SIN_IDENTIFICAR:,.2f} lleva al cliente "
            "identificado (DNI).",
            avisos,
        )


def _cobros_validos(entradas: list[CobroEntrada]) -> list[CobroEntrada]:
    """Cada cobro revisado por separado: método vigente, monto, operación y efectivo recibido."""
    validos = []
    for entrada in entradas:
        medio = entrada.medio_pago
        if medio.estado != EstadoRegistro.ACTIVO:
            raise VentaInvalida(f"El método de pago «{medio.nombre}» no está disponible.")
        monto = _decimal(entrada.monto, f"Cobro con {medio.nombre}", decimales=Decimal("0.01"))
        if monto <= 0:
            raise VentaInvalida(f"Cobro con {medio.nombre}: el monto debe ser mayor que cero.")
        referencia = _texto(entrada.referencia, 60)
        if medio.requiere_referencia and not referencia:
            raise VentaInvalida(f"Cobro con {medio.nombre}: indique el número de operación.")
        recibido = entrada.recibido
        if recibido is not None:
            if medio.tipo != MedioPago.Tipo.EFECTIVO:
                raise VentaInvalida("Solo el efectivo lleva monto recibido y vuelto.")
            recibido = _decimal(recibido, "Efectivo recibido", decimales=Decimal("0.01"))
            cobros.calcular_vuelto(monto, recibido)
        validos.append(CobroEntrada(medio, monto, referencia, recibido))
    return validos


def _validar_cobros(
    entradas: list[CobroEntrada], totales: list[Decimal], total: Decimal
) -> tuple[list[cobros.Fragmento], list[CobroEntrada]]:
    validos = _cobros_validos(entradas)
    if sum((c.monto for c in validos), CERO) != total:
        raise VentaInvalida(
            f"Los cobros ({sum((c.monto for c in validos), CERO):,.2f}) deben sumar "
            f"exactamente el total de la venta ({total:,.2f})."
        )
    return cobros.repartir_cobros(totales, [c.monto for c in validos]), validos


def _emitir(
    venta: Venta,
    c: _Comprobante,
    tipo: TipoComprobante,
    fecha: date,
    cliente: Cliente | None,
    moneda: str,
    cambio: Decimal,
    lista: ListaPrecio,
) -> ComprobanteVenta:
    serie, numero = siguiente_numero(c.empresa, c.serie.pk)
    t = c.totales
    comprobante = ComprobanteVenta.objects.create(
        empresa=c.empresa,
        venta=venta,
        tipo_comprobante=tipo,
        serie_comprobante=c.serie,
        serie=serie,
        numero=numero,
        fecha=fecha,
        op_gravada=t.op_gravada,
        op_exonerada=t.op_exonerada,
        op_inafecta=t.op_inafecta,
        igv=t.igv,
        total=t.total,
    )
    _sacar_del_inventario(venta, comprobante, c, fecha, cliente, moneda, cambio)
    for orden, ln in enumerate(c.lineas):
        e = ln.entrada
        ln.linea_venta = LineaVenta.objects.create(
            empresa=c.empresa,
            venta=venta,
            comprobante=comprobante,
            orden=orden,
            producto=e.producto,
            descripcion=ln.descripcion,
            almacen=e.almacen,
            cantidad=e.cantidad,
            afectacion=ln.afectacion,
            tasa_igv=ln.tasa,
            lista=lista,
            precio_lista=ln.precio_lista,
            precio_unitario=ln.precio,
            precio_minimo=ln.minimo,
            bajo_minimo=ln.bajo_minimo,
            valor_venta=ln.importes.valor_venta,
            igv=ln.importes.igv,
            total=ln.importes.total,
            costo_unitario=ln.costo_unitario,
            costo_total=ln.costo_total,
            series=list(e.series),
            movimiento=ln.movimiento,
        )
    return comprobante


def _sacar_del_inventario(
    venta: Venta,
    comprobante: ComprobanteVenta,
    c: _Comprobante,
    fecha: date,
    cliente: Cliente | None,
    moneda: str,
    cambio: Decimal,
) -> None:
    """Una salida por cada almacén de la empresa; el costo de cada línea vuelve a la línea."""
    por_almacen: dict[int, list[_Linea]] = {}
    for ln in c.lineas:
        if ln.entrada.almacen is not None:
            por_almacen.setdefault(ln.entrada.almacen.pk, []).append(ln)
        elif ln.entrada.stock_ya_descontado:  # ya salió del almacén: el costo es el real
            ln.costo_total = a_dos(ln.entrada.costo_total)
            ln.costo_unitario = a_seis(ln.entrada.costo_total / ln.entrada.cantidad)
        else:  # un servicio: no mueve stock, su costo es el que tiene registrado
            ln.costo_unitario = ln.costo_estimado
            ln.costo_total = a_dos(ln.costo_estimado * ln.entrada.cantidad)
    for almacen_id in sorted(por_almacen):
        grupo = por_almacen[almacen_id]
        movimiento = registrar_salida(
            empresa=c.empresa,
            almacen=grupo[0].entrada.almacen,
            tipo=TipoMovimiento.SALIDA,
            origen=OrigenMovimiento.VENTA,
            fecha=fecha,
            lineas=[
                LineaNueva(
                    ln.entrada.producto,
                    ln.entrada.cantidad,
                    ln.precio,
                    series=tuple(ln.entrada.series),
                )
                for ln in grupo
            ],
            cliente=cliente,
            comprobante_tipo=comprobante.tipo_comprobante.codigo,
            comprobante_serie=comprobante.serie,
            comprobante_numero=str(comprobante.numero),
            comprobante_fecha=fecha,
            moneda=moneda,
            tipo_cambio=cambio if moneda != Moneda.PEN else None,
            referencia_tipo="venta",
            referencia_id=venta.pk,
            totales=(
                sum((ln.importes.valor_venta for ln in grupo), CERO),
                sum((ln.importes.igv for ln in grupo), CERO),
                sum((ln.importes.total for ln in grupo), CERO),
            ),
        )
        salidas = list(movimiento.lineas.order_by("orden"))
        if len(salidas) != len(grupo):
            raise VentaInvalida("No se pudo relacionar la salida de stock con la venta.")
        for ln, salida in zip(grupo, salidas, strict=True):
            ln.costo_unitario = salida.costo_unitario
            ln.costo_total = salida.costo_total
            ln.movimiento = movimiento


def _cobrar(
    venta: Venta,
    comprobante: ComprobanteVenta,
    empresa: Empresa,
    entrada: CobroEntrada,
    fragmento: cobros.Fragmento,
    cuenta: CuentaFinanciera,
    *,
    es_primero: bool,
    fecha: date,
) -> CobroVenta:
    vuelto = cobros.calcular_vuelto(entrada.monto, entrada.recibido) if es_primero else CERO
    cobro = CobroVenta.objects.create(
        empresa=empresa,
        venta=venta,
        comprobante=comprobante,
        medio_pago=entrada.medio_pago,
        cuenta=cuenta,
        monto=fragmento.monto,
        monto_cuenta=fragmento.monto,
        referencia=entrada.referencia,
        recibido=entrada.recibido if es_primero else None,
        vuelto=vuelto,
    )
    caja.registrar_cobro_de_venta(
        empresa=empresa,
        cuenta=cuenta,
        monto=fragmento.monto,
        fecha=fecha,
        referencia=entrada.referencia or comprobante.numero_completo,
        glosa=f"Venta {venta.numero:06d} · {comprobante.numero_completo}",
        cobro_id=cobro.pk,
        medio_pago=entrada.medio_pago,
    )
    return cobro


# ---------------------------------------------------------------------------
# Anular
# ---------------------------------------------------------------------------
@transaction.atomic
def anular_comprobante(comprobante: ComprobanteVenta, *, motivo: str) -> ComprobanteVenta:
    """Anula el comprobante de una empresa: el stock vuelve al almacén y el cobro se extorna.

    Los demás comprobantes de la venta siguen vigentes; cuando se anula el último, la venta
    también queda anulada. La numeración del comprobante anulado no se reutiliza.
    """
    from . import ventas_internas  # import tardío: ese módulo usa cosas de este

    periodos.exigir_empresa(comprobante.empresa)
    if comprobante.guias.filter(estado="EMITIDO").exists():
        raise VentaNoAnulable("El comprobante tiene guías de remisión vigentes: anúlalas primero.")
    if comprobante.notas_credito.exists():
        raise VentaNoAnulable(
            "El comprobante tiene notas de crédito: ya se devolvió una parte y no se puede anular."
        )
    # Si la venta pasó mercadería entre empresas: acceso a las dos y bloqueo en el orden de siempre.
    internas = ventas_internas.bloquear_para_anular(comprobante)
    comprobante.anular(motivo=motivo)  # exige el motivo y bloquea la fila
    movimientos = {
        ln.movimiento
        for ln in LineaVenta.objects.filter(comprobante=comprobante).select_related("movimiento")
        if ln.movimiento is not None
    }
    for movimiento in sorted(movimientos, key=lambda m: m.pk):
        anular_movimiento(
            movimiento, motivo=f"Anulación de {comprobante.numero_completo}: {motivo}"
        )
    # La mercadería ya volvió al almacén de la facturadora: ahora vuelve a quien la entregó.
    ventas_internas.anular_de_comprobante(internas, motivo=motivo)
    for cobro in CobroVenta.objects.filter(comprobante=comprobante):
        caja.anular_por_origen(
            Origen.COBRO_VENTA,
            cobro.pk,
            motivo=f"Anulación de {comprobante.numero_completo}: {motivo}",
        )
    # A crédito: lo que el cliente ya abonó vuelve a la caja de la empresa.
    from .cuentas_por_cobrar import revertir_abonos_de

    revertir_abonos_de(comprobante, f"Anulación de {comprobante.numero_completo}: {motivo}")
    venta = comprobante.venta
    if not ComprobanteVenta.objects.filter(
        venta=venta, estado=ComprobanteVenta.Estado.EMITIDO
    ).exists():
        venta.anular(motivo=motivo)
    registrar(
        "ventas.comprobante_anulado",
        recurso_tipo="comprobante_venta",
        recurso_id=comprobante.pk,
        empresa_id=comprobante.empresa_id,
        resumen=f"Se anuló el comprobante {comprobante.numero_completo}",
        detalle={"motivo": motivo, "venta": venta.numero},
    )
    return comprobante


def anular_venta(venta: Venta, *, motivo: str) -> Venta:
    """Anula todos los comprobantes vigentes de la venta (en el mismo orden de siempre)."""
    vigentes = list(
        ComprobanteVenta.objects.filter(venta=venta, estado=ComprobanteVenta.Estado.EMITIDO)
    )
    if not vigentes:
        raise VentaNoAnulable("La venta ya está anulada.")
    with transaction.atomic():
        for comprobante in sorted(vigentes, key=lambda c: c.pk):
            anular_comprobante(comprobante, motivo=motivo)
    venta.refresh_from_db()
    return venta
