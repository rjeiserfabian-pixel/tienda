"""Datos de «Arma tu PC»: qué productos están completos, y carga masiva por Excel.

El armador solo puede asegurar que dos piezas son compatibles si ambas tienen los datos que las
reglas comparan (socket, tipo de memoria…). Aquí se calcula, por espacio y categoría, qué productos
publicados no los tienen todavía, y se permite completarlos de una vez: se baja un Excel con los
productos incompletos, se llena y se vuelve a subir (primero una revisión, luego se aplica).

Reglas de la carga: se busca cada producto por su CÓDIGO; solo se escriben celdas con contenido
(nunca se borra un dato existente); cada valor se valida contra la plantilla de la categoría, igual
que al editar el producto a mano, y una fila con error no se aplica.
"""

import io
import logging
import zipfile

from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.mantenimiento import especificaciones
from apps.mantenimiento.models import CampoEspecificacion, Categoria, EstadoRegistro, Producto

from . import armador, catalogo
from .exceptions import DatosInvalidos

logger = logging.getLogger(__name__)

MAX_FILAS = 2000
MAX_LISTA = 200
MAX_ARCHIVO = 5 * 1024 * 1024
FIJAS = ("Código", "Producto", "Categoría")


def _vacio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


# Datos que se aceptan "uno u otro": basta con tener cualquiera de cada grupo (regla → alias).
ALTERNATIVAS = {"fuente_potencia": ("cpu_turbo", "cpu_tdp")}


def _claves_por_espacio(config) -> dict[str, dict[str, str]]:
    """Espacio → {clave de especificación: para qué regla se necesita} (solo reglas activas)."""
    efectivas = armador.claves_efectivas(config)
    salida: dict[str, dict[str, str]] = {}
    for regla in armador.reglas_activas(config):
        for alias, (espacio, _) in regla.claves.items():
            clave = efectivas[regla.id][alias]
            salida.setdefault(espacio, {}).setdefault(clave, regla.nombre)
    return salida


def _grupos_alternativos(config, espacio: str) -> list[tuple[str, ...]]:
    efectivas = armador.claves_efectivas(config)
    grupos = []
    for regla in armador.reglas_activas(config):
        aliases = ALTERNATIVAS.get(regla.id)
        if aliases and all(regla.claves[a][0] == espacio for a in aliases):
            grupos.append(tuple(efectivas[regla.id][a] for a in aliases))
    return grupos


def _faltan(valores: dict, claves, grupos) -> list[str]:
    """Las claves que faltan; en un grupo de alternativas solo falta si no hay NINGUNA."""
    enlazadas = {k for g in grupos for k in g}
    faltan = [k for k in claves if k not in enlazadas and _vacio(valores.get(k))]
    for g in grupos:
        if all(_vacio(valores.get(k)) for k in g):
            faltan.append(g[0])
    return faltan


def _productos(organizacion_id: int, categoria_ids):
    return (
        Producto.objects.sin_ambito()
        .filter(
            organizacion_id=organizacion_id,
            publicado_web=True,
            estado=EstadoRegistro.ACTIVO,
            categoria_id__in=categoria_ids,
        )
        .select_related("categoria")
        .order_by("categoria__nombre", "nombre")
    )


def _campos(categoria_ids) -> dict[int, dict[str, CampoEspecificacion]]:
    por_categoria: dict[int, dict[str, CampoEspecificacion]] = {}
    filas = CampoEspecificacion.objects.sin_ambito().filter(
        categoria_id__in=categoria_ids, estado=EstadoRegistro.ACTIVO
    )
    for c in filas.order_by("orden", "id"):
        por_categoria.setdefault(c.categoria_id, {})[c.clave] = c
    return por_categoria


