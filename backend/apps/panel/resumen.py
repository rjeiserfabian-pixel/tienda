"""Resumen del panel de Inicio: lo que importa hoy, de UNA empresa.

Reutiliza las consultas de cada módulo (ventas, cartera, compras, caja, gastos, inventario y
servicio técnico). Cada bloque se muestra solo si la persona tiene el permiso de ese módulo con
alcance de toda la empresa; si no, el bloque ni se calcula. Si un bloque falla, los demás siguen:
se registra el error y ese bloque llega marcado como no disponible.

Soles y dólares nunca se suman: cada total viaja por moneda. El costo y la utilidad solo salen para
quien tiene VENTAS.VER_UTILIDAD.
"""

import logging
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from apps.caja import alertas as alertas_caja
from apps.caja import servicios as servicios_caja
from apps.compras.models import Compra, CuotaCompra
from apps.gastos import reportes as reportes_gastos
from apps.inventario import antiguedad
from apps.inventario.models import SaldoStock
from apps.mantenimiento.models import EstadoRegistro, TipoProducto
from apps.organizacion.models import Empresa
from apps.seguridad.services import permisos_engine as motor
from apps.servicio_tecnico.models import EstadoOrden, OrdenServicio
from apps.ventas import cartera
from apps.ventas import reportes as reportes_ventas
from apps.ventas.models import LineaNotaCredito, LineaVenta

logger = logging.getLogger(__name__)

CERO = Decimal("0")
SEGUNDOS_CACHE = 60
TOP_PRODUCTOS = 5
TOP_CATEGORIAS = 6
MAX_AVISOS = 5
EMITIDO = "EMITIDO"
SIN_CATEGORIA = "Sin categoría"
# Una orden en alguno de estos estados ya no está en el taller.
ESTADOS_CERRADOS = (
    EstadoOrden.ENTREGADO,
    EstadoOrden.NO_APROBADO,
    EstadoOrden.SIN_SOLUCION,
    EstadoOrden.ABANDONADO,
)
PENDIENTE = ExpressionWrapper(
    F("monto") - F("pagado"), output_field=DecimalField(max_digits=16, decimal_places=2)
)

# Permiso que habilita cada bloque (siempre con alcance de toda la empresa).
PERMISOS = {
    "ventas": "VENTAS.VER",
    "por_cobrar": "VENTAS.VER",
    "compras": "COMPRAS.VER",
    "gastos": "GASTOS.VER",
    "inventario": "INVENTARIO.VER",
    "caja": "CAJA.MOVIMIENTOS.VER",
    "servicio": "SERVICIOS.VER",
}
UTILIDAD = "VENTAS.VER_UTILIDAD"


def _periodo(hoy: date) -> tuple[date, date]:
    return hoy.replace(day=1), hoy


def _por_moneda(filas: list[dict], campo: str) -> list[dict]:
    return [{"moneda": f["moneda"], "monto": f[campo]} for f in filas]


# -- ventas -------------------------------------------------------------------
def _lineas_netas(empresa: Empresa, desde: date, hasta: date, ruta_producto: str, nota_ruta: str):
    """Valor vendido (sin IGV) por moneda y grupo, restando lo devuelto con notas de crédito."""
    neto: dict[tuple[str, str, str], dict] = {}

    def sumar(clave, nombre, valor, unidades):
        fila = neto.setdefault(clave, {"nombre": nombre, "valor": CERO, "unidades": CERO})
        fila["valor"] += valor
        fila["unidades"] += unidades

    vendidas = (
        LineaVenta.objects.filter(
            empresa=empresa,
            comprobante__estado=EMITIDO,
            comprobante__fecha__gte=desde,
            comprobante__fecha__lte=hasta,
        )
        .values("venta__moneda", ruta_producto)
        .annotate(valor=Sum("valor_venta"), unidades=Sum("cantidad"))
    )
    for f in vendidas:
        nombre = f[ruta_producto]
        sumar((f["venta__moneda"], nombre or "", ""), nombre, f["valor"] or CERO, f["unidades"])
    devueltas = (
        LineaNotaCredito.objects.filter(
            empresa=empresa, nota__estado=EMITIDO, nota__fecha__gte=desde, nota__fecha__lte=hasta
        )
        .values("nota__venta__moneda", nota_ruta)
        .annotate(valor=Sum("valor_venta"), unidades=Sum("cantidad"))
    )
    for f in devueltas:
        nombre = f[nota_ruta]
        sumar(
            (f["nota__venta__moneda"], nombre or "", ""),
            nombre,
            -(f["valor"] or CERO),
            -(f["unidades"] or CERO),
        )
    return neto


