"""Importación masiva de clientes y proveedores desde un Excel (.xlsx) o un CSV.

Flujo: el usuario sube el archivo, el sistema lo VALIDA entero sin guardar nada y devuelve un
informe (filas válidas, errores por fila, repetidos); si está de acuerdo, lo sube de nuevo y se
IMPORTAN solo las filas válidas. Nada del informe se da por bueno: al importar se vuelve a
validar todo.

* Tamaño y cantidad de filas acotados (el archivo es entrada no confiable).
* Solo se CREAN registros: lo que ya existe (mismo documento) se omite, nunca se sobrescribe.
* El Excel se lee en modo de solo lectura y solo con los valores (sin fórmulas ni macros).
"""

import csv
import io
import logging
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Banco, Cliente, Proveedor, TipoDocumento
from apps.mantenimiento.services import SIN_UNICIDAD
from apps.mantenimiento.validators import normalizar_documento

logger = logging.getLogger(__name__)

TAMANO_MAXIMO = 2 * 1024 * 1024  # 2 MB
FILAS_MAXIMAS = 2000
ERRORES_MOSTRADOS = 100


class ErrorImportacion(Exception):
    """El archivo no se puede procesar (formato, tamaño o columnas): mensaje para el usuario."""


@dataclass(frozen=True)
class Columna:
    campo: str
    titulo: str  # encabezado de la plantilla
    ejemplo: str
    alias: tuple[str, ...] = ()


@dataclass(frozen=True)
class Especificacion:
    modelo: type
    entrada: type
    recurso: str
    plural: str
    columnas: tuple[Columna, ...]
    tipo_por_defecto: str = TipoDocumento.DNI
    con_asesor: bool = False

    def campos(self) -> set[str]:
        return {c.campo for c in self.columnas}


_BASE = (
    Columna("tipo_documento", "Tipo de documento", "DNI", ("tipo documento", "tipo doc", "tipo")),
    Columna(
        "numero_documento",
        "Número de documento",
        "45871236",
        ("documento", "nro documento", "n documento", "dni", "ruc", "dni ruc", "numero"),
    ),
    Columna(
        "nombre",
        "Nombre o razón social",
        "Ana Ruiz Pérez",
        ("nombre", "razon social", "nombres", "cliente", "proveedor", "nombre completo"),
    ),
    Columna("nombre_comercial", "Nombre comercial", "", ("comercial",)),
    Columna("telefono", "Teléfono", "987654321", ("celular", "movil", "cel", "telefono celular")),
    Columna("correo", "Correo", "ana@correo.com", ("email", "e mail", "correo electronico")),
    Columna("direccion", "Dirección", "Av. Principal 123, Lima", ("domicilio",)),
)

_EXTRA_PROVEEDOR = (
    Columna("contacto", "Persona de contacto", "Marta Silva", ("persona de contacto",)),
    Columna("ciudad", "Ciudad", "Lima", ("localidad", "provincia")),
    Columna("banco", "Banco", "BCP", ()),
    Columna(
        "cuenta_bancaria",
        "Número de cuenta bancaria",
        "193-12345678-0-12",
        ("cuenta", "nro cuenta", "numero de cuenta", "numero cuenta bancaria", "cuenta bancaria"),
    ),
    Columna(
        "productos_referencia",
        "Productos de referencia",
        "Baterías y aceites",
        ("productos", "referencia"),
    ),
)


def especificacion_clientes():
    from apps.mantenimiento.api.v1.serializers import ClienteEntrada

    return Especificacion(
        Cliente, ClienteEntrada, "cliente", "clientes", _BASE, TipoDocumento.DNI, con_asesor=True
    )


