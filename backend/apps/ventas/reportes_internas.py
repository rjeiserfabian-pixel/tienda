"""Reportes de la venta interna: lo que pasó entre las empresas y el total de las dos sin duplicar.

* **Ventas internas**: cada traslado de mercadería de una empresa a la otra (al costo), si ya
  volvió algo por devoluciones y si ya se liquidó; y cuánto de lo que una vendió al cliente salió
  del stock de la otra, con su utilidad.
* **Consolidado**: lo vendido por cada empresa a sus clientes y el total de las dos. La venta
  interna NO suma: no es una venta al cliente sino la misma mercadería pasando de una empresa a la
  otra. Lo vendido al cliente se cuenta una sola vez, en la empresa que emitió el comprobante.

Solo cuentan los documentos emitidos; los anulados se muestran aparte. El costo y la utilidad (en
soles) salen solo para quien puede verlos.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.caja.reportes import DINERO, FECHA, SIMBOLO, tabla_excel
from apps.core.models import DocumentoInmutable
from apps.organizacion.models import Empresa, Estado

from . import liquidacion_interna
from .models import LineaNotaCredito, LineaVenta, LiquidacionInterna, VentaInterna
from .reportes import MAX_FILAS_DETALLE, resumen, validar_rango

CERO = Decimal("0")
CENTIMO = Decimal("0.01")
EMITIDO = DocumentoInmutable.Estado.EMITIDO
ANULADO = DocumentoInmutable.Estado.ANULADO


def _nombre(empresa: Empresa) -> str:
    return empresa.nombre_comercial or empresa.razon_social


def estado_de_devolucion(total: Decimal, devuelto: Decimal) -> str:
    """Cuánto de lo trasladado ya volvió a quien lo entregó: NINGUNA, PARCIAL o TOTAL."""
    if devuelto <= 0:
        return "NINGUNA"
    return "TOTAL" if devuelto >= total else "PARCIAL"


def _liquidacion_de(interna: VentaInterna) -> str:
    """Si la deuda que dejó la venta ya se liquidó (y en cuál) o sigue pendiente."""
    if interna.estado == ANULADO:
        return ""
    partida = next((p for p in interna.partidas.all() if p.motivo == "VENTA"), None)
    if partida is None:
        return ""
    if partida.liquidacion is None:
        return "Pendiente"
    return f"Liquidada N° {partida.liquidacion.numero:06d}"


def _comprobante_de(interna: VentaInterna) -> str:
    """El comprobante que emitió la empresa que facturó con esta mercadería."""
    for c in interna.venta.comprobantes.all():
        if c.empresa_id == interna.empresa_destino_id:
            return c.numero_completo
    return ""


def _soles(valor: Decimal, tipo_cambio: Decimal) -> Decimal:
    return (valor * tipo_cambio).quantize(CENTIMO)


def _con_mercaderia_de_la_otra(
    empresa: Empresa, desde: date, hasta: date, con_utilidad: bool
) -> dict:
    """Lo que ``empresa`` vendió al cliente con mercadería que le pasó la otra (en soles).

    Como en los demás reportes, las notas de crédito restan en la fecha en que se emitieron.
    """
    lineas = LineaVenta.objects.filter(
        empresa=empresa,
        comprobante__estado=EMITIDO,
        comprobante__fecha__gte=desde,
        comprobante__fecha__lte=hasta,
        origen_interno__venta_interna__estado=EMITIDO,
    ).values("valor_venta", "costo_total", "venta__tipo_cambio")
    notas = LineaNotaCredito.objects.filter(
        empresa=empresa,
        nota__estado=EMITIDO,
        nota__fecha__gte=desde,
        nota__fecha__lte=hasta,
        linea_venta__origen_interno__venta_interna__estado=EMITIDO,
    ).values("valor_venta", "costo_total", "nota__venta__tipo_cambio")
    vendido = devuelto = costo = CERO
    cantidad = 0
    for ln in lineas:
        cantidad += 1
        vendido += _soles(ln["valor_venta"], ln["venta__tipo_cambio"])
        costo += ln["costo_total"]
    for ln in notas:
        devuelto += _soles(ln["valor_venta"], ln["nota__venta__tipo_cambio"])
        costo -= ln["costo_total"]
    neto = vendido - devuelto
    datos = {"lineas": cantidad, "vendido": vendido, "devuelto": devuelto, "neto": neto}
    if con_utilidad:
        datos["costo"] = costo
        datos["utilidad"] = neto - costo
    return datos


def ventas_internas(
    empresa: Empresa,
    desde: date,
    hasta: date,
    *,
    con_utilidad: bool = False,
    limite: int | None = MAX_FILAS_DETALLE,
) -> dict:
    """Los traslados de mercadería entre las empresas en que participó ``empresa``."""
    desde, hasta = validar_rango(desde, hasta)
    internas = (
        VentaInterna.objects.filter(fecha__gte=desde, fecha__lte=hasta, venta__isnull=False)
        .filter(Q(empresa=empresa) | Q(empresa_destino=empresa))
        .select_related("empresa", "empresa_destino", "venta")
        .prefetch_related("lineas", "devoluciones", "partidas__liquidacion", "venta__comprobantes")
        .order_by("-fecha", "-id")
    )
    totales = {
        "entregado": {"cantidad": 0, "costo": CERO, "devuelto": CERO},
        "recibido": {"cantidad": 0, "costo": CERO, "devuelto": CERO},
        "anuladas": {"cantidad": 0, "costo": CERO},
    }
    filas = []
    for i in internas:
        entrega = i.empresa_id == empresa.pk
        total_cantidad = sum((ln.cantidad for ln in i.lineas.all()), CERO)
        devuelto_cantidad = sum((d.cantidad for d in i.devoluciones.all()), CERO)
        devuelto = sum((d.costo_total for d in i.devoluciones.all()), CERO)
        if i.estado == EMITIDO:
            bloque = totales["entregado" if entrega else "recibido"]
            bloque["cantidad"] += 1
            bloque["costo"] += i.total_costo
            bloque["devuelto"] += devuelto
        else:
            totales["anuladas"]["cantidad"] += 1
            totales["anuladas"]["costo"] += i.total_costo
        fila = {
            "fecha": i.fecha,
            "numero": f"{i.numero:06d}",
            "rol": "ENTREGA" if entrega else "RECIBE",
            "entrega": _nombre(i.empresa),
            "recibe": _nombre(i.empresa_destino),
            "venta": f"{i.venta.numero:06d}",
            "comprobante": _comprobante_de(i),
            "documento": i.get_documento_display(),
            "estado": i.estado,
            "devolucion": estado_de_devolucion(total_cantidad, devuelto_cantidad),
            "liquidacion": _liquidacion_de(i),
        }
        if con_utilidad:
            fila["costo"] = i.total_costo
            fila["devuelto"] = devuelto
        filas.append(fila)

    for bloque in (totales["entregado"], totales["recibido"]):
        bloque["neto"] = bloque["costo"] - bloque["devuelto"]
    resultado = {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "empresa": empresa.pk,
        "empresa_nombre": _nombre(empresa),
        "total_filas": len(filas),
        "truncado": limite is not None and len(filas) > limite,
        "totales": totales,
        "con_mercaderia_de_la_otra": _con_mercaderia_de_la_otra(
            empresa, desde, hasta, con_utilidad
        ),
        "filas": filas if limite is None else filas[:limite],
    }
    if con_utilidad:
        resultado["por_liquidar"] = [
            {
                "pagadora": _nombre(p.pagadora),
                "receptora": _nombre(p.receptora),
                "monto": p.monto,
            }
            for p in liquidacion_interna.pendientes(empresa.organizacion_id)
            if empresa.pk in (p.pagadora.pk, p.receptora.pk)
        ]
    else:
        # Sin permiso de costos tampoco se ven los importes: solo cuántas operaciones hubo.
        for bloque in (totales["entregado"], totales["recibido"]):
            for campo in ("costo", "devuelto", "neto"):
                bloque.pop(campo, None)
        totales["anuladas"].pop("costo", None)
    return resultado


def consolidado(empresa: Empresa, desde: date, hasta: date, *, con_utilidad: bool = False) -> dict:
    """Lo vendido por cada empresa de la organización y el total de todas, sin duplicar."""
    desde, hasta = validar_rango(desde, hasta)
    empresas = list(
        Empresa.objects.filter(
            organizacion_id=empresa.organizacion_id, estado=Estado.ACTIVO
        ).order_by("-es_principal", "id")
    )
    por_empresa = []
    suma: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: CERO))
    for e in empresas:
        datos = resumen(e, desde, hasta, con_utilidad=con_utilidad)
        por_empresa.append({"empresa": e.pk, "nombre": _nombre(e), "totales": datos["totales"]})
        for t in datos["totales"]:
            acumulado = suma[t["moneda"]]
            for campo, valor in t.items():
                if campo != "moneda":
                    acumulado[campo] += valor
    internas = VentaInterna.objects.filter(fecha__gte=desde, fecha__lte=hasta, estado=EMITIDO)
    costo_interno = sum((i.total_costo for i in internas), CERO)
    return {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "empresas": por_empresa,
        "totales": [{"moneda": m, **dict(t)} for m, t in sorted(suma.items())],
        # Informativo: NO está sumado arriba. Es mercadería que pasó de una empresa a la otra.
        "ventas_internas": {
            "cantidad": internas.count(),
            **({"costo": costo_interno} if con_utilidad else {}),
        },
    }


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
_DEVOLUCION = {"NINGUNA": "", "PARCIAL": "Parcial", "TOTAL": "Total"}


def ventas_internas_excel(empresa: Empresa, datos: dict) -> bytes:
    con = datos["con_utilidad"]
    titulos = [
        "Fecha",
        "N° venta interna",
        "Entrega",
        "Recibe",
        "Venta N°",
        "Comprobante",
        "Respaldo",
        "Estado",
        "Devuelto a quien entregó",
        "Liquidación",
    ]
    if con:
        titulos += ["Costo trasladado (S/)", "Devuelto (S/)"]
    filas = []
    for f in datos["filas"]:
        celdas = [
            (f["fecha"], FECHA),
            (f["numero"], None),
            (f["entrega"], None),
            (f["recibe"], None),
            (f["venta"], None),
            (f["comprobante"], None),
            (f["documento"], None),
            ("Anulada" if f["estado"] == ANULADO else "Vigente", None),
            (_DEVOLUCION[f["devolucion"]], None),
            (f["liquidacion"], None),
        ]
        if con:
            celdas += [(f["costo"], DINERO), (f["devuelto"], DINERO)]
        filas.append(celdas)
    totales = []
    if con:
        for clave, texto in (("entregado", "ENTREGADO"), ("recibido", "RECIBIDO")):
            t = datos["totales"][clave]
            totales.append(
                [(f"{texto} (neto de devoluciones)", None)]
                + [(None, None)] * 9
                + [(t["costo"], DINERO), (t["devuelto"], DINERO)]
            )
    return tabla_excel(
        empresa,
        hoja="Ventas internas",
        titulo="VENTAS INTERNAS ENTRE LAS EMPRESAS",
        subtitulo=(
            f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} (al costo, en soles)"
        ),
        titulos=titulos,
        filas=filas,
        totales=totales,
        anchos=[12, 12, 24, 24, 10, 18, 18, 10, 14, 20, 16, 16],
    )


def liquidacion_excel(liquidacion: LiquidacionInterna) -> bytes:
    """El informe de una liquidación: cada partida que se saldó y lo que quedó a pagar."""
    partidas = list(
        liquidacion.partidas.select_related("empresa", "acreedora", "venta_interna").order_by(
            "fecha", "id"
        )
    )
    transferencia = liquidacion.transferencia
    recorrido = (
        f" · de «{transferencia.cuenta_origen.nombre}» a «{transferencia.cuenta_destino.nombre}»"
        if transferencia
        else " · las deudas se compensaron: no hubo dinero que mover"
    )
    estado = " · ANULADA" if liquidacion.estado == ANULADO else ""
    return tabla_excel(
        liquidacion.empresa,
        hoja="Liquidación",
        titulo=f"LIQUIDACIÓN ENTRE EMPRESAS N° {liquidacion.numero:06d}",
        subtitulo=(
            f"{_nombre(liquidacion.empresa)} paga a {_nombre(liquidacion.empresa_destino)} · "
            f"{liquidacion.fecha:%d/%m/%Y}{recorrido}{estado}"
        ),
        titulos=[
            "Fecha",
            "Qué pasó",
            "Venta interna N° / Pedido",
            "Debe",
            "A favor de",
            "Monto (S/)",
        ],
        filas=[
            [
                (p.fecha, FECHA),
                (p.get_motivo_display(), None),
                (
                    f"{p.venta_interna.numero:06d}" if p.venta_interna_id else p.referencia,
                    None,
                ),
                (_nombre(p.empresa), None),
                (_nombre(p.acreedora), None),
                (p.monto, DINERO),
            ]
            for p in partidas
        ],
        totales=[
            [("A PAGAR (neto, ya compensado)", None)]
            + [(None, None)] * 4
            + [(liquidacion.monto, DINERO)]
        ],
        anchos=[12, 26, 16, 24, 24, 16],
    )


def consolidado_excel(empresa: Empresa, datos: dict) -> bytes:
    con = datos["con_utilidad"]
    campos = ["valor", "igv", "total", "notas", "neto"]
    titulos_dinero = ["Ventas sin IGV", "IGV", "Total", "Notas de crédito", "Neto"]
    if con:
        campos += ["costo", "utilidad"]
        titulos_dinero += ["Costo", "Utilidad (S/)"]
    filas = []
    for e in datos["empresas"]:
        for t in e["totales"]:
            filas.append(
                [(e["nombre"], None), (SIMBOLO[t["moneda"]], None), (t["cantidad"], None)]
                + [(t[c], DINERO) for c in campos]
            )
    totales = [
        [("TOTAL DE LAS EMPRESAS", None), (SIMBOLO[t["moneda"]], None), (t["cantidad"], None)]
        + [(t[c], DINERO) for c in campos]
        for t in datos["totales"]
    ]
    return tabla_excel(
        empresa,
        hoja="Consolidado",
        titulo="VENTAS CONSOLIDADAS DE LAS EMPRESAS",
        subtitulo=(
            f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} "
            "(lo vendido a clientes; las ventas internas entre empresas no suman)"
        ),
        titulos=["Empresa", "Moneda", "Comprobantes", *titulos_dinero],
        filas=filas,
        totales=totales,
        anchos=[30, 9, 14, *([16] * len(titulos_dinero))],
    )
