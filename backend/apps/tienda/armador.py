"""«Arma tu PC»: espacios, reglas de compatibilidad y validación de un armado.

PRINCIPIO: nunca se afirma que algo es compatible sin dato. Cada regla compara valores que el
negocio cargó en las ESPECIFICACIONES de los productos (socket, tipo de memoria, factor de
forma…). Si a alguno de los dos productos le falta el dato, el resultado es ``NO_VERIFICABLE`` (se
avisa, no bloquea). Solo ``INCOMPATIBLE`` bloquea «agregar todo al carrito».

La configuración (qué categorías llenan cada espacio, qué reglas están activas y con qué claves de
especificación comparan) la edita el negocio en el panel; las reglas en sí son código revisado.
"""

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import carrito, catalogo
from .catalogo import Contexto
from .exceptions import DatosInvalidos
from .models import ConfiguracionArmador

COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
NO_VERIFICABLE = "NO_VERIFICABLE"
LIBRE = "LIBRE"  # nada con qué compararlo todavía
MAX_LINEAS = 30
MAX_CANDIDATOS = 600
# Prioridad al resumir: 0 es el peor resultado.
PRIORIDAD = {INCOMPATIBLE: 0, NO_VERIFICABLE: 1, COMPATIBLE: 2, LIBRE: 3}
# En las listas: primero lo que encaja, luego lo no verificable y al final lo que no encaja.
ORDEN_LISTA = {COMPATIBLE: 0, LIBRE: 0, NO_VERIFICABLE: 1, INCOMPATIBLE: 2}


# ---------------------------------------------------------------------------
# Espacios (fijos); el negocio elige las categorías de cada uno
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EspacioDef:
    clave: str
    nombre: str
    obligatorio: bool
    max_unidades: int
    ayuda: str


ESPACIOS: tuple[EspacioDef, ...] = (
    EspacioDef("procesador", "Procesador", True, 1, "El cerebro de tu PC."),
    EspacioDef("placa", "Placa madre", True, 1, "Conecta todas las piezas entre sí."),
    EspacioDef("ram", "Memoria RAM", True, 4, "Más memoria, más programas a la vez."),
    EspacioDef("almacenamiento", "Almacenamiento", True, 4, "Donde se guardan tus archivos."),
    EspacioDef("video", "Tarjeta de video", False, 1, "Para juegos, diseño y edición."),
    EspacioDef("fuente", "Fuente de poder", True, 1, "Da energía a toda la PC."),
    EspacioDef("gabinete", "Gabinete", True, 1, "La caja que contiene las piezas."),
    EspacioDef("refrigeracion", "Refrigeración", False, 1, "Mantiene fresco el procesador."),
    EspacioDef("monitor", "Monitor", False, 1, "La pantalla de tu equipo."),
    EspacioDef("perifericos", "Periféricos", False, 6, "Teclado, mouse y más."),
)
ESPACIO_POR_CLAVE = {e.clave: e for e in ESPACIOS}


# ---------------------------------------------------------------------------
# Valores de las especificaciones
# ---------------------------------------------------------------------------
def _valor(producto, clave: str):
    valor = (producto.especificaciones or {}).get(clave)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    return valor


def _norm(valor) -> str:
    """Mayúsculas y sin espacios, guiones ni guiones bajos: «Micro-ATX» y «micro atx» coinciden."""
    return re.sub(r"[\s\-_]", "", str(valor)).upper()


def _tokens(valor) -> set[str]:
    partes = re.split(r"[,;/|\n]| y ", str(valor))
    return {_norm(p) for p in partes if p.strip()}


def _num(valor) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return Decimal(str(valor).replace(",", "."))
    except InvalidOperation:
        return None


def _entero_inicial(valor) -> int | None:
    """«2 módulos (kit)» → 2."""
    m = re.match(r"\s*(\d+)", str(valor)) if valor is not None else None
    return int(m.group(1)) if m else None


def _corto(producto) -> str:
    nombre = producto.nombre
    return nombre if len(nombre) <= 60 else nombre[:57] + "…"