def informe(organizacion_id: int) -> dict:
    """Cuántos productos de cada espacio están completos y cuáles faltan, con lo que les falta."""
    config = armador.configuracion_vigente(organizacion_id)
    necesarias = _claves_por_espacio(config)
    espacios_salida = []
    incompletos = []
    categorias_todas = {c for e in armador.espacios_con_categorias(config) for c in e["categorias"]}
    campos = _campos(categorias_todas)
    nombres_categoria = dict(
        Categoria.objects.sin_ambito().filter(pk__in=categorias_todas).values_list("pk", "nombre")
    )
    for espacio in armador.espacios_con_categorias(config):
        claves = necesarias.get(espacio["clave"], {})
        grupos = _grupos_alternativos(config, espacio["clave"])
        total = completos = 0
        faltan_por_clave = dict.fromkeys(claves, 0)
        sin_campo = []
        for categoria_id in espacio["categorias"]:
            existentes = campos.get(categoria_id, {})
            for clave, regla in claves.items():
                if clave not in existentes:
                    sin_campo.append(
                        {
                            "categoria": nombres_categoria.get(categoria_id, ""),
                            "clave": clave,
                            "regla": regla,
                        }
                    )
        for p in _productos(organizacion_id, espacio["categorias"]):
            total += 1
            faltan = _faltan(p.especificaciones or {}, claves, grupos)
            for k in faltan:
                faltan_por_clave[k] += 1
            if not faltan:
                completos += 1
            else:
                incompletos.append(
                    {
                        "id": p.pk,
                        "codigo": p.codigo,
                        "nombre": p.nombre,
                        "espacio": espacio["nombre"],
                        "categoria": p.categoria.nombre,
                        "faltan": [
                            campos.get(p.categoria_id, {}).get(k).nombre
                            if campos.get(p.categoria_id, {}).get(k)
                            else k
                            for k in faltan
                        ],
                    }
                )
        espacios_salida.append(
            {
                "clave": espacio["clave"],
                "nombre": espacio["nombre"],
                "total": total,
                "completos": completos,
                "incompletos": total - completos,
                "faltan_por_dato": [
                    {"clave": k, "regla": claves[k], "faltan": n}
                    for k, n in faltan_por_clave.items()
                ],
                "categorias_sin_el_campo": sin_campo,
            }
        )
    return {
        "activo": bool(config and config.activo),
        "espacios": espacios_salida,
        "total_incompletos": len(incompletos),
        "incompletos": incompletos[:MAX_LISTA],
        "hay_mas": len(incompletos) > MAX_LISTA,
    }


