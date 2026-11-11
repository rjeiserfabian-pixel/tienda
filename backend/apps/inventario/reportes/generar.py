"""Elige y arma el reporte pedido: valida los parámetros y devuelve el archivo en memoria."""

import re
from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from apps.inventario.exceptions import ReporteInvalido
from apps.mantenimiento.models import Almacen, Producto
from apps.organizacion.models import Empresa

from . import datos as consulta
from . import excel, pdf

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"
MAX_DIAS = 366

# slug de la URL → (título, necesita producto, solo Excel)
REPORTES = {
    "kardex-fisico": ("Formato 12.1 Inventario permanente en unidades físicas", True, False),
    "kardex-valorizado": ("Formato 13.1 Inventario permanente valorizado", True, False),
    "saldos": ("Saldos de inventario valorizado", False, False),
    "costo-venta": ("Costo de venta por producto", False, False),
    "movimientos": ("Libro de movimientos (formato Kardex 2.0)", False, True),
    "antiguedad": ("Antigüedad del stock", False, True),
}


@dataclass(frozen=True, slots=True)
class Resultado:
    contenido: bytes
    nombre: str
    mime: str
    titulo: str
    filas: int


def _validar_rango(desde: date | None, hasta: date | None) -> tuple[date, date]:
    if desde is None or hasta is None:
        raise ReporteInvalido("Indique el rango de fechas (desde y hasta).")
    if desde > hasta:
        raise ReporteInvalido("La fecha «desde» no puede ser posterior a «hasta».")
    if hasta > timezone.localdate():
        raise ReporteInvalido("La fecha «hasta» no puede ser futura.")
    if (hasta - desde).days > MAX_DIAS:
        raise ReporteInvalido("El rango no puede pasar de un año.")
    return desde, hasta


def _nombre(slug: str, empresa: Empresa, sufijo: str, extension: str) -> str:
    """Nombre de archivo seguro: solo letras, números y guiones."""
    limpio = re.sub(r"[^A-Za-z0-9_-]", "", f"{slug}_{empresa.ruc}_{sufijo}")
    return f"{limpio}.{extension}"


def generar(
    tipo: str,
    formato: str,
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
) -> Resultado:
    titulo, necesita_producto, solo_excel = REPORTES[tipo]
    if formato == "pdf" and solo_excel:
        raise ReporteInvalido("Este reporte solo está disponible en Excel.")
    if necesita_producto and (almacen is None or producto is None):
        raise ReporteInvalido("Elija el almacén y el producto.")
    extension = "pdf" if formato == "pdf" else "xlsx"
    mime = PDF if formato == "pdf" else XLSX

    if tipo == "antiguedad":
        datos_antiguedad = consulta.antiguedad_del_stock(
            empresa, almacen, categoria, marca, solo_antiguo
        )
        return Resultado(
            excel.antiguedad_xlsx(empresa, almacen, datos_antiguedad),
            _nombre(tipo, empresa, f"{datos_antiguedad.hoy:%Y%m%d}", extension),
            mime,
            titulo,
            len(datos_antiguedad.filas),
        )

    if tipo in ("kardex-fisico", "kardex-valorizado"):
        desde, hasta = _validar_rango(desde, hasta)
        datos = consulta.kardex(empresa, almacen, producto, desde, hasta)
        libro = {
            ("kardex-fisico", "xlsx"): excel.libro_12_1,
            ("kardex-fisico", "pdf"): pdf.libro_12_1,
            ("kardex-valorizado", "xlsx"): excel.libro_13_1,
            ("kardex-valorizado", "pdf"): pdf.libro_13_1,
        }[(tipo, formato)]
        sufijo = f"{producto.codigo}_{desde:%Y%m%d}_{hasta:%Y%m%d}"
        return Resultado(
            libro(datos), _nombre(tipo, empresa, sufijo, extension), mime, titulo, len(datos.lineas)
        )

    if tipo == "saldos":
        corte = fecha or timezone.localdate()
        if corte > timezone.localdate():
            raise ReporteInvalido("La fecha no puede ser futura.")
        filas = consulta.saldos_a_fecha(empresa, corte, almacen)
        escribir = pdf.saldos_pdf if formato == "pdf" else excel.saldos_xlsx
        return Resultado(
            escribir(empresa, corte, almacen, filas),
            _nombre(tipo, empresa, f"{corte:%Y%m%d}", extension),
            mime,
            titulo,
            len(filas),
        )

    if tipo == "costo-venta":
        desde, hasta = _validar_rango(desde, hasta)
        filas = consulta.costo_de_venta(empresa, desde, hasta, almacen)
        escribir = pdf.costo_venta_pdf if formato == "pdf" else excel.costo_venta_xlsx
        return Resultado(
            escribir(empresa, desde, hasta, almacen, filas),
            _nombre(tipo, empresa, f"{desde:%Y%m%d}_{hasta:%Y%m%d}", extension),
            mime,
            titulo,
            len(filas),
        )

    desde, hasta = _validar_rango(desde, hasta)  # movimientos
    datos_mov = consulta.movimientos(empresa, desde, hasta)
    return Resultado(
        excel.movimientos_xlsx(datos_mov),
        _nombre(tipo, empresa, f"{desde:%Y%m%d}_{hasta:%Y%m%d}", extension),
        mime,
        titulo,
        len(datos_mov.movimientos),
    )