# ---------------------------------------------------------------------------
# Motor de reglas
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Resultado:
    regla: str
    estado: str
    mensaje: str
    productos: list[int] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "regla": self.regla,
            "estado": self.estado,
            "mensaje": self.mensaje,
            "productos": self.productos,
        }


class Evaluacion:
    """Un armado (espacio → [(producto, cantidad)]) y las claves de especificación en uso."""

    def __init__(self, seleccion: dict[str, list], claves: dict[str, dict[str, str]]):
        self.sel = seleccion
        self.claves = claves  # regla → alias → clave

    def items(self, espacio: str) -> list:
        return self.sel.get(espacio, [])

    def valor(self, regla: str, alias: str, producto):
        return _valor(producto, self.claves[regla][alias])

    def nombre_campo(self, regla: str, alias: str) -> str:
        return self.claves[regla][alias].replace("-", " ")


def _falta(regla: str, que: str, productos) -> Resultado:
    return Resultado(
        regla,
        NO_VERIFICABLE,
        f"No pudimos verificar {que}: falta ese dato en la ficha. Confírmalo con nosotros.",
        [p.pk for p in productos],
    )


def _pareja(
    ev: Evaluacion,
    regla: str,
    espacio_a: str,
    espacio_b: str,
    comparar: Callable[[object, object, Evaluacion], tuple[str, str] | None],
) -> list[Resultado]:
    """Aplica ``comparar(a, b)`` a cada pareja (a de ``espacio_a``, b de ``espacio_b``).

    ``comparar`` devuelve (estado, mensaje) o ``None`` si falta un dato.
    """
    salida = []
    for a, _ in ev.items(espacio_a):
        for b, _ in ev.items(espacio_b):
            r = comparar(a, b, ev)
            if r is None:
                salida.append(_falta(regla, f"{_corto(a)} con {_corto(b)}", [a, b]))
            else:
                salida.append(Resultado(regla, r[0], r[1], [a.pk, b.pk]))
    return salida


def _igual(regla, ea, aa, eb, ab, titulo):
    def comparar(a, b, ev):
        va, vb = ev.valor(regla, aa, a), ev.valor(regla, ab, b)
        if va is None or vb is None:
            return None
        if _norm(va) == _norm(vb):
            return COMPATIBLE, f"{titulo}: ambos usan {va}."
        return INCOMPATIBLE, f"{titulo}: {_corto(a)} es {va} y {_corto(b)} es {vb}. No encajan."

    return lambda ev: _pareja(ev, regla, ea, eb, comparar)


def _en_lista(regla, ea, aa, eb, ab, titulo):
    """El valor de A debe estar en la lista de B (texto separado por comas)."""

    def comparar(a, b, ev):
        va, lista = ev.valor(regla, aa, a), ev.valor(regla, ab, b)
        if va is None or lista is None:
            return None
        if _norm(va) in _tokens(lista):
            return COMPATIBLE, f"{titulo}: {_corto(b)} admite {va}."
        return INCOMPATIBLE, f"{titulo}: {_corto(b)} admite {lista}, y {_corto(a)} es {va}."

    return lambda ev: _pareja(ev, regla, ea, eb, comparar)


def _menor_igual(regla, ea, aa, eb, ab, titulo, unidad):
    """El número de A no puede pasar el de B."""

    def comparar(a, b, ev):
        va, vb = _num(ev.valor(regla, aa, a)), _num(ev.valor(regla, ab, b))
        if va is None or vb is None:
            return None
        if va <= vb:
            return COMPATIBLE, f"{titulo}: {va:g} {unidad} entra en el máximo de {vb:g} {unidad}."
        return (
            INCOMPATIBLE,
            f"{titulo}: {_corto(a)} mide {va:g} {unidad} y {_corto(b)} admite "
            f"hasta {vb:g} {unidad}.",
        )

    return lambda ev: _pareja(ev, regla, ea, eb, comparar)


