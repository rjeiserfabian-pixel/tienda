"""Especificaciones técnicas por categoría: la plantilla de campos y los valores de cada producto.

Cada categoría define sus campos una sola vez (RAM, DPI, socket…). El producto guarda sus valores en
``Producto.especificaciones`` bajo la clave de cada campo. Los campos marcados como FILTRO arman los
filtros de la tienda y los marcados para la TARJETA se ven sin abrir el producto.

Los valores se validan siempre contra la plantilla vigente de la categoría: un campo que no existe,
un número que no es número o una opción fuera de la lista se rechazan, para que los filtros de la
tienda nunca se partan por errores de tipeo. Un campo que se quita queda INACTIVO (no se borra), así
no se pierde lo ya cargado.
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from apps.auditoria.servicios import registrar

from .models import CampoEspecificacion, Categoria, EstadoRegistro, Producto

logger = logging.getLogger(__name__)

Tipo = CampoEspecificacion.Tipo
MAX_CAMPOS = 80
MAX_OPCIONES = 40
MAX_TEXTO = 200
MAX_SLUG_AUTOMATICO = 70
MAX_NUMERO = Decimal("1000000000")
SI = {"si", "sí", "s", "yes", "true", "1"}
NO = {"no", "n", "false", "0"}
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Plantillas de ejemplo (de las fichas reales de Deltron, ordenadas por sección)
# ---------------------------------------------------------------------------
def _c(
    nombre,
    tipo=Tipo.TEXTO,
    *,
    unidad="",
    opciones=(),
    seccion="General",
    filtro=False,
    tarjeta=False,
):
    return {
        "nombre": nombre,
        "tipo": tipo,
        "unidad": unidad,
        "opciones": list(opciones),
        "seccion": seccion,
        "es_filtro": filtro,
        "en_tarjeta": tarjeta,
    }


T, N, L, S = Tipo.TEXTO, Tipo.NUMERO, Tipo.LISTA, Tipo.SI_NO
_COLORES = ("Negro", "Blanco", "Gris", "Plata", "Azul", "Rojo", "Verde", "Rosado", "Otro")

PLANTILLAS: dict[str, dict] = {
    "laptop": {
        "nombre": "Laptop",
        "campos": [
            _c("Serie", T, seccion="General"),
            _c("Modelo", T, seccion="General"),
            _c("Color", L, opciones=_COLORES, seccion="General"),
            _c(
                "Uso",
                L,
                opciones=("Oficina", "Estudio", "Gaming", "Diseño", "Empresarial"),
                seccion="General",
                filtro=True,
            ),
            _c(
                "Tamaño de pantalla",
                N,
                unidad="pulgadas",
                seccion="Pantalla",
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Resolución",
                L,
                opciones=(
                    "HD 1366x768",
                    "Full HD 1920x1080",
                    "WUXGA 1920x1200",
                    "2K 2560x1440",
                    "2.8K",
                    "4K",
                ),
                seccion="Pantalla",
                filtro=True,
            ),
            _c(
                "Tipo de panel",
                L,
                opciones=("IPS", "TN", "VA", "OLED"),
                seccion="Pantalla",
                filtro=True,
            ),
            _c("Pantalla táctil", S, seccion="Pantalla", filtro=True),
            _c("Brillo", N, unidad="nits", seccion="Pantalla"),
            _c("Frecuencia de pantalla", N, unidad="Hz", seccion="Pantalla"),
            _c(
                "Línea de procesador",
                L,
                opciones=(
                    "Intel Core i3",
                    "Intel Core i5",
                    "Intel Core i7",
                    "Intel Core i9",
                    "Intel Core Ultra 5",
                    "Intel Core Ultra 7",
                    "Intel Celeron",
                    "AMD Ryzen 3",
                    "AMD Ryzen 5",
                    "AMD Ryzen 7",
                    "AMD Ryzen 9",
                ),
                seccion="Procesador",
                filtro=True,
            ),
            _c("Modelo de procesador", T, seccion="Procesador"),
            _c("Frecuencia máxima", N, unidad="GHz", seccion="Procesador"),
            _c("Núcleos", N, seccion="Procesador"),
            _c("Hilos", N, seccion="Procesador"),
            _c("Memoria RAM", N, unidad="GB", seccion="Memoria", filtro=True, tarjeta=True),
            _c(
                "Tipo de memoria",
                L,
                opciones=("DDR4", "DDR5", "LPDDR4X", "LPDDR5"),
                seccion="Memoria",
                filtro=True,
            ),
            _c("Máximo de memoria", N, unidad="GB", seccion="Memoria"),
            _c(
                "Almacenamiento",
                N,
                unidad="GB",
                seccion="Almacenamiento",
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Tipo de unidad",
                L,
                opciones=("SSD NVMe", "SSD SATA", "HDD", "SSD + HDD"),
                seccion="Almacenamiento",
                filtro=True,
            ),
            _c("Lector de tarjetas", S, seccion="Almacenamiento"),
            _c(
                "Tarjeta de video",
                L,
                opciones=("Integrada", "NVIDIA GeForce", "AMD Radeon", "Intel Arc"),
                seccion="Video",
                filtro=True,
            ),
            _c("Modelo de video", T, seccion="Video"),
            _c(
                "Wi-Fi",
                L,
                opciones=("Wi-Fi 5", "Wi-Fi 6", "Wi-Fi 6E", "Wi-Fi 7"),
                seccion="Conectividad",
            ),
            _c("Bluetooth", T, seccion="Conectividad"),
            _c("Puertos", T, seccion="Conectividad"),
            _c("Cámara", T, seccion="Audio y cámara"),
            _c("Audio", T, seccion="Audio y cámara"),
            _c(
                "Idioma del teclado",
                L,
                opciones=("Español Latinoamérica", "Español España", "Inglés US"),
                seccion="Teclado",
            ),
            _c("Teclado retroiluminado", S, seccion="Teclado", filtro=True),
            _c("Batería", T, seccion="Energía"),
            _c("Adaptador", T, seccion="Energía"),
            _c(
                "Sistema operativo",
                L,
                opciones=(
                    "Windows 11 Home",
                    "Windows 11 Pro",
                    "Sin sistema operativo",
                    "macOS",
                    "ChromeOS",
                    "Linux",
                ),
                seccion="Software",
                filtro=True,
            ),
            _c("Seguridad", T, seccion="Software"),
            _c("Material", T, seccion="Físico"),
            _c("Dimensiones", T, seccion="Físico"),
        ],
    },
    "mouse": {
        "nombre": "Mouse",
        "campos": [
            _c("Modelo", T),
            _c(
                "Tipo",
                L,
                opciones=("Oficina", "Gamer", "Ergonómico", "Viaje"),
                filtro=True,
                tarjeta=True,
            ),
            _c("Diseño", T),
            _c("Color", L, opciones=_COLORES, filtro=True),
            _c("Sensor", T, seccion="Rendimiento"),
            _c(
                "Resolución máxima",
                N,
                unidad="DPI",
                seccion="Rendimiento",
                filtro=True,
                tarjeta=True,
            ),
            _c("Botones", N, seccion="Rendimiento", filtro=True),
            _c(
                "Conexión",
                L,
                opciones=(
                    "Con cable USB",
                    "Inalámbrico 2.4 GHz",
                    "Bluetooth",
                    "Inalámbrico y Bluetooth",
                ),
                seccion="Conexión",
                filtro=True,
                tarjeta=True,
            ),
            _c("Cobertura", N, unidad="m", seccion="Conexión"),
            _c("Alimentación", T, seccion="Energía"),
            _c("Iluminación RGB", S, seccion="Físico", filtro=True),
            _c("Compatibilidad", T, seccion="Físico"),
            _c("Dimensiones", T, seccion="Físico"),
        ],
    },
    "teclado": {
        "nombre": "Teclado",
        "campos": [
            _c("Modelo", T),
            _c("Gama", L, opciones=("Oficina", "Gaming", "Multimedia"), filtro=True),
            _c("Color", L, opciones=_COLORES, filtro=True),
            _c("Cantidad de teclas", N, seccion="Teclas"),
            _c(
                "Formato",
                L,
                opciones=("Full-size con teclado numérico", "TKL", "75 %", "60 %"),
                seccion="Teclas",
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Distribución",
                L,
                opciones=("Español Latinoamérica", "Español España", "Inglés US"),
                seccion="Teclas",
                filtro=True,
            ),
            _c("Teclado numérico", S, seccion="Teclas"),
            _c("Teclas multimedia", T, seccion="Teclas"),
            _c(
                "Tecnología",
                L,
                opciones=("Membrana", "Mecánico", "Tijera"),
                seccion="Funcionamiento",
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Retroiluminación",
                L,
                opciones=("Sin retroiluminación", "LED de un color", "RGB"),
                seccion="Funcionamiento",
                filtro=True,
            ),
            _c(
                "Conexión",
                L,
                opciones=(
                    "Con cable USB",
                    "Inalámbrico 2.4 GHz",
                    "Bluetooth",
                    "Inalámbrico y Bluetooth",
                ),
                seccion="Conexión",
                filtro=True,
                tarjeta=True,
            ),
            _c("Longitud del cable", N, unidad="m", seccion="Conexión"),
            _c("Resistencia al agua", T, seccion="Físico", filtro=False),
            _c("Material", T, seccion="Físico"),
            _c("Sistemas operativos", T, seccion="Físico"),
            _c("Incluye", T, seccion="Contenido"),
        ],
    },
    "procesador": {
        "nombre": "Procesador",
        "campos": [
            _c(
                "Familia",
                L,
                opciones=(
                    "Intel Core i3",
                    "Intel Core i5",
                    "Intel Core i7",
                    "Intel Core i9",
                    "Intel Core Ultra",
                    "AMD Ryzen 3",
                    "AMD Ryzen 5",
                    "AMD Ryzen 7",
                    "AMD Ryzen 9",
                    "Otro",
                ),
                filtro=True,
                tarjeta=True,
            ),
            _c("Generación", T),
            _c("Nombre", T),
            _c(
                "Socket",
                L,
                opciones=("LGA1700", "LGA1851", "AM4", "AM5", "Otro"),
                seccion="Plataforma",
                filtro=True,
                tarjeta=True,
            ),
            _c("Litografía", T, seccion="Plataforma"),
            _c("Núcleos", N, seccion="Rendimiento", filtro=True, tarjeta=True),
            _c("Subprocesos", N, seccion="Rendimiento"),
            _c("Frecuencia base", N, unidad="GHz", seccion="Rendimiento"),
            _c("Frecuencia turbo", N, unidad="GHz", seccion="Rendimiento"),
            _c("Caché", N, unidad="MB", seccion="Memoria"),
            _c("Potencia base (TDP)", N, unidad="W", seccion="Energía"),
            _c("Potencia turbo máxima", N, unidad="W", seccion="Energía"),
            _c("Gráficos integrados", T, seccion="Video"),
            _c("Incluye cooler", S, seccion="Contenido", filtro=True),
        ],
    },
    "memoria-ram": {
        "nombre": "Memoria RAM",
        "campos": [
            _c("Modelo", T),
            _c("Color", L, opciones=_COLORES),
            _c("Capacidad", N, unidad="GB", seccion="Memoria", filtro=True, tarjeta=True),
            _c(
                "Tipo",
                L,
                opciones=("DDR3", "DDR4", "DDR5"),
                seccion="Memoria",
                filtro=True,
                tarjeta=True,
            ),
            _c("Frecuencia", N, unidad="MHz", seccion="Memoria", filtro=True, tarjeta=True),
            _c("Estándar", T, seccion="Memoria"),
            _c(
                "Número de módulos",
                L,
                opciones=("1 módulo", "2 módulos (kit)", "4 módulos (kit)"),
                seccion="Memoria",
                filtro=True,
            ),
            _c(
                "Formato",
                L,
                opciones=("DIMM (PC de escritorio)", "SODIMM (laptop)"),
                seccion="Memoria",
                filtro=True,
            ),
            _c("Número de pines", N, seccion="Memoria"),
            _c("Voltaje", T, seccion="Eléctrico"),
            _c("Latencia", T, seccion="Rendimiento"),
            _c("Timing", T, seccion="Rendimiento"),
            _c("Corrección de errores", L, opciones=("Non-ECC", "ECC"), seccion="Rendimiento"),
            _c("Perfil de overclock", T, seccion="Rendimiento"),
            _c("Disipador de calor", S, seccion="Físico"),
        ],
    },
    "ssd": {
        "nombre": "Disco sólido (SSD)",
        "campos": [
            _c("Modelo", T),
            _c("Capacidad", N, unidad="GB", seccion="Almacenamiento", filtro=True, tarjeta=True),
            _c(
                "Interfaz",
                L,
                opciones=("SATA III", "NVMe PCIe 3.0 x4", "NVMe PCIe 4.0 x4", "NVMe PCIe 5.0 x4"),
                seccion="Almacenamiento",
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Formato",
                L,
                opciones=("2.5 pulgadas SATA", "M.2 2280", "M.2 2242", "M.2 2230"),
                seccion="Almacenamiento",
                filtro=True,
                tarjeta=True,
            ),
            _c("Velocidad de lectura", N, unidad="MB/s", seccion="Rendimiento"),
            _c("Velocidad de escritura", N, unidad="MB/s", seccion="Rendimiento"),
            _c("Dimensiones", T, seccion="Físico"),
        ],
    },
    "monitor": {
        "nombre": "Monitor",
        "campos": [
            _c(
                "Tipo de monitor",
                L,
                opciones=("Oficina", "Gaming", "Diseño", "Profesional"),
                filtro=True,
            ),
            _c("Modelo", T),
            _c("Color", L, opciones=_COLORES),
            _c("Tamaño", N, unidad="pulgadas", seccion="Pantalla", filtro=True, tarjeta=True),
            _c(
                "Tipo de panel",
                L,
                opciones=("IPS", "VA", "TN", "OLED"),
                seccion="Pantalla",
                filtro=True,
            ),
            _c(
                "Formato de pantalla",
                L,
                opciones=("Plano", "Curvo"),
                seccion="Pantalla",
                filtro=True,
            ),
            _c(
                "Resolución",
                L,
                opciones=(
                    "HD 1366x768",
                    "Full HD 1920x1080",
                    "2K 2560x1440",
                    "4K 3840x2160",
                    "Ultrawide",
                ),
                seccion="Pantalla",
                filtro=True,
                tarjeta=True,
            ),
            _c("Proporción", T, seccion="Pantalla"),
            _c("Superficie", L, opciones=("Antirreflejo", "Brillante"), seccion="Pantalla"),
            _c("Pantalla táctil", S, seccion="Pantalla"),
            _c(
                "Tasa de refresco", N, unidad="Hz", seccion="Rendimiento", filtro=True, tarjeta=True
            ),
            _c("Tiempo de respuesta", N, unidad="ms", seccion="Rendimiento", filtro=True),
            _c("FreeSync o G-Sync", S, seccion="Rendimiento", filtro=True),
            _c("Brillo", N, unidad="nits", seccion="Imagen"),
            _c("Contraste", T, seccion="Imagen"),
            _c("HDR", S, seccion="Imagen", filtro=True),
            _c("Cobertura sRGB", N, unidad="%", seccion="Imagen"),
            _c("Ángulo de visión", T, seccion="Imagen"),
            _c("Puertos", T, seccion="Conexión", filtro=False),
            _c("Parlantes integrados", S, seccion="Conexión"),
            _c("Montaje VESA", T, seccion="Físico"),
            _c("Inclinación", T, seccion="Físico"),
            _c("Consumo típico", N, unidad="W", seccion="Energía"),
            _c("Dimensiones con base", T, seccion="Físico"),
            _c("Contenido de la caja", T, seccion="Contenido"),
        ],
    },
    "placa-base": {
        "nombre": "Placa base",
        "campos": [
            _c("Modelo", T),
            _c("Chipset", T, seccion="Plataforma", filtro=False),
            _c(
                "Socket",
                L,
                opciones=("LGA1700", "LGA1851", "AM4", "AM5", "Otro"),
                seccion="Plataforma",
                filtro=True,
                tarjeta=True,
            ),
            _c("Procesadores compatibles", T, seccion="Plataforma"),
            _c(
                "Tipo de RAM",
                L,
                opciones=("DDR4", "DDR5"),
                seccion="Memoria",
                filtro=True,
                tarjeta=True,
            ),
            _c("Ranuras de memoria", N, seccion="Memoria"),
            _c("Máximo de memoria", N, unidad="GB", seccion="Memoria"),
            _c("Tecnología de memoria", T, seccion="Memoria"),
            _c("Ranuras M.2", N, seccion="Almacenamiento", filtro=True),
            _c("Puertos SATA", N, seccion="Almacenamiento"),
            _c("RAID", T, seccion="Almacenamiento"),
            _c(
                "Wi-Fi integrado",
                L,
                opciones=("Sin Wi-Fi", "Wi-Fi 5", "Wi-Fi 6", "Wi-Fi 6E", "Wi-Fi 7"),
                seccion="Conectividad",
                filtro=True,
            ),
            _c("Bluetooth", T, seccion="Conectividad"),
            _c("Red cableada", T, seccion="Conectividad"),
            _c("Audio", T, seccion="Audio"),
            _c("Ranuras PCIe", T, seccion="Expansión"),
            _c("Puertos traseros", T, seccion="Puertos"),
            _c(
                "Factor de forma",
                L,
                opciones=("ATX", "Micro-ATX", "Mini-ITX", "E-ATX"),
                seccion="Físico",
                filtro=True,
                tarjeta=True,
            ),
            _c("Dimensiones", T, seccion="Físico"),
            _c("BIOS", T, seccion="Software"),
        ],
    },
    # --- Piezas para «Arma tu PC»: las claves (slug del nombre) las usan las reglas de
    # compatibilidad de apps/tienda/armador.py (formatos, largo, potencia, sockets del cooler).
    "gabinete": {
        "nombre": "Gabinete",
        "campos": [
            _c("Modelo", T),
            _c("Color", L, opciones=_COLORES),
            _c(
                "Tipo",
                L,
                opciones=("Mini torre", "Torre media", "Torre completa", "Cubo"),
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Factores de forma compatibles",
                T,
                seccion="Compatibilidad",
                tarjeta=True,
            ),
            _c("Largo máximo de tarjeta de video", N, unidad="mm", seccion="Compatibilidad"),
            _c("Altura máxima del cooler", N, unidad="mm", seccion="Compatibilidad"),
            _c(
                "Panel lateral",
                L,
                opciones=("Vidrio templado", "Acrílico", "Metal"),
                seccion="Físico",
                filtro=True,
            ),
            _c("Fuente incluida", S, seccion="Contenido", filtro=True),
            _c("Ventiladores incluidos", N, seccion="Contenido"),
        ],
    },
    "fuente-de-poder": {
        "nombre": "Fuente de poder",
        "campos": [
            _c("Modelo", T),
            _c("Potencia", N, unidad="W", seccion="Energía", filtro=True, tarjeta=True),
            _c(
                "Certificación",
                L,
                opciones=(
                    "Sin certificación",
                    "80 Plus",
                    "80 Plus Bronze",
                    "80 Plus Silver",
                    "80 Plus Gold",
                    "80 Plus Platinum",
                    "80 Plus Titanium",
                ),
                seccion="Energía",
                filtro=True,
                tarjeta=True,
            ),
            _c("Modular", L, opciones=("No", "Semi modular", "Full modular"), seccion="Cables"),
            _c("Conectores de la tarjeta de video", T, seccion="Cables"),
        ],
    },
    "tarjeta-de-video": {
        "nombre": "Tarjeta de video",
        "campos": [
            _c("Modelo", T),
            _c(
                "Fabricante del chip",
                L,
                opciones=("NVIDIA", "AMD", "Intel"),
                filtro=True,
                tarjeta=True,
            ),
            _c("Memoria", N, unidad="GB", seccion="Memoria", filtro=True, tarjeta=True),
            _c("Tipo de memoria", T, seccion="Memoria"),
            _c("Consumo (TGP)", N, unidad="W", seccion="Energía", tarjeta=True),
            _c("Conectores de energía", T, seccion="Energía"),
            _c("Largo", N, unidad="mm", seccion="Físico"),
        ],
    },
    "refrigeracion": {
        "nombre": "Refrigeración (cooler)",
        "campos": [
            _c("Modelo", T),
            _c("Tipo", L, opciones=("Aire", "Líquido"), filtro=True, tarjeta=True),
            _c("Sockets compatibles", T, seccion="Compatibilidad", tarjeta=True),
            _c("Altura", N, unidad="mm", seccion="Físico"),
            _c("Tamaño del radiador", T, seccion="Físico"),
        ],
    },
    "impresora": {
        "nombre": "Impresora",
        "campos": [
            _c("Modelo", T),
            _c(
                "Función",
                L,
                opciones=("Solo impresora", "Multifuncional"),
                filtro=True,
                tarjeta=True,
            ),
            _c(
                "Tecnología de impresión",
                L,
                opciones=(
                    "Inyección de tinta",
                    "Sistema de tinta continua",
                    "Láser monocromo",
                    "Láser color",
                    "Matricial",
                ),
                seccion="Impresión",
                filtro=True,
                tarjeta=True,
            ),
            _c("Resolución máxima", T, seccion="Impresión"),
            _c("Velocidad en negro", N, unidad="ppm", seccion="Impresión"),
            _c("Velocidad en color", N, unidad="ppm", seccion="Impresión"),
            _c(
                "Conectividad",
                L,
                opciones=("USB", "USB y Wi-Fi", "USB, Wi-Fi y red", "USB y red"),
                seccion="Conexión",
                filtro=True,
                tarjeta=True,
            ),
            _c("Sistemas compatibles", T, seccion="Conexión"),
            _c("Tamaños de papel", T, seccion="Papel"),
            _c("Tipo de escáner", T, seccion="Escáner"),
            _c("Resolución de escaneado", T, seccion="Escáner"),
            _c("Suministros compatibles", T, seccion="Suministros"),
            _c("Consumo", N, unidad="W", seccion="Energía"),
            _c("Dimensiones", T, seccion="Físico"),
        ],
    },
}


def plantillas_disponibles() -> list[dict]:
    return [
        {
            "clave": clave,
            "nombre": p["nombre"],
            "campos": len(p["campos"]),
            "secciones": list(dict.fromkeys(c["seccion"] for c in p["campos"])),
        }
        for clave, p in PLANTILLAS.items()
    ]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _error(campo: str, mensaje: str):
    raise ValidationError({campo: mensaje})


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor if valor is not None else "").split())[:maximo]


def campos_de(categoria: Categoria, *, solo_activos: bool = False):
    consulta = CampoEspecificacion.objects.filter(categoria=categoria)
    if solo_activos:
        consulta = consulta.filter(estado=EstadoRegistro.ACTIVO)
    return consulta.order_by("orden", "id")


def _clave_libre(nombre: str, usadas: set[str]) -> str:
    base = (slugify(nombre) or "campo")[:50]
    clave, n = base, 2
    while clave in usadas:
        clave = f"{base}-{n}"
        n += 1
    return clave


# ---------------------------------------------------------------------------
# Editar la plantilla de una categoría
# ---------------------------------------------------------------------------
def _validar_campo(dato: dict, posicion: int) -> dict:
    nombre = _texto(dato.get("nombre"), 80)
    if not nombre:
        _error("campos", f"Campo {posicion}: indique el nombre.")
    tipo = dato.get("tipo", Tipo.TEXTO)
    if tipo not in Tipo.values:
        _error("campos", f"«{nombre}»: el tipo no es válido.")
    opciones: list[str] = []
    if tipo == Tipo.LISTA:
        crudas = dato.get("opciones") or []
        if not isinstance(crudas, (list, tuple)):
            _error("campos", f"«{nombre}»: las opciones deben ser una lista.")
        vistas: set[str] = set()
        for o in crudas:
            texto = _texto(o, 60)
            if texto and texto.lower() not in vistas:
                vistas.add(texto.lower())
                opciones.append(texto)
        if len(opciones) > MAX_OPCIONES:
            _error("campos", f"«{nombre}»: admite hasta {MAX_OPCIONES} opciones.")
    return {
        "nombre": nombre,
        "tipo": tipo,
        "unidad": _texto(dato.get("unidad"), 20) if tipo == Tipo.NUMERO else "",
        "opciones": opciones,
        "seccion": _texto(dato.get("seccion"), 60) or "General",
        "es_filtro": bool(dato.get("es_filtro")) and tipo != Tipo.TEXTO,
        "en_tarjeta": bool(dato.get("en_tarjeta")),
    }


@transaction.atomic
def guardar_campos(categoria: Categoria, campos: list[dict]) -> list[CampoEspecificacion]:
    """Reemplaza la plantilla de la categoría con la lista dada (en ese orden).

    Cada elemento puede traer ``id`` (para modificar uno existente) o no (uno nuevo). Los campos
    existentes que ya no vengan quedan INACTIVOS: los valores de los productos no se pierden.
    """
    if not isinstance(campos, list):
        _error("campos", "Envíe la lista de campos.")
    if len(campos) > MAX_CAMPOS:
        _error("campos", f"Una categoría admite hasta {MAX_CAMPOS} campos.")
    existentes = {
        c.pk: c for c in CampoEspecificacion.objects.select_for_update().filter(categoria=categoria)
    }
    usadas = {c.clave for c in existentes.values()}
    nombres: set[str] = set()
    cargados: set[int] = set()
    resultado = []
    for posicion, dato in enumerate(campos, start=1):
        if not isinstance(dato, dict):
            _error("campos", f"Campo {posicion}: formato no válido.")
        valido = _validar_campo(dato, posicion)
        if valido["nombre"].lower() in nombres:
            _error("campos", f"«{valido['nombre']}» está repetido.")
        nombres.add(valido["nombre"].lower())
        campo = existentes.get(dato.get("id")) if dato.get("id") else None
        if dato.get("id") and campo is None:
            _error("campos", f"El campo «{valido['nombre']}» no es de esta categoría.")
        if campo is None:
            campo = CampoEspecificacion(
                organizacion_id=categoria.organizacion_id,
                categoria=categoria,
                clave=_clave_libre(valido["nombre"], usadas),
            )
            usadas.add(campo.clave)
        else:
            cargados.add(campo.pk)
        for atributo, valor in valido.items():
            setattr(campo, atributo, valor)
        campo.orden = posicion
        campo.estado = EstadoRegistro.ACTIVO
        campo.save()
        resultado.append(campo)
    quitados = [
        c
        for pk, c in existentes.items()
        if pk not in cargados and c.estado == EstadoRegistro.ACTIVO
    ]
    for campo in quitados:
        campo.estado = EstadoRegistro.INACTIVO
        campo.save(update_fields=["estado"])
    purgados = _purgar_sin_uso(categoria, [c for pk, c in existentes.items() if pk not in cargados])
    registrar(
        "categoria.especificaciones_guardadas",
        recurso_tipo="categoria",
        recurso_id=categoria.pk,
        resumen=f"Especificaciones de la categoría {categoria.nombre} actualizadas",
        detalle={"campos": len(resultado), "quitados": len(quitados), "eliminados": purgados},
    )
    return resultado


def _purgar_sin_uso(categoria: Categoria, candidatos: list[CampoEspecificacion]) -> int:
    """Elimina los campos quitados que ningún producto de la categoría usa (no dejan basura).

    Un campo quitado que todavía tiene valores guardados se conserva INACTIVO, para no perderlos.
    """
    eliminados = 0
    for campo in candidatos:
        en_uso = Producto.objects.filter(
            categoria=categoria, especificaciones__has_key=campo.clave
        ).exists()
        if not en_uso:
            campo.delete()  # borrado lógico: libera la clave para un campo nuevo
            eliminados += 1
    return eliminados


@transaction.atomic
def cargar_plantilla(categoria: Categoria, clave: str) -> list[CampoEspecificacion]:
    """Suma los campos de una plantilla de ejemplo.

    Los que la categoría ya tiene ACTIVOS no se tocan (conservan lo que el usuario ajustó). Los que
    existen pero estaban QUITADOS se vuelven a usar tal como los define la plantilla.
    """
    plantilla = PLANTILLAS.get(clave)
    if plantilla is None:
        raise ValidationError({"plantilla": "Esa plantilla no existe."})
    actuales = list(campos_de(categoria))
    por_nombre = {c.nombre.lower(): c for c in actuales}
    usadas = {c.clave for c in actuales}
    orden = max((c.orden for c in actuales if c.estado == EstadoRegistro.ACTIVO), default=0)
    nuevos = []
    reactivados = 0
    for dato in plantilla["campos"]:
        existente = por_nombre.get(dato["nombre"].lower())
        if existente is not None and existente.estado == EstadoRegistro.ACTIVO:
            continue
        orden += 1
        if existente is not None:
            for atributo, valor in dato.items():
                setattr(existente, atributo, valor)
            existente.orden, existente.estado = orden, EstadoRegistro.ACTIVO
            existente.save()
            reactivados += 1
            continue
        nuevos.append(
            CampoEspecificacion(
                organizacion_id=categoria.organizacion_id,
                categoria=categoria,
                clave=_clave_libre(dato["nombre"], usadas),
                orden=orden,
                **dato,
            )
        )
        usadas.add(nuevos[-1].clave)
    CampoEspecificacion.objects.bulk_create(nuevos)
    registrar(
        "categoria.plantilla_cargada",
        recurso_tipo="categoria",
        recurso_id=categoria.pk,
        resumen=f"Plantilla «{plantilla['nombre']}» cargada en {categoria.nombre}",
        detalle={"agregados": len(nuevos), "reactivados": reactivados},
    )
    return list(campos_de(categoria))


# ---------------------------------------------------------------------------
# Valores de un producto
# ---------------------------------------------------------------------------
def _normalizar(campo: CampoEspecificacion, valor):
    """El valor ya limpio, o ``None`` si está vacío. Lanza el error del campo si no sirve."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if campo.tipo == Tipo.SI_NO:
        if isinstance(valor, bool):
            return valor
        texto = str(valor).strip().lower()
        if texto in SI:
            return True
        if texto in NO:
            return False
        raise ValueError("elija Sí o No")
    if campo.tipo == Tipo.NUMERO:
        if isinstance(valor, bool):
            raise ValueError("indique un número")
        try:
            numero = Decimal(str(valor).strip().replace(",", "."))
        except InvalidOperation:
            raise ValueError("indique un número") from None
        if not numero.is_finite() or numero < 0 or numero > MAX_NUMERO:
            raise ValueError("el número no es válido")
        if numero != numero.quantize(Decimal("0.001")):
            raise ValueError("admite hasta 3 decimales")
        return format(numero.normalize(), "f")
    texto = _texto(valor, MAX_TEXTO)
    if campo.tipo == Tipo.LISTA and campo.opciones:
        por_minuscula = {str(o).lower(): o for o in campo.opciones}
        if texto.lower() not in por_minuscula:
            raise ValueError("elija una de las opciones")
        return por_minuscula[texto.lower()]
    return texto[:100] if campo.tipo == Tipo.LISTA else texto


