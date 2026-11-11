"""Guías de remisión: el documento que acompaña la mercadería vendida hasta el cliente.

La guía la emite la empresa que vendió (cada comprobante, con su empresa, tiene las suyas), con su
propia serie. Dice qué viaja, desde dónde, hacia dónde y quién lo lleva:

* **Transporte público:** una empresa de transporte (de la lista de Mantenimiento o, si no, su
  nombre y RUC escritos a mano).
* **Transporte privado:** la propia empresa con su conductor y su vehículo (de las listas o escritos
  a mano). Si el traslado es en un vehículo de categoría M1 o L no se exige conductor ni placa.

El destinatario es el cliente de la venta, o el cliente registrado que se indique. Cada producto
puede llevar su peso. No mueve stock. Se pueden hacer envíos parciales: entre todas las guías
vigentes de un comprobante no se envía más de lo que se vendió.
"""

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Exists, F, OuterRef, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.inventario import periodos
from apps.inventario.models import (
    LineaMovimiento,
    MovimientoInventario,
    OrigenMovimiento,
    TipoMovimiento,
)
from apps.mantenimiento.models import (
    Almacen,
    Cliente,
    Conductor,
    EmpresaTransporte,
    EstadoRegistro,
    SerieComprobante,
    TipoComprobante,
    Ubigeo,
    Vehiculo,
)
from apps.mantenimiento.series import formatear, siguiente_numero
from apps.organizacion.models import Empresa, Sucursal

from .exceptions import VentaInvalida
from .models import (
    CERO,
    ComprobanteVenta,
    GuiaRemision,
    LineaGuia,
    LineaVenta,
    ModalidadTransporte,
    MotivoTraslado,
)
from .servicios import _texto, serie_sugerida

logger = logging.getLogger(__name__)

TRES = Decimal("0.001")
MAXIMO_VEHICULOS_SECUNDARIOS = 5


def enviado_antes(linea_ids: list[int]) -> dict[int, Decimal]:
    """Lo ya enviado de cada línea en guías que siguen vigentes."""
    filas = LineaGuia.objects.sin_ambito().filter(
        linea_venta_id__in=linea_ids, guia__estado=GuiaRemision.Estado.EMITIDO
    )
    enviado: dict[int, Decimal] = defaultdict(lambda: CERO)
    for f in filas:
        enviado[f.linea_venta_id] += f.cantidad
    return enviado


def con_algo_por_enviar(comprobantes: QuerySet) -> QuerySet:
    """Los comprobantes a los que todavía les queda alguna línea por enviar (en la base)."""
    cantidad = DecimalField(max_digits=14, decimal_places=3)
    enviado = (
        LineaGuia.objects.sin_ambito()
        .filter(linea_venta=OuterRef("pk"), guia__estado=GuiaRemision.Estado.EMITIDO)
        .values("linea_venta")
        .annotate(total=Sum("cantidad"))
        .values("total")
    )
    por_enviar = (
        LineaVenta.objects.sin_ambito()
        .filter(comprobante=OuterRef("pk"))
        .annotate(
            ya_enviado=Coalesce(
                Subquery(enviado, output_field=cantidad), Value(CERO, output_field=cantidad)
            )
        )
        .filter(cantidad__gt=F("ya_enviado"))
    )
    return comprobantes.filter(Exists(por_enviar))


def pendiente_de_enviar(comprobante: ComprobanteVenta) -> list[dict]:
    """Cada línea del comprobante con lo que todavía no viajó en una guía."""
    lineas = list(
        LineaVenta.objects.filter(comprobante=comprobante)
        .select_related("producto__unidad", "almacen")
        .order_by("orden")
    )
    enviado = enviado_antes([ln.pk for ln in lineas])
    return [
        {"linea": ln, "enviado": enviado[ln.pk], "pendiente": ln.cantidad - enviado[ln.pk]}
        for ln in lineas
    ]