def _ram_escritorio(ev: Evaluacion) -> list[Resultado]:
    r = "ram_escritorio"
    salida = []
    for p, _ in ev.items("ram"):
        formato = ev.valor(r, "formato", p)
        if formato is None:
            salida.append(_falta(r, f"si {_corto(p)} es para PC de escritorio", [p]))
        elif "SODIMM" in _norm(formato):
            salida.append(
                Resultado(
                    r,
                    INCOMPATIBLE,
                    f"{_corto(p)} es memoria para laptop (SODIMM), no para PC de escritorio.",
                    [p.pk],
                )
            )
        else:
            salida.append(
                Resultado(r, COMPATIBLE, f"{_corto(p)} es memoria para PC de escritorio.", [p.pk])
            )
    return salida


def _suma(ev, regla, espacio, alias_valor, convertir=_num):
    """Suma (valor × cantidad) del espacio; ``None`` si a alguno le falta el dato."""
    total = Decimal(0)
    for p, cantidad in ev.items(espacio):
        v = convertir(ev.valor(regla, alias_valor, p))
        if v is None:
            return None, [p]
        total += Decimal(v) * cantidad
    return total, []


def _ram_ranuras(ev: Evaluacion) -> list[Resultado]:
    r = "ram_ranuras"
    if not ev.items("ram") or not ev.items("placa"):
        return []
    salida = []
    modulos, faltan = _suma(ev, r, "ram", "modulos", _entero_inicial)
    for placa, _ in ev.items("placa"):
        ranuras = _num(ev.valor(r, "ranuras", placa))
        if modulos is None or ranuras is None:
            salida.append(_falta(r, "cuántos módulos de memoria caben", [placa, *faltan]))
        elif modulos <= ranuras:
            salida.append(
                Resultado(
                    r,
                    COMPATIBLE,
                    f"Tus {modulos:g} módulos caben en las {ranuras:g} ranuras de la placa.",
                    [placa.pk],
                )
            )
        else:
            salida.append(
                Resultado(
                    r,
                    INCOMPATIBLE,
                    f"Elegiste {modulos:g} módulos y la placa solo tiene {ranuras:g} ranuras.",
                    [placa.pk],
                )
            )
    return salida


def _ram_maximo(ev: Evaluacion) -> list[Resultado]:
    r = "ram_maximo"
    if not ev.items("ram") or not ev.items("placa"):
        return []
    salida = []
    total, faltan = _suma(ev, r, "ram", "capacidad")
    for placa, _ in ev.items("placa"):
        maximo = _num(ev.valor(r, "maximo", placa))
        if total is None or maximo is None:
            salida.append(_falta(r, "cuánta memoria acepta la placa", [placa, *faltan]))
        elif total <= maximo:
            salida.append(
                Resultado(
                    r,
                    COMPATIBLE,
                    f"{total:g} GB de memoria: la placa acepta hasta {maximo:g} GB.",
                    [placa.pk],
                )
            )
        else:
            salida.append(
                Resultado(
                    r,
                    INCOMPATIBLE,
                    f"Elegiste {total:g} GB de memoria y la placa acepta hasta {maximo:g} GB.",
                    [placa.pk],
                )
            )
    return salida


def _fuente_potencia(ev: Evaluacion) -> list[Resultado]:
    """La fuente debe cubrir procesador + tarjeta de video + 100 W para lo demás (estimado)."""
    r = "fuente_potencia"
    if not ev.items("fuente") or not ev.items("procesador"):
        return []
    salida = []
    for fuente, _ in ev.items("fuente"):
        potencia = _num(ev.valor(r, "potencia", fuente))
        cpus = []
        for cpu, _ in ev.items("procesador"):
            turbo = _num(ev.valor(r, "cpu_turbo", cpu))
            base = _num(ev.valor(r, "cpu_tdp", cpu))
            cpus.append(turbo if turbo is not None else base)
        gpus = [_num(ev.valor(r, "gpu_consumo", g)) for g, _ in ev.items("video")]
        if potencia is None or any(c is None for c in cpus) or any(g is None for g in gpus):
            productos = [
                fuente,
                *[p for p, _ in ev.items("procesador")],
                *[p for p, _ in ev.items("video")],
            ]
            salida.append(_falta(r, "si la fuente alcanza para tu armado", productos))
            continue
        necesaria = sum(cpus, Decimal(0)) + sum(gpus, Decimal(0)) + 100
        ids = [
            fuente.pk,
            *[p.pk for p, _ in ev.items("procesador")],
            *[p.pk for p, _ in ev.items("video")],
        ]
        if potencia >= necesaria:
            salida.append(
                Resultado(
                    r,
                    COMPATIBLE,
                    f"La fuente de {potencia:g} W cubre lo estimado ({necesaria:g} W).",
                    ids,
                )
            )
        else:
            salida.append(
                Resultado(
                    r,
                    INCOMPATIBLE,
                    f"Tu armado necesita unos {necesaria:g} W y la fuente es de {potencia:g} W. "
                    "Elige una de mayor potencia.",
                    ids,
                )
            )
    return salida


