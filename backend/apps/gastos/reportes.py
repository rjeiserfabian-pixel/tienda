"""Reportes de gastos: por categoría y mes, por proveedor y los que no tienen comprobante.

Todos miden el COSTO de la empresa: lo que le toca asumir. Un gasto que solo es de la empresa cuenta
completo; uno repartido cuenta, para cada empresa, la parte que le toca (aunque lo haya registrado
otra). Soles y dólares nunca se suman. Los gastos anulados no cuentan.
"""

from datetime import date
from decimal import Decimal

from apps.caja.reportes import DINERO, SIMBOLO, tabla_excel
from apps.organizacion.models import Empresa

from .exceptions import GastoInvalido
from .models import Gasto, GastoReparto

CERO = Decimal("0")
MAX_DIAS = 732
MAX_FILAS_DETALLE = 500


def validar_rango(desde: date | None, hasta: date | None) -> tuple[date, date]:
    if desde is None or hasta is None:
        raise GastoInvalido("Indique el rango de fechas (desde y hasta).")
    if desde > hasta:
        raise GastoInvalido("La fecha «desde» no puede ser posterior a «hasta».")
    if (hasta - desde).days > MAX_DIAS:
        raise GastoInvalido("El rango no puede pasar de dos años.")
    return desde, hasta


def costos(empresa: Empresa, desde: date, hasta: date) -> list[dict]:
    """Una fila por gasto (o parte de gasto) que le toca a la empresa en el rango."""
    base = Gasto.objects.filter(estado=Gasto.Estado.EMITIDO, fecha__gte=desde, fecha__lte=hasta)
    campos = (
        "id",
        "numero",
        "fecha",
        "descripcion",
        "moneda",
        "con_comprobante",
        "gastado_por",
        "categoria__nombre",
        "proveedor__nombre",
        "proveedor__numero_documento",
        "tipo_comprobante__nombre",
        "comprobante_serie",
        "comprobante_numero",
        "empresa__razon_social",
        "empresa_id",
    )
    propios = base.filter(empresa=empresa, repartos__isnull=True).values(*campos, "total")
    repartidos = (
        GastoReparto.objects.filter(
            empresa=empresa,
            gasto__estado=Gasto.Estado.EMITIDO,
            gasto__fecha__gte=desde,
            gasto__fecha__lte=hasta,
        )
        .select_related("gasto")
        .values(
            *(f"gasto__{c}" for c in campos),
            "monto",
        )
    )
    filas = []
    for g in propios:
        filas.append({**{c: g[c] for c in campos}, "monto": g["total"], "repartido": False})
    for r in repartidos:
        filas.append(
            {
                **{c: r[f"gasto__{c}"] for c in campos},
                "monto": r["monto"],
                "repartido": True,
            }
        )
    return filas


def _periodo(fecha: date) -> str:
    return f"{fecha:%Y-%m}"


def resumen(empresa: Empresa, desde: date, hasta: date) -> dict:
    """Totales, por categoría y por mes (cada moneda aparte)."""
    desde, hasta = validar_rango(desde, hasta)
    filas = costos(empresa, desde, hasta)
    totales: dict[str, dict] = {}
    categorias: dict[tuple[str, str], dict] = {}
    meses: dict[tuple[str, str], Decimal] = {}
    matriz: dict[tuple[str, str], dict[str, Decimal]] = {}
    for f in filas:
        m = f["moneda"]
        t = totales.setdefault(
            m, {"moneda": m, "total": CERO, "con_comprobante": CERO, "sin_comprobante": CERO}
        )
        t["total"] += f["monto"]
        t["con_comprobante" if f["con_comprobante"] else "sin_comprobante"] += f["monto"]
        c = categorias.setdefault(
            (m, f["categoria__nombre"]),
            {"categoria": f["categoria__nombre"], "moneda": m, "monto": CERO, "cantidad": 0},
        )
        c["monto"] += f["monto"]
        c["cantidad"] += 1
        periodo = _periodo(f["fecha"])
        meses[(m, periodo)] = meses.get((m, periodo), CERO) + f["monto"]
        fila = matriz.setdefault((m, f["categoria__nombre"]), {})
        fila[periodo] = fila.get(periodo, CERO) + f["monto"]
    for c in categorias.values():
        total = totales[c["moneda"]]["total"]
        c["porcentaje"] = (c["monto"] * 100 / total).quantize(Decimal("0.1")) if total else CERO
    return {
        "desde": desde,
        "hasta": hasta,
        "totales": sorted(totales.values(), key=lambda t: t["moneda"]),
        "por_categoria": sorted(categorias.values(), key=lambda c: (c["moneda"], -c["monto"])),
        "por_mes": [{"periodo": p, "moneda": m, "monto": v} for (m, p), v in sorted(meses.items())],
        "matriz": [
            {"categoria": cat, "moneda": m, "meses": dict(sorted(fila.items()))}
            for (m, cat), fila in sorted(matriz.items())
        ],
    }


