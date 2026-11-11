"""Vista previa en pantalla de los reportes de inventario: las mismas cifras que el archivo.

Devuelve las primeras ``FILAS_VISTA`` filas y los totales del reporte completo, para que se
revise antes de descargar. Los números viajan como texto (sin perder decimales); el panel los
da formato según el ``tipo`` de cada columna: ``texto``, ``num`` (cantidad) o ``soles``.
"""

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.inventario.exceptions import ReporteInvalido
from apps.inventario.models import OrigenMovimiento, TipoMovimiento
from apps.mantenimiento.models import Almacen, Producto
from apps.organizacion.models import Empresa

from . import datos as consulta
from .generar import REPORTES, _validar_rango

FILAS_VISTA = 200
CERO = Decimal("0")

_TIPOS = {t.value: t.label for t in TipoMovimiento}
_ORIGENES = {o.value: o.label for o in OrigenMovimiento}


def _col(clave: str, titulo: str, tipo: str = "texto") -> dict:
    return {"clave": clave, "titulo": titulo, "tipo": tipo}


def _comprobante(serie: str, numero: str) -> str:
    return f"{serie}-{numero}" if serie and numero else (numero or "")


def _movimiento(tipo: str, origen: str) -> str:
    return f"{_TIPOS.get(tipo, tipo)} · {_ORIGENES.get(origen, origen)}"


def _texto(valor) -> str:
    return "" if valor is None else str(valor)


def _respuesta(tipo: str, columnas: list[dict], filas: list[dict], **extra) -> dict:
    return {
        "reporte": tipo,
        "titulo": REPORTES[tipo][0],
        "columnas": columnas,
        "filas": filas[:FILAS_VISTA],
        "total_filas": len(filas),
        "recortado": len(filas) > FILAS_VISTA,
        **extra,
    }


def _kardex(tipo: str, empresa, almacen, producto, desde, hasta) -> dict:
    d = consulta.kardex(empresa, almacen, producto, desde, hasta)
    valorizado = tipo == "kardex-valorizado"
    columnas = [
        _col("fecha", "Fecha"),
        _col("numero", "N°"),
        _col("movimiento", "Movimiento"),
        _col("comprobante", "Comprobante"),
        _col("entrada", "Entrada", "num"),
        _col("salida", "Salida", "num"),
    ]
    if valorizado:
        columnas += [
            _col("costo_unitario", "Costo unit.", "soles"),
            _col("costo_total", "Costo total", "soles"),
        ]
    columnas.append(_col("saldo", "Saldo", "num"))
    if valorizado:
        columnas += [
            _col("saldo_costo_unitario", "Costo prom.", "soles"),
            _col("saldo_valor", "Saldo valorizado", "soles"),
        ]

    filas = []
    entradas = salidas = CERO
    for ln in d.lineas:
        mov = ln.movimiento
        es_entrada = ln.tipo == TipoMovimiento.ENTRADA
        entradas += ln.cantidad if es_entrada else CERO
        salidas += CERO if es_entrada else ln.cantidad
        filas.append(
            {
                "fecha": ln.fecha.isoformat(),
                "numero": f"{mov.numero:06d}",
                "movimiento": _movimiento(ln.tipo, mov.origen),
                "comprobante": _comprobante(mov.comprobante_serie, mov.comprobante_numero),
                "entrada": _texto(ln.cantidad) if es_entrada else "",
                "salida": "" if es_entrada else _texto(ln.cantidad),
                "costo_unitario": _texto(ln.costo_unitario),
                "costo_total": _texto(ln.costo_total),
                "saldo": _texto(ln.saldo_cantidad),
                "saldo_costo_unitario": _texto(ln.saldo_costo_unitario),
                "saldo_valor": _texto(ln.saldo_costo_total),
            }
        )
    resumen = [
        {"titulo": "Saldo inicial", "valor": _texto(d.saldo_inicial.cantidad), "tipo": "num"},
        {"titulo": "Entradas", "valor": _texto(entradas), "tipo": "num"},
        {"titulo": "Salidas", "valor": _texto(salidas), "tipo": "num"},
        {
            "titulo": "Saldo final",
            "valor": _texto(d.lineas[-1].saldo_cantidad if d.lineas else d.saldo_inicial.cantidad),
            "tipo": "num",
        },
    ]
    if valorizado:
        final = d.lineas[-1].saldo_costo_total if d.lineas else d.saldo_inicial.costo_total
        resumen.append({"titulo": "Valor final", "valor": _texto(final), "tipo": "soles"})
    return _respuesta(
        tipo,
        columnas,
        filas,
        resumen=resumen,
        encabezado=f"{producto.codigo} · {producto.nombre} · {almacen.nombre}",
    )