def _almacenamiento(regla: str, alias: str, etiqueta: str, es_tipo: Callable[[str], bool]):
    """Cuenta los discos de un tipo (M.2 o SATA) y los compara con lo que ofrece la placa."""

    def evaluar(ev: Evaluacion) -> list[Resultado]:
        discos, desconocidos = [], []
        for d, cantidad in ev.items("almacenamiento"):
            formato = ev.valor(regla, "formato", d)
            if formato is None:
                desconocidos.append(d)
            elif es_tipo(_norm(formato)):
                discos.append((d, cantidad))
        if not discos and not desconocidos:
            return []
        salida = []
        usados = sum(c for _, c in discos)
        for placa, _ in ev.items("placa"):
            disponibles = _num(ev.valor(regla, alias, placa))
            if disponibles is None or desconocidos:
                salida.append(
                    _falta(
                        regla,
                        f"si la placa tiene lugar para tus discos {etiqueta}",
                        [placa, *desconocidos],
                    )
                )
            elif usados <= disponibles:
                salida.append(
                    Resultado(
                        regla,
                        COMPATIBLE,
                        f"La placa tiene {disponibles:g} lugares {etiqueta} y usas {usados}.",
                        [placa.pk, *[d.pk for d, _ in discos]],
                    )
                )
            else:
                salida.append(
                    Resultado(
                        regla,
                        INCOMPATIBLE,
                        f"Elegiste {usados} discos {etiqueta}; la placa tiene {disponibles:g}.",
                        [placa.pk, *[d.pk for d, _ in discos]],
                    )
                )
        return salida

    return evaluar


@dataclass(frozen=True, slots=True)
class ReglaDef:
    id: str
    nombre: str
    descripcion: str
    claves: dict[str, tuple[str, str]]  # alias → (espacio, clave de especificación por defecto)
    evaluar: Callable[[Evaluacion], list[Resultado]]


