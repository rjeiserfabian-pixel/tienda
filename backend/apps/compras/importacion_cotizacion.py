"""Plantilla y lectura en Excel de la respuesta de un proveedor a una cotización.

El flujo: se descarga la plantilla (ya trae los productos y cantidades pedidos), el proveedor o
quien la recibe escribe los precios, y se sube. Se hace en dos pasos, como el conteo de inventario:
``revisar`` informa fila por fila SIN guardar nada y ``aplicar`` guarda todo o nada.

Reglas para no dar por bueno un archivo dudoso:

* Cada fila se empareja con una línea de la cotización por su número («N°») y, si trae código,
  este debe coincidir con el del producto (si no, el archivo es de otra cotización).
* Un precio vacío significa «no cotiza ese producto»; un precio inválido es un error.
* Si hay UN error, no se guarda nada y se informa cuáles son.
* El archivo es entrada no confiable: tamaño y filas acotados; solo se leen valores, no fórmulas.
"""

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.mantenimiento.importacion import TAMANO_MAXIMO, ErrorImportacion, _filas_xlsx, _plano

from .cotizaciones import PrecioDado, registrar_respuesta
from .exceptions import CotizacionInvalida
from .models import (
    FormaPago,
    LineaSolicitudCotizacion,
    RespuestaCotizacion,
)

logger = logging.getLogger(__name__)

FILAS_MAXIMAS = 500
FILAS_BUSCANDO_ENCABEZADO = 30
DETALLE_MOSTRADO = 200

TITULOS = (
    "N°",
    "Código",
    "Producto",
    "Unidad",
    "Cantidad pedida",
    "Precio unitario",
    "Cantidad ofrecida",
    "Observación",
)
# Encabezados que se reconocen (sin tildes, en minúsculas y sin signos).
_ALIAS = {
    "posicion": ("n", "no", "nro", "numero", "item", "n°", "num"),
    "codigo": ("codigo", "cod", "codigo producto"),
    "precio": ("precio unitario", "precio", "precio unit", "p unitario", "precio ofertado"),
    "ofrecida": ("cantidad ofrecida", "cant ofrecida", "ofrece", "cantidad que ofrece"),
    "observacion": ("observacion", "observaciones", "nota", "comentario"),
}
_CAMPO_DE = {alias: campo for campo, lista in _ALIAS.items() for alias in lista}

# Datos generales que se leen de las filas de arriba (el rótulo empieza así → campo).
ETIQUETAS = {
    "forma de pago": "forma_pago",
    "plazo de credito": "plazo_dias",
    "plazo de entrega": "plazo_entrega_dias",
    "precios validos hasta": "validez_hasta",
    "observacion general": "observacion",
}
_FORMAS = {"contado": FormaPago.CONTADO, "credito": FormaPago.CREDITO}