def especificacion_proveedores():
    from apps.mantenimiento.api.v1.serializers import ProveedorEntrada

    base = {c.campo: c for c in _BASE}
    columnas = (
        Columna("tipo_documento", "Tipo de documento", "RUC", base["tipo_documento"].alias),
        Columna(
            "numero_documento", "Número de documento", "20100000017", base["numero_documento"].alias
        ),
        Columna("nombre", "Razón social", "Distribuidora Andina S.A.C.", base["nombre"].alias),
        base["nombre_comercial"],
        _EXTRA_PROVEEDOR[0],  # contacto
        base["telefono"],
        base["correo"],
        base["direccion"],
        _EXTRA_PROVEEDOR[1],  # ciudad
        *_EXTRA_PROVEEDOR[2:],  # banco, cuenta, productos
    )
    return Especificacion(
        Proveedor, ProveedorEntrada, "proveedor", "proveedores", columnas, TipoDocumento.RUC
    )


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
def _plano(texto) -> str:
    """Minúsculas, sin tildes ni signos: «Número de documento» → «numero de documento»."""
    s = unicodedata.normalize("NFD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _mapa_encabezados(spec: Especificacion) -> dict[str, str]:
    mapa = {}
    for c in spec.columnas:
        for nombre in (c.campo.replace("_", " "), c.titulo, *c.alias):
            mapa[_plano(nombre)] = c.campo
    return mapa


def _celda(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)  # Excel guarda 45871236 como 45871236.0
    return str(valor).strip()


def _filas_csv(contenido: bytes) -> list[list[str]]:
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")  # CSV guardado por Excel en español
    muestra = texto[:4096]
    delimitador = max(",;\t", key=muestra.count)
    return [
        [_celda(c) for c in fila] for fila in csv.reader(io.StringIO(texto), delimiter=delimitador)
    ]


def _filas_xlsx(archivo, limite: int = FILAS_MAXIMAS) -> list[list[str]]:
    from openpyxl import load_workbook  # solo se importa si hace falta
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        libro = load_workbook(archivo, read_only=True, data_only=True)
        hoja = libro.worksheets[0]
        filas = []
        for fila in hoja.iter_rows(values_only=True):
            filas.append([_celda(c) for c in fila])
            if len(filas) > limite + 50:  # se corta la lectura: ya es demasiado
                break
        libro.close()
    except (zipfile.BadZipFile, InvalidFileException, KeyError, IndexError, ValueError, OSError):
        raise ErrorImportacion(
            "No se pudo leer el archivo. Verifica que sea un Excel (.xlsx) válido."
        ) from None
    return filas


def leer(
    archivo,
    spec,
    *,
    obligatorios: tuple[str, ...] = ("numero_documento", "nombre"),
    filas_maximas: int = FILAS_MAXIMAS,
) -> tuple[list[tuple[int, dict]], list[str]]:
    """Devuelve ``([(número_de_fila, {campo: valor})], columnas_ignoradas)``.

    ``spec`` solo necesita un atributo ``columnas`` (cada una con ``campo``, ``titulo`` y
    ``alias``). Otros módulos (inventario) la reutilizan con sus propias columnas obligatorias.
    """
    if archivo.size > TAMANO_MAXIMO:
        raise ErrorImportacion("El archivo pesa más de 2 MB. Divídelo en partes más pequeñas.")
    nombre = (archivo.name or "").lower()
    if nombre.endswith(".xlsx"):
        filas = _filas_xlsx(archivo, filas_maximas)
    elif nombre.endswith(".csv"):
        filas = _filas_csv(archivo.read())
    else:
        raise ErrorImportacion("Sube un archivo Excel (.xlsx) o CSV (.csv).")

    filas = [(i + 1, f) for i, f in enumerate(filas)]
    encabezado = next(((i, f) for i, f in filas if any(f)), None)
    if encabezado is None:
        raise ErrorImportacion("El archivo está vacío.")
    pos_encabezado, titulos = encabezado
    mapa = _mapa_encabezados(spec)
    columnas, ignoradas = {}, []
    for indice, titulo in enumerate(titulos):
        campo = mapa.get(_plano(titulo))
        if campo and campo not in columnas.values():
            columnas[indice] = campo
        elif titulo:
            ignoradas.append(titulo)
    faltan = [
        c.titulo
        for c in spec.columnas
        if c.campo in obligatorios and c.campo not in columnas.values()
    ]
    if faltan:
        raise ErrorImportacion(
            f"Faltan columnas obligatorias: {', '.join(faltan)}. Usa la plantilla."
        )

    datos = []
    for numero, fila in filas:
        if numero <= pos_encabezado or not any(fila):
            continue
        datos.append(
            (numero, {campo: fila[i] if i < len(fila) else "" for i, campo in columnas.items()})
        )
    if len(datos) > filas_maximas:
        raise ErrorImportacion(
            f"El archivo tiene más de {filas_maximas} filas. Divídelo en partes."
        )
    if not datos:
        raise ErrorImportacion("El archivo no tiene filas de datos debajo del encabezado.")
    return datos, ignoradas


# ---------------------------------------------------------------------------
# Limpieza y validación de cada fila
# ---------------------------------------------------------------------------
_TIPOS = {
    "dni": "DNI",
    "ruc": "RUC",
    "ce": "CE",
    "carnet de extranjeria": "CE",
    "carne de extranjeria": "CE",
    "pasaporte": "PASAPORTE",
    "otro": "OTRO",
}
_BANCOS = {_plano(b.label): b.value for b in Banco} | {
    "nacion": "BANCO_NACION",
    "banco nacion": "BANCO_NACION",
    "pichincha": "PICHINCHA",
}


def _limpiar(spec: Especificacion, crudo: dict) -> dict:
    datos = {campo: crudo.get(campo, "") for campo in spec.campos()}
    numero = normalizar_documento(datos["numero_documento"])
    tipo = datos["tipo_documento"]
    if tipo:
        datos["tipo_documento"] = _TIPOS.get(_plano(tipo), tipo)
    elif numero.isdigit() and len(numero) in (7, 8):
        datos["tipo_documento"] = "DNI"
    elif numero.isdigit() and len(numero) == 11:
        datos["tipo_documento"] = "RUC"
    else:
        datos["tipo_documento"] = spec.tipo_por_defecto
    if datos["tipo_documento"] == "DNI" and numero.isdigit() and len(numero) in (6, 7):
        numero = numero.zfill(8)  # Excel pierde los ceros iniciales de los números
    datos["numero_documento"] = numero
    if datos.get("banco"):
        datos["banco"] = _BANCOS.get(_plano(datos["banco"]), datos["banco"])
    return {campo: valor for campo, valor in datos.items() if valor != ""} | {
        "tipo_documento": datos["tipo_documento"],
        "numero_documento": numero,
    }


def _mensaje(errores) -> str:
    """Resume los errores de un serializer o de Django en una frase corta."""
    if isinstance(errores, ValidationError):
        errores = errores.message_dict if hasattr(errores, "error_dict") else {"": errores.messages}
    partes = []
    for campo, mensajes in errores.items():
        texto = " ".join(str(m) for m in (mensajes if isinstance(mensajes, list) else [mensajes]))
        partes.append(f"{campo.replace('_', ' ')}: {texto}" if campo else texto)
    return "; ".join(partes)


@dataclass
class Informe:
    total: int = 0
    instancias: list = field(default_factory=list)
    errores: list[dict] = field(default_factory=list)
    repetidos: list[dict] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)

    @property
    def validas(self) -> int:
        return len(self.instancias)

    def como_dict(self) -> dict:
        return {
            "total": self.total,
            "validas": self.validas,
            "con_error": len(self.errores),
            "repetidos": len(self.repetidos),
            "errores": self.errores[:ERRORES_MOSTRADOS],
            "repetidos_detalle": self.repetidos[:ERRORES_MOSTRADOS],
            "columnas_ignoradas": self.ignoradas,
            "recortado": len(self.errores) > ERRORES_MOSTRADOS
            or len(self.repetidos) > ERRORES_MOSTRADOS,
        }