def _reglas() -> tuple[ReglaDef, ...]:
    return (
        ReglaDef(
            "socket",
            "Socket del procesador y la placa",
            "El procesador debe encajar en la placa.",
            {"a": ("procesador", "socket"), "b": ("placa", "socket")},
            _igual("socket", "procesador", "a", "placa", "b", "Socket"),
        ),
        ReglaDef(
            "tipo_ram",
            "Tipo de memoria (DDR4, DDR5…)",
            "La memoria debe ser del tipo que acepta la placa.",
            {"a": ("placa", "tipo-de-ram"), "b": ("ram", "tipo")},
            _igual("tipo_ram", "placa", "a", "ram", "b", "Tipo de memoria"),
        ),
        ReglaDef(
            "ram_escritorio",
            "Memoria de escritorio",
            "La memoria SODIMM es de laptop y no sirve en una PC de escritorio.",
            {"formato": ("ram", "formato")},
            _ram_escritorio,
        ),
        ReglaDef(
            "ram_ranuras",
            "Ranuras de memoria",
            "Los módulos de memoria elegidos deben caber en la placa.",
            {"modulos": ("ram", "numero-de-modulos"), "ranuras": ("placa", "ranuras-de-memoria")},
            _ram_ranuras,
        ),
        ReglaDef(
            "ram_maximo",
            "Memoria máxima de la placa",
            "La suma de memoria no puede pasar lo que acepta la placa.",
            {"capacidad": ("ram", "capacidad"), "maximo": ("placa", "maximo-de-memoria")},
            _ram_maximo,
        ),
        ReglaDef(
            "factor_forma",
            "Tamaño de la placa y el gabinete",
            "El gabinete debe admitir el tamaño de la placa (ATX, Micro-ATX…).",
            {"a": ("placa", "factor-de-forma"), "b": ("gabinete", "factores-de-forma-compatibles")},
            _en_lista("factor_forma", "placa", "a", "gabinete", "b", "Tamaño de la placa"),
        ),
        ReglaDef(
            "cooler_socket",
            "Socket del cooler",
            "El cooler debe servir para el socket del procesador.",
            {"a": ("procesador", "socket"), "b": ("refrigeracion", "sockets-compatibles")},
            _en_lista(
                "cooler_socket", "procesador", "a", "refrigeracion", "b", "Cooler y procesador"
            ),
        ),
        ReglaDef(
            "cooler_altura",
            "Altura del cooler",
            "El cooler debe entrar en el gabinete.",
            {"a": ("refrigeracion", "altura"), "b": ("gabinete", "altura-maxima-del-cooler")},
            _menor_igual(
                "cooler_altura", "refrigeracion", "a", "gabinete", "b", "Altura del cooler", "mm"
            ),
        ),
        ReglaDef(
            "gpu_largo",
            "Largo de la tarjeta de video",
            "La tarjeta de video debe entrar en el gabinete.",
            {"a": ("video", "largo"), "b": ("gabinete", "largo-maximo-de-tarjeta-de-video")},
            _menor_igual(
                "gpu_largo", "video", "a", "gabinete", "b", "Largo de la tarjeta de video", "mm"
            ),
        ),
        ReglaDef(
            "fuente_potencia",
            "Potencia de la fuente",
            "La fuente debe cubrir el procesador, la tarjeta de video y 100 W más (estimado).",
            {
                "potencia": ("fuente", "potencia"),
                "cpu_turbo": ("procesador", "potencia-turbo-maxima"),
                "cpu_tdp": ("procesador", "potencia-base-tdp"),
                "gpu_consumo": ("video", "consumo-tgp"),
            },
            _fuente_potencia,
        ),
        ReglaDef(
            "ssd_m2",
            "Ranuras M.2",
            "Los discos M.2 necesitan ranuras M.2 en la placa.",
            {"formato": ("almacenamiento", "formato"), "ranuras": ("placa", "ranuras-m2")},
            _almacenamiento("ssd_m2", "ranuras", "M.2", lambda f: f.startswith("M.2")),
        ),
        ReglaDef(
            "ssd_sata",
            "Puertos SATA",
            "Los discos SATA necesitan puertos SATA en la placa.",
            {"formato": ("almacenamiento", "formato"), "ranuras": ("placa", "puertos-sata")},
            _almacenamiento("ssd_sata", "ranuras", "SATA", lambda f: "SATA" in f),
        ),
    )


REGLAS = _reglas()
REGLA_POR_ID = {r.id: r for r in REGLAS}
CLAVE_VALIDA = re.compile(r"^[a-z0-9][a-z0-9\-]{0,49}$")


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def _espacios_guardados(config: ConfiguracionArmador | None) -> dict[str, dict]:
    guardado = {
        e.get("clave"): e for e in (config.espacios if config else []) if isinstance(e, dict)
    }
    salida = {}
    for orden, d in enumerate(ESPACIOS):
        g = guardado.get(d.clave, {})
        salida[d.clave] = {
            "clave": d.clave,
            "nombre": d.nombre,
            "ayuda": d.ayuda,
            "orden": orden,
            "categorias": [int(c) for c in g.get("categorias", []) if str(c).isdigit()],
            "obligatorio": bool(g.get("obligatorio", d.obligatorio)),
            "max_unidades": int(g.get("max_unidades", d.max_unidades)),
        }
    return salida


def claves_efectivas(config: ConfiguracionArmador | None) -> dict[str, dict[str, str]]:
    """Regla → alias → clave de especificación (la ajustada por el negocio o la de fábrica)."""
    ajustes = (config.reglas if config else {}) or {}
    salida = {}
    for regla in REGLAS:
        propias = (ajustes.get(regla.id) or {}).get("claves") or {}
        salida[regla.id] = {
            alias: (propias.get(alias) if CLAVE_VALIDA.match(str(propias.get(alias, ""))) else None)
            or clave
            for alias, (_, clave) in regla.claves.items()
        }
    return salida