def almacen_de_origen(lineas: list[LineaVenta]) -> Almacen | None:
    """El almacén del que salió lo que viaja, si todo salió de uno solo."""
    ids = {ln.almacen_id for ln in lineas}
    if len(ids) != 1 or None in ids:
        return None
    return lineas[0].almacen


def _tipo_guia(empresa: Empresa) -> TipoComprobante:
    tipo = (
        TipoComprobante.objects.sin_ambito()
        .filter(organizacion_id=empresa.organizacion_id, codigo="09")
        .first()
    )
    if tipo is None or tipo.estado != EstadoRegistro.ACTIVO or not tipo.aplica_ventas:
        raise VentaInvalida("La guía de remisión no está disponible en esta organización.")
    return tipo


# ---------------------------------------------------------------------------
# Serie
# ---------------------------------------------------------------------------
def series_de_guia(empresa: Empresa) -> list[SerieComprobante]:
    """Las series activas con que la empresa puede emitir guías de remisión."""
    return list(
        SerieComprobante.objects.sin_ambito()
        .filter(empresa=empresa, tipo_comprobante=_tipo_guia(empresa), estado=EstadoRegistro.ACTIVO)
        .order_by("serie")
    )


def elegir_serie_de_guia(
    empresa: Empresa, sucursal: Sucursal | None, elegida: int | None = None
) -> SerieComprobante:
    """La serie de la guía: la elegida (si es de la empresa) o la que corresponde sola.

    ``sucursal`` es la tienda de la venta (o la del almacén de origen en un traspaso).
    """
    series = series_de_guia(empresa)
    nombre = empresa.nombre_comercial or empresa.razon_social
    if not series:
        raise VentaInvalida(
            f"{nombre} no tiene una serie activa de guía de remisión: cree una (por ejemplo T001) "
            "en Mantenimiento → Series de comprobantes."
        )
    if elegida is not None:
        serie = next((s for s in series if s.pk == elegida), None)
        if serie is None:
            raise VentaInvalida("La serie elegida no sirve para una guía de esta empresa.")
        return serie
    sugerida = serie_sugerida(empresa, sucursal, series)
    if sugerida is None:
        raise VentaInvalida(f"{nombre} tiene varias series de guía de remisión: elija una.")
    return sugerida


def series_para_elegir(empresa: Empresa, sucursal: Sucursal | None) -> dict:
    """Las series posibles de la guía con su próximo número, y cuál corresponde sola."""
    series = series_de_guia(empresa)
    sugerida = serie_sugerida(empresa, sucursal, series)
    return {
        "series": [
            {
                "id": s.pk,
                "serie": s.serie,
                "nombre": s.nombre,
                "sucursal": s.sucursal_id,
                "proximo": formatear(s.serie, s.proximo_numero),
            }
            for s in series
        ],
        "serie_sugerida": sugerida.pk if sugerida else None,
    }


# ---------------------------------------------------------------------------
# Validaciones de lo que se elige
# ---------------------------------------------------------------------------
def _ubigeo(valor: str, que: str) -> str:
    codigo = (valor or "").strip()
    if codigo and not (
        codigo.isdigit() and len(codigo) == 6 and Ubigeo.objects.filter(codigo=codigo).exists()
    ):
        raise VentaInvalida(f"El ubigeo {que} no está en la lista del INEI.")
    return codigo


def _de_la_organizacion(objeto, empresa: Empresa, que: str):
    """Un registro de los catálogos: de la misma organización y activo."""
    if objeto is None:
        return None
    if objeto.organizacion_id != empresa.organizacion_id or objeto.estado != EstadoRegistro.ACTIVO:
        raise VentaInvalida(f"{que} no existe o está inactivo.")
    return objeto


def _peso(
    valor, mensaje: str = "El peso admite hasta 3 decimales y no puede ser negativo."
) -> Decimal:
    if not isinstance(valor, Decimal) or valor < 0 or valor != valor.quantize(TRES):
        raise VentaInvalida(mensaje)
    return valor


