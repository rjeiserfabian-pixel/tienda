"""Lectura del estado de cuenta que entrega el banco (Excel o CSV).

Cada banco ordena sus columnas a su manera y suele poner líneas de encabezado antes de la tabla.
Aquí se busca la fila de títulos (la primera con una columna de fecha y otra de importe) y se
reconocen las columnas por su nombre. El archivo es entrada no confiable: tamaño y filas acotados,
solo se leen valores y NADA se guarda: el resultado se revisa antes de importar.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from apps.mantenimiento.importacion import (
    TAMANO_MAXIMO,
    ErrorImportacion,
    _filas_csv,
    _filas_xlsx,
    _plano,
)

FILAS_MAXIMAS = 5000
ERRORES_MOSTRADOS = 50
FILAS_PARA_ENCABEZADO = 40
MAXIMO = Decimal("9999999999999.99")
DOS = Decimal("0.01")

ALIAS = {
    "fecha": (
        "fecha",
        "fecha operacion",
        "fecha de operacion",
        "fecha proceso",
        "fecha de proceso",
        "fecha movimiento",
        "fecha valuta",
        "f operacion",
        "f proceso",
    ),
    "descripcion": (
        "descripcion",
        "descripcion operacion",
        "detalle",
        "detalle de movimiento",
        "glosa",
        "concepto",
        "movimiento",
    ),
    "referencia": (
        "referencia",
        "operacion",
        "nro operacion",
        "numero de operacion",
        "n operacion",
        "nro de operacion",
        "num operacion",
        "numero operacion",
        "codigo de operacion",
        "nro operacion",
        "nro mov",
        "n de movimiento",
    ),
    "cargo": (
        "cargo",
        "cargos",
        "debito",
        "debitos",
        "debe",
        "retiro",
        "retiros",
        "egreso",
        "egresos",
        "salida",
    ),
    "abono": (
        "abono",
        "abonos",
        "credito",
        "creditos",
        "haber",
        "deposito",
        "depositos",
        "ingreso",
        "ingresos",
        "entrada",
    ),
    "monto": ("monto", "importe", "importe total", "valor"),
    "saldo": ("saldo", "saldo contable", "saldo disponible", "saldo final"),
}
_CAMPO_DE = {_plano(a): campo for campo, alias in ALIAS.items() for a in alias}
_FORMATOS_FECHA = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y", "%Y/%m/%d")


@dataclass
class LineaLeida:
    fila: int
    fecha: date
    descripcion: str
    referencia: str
    monto: Decimal
    saldo: Decimal | None = None
    huella: str = ""


@dataclass
class Lectura:
    lineas: list[LineaLeida] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    total_errores: int = 0
    columnas: dict[str, str] = field(default_factory=dict)
    ignoradas: int = 0


def numero(texto) -> Decimal:
    """Importe de un extracto: «1,234.50», «1.234,50», «S/ -50.00», «(50.00)» o «50.00-»."""
    crudo = str(texto or "").strip()
    if not crudo:
        raise ValueError("vacío")
    negativo = crudo.startswith("(") and crudo.endswith(")")
    s = re.sub(r"(?i)s/\.?|us\$|\$|usd|pen|\s", "", crudo).strip("()")
    if s.endswith("-"):
        negativo, s = True, s[:-1]
    if s.startswith("-"):
        negativo, s = True, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if not re.fullmatch(r"[\d.,]+", s):
        raise ValueError("no es un número")
    punto, coma = s.rfind("."), s.rfind(",")
    if punto >= 0 and coma >= 0:  # el último símbolo es el decimal
        decimal = "." if punto > coma else ","
    elif coma >= 0:
        decimal = "," if len(s) - coma - 1 <= 2 and s.count(",") == 1 else None
    elif punto >= 0:
        decimal = "." if s.count(".") == 1 else None
    else:
        decimal = None
    if decimal:
        entero, _, fraccion = s.rpartition(decimal)
        s = re.sub(r"[.,]", "", entero) + "." + fraccion
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        valor = Decimal(s)
    except InvalidOperation:
        raise ValueError("no es un número") from None
    if not valor.is_finite() or valor != valor.quantize(DOS):
        raise ValueError("admite hasta 2 decimales")
    if valor > MAXIMO:
        raise ValueError("es demasiado grande")
    return -valor if negativo else valor


def fecha(texto) -> date:
    crudo = str(texto or "").strip()
    if not crudo:
        raise ValueError("vacía")
    crudo = crudo.split(" ")[0].split("T")[0]
    for formato in _FORMATOS_FECHA:
        try:
            return datetime.strptime(crudo, formato).date()
        except ValueError:
            continue
    raise ValueError("no se reconoce")


def _encabezado(filas: list[list[str]]) -> tuple[int, dict[int, str]]:
    for i, fila in enumerate(filas[:FILAS_PARA_ENCABEZADO]):
        columnas: dict[int, str] = {}
        for j, titulo in enumerate(fila):
            campo = _CAMPO_DE.get(_plano(titulo))
            if campo and campo not in columnas.values():
                columnas[j] = campo
        campos = set(columnas.values())
        if "fecha" in campos and ("monto" in campos or {"cargo", "abono"} & campos):
            return i, columnas
    raise ErrorImportacion(
        "No se encontró la tabla del extracto. Debe tener una columna de fecha y otra de importe "
        "(o de cargos y abonos) con sus títulos en una de las primeras filas."
    )


def leer(archivo) -> Lectura:
    """Lee el extracto y devuelve sus líneas válidas y los errores por fila. No guarda nada."""
    if archivo.size > TAMANO_MAXIMO:
        raise ErrorImportacion("El archivo pesa más de 2 MB. Exporta un periodo más corto.")
    nombre = (archivo.name or "").lower()
    if nombre.endswith(".xlsx"):
        filas = _filas_xlsx(archivo, FILAS_MAXIMAS)
    elif nombre.endswith(".csv"):
        filas = _filas_csv(archivo.read())
    else:
        raise ErrorImportacion("Sube el extracto en Excel (.xlsx) o CSV (.csv).")
    posicion, columnas = _encabezado(filas)
    lectura = Lectura(columnas={campo: str(filas[posicion][j]) for j, campo in columnas.items()})
    por_campo = {campo: j for j, campo in columnas.items()}

    def celda(fila, campo):
        j = por_campo.get(campo)
        return fila[j] if j is not None and j < len(fila) else ""

    datos = [(i + 1, f) for i, f in enumerate(filas) if i > posicion and any(f)]
    if len(datos) > FILAS_MAXIMAS:
        raise ErrorImportacion(f"El extracto tiene más de {FILAS_MAXIMAS} líneas. Divídelo.")
    if not datos:
        raise ErrorImportacion("El archivo no tiene líneas debajo de los títulos.")

    for numero_fila, fila in datos:
        try:
            try:
                f = fecha(celda(fila, "fecha"))
            except ValueError as e:
                raise ValueError(f"Fecha {e}.") from None
            try:
                if "monto" in por_campo and str(celda(fila, "monto")).strip():
                    monto = numero(celda(fila, "monto"))
                else:
                    cargo = celda(fila, "cargo")
                    abono = celda(fila, "abono")
                    c = abs(numero(cargo)) if str(cargo).strip() else Decimal("0")
                    a = abs(numero(abono)) if str(abono).strip() else Decimal("0")
                    if c and a:
                        raise ValueError("tiene cargo y abono a la vez")
                    monto = a - c
            except ValueError as e:
                raise ValueError(f"Importe {e}.") from None
            if monto == 0:
                lectura.ignoradas += 1  # líneas informativas (saldos, totales) sin importe
                continue
            saldo = None
            if str(celda(fila, "saldo")).strip():
                try:
                    saldo = numero(celda(fila, "saldo"))
                except ValueError:
                    saldo = None
            lectura.lineas.append(
                LineaLeida(
                    fila=numero_fila,
                    fecha=f,
                    descripcion=" ".join(str(celda(fila, "descripcion")).split())[:250],
                    referencia=" ".join(str(celda(fila, "referencia")).split())[:60],
                    monto=monto,
                    saldo=saldo,
                )
            )
        except ValueError as e:
            lectura.total_errores += 1
            if len(lectura.errores) < ERRORES_MOSTRADOS:
                lectura.errores.append(f"Fila {numero_fila}: {e}")
    if not lectura.lineas and not lectura.errores:
        raise ErrorImportacion("El extracto no tiene movimientos con importe.")
    poner_huellas(lectura.lineas)
    return lectura


def poner_huellas(lineas: list[LineaLeida]) -> None:
    """Identifica cada línea para no importarla dos veces si dos extractos se traslapan."""
    vistas: dict[str, int] = {}
    for linea in lineas:
        base = "|".join(
            [
                linea.fecha.isoformat(),
                str(linea.monto),
                _plano(linea.referencia),
                _plano(linea.descripcion),
            ]
        )
        vistas[base] = vistas.get(base, 0) + 1  # dos líneas idénticas el mismo día son distintas
        linea.huella = hashlib.sha256(f"{base}|{vistas[base]}".encode()).hexdigest()[:40]