def reglas_activas(config: ConfiguracionArmador | None) -> list[ReglaDef]:
    ajustes = (config.reglas if config else {}) or {}
    return [r for r in REGLAS if (ajustes.get(r.id) or {}).get("activa", True)]


def configuracion_vigente(organizacion_id: int) -> ConfiguracionArmador | None:
    return ConfiguracionArmador.objects.sin_ambito().filter(organizacion_id=organizacion_id).first()


def espacios_con_categorias(config: ConfiguracionArmador | None) -> list[dict]:
    """Los espacios que tienen al menos una categoría (los únicos que se muestran)."""
    return [e for e in _espacios_guardados(config).values() if e["categorias"]]


def esta_listo(config: ConfiguracionArmador | None) -> bool:
    return bool(config and config.activo and espacios_con_categorias(config))


def publica(config: ConfiguracionArmador | None, ctx: Contexto) -> dict:
    """Lo que ve el cliente de la configuración (sin ids internos de reglas ni claves)."""
    if not esta_listo(config):
        return {"activo": False}
    from apps.mantenimiento.models import Categoria

    nombres = {
        c.pk: c for c in Categoria.objects.sin_ambito().filter(organizacion_id=ctx.organizacion_id)
    }
    espacios = []
    for e in espacios_con_categorias(config):
        espacios.append(
            {
                "clave": e["clave"],
                "nombre": e["nombre"],
                "ayuda": e["ayuda"],
                "obligatorio": e["obligatorio"],
                "max_unidades": e["max_unidades"],
                "categorias": [
                    {"slug": nombres[c].slug, "nombre": nombres[c].nombre}
                    for c in e["categorias"]
                    if c in nombres and nombres[c].slug
                ],
            }
        )
    return {
        "activo": True,
        "espacios": espacios,
        "reglas": [{"id": r.id, "nombre": r.nombre} for r in reglas_activas(config)],
    }


# ---------------------------------------------------------------------------
# Armado
# ---------------------------------------------------------------------------
def normalizar_lineas(entradas) -> list[dict]:
    """Valida lo que manda el navegador: [{producto, cantidad}] con enteros y sin repetidos."""
    if not isinstance(entradas, list) or len(entradas) > MAX_LINEAS:
        raise DatosInvalidos("El armado no es válido.")
    acumulado: dict[int, int] = {}
    for fila in entradas:
        try:
            producto, cantidad = int(fila["producto"]), int(fila.get("cantidad", 1))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise DatosInvalidos("El armado no es válido.") from None
        if producto < 1 or not 1 <= cantidad <= 99:
            raise DatosInvalidos("El armado no es válido.")
        acumulado[producto] = acumulado.get(producto, 0) + cantidad
    return [{"producto": p, "cantidad": c} for p, c in acumulado.items()]


def _espacio_de_categoria(config: ConfiguracionArmador | None) -> dict[int, str]:
    return {c: e["clave"] for e in espacios_con_categorias(config) for c in e["categorias"]}


def agrupar(ctx: Contexto, config: ConfiguracionArmador, entradas: list[dict]):
    """Arma ``espacio → [(producto, cantidad)]``. Descarta lo que ya no se vende y rechaza
    lo que no es una pieza del armador o pasa el máximo de su espacio."""
    por_categoria = _espacio_de_categoria(config)
    vigentes = {
        p.pk: p
        for p in catalogo.productos_publicos(ctx).filter(pk__in=[e["producto"] for e in entradas])
    }
    maximos = {e["clave"]: e["max_unidades"] for e in espacios_con_categorias(config)}
    seleccion: dict[str, list] = defaultdict(list)
    quitados = []
    for e in entradas:
        producto = vigentes.get(e["producto"])
        if producto is None:
            quitados.append(e["producto"])
            continue
        espacio = por_categoria.get(producto.categoria_id)
        if espacio is None:
            raise DatosInvalidos(f"{_corto(producto)} no es una pieza del armador.")
        seleccion[espacio].append((producto, e["cantidad"]))
    for espacio, lista in seleccion.items():
        unidades = sum(c for _, c in lista)
        nombre = ESPACIO_POR_CLAVE[espacio].nombre
        if maximos[espacio] == 1 and len(lista) > 1:
            raise DatosInvalidos(f"En «{nombre}» solo puedes elegir una pieza.")
        if unidades > maximos[espacio]:
            raise DatosInvalidos(f"En «{nombre}» puedes elegir hasta {maximos[espacio]} unidades.")
    return dict(seleccion), quitados