def _transporte(
    empresa: Empresa,
    *,
    modalidad: str,
    traslado_m1_l: bool,
    transportista: EmpresaTransporte | None,
    transportista_nombre: str,
    transportista_documento: str,
    conductor: Conductor | None,
    conductor_nombre: str,
    conductor_licencia: str,
    vehiculo: Vehiculo | None,
    placa: str,
    vehiculos_secundarios: list[Vehiculo],
) -> dict:
    """Los datos de quién lleva la mercadería, tal como se guardan en la guía."""
    datos = {
        "transportista": None,
        "transportista_nombre": "",
        "transportista_documento": "",
        "transportista_mtc": "",
        "transportista_certificado": "",
        "conductor": None,
        "conductor_nombre": "",
        "conductor_documento": "",
        "conductor_licencia": "",
        "vehiculo": None,
        "placa": "",
        "vehiculo_descripcion": "",
        "placas_secundarias": [],
    }
    if modalidad == ModalidadTransporte.PUBLICO:
        if transportista is not None:
            datos.update(
                transportista=transportista,
                transportista_nombre=transportista.nombre,
                transportista_documento=transportista.ruc,
                transportista_mtc=transportista.registro_mtc,
                transportista_certificado=transportista.certificado_inspeccion,
            )
        else:
            nombre = _texto(transportista_nombre, 250)
            documento = _texto(transportista_documento, 20)
            if len(nombre) < 3 or len(documento) < 8:
                raise VentaInvalida(
                    "Con transporte público elija al transportista (o indique su nombre y RUC)."
                )
            datos.update(transportista_nombre=nombre, transportista_documento=documento)
    else:
        # En el transporte privado lleva la propia empresa que emite la guía.
        datos.update(transportista_nombre=empresa.razon_social, transportista_documento=empresa.ruc)

    if conductor is not None:
        datos.update(
            conductor=conductor,
            conductor_nombre=conductor.nombre,
            conductor_documento=conductor.numero_documento,
            conductor_licencia=conductor.licencia,
        )
    else:
        datos.update(
            conductor_nombre=_texto(conductor_nombre, 150),
            conductor_licencia=_texto(conductor_licencia, 20).upper(),
        )
    if vehiculo is not None:
        datos.update(vehiculo=vehiculo, placa=vehiculo.placa, vehiculo_descripcion=str(vehiculo))
    else:
        datos.update(placa=_texto(placa, 10).upper())

    privado_con_datos = modalidad == ModalidadTransporte.PRIVADO and not traslado_m1_l
    if privado_con_datos and (len(datos["placa"]) < 5 or len(datos["conductor_nombre"]) < 3):
        raise VentaInvalida(
            "Con transporte privado elija el conductor y el vehículo (o indique la placa y el "
            "conductor), salvo que sea un vehículo de categoría M1 o L."
        )
    placas = []
    for secundario in vehiculos_secundarios:
        if secundario.placa == datos["placa"] or secundario.placa in placas:
            raise VentaInvalida("Un vehículo secundario se repite o es el principal.")
        placas.append(secundario.placa)
    datos["placas_secundarias"] = placas
    return datos


MOTIVOS_DE_TRASPASO = (MotivoTraslado.ENTRE_ESTABLECIMIENTOS, MotivoTraslado.OTROS)


