"""Consulta rápida de un producto para el vendedor: precios, stock por almacén y ubicación.

Es una vista pensada para atender al cliente: NUNCA devuelve costos ni utilidad (el stock normal
sí los trae). Busca por nombre, código, código de barras o código del fabricante; si lo escrito
(o escaneado) coincide exactamente con un código, devuelve solo ese producto.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Prefetch, Q

from apps.mantenimiento.models import (
    EstadoRegistro,
    PrecioPresentacion,
    PrecioProducto,
    PresentacionProducto,
    Producto,
    UbicacionProducto,
)

from . import consultas
from .models import SaldoStock

MAX_RESULTADOS = 10
MIN_LETRAS = 2


def buscar(texto: str) -> tuple[list[Producto], bool, int | None]:
    """Productos activos que coinciden con ``texto``.

    El 2.º valor dice si fue un código exacto y el 3.º, qué presentación (caja, docena…) se
    escaneó cuando el código es el de una de ellas.
    """
    texto = " ".join((texto or "").split())
    if len(texto) < MIN_LETRAS:
        return [], False, None
    base = (
        Producto.objects.filter(estado=EstadoRegistro.ACTIVO)
        .select_related("categoria", "marca", "unidad")
        .prefetch_related(
            "fotos",
            Prefetch(
                "precios",
                queryset=PrecioProducto.objects.select_related("lista").order_by(
                    "lista__orden", "lista_id"
                ),
            ),
            Prefetch(
                "presentaciones",
                queryset=PresentacionProducto.objects.filter(estado=EstadoRegistro.ACTIVO)
                .select_related("unidad")
                .order_by("factor", "id")
                .prefetch_related(
                    Prefetch(
                        "precios",
                        queryset=PrecioPresentacion.objects.select_related("lista").order_by(
                            "lista__orden", "lista_id"
                        ),
                    )
                ),
            ),
        )
    )
    # El código de una caja o docena lleva al producto, con esa presentación marcada.
    codigo_presentacion = "".join(texto.split()).upper()
    de_presentacion = (
        PresentacionProducto.objects.filter(
            codigo_barras=codigo_presentacion, estado=EstadoRegistro.ACTIVO
        )
        .exclude(codigo_barras="")
        .first()
    )
    if de_presentacion is not None:
        producto = base.filter(pk=de_presentacion.producto_id).first()
        if producto is not None:
            return [producto], True, de_presentacion.pk
    exactos = base.filter(
        Q(codigo_barras__iexact=texto)
        | Q(codigo__iexact=texto)
        | Q(codigo_fabricante__iexact=texto)
    ).order_by("nombre", "id")[:MAX_RESULTADOS]
    exactos = list(exactos)
    if exactos:
        return exactos, True, None
    parecidos = base.filter(
        Q(nombre__icontains=texto)
        | Q(codigo__icontains=texto)
        | Q(codigo_barras__icontains=texto)
        | Q(codigo_fabricante__icontains=texto)
    ).order_by("nombre", "id")[:MAX_RESULTADOS]
    return list(parecidos), False, None


def _stock(usuario, productos: list[Producto]) -> dict[int, list[dict] | None]:
    """Stock vendible por producto y empresa; ``None`` si la persona no puede ver ningún stock."""
    visibles, habilitadas, con_detalle = consultas.empresas_visibles(usuario)
    if not visibles:
        return dict.fromkeys((p.pk for p in productos), None)
    ids = [p.pk for p in productos]
    saldos = defaultdict(lambda: defaultdict(list))
    filas = (
        SaldoStock.objects.sin_ambito()
        .filter(
            producto_id__in=ids,
            empresa_id__in=[e.pk for e in visibles],
            almacen__permite_venta=True,
            cantidad__gt=0,
        )
        .select_related("almacen")
        .order_by("almacen__codigo", "almacen_id")
    )
    for fila in filas:
        saldos[fila.producto_id][fila.empresa_id].append(fila)
    ubicaciones = {
        (u.almacen_id, u.producto_id): u.ubicacion
        for u in UbicacionProducto.objects.sin_ambito()
        .filter(producto_id__in=ids, empresa_id__in=list(con_detalle))
        .select_related("ubicacion")
    }

    resultado = {}
    for producto in productos:
        por_empresa = []
        for empresa in visibles:
            filas_empresa = saldos[producto.pk].get(empresa.pk, [])
            elemento = {
                "empresa": empresa.pk,
                "nombre": empresa.nombre_comercial or empresa.razon_social,
                "propia": empresa.pk in habilitadas,
                "cantidad": str(sum((f.cantidad for f in filas_empresa), Decimal("0"))),
            }
            if empresa.pk in con_detalle:
                elemento["almacenes"] = [
                    {
                        "almacen": f.almacen.nombre,
                        "cantidad": str(f.cantidad),
                        "ubicacion_codigo": getattr(
                            ubicaciones.get((f.almacen_id, producto.pk)), "codigo", None
                        ),
                        "ubicacion_nombre": getattr(
                            ubicaciones.get((f.almacen_id, producto.pk)), "nombre", None
                        ),
                    }
                    for f in filas_empresa
                ]
            por_empresa.append(elemento)
        resultado[producto.pk] = por_empresa
    return resultado


def _presentacion(presentacion: PresentacionProducto) -> dict:
    """Una caja o docena: cuántas unidades trae y su precio en cada lista (sin costos)."""
    return {
        "id": presentacion.pk,
        "unidad": presentacion.unidad.abreviatura,
        "unidad_nombre": presentacion.unidad.nombre,
        "factor": f"{presentacion.factor.normalize():f}",
        "precios": [
            {
                "lista": pr.lista_id,
                "nombre": pr.lista.nombre,
                "es_principal": pr.lista.es_principal,
                "precio": str(pr.precio),
            }
            for pr in presentacion.precios.all()
            if pr.lista.estado == EstadoRegistro.ACTIVO
        ],
    }


def consultar(usuario, texto: str) -> dict:
    """Respuesta completa de la consulta: productos con precios y stock (sin costos)."""
    productos, exacto, escaneada = buscar(texto)
    stock = _stock(usuario, [p for p in productos if p.controla_stock])
    resultados = []
    for p in productos:
        fotos = list(p.fotos.all())
        resultados.append(
            {
                "id": p.pk,
                "codigo": p.codigo,
                "nombre": p.nombre,
                "descripcion": p.descripcion,
                "marca": p.marca.nombre if p.marca else None,
                "categoria": p.categoria.nombre,
                "unidad": p.unidad.abreviatura,
                "codigo_barras": p.codigo_barras_efectivo,
                "tipo": p.tipo,
                "lleva_serie": p.lleva_serie,
                "controla_stock": p.controla_stock,
                "foto_principal": fotos[0].pk if fotos else None,
                "precios": [
                    {
                        "lista": pr.lista_id,
                        "nombre": pr.lista.nombre,
                        "es_principal": pr.lista.es_principal,
                        "precio": str(pr.precio),
                    }
                    for pr in p.precios.all()
                    if pr.lista.estado == EstadoRegistro.ACTIVO
                ],
                "presentaciones": [_presentacion(pr) for pr in p.presentaciones.all()],
                # ``None`` = no controla stock (servicio); lista vacía = sin permiso para verlo.
                "stock": (stock.get(p.pk) or []) if p.controla_stock else None,
            }
        )
    return {"exacto": exacto, "presentacion_escaneada": escaneada, "results": resultados}
