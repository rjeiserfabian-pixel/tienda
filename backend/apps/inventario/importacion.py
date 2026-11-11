"""Carga del saldo inicial del inventario desde un Excel (.xlsx) o un CSV.

Flujo (el mismo de clientes y proveedores): se sube el archivo, el sistema lo REVISA entero sin
guardar nada y devuelve un informe; si convence, se vuelve a subir y se IMPORTAN las filas
válidas. Al importar se valida otra vez todo, con el cerrojo de la empresa tomado.

* Cada producto se carga UNA sola vez por almacén: si ya tiene movimientos allí, o se repite en
  el archivo, esa fila se omite (para corregir cantidades se usa un ajuste, nunca se duplica).
* Se crea un movimiento «Saldo inicial» por almacén (de hasta 200 productos cada uno), todos en
  una sola transacción: o entra todo lo válido, o no entra nada.
* El archivo es entrada no confiable: tamaño y filas acotados, y solo se leen valores.
"""

import io
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import PatternFill

from apps.auditoria.servicios import registrar
from apps.mantenimiento.importacion import Columna, ErrorImportacion, leer
from apps.mantenimiento.models import (
    Almacen,
    EstadoRegistro,
    Producto,
    TipoProducto,
    Ubicacion,
)
from apps.organizacion.models import Empresa

from . import numeracion, periodos, ubicaciones
from .costeo import a_dos
from .models import LineaMovimiento, OrigenMovimiento, TipoMovimiento
from .movimientos import MAX_LINEAS, LineaNueva, registrar_movimiento
from .reportes.excel import _poner

logger = logging.getLogger(__name__)

FILAS_MAXIMAS = 2000
MAX_PLANTILLA = 5000
ERRORES_MOSTRADOS = 100
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")

COLUMNAS = (
    Columna(
        "codigo",
        "Código del producto",
        "000001",
        ("codigo", "cod", "codigo producto", "codigo del sistema"),
    ),
    Columna(
        "producto",
        "Producto (solo referencia)",
        "Cemento Pacasmayo MS",
        ("nombre", "descripcion", "nombre del producto"),
    ),
    Columna(
        "almacen",
        "Código del almacén",
        "ALM1",
        ("almacen", "codigo almacen", "cod almacen"),
    ),
    Columna("cantidad", "Cantidad", "50", ("cant", "stock", "existencia", "stock inicial")),
    Columna(
        "costo",
        "Costo unitario (S/ sin IGV)",
        "20.00",
        ("costo unitario", "costo unit", "costo", "precio de costo"),
    ),
    Columna(
        "ubicacion",
        "Ubicación (opcional)",
        "A-03",
        ("ubicacion", "codigo ubicacion", "cod ubicacion", "ubicacion del producto"),
    ),
)
OBLIGATORIAS = ("codigo", "cantidad", "costo")


@dataclass(frozen=True)
class _Especificacion:
    columnas: tuple[Columna, ...] = COLUMNAS


@dataclass(frozen=True, slots=True)
class FilaValida:
    numero: int
    producto: Producto
    almacen: Almacen
    cantidad: Decimal
    costo: Decimal
    ubicacion: Ubicacion | None = None

    @property
    def valor(self) -> Decimal:
        return a_dos(self.cantidad * self.costo)