def por_proveedor(empresa: Empresa, desde: date, hasta: date) -> dict:
    """Cuánto se gastó con cada proveedor (los gastos sin proveedor, juntos)."""
    desde, hasta = validar_rango(desde, hasta)
    grupos: dict[tuple[str, str, str], dict] = {}
    for f in costos(empresa, desde, hasta):
        nombre = f["proveedor__nombre"] or "Sin proveedor"
        clave = (f["moneda"], nombre, f["proveedor__numero_documento"] or "")
        g = grupos.setdefault(
            clave,
            {
                "proveedor": nombre,
                "documento": f["proveedor__numero_documento"] or "",
                "moneda": f["moneda"],
                "monto": CERO,
                "cantidad": 0,
            },
        )
        g["monto"] += f["monto"]
        g["cantidad"] += 1
    return {
        "desde": desde,
        "hasta": hasta,
        "filas": sorted(grupos.values(), key=lambda g: (g["moneda"], -g["monto"], g["proveedor"])),
    }


def sin_comprobante(empresa: Empresa, desde: date, hasta: date) -> dict:
    """Los gastos sin comprobante del rango, para vigilarlos: quién, cuánto y cuántas veces."""
    desde, hasta = validar_rango(desde, hasta)
    detalle = [f for f in costos(empresa, desde, hasta) if not f["con_comprobante"]]
    por_persona: dict[tuple[str, str], dict] = {}
    for f in detalle:
        persona = f["gastado_por"] or "Sin nombre"
        p = por_persona.setdefault(
            (f["moneda"], persona),
            {"persona": persona, "moneda": f["moneda"], "monto": CERO, "cantidad": 0},
        )
        p["monto"] += f["monto"]
        p["cantidad"] += 1
    detalle.sort(key=lambda f: (f["fecha"], f["numero"]), reverse=True)
    return {
        "desde": desde,
        "hasta": hasta,
        "total_filas": len(detalle),
        "truncado": len(detalle) > MAX_FILAS_DETALLE,
        "por_persona": sorted(por_persona.values(), key=lambda p: (p["moneda"], -p["monto"])),
        "filas": [
            {
                "id": f["id"],
                "numero": f["numero"],
                "fecha": f["fecha"],
                "descripcion": f["descripcion"],
                "categoria": f["categoria__nombre"],
                "gastado_por": f["gastado_por"],
                "moneda": f["moneda"],
                "monto": f["monto"],
                "repartido": f["repartido"],
            }
            for f in detalle[:MAX_FILAS_DETALLE]
        ],
    }


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _subtitulo(datos: dict) -> str:
    return f"Del {datos['desde']:%d/%m/%Y} al {datos['hasta']:%d/%m/%Y} (costo de la empresa)"


def resumen_excel(empresa: Empresa, datos: dict) -> bytes:
    """Categorías en filas, meses en columnas (una tabla por moneda cuando hay dos)."""
    meses = sorted({p for f in datos["matriz"] for p in f["meses"]})
    filas = []
    for f in datos["matriz"]:
        total = sum(f["meses"].values(), CERO)
        filas.append(
            [(f["categoria"], None), (SIMBOLO[f["moneda"]], None)]
            + [(f["meses"].get(p, CERO), DINERO) for p in meses]
            + [(total, DINERO)]
        )
    totales = [
        [("TOTAL", None), (SIMBOLO[t["moneda"]], None)]
        + [
            (
                sum(
                    (
                        f["meses"].get(p, CERO)
                        for f in datos["matriz"]
                        if f["moneda"] == t["moneda"]
                    ),
                    CERO,
                ),
                DINERO,
            )
            for p in meses
        ]
        + [(t["total"], DINERO)]
        for t in datos["totales"]
    ]
    return tabla_excel(
        empresa,
        hoja="Por categoría",
        titulo="GASTOS POR CATEGORÍA Y MES",
        subtitulo=_subtitulo(datos),
        titulos=["Categoría", "Moneda", *meses, "Total"],
        filas=filas,
        totales=totales,
        anchos=[36, 9, *([14] * len(meses)), 16],
    )


def proveedores_excel(empresa: Empresa, datos: dict) -> bytes:
    return tabla_excel(
        empresa,
        hoja="Por proveedor",
        titulo="GASTOS POR PROVEEDOR",
        subtitulo=_subtitulo(datos),
        titulos=["Proveedor", "Documento", "Moneda", "Gastos", "Total"],
        filas=[
            [
                (f["proveedor"], None),
                (f["documento"], None),
                (SIMBOLO[f["moneda"]], None),
                (f["cantidad"], None),
                (f["monto"], DINERO),
            ]
            for f in datos["filas"]
        ],
        anchos=[40, 16, 9, 10, 16],
    )


def sin_comprobante_excel(empresa: Empresa, datos: dict) -> bytes:
    return tabla_excel(
        empresa,
        hoja="Sin comprobante",
        titulo="GASTOS SIN COMPROBANTE",
        subtitulo=_subtitulo(datos),
        titulos=["Fecha", "N°", "Quién lo gastó", "Categoría", "Descripción", "Moneda", "Monto"],
        filas=[
            [
                (f["fecha"], "dd/mm/yyyy"),
                (f["numero"], None),
                (f["gastado_por"], None),
                (f["categoria"], None),
                (f["descripcion"], None),
                (SIMBOLO[f["moneda"]], None),
                (f["monto"], DINERO),
            ]
            for f in datos["filas"]
        ],
        totales=[
            [("TOTAL " + p["persona"], None), ("", None), ("", None), ("", None), ("", None)]
            + [(SIMBOLO[p["moneda"]], None), (p["monto"], DINERO)]
            for p in datos["por_persona"]
        ],
        anchos=[12, 8, 24, 26, 44, 9, 14],
    )
