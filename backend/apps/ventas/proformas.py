"""Proformas: cotizar un carrito sin mover stock ni dinero, y venderlo después.

Los precios, el mínimo permitido y el IGV de cada empresa se calculan igual que en una venta, así
lo cotizado es lo que se cobrará si el cliente acepta. Cada línea recuerda qué empresa la surtiría
y la proforma muestra el total de cada una. El stock no se reserva: se revisa al vender.
"""

import logging
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.compras.calculo import EntradaLinea
from apps.inventario import periodos
from apps.inventario.models import TipoMovimiento
from apps.inventario.movimientos import resolver_tipo_cambio
from apps.mantenimiento import series as numeracion
from apps.mantenimiento.models import (
    Cliente,
    EstadoRegistro,
    ListaPrecio,
    SerieComprobante,
)
from apps.organizacion.models import Empresa, Sucursal

from . import calculo, precios
from .exceptions import VentaInvalida
from .models import CERO, FormaPago, LineaProforma, Moneda, Proforma, Venta
from .servicios import (
    LineaEntrada,
    _fecha,
    _lista_de_credito,
    _lista_de_venta,
    _orden_de_empresas,
    _preparar_linea,
    _texto,
)

logger = logging.getLogger(__name__)

VALIDEZ_MAXIMA = 90
MAX_LINEAS = 100
VIGENTE, VENCIDA, VENDIDA, ANULADA = "VIGENTE", "VENCIDA", "VENDIDA", "ANULADA"


def estado_de(proforma: Proforma, hoy: date | None = None, *, vendida: bool | None = None) -> str:
    """Cómo está la proforma: vigente, vencida, ya vendida o anulada."""
    if proforma.estado == Proforma.Estado.ANULADO:
        return ANULADA
    if vendida is None:
        vendida = (
            Venta.objects.sin_ambito()
            .filter(proforma=proforma, estado=Venta.Estado.EMITIDO)
            .exists()
        )
    if vendida:
        return VENDIDA
    return VENCIDA if proforma.valida_hasta < (hoy or timezone.localdate()) else VIGENTE


def series_de_proforma(empresa_id: int) -> list[dict]:
    """Las series de proformas activas de la empresa, con su próximo número."""
    return [
        {
            "id": x.pk,
            "serie": x.serie,
            "nombre": x.nombre,
            "sucursal": x.sucursal_id,
            "proximo": numeracion.formatear(x.serie, x.proximo_numero),
        }
        for x in SerieComprobante.objects.sin_ambito()
        .filter(empresa_id=empresa_id, tipo_comprobante__codigo="PF", estado=EstadoRegistro.ACTIVO)
        .order_by("serie")
    ]


def _serie_de_proformas(
    empresa: Empresa, sucursal: Sucursal | None, elegida: int | None
) -> SerieComprobante:
    """La serie con que la empresa numera la proforma: la elegida o la de su tienda."""
    nombre = empresa.nombre_comercial or empresa.razon_social
    series = list(
        SerieComprobante.objects.sin_ambito().filter(
            empresa=empresa, tipo_comprobante__codigo="PF", estado=EstadoRegistro.ACTIVO
        )
    )
    if not series:
        raise VentaInvalida(
            f"{nombre} no tiene una serie de proformas (por ejemplo P001). Créela en "
            "Mantenimiento → Series de comprobantes para poder hacer proformas."
        )
    if elegida is not None:
        serie = next((x for x in series if x.pk == elegida), None)
        if serie is None:
            raise VentaInvalida(f"La serie de proformas elegida no es válida para {nombre}.")
        return serie
    propias = [x for x in series if sucursal is not None and x.sucursal_id == sucursal.pk]
    generales = [x for x in series if x.sucursal_id is None]
    for grupo in (propias, generales, series):
        if len(grupo) == 1:
            return grupo[0]
    raise VentaInvalida(f"{nombre} tiene varias series de proformas: elija una.")