def _cabecera(
    *,
    motivo: str,
    motivos_validos,
    modalidad: str,
    fecha_traslado: date,
    punto_partida: str,
    punto_llegada: str,
    ubigeo_partida: str,
    ubigeo_llegada: str,
    bultos: int,
    peso_kg: Decimal | None,
    vehiculos_secundarios: list | None,
) -> dict:
    """Valida lo que toda guía lleva (motivo, fechas, lugares, carga) y lo devuelve ya limpio."""
    if motivo not in motivos_validos:
        raise VentaInvalida("El motivo del traslado no es válido.")
    if modalidad not in ModalidadTransporte.values:
        raise VentaInvalida("La modalidad de transporte no es válida.")
    hoy = timezone.localdate()
    if not isinstance(fecha_traslado, date) or fecha_traslado < hoy:
        raise VentaInvalida("La fecha de traslado no puede ser anterior a hoy.")
    partida, llegada = _texto(punto_partida, 250), _texto(punto_llegada, 250)
    if len(partida) < 5 or len(llegada) < 5:
        raise VentaInvalida("Indique desde dónde y hasta dónde se traslada.")
    ubigeo_de_partida = _ubigeo(ubigeo_partida, "de partida")
    ubigeo_de_llegada = _ubigeo(ubigeo_llegada, "de llegada")
    if not isinstance(bultos, int) or not (1 <= bultos <= 100_000):
        raise VentaInvalida("Los bultos son un número entero mayor que cero.")
    if peso_kg is not None:
        _peso(peso_kg)
    secundarios = list(vehiculos_secundarios or [])
    if len(secundarios) > MAXIMO_VEHICULOS_SECUNDARIOS:
        raise VentaInvalida(f"Indique hasta {MAXIMO_VEHICULOS_SECUNDARIOS} vehículos secundarios.")
    return {
        "hoy": hoy,
        "partida": partida,
        "llegada": llegada,
        "ubigeo_partida": ubigeo_de_partida,
        "ubigeo_llegada": ubigeo_de_llegada,
        "secundarios": secundarios,
    }


def _emitir(
    empresa: Empresa,
    sucursal: Sucursal | None,
    *,
    serie_id: int | None,
    origen: dict,
    quien: dict,
    cabecera: dict,
    fecha_traslado: date,
    motivo: str,
    modalidad: str,
    almacen_origen: Almacen | None,
    traslado_m1_l: bool,
    peso_total: Decimal,
    bultos: int,
    observacion: str,
    usuario_nombre: str,
    transporte: dict,
) -> GuiaRemision:
    """Numera y guarda la cabecera; ``origen`` dice de qué comprobante o traspaso sale la guía."""
    tipo = _tipo_guia(empresa)
    serie_obj = elegir_serie_de_guia(empresa, sucursal, serie_id)
    serie, numero = siguiente_numero(empresa, serie_obj.pk)
    return GuiaRemision.objects.create(
        empresa=empresa,
        tipo_comprobante=tipo,
        serie_comprobante=serie_obj,
        serie=serie,
        numero=numero,
        fecha_emision=cabecera["hoy"],
        fecha_traslado=fecha_traslado,
        motivo=motivo,
        modalidad=modalidad,
        punto_partida=cabecera["partida"],
        ubigeo_partida=cabecera["ubigeo_partida"],
        punto_llegada=cabecera["llegada"],
        ubigeo_llegada=cabecera["ubigeo_llegada"],
        almacen_origen=almacen_origen,
        traslado_m1_l=bool(traslado_m1_l),
        peso_kg=peso_total,
        bultos=bultos,
        observacion=_texto(observacion, 250),
        emitida_por_nombre=_texto(usuario_nombre, 150),
        **origen,
        **quien,
        **transporte,
    )


