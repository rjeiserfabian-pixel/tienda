"""Reportes de ventas: resumen, por vendedor, producto, método de pago, cliente y registro.

Miden lo vendido por UNA empresa (cada comprobante es de una empresa). Las notas de crédito restan
en la fecha en que se emitieron. Soles y dólares nunca se suman. Los comprobantes anulados no
cuentan. El costo y la utilidad (en soles) solo se calculan si quien pide el reporte puede verlos.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.caja.reportes import DINERO, SIMBOLO, tabla_excel
from apps.core.models import DocumentoInmutable
from apps.organizacion.models import Empresa

from .exceptions import VentaInvalida
from .models import (
    AbonoVenta,
    CobroVenta,
    ComprobanteVenta,
    FormaPago,
    LineaNotaCredito,
    LineaVenta,
    NotaCredito,
    ReembolsoNota,
)

CERO = Decimal("0")
CIEN = Decimal("100")
MAX_DIAS = 732
MAX_FILAS_DETALLE = 500
EMITIDO = DocumentoInmutable.Estado.EMITIDO


def validar_rango(desde: date | None, hasta: date | None) -> tuple[date, date]:
    if desde is None or hasta is None:
        raise VentaInvalida("Indique el rango de fechas (desde y hasta).")
    if desde > hasta:
        raise VentaInvalida("La fecha «desde» no puede ser posterior a «hasta».")
    if (hasta - desde).days > MAX_DIAS:
        raise VentaInvalida("El rango no puede pasar de dos años.")
    return desde, hasta


def _comprobantes(empresa: Empresa, desde: date, hasta: date):
    return ComprobanteVenta.objects.filter(
        empresa=empresa, estado=EMITIDO, fecha__gte=desde, fecha__lte=hasta
    )


def _notas(empresa: Empresa, desde: date, hasta: date):
    return NotaCredito.objects.filter(
        empresa=empresa, estado=EMITIDO, fecha__gte=desde, fecha__lte=hasta
    )


def _vacio() -> dict:
    return {
        "cantidad": 0,
        "valor": CERO,
        "igv": CERO,
        "total": CERO,
        "notas": CERO,
        "contado": CERO,
        "credito": CERO,
        "costo": CERO,
        "utilidad": CERO,
    }


def _neto(g: dict) -> Decimal:
    return g["total"] - g["notas"]


def _utilidad_linea(valor: Decimal, tipo_cambio: Decimal, costo: Decimal) -> Decimal:
    return (valor * tipo_cambio).quantize(Decimal("0.01")) - costo


def _hechos(empresa: Empresa, desde: date, hasta: date) -> tuple[list[dict], list[dict]]:
    """Cada comprobante y cada nota del rango, como filas planas (con lo de su venta)."""
    comprobantes = [
        {
            "id": c["id"],
            "fecha": c["fecha"],
            "numero": f"{c['serie']}-{c['numero']:08d}",
            "tipo": c["tipo_comprobante__nombre"],
            "moneda": c["venta__moneda"],
            "tipo_cambio": c["venta__tipo_cambio"],
            "forma_pago": c["venta__forma_pago"],
            "vendedor": c["venta__vendedor_nombre"] or "Sin vendedor",
            "cliente": c["venta__cliente_nombre"] or "Clientes varios",
            "documento": c["venta__cliente_documento"],
            "valor": c["op_gravada"] + c["op_exonerada"] + c["op_inafecta"],
            "igv": c["igv"],
            "total": c["total"],
        }
        for c in _comprobantes(empresa, desde, hasta).values(
            "id",
            "fecha",
            "serie",
            "numero",
            "tipo_comprobante__nombre",
            "venta__moneda",
            "venta__tipo_cambio",
            "venta__forma_pago",
            "venta__vendedor_nombre",
            "venta__cliente_nombre",
            "venta__cliente_documento",
            "op_gravada",
            "op_exonerada",
            "op_inafecta",
            "igv",
            "total",
        )
    ]
    notas = [
        {
            "id": n["id"],
            "fecha": n["fecha"],
            "numero": f"{n['serie']}-{n['numero']:08d}",
            "tipo": n["tipo_comprobante__nombre"],
            "moneda": n["venta__moneda"],
            "tipo_cambio": n["venta__tipo_cambio"],
            "forma_pago": n["venta__forma_pago"],
            "vendedor": n["venta__vendedor_nombre"] or "Sin vendedor",
            "cliente": n["venta__cliente_nombre"] or "Clientes varios",
            "documento": n["venta__cliente_documento"],
            "valor": n["op_gravada"] + n["op_exonerada"] + n["op_inafecta"],
            "igv": n["igv"],
            "total": n["total"],
        }
        for n in _notas(empresa, desde, hasta).values(
            "id",
            "fecha",
            "serie",
            "numero",
            "tipo_comprobante__nombre",
            "venta__moneda",
            "venta__tipo_cambio",
            "venta__forma_pago",
            "venta__vendedor_nombre",
            "venta__cliente_nombre",
            "venta__cliente_documento",
            "op_gravada",
            "op_exonerada",
            "op_inafecta",
            "igv",
            "total",
        )
    ]
    return comprobantes, notas


def _costos(empresa: Empresa, desde: date, hasta: date) -> tuple[dict, dict]:
    """El costo vendido y el devuelto por comprobante y por nota (en soles)."""
    vendido: dict[int, Decimal] = defaultdict(lambda: CERO)
    for ln in LineaVenta.objects.filter(
        empresa=empresa,
        comprobante__estado=EMITIDO,
        comprobante__fecha__gte=desde,
        comprobante__fecha__lte=hasta,
    ).values("comprobante_id", "costo_total"):
        vendido[ln["comprobante_id"]] += ln["costo_total"]
    devuelto: dict[int, Decimal] = defaultdict(lambda: CERO)
    for ln in LineaNotaCredito.objects.filter(
        empresa=empresa,
        nota__estado=EMITIDO,
        nota__fecha__gte=desde,
        nota__fecha__lte=hasta,
    ).values("nota_id", "costo_total"):
        devuelto[ln["nota_id"]] += ln["costo_total"]
    return vendido, devuelto


def _agrupar(
    empresa: Empresa, desde: date, hasta: date, clave, *, con_utilidad: bool
) -> dict[tuple, dict]:
    """Suma comprobantes y resta notas por la clave dada (la moneda siempre va primero)."""
    comprobantes, notas = _hechos(empresa, desde, hasta)
    costo_c, costo_n = _costos(empresa, desde, hasta) if con_utilidad else ({}, {})
    grupos: dict[tuple, dict] = defaultdict(_vacio)
    for c in comprobantes:
        g = grupos[(c["moneda"], *clave(c))]
        g["cantidad"] += 1
        g["valor"] += c["valor"]
        g["igv"] += c["igv"]
        g["total"] += c["total"]
        g["credito" if c["forma_pago"] == FormaPago.CREDITO else "contado"] += c["total"]
        if con_utilidad:
            costo = costo_c.get(c["id"], CERO)
            g["costo"] += costo
            g["utilidad"] += _utilidad_linea(c["valor"], c["tipo_cambio"], costo)
    for n in notas:
        g = grupos[(n["moneda"], *clave(n))]
        g["notas"] += n["total"]
        if con_utilidad:
            costo = costo_n.get(n["id"], CERO)
            g["costo"] -= costo
            g["utilidad"] -= _utilidad_linea(n["valor"], n["tipo_cambio"], costo)
    return grupos


def _fila(g: dict, con_utilidad: bool) -> dict:
    fila = {
        "cantidad": g["cantidad"],
        "valor": g["valor"],
        "igv": g["igv"],
        "total": g["total"],
        "notas": g["notas"],
        "neto": _neto(g),
    }
    if con_utilidad:
        fila["costo"] = g["costo"]
        fila["utilidad"] = g["utilidad"]
    return fila


def resumen(empresa: Empresa, desde: date, hasta: date, *, con_utilidad: bool = False) -> dict:
    """Totales por moneda (contado y crédito aparte) y las ventas de cada mes."""
    desde, hasta = validar_rango(desde, hasta)
    grupos = _agrupar(
        empresa, desde, hasta, lambda h: (f"{h['fecha']:%Y-%m}",), con_utilidad=con_utilidad
    )
    totales: dict[str, dict] = defaultdict(_vacio)
    por_mes = []
    for (moneda, periodo), g in sorted(grupos.items()):
        t = totales[moneda]
        for campo in t:
            t[campo] += g[campo]
        por_mes.append({"periodo": periodo, "moneda": moneda, **_fila(g, con_utilidad)})
    return {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "totales": [
            {
                "moneda": moneda,
                "contado": t["contado"],
                "credito": t["credito"],
                **_fila(t, con_utilidad),
            }
            for moneda, t in sorted(totales.items())
        ],
        "por_mes": por_mes,
    }


def _ranking(
    empresa: Empresa, desde: date, hasta: date, clave, nombres: tuple[str, ...], con_utilidad: bool
) -> list[dict]:
    grupos = _agrupar(empresa, desde, hasta, clave, con_utilidad=con_utilidad)
    filas = [
        {**dict(zip(nombres, k[1:], strict=True)), "moneda": k[0], **_fila(g, con_utilidad)}
        for k, g in grupos.items()
        if g["cantidad"] or g["notas"]
    ]
    return sorted(filas, key=lambda f: (f["moneda"], -f["neto"], str(f[nombres[0]])))


def por_vendedor(empresa: Empresa, desde: date, hasta: date, *, con_utilidad: bool = False) -> dict:
    desde, hasta = validar_rango(desde, hasta)
    return {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "filas": _ranking(
            empresa, desde, hasta, lambda h: (h["vendedor"],), ("vendedor",), con_utilidad
        ),
    }


def por_cliente(empresa: Empresa, desde: date, hasta: date, *, con_utilidad: bool = False) -> dict:
    desde, hasta = validar_rango(desde, hasta)
    return {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "filas": _ranking(
            empresa,
            desde,
            hasta,
            lambda h: (h["cliente"], h["documento"]),
            ("cliente", "documento"),
            con_utilidad,
        ),
    }


def por_producto(empresa: Empresa, desde: date, hasta: date, *, con_utilidad: bool = False) -> dict:
    """Qué se vendió más: unidades, importe (sin IGV) y, si se puede ver, el margen."""
    desde, hasta = validar_rango(desde, hasta)
    grupos: dict[tuple[str, int], dict] = {}

    def grupo(moneda, producto_id, descripcion):
        return grupos.setdefault(
            (moneda, producto_id),
            {
                "producto": descripcion,
                "moneda": moneda,
                "unidades": CERO,
                "valor": CERO,
                "costo": CERO,
                "utilidad": CERO,
            },
        )

    for ln in LineaVenta.objects.filter(
        empresa=empresa,
        comprobante__estado=EMITIDO,
        comprobante__fecha__gte=desde,
        comprobante__fecha__lte=hasta,
    ).values(
        "producto_id",
        "descripcion",
        "cantidad",
        "valor_venta",
        "costo_total",
        "venta__moneda",
        "venta__tipo_cambio",
    ):
        g = grupo(ln["venta__moneda"], ln["producto_id"], ln["descripcion"])
        g["unidades"] += ln["cantidad"]
        g["valor"] += ln["valor_venta"]
        g["costo"] += ln["costo_total"]
        g["utilidad"] += _utilidad_linea(
            ln["valor_venta"], ln["venta__tipo_cambio"], ln["costo_total"]
        )
    for ln in LineaNotaCredito.objects.filter(
        empresa=empresa, nota__estado=EMITIDO, nota__fecha__gte=desde, nota__fecha__lte=hasta
    ).values(
        "linea_venta__producto_id",
        "linea_venta__descripcion",
        "cantidad",
        "valor_venta",
        "costo_total",
        "nota__venta__moneda",
        "nota__venta__tipo_cambio",
    ):
        g = grupo(
            ln["nota__venta__moneda"],
            ln["linea_venta__producto_id"],
            ln["linea_venta__descripcion"],
        )
        g["unidades"] -= ln["cantidad"]
        g["valor"] -= ln["valor_venta"]
        g["costo"] -= ln["costo_total"]
        g["utilidad"] -= _utilidad_linea(
            ln["valor_venta"], ln["nota__venta__tipo_cambio"], ln["costo_total"]
        )
    filas = []
    for g in sorted(grupos.values(), key=lambda g: (g["moneda"], -g["valor"], g["producto"])):
        fila = {
            "producto": g["producto"],
            "moneda": g["moneda"],
            "unidades": g["unidades"],
            "valor": g["valor"],
        }
        if con_utilidad:
            fila["costo"] = g["costo"]
            fila["utilidad"] = g["utilidad"]
            base = g["valor"]
            fila["margen"] = (
                (g["utilidad"] * CIEN / base).quantize(Decimal("0.1")) if base else CERO
            )
        filas.append(fila)
    return {"desde": desde, "hasta": hasta, "con_utilidad": con_utilidad, "filas": filas}


def por_metodo(empresa: Empresa, desde: date, hasta: date) -> dict:
    """Lo que entró y salió por cada método: ventas al contado, cuotas cobradas y devoluciones."""
    desde, hasta = validar_rango(desde, hasta)
    grupos: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"ventas": CERO, "cuotas": CERO, "devuelto": CERO}
    )
    cobros = (
        CobroVenta.objects.filter(
            empresa=empresa,
            comprobante__estado=EMITIDO,
            comprobante__fecha__gte=desde,
            comprobante__fecha__lte=hasta,
        )
        .values("venta__moneda", "medio_pago__nombre")
        .annotate(suma=Sum("monto"))
    )
    for c in cobros:
        grupos[(c["venta__moneda"], c["medio_pago__nombre"])]["ventas"] += c["suma"]
    abonos = (
        AbonoVenta.objects.filter(
            empresa=empresa, anulado=False, fecha__gte=desde, fecha__lte=hasta
        )
        .values("comprobante__venta__moneda", "medio_pago__nombre")
        .annotate(suma=Sum("monto"))
    )
    for a in abonos:
        grupos[(a["comprobante__venta__moneda"], a["medio_pago__nombre"])]["cuotas"] += a["suma"]
    devoluciones = (
        ReembolsoNota.objects.filter(
            empresa=empresa, nota__estado=EMITIDO, nota__fecha__gte=desde, nota__fecha__lte=hasta
        )
        .values("nota__venta__moneda", "medio_pago__nombre")
        .annotate(suma=Sum("monto"))
    )
    for d in devoluciones:
        grupos[(d["nota__venta__moneda"], d["medio_pago__nombre"])]["devuelto"] += d["suma"]
    filas = [
        {
            "metodo": metodo,
            "moneda": moneda,
            **g,
            "neto": g["ventas"] + g["cuotas"] - g["devuelto"],
        }
        for (moneda, metodo), g in grupos.items()
    ]
    filas.sort(key=lambda f: (f["moneda"], -f["neto"], f["metodo"]))
    return {"desde": desde, "hasta": hasta, "filas": filas}


def registro(
    empresa: Empresa,
    desde: date,
    hasta: date,
    *,
    con_utilidad: bool = False,
    limite: int | None = MAX_FILAS_DETALLE,
) -> dict:
    """Registro de ventas: cada comprobante y cada nota de crédito (en negativo), por fecha."""
    desde, hasta = validar_rango(desde, hasta)
    comprobantes, notas = _hechos(empresa, desde, hasta)
    costo_c, costo_n = _costos(empresa, desde, hasta) if con_utilidad else ({}, {})
    filas = []
    for signo, grupo, costos in ((1, comprobantes, costo_c), (-1, notas, costo_n)):
        for h in grupo:
            fila = {
                "fecha": h["fecha"],
                "numero": h["numero"],
                "tipo": h["tipo"],
                "cliente": h["cliente"],
                "documento": h["documento"],
                "vendedor": h["vendedor"],
                "forma_pago": h["forma_pago"],
                "moneda": h["moneda"],
                "valor": signo * h["valor"],
                "igv": signo * h["igv"],
                "total": signo * h["total"],
            }
            if con_utilidad:
                costo = costos.get(h["id"], CERO)
                fila["costo"] = signo * costo
                fila["utilidad"] = signo * _utilidad_linea(h["valor"], h["tipo_cambio"], costo)
            filas.append(fila)
    filas.sort(key=lambda f: (f["fecha"], f["numero"]), reverse=True)
    return {
        "desde": desde,
        "hasta": hasta,
        "con_utilidad": con_utilidad,
        "total_filas": len(filas),
        "truncado": limite is not None and len(filas) > limite,
        "filas": filas if limite is None else filas[:limite],
    }


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _subtitulo(datos: dict) -> str:
    return f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} (sin IGV salvo «Total»)"


def _celdas_dinero(fila: dict, campos: list[str]) -> list[tuple]:
    return [(fila[c], DINERO) for c in campos]


def _titulos_dinero(datos: dict) -> tuple[list[str], list[str]]:
    titulos = ["Ventas sin IGV", "IGV", "Total", "Notas de crédito", "Neto"]
    campos = ["valor", "igv", "total", "notas", "neto"]
    if datos["con_utilidad"]:
        titulos += ["Costo", "Utilidad (S/)"]
        campos += ["costo", "utilidad"]
    return titulos, campos


def resumen_excel(empresa: Empresa, datos: dict) -> bytes:
    titulos, campos = _titulos_dinero(datos)
    return tabla_excel(
        empresa,
        hoja="Resumen",
        titulo="RESUMEN DE VENTAS POR MES",
        subtitulo=_subtitulo(datos),
        titulos=["Mes", "Moneda", "Comprobantes", *titulos],
        filas=[
            [(f["periodo"], None), (SIMBOLO[f["moneda"]], None), (f["cantidad"], None)]
            + _celdas_dinero(f, campos)
            for f in datos["por_mes"]
        ],
        totales=[
            [("TOTAL", None), (SIMBOLO[t["moneda"]], None), (t["cantidad"], None)]
            + _celdas_dinero(t, campos)
            for t in datos["totales"]
        ],
        anchos=[12, 9, 14, *([16] * len(titulos))],
    )


def _ranking_excel(empresa: Empresa, datos: dict, hoja: str, titulo: str, columnas: list[tuple]):
    titulos, campos = _titulos_dinero(datos)
    return tabla_excel(
        empresa,
        hoja=hoja,
        titulo=titulo,
        subtitulo=_subtitulo(datos),
        titulos=[c[1] for c in columnas] + ["Moneda", "Comprobantes", *titulos],
        filas=[
            [(f[c[0]], None) for c in columnas]
            + [(SIMBOLO[f["moneda"]], None), (f["cantidad"], None)]
            + _celdas_dinero(f, campos)
            for f in datos["filas"]
        ],
        anchos=[34] * len(columnas) + [9, 14, *([16] * len(titulos))],
    )


def vendedores_excel(empresa: Empresa, datos: dict) -> bytes:
    return _ranking_excel(
        empresa, datos, "Por vendedor", "VENTAS POR VENDEDOR", [("vendedor", "Vendedor")]
    )


def clientes_excel(empresa: Empresa, datos: dict) -> bytes:
    return _ranking_excel(
        empresa,
        datos,
        "Por cliente",
        "VENTAS POR CLIENTE",
        [("cliente", "Cliente"), ("documento", "Documento")],
    )


def productos_excel(empresa: Empresa, datos: dict) -> bytes:
    titulos = ["Unidades", "Ventas sin IGV"]
    campos = ["unidades", "valor"]
    if datos["con_utilidad"]:
        titulos += ["Costo", "Utilidad (S/)", "Margen %"]
        campos += ["costo", "utilidad", "margen"]
    return tabla_excel(
        empresa,
        hoja="Por producto",
        titulo="VENTAS POR PRODUCTO",
        subtitulo=_subtitulo(datos),
        titulos=["Producto", "Moneda", *titulos],
        filas=[
            [(f["producto"], None), (SIMBOLO[f["moneda"]], None)]
            + [(f[c], None if c in {"unidades", "margen"} else DINERO) for c in campos]
            for f in datos["filas"]
        ],
        anchos=[44, 9, *([16] * len(titulos))],
    )


def metodos_excel(empresa: Empresa, datos: dict) -> bytes:
    return tabla_excel(
        empresa,
        hoja="Por método de pago",
        titulo="COBROS POR MÉTODO DE PAGO",
        subtitulo=_subtitulo(datos),
        titulos=["Método", "Moneda", "Ventas al contado", "Cuotas cobradas", "Devuelto", "Neto"],
        filas=[
            [(f["metodo"], None), (SIMBOLO[f["moneda"]], None)]
            + _celdas_dinero(f, ["ventas", "cuotas", "devuelto", "neto"])
            for f in datos["filas"]
        ],
        anchos=[30, 9, 18, 18, 16, 16],
    )


def registro_excel(empresa: Empresa, datos: dict) -> bytes:
    campos = ["valor", "igv", "total"]
    titulos = ["Sin IGV", "IGV", "Total"]
    if datos["con_utilidad"]:
        campos += ["costo", "utilidad"]
        titulos += ["Costo", "Utilidad (S/)"]
    return tabla_excel(
        empresa,
        hoja="Registro de ventas",
        titulo="REGISTRO DE VENTAS",
        subtitulo=_subtitulo(datos),
        titulos=[
            "Fecha",
            "Comprobante",
            "Tipo",
            "Cliente",
            "Documento",
            "Vendedor",
            "Pago",
            "Moneda",
            *titulos,
        ],
        filas=[
            [
                (f["fecha"], "dd/mm/yyyy"),
                (f["numero"], None),
                (f["tipo"], None),
                (f["cliente"], None),
                (f["documento"], None),
                (f["vendedor"], None),
                ("Crédito" if f["forma_pago"] == FormaPago.CREDITO else "Contado", None),
                (SIMBOLO[f["moneda"]], None),
            ]
            + _celdas_dinero(f, campos)
            for f in datos["filas"]
        ],
        anchos=[12, 16, 18, 34, 14, 22, 10, 9, *([14] * len(titulos))],
    )


def notas_credito_excel(
    empresa: Empresa, notas: list[dict], desde: date | None, hasta: date | None
) -> bytes:
    """El listado de notas de crédito tal como se filtró en pantalla, con el total por moneda."""
    periodo = (f"Del {desde:%d/%m/%Y} " if desde else "Desde el inicio ") + (
        f"al {hasta:%d/%m/%Y}" if hasta else "hasta hoy"
    )
    totales: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"total": Decimal("0"), "asociado": Decimal("0"), "reembolsado": Decimal("0")}
    )
    for n in notas:
        for campo in ("total", "asociado", "reembolsado"):
            totales[n["moneda"]][campo] += n[campo]
    return tabla_excel(
        empresa,
        hoja="Notas de crédito",
        titulo="NOTAS DE CRÉDITO",
        subtitulo=periodo,
        titulos=[
            "Fecha",
            "Nota de crédito",
            "Usuario",
            "Cliente",
            "RUC/DNI",
            "Comprobante que modifica",
            "Fecha del comprobante",
            "Motivo",
            "Moneda",
            "Total",
            "Asociado (descontado de la deuda)",
            "Pendiente de cobro",
            "Devuelto en dinero",
        ],
        filas=[
            [
                (n["fecha"], "dd/mm/yyyy"),
                (n["numero"], None),
                (n["usuario"], None),
                (n["cliente"], None),
                (n["documento"], None),
                (n["comprobante"], None),
                (n["fecha_comprobante"], "dd/mm/yyyy"),
                (n["motivo"], None),
                (SIMBOLO[n["moneda"]], None),
                (n["total"], DINERO),
                (n["asociado"], DINERO),
                (n["pendiente"], DINERO),
                (n["reembolsado"], DINERO),
            ]
            for n in notas
        ],
        totales=[
            [("TOTAL", None)]
            + [("", None)] * 7
            + [
                (SIMBOLO[moneda], None),
                (t["total"], DINERO),
                (t["asociado"], DINERO),
                ("", None),
                (t["reembolsado"], DINERO),
            ]
            for moneda, t in sorted(totales.items())
        ],
        anchos=[12, 17, 22, 34, 14, 20, 14, 24, 9, 14, 18, 16, 16],
    )


def guias_excel(
    empresa: Empresa, guias: list[dict], desde: date | None, hasta: date | None
) -> bytes:
    """El listado de guías de remisión tal como se filtró en pantalla."""
    periodo = (f"Del {desde:%d/%m/%Y} " if desde else "Desde el inicio ") + (
        f"al {hasta:%d/%m/%Y}" if hasta else "hasta hoy"
    )
    return tabla_excel(
        empresa,
        hoja="Guías de remisión",
        titulo="GUÍAS DE REMISIÓN",
        subtitulo=periodo,
        titulos=[
            "Emisión",
            "Guía",
            "Usuario",
            "Destinatario",
            "RUC/DNI",
            "Comprobante",
            "Motivo",
            "Traslado",
            "Transporte",
            "Transportista",
            "Conductor",
            "Placa",
            "Punto de partida",
            "Punto de llegada",
            "Bultos",
            "Peso (kg)",
            "Estado",
        ],
        filas=[
            [
                (g["fecha"], "dd/mm/yyyy"),
                (g["numero"], None),
                (g["usuario"], None),
                (g["destinatario"], None),
                (g["documento"], None),
                (g["comprobante"], None),
                (g["motivo"], None),
                (g["traslado"], "dd/mm/yyyy"),
                (g["transporte"], None),
                (g["transportista"], None),
                (g["conductor"], None),
                (g["placa"], None),
                (g["partida"], None),
                (g["llegada"], None),
                (g["bultos"], None),
                (g["peso"], "#,##0.000"),
                (g["estado"], None),
            ]
            for g in guias
        ],
        anchos=[12, 17, 20, 32, 14, 17, 12, 12, 11, 28, 24, 10, 34, 34, 8, 11, 10],
    )
