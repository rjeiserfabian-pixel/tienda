"""Panel de métricas de la tienda: cómo van las ventas web y qué requiere atención.

Todo sale de los pedidos y de la actividad de la propia tienda (nada inventado). «Venta» es un
pedido ya cobrado: pagado, en preparación, enviado, listo o entregado; los reembolsados, vencidos y
cancelados no cuentan. Los importes son con IGV, tal como paga el cliente.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import carrito_abandonado
from .models import (
    AvisoDisponibilidad,
    CuentaCliente,
    Cupon,
    Favorito,
    LineaPedido,
    PedidoTienda,
    Reclamo,
    ResenaProducto,
    UsoCupon,
)

Estado = PedidoTienda.Estado
VENTA = [
    Estado.PAGADO,
    Estado.EN_PREPARACION,
    Estado.ENVIADO,
    Estado.LISTO_PARA_RECOJO,
    Estado.ENTREGADO,
]
CON_ADELANTO = [Estado.ADELANTO_PAGADO]
DIAS_PERMITIDOS = (7, 30, 90)
CERO = Decimal("0")


def _dinero(valor) -> str:
    return format((valor or CERO).quantize(Decimal("0.01")), "f")


def resumen(organizacion_id: int, dias: int = 30) -> dict:
    dias = dias if dias in DIAS_PERMITIDOS else 30
    zona = timezone.get_current_timezone()
    ahora = timezone.now()
    hoy = timezone.localtime(ahora, zona).date()
    primer_dia = hoy - timedelta(days=dias - 1)
    desde = timezone.make_aware(datetime.combine(primer_dia, datetime.min.time()), zona)

    pedidos = PedidoTienda.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    del_periodo = pedidos.filter(creado_en__gte=desde)
    ventas = pedidos.filter(estado__in=VENTA, pagado_en__gte=desde)

    agregado = ventas.aggregate(n=Count("id"), total=Sum("total"), descuento=Sum("descuento_cupon"))
    n = agregado["n"] or 0
    total = agregado["total"] or CERO

    por_dia = {
        f["dia"]: f
        for f in ventas.annotate(dia=TruncDate("pagado_en", tzinfo=zona))
        .values("dia")
        .annotate(n=Count("id"), total=Sum("total"))
    }
    serie = []
    for i in range(dias):
        dia = primer_dia + timedelta(days=i)
        f = por_dia.get(dia)
        serie.append(
            {
                "fecha": dia.isoformat(),
                "pedidos": f["n"] if f else 0,
                "total": _dinero(f["total"]) if f else "0.00",
            }
        )

    creados = del_periodo.count()
    cobrados = del_periodo.filter(estado__in=[*VENTA, *CON_ADELANTO]).count()
    por_metodo = {
        (fila["pago_metodo"], fila["culqi_medio"] or ""): fila["n"]
        for fila in ventas.values("pago_metodo", "culqi_medio").annotate(n=Count("id"))
    }
    tarjeta = sum(v for (m, c), v in por_metodo.items() if m == "CULQI" and c == "tarjeta")
    yape = sum(v for (m, c), v in por_metodo.items() if m == "CULQI" and c == "yape")
    transferencia = sum(v for (m, _), v in por_metodo.items() if m == "TRANSFERENCIA")
    modalidades = {
        f["modalidad"]: f["n"] for f in ventas.values("modalidad").annotate(n=Count("id"))
    }

    top = (
        LineaPedido.objects.sin_ambito()
        .filter(pedido__in=ventas, es_envio=False)
        .values("producto_id", "descripcion")
        .annotate(unidades=Sum("cantidad"), total=Sum("total"))
        .order_by("-unidades", "-total")[:8]
    )

    usos = UsoCupon.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, estado="CONSUMIDO", creado_en__gte=desde
    )
    cupones = usos.aggregate(n=Count("id"), monto=Sum("monto"))
    cuentas = CuentaCliente.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    resenas = ResenaProducto.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, estado="PUBLICADA"
    )
    reclamos = Reclamo.objects.sin_ambito().filter(
        organizacion_id=organizacion_id, estado="PENDIENTE"
    )
    interes = (
        AvisoDisponibilidad.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, avisado_en__isnull=True)
        .values("producto_id", "producto__nombre")
        .annotate(n=Count("id"))
        .order_by("-n")[:5]
    )

    return {
        "dias": dias,
        "desde": primer_dia.isoformat(),
        "ventas": {
            "pedidos": n,
            "total": _dinero(total),
            "ticket_promedio": _dinero(total / n) if n else "0.00",
            "descuentos": _dinero(agregado["descuento"]),
            "serie": serie,
        },
        "embudo": {
            "creados": creados,
            "cobrados": cobrados,
            "sin_pagar": del_periodo.filter(
                estado__in=[Estado.PENDIENTE_PAGO, Estado.EXPIRADO, Estado.CANCELADO]
            ).count(),
            "tasa_pago": round(cobrados * 100 / creados, 1) if creados else None,
        },
        "pago": {"tarjeta": tarjeta, "yape": yape, "transferencia": transferencia},
        "entrega": {
            "envio": modalidades.get("ENVIO", 0),
            "recojo": modalidades.get("RECOJO", 0),
        },
        "top_productos": [
            {
                "id": f["producto_id"],
                "nombre": f["descripcion"],
                "unidades": int(f["unidades"] or 0),
                "total": _dinero(f["total"]),
            }
            for f in top
        ],
        "clientes": {
            "nuevos": cuentas.filter(creado_en__gte=desde).count(),
            "total": cuentas.count(),
            "compradores": ventas.values("cuenta_id").distinct().count(),
        },
        "cupones": {
            "usos": cupones["n"] or 0,
            "descontado": _dinero(cupones["monto"]),
            "activos": Cupon.objects.sin_ambito()
            .filter(organizacion_id=organizacion_id, activo=True)
            .count(),
        },
        "carrito_abandonado": carrito_abandonado.estadisticas(organizacion_id),
        "opiniones": {
            "nuevas": resenas.filter(creado_en__gte=desde).count(),
            "total": resenas.count(),
            "sin_respuesta": resenas.filter(respuesta="").count(),
        },
        "interes": {
            "favoritos": Favorito.objects.sin_ambito()
            .filter(organizacion_id=organizacion_id)
            .count(),
            "avisos_pendientes": AvisoDisponibilidad.objects.sin_ambito()
            .filter(organizacion_id=organizacion_id, avisado_en__isnull=True)
            .count(),
            "mas_pedidos": [
                {"id": f["producto_id"], "nombre": f["producto__nombre"], "personas": f["n"]}
                for f in interes
            ],
        },
        "atencion": {
            "por_verificar": pedidos.filter(estado=Estado.POR_VERIFICAR).count(),
            "con_problema": pedidos.filter(
                estado__in=[
                    Estado.PAGADO_SIN_COMPROBANTE,
                    Estado.PAGADO_FUERA_DE_PLAZO,
                    Estado.REEMBOLSO_PENDIENTE,
                ]
            ).count(),
            "por_atender": pedidos.filter(
                Q(estado=Estado.PAGADO) | Q(estado=Estado.ADELANTO_PAGADO)
            ).count(),
            "reclamos_pendientes": reclamos.count(),
            "reclamos_vencidos": reclamos.filter(vence_en__lt=ahora).count(),
        },
    }
