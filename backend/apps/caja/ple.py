"""Libro Caja y Bancos electrónico (PLE de SUNAT): borrador de los archivos TXT 1.1 y 1.2.

IMPORTANTE: es un BORRADOR. La estructura de columnas sigue la del PLE, pero varios valores fijos
(cuenta contable, código de la entidad financiera, medio de pago, tipo de comprobante, fechas en
blanco) se tomaron de lo habitual y NO están verificados contra la tabla oficial de SUNAT. Antes de
declarar, el contador debe revisar el archivo en el programa PLE de SUNAT, que valida la estructura.

Limitaciones conocidas:
* Solo cuentas en soles: las de dólares exigen convertir cada movimiento con el tipo de cambio de
  su día y el sistema aún no lo guarda por movimiento.
* No incluye el asiento del saldo inicial (apertura).
* El código único de operación (CUO) es el número interno del movimiento.
"""

from datetime import date
from decimal import Decimal

from .exceptions import MovimientoInvalido

SIN_FECHA = "01/01/0001"
FORMATOS = {"1.1": "010100", "1.2": "010200"}
MEDIO_TRANSFERENCIA = "003"
MEDIO_OTROS = "999"


def _importe(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _texto(valor: str, largo: int = 200) -> str:
    """Sin el separador del archivo ni saltos de línea, y acotado."""
    return " ".join(str(valor or "").replace("|", " ").split())[:largo]


def _fecha(valor: date) -> str:
    return f"{valor:%d/%m/%Y}"


def _fila(campos: list[str]) -> str:
    return "|".join(campos) + "|"


def _descripcion(linea: dict) -> str:
    return _texto(f"{linea['concepto']} {linea['glosa']}".strip())


def generar(empresa, datos: dict, formato: str) -> dict:
    """Devuelve ``{"nombre", "contenido", "lineas", "avisos"}`` del formato ``1.1`` o ``1.2``."""
    if formato not in FORMATOS:
        raise MovimientoInvalido("Elija el formato 1.1 (efectivo) o 1.2 (bancos).")
    periodo = f"{datos['anio']}{datos['mes']:02d}00"
    secciones = datos["efectivo"] if formato == "1.1" else datos["bancos"]
    avisos = []
    en_soles = []
    for s in secciones:
        if s["moneda"] != "PEN":
            avisos.append(
                f"«{s['nombre']}» está en dólares y no se incluye (falta convertirla a soles)."
            )
        else:
            en_soles.append(s)
    faltan = []
    for s in en_soles:
        if formato == "1.1" and not s["cuenta_contable"]:
            faltan.append(f"«{s['nombre']}»: falta la cuenta contable")
        if formato == "1.2" and (not s["codigo_entidad"] or not s["numero_cuenta"]):
            faltan.append(f"«{s['nombre']}»: falta el código SUNAT del banco o el número de cuenta")
    if faltan:
        raise MovimientoInvalido(
            "Complete los datos de estas cajas y cuentas (en Cajas y cuentas): "
            + "; ".join(faltan)
            + "."
        )

    filas = []
    movimientos = sorted(
        (
            (linea, s)
            for s in en_soles
            for linea in s["lineas"]
            if linea.get("numero") is not None  # el saldo inicial no es un asiento del periodo
        ),
        key=lambda x: (x[0]["fecha"], x[0]["numero"]),
    )
    for linea, s in movimientos:
        cuo = str(linea["numero"])
        correlativo = f"M{linea['numero']:09d}"
        debe, haber = _importe(linea["debe"]), _importe(linea["haber"])
        if formato == "1.1":
            filas.append(
                _fila(
                    [
                        periodo,
                        cuo,
                        correlativo,
                        s["cuenta_contable"],
                        "",
                        "",
                        "PEN",
                        "00",
                        "0",
                        "0",
                        _fecha(linea["fecha"]),
                        SIN_FECHA,
                        _fecha(linea["fecha"]),
                        _descripcion(linea),
                        _texto(linea["referencia"]),
                        debe,
                        haber,
                        "",
                        "1",
                    ]
                )
            )
        else:
            medio = MEDIO_TRANSFERENCIA if linea["origen"] == "TRANSFERENCIA" else MEDIO_OTROS
            filas.append(
                _fila(
                    [
                        periodo,
                        cuo,
                        correlativo,
                        s["codigo_entidad"],
                        _texto(s["numero_cuenta"], 30),
                        _fecha(linea["fecha"]),
                        medio,
                        _descripcion(linea),
                        "",
                        "",
                        "",
                        _texto(linea["referencia"], 20),
                        debe,
                        haber,
                        "1",
                    ]
                )
            )
    con_datos = "1" if filas else "0"
    nombre = (
        f"LE{empresa.ruc}{datos['anio']}{datos['mes']:02d}00{FORMATOS[formato]}001{con_datos}11.TXT"
    )
    return {
        "nombre": nombre,
        "contenido": "".join(f"{f}\r\n" for f in filas),
        "lineas": len(filas),
        "avisos": avisos,
    }
