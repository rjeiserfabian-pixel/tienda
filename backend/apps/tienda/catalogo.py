"""Catálogo de la tienda pública: qué se ve, a qué precio y con qué stock.

Todo lo que sale de aquí es PÚBLICO (lo lee cualquiera, sin sesión), así que se arma con cuidado:

* Solo se muestran productos PUBLICADOS y ACTIVOS de la organización de la tienda. Nada más.
* Nunca se expone el costo, la utilidad, las demás listas de precios ni el stock exacto (solo
  «disponible», «pocas unidades» con su número, o «agotado»).
* Las consultas no usan el aislamiento por sesión (no hay sesión): filtran SIEMPRE por la
  organización de la tienda de forma explícita.
* El precio sale de UNA lista de precios (la que se eligió en la configuración) y se le suma el IGV
  solo para mostrarlo. El monto final de una compra lo recalcula Ventas al cobrar, porque depende de
  la zona de entrega (por ejemplo, la exoneración de la Amazonía).
"""

import logging
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings
from django.core.cache import cache
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone

from apps.inventario.models import SaldoStock
from apps.mantenimiento.fiscal import tasa_vigente
from apps.mantenimiento.models import (
    Almacen,
    CampoEspecificacion,
    Categoria,
    EstadoRegistro,
    Familia,
    FotoProducto,
    ListaPrecio,
    Marca,
    PrecioProducto,
    Producto,
    TipoProducto,
)

from .models import ConfiguracionTienda, OfertaProducto, ReservaStock

logger = logging.getLogger(__name__)

Tipo = CampoEspecificacion.Tipo
CENTIMO = Decimal("0.01")
CIEN = Decimal("100")
TAM_PAGINA = 24
MAX_PAGINA = 48
MAX_FILAS_FACETAS = 5000
MAX_PALABRAS = 5
SEGUNDOS_CONTEXTO = 60
RUTA_FOTOS = "/api/v1/tienda/fotos"
CLAVE_VERSION = "tienda:version"


# ---------------------------------------------------------------------------
# Caché de respuestas: una «versión» que se sube cuando cambia el catálogo
# ---------------------------------------------------------------------------
def version() -> int:
    """Número que forma parte de cada clave de caché: subirlo invalida todas las respuestas."""
    valor = cache.get(CLAVE_VERSION)
    if valor is None:
        cache.add(CLAVE_VERSION, 1, None)
        valor = cache.get(CLAVE_VERSION) or 1
    return valor


def invalidar() -> None:
    """El catálogo cambió (producto, foto, precio…): las respuestas guardadas ya no valen."""
    try:
        cache.incr(CLAVE_VERSION)
    except ValueError:
        cache.set(CLAVE_VERSION, 2, None)
    cache.delete("tienda:contexto")
    _avisar_a_la_tienda()


def _avisar_a_la_tienda() -> None:
    """Pide a la tienda renovar sus páginas, junto con otros cambios seguidos (una sola vez)."""
    if not (settings.TIENDA_RENOVAR_URL and settings.TIENDA_RENOVAR_TOKEN):
        return
    from .tasks import renovar_tienda

    if cache.add("tienda:renovar:pendiente", 1, 5):
        try:
            renovar_tienda.apply_async(countdown=2)
        except Exception:  # noqa: BLE001 - sin el broker la tienda se renueva sola por tiempo
            logger.warning("tienda_renovar_no_encolada")


# ---------------------------------------------------------------------------
# Contexto: la organización de la tienda y su configuración
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Contexto:
    organizacion_id: int
    nombre: str
    lista_id: int | None
    almacen_ids: tuple[int, ...]
    igv: Decimal  # porcentaje; 0 si no hay tasa vigente
    precios_con_igv: bool
    pocas: int
    permite_envio: bool = True
    permite_recojo: bool = True
    peso_defecto_kg: Decimal = Decimal("1")