def _saldos(empresa, almacen, fecha) -> dict:
    corte = fecha or timezone.localdate()
    if corte > timezone.localdate():
        raise ReporteInvalido("La fecha no puede ser futura.")
    datos = consulta.saldos_a_fecha(empresa, corte, almacen)
    columnas = [
        _col("almacen", "Almacén"),
        _col("codigo", "Código"),
        _col("producto", "Producto"),
        _col("unidad", "Unidad"),
        _col("cantidad", "Cantidad", "num"),
        _col("costo_unitario", "Costo unit.", "soles"),
        _col("valor", "Valor", "soles"),
    ]
    filas = [
        {
            "almacen": f.almacen.nombre,
            "codigo": f.producto.codigo,
            "producto": f.producto.nombre,
            "unidad": f.producto.unidad.abreviatura,
            "cantidad": _texto(f.cantidad),
            "costo_unitario": _texto(f.costo_unitario),
            "valor": _texto(f.costo_total),
        }
        for f in datos
    ]
    resumen = [
        {"titulo": "Productos", "valor": str(len(datos)), "tipo": "entero"},
        {
            "titulo": "Valor total",
            "valor": _texto(sum((f.costo_total for f in datos), CERO)),
            "tipo": "soles",
        },
    ]
    return _respuesta("saldos", columnas, filas, resumen=resumen, encabezado=f"Al {corte:%d/%m/%Y}")


def _costo_venta(empresa, almacen, desde, hasta) -> dict:
    datos = consulta.costo_de_venta(empresa, desde, hasta, almacen)
    columnas = [
        _col("almacen", "Almacén"),
        _col("codigo", "Código"),
        _col("producto", "Producto"),
        _col("inicial", "Inv. inicial", "soles"),
        _col("entradas", "Entradas", "soles"),
        _col("salidas_cantidad", "Salió", "num"),
        _col("final", "Inv. final", "soles"),
        _col("costo_venta", "Costo de venta", "soles"),
    ]
    filas = [
        {
            "almacen": f.almacen.nombre,
            "codigo": f.producto.codigo,
            "producto": f.producto.nombre,
            "inicial": _texto(f.inicial_valor),
            "entradas": _texto(f.entradas_valor),
            "salidas_cantidad": _texto(f.salidas_cantidad),
            "final": _texto(f.final_valor),
            "costo_venta": _texto(f.costo_de_venta),
        }
        for f in datos
    ]
    resumen = [
        {"titulo": "Productos", "valor": str(len(datos)), "tipo": "entero"},
        {
            "titulo": "Costo de venta",
            "valor": _texto(sum((f.costo_de_venta for f in datos), CERO)),
            "tipo": "soles",
        },
    ]
    return _respuesta(
        "costo-venta",
        columnas,
        filas,
        resumen=resumen,
        encabezado=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
    )


def _movimientos(empresa, desde, hasta) -> dict:
    datos = consulta.movimientos(empresa, desde, hasta)
    columnas = [
        _col("numero", "N°"),
        _col("fecha", "Fecha"),
        _col("almacen", "Almacén"),
        _col("movimiento", "Movimiento"),
        _col("comprobante", "Comprobante"),
        _col("productos", "Productos", "entero"),
        _col("estado", "Estado"),
    ]
    filas = [
        {
            "numero": f"{m.numero:06d}",
            "fecha": m.fecha.isoformat(),
            "almacen": m.almacen.nombre,
            "movimiento": _movimiento(m.tipo, m.origen),
            "comprobante": _comprobante(m.comprobante_serie, m.comprobante_numero),
            "productos": str(len(m.lineas.all())),
            "estado": "Anulado" if m.estado == "ANULADO" else "Emitido",
        }
        for m in datos.movimientos
    ]
    resumen = [{"titulo": "Movimientos", "valor": str(len(filas)), "tipo": "entero"}]
    return _respuesta(
        "movimientos",
        columnas,
        filas,
        resumen=resumen,
        encabezado=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}",
    )