@transaction.atomic
def crear_proforma(
    *,
    empresa: Empresa,
    lineas: list[LineaEntrada],
    vendedor_nombre: str,
    vendedor_id: uuid.UUID | None = None,
    cliente: Cliente | None = None,
    cliente_nombre: str = "",
    cliente_documento: str = "",
    cliente_contacto: str = "",
    cliente_direccion: str = "",
    fecha_entrega: date | None = None,
    atencion: str = "",
    lugar_entrega: str = "",
    serie: int | None = None,
    forma_pago: str = FormaPago.CONTADO,
    puede_credito: bool = False,
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    lista: ListaPrecio | None = None,
    sucursal: Sucursal | None = None,
    validez_dias: int = 7,
    condiciones: str = "",
    puede_descontar: bool = False,
    puede_precio_tecnico: bool = False,
    puede_vender_bajo_minimo: bool = False,
    puede_vender_stock_otra_empresa: bool = False,
) -> Proforma:
    """Cotiza un carrito: guarda las líneas con su precio e IGV, sin tocar el stock."""
    periodos.exigir_empresa(empresa)
    hoy = _fecha(timezone.localdate())
    if moneda not in Moneda.values:
        raise VentaInvalida("La moneda no es válida.")
    if not lineas:
        raise VentaInvalida("Agregue al menos un producto.")
    if len(lineas) > MAX_LINEAS:
        raise VentaInvalida(f"Una proforma admite hasta {MAX_LINEAS} productos.")
    if not isinstance(validez_dias, int) or not (1 <= validez_dias <= VALIDEZ_MAXIMA):
        raise VentaInvalida(f"La proforma vale de 1 a {VALIDEZ_MAXIMA} días.")
    if sucursal is not None and sucursal.empresa_id != empresa.pk:
        raise VentaInvalida("La tienda no pertenece a la empresa.")
    if fecha_entrega is not None and fecha_entrega < hoy:
        raise VentaInvalida("La fecha de entrega no puede ser anterior a hoy.")
    serie_obj = _serie_de_proformas(empresa, sucursal, serie)
    if cliente is not None:
        if cliente.organizacion_id != empresa.organizacion_id:
            raise VentaInvalida("El cliente no pertenece a la organización.")
        nombre, documento = cliente.nombre, cliente.numero_documento
        # Lo que la proforma muestra del cliente sale de su ficha, salvo que se indique otra cosa.
        cliente_direccion = cliente_direccion or cliente.direccion
        cliente_contacto = cliente_contacto or " · ".join(
            x for x in (cliente.telefono, cliente.correo) if x
        )
    else:
        nombre, documento = _texto(cliente_nombre, 250), _texto(cliente_documento, 20)
        if len(nombre) < 2:
            raise VentaInvalida("Indique para quién es la proforma.")

    cambio = resolver_tipo_cambio(empresa, moneda, tipo_cambio, TipoMovimiento.SALIDA, hoy)
    listas = precios.cargar_listas(empresa.organizacion_id)
    if forma_pago not in FormaPago.values:
        raise VentaInvalida("La forma de pago no es válida.")
    a_credito = forma_pago == FormaPago.CREDITO
    if a_credito and not puede_credito:
        raise VentaInvalida("No tiene permiso para cotizar a crédito.")
    if a_credito:
        lista = _lista_de_credito(listas)
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
            fecha=hoy,
            puede_bajo_minimo=puede_vender_bajo_minimo,
            puede_otra_empresa=puede_vender_stock_otra_empresa,
            exigir_almacen=False,
            a_credito=a_credito,
        )
        for ln in lineas
    ]

    # El IGV se calcula por empresa, como en la venta: cada una emitiría su comprobante.
    por_empresa: dict[int, list] = defaultdict(list)
    for p in preparadas:
        por_empresa[p.entrada.empresa.pk].append(p)
    empresas = {p.entrada.empresa.pk: p.entrada.empresa for p in preparadas}
    for surte in _orden_de_empresas(list(empresas.values())):
        grupo = por_empresa[surte.pk]
        totales = calculo.calcular_comprobante(
            [
                EntradaLinea(
                    p.entrada.cantidad, p.precio, p.afectacion.grupo, p.afectacion.impuesto, p.tasa
                )
                for p in grupo
            ]
        )
        for p, importes in zip(grupo, totales.lineas, strict=True):
            p.importes = importes
    total = sum((p.importes.total for p in preparadas), CERO)

    serie_texto, numero = numeracion.siguiente_numero(empresa, serie_obj.pk)
    proforma = Proforma.objects.create(
        empresa=empresa,
        serie=serie_texto,
        serie_comprobante=serie_obj,
        forma_pago=forma_pago,
        numero=numero,
        fecha=hoy,
        valida_hasta=hoy + timedelta(days=validez_dias),
        sucursal=sucursal,
        cliente=cliente,
        cliente_nombre=nombre,
        cliente_documento=documento,
        cliente_contacto=_texto(cliente_contacto, 120),
        cliente_direccion=_texto(cliente_direccion, 250),
        fecha_entrega=fecha_entrega,
        atencion=_texto(atencion, 120),
        lugar_entrega=_texto(lugar_entrega, 250),
        vendedor_id=vendedor_id,
        vendedor_nombre=_texto(vendedor_nombre, 150),
        moneda=moneda,
        tipo_cambio=cambio,
        lista=lista,
        condiciones=_texto(condiciones, 500),
        total=total,
    )
    LineaProforma.objects.bulk_create(
        [
            LineaProforma(
                empresa=p.entrada.empresa,
                proforma=proforma,
                orden=orden,
                producto=p.entrada.producto,
                descripcion=p.descripcion,
                cantidad=p.entrada.cantidad,
                afectacion=p.afectacion,
                tasa_igv=p.tasa,
                precio_lista=p.precio_lista,
                precio_unitario=p.precio,
                valor_venta=p.importes.valor_venta,
                igv=p.importes.igv,
                total=p.importes.total,
            )
            for orden, p in enumerate(preparadas)
        ]
    )
    registrar(
        "ventas.proforma_creada",
        recurso_tipo="proforma",
        recurso_id=proforma.pk,
        empresa_id=empresa.pk,
        resumen=f"Proforma {proforma.numero_completo} para {nombre}: {moneda} {total}",
        detalle={"valida_hasta": proforma.valida_hasta, "lineas": len(preparadas)},
    )
    return proforma


@transaction.atomic
def anular_proforma(proforma: Proforma, *, motivo: str) -> Proforma:
    """Anula una proforma que todavía no se vendió."""
    periodos.exigir_empresa(proforma.empresa)
    if Venta.objects.sin_ambito().filter(proforma=proforma, estado=Venta.Estado.EMITIDO).exists():
        raise VentaInvalida("La proforma ya se vendió: no se puede anular.")
    proforma.anular(motivo=motivo)
    registrar(
        "ventas.proforma_anulada",
        recurso_tipo="proforma",
        recurso_id=proforma.pk,
        empresa_id=proforma.empresa_id,
        resumen=f"Proforma {proforma.numero_completo} anulada",
        detalle={"motivo": (motivo or "").strip()[:200]},
    )
    return proforma