@transaction.atomic
def crear_guia(
    comprobante: ComprobanteVenta,
    *,
    lineas: list[tuple],
    punto_partida: str,
    punto_llegada: str,
    fecha_traslado: date,
    modalidad: str,
    motivo: str = MotivoTraslado.VENTA,
    serie_id: int | None = None,
    destinatario: Cliente | None = None,
    ubigeo_partida: str = "",
    ubigeo_llegada: str = "",
    almacen_origen: Almacen | None = None,
    traslado_m1_l: bool = False,
    transportista: EmpresaTransporte | None = None,
    transportista_nombre: str = "",
    transportista_documento: str = "",
    conductor: Conductor | None = None,
    conductor_nombre: str = "",
    conductor_licencia: str = "",
    vehiculo: Vehiculo | None = None,
    placa: str = "",
    vehiculos_secundarios: list[Vehiculo] | None = None,
    peso_kg: Decimal | None = None,
    bultos: int = 1,
    observacion: str = "",
    usuario_nombre: str = "",
) -> GuiaRemision:
    """Emite la guía de remisión de lo que viaja de un comprobante.

    ``lineas`` son ``(línea de la venta, cantidad)`` o ``(línea, cantidad, peso en kg)``. Sin
    ``peso_kg`` el peso total es la suma de los pesos de las líneas.
    """
    periodos.exigir_empresa(comprobante.empresa)
    comprobante = (
        ComprobanteVenta.objects.select_for_update(of=("self",))  # solo se bloquea el comprobante
        .select_related("venta__cliente", "empresa")
        .get(pk=comprobante.pk)
    )
    empresa = comprobante.empresa
    if comprobante.estado != ComprobanteVenta.Estado.EMITIDO:
        raise VentaInvalida("El comprobante está anulado: no admite guías de remisión.")
    cabecera = _cabecera(
        motivo=motivo,
        motivos_validos=MotivoTraslado.values,
        modalidad=modalidad,
        fecha_traslado=fecha_traslado,
        punto_partida=punto_partida,
        punto_llegada=punto_llegada,
        ubigeo_partida=ubigeo_partida,
        ubigeo_llegada=ubigeo_llegada,
        bultos=bultos,
        peso_kg=peso_kg,
        vehiculos_secundarios=vehiculos_secundarios,
    )
    if not lineas:
        raise VentaInvalida("Elija qué se envía.")

    pendientes = {p["linea"].pk: p for p in pendiente_de_enviar(comprobante)}
    vistas: set[int] = set()
    enviadas: list[tuple[LineaVenta, Decimal, Decimal]] = []
    for item in lineas:
        linea, cantidad, *resto = item
        peso_linea = _peso(
            resto[0] if resto else CERO,
            f"{linea.descripcion}: el peso admite hasta 3 decimales y no puede ser negativo.",
        )
        p = pendientes.get(linea.pk)
        if p is None:
            raise VentaInvalida("Una línea no pertenece al comprobante.")
        if linea.pk in vistas:
            raise VentaInvalida("Una línea se repite: indique la cantidad total en una sola.")
        vistas.add(linea.pk)
        if (
            not isinstance(cantidad, Decimal)
            or cantidad <= 0
            or cantidad != cantidad.quantize(TRES)
        ):
            raise VentaInvalida(f"{linea.descripcion}: la cantidad debe ser mayor que cero.")
        if cantidad > p["pendiente"]:
            raise VentaInvalida(
                f"{linea.descripcion}: solo falta enviar {p['pendiente']:g} "
                f"(ya viajaron {p['enviado']:g})."
            )
        enviadas.append((p["linea"], cantidad, peso_linea))
    peso_total = peso_kg if peso_kg is not None else sum((e[2] for e in enviadas), CERO)

    # Lo que se elige de las listas debe ser de la organización y estar activo.
    transportista = _de_la_organizacion(transportista, empresa, "La empresa de transporte")
    conductor = _de_la_organizacion(conductor, empresa, "El conductor")
    vehiculo = _de_la_organizacion(vehiculo, empresa, "El vehículo")
    secundarios = [
        _de_la_organizacion(v, empresa, "El vehículo secundario") for v in cabecera["secundarios"]
    ]
    destinatario = _de_la_organizacion(destinatario, empresa, "El destinatario")
    if almacen_origen is not None and almacen_origen.empresa_id != comprobante.empresa_id:
        raise VentaInvalida("El almacén de origen no es de la empresa que emite la guía.")
    if almacen_origen is None:
        almacen_origen = almacen_de_origen([e[0] for e in enviadas])
    transporte = _transporte(
        empresa,
        modalidad=modalidad,
        traslado_m1_l=traslado_m1_l,
        transportista=transportista,
        transportista_nombre=transportista_nombre,
        transportista_documento=transportista_documento,
        conductor=conductor,
        conductor_nombre=conductor_nombre,
        conductor_licencia=conductor_licencia,
        vehiculo=vehiculo,
        placa=placa,
        vehiculos_secundarios=secundarios,
    )

    venta = comprobante.venta
    if destinatario is not None:
        quien = {
            "destinatario": destinatario,
            "destinatario_nombre": destinatario.nombre,
            "destinatario_tipo_documento": destinatario.tipo_documento,
            "destinatario_documento": destinatario.numero_documento,
        }
    else:
        quien = {
            "destinatario": venta.cliente,
            "destinatario_nombre": venta.cliente_nombre,
            "destinatario_tipo_documento": venta.cliente_tipo_documento,
            "destinatario_documento": venta.cliente_documento,
        }
    guia = _emitir(
        empresa,
        venta.sucursal,
        serie_id=serie_id,
        origen={"comprobante": comprobante},
        quien=quien,
        cabecera=cabecera,
        fecha_traslado=fecha_traslado,
        motivo=motivo,
        modalidad=modalidad,
        almacen_origen=almacen_origen,
        traslado_m1_l=traslado_m1_l,
        peso_total=peso_total,
        bultos=bultos,
        observacion=observacion,
        usuario_nombre=usuario_nombre,
        transporte=transporte,
    )
    LineaGuia.objects.bulk_create(
        [
            LineaGuia(
                empresa=empresa,
                guia=guia,
                linea_venta=linea,
                orden=orden,
                descripcion=linea.descripcion,
                unidad=linea.producto.unidad.abreviatura,
                cantidad=cantidad,
                peso_kg=peso_linea,
            )
            for orden, (linea, cantidad, peso_linea) in enumerate(enviadas)
        ]
    )
    registrar(
        "ventas.guia_emitida",
        recurso_tipo="guia_remision",
        recurso_id=guia.pk,
        empresa_id=empresa.pk,
        resumen=f"Guía {guia.numero_completo} de {comprobante.numero_completo}",
        detalle={"modalidad": modalidad, "bultos": bultos, "lineas": len(enviadas)},
    )
    return guia