def _antiguedad(empresa, almacen, categoria, marca, solo_antiguo) -> dict:
    d = consulta.antiguedad_del_stock(empresa, almacen, categoria, marca, solo_antiguo)
    columnas = [
        _col("almacen", "Almacén"),
        _col("codigo", "Código"),
        _col("producto", "Producto"),
        _col("stock", "Stock", "num"),
        _col("t1", "0-30 días", "num"),
        _col("t2", "31-60", "num"),
        _col("t3", "61-90", "num"),
        _col("t4", "91-180", "num"),
        _col("t5", "Más de 180", "num"),
        _col("ingreso", "Ingreso más antiguo"),
        _col("dias", "Días", "entero"),
        _col("antiguas", "Unid. antiguas", "num"),
        _col("valor", "Valor antiguo", "soles"),
    ]
    filas = []
    for f in d.filas:
        fila = {
            "almacen": f.almacen.nombre,
            "codigo": f.producto.codigo,
            "producto": f.producto.nombre,
            "stock": _texto(f.saldo),
            "ingreso": f.mas_antigua.isoformat() if f.mas_antigua else "",
            "dias": "" if f.dias is None else str(f.dias),
            "antiguas": _texto(f.unidades_antiguas),
            "valor": _texto(f.valor_antiguo),
            "antiguo": f.unidades_antiguas > CERO,
        }
        for i, tramo in enumerate(f.tramos, start=1):
            fila[f"t{i}"] = _texto(tramo)
        filas.append(fila)
    antiguas = [f for f in d.filas if f.unidades_antiguas > CERO]
    resumen = [
        {"titulo": "Productos con stock", "valor": str(len(d.filas)), "tipo": "entero"},
        {"titulo": "Con stock antiguo", "valor": str(len(antiguas)), "tipo": "entero"},
        {
            "titulo": "Unidades antiguas",
            "valor": _texto(sum((f.unidades_antiguas for f in antiguas), CERO)),
            "tipo": "num",
        },
        {
            "titulo": "Valor antiguo",
            "valor": _texto(sum((f.valor_antiguo for f in antiguas), CERO)),
            "tipo": "soles",
        },
    ]
    return _respuesta(
        "antiguedad",
        columnas,
        filas,
        resumen=resumen,
        encabezado=f"Al {d.hoy:%d/%m/%Y} · antiguo = más de {d.umbral} días en el almacén",
    )


def previsualizar(
    tipo: str,
    *,
    empresa: Empresa,
    almacen: Almacen | None,
    producto: Producto | None,
    desde: date | None,
    hasta: date | None,
    fecha: date | None,
    categoria: int | None = None,
    marca: int | None = None,
    solo_antiguo: bool = False,
) -> dict:
    """Mismos parámetros y validaciones que ``generar``, pero devuelve datos, no un archivo."""
    _, necesita_producto, _ = REPORTES[tipo]
    if necesita_producto and (almacen is None or producto is None):
        raise ReporteInvalido("Elija el almacén y el producto.")
    if tipo == "antiguedad":
        return _antiguedad(empresa, almacen, categoria, marca, solo_antiguo)
    if tipo in ("kardex-fisico", "kardex-valorizado"):
        desde, hasta = _validar_rango(desde, hasta)
        return _kardex(tipo, empresa, almacen, producto, desde, hasta)
    if tipo == "saldos":
        return _saldos(empresa, almacen, fecha)
    desde, hasta = _validar_rango(desde, hasta)
    if tipo == "costo-venta":
        return _costo_venta(empresa, almacen, desde, hasta)
    return _movimientos(empresa, desde, hasta)