def _top_por_moneda(neto: dict, limite: int, *, etiqueta_vacia: str) -> list[dict]:
    por_moneda: dict[str, list[dict]] = {}
    for (moneda, _nombre, _), f in neto.items():
        if f["valor"] <= 0:
            continue
        por_moneda.setdefault(moneda, []).append(
            {
                "nombre": f["nombre"] or etiqueta_vacia,
                "valor": f["valor"],
                "unidades": f["unidades"],
            }
        )
    salida = []
    for moneda, filas in sorted(por_moneda.items()):
        filas.sort(key=lambda f: -f["valor"])
        total = sum((f["valor"] for f in filas), CERO)
        principales = filas[:limite]
        resto = sum((f["valor"] for f in filas[limite:]), CERO)
        if resto > 0:
            principales.append({"nombre": "Otros", "valor": resto, "unidades": CERO})
        for f in principales:
            f["porcentaje"] = (f["valor"] * 100 / total).quantize(Decimal("0.1")) if total else CERO
        salida.append({"moneda": moneda, "total": total, "filas": principales})
    return salida


def _ventas(empresa: Empresa, usuario, hoy: date) -> dict:
    desde, hasta = _periodo(hoy)
    con_utilidad = motor.tiene_permiso(usuario, UTILIDAD, empresa.pk, alcance_minimo="EMPRESA")
    dia = reportes_ventas.resumen(empresa, hoy, hoy, con_utilidad=con_utilidad)
    mes = reportes_ventas.resumen(empresa, desde, hasta, con_utilidad=con_utilidad)
    categorias = _lineas_netas(
        empresa,
        desde,
        hasta,
        "producto__categoria__familia__nombre",
        "linea_venta__producto__categoria__familia__nombre",
    )
    productos = _lineas_netas(
        empresa, desde, hasta, "producto__nombre", "linea_venta__producto__nombre"
    )
    return {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "hoy": dia["totales"],
        "mes": mes["totales"],
        "por_categoria": _top_por_moneda(categorias, TOP_CATEGORIAS, etiqueta_vacia=SIN_CATEGORIA),
        "mas_vendidos": _top_por_moneda(productos, TOP_PRODUCTOS, etiqueta_vacia="Otros"),
    }


def _por_cobrar(empresa: Empresa, usuario, hoy: date) -> dict:
    filas = cartera.resumen(cartera.comprobantes_a_credito(empresa.pk), hoy=hoy)
    return {"totales": filas}


# -- compras, gastos ----------------------------------------------------------
def _compras(empresa: Empresa, usuario, hoy: date) -> dict:
    desde, hasta = _periodo(hoy)
    mes = (
        Compra.objects.filter(
            empresa=empresa, estado=EMITIDO, fecha_emision__gte=desde, fecha_emision__lte=hasta
        )
        .values("moneda")
        .annotate(total=Sum("total"), cantidad=Count("id"))
        .order_by("moneda")
    )
    cuotas = (
        CuotaCompra.objects.filter(
            empresa=empresa,
            compra__estado=EMITIDO,
            compra__forma_pago="CREDITO",
            pagado__lt=F("monto"),
        )
        .values("compra__moneda")
        .annotate(
            saldo=Sum(PENDIENTE),
            vencido=Sum(PENDIENTE, filter=Q(fecha_vencimiento__lt=hoy)),
            facturas=Count("compra", distinct=True),
        )
        .order_by("compra__moneda")
    )
    return {
        "mes": [
            {"moneda": f["moneda"], "total": f["total"] or CERO, "cantidad": f["cantidad"]}
            for f in mes
        ],
        "por_pagar": [
            {
                "moneda": f["compra__moneda"],
                "saldo": f["saldo"] or CERO,
                "vencido": f["vencido"] or CERO,
                "facturas": f["facturas"],
            }
            for f in cuotas
        ],
    }


def _gastos(empresa: Empresa, usuario, hoy: date) -> dict:
    desde, hasta = _periodo(hoy)
    datos = reportes_gastos.resumen(empresa, desde, hasta)
    return {"mes": [{"moneda": t["moneda"], "total": t["total"]} for t in datos["totales"]]}