# ---------------------------------------------------------------------------
# Guía de un traspaso entre almacenes
# ---------------------------------------------------------------------------
def mitades_de_traspaso(
    movimiento: MovimientoInventario,
) -> tuple[MovimientoInventario, MovimientoInventario]:
    """``(salida, entrada)`` del traspaso al que pertenece cualquiera de sus dos movimientos."""
    entre_empresas = movimiento.origen == OrigenMovimiento.TRASLADO_EMPRESAS
    if (
        movimiento.origen not in (OrigenMovimiento.TRASPASO, OrigenMovimiento.TRASLADO_EMPRESAS)
        or movimiento.traspaso_id is None
    ):
        raise VentaInvalida("El movimiento no es un traspaso entre almacenes.")
    mitades_de = MovimientoInventario.objects.select_related("almacen__sucursal", "empresa").filter(
        traspaso_id=movimiento.traspaso_id, origen=movimiento.origen
    )
    if not entre_empresas:  # en un traslado entre empresas las dos mitades son de empresas distintas
        mitades_de = mitades_de.filter(empresa_id=movimiento.empresa_id)
    mitades = {m.tipo: m for m in mitades_de}
    if set(mitades) != {TipoMovimiento.SALIDA, TipoMovimiento.ENTRADA}:
        raise VentaInvalida("No se encontraron las dos mitades del traspaso.")
    return mitades[TipoMovimiento.SALIDA], mitades[TipoMovimiento.ENTRADA]


def guia_vigente_del_traspaso(salida: MovimientoInventario) -> GuiaRemision | None:
    """La guía vigente de ese traspaso, si ya se emitió una."""
    return GuiaRemision.objects.filter(
        movimiento_salida=salida, estado=GuiaRemision.Estado.EMITIDO
    ).first()