# ---------------------------------------------------------------------------
# Plantilla
# ---------------------------------------------------------------------------
def plantilla(respuesta: RespuestaCotizacion) -> bytes:
    """Excel con los productos pedidos y las celdas para los precios y condiciones."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    solicitud = respuesta.solicitud
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Cotización"
    negrita = Font(bold=True)
    entrada = PatternFill("solid", fgColor="FFF2CC")  # amarillo: lo que hay que llenar
    cabecera = PatternFill("solid", fgColor="D9D9D9")

    hoja.append([f"Cotización {solicitud.codigo}"])
    hoja["A1"].font = Font(bold=True, size=14)
    hoja.append([f"Proveedor: {respuesta.proveedor.nombre}"])
    base = "con IGV incluido" if solicitud.precios_incluyen_igv else "SIN IGV (más IGV)"
    hoja.append([f"Moneda: {solicitud.moneda}. Los precios van {base}."])
    hoja.append(["Llene solo las celdas amarillas. Deje el precio vacío si no cotiza el producto."])
    condiciones = [
        ("Forma de pago (Contado o Crédito):", "Contado"),
        ("Plazo de crédito (días):", 0),
        ("Plazo de entrega (días):", 0),
        ("Precios válidos hasta (AAAA-MM-DD):", ""),
        ("Observación general:", ""),
    ]
    for etiqueta, valor in condiciones:
        hoja.append([etiqueta, valor])
        fila = hoja.max_row
        hoja.cell(row=fila, column=1).font = negrita
        hoja.cell(row=fila, column=2).fill = entrada
    hoja.append([])
    hoja.append(list(TITULOS))
    encabezado = hoja.max_row
    for columna in range(1, len(TITULOS) + 1):
        c = hoja.cell(row=encabezado, column=columna)
        c.font, c.fill = negrita, cabecera
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    lineas = LineaSolicitudCotizacion.objects.filter(solicitud=solicitud).select_related("producto")
    for ln in lineas.order_by("posicion"):
        hoja.append(
            [
                ln.posicion,
                ln.producto.codigo,
                ln.producto.nombre,
                ln.unidad,
                float(ln.cantidad),
                None,
                None,
                None,
            ]
        )
        fila = hoja.max_row
        for columna in (6, 7, 8):
            hoja.cell(row=fila, column=columna).fill = entrada
    for columna, ancho in enumerate((16, 14, 46, 12, 16, 16, 18, 30), start=1):
        hoja.column_dimensions[get_column_letter(columna)].width = ancho
    hoja.freeze_panes = hoja.cell(row=encabezado + 1, column=1)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
@dataclass
class Informe:
    condiciones: dict = field(default_factory=dict)
    filas: list[dict] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    precios: list[PrecioDado] = field(default_factory=list)

    @property
    def con_errores(self) -> bool:
        return bool(self.problemas) or any(f["estado"] == "error" for f in self.filas)

    def como_dict(self) -> dict:
        return {
            "condiciones": self.condiciones,
            "filas": self.filas[:DETALLE_MOSTRADO],
            "filas_total": len(self.filas),
            "cotizados": sum(1 for f in self.filas if f["estado"] == "ok"),
            "sin_precio": sum(1 for f in self.filas if f["estado"] == "sin_precio"),
            "errores": sum(1 for f in self.filas if f["estado"] == "error"),
            "problemas": self.problemas,
            "se_puede_aplicar": not self.con_errores
            and any(f["estado"] == "ok" for f in self.filas),
        }


def _numero(texto: str) -> Decimal | None:
    """«12,5», «1 234.50» o «S/ 10» → Decimal. Vacío → None. Ilegible → ValueError."""
    if not (texto or "").strip():
        return None
    limpio = re.sub(r"[^\d,.\-]", "", texto)
    if not limpio:  # había algo escrito pero sin ningún número: no se adivina
        raise ValueError(texto)
    if "," in limpio and "." in limpio:  # el último separador es el decimal
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", ".")
    try:
        valor = Decimal(limpio)
    except InvalidOperation:
        raise ValueError(texto) from None
    if not valor.is_finite():
        raise ValueError(texto)
    return valor


def _fecha(texto: str) -> date | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    raise ValueError(texto)


def _condiciones(filas_arriba: list[list[str]], informe: Informe) -> dict:
    """Lee «etiqueta | valor» de las filas anteriores a la tabla."""
    crudas = {}
    for fila in filas_arriba:
        if len(fila) < 2 or not fila[0] or fila[1] == "":
            continue
        rotulo = _plano(fila[0])
        campo = next((c for e, c in ETIQUETAS.items() if rotulo.startswith(e)), None)
        if campo:
            crudas[campo] = fila[1]
    resultado: dict = {}
    if "forma_pago" in crudas:
        forma = _FORMAS.get(_plano(crudas["forma_pago"]))
        if forma is None:
            informe.problemas.append("La forma de pago debe ser Contado o Crédito.")
        else:
            resultado["forma_pago"] = forma
    for campo in ("plazo_dias", "plazo_entrega_dias"):
        if campo in crudas:
            try:
                valor = _numero(crudas[campo])
            except ValueError:
                valor = None
            if valor is None or valor != valor.to_integral_value() or valor < 0:
                informe.problemas.append(f"«{campo.replace('_', ' ')}»: indique un número entero.")
            else:
                resultado[campo] = int(valor)
    if "validez_hasta" in crudas:
        try:
            resultado["validez_hasta"] = _fecha(crudas["validez_hasta"])
        except ValueError:
            informe.problemas.append("«Precios válidos hasta»: use el formato AAAA-MM-DD.")
    if "observacion" in crudas:
        resultado["observacion"] = crudas["observacion"][:250]
    return resultado


def _leer(respuesta: RespuestaCotizacion, archivo) -> Informe:
    if archivo is None or archivo.size > TAMANO_MAXIMO:
        raise ErrorImportacion("El archivo pesa más de 2 MB o no se recibió.")
    if not (archivo.name or "").lower().endswith(".xlsx"):
        raise ErrorImportacion(
            "Sube un archivo Excel (.xlsx). Descarga la plantilla de esta cotización."
        )
    filas = _filas_xlsx(archivo, FILAS_MAXIMAS)
    informe = Informe()

    # La tabla empieza en la primera fila con «Precio» entre sus títulos.
    columnas: dict[str, int] = {}
    inicio = None
    for i, fila in enumerate(filas[:FILAS_BUSCANDO_ENCABEZADO]):
        mapa = {}
        for indice, titulo in enumerate(fila):
            campo = _CAMPO_DE.get(_plano(titulo))
            if campo and campo not in mapa:
                mapa[campo] = indice
        if "precio" in mapa and ("posicion" in mapa or "codigo" in mapa):
            columnas, inicio = mapa, i
            break
    if inicio is None:
        raise ErrorImportacion(
            "No se encontró la tabla. Use la plantilla de la cotización (columnas N°, Código y "
            "Precio unitario)."
        )
    informe.condiciones = _condiciones(filas[:inicio], informe)

    lineas = list(
        LineaSolicitudCotizacion.objects.filter(solicitud=respuesta.solicitud)
        .select_related("producto")
        .order_by("posicion")
    )
    por_posicion = {ln.posicion: ln for ln in lineas}
    por_codigo = {ln.producto.codigo.strip().lower(): ln for ln in lineas}
    vistas: set[int] = set()

    def celda(fila, campo):
        indice = columnas.get(campo)
        return fila[indice].strip() if indice is not None and indice < len(fila) else ""

    for numero, fila in enumerate(filas[inicio + 1 :], start=inicio + 2):
        if not any(fila):
            continue
        posicion_txt, codigo, precio_txt = (
            celda(fila, "posicion"),
            celda(fila, "codigo"),
            celda(fila, "precio"),
        )
        if not posicion_txt and not codigo:
            continue
        resultado = {
            "fila": numero,
            "posicion": None,
            "producto": "",
            "precio": None,
            "cantidad_ofrecida": None,
            "estado": "ok",
            "mensaje": "",
        }
        linea = None
        try:
            if posicion_txt:
                pos = _numero(posicion_txt)
                linea = por_posicion.get(int(pos)) if pos is not None else None
            if linea is None and codigo:
                linea = por_codigo.get(codigo.lower())
        except (ValueError, OverflowError):
            linea = None
        if linea is None:
            resultado.update(
                estado="error", mensaje="No coincide con ningún producto de la cotización."
            )
            informe.filas.append(resultado)
            continue
        resultado["posicion"], resultado["producto"] = linea.posicion, linea.producto.nombre
        if codigo and codigo.lower() != linea.producto.codigo.strip().lower():
            resultado.update(
                estado="error",
                mensaje="El código no coincide con el de ese número: ¿es de otra cotización?",
            )
            informe.filas.append(resultado)
            continue
        if linea.pk in vistas:
            resultado.update(estado="error", mensaje="Este producto aparece dos veces.")
            informe.filas.append(resultado)
            continue
        vistas.add(linea.pk)
        try:
            precio = _numero(precio_txt)
            ofrecida = _numero(celda(fila, "ofrecida"))
        except ValueError:
            resultado.update(
                estado="error", mensaje="El precio o la cantidad ofrecida no es un número."
            )
            informe.filas.append(resultado)
            continue
        if precio is None:
            resultado.update(estado="sin_precio", mensaje="No cotiza este producto.")
            informe.precios.append(PrecioDado(linea.pk, None))
        elif precio < 0:
            resultado.update(estado="error", mensaje="El precio no puede ser negativo.")
        elif ofrecida is not None and (ofrecida <= 0 or ofrecida > linea.cantidad):
            resultado.update(
                estado="error",
                mensaje=f"La cantidad ofrecida va de 0 a {linea.cantidad.normalize():f}.",
            )
        else:
            resultado.update(
                precio=str(precio), cantidad_ofrecida=None if ofrecida is None else str(ofrecida)
            )
            informe.precios.append(
                PrecioDado(linea.pk, precio, ofrecida, celda(fila, "observacion"))
            )
        informe.filas.append(resultado)

    faltan = [ln.posicion for ln in lineas if ln.pk not in vistas]
    if faltan:
        informe.problemas.append(
            "Faltan productos de la cotización en el archivo (N° "
            + ", ".join(map(str, faltan[:20]))
            + ")."
        )
    return informe


def revisar(respuesta: RespuestaCotizacion, archivo) -> Informe:
    """Lee el archivo y dice qué traería, sin guardar nada."""
    return _leer(respuesta, archivo)


def aplicar(respuesta: RespuestaCotizacion, archivo) -> Informe:
    """Guarda la respuesta si el archivo no tiene errores (todo o nada)."""
    informe = _leer(respuesta, archivo)
    if informe.con_errores:
        raise ErrorImportacion("El archivo tiene errores: corrígelos y vuelve a subirlo.")
    if not informe.precios or not any(p.precio_unitario is not None for p in informe.precios):
        raise ErrorImportacion("El archivo no trae ningún precio.")
    c = informe.condiciones
    try:
        registrar_respuesta(
            respuesta,
            precios=informe.precios,
            forma_pago=c.get("forma_pago", FormaPago.CONTADO),
            plazo_dias=c.get("plazo_dias", 0),
            plazo_entrega_dias=c.get("plazo_entrega_dias", 0),
            validez_hasta=c.get("validez_hasta"),
            observacion=c.get("observacion", ""),
            origen=RespuestaCotizacion.Origen.ARCHIVO,
        )
    except CotizacionInvalida as error:
        raise ErrorImportacion(error.mensaje) from None
    logger.info(
        "cotizacion_importada",
        extra={
            "respuesta_id": respuesta.pk,
            "filas": len(informe.filas),
            "hoy": str(timezone.localdate()),
        },
    )
    return informe