def _calcular_contexto() -> Contexto | None:
    configuraciones = ConfiguracionTienda.objects.sin_ambito().filter(activa=True)
    if settings.TIENDA_ORGANIZACION_ID:
        configuraciones = configuraciones.filter(organizacion_id=settings.TIENDA_ORGANIZACION_ID)
    activas = list(configuraciones[:2])
    if len(activas) != 1:
        if len(activas) > 1:
            logger.error(
                "tienda_ambigua",
                extra={"detalle": "Varias tiendas activas; indique TIENDA_ORGANIZACION_ID"},
            )
        return None
    config = activas[0]
    org = config.organizacion_id
    lista_id = config.lista_precio_id
    if lista_id is None:
        lista_id = (
            ListaPrecio.objects.sin_ambito()
            .filter(organizacion_id=org, es_principal=True, estado=EstadoRegistro.ACTIVO)
            .values_list("pk", flat=True)
            .first()
        )
    elegidos = ConfiguracionTienda.almacenes.through.objects.filter(
        configuraciontienda_id=config.pk
    ).values_list("almacen_id", flat=True)
    almacenes = tuple(
        Almacen.objects.sin_ambito()
        .filter(pk__in=list(elegidos), estado=EstadoRegistro.ACTIVO)
        .values_list("pk", flat=True)
    )
    try:
        igv = tasa_vigente(org, "IGV")
    except Exception:  # noqa: BLE001 - sin tasa cargada se muestran los precios sin IGV
        logger.warning("tienda_sin_tasa_igv", extra={"organizacion_id": org})
        igv = Decimal("0")
    return Contexto(
        organizacion_id=org,
        nombre=config.nombre,
        lista_id=lista_id,
        almacen_ids=almacenes,
        igv=igv,
        precios_con_igv=config.precios_con_igv,
        pocas=config.pocas_unidades,
        permite_envio=config.permite_envio,
        permite_recojo=config.permite_recojo,
        peso_defecto_kg=config.peso_por_defecto_kg,
    )


def contexto() -> Contexto | None:
    """La tienda activa, o ``None`` si no hay (apagada o sin configurar). Se guarda un minuto."""
    guardado = cache.get("tienda:contexto")
    if guardado is not None:
        return guardado or None
    calculado = _calcular_contexto()
    cache.set("tienda:contexto", calculado or False, SEGUNDOS_CONTEXTO)
    return calculado