# ---------------------------------------------------------------------------
# Excel para completar
# ---------------------------------------------------------------------------
def plantilla_xlsx(
    organizacion_id: int, *, solo_incompletos: bool = True, espacio: str = ""
) -> bytes:
    """Un Excel con los productos y una columna por cada dato que el armador necesita."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    config = armador.configuracion_vigente(organizacion_id)
    necesarias = _claves_por_espacio(config)
    espacios = [
        e for e in armador.espacios_con_categorias(config) if not espacio or e["clave"] == espacio
    ]
    categorias = {c for e in espacios for c in e["categorias"]}
    campos = _campos(categorias)
    # Un dato = una columna por NOMBRE (categorías distintas pueden llamarlo igual).
    columnas: list[str] = []
    for e in espacios:
        for categoria_id in e["categorias"]:
            for clave in necesarias.get(e["clave"], {}):
                campo = campos.get(categoria_id, {}).get(clave)
                if campo and campo.nombre not in columnas:
                    columnas.append(campo.nombre)
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Productos"
    hoja.append([*FIJAS, *columnas])
    for celda in hoja[1]:
        celda.font = Font(bold=True)
        celda.fill = PatternFill("solid", fgColor="DDE7FF")
    filas = 0
    for e in espacios:
        claves = necesarias.get(e["clave"], {})
        for p in _productos(organizacion_id, e["categorias"]):
            valores = p.especificaciones or {}
            if solo_incompletos and not _faltan(
                valores, claves, _grupos_alternativos(config, e["clave"])
            ):
                continue
            por_nombre = {c.nombre: c for c in campos.get(p.categoria_id, {}).values()}
            fila = [p.codigo, p.nombre, p.categoria.nombre]
            for nombre in columnas:
                campo = por_nombre.get(nombre)
                valor = valores.get(campo.clave) if campo else None
                # Lo que no aplica a esta categoría queda en gris con un guion (no se escribe).
                fila.append("" if _vacio(valor) else str(valor) if campo else "—")
            hoja.append(fila)
            filas += 1
            if filas >= MAX_FILAS:
                break
    hoja.freeze_panes = "D2"
    hoja.column_dimensions["A"].width = 14
    hoja.column_dimensions["B"].width = 48
    hoja.column_dimensions["C"].width = 24
    ayuda = libro.create_sheet("Cómo llenarlo")
    for linea in (
        "Completa solo las celdas vacías de cada producto.",
        "No cambies el código ni los títulos de las columnas.",
        "Las celdas con «—» no aplican a esa categoría: déjalas así.",
        "Las listas aceptan solo las opciones que la plantilla de la categoría permite.",
        "Los números van sin unidad (la unidad ya está en el dato).",
        "Lo que no escribas no se modifica: nunca se borra un dato existente.",
    ):
        ayuda.append([linea])
    ayuda.column_dimensions["A"].width = 90
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _leer_xlsx(archivo) -> list[list]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    if getattr(archivo, "size", 0) > MAX_ARCHIVO:
        raise DatosInvalidos("El archivo pesa más de 5 MB.")
    try:
        libro = load_workbook(archivo, read_only=True, data_only=True)
        hoja = libro.worksheets[0]
        filas = []
        for fila in hoja.iter_rows(values_only=True):
            filas.append(list(fila))
            if len(filas) > MAX_FILAS + 1:
                raise DatosInvalidos(f"El archivo tiene más de {MAX_FILAS} filas.")
        libro.close()
    except (zipfile.BadZipFile, InvalidFileException, KeyError, IndexError, ValueError, OSError):
        raise DatosInvalidos("No se pudo leer el archivo. Sube un Excel (.xlsx) válido.") from None
    return filas


def _texto(celda) -> str:
    if celda is None:
        return ""
    if isinstance(celda, float) and celda.is_integer():
        return str(int(celda))
    return " ".join(str(celda).split())


def cargar(organizacion_id: int, archivo, *, aplicar: bool, usuario=None) -> dict:
    """Revisa (``aplicar=False``) o aplica el Excel. Devuelve el detalle por fila."""
    filas = _leer_xlsx(archivo)
    if not filas:
        raise DatosInvalidos("El archivo está vacío.")
    encabezado = [_texto(c) for c in filas[0]]
    if "Código" not in encabezado:
        raise DatosInvalidos("Falta la columna «Código». Descarga la plantilla y úsala tal cual.")
    pos_codigo = encabezado.index("Código")
    datos_cols = {
        i: nombre for i, nombre in enumerate(encabezado) if nombre and nombre not in FIJAS
    }
    resultado = {"filas": 0, "con_cambios": 0, "sin_cambios": 0, "con_error": 0, "detalle": []}
    pendientes: list[tuple[Producto, dict]] = []
    vistos: set[str] = set()
    for numero, fila in enumerate(filas[1:], start=2):
        codigo = _texto(fila[pos_codigo] if pos_codigo < len(fila) else "").upper().replace(" ", "")
        if not codigo:
            continue
        resultado["filas"] += 1
        if codigo in vistos:
            resultado["con_error"] += 1
            resultado["detalle"].append(
                {
                    "fila": numero,
                    "codigo": codigo,
                    "error": "El código está repetido en el archivo.",
                }
            )
            continue
        vistos.add(codigo)
        productos = list(
            Producto.objects.sin_ambito()
            .filter(organizacion_id=organizacion_id, codigo=codigo)
            .select_related("categoria")[:2]
        )
        if len(productos) != 1:
            resultado["con_error"] += 1
            resultado["detalle"].append(
                {
                    "fila": numero,
                    "codigo": codigo,
                    "error": "No existe ese código."
                    if not productos
                    else "Hay más de un producto con ese código.",
                }
            )
            continue
        producto = productos[0]
        por_nombre = {
            c.nombre.lower(): c
            for c in especificaciones.campos_de(producto.categoria, solo_activos=True)
        }
        nuevos: dict = {}
        for i, nombre in datos_cols.items():
            texto = _texto(fila[i] if i < len(fila) else "")
            if not texto or texto == "—":
                continue
            campo = por_nombre.get(nombre.lower())
            if campo is None:
                continue  # no aplica a esta categoría
            nuevos[campo.clave] = texto
        if not nuevos:
            resultado["sin_cambios"] += 1
            continue
        try:
            validos = especificaciones.validar_valores(producto.categoria, nuevos)
        except Exception as error:  # noqa: BLE001 - el detalle del error llega como validación
            detalle = getattr(error, "detail", None)
            mensaje = (
                "; ".join(str(v) for v in (detalle.get("especificaciones", {}) or {}).values())
                if isinstance(detalle, dict) and isinstance(detalle.get("especificaciones"), dict)
                else "Algún valor no es válido."
            )
            resultado["con_error"] += 1
            resultado["detalle"].append({"fila": numero, "codigo": codigo, "error": mensaje})
            continue
        cambios = {
            k: v for k, v in validos.items() if (producto.especificaciones or {}).get(k) != v
        }
        if not cambios:
            resultado["sin_cambios"] += 1
            continue
        resultado["con_cambios"] += 1
        resultado["detalle"].append(
            {"fila": numero, "codigo": codigo, "nombre": producto.nombre, "datos": len(cambios)}
        )
        pendientes.append((producto, cambios))
    resultado["detalle"] = resultado["detalle"][:MAX_LISTA]
    resultado["aplicado"] = False
    if aplicar and pendientes:
        with transaction.atomic():
            for producto, cambios in pendientes:
                actuales = dict(producto.especificaciones or {})
                actuales.update(cambios)
                producto.especificaciones = actuales
                producto.save(update_fields=["especificaciones", "actualizado_en"])
        registrar(
            "tienda.especificaciones_importadas",
            recurso_tipo="producto",
            recurso_id=0,
            organizacion_id=organizacion_id,
            resumen=f"Datos de Arma tu PC cargados por Excel en {len(pendientes)} productos",
            detalle={"productos": len(pendientes)},
        )
        catalogo.invalidar()
        resultado["aplicado"] = True
    return resultado