def validar_valores(categoria: Categoria, valores) -> dict:
    """Valida los valores de un producto contra la plantilla ACTIVA de su categoría."""
    if valores in (None, {}):
        return {}
    if not isinstance(valores, dict):
        raise ValidationError({"especificaciones": "Formato no válido."})
    por_clave = {c.clave: c for c in campos_de(categoria, solo_activos=True)}
    limpios: dict = {}
    errores: dict = {}
    for clave, valor in valores.items():
        campo = por_clave.get(clave)
        if campo is None:
            errores[clave] = "Este dato no existe en la categoría."
            continue
        try:
            normal = _normalizar(campo, valor)
        except ValueError as error:
            errores[clave] = f"{campo.nombre}: {error}."
            continue
        if normal is not None:
            limpios[clave] = normal
    if errores:
        raise ValidationError({"especificaciones": errores})
    return limpios


def podar(categoria: Categoria, valores: dict | None) -> dict:
    """Deja solo los valores cuyo campo sigue activo en la categoría (al cambiarla de categoría)."""
    if not valores:
        return {}
    activas = {c.clave for c in campos_de(categoria, solo_activos=True)}
    return {k: v for k, v in valores.items() if k in activas}


# ---------------------------------------------------------------------------
# Datos de la tienda del producto
# ---------------------------------------------------------------------------
def validar_slug(organizacion_id: int, slug: str, *, excluir: Producto | None = None) -> str:
    slug = (slug or "").strip().lower()
    if not _SLUG.fullmatch(slug) or len(slug) > 200:
        raise ValidationError(
            {"slug": "Use letras minúsculas, números y guiones (ej. laptop-lenovo-i5)."}
        )
    otros = Producto.objects.filter(organizacion_id=organizacion_id, slug=slug)
    if excluir is not None and excluir.pk:
        otros = otros.exclude(pk=excluir.pk)
    if otros.exists():
        raise ValidationError({"slug": "Ya hay un producto con esa dirección web."})
    return slug