@dataclass
class Informe:
    total: int = 0
    filas: list[FilaValida] = field(default_factory=list)
    errores: list[dict] = field(default_factory=list)
    repetidos: list[dict] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)

    @property
    def validas(self) -> int:
        return len(self.filas)

    @property
    def movimientos(self) -> int:
        """Cuántos movimientos se crearían: uno por almacén, de hasta 200 productos cada uno."""
        por_almacen: dict[int, int] = defaultdict(int)
        for fila in self.filas:
            por_almacen[fila.almacen.pk] += 1
        return sum(-(-n // MAX_LINEAS) for n in por_almacen.values())

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
            "movimientos": self.movimientos,
            "valor_total": str(sum((f.valor for f in self.filas), Decimal("0"))),
        }


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def _numero(texto: str, nombre: str, decimales: int, *, maximo: Decimal) -> Decimal:
    limpio = (texto or "").strip()
    if not limpio:
        raise ValueError(f"Indique {nombre}.")
    if not _NUMERO.fullmatch(limpio):
        raise ValueError(f"{nombre}: escriba un número, sin signos ni separador de miles.")
    valor = Decimal(limpio.replace(",", "."))
    if valor != valor.quantize(Decimal(1).scaleb(-decimales)):
        raise ValueError(f"{nombre}: admite hasta {decimales} decimales.")
    if valor <= 0:
        raise ValueError(f"{nombre} debe ser mayor que cero.")
    if valor > maximo:
        raise ValueError(f"{nombre} es demasiado grande.")
    return valor


def _codigo(texto: str) -> str:
    codigo = (texto or "").strip().upper()
    # Excel pierde los ceros iniciales de los números: 1 → 000001.
    return codigo.zfill(6) if codigo.isdigit() and len(codigo) < 6 else codigo


def validar(empresa: Empresa, fecha: date, archivo) -> Informe:
    """Lee y valida todas las filas SIN guardar nada."""
    if fecha > timezone.localdate():
        raise ErrorImportacion("La fecha del saldo inicial no puede ser futura.")
    periodos.exigir_abierto(empresa.pk, fecha)
    filas, ignoradas = leer(
        archivo, _Especificacion(), obligatorios=OBLIGATORIAS, filas_maximas=FILAS_MAXIMAS
    )
    informe = Informe(total=len(filas), ignoradas=ignoradas)

    almacenes = {
        a.codigo: a for a in Almacen.objects.filter(empresa=empresa, estado=EstadoRegistro.ACTIVO)
    }
    unico = next(iter(almacenes.values())) if len(almacenes) == 1 else None
    ubicaciones_por_clave = {
        (u.almacen_id, u.codigo.upper()): u
        for u in Ubicacion.objects.filter(
            empresa=empresa, almacen__in=almacenes.values(), estado=EstadoRegistro.ACTIVO
        )
    }
    productos = {
        p.codigo.upper(): p
        for p in Producto.objects.filter(
            codigo__in={_codigo(f.get("codigo", "")) for _, f in filas if f.get("codigo")}
        )
    }
    con_historial = set(
        LineaMovimiento.objects.filter(
            empresa=empresa, almacen_id__in=[a.pk for a in almacenes.values()]
        )
        .filter(producto_id__in=[p.pk for p in productos.values()])
        .values_list("almacen_id", "producto_id")
        .distinct()
    )

    vistos: dict[tuple[int, int], int] = {}
    for numero, crudo in filas:
        try:
            codigo = _codigo(crudo.get("codigo", ""))
            if not codigo:
                raise ValueError("Indique el código del producto.")
            producto = productos.get(codigo)
            if producto is None:
                raise ValueError(f"No existe un producto con el código {codigo}.")
            if producto.tipo != TipoProducto.BIEN or not producto.controla_stock:
                raise ValueError(f"{producto.nombre} no lleva control de stock.")
            if producto.lleva_serie:
                raise ValueError(
                    f"{producto.nombre} lleva serie o IMEI: regístrelo con una compra o un "
                    "ajuste, indicando cada serie."
                )
            texto_almacen = (crudo.get("almacen") or "").strip().upper().replace(" ", "")
            almacen = almacenes.get(texto_almacen) if texto_almacen else unico
            if almacen is None:
                raise ValueError(
                    f"No existe el almacén «{texto_almacen}» en la empresa."
                    if texto_almacen
                    else "Indique el código del almacén."
                )
            texto_ubicacion = (crudo.get("ubicacion") or "").strip().upper().replace(" ", "")
            ubicacion = None
            if texto_ubicacion:
                ubicacion = ubicaciones_por_clave.get((almacen.pk, texto_ubicacion))
                if ubicacion is None:
                    raise ValueError(
                        f"No existe la ubicación «{texto_ubicacion}» en {almacen.codigo}."
                    )
            cantidad = _numero(
                crudo.get("cantidad", ""), "la cantidad", 3, maximo=Decimal("99999999999.999")
            )
            costo = _numero(
                crudo.get("costo", ""), "el costo unitario", 6, maximo=Decimal("9999999999.999999")
            )
            if a_dos(cantidad * costo) > Decimal("99999999999999.99"):
                raise ValueError("El valor de la fila es demasiado grande.")
        except ValueError as error:
            informe.errores.append({"fila": numero, "mensaje": str(error)})
            continue
        clave = (almacen.pk, producto.pk)
        etiqueta = f"{producto.codigo} en {almacen.codigo}"
        if clave in con_historial:
            informe.repetidos.append(
                {
                    "fila": numero,
                    "documento": etiqueta,
                    "motivo": "Ya tiene movimientos en ese almacén (use un ajuste).",
                }
            )
        elif clave in vistos:
            informe.repetidos.append(
                {
                    "fila": numero,
                    "documento": etiqueta,
                    "motivo": f"Repetido en la fila {vistos[clave]} del archivo.",
                }
            )
        else:
            vistos[clave] = numero
            informe.filas.append(FilaValida(numero, producto, almacen, cantidad, costo, ubicacion))
    return informe


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------
def importar(empresa: Empresa, fecha: date, archivo) -> Informe:
    """Valida de nuevo y crea los movimientos de saldo inicial (todos o ninguno)."""
    with transaction.atomic():
        # Con el cerrojo de la empresa tomado nadie puede mover stock mientras se valida e importa.
        numeracion.bloquear(empresa)
        informe = validar(empresa, fecha, archivo)
        if not informe.filas:
            return informe
        por_almacen: dict[int, list[FilaValida]] = defaultdict(list)
        for fila in informe.filas:
            por_almacen[fila.almacen.pk].append(fila)
        for filas in por_almacen.values():
            for inicio in range(0, len(filas), MAX_LINEAS):
                trozo = filas[inicio : inicio + MAX_LINEAS]
                registrar_movimiento(
                    empresa=empresa,
                    almacen=trozo[0].almacen,
                    tipo=TipoMovimiento.ENTRADA,
                    origen=OrigenMovimiento.SALDO_INICIAL,
                    fecha=fecha,
                    lineas=[LineaNueva(f.producto, f.cantidad, f.costo) for f in trozo],
                    observacion="Carga inicial desde archivo",
                    referencia_tipo="importacion",
                )
        for fila in informe.filas:
            if fila.ubicacion is not None:
                ubicaciones.asignar_ubicacion(
                    empresa=empresa,
                    almacen_id=fila.almacen.pk,
                    producto_id=fila.producto.pk,
                    ubicacion_id=fila.ubicacion.pk,
                )
        registrar(
            "inventario.saldo_inicial_importado",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Saldo inicial importado: {informe.validas} productos",
            detalle={
                "fecha": fecha,
                "filas": informe.total,
                "productos": informe.validas,
                "movimientos": informe.movimientos,
                "con_error": len(informe.errores),
                "omitidos": len(informe.repetidos),
                "con_ubicacion": sum(1 for f in informe.filas if f.ubicacion is not None),
                "valor_total": sum((f.valor for f in informe.filas), Decimal("0")),
                "archivo": (getattr(archivo, "name", "") or "")[:80],
            },
        )
    logger.info(
        "saldo_inicial_importado",
        extra={"empresa_id": empresa.pk, "productos": informe.validas},
    )
    return informe


# ---------------------------------------------------------------------------
# Plantilla
# ---------------------------------------------------------------------------
def plantilla_xlsx(empresa: Empresa) -> bytes:
    """Excel con los productos del catálogo ya listados: solo falta llenar cantidad y costo."""
    almacenes = list(
        Almacen.objects.filter(empresa=empresa, estado=EstadoRegistro.ACTIVO).order_by("codigo")
    )
    por_defecto = almacenes[0].codigo if len(almacenes) == 1 else ""
    productos = list(
        Producto.objects.filter(
            tipo=TipoProducto.BIEN, controla_stock=True, estado=EstadoRegistro.ACTIVO
        ).order_by("nombre", "id")[: MAX_PLANTILLA + 1]
    )
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Saldo inicial"
    fondo = PatternFill("solid", fgColor="D9DEE8")
    for i, columna in enumerate(COLUMNAS, start=1):
        celda = _poner(hoja, 1, i, columna.titulo, negrita=True)
        celda.fill = fondo
    for fila, producto in enumerate(productos[:MAX_PLANTILLA], start=2):
        _poner(hoja, fila, 1, producto.codigo)
        _poner(hoja, fila, 2, producto.nombre)
        _poner(hoja, fila, 3, por_defecto)
    for letra, ancho in zip("ABCDEF", [20, 44, 18, 14, 28, 22], strict=True):
        hoja.column_dimensions[letra].width = ancho
    hoja.freeze_panes = "A2"

    guia = libro.create_sheet("Instrucciones")
    textos = [
        f"Saldo inicial de {empresa.razon_social} (RUC {empresa.ruc})",
        "1. Llene Cantidad y Costo unitario (en soles, sin IGV) de los productos que tiene.",
        "2. Borre las filas de los productos que no tiene en stock; no hace falta ponerles 0.",
        "3. Código del almacén: "
        + (
            f"déjelo como está ({por_defecto})."
            if por_defecto
            else "escriba el código de cada almacén ("
            + ", ".join(a.codigo for a in almacenes)
            + ")."
        ),
        "4. La columna Producto es solo para que reconozca cada fila; el sistema usa el Código.",
        "5. Cada producto se carga una sola vez por almacén. Para corregir después, use un ajuste.",
        "6. La cantidad admite hasta 3 decimales y el costo hasta 6. Sin separador de miles.",
        "7. Ubicación (opcional): el código de la ubicación del almacén, por ejemplo V1 o A-03. "
        "Debe existir en Mantenimiento → Ubicaciones; vacío, deja al producto como está.",
    ]
    if len(productos) > MAX_PLANTILLA:
        textos.append(f"Nota: esta plantilla trae los primeros {MAX_PLANTILLA} productos.")
    for i, texto in enumerate(textos, start=1):
        _poner(guia, i, 1, texto, negrita=(i == 1))
    guia.column_dimensions["A"].width = 110
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
