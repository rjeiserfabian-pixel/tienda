"""Consultas de solo lectura sobre el stock: disponibilidad entre empresas y saldo del Kardex."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.mantenimiento.models import Producto
from apps.organizacion.models import Empresa, Estado
from apps.seguridad.services import permisos_engine as motor

from .costeo import Saldo
from .models import LineaMovimiento, SaldoStock

CERO = "0"


def _texto(valor: Decimal) -> str:
    """Los importes viajan como texto: un número flotante en JSON perdería precisión."""
    return str(valor)


VER = "INVENTARIO.VER"
VER_OTRA_EMPRESA = "INVENTARIO.STOCK_OTRA_EMPRESA.VER"


def saldo_antes_de(empresa_id: int, almacen_id: int, producto_id: int, desde: date | None) -> Saldo:
    """Saldo (con decimales) con que arranca el Kardex en ``desde``: la última línea anterior."""
    if desde is None:
        return Saldo()
    anterior = (
        LineaMovimiento.objects.filter(
            empresa_id=empresa_id, almacen_id=almacen_id, producto_id=producto_id, fecha__lt=desde
        )
        .order_by("-fecha", "-movimiento_id", "-id")
        .first()
    )
    if anterior is None:
        return Saldo()
    return Saldo(anterior.saldo_cantidad, anterior.saldo_costo_total, anterior.saldo_costo_unitario)


def saldo_al_inicio(empresa_id: int, almacen_id: int, producto_id: int, desde: date | None):
    """Lo mismo que ``saldo_antes_de``, como texto para la API (sin perder precisión)."""
    saldo = saldo_antes_de(empresa_id, almacen_id, producto_id, desde)
    if desde is None:
        return {"cantidad": CERO, "costo_total": CERO, "costo_unitario": CERO}
    return {
        "cantidad": _texto(saldo.cantidad),
        "costo_total": _texto(saldo.costo_total),
        "costo_unitario": _texto(saldo.costo_unitario),
    }


def empresas_visibles(usuario) -> tuple[list[Empresa], set[int], set[int]]:
    """Empresas cuyo stock puede ver la persona: ``(visibles, habilitadas, con_detalle)``.

    ``con_detalle`` son las suyas con ``INVENTARIO.VER`` (ve almacenes); las demás visibles solo
    muestran la cantidad total (``INVENTARIO.STOCK_OTRA_EMPRESA.VER``).
    """
    empresas = list(Empresa.objects.filter(estado=Estado.ACTIVO).order_by("-es_principal", "id"))
    habilitadas = set(motor.empresas_ids_de(usuario))
    ve_otras = motor.tiene_permiso(usuario, VER_OTRA_EMPRESA, None)
    detalle_de = {
        e.pk for e in empresas if e.pk in habilitadas and motor.tiene_permiso(usuario, VER, e.pk)
    }
    visibles = [e for e in empresas if e.pk in detalle_de or ve_otras]
    return visibles, habilitadas, detalle_de


def disponibilidad(usuario, producto: Producto) -> list[dict]:
    """Existencias de un producto en cada empresa de la organización, según lo que puede ver.

    * Empresa a la que tiene acceso y con ``INVENTARIO.VER``: detalle por almacén, con costos.
    * Otra empresa, si tiene ``INVENTARIO.STOCK_OTRA_EMPRESA.VER`` (a nivel de organización):
      solo la cantidad total, sin costos ni almacenes.
    * Cualquier otra: no aparece.
    """
    visibles, habilitadas, detalle_de = empresas_visibles(usuario)
    if not visibles:
        return []

    saldos = defaultdict(list)
    filas = (
        SaldoStock.objects.sin_ambito()
        .filter(producto=producto, empresa_id__in=[e.pk for e in visibles])
        .filter(Q(cantidad__gt=0) | Q(costo_total__gt=0))
        .select_related("almacen")
        .order_by("almacen__codigo", "almacen_id")
    )
    for fila in filas:
        saldos[fila.empresa_id].append(fila)

    resultado = []
    for empresa in visibles:
        filas_empresa = saldos.get(empresa.pk, [])
        total = sum((f.cantidad for f in filas_empresa), Decimal("0"))
        elemento = {
            "empresa": empresa.pk,
            "razon_social": empresa.razon_social,
            "nombre_comercial": empresa.nombre_comercial,
            "es_principal": empresa.es_principal,
            "propia": empresa.pk in habilitadas,
            "cantidad": _texto(total),
        }
        if empresa.pk in detalle_de:
            elemento["almacenes"] = [
                {
                    "almacen": f.almacen_id,
                    "nombre": f.almacen.nombre,
                    "cantidad": _texto(f.cantidad),
                    "costo_unitario": _texto(f.costo_unitario),
                    "costo_total": _texto(f.costo_total),
                }
                for f in filas_empresa
            ]
        resultado.append(elemento)
    return resultado
