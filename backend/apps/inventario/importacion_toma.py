"""Importación del conteo de una toma de inventario desde un Excel (.xlsx).

Sirve para traer un conteo que ya se hizo fuera del sistema (una hoja de cálculo): se sube el
archivo, el sistema lo REVISA entero sin guardar nada y devuelve un informe; si convence, se
vuelve a subir y se IMPORTAN solo las filas buenas, todas o ninguna.

Reglas (pensadas para no dar por bueno un conteo dudoso):

* Solo cuentan las filas que tienen cantidad en la columna del conteo («STOCK INVENT.»); una celda
  vacía es «todavía no se cuenta», nunca un 0.
* Un 0 de un producto con stock NO se importa salvo que se pida: en hojas de cálculo suele
  significar «no lo encontré» y no «no hay». Queda pendiente para contarlo bien.
* Un producto que ya tiene conteo en la toma no se toca (nada se sobrescribe).
* Solo se importa lo que se empareja con UN producto de la toma. Lo demás se informa fila por fila.
* Cada conteo lleva su fecha y hora reales (columnas FECHA y HORA FIN). El ajuste futuro descuenta
  lo que ventas y compras movieron entre ese momento y el corte, así un conteo de días atrás no
  se confunde con faltantes. Sin fecha se asume que se contó al momento del corte.
* El archivo es entrada no confiable: tamaño y filas acotados, y solo se leen valores.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.tenant import obtener_contexto
from apps.mantenimiento.importacion import TAMANO_MAXIMO, ErrorImportacion, _filas_xlsx, _plano
from apps.mantenimiento.models import Producto, TipoProducto

from . import numeracion, tomas
from .exceptions import ConteoInvalido
from .models import (
    ConteoToma,
    DetalleToma,
    EstadoFisico,
    EstadoToma,
    TomaInventario,
    TurnoToma,
)

logger = logging.getLogger(__name__)

FILAS_MAXIMAS = 5000
FILAS_BUSCANDO_ENCABEZADO = 20
DETALLE_MOSTRADO = 100
MODOS = ("automatico", "codigo")

# Encabezados que se reconocen (ya sin tildes, en minúsculas y sin signos).
_ALIAS = {
    "conteo": ("stock invent", "stock inventariado", "conteo", "cantidad contada", "contado"),
    "descripcion": ("prod descripcion", "descripcion", "producto", "nombre"),
    "barras": ("prod codigo barra", "codigo de barras", "codigo barra", "barras"),
    "codigo": ("codigo", "cod", "codigo producto", "codigo del sistema"),
    "fecha": ("fecha",),
    "turno": ("turno",),
    "hora_inicio": ("hora inicio",),
    "hora_fin": ("hora fin",),
    "nota": ("nota", "observacion", "observaciones"),
}
_CAMPO_DE = {alias: campo for campo, alias_del_campo in _ALIAS.items() for alias in alias_del_campo}
_IDENTIFICADORES = ("descripcion", "barras", "codigo")
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_HORA = re.compile(r"(\d{1,2}):(\d{2})")
_TURNOS = {
    "manana": TurnoToma.Turno.MANANA,
    "tarde": TurnoToma.Turno.TARDE,
    "manana y tarde": TurnoToma.Turno.MANANA_Y_TARDE,
}

# Categorías de lo que NO se importa, en el orden en que se muestran.
CATEGORIAS = {
    "ceros": "Contados en 0 (se dejan pendientes)",
    "no_encontrados": "No se encontró el producto",
    "ambiguos": "Coincide con varios productos",
    "fuera_de_toma": "El producto no está en esta toma",
    "ya_contados": "Ya tienen conteo en la toma",
    "duplicados": "Repetidos en el archivo",
    "invalidos": "Datos no válidos",
}


@dataclass(frozen=True, slots=True)
class Item:
    """Un conteo listo para importar."""

    fila: int
    detalle: DetalleToma
    cantidad: Decimal
    nota: str
    instante: datetime | None
    turno: tuple | None


@dataclass
class Informe:
    total: int = 0  # filas con datos debajo del encabezado
    sin_conteo: int = 0
    items: list[Item] = field(default_factory=list)
    problemas: dict[str, list[dict]] = field(
        default_factory=lambda: {clave: [] for clave in CATEGORIAS}
    )
    ignoradas: list[str] = field(default_factory=list)

    @property
    def con_conteo(self) -> int:
        return self.total - self.sin_conteo

    @property
    def turnos(self) -> int:
        return len({i.turno for i in self.items if i.turno is not None})

    def anotar(self, categoria: str, fila: int, texto: str, motivo: str) -> None:
        self.problemas[categoria].append({"fila": fila, "texto": texto[:80], "motivo": motivo})

    def como_dict(self) -> dict:
        return {
            "total": self.total,
            "con_conteo": self.con_conteo,
            "sin_conteo": self.sin_conteo,
            "a_importar": len(self.items),
            "turnos": self.turnos,
            "columnas_ignoradas": self.ignoradas,
            "categorias": {
                clave: {
                    "titulo": CATEGORIAS[clave],
                    "cantidad": len(filas),
                    "detalle": filas[:DETALLE_MOSTRADO],
                }
                for clave, filas in self.problemas.items()
                if filas
            },
        }


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------
def _leer(archivo) -> tuple[list[tuple[int, dict]], list[str]]:
    """``([(número_de_fila, {campo: texto})], columnas_ignoradas)`` de la primera hoja."""
    if archivo.size > TAMANO_MAXIMO:
        raise ErrorImportacion("El archivo pesa más de 2 MB.")
    if not (archivo.name or "").lower().endswith(".xlsx"):
        raise ErrorImportacion("Sube un archivo Excel (.xlsx).")
    filas = _filas_xlsx(archivo, FILAS_MAXIMAS)

    encabezado = None
    for indice, fila in enumerate(filas[:FILAS_BUSCANDO_ENCABEZADO]):
        columnas = {}
        for posicion, titulo in enumerate(fila):
            campo = _CAMPO_DE.get(_plano(titulo))
            if campo and campo not in columnas.values():
                columnas[posicion] = campo
        if "conteo" in columnas.values() and any(c in columnas.values() for c in _IDENTIFICADORES):
            encabezado = (indice, fila, columnas)
            break
    if encabezado is None:
        raise ErrorImportacion(
            "No se encontró el encabezado del conteo. El archivo debe tener la columna "
            "«STOCK INVENT.» y, al menos, la descripción, el código de barras o el código "
            "del producto."
        )
    indice, titulos, columnas = encabezado
    ignoradas = [t for p, t in enumerate(titulos) if t and p not in columnas]
    datos = []
    for posicion in range(indice + 1, len(filas)):
        fila = filas[posicion]
        if not any(fila):
            continue
        datos.append(
            (
                posicion + 1,
                {campo: fila[p] if p < len(fila) else "" for p, campo in columnas.items()},
            )
        )
    if len(datos) > FILAS_MAXIMAS:
        raise ErrorImportacion(f"El archivo tiene más de {FILAS_MAXIMAS} filas.")
    if not datos:
        raise ErrorImportacion("El archivo no tiene filas de datos debajo del encabezado.")
    return datos, ignoradas


def _fecha(texto: str) -> date | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    for patron, orden in (
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", "aaaammdd"),
        (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", "ddmmaaaa"),
    ):
        coincide = re.match(patron, texto)
        if coincide:
            a, b, c = (int(x) for x in coincide.groups())
            try:
                return date(a, b, c) if orden == "aaaammdd" else date(c, b, a)
            except ValueError:
                break
    raise ValueError(f"La fecha «{texto[:20]}» no es válida (use día/mes/año).")


def _hora(texto: str) -> time | None:
    coincide = _HORA.search(texto or "")
    if not coincide:
        return None
    hora, minuto = int(coincide.group(1)), int(coincide.group(2))
    return time(hora, minuto) if hora < 24 and minuto < 60 else None


def _clave_barras(texto: str) -> str:
    return re.sub(r"\s+", "", texto or "").upper()


def _clave_codigo(texto: str) -> str:
    limpio = (texto or "").strip().upper()
    return str(int(limpio)) if limpio.isdigit() else limpio  # 000123 y 123 son el mismo código


# ---------------------------------------------------------------------------
# Revisión (emparejar y validar fila por fila)
# ---------------------------------------------------------------------------
def _indices(productos) -> tuple[dict, dict, dict]:
    por_barras, por_nombre, por_codigo = defaultdict(set), defaultdict(set), defaultdict(set)
    for pk, codigo, nombre, barras, fabricante in productos:
        for texto in (barras, fabricante):
            if texto:
                por_barras[_clave_barras(texto)].add(pk)
        por_nombre[_plano(nombre)].add(pk)
        por_codigo[_clave_codigo(codigo)].add(pk)
    return por_barras, por_nombre, por_codigo


def armar(toma: TomaInventario, archivo, modo: str, importar_ceros: bool) -> Informe:
    """Lee el archivo y lo cruza con la toma, SIN guardar nada."""
    if modo not in MODOS:
        raise ErrorImportacion("El modo de emparejar no es válido.")
    filas, ignoradas = _leer(archivo)
    informe = Informe(total=len(filas), ignoradas=ignoradas)

    detalles = {
        d.producto_id: d
        for d in DetalleToma.objects.filter(toma=toma).select_related("producto__unidad")
    }
    por_barras, por_nombre, por_codigo = _indices(
        Producto.objects.filter(tipo=TipoProducto.BIEN).values_list(
            "pk", "codigo", "nombre", "codigo_barras", "codigo_fabricante"
        )
    )

    def candidatos(crudo: dict) -> set[int]:
        if modo == "codigo":
            clave = _clave_codigo(crudo.get("codigo", ""))
            return por_codigo.get(clave, set()) if clave else set()
        clave = _clave_barras(crudo.get("barras", ""))
        if clave and por_barras.get(clave):
            return por_barras[clave]
        nombre = _plano(crudo.get("descripcion", ""))
        return por_nombre.get(nombre, set()) if nombre else set()

    ahora = timezone.now()
    por_detalle: dict[int, list[Item]] = defaultdict(list)
    for numero, crudo in filas:
        texto_conteo = (crudo.get("conteo") or "").strip()
        etiqueta = crudo.get("descripcion") or crudo.get("barras") or crudo.get("codigo") or ""
        if not texto_conteo:
            informe.sin_conteo += 1
            continue
        if not _NUMERO.fullmatch(texto_conteo):
            informe.anotar(
                "invalidos", numero, etiqueta, f"«{texto_conteo[:20]}» no es una cantidad."
            )
            continue
        encontrados = candidatos(crudo)
        if not encontrados:
            informe.anotar("no_encontrados", numero, etiqueta, "Ningún producto coincide.")
            continue
        if len(encontrados) > 1:
            informe.anotar(
                "ambiguos", numero, etiqueta, f"Coincide con {len(encontrados)} productos."
            )
            continue
        detalle = detalles.get(next(iter(encontrados)))
        if detalle is None:
            informe.anotar(
                "fuera_de_toma",
                numero,
                etiqueta,
                "Existe en el catálogo pero no está en la toma "
                "(sin stock, excluido o de otra categoría).",
            )
            continue
        try:
            cantidad = tomas._cantidad_valida(
                Decimal(texto_conteo.replace(",", ".")), detalle.producto
            )
        except ConteoInvalido as error:
            informe.anotar("invalidos", numero, etiqueta, error.mensaje)
            continue
        if detalle.cantidad_contada is not None:
            informe.anotar("ya_contados", numero, etiqueta, "Ya tiene conteo; no se sobrescribe.")
            continue
        if cantidad == 0 and not importar_ceros:
            informe.anotar(
                "ceros",
                numero,
                etiqueta,
                "Contado en 0: puede ser «no lo encontré». Queda pendiente para contarlo bien.",
            )
            continue
        try:
            instante, turno = _momento(crudo, ahora)
        except ValueError as error:
            informe.anotar("invalidos", numero, etiqueta, str(error))
            continue
        nota = " ".join((crudo.get("nota") or "").split())[:250]
        por_detalle[detalle.producto_id].append(
            Item(numero, detalle, cantidad, nota, instante, turno)
        )

    for items in por_detalle.values():
        if len(items) > 1:
            for item in items:
                informe.anotar(
                    "duplicados",
                    item.fila,
                    item.detalle.producto.nombre,
                    f"El producto aparece {len(items)} veces en el archivo; no se sabe cuál vale.",
                )
        else:
            informe.items.append(items[0])
    informe.items.sort(key=lambda i: i.fila)
    return informe


def _momento(crudo: dict, ahora: datetime) -> tuple[datetime | None, tuple | None]:
    """Cuándo se contó (de FECHA y HORA FIN) y el turno al que pertenece, si se puede saber."""
    dia = _fecha(crudo.get("fecha", ""))
    if dia is None:
        return None, None  # sin fecha: se asume que se contó al corte
    inicio, fin = _hora(crudo.get("hora_inicio", "")), _hora(crudo.get("hora_fin", ""))
    instante = timezone.make_aware(datetime.combine(dia, fin or inicio or time(12, 0)))
    if instante > ahora:
        raise ValueError("La fecha y hora del conteo están en el futuro.")
    codigo_turno = _TURNOS.get(_plano(crudo.get("turno", "")))
    turno = (dia, codigo_turno, inicio, fin) if codigo_turno and inicio else None
    return instante, turno


def revisar(
    toma_id: int, archivo, *, modo: str = "automatico", importar_ceros: bool = False
) -> Informe:
    """El informe de lo que se importaría, sin guardar nada."""
    toma = TomaInventario.objects.filter(pk=toma_id).first()
    if toma is None:
        raise ErrorImportacion("La toma no existe.")
    tomas._exigir_estado(toma, (EstadoToma.ABIERTA, EstadoToma.EN_CONTEO), "importar conteos")
    return armar(toma, archivo, modo, importar_ceros)


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------
@transaction.atomic
def importar(
    toma_id: int, archivo, *, modo: str = "automatico", importar_ceros: bool = False
) -> Informe:
    """Vuelve a revisar todo y guarda los conteos válidos (todos o ninguno)."""
    toma = tomas._bloquear(toma_id)
    tomas._exigir_estado(toma, (EstadoToma.ABIERTA, EstadoToma.EN_CONTEO), "importar conteos")
    numeracion.bloquear(toma.empresa)  # nadie mueve stock mientras se corrige por lo movido
    informe = armar(toma, archivo, modo, importar_ceros)
    if not informe.items:
        return informe

    # Cuándo se contó cada producto: la fecha del archivo, o el corte si no la trae.
    instantes = {i.detalle.producto_id: i.instante or toma.fecha_corte for i in informe.items}
    netos = tomas.netos_hasta(toma, instantes)
    turnos = {
        clave: TurnoToma.objects.create(
            empresa=toma.empresa,
            toma=toma,
            fecha=clave[0],
            turno=clave[1],
            hora_inicio=clave[2],
            hora_fin=clave[3],
            equipo="Importado del Excel",
        )
        for clave in sorted({i.turno for i in informe.items if i.turno}, key=str)
    }
    conteos, detalles = [], []
    for item in informe.items:
        d = item.detalle
        instante = instantes[d.producto_id]
        esperado = d.stock_sistema + netos.get(d.producto_id, Decimal("0"))
        tomas._poner_conteo(
            toma,
            d,
            item.cantidad,
            1,
            nota=item.nota,
            estado_fisico=EstadoFisico.BUENO,
            esperado=esperado,
            instante=instante,
        )
        detalles.append(d)
        conteos.append(
            ConteoToma(
                empresa=toma.empresa,
                detalle=d,
                numero=1,
                cantidad=item.cantidad,
                turno=turnos.get(item.turno),
                nota=item.nota,
                importado=True,
            )
        )
    ConteoToma.objects.bulk_create(conteos, batch_size=500)
    DetalleToma.objects.bulk_update(
        detalles,
        [
            "cantidad_contada",
            "diferencia",
            "importe_diferencia",
            "resultado",
            "estado_fisico",
            "nota",
            "numero_conteos",
            "requiere_reconteo",
            "contado_por_id",
            "contado_en",
        ],
        batch_size=500,
    )
    if toma.estado == EstadoToma.ABIERTA:
        toma.estado = EstadoToma.EN_CONTEO
        toma.save(update_fields=["estado"])
    contexto = obtener_contexto()
    registrar(
        "inventario.toma_conteo_importado",
        recurso_tipo="toma_inventario",
        recurso_id=toma.pk,
        empresa_id=toma.empresa_id,
        resumen=f"Toma N° {toma.numero:06d}: {len(conteos)} conteos importados de un Excel",
        detalle={
            "archivo": (getattr(archivo, "name", "") or "")[:80],
            "modo": modo,
            "filas": informe.total,
            "importados": len(conteos),
            "con_conteo": informe.con_conteo,
            "omitidos": sum(len(v) for v in informe.problemas.values()),
            "turnos": len(turnos),
            "usuario": str(contexto.usuario_id) if contexto else None,
        },
    )
    logger.info(
        "toma_conteo_importado",
        extra={"empresa_id": toma.empresa_id, "toma_id": toma.pk, "importados": len(conteos)},
    )
    return informe