# ---------------------------------------------------------------------------
# Consulta base de productos públicos
# ---------------------------------------------------------------------------
def productos_publicos(ctx: Contexto):
    """Productos publicados y activos, con su precio web, su stock sumado y su foto principal."""
    precio = Subquery(
        PrecioProducto.objects.sin_ambito()
        .filter(producto=OuterRef("pk"), lista_id=ctx.lista_id)
        .values("precio")[:1]
    )
    stock = Subquery(
        SaldoStock.objects.sin_ambito()
        .filter(producto=OuterRef("pk"), almacen_id__in=ctx.almacen_ids)
        .values("producto")
        .annotate(total=Sum("cantidad"))
        .values("total")[:1]
    )
    # Lo apartado para pedidos que todavía se están pagando no se ofrece a nadie más.
    reservado = Subquery(
        ReservaStock.objects.sin_ambito()
        .filter(producto=OuterRef("pk"), almacen_id__in=ctx.almacen_ids, liberada_en__isnull=True)
        .values("producto")
        .annotate(total=Sum("cantidad"))
        .values("total")[:1]
    )
    foto = Subquery(
        FotoProducto.objects.sin_ambito()
        .filter(producto=OuterRef("pk"))
        .order_by("-es_principal", "orden", "id")
        .values("id")[:1]
    )
    # La oferta vigente AHORA (la de menor precio si hubiera más de una). Se evalúa con la hora de
    # la consulta: las respuestas guardadas duran poco y una tarea las renueva al empezar/terminar.
    ahora = timezone.now()
    oferta = (
        OfertaProducto.objects.sin_ambito()
        .filter(producto=OuterRef("pk"), activa=True, desde__lte=ahora, hasta__gt=ahora)
        .order_by("precio_oferta", "id")
    )
    return (
        Producto.objects.sin_ambito()
        .filter(
            organizacion_id=ctx.organizacion_id,
            publicado_web=True,
            estado=EstadoRegistro.ACTIVO,
            categoria__estado=EstadoRegistro.ACTIVO,
        )
        .filter(Q(marca__isnull=True) | Q(marca__estado=EstadoRegistro.ACTIVO))
        .select_related("marca", "categoria__familia", "afectacion_igv")
        .annotate(
            precio_web=precio,
            stock_web=Coalesce(
                stock,
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            )
            - Coalesce(
                reservado,
                Value(Decimal("0")),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            ),
            foto_principal_id=foto,
            precio_oferta=Subquery(oferta.values("precio_oferta")[:1]),
            oferta_hasta=Subquery(oferta.values("hasta")[:1]),
            oferta_etiqueta=Subquery(oferta.values("etiqueta")[:1]),
        )
        # El precio que cuenta: el de oferta si es de verdad menor que el normal.
        .annotate(
            precio_vigente=Case(
                When(precio_oferta__lt=F("precio_web"), then=F("precio_oferta")),
                default=F("precio_web"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            # Cuánto se ahorra (0 a 1) sobre el precio normal; vacío si no está en oferta.
            descuento_relativo=Case(
                When(
                    precio_oferta__lt=F("precio_web"),
                    then=ExpressionWrapper(
                        (F("precio_web") - F("precio_oferta")) / F("precio_web"),
                        output_field=DecimalField(max_digits=12, decimal_places=6),
                    ),
                ),
                default=None,
                output_field=DecimalField(max_digits=12, decimal_places=6),
            ),
        )
    )


# ---------------------------------------------------------------------------
# Formato de lo que se muestra
# ---------------------------------------------------------------------------
def _dinero(valor: Decimal) -> str:
    return format(valor.quantize(CENTIMO, rounding=ROUND_HALF_UP), "f")


def _con_igv(base: Decimal, p, ctx: Contexto) -> tuple[Decimal, Decimal, bool]:
    """``(con IGV, el que se muestra, paga IGV)`` para un precio base sin IGV."""
    paga = ctx.igv > 0 and (p.afectacion_igv is None or p.afectacion_igv.paga_impuesto)
    con_igv = base * (Decimal(1) + ctx.igv / CIEN) if paga else base
    return con_igv, (con_igv if ctx.precios_con_igv else base), bool(paga)


def _precios(p, ctx: Contexto) -> dict:
    normal = p.precio_web
    if normal is None:
        return {
            "consultar_precio": True,
            "precio": None,
            "precio_con_igv": None,
            "precio_mostrar": None,
            "incluye_igv": False,
            "precio_normal_mostrar": None,
            "descuento_pct": None,
            "oferta": None,
        }
    oferta_base = getattr(p, "precio_oferta", None)
    en_oferta = oferta_base is not None and oferta_base < normal
    base = oferta_base if en_oferta else normal
    con_igv, mostrar, paga = _con_igv(base, p, ctx)
    salida = {
        "consultar_precio": False,
        "precio": _dinero(base),
        "precio_con_igv": _dinero(con_igv),
        "precio_mostrar": _dinero(mostrar),
        "incluye_igv": bool(ctx.precios_con_igv and paga),
        "precio_normal_mostrar": None,
        "descuento_pct": None,
        "oferta": None,
    }
    if en_oferta:
        _, normal_mostrar, _ = _con_igv(normal, p, ctx)
        salida["precio_normal_mostrar"] = _dinero(normal_mostrar)
        salida["descuento_pct"] = max(
            1, int(((1 - mostrar / normal_mostrar) * CIEN).quantize(Decimal("1"), ROUND_HALF_UP))
        )
        salida["oferta"] = {
            "etiqueta": getattr(p, "oferta_etiqueta", "") or "",
            "termina_en": p.oferta_hasta.isoformat() if getattr(p, "oferta_hasta", None) else None,
        }
    return salida


def _disponibilidad(p, ctx: Contexto) -> dict:
    """«disponible», «pocas» (con las unidades que quedan) o «agotado». Nunca el stock exacto."""
    if p.tipo == TipoProducto.SERVICIO or not p.controla_stock:
        return {"disponibilidad": "disponible", "unidades": None}
    stock = p.stock_web or Decimal("0")
    if stock < 1:
        return {"disponibilidad": "agotado", "unidades": 0}
    if stock <= ctx.pocas:
        return {"disponibilidad": "pocas", "unidades": int(stock)}
    return {"disponibilidad": "disponible", "unidades": None}


def url_foto(foto_id: int, tam: str) -> str:
    return f"{RUTA_FOTOS}/{foto_id}/{tam}/"


def _valor_texto(campo: CampoEspecificacion, valor) -> str:
    if campo.tipo == Tipo.SI_NO:
        return "Sí" if valor else "No"
    texto = str(valor)
    if campo.tipo == Tipo.NUMERO and campo.unidad:
        return f"{texto} {campo.unidad}"
    return texto


def campos_activos(categoria_id: int) -> list[CampoEspecificacion]:
    return list(
        CampoEspecificacion.objects.sin_ambito()
        .filter(categoria_id=categoria_id, estado=EstadoRegistro.ACTIVO)
        .order_by("orden", "id")
    )


def _campos_de_tarjeta(categoria_ids: set[int]) -> dict[int, list[CampoEspecificacion]]:
    """Los datos que se ven en la tarjeta, por categoría, con una sola consulta."""
    mapa: dict[int, list[CampoEspecificacion]] = {}
    filas = (
        CampoEspecificacion.objects.sin_ambito()
        .filter(categoria_id__in=categoria_ids, estado=EstadoRegistro.ACTIVO, en_tarjeta=True)
        .order_by("orden", "id")
    )
    for campo in filas:
        mapa.setdefault(campo.categoria_id, []).append(campo)
    return mapa


def tarjetas(productos: list, ctx: Contexto) -> list[dict]:
    """Los productos como tarjetas de listado."""
    por_categoria = _campos_de_tarjeta({p.categoria_id for p in productos})
    salida = []
    for p in productos:
        datos = []
        for campo in por_categoria.get(p.categoria_id, []):
            valor = (p.especificaciones or {}).get(campo.clave)
            if valor is not None:
                datos.append({"nombre": campo.nombre, "valor": _valor_texto(campo, valor)})
        salida.append(
            {
                "id": p.pk,
                "slug": p.slug,
                "nombre": p.nombre,
                "marca": {"nombre": p.marca.nombre, "slug": p.marca.slug} if p.marca else None,
                "categoria": {"nombre": p.categoria.nombre, "slug": p.categoria.slug},
                "foto": url_foto(p.foto_principal_id, "mini") if p.foto_principal_id else None,
                "nuevo": p.es_nuevo,
                "destacado": p.destacado,
                "tarjeta": datos,
                **_precios(p, ctx),
                **_disponibilidad(p, ctx),
            }
        )
    return salida


# ---------------------------------------------------------------------------
# Filtros del listado
# ---------------------------------------------------------------------------
def _decimal_o_none(texto) -> Decimal | None:
    try:
        valor = Decimal(str(texto).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return valor if valor.is_finite() and 0 <= valor <= Decimal("100000000") else None


def _valor_de_filtro(campo: CampoEspecificacion, texto: str):
    """El valor de la dirección convertido a como se guarda; ``None`` si no sirve."""
    texto = (texto or "").strip()
    if not texto:
        return None
    if campo.tipo == Tipo.SI_NO:
        return {"1": True, "si": True, "sí": True, "0": False, "no": False}.get(texto.lower())
    if campo.tipo == Tipo.NUMERO:
        numero = _decimal_o_none(texto)
        return None if numero is None else format(numero.normalize(), "f")
    if campo.tipo == Tipo.LISTA and campo.opciones:
        por_minuscula = {str(o).lower(): o for o in campo.opciones}
        return por_minuscula.get(texto.lower())
    return None  # el texto libre no se usa como filtro


def _aplicar_busqueda(qs, texto: str):
    palabras = [w for w in texto.split() if len(w) >= 2][:MAX_PALABRAS]
    for palabra in palabras:
        qs = qs.filter(
            Q(nombre__icontains=palabra)
            | Q(codigo__icontains=palabra)
            | Q(codigo_fabricante__icontains=palabra)
            | Q(marca__nombre__icontains=palabra)
            | Q(categoria__nombre__icontains=palabra)
        )
    return qs


def _categoria_por_slug(ctx: Contexto, slug: str) -> Categoria:
    categoria = (
        Categoria.objects.sin_ambito()
        .select_related("familia")
        .filter(organizacion_id=ctx.organizacion_id, slug=slug, estado=EstadoRegistro.ACTIVO)
        .first()
    )
    if categoria is None:
        raise Http404
    return categoria


def _entero(valor, defecto: int, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return defecto
    return max(minimo, min(n, maximo))


ORDENES = {
    "relevancia": ("-destacado", "-es_nuevo", "-creado_en", "id"),
    "nuevos": ("-creado_en", "id"),
    "nombre": ("nombre", "id"),
}


def _ordenar(qs, orden: str):
    if orden == "precio_asc":
        return qs.order_by(F("precio_vigente").asc(nulls_last=True), "id")
    if orden == "precio_desc":
        return qs.order_by(F("precio_vigente").desc(nulls_last=True), "id")
    if orden == "descuento":
        # Mayor ahorro primero (sobre el precio normal); lo que no está en oferta, al final.
        return qs.order_by(F("descuento_relativo").desc(nulls_last=True), "id")
    return qs.order_by(*ORDENES.get(orden, ORDENES["relevancia"]))


# ---------------------------------------------------------------------------
# Facetas (los filtros que se ofrecen)
# ---------------------------------------------------------------------------
def _facetas(qs, ctx: Contexto, categoria: Categoria | None) -> dict:
    """Qué filtros se pueden ofrecer sobre este conjunto de productos, con sus cantidades."""
    sin_orden = qs.order_by()
    marcas = (
        sin_orden.exclude(marca__isnull=True)
        .values("marca__nombre", "marca__slug")
        .annotate(cantidad=Count("id"))
        .order_by("marca__nombre")
    )
    rango = sin_orden.aggregate(minimo=Min("precio_vigente"), maximo=Max("precio_vigente"))
    factor = (Decimal(1) + ctx.igv / CIEN) if ctx.precios_con_igv and ctx.igv > 0 else Decimal(1)
    precio = {
        "minimo": _dinero(rango["minimo"] * factor) if rango["minimo"] is not None else None,
        "maximo": _dinero(rango["maximo"] * factor) if rango["maximo"] is not None else None,
    }
    especificaciones = []
    if categoria is not None:
        campos = [c for c in campos_activos(categoria.pk) if c.es_filtro]
        if campos:
            filas = list(sin_orden.values_list("especificaciones", flat=True)[:MAX_FILAS_FACETAS])
            for campo in campos:
                opciones = _opciones_de_faceta(campo, filas)
                if opciones:
                    especificaciones.append(
                        {
                            "clave": campo.clave,
                            "nombre": campo.nombre,
                            "tipo": campo.tipo,
                            "unidad": campo.unidad,
                            "opciones": opciones,
                        }
                    )
    return {
        "marcas": [
            {"nombre": m["marca__nombre"], "slug": m["marca__slug"], "cantidad": m["cantidad"]}
            for m in marcas
        ],
        "precio": precio,
        "especificaciones": especificaciones,
    }


def _opciones_de_faceta(campo: CampoEspecificacion, filas: list) -> list[dict]:
    cuenta: Counter = Counter()
    for valores in filas:
        valor = (valores or {}).get(campo.clave)
        if valor is None:
            continue
        cuenta[str(valor) if campo.tipo != Tipo.SI_NO else bool(valor)] += 1
    if campo.tipo == Tipo.SI_NO:
        return [
            {"valor": "1" if v else "0", "etiqueta": "Sí" if v else "No", "cantidad": n}
            for v, n in sorted(cuenta.items(), key=lambda x: not x[0])
        ]
    if campo.tipo == Tipo.NUMERO:
        ordenado = sorted(cuenta.items(), key=lambda x: Decimal(x[0]))
        return [
            {
                "valor": v,
                "etiqueta": f"{v} {campo.unidad}".strip(),
                "cantidad": n,
            }
            for v, n in ordenado
        ]
    orden_opciones = {str(o): i for i, o in enumerate(campo.opciones)}
    ordenado = sorted(cuenta.items(), key=lambda x: (orden_opciones.get(x[0], 9999), x[0]))
    return [{"valor": v, "etiqueta": v, "cantidad": n} for v, n in ordenado]


# ---------------------------------------------------------------------------
# Listado
# ---------------------------------------------------------------------------
def listar(ctx: Contexto, params) -> dict:
    """Productos de la tienda con filtros, orden y paginación (``params`` = la dirección)."""
    qs = productos_publicos(ctx)
    categoria = None
    if slug := params.get("categoria"):
        categoria = _categoria_por_slug(ctx, slug)
        qs = qs.filter(categoria=categoria)
    elif slug := params.get("familia"):
        familia = (
            Familia.objects.sin_ambito()
            .filter(organizacion_id=ctx.organizacion_id, slug=slug, estado=EstadoRegistro.ACTIVO)
            .first()
        )
        if familia is None:
            raise Http404
        qs = qs.filter(categoria__familia=familia)
    if texto := (params.get("q") or "").strip()[:80]:
        qs = _aplicar_busqueda(qs, texto)
    if params.get("nuevo") == "1":
        qs = qs.filter(es_nuevo=True)
    if params.get("destacado") == "1":
        qs = qs.filter(destacado=True)
    if params.get("oferta") == "1":
        qs = qs.filter(precio_oferta__isnull=False, precio_oferta__lt=F("precio_web"))
    if params.get("disponible") == "1":
        qs = qs.filter(
            Q(stock_web__gte=1) | Q(tipo=TipoProducto.SERVICIO) | Q(controla_stock=False)
        )
    factor = (Decimal(1) + ctx.igv / CIEN) if ctx.precios_con_igv and ctx.igv > 0 else Decimal(1)
    minimo, maximo = (
        _decimal_o_none(params.get("precio_min")),
        _decimal_o_none(params.get("precio_max")),
    )
    if minimo is not None:
        qs = qs.filter(precio_vigente__gte=minimo / factor)
    if maximo is not None:
        qs = qs.filter(precio_vigente__lte=maximo / factor)

    # Las facetas se calculan ANTES de marca y especificaciones: así se ve lo que hay disponible.
    facetas = _facetas(qs, ctx, categoria) if params.get("facetas") == "1" else None

    marcas = [m for m in params.getlist("marca") if m][:10]
    if marcas:
        qs = qs.filter(marca__slug__in=marcas)
    if categoria is not None:
        for campo in (c for c in campos_activos(categoria.pk) if c.es_filtro):
            pedidos = params.getlist(f"esp.{campo.clave}")[:20]
            valores = [v for v in (_valor_de_filtro(campo, t) for t in pedidos) if v is not None]
            if valores:
                condicion = Q()
                for v in valores:
                    condicion |= Q(especificaciones__contains={campo.clave: v})
                qs = qs.filter(condicion)

    qs = _ordenar(qs, params.get("orden") or "relevancia")
    total = qs.count()
    tam = _entero(params.get("page_size"), TAM_PAGINA, 1, MAX_PAGINA)
    paginas = max((total + tam - 1) // tam, 1)
    pagina = _entero(params.get("page"), 1, 1, paginas)
    filas = list(qs[(pagina - 1) * tam : pagina * tam])
    respuesta = {
        "count": total,
        "page": pagina,
        "page_size": tam,
        "paginas": paginas,
        "categoria": (
            {
                "nombre": categoria.nombre,
                "slug": categoria.slug,
                "familia": {"nombre": categoria.familia.nombre, "slug": categoria.familia.slug},
            }
            if categoria
            else None
        ),
        "results": tarjetas(filas, ctx),
    }
    if facetas is not None:
        respuesta["filtros"] = facetas
    return respuesta


# ---------------------------------------------------------------------------
# Ficha de un producto
# ---------------------------------------------------------------------------
def detalle(ctx: Contexto, slug: str) -> dict:
    producto = productos_publicos(ctx).filter(slug=slug).first()
    if producto is None:
        raise Http404
    fotos = list(
        FotoProducto.objects.sin_ambito()
        .filter(producto=producto)
        .order_by("-es_principal", "orden", "id")
    )
    campos = campos_activos(producto.categoria_id)
    valores = producto.especificaciones or {}
    secciones: dict[str, list[dict]] = {}
    for campo in campos:
        if campo.clave in valores and valores[campo.clave] is not None:
            secciones.setdefault(campo.seccion, []).append(
                {"nombre": campo.nombre, "valor": _valor_texto(campo, valores[campo.clave])}
            )
    relacionados = list(
        productos_publicos(ctx)
        .filter(categoria_id=producto.categoria_id)
        .exclude(pk=producto.pk)
        .order_by("-destacado", "-es_nuevo", "-creado_en", "id")[:8]
    )
    marca = (
        {"nombre": producto.marca.nombre, "slug": producto.marca.slug} if producto.marca else None
    )
    descripcion = producto.descripcion_web or producto.descripcion
    return {
        "id": producto.pk,
        "slug": producto.slug,
        "codigo": producto.codigo,
        "numero_de_parte": producto.codigo_fabricante,
        "nombre": producto.nombre,
        "marca": marca,
        "categoria": {"nombre": producto.categoria.nombre, "slug": producto.categoria.slug},
        "familia": {
            "nombre": producto.categoria.familia.nombre,
            "slug": producto.categoria.familia.slug,
        },
        "descripcion": descripcion,
        "puntos_destacados": list(producto.puntos_destacados or []),
        "especificaciones": [{"seccion": s, "datos": d} for s, d in secciones.items()],
        "garantia_meses": producto.garantia_meses,
        "peso_kg": format(producto.peso_kg, "f") if producto.peso_kg is not None else None,
        "medidas_cm": {
            "largo": format(producto.largo_cm, "f") if producto.largo_cm is not None else None,
            "ancho": format(producto.ancho_cm, "f") if producto.ancho_cm is not None else None,
            "alto": format(producto.alto_cm, "f") if producto.alto_cm is not None else None,
        },
        "nuevo": producto.es_nuevo,
        "destacado": producto.destacado,
        "fotos": [
            {
                "id": f.pk,
                "mini": url_foto(f.pk, "mini"),
                "grande": url_foto(f.pk, "grande"),
                "principal": f.es_principal,
            }
            for f in fotos
        ],
        "migas": [
            {"nombre": "Inicio", "slug": None, "tipo": "inicio"},
            {
                "nombre": producto.categoria.familia.nombre,
                "slug": producto.categoria.familia.slug,
                "tipo": "familia",
            },
            {
                "nombre": producto.categoria.nombre,
                "slug": producto.categoria.slug,
                "tipo": "categoria",
            },
        ],
        "relacionados": tarjetas(relacionados, ctx),
        "seo": {
            "titulo": f"{producto.nombre} | {ctx.nombre}"[:70],
            "descripcion": (descripcion or "").strip()[:160],
        },
        **_precios(producto, ctx),
        **_disponibilidad(producto, ctx),
    }


# ---------------------------------------------------------------------------
# Comparador
# ---------------------------------------------------------------------------
MAX_COMPARAR = 4


def _seccion_de_datos(productos: list) -> dict | None:
    """Filas comunes a todo producto (marca, garantía, peso), si alguno tiene el dato."""
    filas = []
    marcas = [p.marca.nombre if p.marca else None for p in productos]
    garantias = [f"{p.garantia_meses} meses" if p.garantia_meses else None for p in productos]
    pesos = [f"{format(p.peso_kg, 'f')} kg" if p.peso_kg is not None else None for p in productos]
    for nombre, valores in (("Marca", marcas), ("Garantía", garantias), ("Peso", pesos)):
        if any(v is not None for v in valores):
            filas.append(
                {
                    "nombre": nombre,
                    "unidad": "",
                    "valores": valores,
                    "difiere": len(set(valores)) > 1,
                }
            )
    return {"seccion": "Datos del producto", "filas": filas} if filas else None


def comparar(ctx: Contexto, ids: list[int]) -> dict:
    """Varios productos lado a lado, con una tabla de especificaciones unificada.

    Misma categoría: se usa su plantilla (orden y secciones ya definidos). Categorías distintas: los
    campos se unen por nombre. Solo productos publicados y activos; nunca costos ni stock exacto.
    """
    avisos: list[str] = []
    por_id = {p.pk: p for p in productos_publicos(ctx).filter(pk__in=ids)}
    productos = []
    for pk in ids:
        if pk in por_id:
            productos.append(por_id[pk])
        else:
            avisos.append(f"El producto {pk} ya no está disponible y no se comparó.")
    tarjeta_de = {t["id"]: t for t in tarjetas(productos, ctx)}
    misma = len({p.categoria_id for p in productos}) <= 1
    campos_por_categoria = {cid: campos_activos(cid) for cid in {p.categoria_id for p in productos}}

    # Un renglón por campo: clave = la del campo (misma categoría) o su nombre (categorías mixtas).
    filas: dict[tuple[str, str], dict] = {}
    for indice, producto in enumerate(productos):
        valores = producto.especificaciones or {}
        for campo in campos_por_categoria[producto.categoria_id]:
            llave = (campo.seccion, campo.clave if misma else campo.nombre.strip().lower())
            fila = filas.setdefault(
                llave,
                {
                    "seccion": campo.seccion,
                    "nombre": campo.nombre,
                    "unidad": campo.unidad if campo.tipo == Tipo.NUMERO else "",
                    "valores": [None] * len(productos),
                },
            )
            if valores.get(campo.clave) is not None:
                fila["valores"][indice] = _valor_texto(campo, valores[campo.clave])
    secciones: dict[str, list[dict]] = {}
    for fila in filas.values():
        if all(v is None for v in fila["valores"]):
            continue  # nadie tiene ese dato: no aporta a la comparación
        fila["difiere"] = len(set(fila["valores"])) > 1
        secciones.setdefault(fila.pop("seccion"), []).append(fila)
    tabla = [{"seccion": s, "filas": f} for s, f in secciones.items()]
    datos = _seccion_de_datos(productos)
    if datos:
        tabla.insert(0, datos)
    return {
        # Se copia la tarjeta completa (precio, oferta, disponibilidad…): el comparador muestra
        # siempre lo mismo que el listado; solo se omiten los datos que ya van en la tabla.
        "productos": [
            {k: v for k, v in tarjeta_de[p.pk].items() if k != "tarjeta"} for p in productos
        ],
        "misma_categoria": misma,
        "secciones": tabla,
        "avisos": avisos,
    }


# ---------------------------------------------------------------------------
# Menú, inicio, sugerencias y mapa del sitio
# ---------------------------------------------------------------------------
def menu(ctx: Contexto) -> dict:
    """Familias con sus categorías y las marcas, solo donde hay productos publicados."""
    base = productos_publicos(ctx).order_by()
    por_categoria = {
        f["categoria_id"]: f["n"] for f in base.values("categoria_id").annotate(n=Count("id"))
    }
    por_marca = {
        f["marca_id"]: f["n"]
        for f in base.exclude(marca__isnull=True).values("marca_id").annotate(n=Count("id"))
    }
    categorias = (
        Categoria.objects.sin_ambito()
        .filter(
            organizacion_id=ctx.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            pk__in=list(por_categoria),
        )
        .order_by("nombre")
    )
    por_familia: dict[int, list[dict]] = {}
    for c in categorias:
        por_familia.setdefault(c.familia_id, []).append(
            {"nombre": c.nombre, "slug": c.slug, "cantidad": por_categoria[c.pk]}
        )
    familias = (
        Familia.objects.sin_ambito()
        .filter(
            organizacion_id=ctx.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            pk__in=list(por_familia),
        )
        .order_by("nombre")
    )
    marcas = (
        Marca.objects.sin_ambito()
        .filter(
            organizacion_id=ctx.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            pk__in=list(por_marca),
        )
        .order_by("nombre")
    )
    return {
        "tienda": {"nombre": ctx.nombre, "precios_con_igv": ctx.precios_con_igv},
        "familias": [
            {
                "nombre": f.nombre,
                "slug": f.slug,
                "cantidad": sum(c["cantidad"] for c in por_familia[f.pk]),
                "categorias": por_familia[f.pk],
            }
            for f in familias
        ],
        "marcas": [
            {"nombre": m.nombre, "slug": m.slug, "cantidad": por_marca[m.pk]} for m in marcas
        ],
        "secciones": _secciones(ctx),
    }


def _secciones(ctx: Contexto) -> dict:
    """Qué secciones opcionales tienen algo que mostrar (para ponerlas en el menú)."""
    from .models import ConfiguracionArmador
    from .ofertas import vigentes

    return {
        "ofertas": vigentes(ctx.organizacion_id).exists(),
        "armador": ConfiguracionArmador.objects.sin_ambito()
        .filter(organizacion_id=ctx.organizacion_id, activo=True)
        .exists(),
    }


def inicio(ctx: Contexto) -> dict:
    """Lo que se muestra en la portada: destacados y novedades."""
    base = productos_publicos(ctx)
    destacados = list(base.filter(destacado=True).order_by("-creado_en", "id")[:12])
    novedades = list(base.filter(es_nuevo=True).order_by("-creado_en", "id")[:12])
    ofertas = list(
        base.filter(precio_oferta__isnull=False, precio_oferta__lt=F("precio_web")).order_by(
            F("descuento_relativo").desc(), "id"
        )[:12]
    )
    return {
        "destacados": tarjetas(destacados, ctx),
        "novedades": tarjetas(novedades, ctx),
        "ofertas": tarjetas(ofertas, ctx),
    }


def sugerencias(ctx: Contexto, texto: str) -> dict:
    """Ayuda al escribir en el buscador: unos productos, categorías y marcas que coinciden."""
    texto = (texto or "").strip()[:60]
    if len(texto) < 2:
        return {"productos": [], "categorias": [], "marcas": []}
    productos = list(
        _aplicar_busqueda(productos_publicos(ctx), texto).order_by("-destacado", "nombre")[:6]
    )
    categorias = list(
        Categoria.objects.sin_ambito()
        .filter(
            organizacion_id=ctx.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            nombre__icontains=texto,
            productos__publicado_web=True,
            productos__estado=EstadoRegistro.ACTIVO,
        )
        .distinct()
        .order_by("nombre")[:3]
    )
    marcas = list(
        Marca.objects.sin_ambito()
        .filter(
            organizacion_id=ctx.organizacion_id,
            estado=EstadoRegistro.ACTIVO,
            nombre__icontains=texto,
            productos__publicado_web=True,
            productos__estado=EstadoRegistro.ACTIVO,
        )
        .distinct()
        .order_by("nombre")[:3]
    )
    return {
        "productos": [
            {
                "slug": t["slug"],
                "nombre": t["nombre"],
                "foto": t["foto"],
                "precio_mostrar": t["precio_mostrar"],
                "consultar_precio": t["consultar_precio"],
            }
            for t in tarjetas(productos, ctx)
        ],
        "categorias": [{"nombre": c.nombre, "slug": c.slug} for c in categorias],
        "marcas": [{"nombre": m.nombre, "slug": m.slug} for m in marcas],
    }


def mapa_del_sitio(ctx: Contexto) -> dict:
    """Las direcciones públicas, para que los buscadores indexen la tienda."""
    productos = productos_publicos(ctx).order_by("id").values_list("slug", "actualizado_en")[:5000]
    menu_actual = menu(ctx)
    return {
        "generado": timezone.now().isoformat(),
        "productos": [{"slug": s, "actualizado": a.isoformat()} for s, a in productos],
        "categorias": [c["slug"] for f in menu_actual["familias"] for c in f["categorias"]],
        "marcas": [m["slug"] for m in menu_actual["marcas"]],
    }


def foto_publica(ctx: Contexto, foto_id: int) -> FotoProducto | None:
    """La foto, solo si es de un producto publicado y activo de la tienda."""
    return (
        FotoProducto.objects.sin_ambito()
        .filter(
            pk=foto_id,
            producto__organizacion_id=ctx.organizacion_id,
            producto__publicado_web=True,
            producto__estado=EstadoRegistro.ACTIVO,
        )
        .first()
    )