def evaluar(config: ConfiguracionArmador, seleccion: dict[str, list]) -> list[Resultado]:
    ev = Evaluacion(seleccion, claves_efectivas(config))
    resultados: list[Resultado] = []
    for regla in reglas_activas(config):
        resultados.extend(regla.evaluar(ev))
    return resultados


def validar(ctx: Contexto, config: ConfiguracionArmador, entradas: list[dict]) -> dict:
    """Compatibilidad, faltantes, total y si se puede agregar todo al carrito."""
    entradas = normalizar_lineas(entradas)
    seleccion, quitados = agrupar(ctx, config, entradas)
    resultados = evaluar(config, seleccion)
    vigentes = [{"producto": p.pk, "cantidad": c} for lista in seleccion.values() for p, c in lista]
    calculo = carrito.calcular(ctx, vigentes) if vigentes else None
    espacio_de = {p.pk: esp for esp, lista in seleccion.items() for p, _ in lista}
    lineas = []
    for ln in (calculo or {"lineas": []})["lineas"]:
        lineas.append({**ln, "espacio": espacio_de.get(ln["producto"])})
    faltantes = [
        {"clave": e["clave"], "nombre": e["nombre"]}
        for e in espacios_con_categorias(config)
        if e["obligatorio"] and e["clave"] not in seleccion
    ]
    incompatibles = sum(1 for r in resultados if r.estado == INCOMPATIBLE)
    sin_verificar = sum(1 for r in resultados if r.estado == NO_VERIFICABLE)
    problemas = calculo["problemas"] if calculo else 0
    return {
        "lineas": lineas,
        "quitados": quitados,
        "compatibilidades": [
            r.como_dict() for r in sorted(resultados, key=lambda r: PRIORIDAD[r.estado])
        ],
        "incompatibles": incompatibles,
        "no_verificables": sin_verificar,
        "faltantes": faltantes,
        "completo": not faltantes and bool(vigentes),
        "subtotal": calculo["subtotal"] if calculo else "0.00",
        "peso_kg": calculo["peso_kg"] if calculo else "0.00",
        "problemas": problemas,
        "puede_agregar": bool(vigentes) and incompatibles == 0 and problemas == 0,
    }


def _estado_peor(resultados: list[Resultado]) -> str:
    if not resultados:
        return LIBRE
    return min((r.estado for r in resultados), key=lambda e: PRIORIDAD[e])