def validar(spec: Especificacion, archivo, *, organizacion_id: int, asesor) -> Informe:
    """Lee y valida todas las filas SIN guardar nada."""
    filas, ignoradas = leer(archivo, spec)
    informe = Informe(total=len(filas), ignoradas=ignoradas)
    existentes = set(
        spec.modelo.objects.values_list("tipo_documento", "numero_documento")
    )  # de la organización: el gestor ya acota por organización
    vistos: dict[tuple, int] = {}
    for numero_fila, crudo in filas:
        entrada = spec.entrada(data=_limpiar(spec, crudo))
        if not entrada.is_valid():
            informe.errores.append({"fila": numero_fila, "mensaje": _mensaje(entrada.errors)})
            continue
        instancia = spec.modelo(**entrada.validated_data, organizacion_id=organizacion_id)
        if spec.con_asesor:
            instancia.asesor = asesor
        try:
            instancia.full_clean(**SIN_UNICIDAD)
        except ValidationError as error:
            informe.errores.append({"fila": numero_fila, "mensaje": _mensaje(error)})
            continue
        clave = (instancia.tipo_documento, instancia.numero_documento)
        documento = f"{clave[0]} {clave[1]}"
        if clave in existentes:
            informe.repetidos.append(
                {"fila": numero_fila, "documento": documento, "motivo": "Ya existe en el sistema."}
            )
        elif clave in vistos:
            informe.repetidos.append(
                {
                    "fila": numero_fila,
                    "documento": documento,
                    "motivo": f"Repetido en la fila {vistos[clave]} del archivo.",
                }
            )
        else:
            vistos[clave] = numero_fila
            informe.instancias.append(instancia)
    return informe


def importar(spec: Especificacion, archivo, *, organizacion_id: int, asesor) -> tuple[Informe, int]:
    """Valida de nuevo y crea las filas válidas (todas o ninguna). Devuelve el informe y cuántas."""
    informe = validar(spec, archivo, organizacion_id=organizacion_id, asesor=asesor)
    if not informe.instancias:
        return informe, 0
    try:
        with transaction.atomic():
            spec.modelo.objects.bulk_create(informe.instancias, batch_size=500)
    except IntegrityError:
        # Alguien registró uno de esos documentos justo ahora: se pide validar de nuevo.
        raise ErrorImportacion(
            "Mientras importabas, otra persona registró algunos de estos documentos. "
            "Vuelve a subir el archivo para revisarlo."
        ) from None
    registrar(
        f"{spec.recurso}.importado",
        recurso_tipo=spec.recurso,
        resumen=f"Importación de {informe.validas} {spec.plural} desde archivo",
        detalle={
            "filas": informe.total,
            "creados": informe.validas,
            "con_error": len(informe.errores),
            "repetidos": len(informe.repetidos),
            "archivo": (archivo.name or "")[:80],
        },
    )
    logger.info(
        "importacion_masiva",
        extra={"recurso": spec.recurso, "creados": informe.validas, "filas": informe.total},
    )
    return informe, informe.validas


def plantilla_csv(spec: Especificacion) -> bytes:
    """CSV con BOM (Excel lo abre con tildes) con los encabezados y una fila de ejemplo."""
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow([c.titulo for c in spec.columnas])
    escritor.writerow([c.ejemplo for c in spec.columnas])
    return ("﻿" + salida.getvalue()).encode("utf-8")
