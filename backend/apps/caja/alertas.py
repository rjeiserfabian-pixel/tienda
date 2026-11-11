"""Avisos de caja y bancos: lo que la persona debería mirar hoy.

Cada aviso trae su nivel (``critica`` pide acción ya, ``aviso`` conviene revisarlo, ``info`` es
para estar al tanto), un título, el detalle y la pantalla donde se resuelve. Se calculan al
consultar: no se guardan, así no quedan avisos viejos que ya no aplican.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Q
from django.utils import timezone

from apps.mantenimiento.models import EstadoRegistro
from apps.organizacion.models import Empresa

from . import bancarizacion, cheques, servicios
from .models import EstadoCuenta, SesionCaja

HORAS_SESION_LARGA = 18
DIAS_EXTRACTO_ABIERTO = 7
DIAS_BANCARIZACION = 30
SIMBOLO = {"PEN": "S/", "USD": "US$"}


def _dinero(valor: Decimal, moneda: str) -> str:
    return f"{SIMBOLO[moneda]} {valor:,.2f}"


def _aviso(codigo, nivel, titulo, detalle, enlace):
    return {
        "codigo": codigo,
        "nivel": nivel,
        "titulo": titulo,
        "detalle": detalle,
        "enlace": enlace,
    }


def alertas(empresa: Empresa) -> list[dict]:
    ahora = timezone.now()
    hoy = timezone.localdate()
    avisos = []

    for fila in servicios.saldos_de_la_empresa(empresa):
        cuenta, saldo = fila["cuenta"], fila["saldo"]
        if cuenta.estado != EstadoRegistro.ACTIVO:
            continue
        enlace = f"/caja/movimientos?cuenta={cuenta.pk}"
        if saldo < 0:
            avisos.append(
                _aviso(
                    "saldo_negativo",
                    "critica",
                    f"{cuenta.nombre} tiene saldo negativo",
                    f"Dice {_dinero(saldo, cuenta.moneda)}: faltan ingresos o hay egresos de más.",
                    enlace,
                )
            )
        elif cuenta.saldo_minimo is not None and saldo < cuenta.saldo_minimo:
            avisos.append(
                _aviso(
                    "saldo_bajo",
                    "aviso",
                    f"{cuenta.nombre} está por debajo de su mínimo",
                    f"Hay {_dinero(saldo, cuenta.moneda)} y el mínimo es "
                    f"{_dinero(cuenta.saldo_minimo, cuenta.moneda)}.",
                    enlace,
                )
            )

    largas = SesionCaja.objects.filter(
        empresa=empresa,
        estado=SesionCaja.Estado.ABIERTA,
        abierta_en__lt=ahora - timedelta(hours=HORAS_SESION_LARGA),
    ).select_related("cuenta")
    for sesion in largas:
        avisos.append(
            _aviso(
                "sesion_larga",
                "aviso",
                f"{sesion.cuenta.nombre} sigue abierta",
                f"Abierta por {sesion.responsable_nombre} el {sesion.abierta_en:%d/%m %H:%M}. "
                "Cuenta el efectivo y ciérrala.",
                "/caja/sesiones",
            )
        )

    viejos = (
        EstadoCuenta.objects.filter(
            empresa=empresa,
            estado=EstadoCuenta.Estado.ABIERTO,
            creado_en__lt=ahora - timedelta(days=DIAS_EXTRACTO_ABIERTO),
        )
        .annotate(pendientes=Count("lineas", filter=Q(lineas__movimiento=None)))
        .filter(pendientes__gt=0)
        .select_related("cuenta")
    )
    for extracto in viejos:
        avisos.append(
            _aviso(
                "extracto_sin_conciliar",
                "aviso",
                f"Falta conciliar el estado de cuenta de {extracto.cuenta.nombre}",
                f"{extracto.pendientes} líneas del banco siguen sin explicar desde "
                f"el {extracto.creado_en:%d/%m}.",
                f"/caja/conciliacion/{extracto.pk}",
            )
        )

    desde = hoy - timedelta(days=DIAS_BANCARIZACION)
    efectivo = list(bancarizacion.sin_bancarizar(empresa, desde, hoy))
    if efectivo:
        monedas = sorted({m.cuenta.moneda for m in efectivo})
        limites = " o ".join(_dinero(bancarizacion.UMBRALES[m], m) for m in monedas)
        avisos.append(
            _aviso(
                "sin_bancarizar",
                "aviso",
                f"{len(efectivo)} operaciones grandes en efectivo",
                f"En los últimos {DIAS_BANCARIZACION} días hubo pagos o cobros desde {limites} "
                "en efectivo. Pueden exigir un medio de pago bancarizado.",
                "/caja/reportes",
            )
        )

    cheq = cheques.resumen_de_avisos(empresa, hoy)
    if cheq["vencidos"]:
        avisos.append(
            _aviso(
                "cheques_vencidos",
                "critica",
                f"{cheq['vencidos']} cheques recibidos ya pasaron su plazo",
                "Pasaron 30 días desde su fecha y siguen sin cobrar: pueden perder validez.",
                "/caja/cheques?vencidos=1",
            )
        )
    if cheq["por_vencer"]:
        avisos.append(
            _aviso(
                "cheques_por_vencer",
                "aviso",
                f"{cheq['por_vencer']} cheques recibidos vencen pronto",
                f"Vencen en los próximos {cheques.DIAS_AVISO} días: deposítalos.",
                "/caja/cheques?estado=EN_CARTERA",
            )
        )
    if cheq["emitidos_sin_cobrar"]:
        avisos.append(
            _aviso(
                "cheques_sin_cobrar",
                "info",
                f"{cheq['emitidos_sin_cobrar']} cheques girados siguen sin cobrar",
                f"Llevan más de {cheques.DIAS_EMITIDO_SIN_COBRAR} días: confirma con el proveedor.",
                "/caja/cheques?tipo=EMITIDO",
            )
        )

    # Las cuotas vencidas son de Compras: caja solo las muestra.
    from apps.compras.models import CuotaCompra

    vencidas = CuotaCompra.objects.filter(
        empresa=empresa,
        compra__estado="EMITIDO",
        pagado__lt=F("monto"),
        fecha_vencimiento__lt=hoy,
    ).count()
    if vencidas:
        avisos.append(
            _aviso(
                "cuotas_vencidas",
                "info",
                f"{vencidas} cuotas a proveedores ya vencieron",
                "Revisa cuáles pagar para no atrasarte.",
                "/compras/por-pagar",
            )
        )

    from apps.compras.models import OrdenCompra

    atrasadas_oc = OrdenCompra.objects.filter(
        empresa=empresa,
        estado__in=(OrdenCompra.Estado.EMITIDA, OrdenCompra.Estado.PARCIAL),
        fecha_entrega__lt=hoy,
    ).count()
    if atrasadas_oc:
        avisos.append(
            _aviso(
                "ordenes_atrasadas",
                "aviso",
                f"{atrasadas_oc} órdenes de compra ya pasaron su fecha de entrega",
                "Mercadería que pediste y todavía no llega. Revisa con el proveedor.",
                "/compras/ordenes?atrasadas=1",
            )
        )
    por_aprobar = OrdenCompra.objects.filter(
        empresa=empresa, estado=OrdenCompra.Estado.PENDIENTE
    ).count()
    if por_aprobar:
        avisos.append(
            _aviso(
                "ordenes_por_aprobar",
                "info",
                f"{por_aprobar} órdenes de compra esperan aprobación",
                "Por su monto necesitan que un administrador las apruebe.",
                "/compras/ordenes?estado=PENDIENTE",
            )
        )

    from apps.gastos.consultas import por_pagar

    gastos_vencidos = por_pagar(empresa, hoy - timedelta(days=1)).count()
    if gastos_vencidos:
        avisos.append(
            _aviso(
                "gastos_vencidos",
                "aviso",
                f"{gastos_vencidos} gastos por pagar ya vencieron",
                "Luz, alquiler u otros gastos que pasaron su fecha de pago.",
                "/gastos/registro?pago=vencido",
            )
        )

    from apps.gastos.consultas import recurrentes_por_registrar

    por_registrar = recurrentes_por_registrar(empresa, hoy)
    if por_registrar:
        atrasados = sum(1 for r in por_registrar if r.proxima_fecha < hoy)
        avisos.append(
            _aviso(
                "gastos_recurrentes",
                "aviso" if atrasados else "info",
                f"{len(por_registrar)} gastos recurrentes por registrar",
                (f"{atrasados} ya pasaron su fecha. " if atrasados else "Les toca pronto: ")
                + ", ".join(r.nombre for r in por_registrar[:3])
                + ("…" if len(por_registrar) > 3 else "."),
                "/gastos/recurrentes",
            )
        )

    orden = {"critica": 0, "aviso": 1, "info": 2}
    return sorted(avisos, key=lambda a: (orden[a["nivel"]], a["titulo"]))