def opciones(
    ctx: Contexto,
    config: ConfiguracionArmador,
    espacio: str,
    entradas: list[dict],
    *,
    todas: bool,
    pagina: int,
    tam: int,
) -> dict:
    """Productos de un espacio, cada uno con su compatibilidad frente a lo ya elegido.

    Sin ``todas`` se ocultan los incompatibles; con ``todas`` salen marcados. Primero los
    compatibles, luego los no verificables y al final los incompatibles.
    """
    definicion = next((e for e in espacios_con_categorias(config) if e["clave"] == espacio), None)
    if definicion is None:
        raise DatosInvalidos("Ese espacio no existe en el armador.")
    seleccion, _ = agrupar(ctx, config, normalizar_lineas(entradas))
    base = (
        {k: v for k, v in seleccion.items() if k != espacio}
        if definicion["max_unidades"] == 1
        else dict(seleccion)
    )
    ev_claves = claves_efectivas(config)
    activas = reglas_activas(config)
    candidatos = list(
        catalogo.productos_publicos(ctx)
        .filter(categoria_id__in=definicion["categorias"])
        .order_by("nombre")[:MAX_CANDIDATOS]
    )
    elegidos = {p.pk for p, _ in seleccion.get(espacio, [])}
    evaluados = []
    for c in candidatos:
        otros = [(p, q) for p, q in base.get(espacio, []) if p.pk != c.pk]
        con_c = {**base, espacio: [*otros, (c, 1)]}
        ev = Evaluacion(con_c, ev_claves)
        propios = [r for regla in activas for r in regla.evaluar(ev) if c.pk in r.productos]
        evaluados.append((c, _estado_peor(propios), propios))
    if not todas:
        evaluados = [t for t in evaluados if t[1] != INCOMPATIBLE]
    evaluados.sort(key=lambda t: (ORDEN_LISTA[t[1]], t[0].nombre))
    total = len(evaluados)
    paginas = max((total + tam - 1) // tam, 1)
    pagina = min(max(pagina, 1), paginas)
    fila = evaluados[(pagina - 1) * tam : pagina * tam]
    tarjetas = catalogo.tarjetas([t[0] for t in fila], ctx)
    for tarjeta, (_, estado, propios) in zip(tarjetas, fila, strict=True):
        tarjeta["compatibilidad"] = {
            "estado": estado,
            "motivos": [r.mensaje for r in propios if r.estado != COMPATIBLE][:3],
        }
        tarjeta["elegido"] = tarjeta["id"] in elegidos
    return {
        "count": total,
        "page": pagina,
        "page_size": tam,
        "paginas": paginas,
        "results": tarjetas,
    }


# ---------------------------------------------------------------------------
# Guardar la configuración (panel)
# ---------------------------------------------------------------------------
def validar_configuracion(organizacion_id: int, datos: dict) -> dict:
    """Valida lo que manda el panel y devuelve ``{'activo', 'espacios', 'reglas'}`` listos."""
    from apps.mantenimiento.models import Categoria, EstadoRegistro

    validas = set(
        Categoria.objects.sin_ambito()
        .filter(organizacion_id=organizacion_id, estado=EstadoRegistro.ACTIVO)
        .values_list("pk", flat=True)
    )
    espacios, usadas = [], {}
    for fila in datos.get("espacios", []):
        definicion = ESPACIO_POR_CLAVE.get(fila["clave"])
        if definicion is None:
            raise DatosInvalidos(f"El espacio «{fila['clave']}» no existe.")
        if any(e["clave"] == fila["clave"] for e in espacios):
            raise DatosInvalidos(f"El espacio «{definicion.nombre}» está repetido.")
        categorias = list(dict.fromkeys(fila.get("categorias", [])))
        for c in categorias:
            if c not in validas:
                raise DatosInvalidos("Hay categorías que no existen o están inactivas.")
            if c in usadas:
                raise DatosInvalidos(
                    "Una categoría solo puede llenar un espacio: está en "
                    f"«{ESPACIO_POR_CLAVE[usadas[c]].nombre}» y en «{definicion.nombre}»."
                )
            usadas[c] = definicion.clave
        espacios.append(
            {
                "clave": definicion.clave,
                "categorias": categorias,
                "obligatorio": bool(fila.get("obligatorio", definicion.obligatorio)),
                "max_unidades": int(fila.get("max_unidades", definicion.max_unidades)),
            }
        )
    reglas = {}
    for regla_id, ajuste in (datos.get("reglas") or {}).items():
        regla = REGLA_POR_ID.get(regla_id)
        if regla is None:
            raise DatosInvalidos(f"La regla «{regla_id}» no existe.")
        claves = {}
        for alias, clave in ((ajuste or {}).get("claves") or {}).items():
            if alias not in regla.claves or not CLAVE_VALIDA.match(str(clave)):
                raise DatosInvalidos(f"Campo no válido en la regla «{regla.nombre}».")
            if clave != regla.claves[alias][1]:
                claves[alias] = clave
        reglas[regla_id] = {"activa": bool((ajuste or {}).get("activa", True)), "claves": claves}
    return {"espacios": espacios, "reglas": reglas}