# -- inventario ---------------------------------------------------------------
def _inventario(empresa: Empresa, usuario, hoy: date) -> dict:
    """Existencias por producto sumando todos los almacenes de la empresa."""
    por_producto = (
        SaldoStock.objects.filter(
            empresa=empresa,
            producto__estado=EstadoRegistro.ACTIVO,
            producto__tipo=TipoProducto.BIEN,
        )
        .values("producto_id", "producto__stock_minimo")
        .annotate(total=Sum("cantidad"), valor=Sum("costo_total"))
    )
    unidades = valor = CERO
    con_stock = bajo = agotados = 0
    for f in por_producto:
        total = f["total"] or CERO
        unidades += total
        valor += f["valor"] or CERO
        minimo = f["producto__stock_minimo"] or CERO
        if total <= 0:
            agotados += 1
        else:
            con_stock += 1
            if minimo > 0 and total <= minimo:
                bajo += 1
    return {
        "unidades": unidades,
        "productos_con_stock": con_stock,
        "productos_bajo_minimo": bajo,
        "productos_agotados": agotados,
        "valor_costo_soles": valor,
        "stock_antiguo": antiguedad.resumen_de_empresa(empresa.pk),
    }


# -- caja y servicio ----------------------------------------------------------
def _caja(empresa: Empresa, usuario, hoy: date) -> dict:
    saldos: dict[str, Decimal] = {}
    cuentas = 0
    for fila in servicios_caja.saldos_de_la_empresa(empresa):
        cuenta = fila["cuenta"]
        if cuenta.estado != EstadoRegistro.ACTIVO:
            continue
        cuentas += 1
        saldos[cuenta.moneda] = saldos.get(cuenta.moneda, CERO) + fila["saldo"]
    avisos = alertas_caja.alertas(empresa)[:MAX_AVISOS]
    return {
        "cuentas": cuentas,
        "saldos": [{"moneda": m, "monto": v} for m, v in sorted(saldos.items())],
        "avisos": avisos,
    }


def _servicio(empresa: Empresa, usuario, hoy: date) -> dict:
    filas = (
        OrdenServicio.objects.filter(empresa=empresa)
        .exclude(estado__in=ESTADOS_CERRADOS)
        .values("estado")
        .annotate(cantidad=Count("id"))
    )
    por_estado = {f["estado"]: f["cantidad"] for f in filas}
    return {
        "abiertas": sum(por_estado.values()),
        "listas_para_entrega": por_estado.get(EstadoOrden.LISTO_ENTREGA, 0),
        "esperan_aprobacion": por_estado.get(EstadoOrden.PENDIENTE_APROBACION, 0),
        "esperan_repuesto": por_estado.get(EstadoOrden.PENDIENTE_REPUESTO, 0),
    }


BLOQUES: dict[str, Callable[[Empresa, object, date], dict]] = {
    "ventas": _ventas,
    "por_cobrar": _por_cobrar,
    "compras": _compras,
    "gastos": _gastos,
    "inventario": _inventario,
    "caja": _caja,
    "servicio": _servicio,
}


def bloques_permitidos(usuario, empresa: Empresa) -> list[str]:
    return [
        nombre
        for nombre, permiso in PERMISOS.items()
        if motor.tiene_permiso(usuario, permiso, empresa.pk, alcance_minimo="EMPRESA")
    ]


def resumen_inicio(usuario, empresa: Empresa) -> dict:
    """Los bloques que la persona puede ver, listos para mostrar (60 s en memoria por usuario)."""
    clave = f"panel:inicio:{empresa.pk}:{usuario.pk}"
    guardado = cache.get(clave)
    if guardado is not None:
        return guardado
    hoy = timezone.localdate()
    datos: dict = {"fecha": hoy, "empresa": empresa.pk, "bloques": {}}
    for nombre in bloques_permitidos(usuario, empresa):
        try:
            datos["bloques"][nombre] = BLOQUES[nombre](empresa, usuario, hoy)
        except Exception:  # noqa: BLE001 - un bloque roto no debe tumbar el panel entero
            logger.exception(
                "panel_bloque_fallo",
                extra={"empresa_id": empresa.pk, "bloque": nombre, "usuario_id": str(usuario.pk)},
            )
            datos["bloques"][nombre] = {"error": True}
    cache.set(clave, datos, SEGUNDOS_CACHE)
    return datos