def traspaso_anulado(salida: MovimientoInventario, entrada: MovimientoInventario) -> bool:
    return MovimientoInventario.Estado.ANULADO in (salida.estado, entrada.estado)


def lineas_del_traspaso(salida: MovimientoInventario) -> list[LineaMovimiento]:
    """Lo que viaja en un traspaso: cada línea de la salida con su producto y sus series."""
    return list(
        salida.lineas.select_related("producto__unidad")
        .prefetch_related("series_salida")
        .order_by("orden", "id")
    )


def series_de_linea(linea: LineaMovimiento) -> list[str]:
    """Los números de serie (o IMEI) que viajan en una línea, en orden."""
    return [s.numero for s in sorted(linea.series_salida.all(), key=lambda s: s.pk)]


def _descripcion_de_traslado(linea: LineaMovimiento) -> str:
    """El nombre del producto y, si lleva series o IMEI, cuáles viajan (cabe en 250 letras)."""
    nombre = linea.producto.nombre
    series = series_de_linea(linea)
    if not series:
        return nombre[:250]
    texto = f"{nombre} (Series: {', '.join(series)})"
    return texto if len(texto) <= 250 else f"{texto[:249]}…"


@transaction.atomic
def crear_guia_de_traslado(
    movimiento: MovimientoInventario,
    *,
    fecha_traslado: date,
    modalidad: str,
    punto_partida: str,
    punto_llegada: str,
    motivo: str = MotivoTraslado.ENTRE_ESTABLECIMIENTOS,
    serie_id: int | None = None,
    ubigeo_partida: str = "",
    ubigeo_llegada: str = "",
    traslado_m1_l: bool = False,
    transportista: EmpresaTransporte | None = None,
    transportista_nombre: str = "",
    transportista_documento: str = "",
    conductor: Conductor | None = None,
    conductor_nombre: str = "",
    conductor_licencia: str = "",
    vehiculo: Vehiculo | None = None,
    placa: str = "",
    vehiculos_secundarios: list[Vehiculo] | None = None,
    pesos: dict[int, Decimal] | None = None,
    peso_kg: Decimal | None = None,
    bultos: int = 1,
    observacion: str = "",
    usuario_nombre: str = "",
) -> GuiaRemision:
    """Emite la guía de remisión de un traspaso entre almacenes de la misma empresa.

    ``movimiento`` es cualquiera de las dos mitades del traspaso. La guía lleva todo lo traspasado,
    sale del almacén de origen y va a nombre de la propia empresa. NO mueve stock: el traspaso ya lo
    movió. Hay una sola guía vigente por traspaso. ``pesos`` es ``{id de la línea: kg}``.
    """
    salida, entrada = mitades_de_traspaso(movimiento)
    # La guía la emite quien entrega la mercadería (en un traslado entre empresas, la de la salida).
    empresa = salida.empresa
    periodos.exigir_empresa(empresa)
    # Se bloquea siempre la salida: dos personas no emiten a la vez la guía del mismo traspaso.
    salida = (
        MovimientoInventario.objects.select_for_update(of=("self",))
        .select_related("almacen__sucursal", "empresa")
        .get(pk=salida.pk)
    )
    entrada = MovimientoInventario.objects.get(pk=entrada.pk)
    if traspaso_anulado(salida, entrada):
        raise VentaInvalida("El traspaso está anulado: no admite guías de remisión.")
    existente = guia_vigente_del_traspaso(salida)
    if existente is not None:
        raise VentaInvalida(
            f"El traspaso ya tiene la guía {existente.numero_completo}: anúlela para emitir otra."
        )
    cabecera = _cabecera(
        motivo=motivo,
        motivos_validos=MOTIVOS_DE_TRASPASO,
        modalidad=modalidad,
        fecha_traslado=fecha_traslado,
        punto_partida=punto_partida,
        punto_llegada=punto_llegada,
        ubigeo_partida=ubigeo_partida,
        ubigeo_llegada=ubigeo_llegada,
        bultos=bultos,
        peso_kg=peso_kg,
        vehiculos_secundarios=vehiculos_secundarios,
    )

    lineas = lineas_del_traspaso(salida)
    if not lineas:
        raise VentaInvalida("El traspaso no tiene productos.")
    pesos = dict(pesos or {})
    if set(pesos) - {ln.pk for ln in lineas}:
        raise VentaInvalida("Hay pesos de productos que no son de este traspaso.")
    peso_de = {
        ln.pk: _peso(
            pesos.get(ln.pk, CERO),
            f"{ln.producto.nombre}: el peso admite hasta 3 decimales y no puede ser negativo.",
        )
        for ln in lineas
    }
    peso_total = peso_kg if peso_kg is not None else sum(peso_de.values(), CERO)

    transportista = _de_la_organizacion(transportista, empresa, "La empresa de transporte")
    conductor = _de_la_organizacion(conductor, empresa, "El conductor")
    vehiculo = _de_la_organizacion(vehiculo, empresa, "El vehículo")
    secundarios = [
        _de_la_organizacion(v, empresa, "El vehículo secundario") for v in cabecera["secundarios"]
    ]
    transporte = _transporte(
        empresa,
        modalidad=modalidad,
        traslado_m1_l=traslado_m1_l,
        transportista=transportista,
        transportista_nombre=transportista_nombre,
        transportista_documento=transportista_documento,
        conductor=conductor,
        conductor_nombre=conductor_nombre,
        conductor_licencia=conductor_licencia,
        vehiculo=vehiculo,
        placa=placa,
        vehiculos_secundarios=secundarios,
    )
    # Entre establecimientos de la misma empresa la destinataria es ella misma; en un traslado entre
    # empresas es la que recibe.
    destinataria = entrada.empresa
    quien = {
        "destinatario": None,
        "destinatario_nombre": destinataria.razon_social,
        "destinatario_tipo_documento": "RUC",
        "destinatario_documento": destinataria.ruc,
    }
    guia = _emitir(
        empresa,
        salida.almacen.sucursal,
        serie_id=serie_id,
        origen={"movimiento_salida": salida},
        quien=quien,
        cabecera=cabecera,
        fecha_traslado=fecha_traslado,
        motivo=motivo,
        modalidad=modalidad,
        almacen_origen=salida.almacen,
        traslado_m1_l=traslado_m1_l,
        peso_total=peso_total,
        bultos=bultos,
        observacion=observacion,
        usuario_nombre=usuario_nombre,
        transporte=transporte,
    )
    LineaGuia.objects.bulk_create(
        [
            LineaGuia(
                empresa=empresa,
                guia=guia,
                producto=ln.producto,
                orden=orden,
                descripcion=_descripcion_de_traslado(ln),
                unidad=ln.producto.unidad.abreviatura,
                cantidad=ln.cantidad,
                peso_kg=peso_de[ln.pk],
            )
            for orden, ln in enumerate(lineas)
        ]
    )
    registrar(
        "ventas.guia_emitida",
        recurso_tipo="guia_remision",
        recurso_id=guia.pk,
        empresa_id=empresa.pk,
        resumen=f"Guía {guia.numero_completo} del traspaso N° {salida.numero:06d}",
        detalle={"modalidad": modalidad, "bultos": bultos, "lineas": len(lineas)},
    )
    return guia


@transaction.atomic
def anular_guia(guia: GuiaRemision, *, motivo: str) -> GuiaRemision:
    """Anula la guía: lo que enviaba vuelve a quedar pendiente de enviar."""
    periodos.exigir_empresa(guia.empresa)
    guia.anular(motivo=motivo)
    registrar(
        "ventas.guia_anulada",
        recurso_tipo="guia_remision",
        recurso_id=guia.pk,
        empresa_id=guia.empresa_id,
        resumen=f"Guía {guia.numero_completo} anulada",
        detalle={"motivo": (motivo or "").strip()[:200]},
    )
    return guia