def generar_slug(organizacion_id: int, nombre: str, *, excluir: Producto | None = None) -> str:
    """Una dirección web a partir del nombre, sin repetir las de otros productos."""
    base = slugify(nombre) or "producto"
    if len(base) > MAX_SLUG_AUTOMATICO:  # nombres larguísimos: se corta en una palabra completa
        base = base[:MAX_SLUG_AUTOMATICO].rsplit("-", 1)[0] or base[:MAX_SLUG_AUTOMATICO]
    base = base.strip("-") or "producto"
    otros = Producto.objects.filter(organizacion_id=organizacion_id)
    if excluir is not None and excluir.pk:
        otros = otros.exclude(pk=excluir.pk)
    usados = set(otros.filter(slug__startswith=base).values_list("slug", flat=True))
    slug, n = base, 2
    while slug in usados:
        slug = f"{base}-{n}"
        n += 1
    return slug


def validar_puntos(puntos) -> list[str]:
    if puntos in (None, ""):
        return []
    if not isinstance(puntos, (list, tuple)):
        raise ValidationError({"puntos_destacados": "Envíe una lista de frases."})
    limpios = [_texto(p, 120) for p in puntos if _texto(p, 120)]
    if len(limpios) > 8:
        raise ValidationError({"puntos_destacados": "Admite hasta 8 puntos destacados."})
    return limpios
