"""Toma de inventario físico: foto del stock, conteo, reconteo, cierre y ajuste del Kardex.

Ciclo::

    BORRADOR → ABIERTA → EN_CONTEO ⇄ EN_RECONTEO → CERRADA → APROBADA     (ANULADA desde cualquiera)

* Al ABRIR se congela, producto por producto, el stock y el costo promedio del almacén. Todo lo
  contado se compara contra esa foto. El bloqueo del correlativo de la empresa garantiza que la
  foto sea consistente: ningún movimiento de inventario se cuela mientras se toma.
* ``cantidad_contada`` nula significa «todavía no se cuenta»; 0 significa «se contó y no hay».
* Cada conteo queda en ``ConteoToma`` (1.º conteo, reconteos, correcciones); nunca se borra.
* La diferencia se valoriza al COSTO promedio congelado, no al precio de venta.
* Al APROBAR se genera el ajuste con los movimientos normales de inventario (origen AJUSTE,
  operación 28 de la tabla 12 de SUNAT). Se ajusta la diferencia REAL: contado menos lo que el
  sistema debía tener al momento del conteo (stock al corte más lo que se movió entre el corte y
  el conteo). Así las ventas hechas mientras se contaba no se vuelven faltantes.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Abs
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.core.exceptions import MotivoObligatorio
from apps.core.tenant import obtener_contexto
from apps.mantenimiento.models import (
    Almacen,
    Categoria,
    Correlativo,
    EstadoRegistro,
    Personal,
    Producto,
    TipoProducto,
)
from apps.organizacion.models import Empresa

from . import numeracion, periodos
from .catalogos import AJUSTE_INVENTARIO
from .costeo import a_dos
from .exceptions import (
    AjusteImposible,
    ConteoInvalido,
    ConteoRequiereConfirmacion,
    TomaEstadoInvalido,
    TomaIncompleta,
    TomaInvalida,
    TomaVigenteExistente,
)
from .models import (
    AlcanceToma,
    ConteoToma,
    DetalleToma,
    EstadoFisico,
    EstadoToma,
    LineaMovimiento,
    MovimientoInventario,
    OrigenMovimiento,
    ResultadoToma,
    SaldoStock,
    TipoMovimiento,
    TomaInventario,
    TurnoToma,
)
from .movimientos import MAX_LINEAS, LineaNueva, anular_movimiento, registrar_movimiento

logger = logging.getLogger(__name__)

MAX_CANTIDAD = Decimal("99999999999.999")  # cabe en max_digits=14, decimal_places=3
TRES = Decimal("0.001")
DOS = Decimal("0.01")
LOTE_DETALLES = 500
ESTADOS_DE_CONTEO = (EstadoToma.ABIERTA, EstadoToma.EN_CONTEO, EstadoToma.EN_RECONTEO)

# Unidades que admiten decimales (se miden, no se cuentan por pieza). El resto exige enteros.
_FRACCIONABLES_SUNAT = frozenset(
    {"MTR", "KGM", "LTR", "GRM", "CMT", "MMT", "GLL", "LBR", "MTK", "MTQ", "TNE", "ONZ", "YRD"}
)
_FRACCIONABLES_ABREV = frozenset(
    {"M", "ML", "MT", "MTS", "KG", "KGS", "GR", "L", "LT", "LTS", "GAL", "CM", "MM", "M2", "M3"}
)
# Si no se puede valorizar (costo 0), un conteo en 0 pide confirmación desde este stock.
_STOCK_CERO_SIN_COSTO = Decimal("10")


def unidad_fraccionable(producto: Producto) -> bool:
    unidad = producto.unidad
    return (
        unidad.codigo_sunat.upper() in _FRACCIONABLES_SUNAT
        or unidad.abreviatura.upper() in _FRACCIONABLES_ABREV
    )


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"inventario:toma:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _bloquear(toma_id: int) -> TomaInventario:
    """La toma con su fila bloqueada. Debe llamarse dentro de una transacción."""
    toma = TomaInventario.objects.select_for_update().filter(pk=toma_id).first()
    if toma is None:
        raise TomaInvalida("La toma de inventario no existe.")
    periodos.exigir_empresa(toma.empresa)
    return toma


def _exigir_estado(toma: TomaInventario, permitidos, accion: str) -> None:
    if toma.estado not in permitidos:
        raise TomaEstadoInvalido(
            f"No se puede {accion}: la toma está «{toma.get_estado_display()}»."
        )


def _auditar(toma: TomaInventario, accion: str, resumen: str, detalle: dict | None = None) -> None:
    registrar(
        f"inventario.toma_{accion}",
        recurso_tipo="toma_inventario",
        recurso_id=toma.pk,
        empresa_id=toma.empresa_id,
        resumen=resumen,
        detalle={"numero": toma.numero, "almacen": toma.almacen_id, **(detalle or {})},
    )
    logger.info(
        f"toma_inventario_{accion}",
        extra={"empresa_id": toma.empresa_id, "toma_id": toma.pk, "almacen_id": toma.almacen_id},
    )


def _cantidad_valida(valor, producto: Producto) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise ConteoInvalido("Indique una cantidad válida.")
    if valor < 0:
        raise ConteoInvalido("La cantidad contada no puede ser negativa.")
    if valor != valor.quantize(TRES):
        raise ConteoInvalido("La cantidad tiene demasiados decimales (máximo 3).")
    if valor > MAX_CANTIDAD:
        raise ConteoInvalido("La cantidad es demasiado grande.")
    if (producto.lleva_serie or not unidad_fraccionable(producto)) and valor != valor.to_integral():
        unidad = producto.unidad.abreviatura
        raise ConteoInvalido(
            f"{producto.nombre}: la unidad «{unidad}» se cuenta en números enteros."
        )
    return valor


def _importe(diferencia: Decimal, costo_unitario: Decimal) -> Decimal:
    return (diferencia * costo_unitario).quantize(DOS, rounding=ROUND_HALF_UP)


def _resultado(diferencia: Decimal) -> str:
    if diferencia < 0:
        return ResultadoToma.FALTANTE
    if diferencia > 0:
        return ResultadoToma.SOBRANTE
    return ResultadoToma.CONFORME


def diferencia_relevante(
    toma: TomaInventario, stock: Decimal, costo_unitario: Decimal, diferencia: Decimal
) -> bool:
    """Pasa el umbral de monto (en soles, al costo) o el de porcentaje sobre el stock."""
    if diferencia == 0:
        return False
    if abs(_importe(diferencia, costo_unitario)) > toma.umbral_monto:
        return True
    return stock > 0 and abs(diferencia) / stock * 100 > toma.umbral_porcentaje


def _cero_requiere_confirmacion(toma: TomaInventario, detalle: DetalleToma) -> bool:
    valor = _importe(detalle.stock_sistema, detalle.costo_unitario)
    if detalle.costo_unitario > 0:
        return valor >= toma.umbral_monto
    return detalle.stock_sistema >= _STOCK_CERO_SIN_COSTO


def con_diferencia_importante(toma: TomaInventario):
    """Productos contados cuya diferencia pasa el umbral de monto o el de porcentaje.

    Es la misma regla de ``diferencia_relevante``, hecha en la base de datos: sirve para contar
    y listar a los que necesitan nota sin recorrerlos uno por uno.
    """
    exceso_porcentual = ExpressionWrapper(
        Abs(F("diferencia")) * 100 - F("stock_sistema") * Value(toma.umbral_porcentaje),
        output_field=DecimalField(max_digits=30, decimal_places=6),
    )
    return (
        DetalleToma.objects.filter(toma=toma, cantidad_contada__isnull=False)
        .exclude(diferencia=0)
        .annotate(exceso_porcentual=exceso_porcentual)
        .filter(
            Q(importe_diferencia__gt=toma.umbral_monto)
            | Q(importe_diferencia__lt=-toma.umbral_monto)
            | Q(exceso_porcentual__gt=0)
        )
    )


def sin_nota(toma: TomaInventario):
    """Productos con una diferencia importante a los que todavía les falta la nota."""
    return con_diferencia_importante(toma).filter(nota="")


# ---------------------------------------------------------------------------
# Crear y abrir
# ---------------------------------------------------------------------------
@transaction.atomic
def crear_toma(
    *,
    empresa: Empresa,
    almacen_id: int,
    alcance: str = AlcanceToma.TODO,
    categorias_ids=(),
    excluidos_ids=(),
    conteo_ciego: bool = True,
    responsable_id: int | None = None,
    observacion: str = "",
    umbral_monto: Decimal = Decimal("500"),
    umbral_porcentaje: Decimal = Decimal("10"),
) -> TomaInventario:
    """Crea la toma en BORRADOR: elige almacén y alcance. Todavía no congela nada."""
    periodos.exigir_empresa(empresa)
    almacen = Almacen.objects.filter(
        pk=almacen_id, empresa=empresa, estado=EstadoRegistro.ACTIVO
    ).first()
    if almacen is None:
        raise TomaInvalida("Elija un almacén activo de la empresa.")
    if alcance not in AlcanceToma.values:
        raise TomaInvalida("El alcance no es válido.")

    categorias_ids, excluidos_ids = set(categorias_ids), set(excluidos_ids)
    if alcance == AlcanceToma.CATEGORIAS and not categorias_ids:
        raise TomaInvalida("Elija al menos una categoría para contar.")
    if alcance == AlcanceToma.TODO and categorias_ids:
        raise TomaInvalida("Las categorías solo se eligen cuando el alcance es «algunas».")
    categorias = list(Categoria.objects.filter(pk__in=categorias_ids))
    if len(categorias) != len(categorias_ids):
        raise TomaInvalida("Hay categorías que no existen en la organización.")
    excluidos = list(Producto.objects.filter(pk__in=excluidos_ids, tipo=TipoProducto.BIEN))
    if len(excluidos) != len(excluidos_ids):
        raise TomaInvalida("Hay productos excluidos que no existen en el catálogo.")
    responsable = None
    if responsable_id is not None:
        responsable = Personal.objects.filter(pk=responsable_id, empresa=empresa).first()
        if responsable is None:
            raise TomaInvalida("El responsable debe ser personal de la misma empresa.")

    # Se numera con la fila del correlativo bloqueada (sin saltos ni repeticiones).
    numero = _siguiente_numero(empresa)
    try:
        with transaction.atomic():  # punto de guardado: el choque de la restricción no rompe todo
            toma = TomaInventario.objects.create(
                empresa=empresa,
                almacen=almacen,
                numero=numero,
                alcance=alcance,
                conteo_ciego=conteo_ciego,
                responsable=responsable,
                observacion=" ".join((observacion or "").split()),
                umbral_monto=umbral_monto,
                umbral_porcentaje=umbral_porcentaje,
            )
    except IntegrityError:
        raise TomaVigenteExistente() from None
    toma.categorias.set(categorias)
    toma.productos_excluidos.set(excluidos)
    _auditar(
        toma,
        "creada",
        f"Toma de inventario N° {toma.numero:06d} creada en {almacen.nombre}",
        {"alcance": alcance, "conteo_ciego": conteo_ciego},
    )
    return toma


@transaction.atomic
def abrir_toma(toma_id: int) -> TomaInventario:
    """Congela el stock y el costo promedio de cada producto del alcance y abre el conteo."""
    toma = _bloquear(toma_id)
    _exigir_estado(toma, (EstadoToma.BORRADOR,), "abrir")
    # Cerrojo por empresa: ningún movimiento de inventario se registra mientras se toma la foto.
    numeracion.bloquear(toma.empresa)

    saldos = SaldoStock.objects.filter(
        empresa=toma.empresa,
        almacen=toma.almacen,
        cantidad__gt=0,
        producto__tipo=TipoProducto.BIEN,
        producto__controla_stock=True,
    )
    if toma.alcance == AlcanceToma.CATEGORIAS:
        saldos = saldos.filter(producto__categoria__in=toma.categorias.values("pk"))
    excluidos = list(toma.productos_excluidos.values_list("pk", flat=True))
    if excluidos:
        saldos = saldos.exclude(producto_id__in=excluidos)
    fotos = list(
        saldos.order_by("producto__categoria__nombre", "producto__nombre", "producto_id")
        .values_list("producto_id", "cantidad", "costo_unitario")
        .iterator(chunk_size=2000)
    )
    if not fotos:
        motivo = "No hay productos con stock en ese alcance: no hay nada que contar."
        if excluidos:
            motivo += (
                f" Se dejaron {len(excluidos)} producto(s) fuera de la toma; si era un error, "
                "anule esta toma y cree otra sin excluirlos."
            )
        raise TomaInvalida(motivo)

    DetalleToma.objects.bulk_create(
        [
            DetalleToma(
                empresa=toma.empresa,
                toma=toma,
                producto_id=producto_id,
                stock_sistema=cantidad,
                costo_unitario=costo,
            )
            for producto_id, cantidad, costo in fotos
        ],
        batch_size=LOTE_DETALLES,
    )
    ahora = timezone.now()
    toma.estado = EstadoToma.ABIERTA
    toma.fecha_corte = ahora
    toma.abierta_en = ahora
    toma.save(update_fields=["estado", "fecha_corte", "abierta_en"])
    _auditar(
        toma,
        "abierta",
        f"Toma N° {toma.numero:06d} abierta: {len(fotos)} productos congelados",
        {"productos": len(fotos)},
    )
    return toma


# ---------------------------------------------------------------------------
# Turnos
# ---------------------------------------------------------------------------
@transaction.atomic
def crear_turno(
    *, toma_id: int, fecha: date, turno: str, hora_inicio: time, equipo: str = ""
) -> TurnoToma:
    toma = _bloquear(toma_id)
    _exigir_estado(toma, ESTADOS_DE_CONTEO, "registrar un turno")
    if turno not in TurnoToma.Turno.values:
        raise TomaInvalida("El turno no es válido.")
    return TurnoToma.objects.create(
        empresa=toma.empresa,
        toma=toma,
        fecha=fecha,
        turno=turno,
        hora_inicio=hora_inicio,
        equipo=" ".join((equipo or "").split()),
    )


@transaction.atomic
def finalizar_turno(*, toma_id: int, turno_id: int, hora_fin: time) -> TurnoToma:
    toma = _bloquear(toma_id)
    turno = TurnoToma.objects.select_for_update().filter(pk=turno_id, toma=toma).first()
    if turno is None:
        raise TomaInvalida("El turno no pertenece a esta toma.")
    if turno.hora_fin is not None:
        raise TomaInvalida("El turno ya está finalizado.")
    if hora_fin < turno.hora_inicio:
        raise TomaInvalida("La hora de fin no puede ser anterior a la de inicio.")
    turno.hora_fin = hora_fin
    turno.save(update_fields=["hora_fin"])
    return turno


# ---------------------------------------------------------------------------
# Conteo
# ---------------------------------------------------------------------------
def _poner_conteo(
    toma: TomaInventario,
    detalle: DetalleToma,
    cantidad: Decimal,
    numero: int,
    *,
    nota: str,
    estado_fisico: str,
    esperado: Decimal | None = None,
    instante: datetime | None = None,
) -> None:
    """Deja en el detalle el resultado de un conteo (diferencia al costo, marca de reconteo…).

    ``esperado`` es lo que el sistema debía tener al contar; por omisión, el stock al corte. Un
    conteo importado de días atrás lo pasa ya corregido por lo que se movió desde entonces.
    No guarda: lo hace quien llama (uno a uno, o en lote).
    """
    esperado = detalle.stock_sistema if esperado is None else esperado
    diferencia = cantidad - esperado
    contexto = obtener_contexto()
    detalle.cantidad_contada = cantidad
    detalle.diferencia = diferencia
    detalle.importe_diferencia = _importe(diferencia, detalle.costo_unitario)
    detalle.resultado = _resultado(diferencia)
    detalle.estado_fisico = estado_fisico
    if nota:
        detalle.nota = nota
    detalle.numero_conteos = numero
    # Solo el primer conteo decide si hace falta recontar; el reconteo lo resuelve.
    detalle.requiere_reconteo = numero == 1 and diferencia_relevante(
        toma, detalle.stock_sistema, detalle.costo_unitario, diferencia
    )
    detalle.contado_por_id = contexto.usuario_id if contexto else None
    detalle.contado_en = instante or timezone.now()


@transaction.atomic
def registrar_conteo(
    *,
    toma_id: int,
    producto_id: int,
    cantidad: Decimal,
    estado_fisico: str = EstadoFisico.BUENO,
    nota: str = "",
    turno_id: int | None = None,
    confirmar_cero: bool = False,
) -> DetalleToma:
    """Registra un conteo (el primero, un reconteo o una corrección) de un producto de la toma.

    En conteo se acepta cualquier producto; en reconteo, solo los que quedaron por recontar.
    El primer conteo con una diferencia relevante marca el producto para reconteo.
    """
    toma = _bloquear(toma_id)  # serializa los conteos de una misma toma
    _exigir_estado(toma, ESTADOS_DE_CONTEO, "registrar conteos")
    detalle = (
        DetalleToma.objects.select_related("producto__unidad")
        .filter(toma=toma, producto_id=producto_id)
        .first()
    )
    if detalle is None:
        raise ConteoInvalido("Ese producto no está en esta toma.")
    if toma.estado == EstadoToma.EN_RECONTEO and not detalle.requiere_reconteo:
        raise ConteoInvalido("Ese producto no está en la lista de reconteo.")
    cantidad = _cantidad_valida(cantidad, detalle.producto)
    if estado_fisico not in EstadoFisico.values:
        raise ConteoInvalido("El estado físico no es válido.")
    nota = " ".join((nota or "").split())
    if len(nota) > 250:
        raise ConteoInvalido("La nota admite hasta 250 caracteres.")
    turno = None
    if turno_id is not None:
        turno = TurnoToma.objects.filter(pk=turno_id, toma=toma).first()
        if turno is None:
            raise ConteoInvalido("El turno no pertenece a esta toma.")
    if cantidad == 0 and not confirmar_cero and _cero_requiere_confirmacion(toma, detalle):
        raise ConteoRequiereConfirmacion(
            f"{detalle.producto.nombre}: se contó 0 y el sistema tiene "
            f"{detalle.stock_sistema.normalize():f}. Confirme si de verdad no hay ninguno."
        )

    numero = detalle.numero_conteos + 1
    ConteoToma.objects.create(
        empresa=toma.empresa,
        detalle=detalle,
        numero=numero,
        cantidad=cantidad,
        turno=turno,
        nota=nota,
    )
    _poner_conteo(toma, detalle, cantidad, numero, nota=nota, estado_fisico=estado_fisico)
    detalle.save()
    if toma.estado == EstadoToma.ABIERTA:
        toma.estado = EstadoToma.EN_CONTEO
        toma.save(update_fields=["estado"])
    return detalle


@transaction.atomic
def registrar_nota(*, toma_id: int, producto_id: int, nota: str) -> DetalleToma:
    """Pone o cambia la nota de un producto ya contado, sin volver a contarlo."""
    toma = _bloquear(toma_id)
    _exigir_estado(toma, ESTADOS_DE_CONTEO, "anotar")
    detalle = DetalleToma.objects.filter(toma=toma, producto_id=producto_id).first()
    if detalle is None:
        raise ConteoInvalido("Ese producto no está en esta toma.")
    if detalle.cantidad_contada is None:
        raise ConteoInvalido("Primero cuente el producto; la nota acompaña a un conteo.")
    nota = " ".join((nota or "").split())
    if not nota or len(nota) > 250:
        raise ConteoInvalido("Escriba una nota de hasta 250 caracteres.")
    detalle.nota = nota
    detalle.save(update_fields=["nota"])
    return detalle


@transaction.atomic
def iniciar_reconteo(toma_id: int) -> int:
    """Pasa a reconteo; devuelve cuántos productos hay que recontar."""
    toma = _bloquear(toma_id)
    _exigir_estado(toma, (EstadoToma.EN_CONTEO,), "iniciar el reconteo")
    cantidad = DetalleToma.objects.filter(toma=toma, requiere_reconteo=True).count()
    if cantidad == 0:
        raise TomaInvalida("No hay productos con diferencias importantes que recontar.")
    toma.estado = EstadoToma.EN_RECONTEO
    toma.save(update_fields=["estado"])
    _auditar(
        toma,
        "reconteo",
        f"Toma N° {toma.numero:06d}: reconteo de {cantidad} productos",
        {"por_recontar": cantidad},
    )
    return cantidad


# ---------------------------------------------------------------------------
# Cerrar y anular
# ---------------------------------------------------------------------------
@transaction.atomic
def cerrar_toma(toma_id: int, *, confirmar_pendientes: bool = False) -> TomaInventario:
    """Cierra el conteo. Los productos sin contar quedan fuera de la toma (con confirmación)."""
    toma = _bloquear(toma_id)
    _exigir_estado(toma, (EstadoToma.EN_CONTEO, EstadoToma.EN_RECONTEO), "cerrar")
    detalles = DetalleToma.objects.filter(toma=toma)

    por_recontar = detalles.filter(requiere_reconteo=True).count()
    if por_recontar:
        raise TomaIncompleta(
            f"Faltan {por_recontar} productos por recontar.", detalle={"por_recontar": por_recontar}
        )
    sin_nota_n = sin_nota(toma).count()
    if sin_nota_n:
        raise TomaIncompleta(
            f"{sin_nota_n} productos con una diferencia importante necesitan una nota.",
            detalle={"sin_nota": sin_nota_n},
        )
    pendientes = detalles.filter(cantidad_contada__isnull=True).count()
    if pendientes and not confirmar_pendientes:
        raise TomaIncompleta(
            f"Quedan {pendientes} productos sin contar. Confirme para dejarlos fuera de la toma.",
            detalle={"pendientes": pendientes},
        )
    contexto = obtener_contexto()
    toma.estado = EstadoToma.CERRADA
    toma.cerrada_en = timezone.now()
    toma.cerrada_por_id = contexto.usuario_id if contexto else None
    toma.save(update_fields=["estado", "cerrada_en", "cerrada_por_id"])
    _auditar(
        toma,
        "cerrada",
        f"Toma N° {toma.numero:06d} cerrada ({pendientes} productos quedaron fuera)",
        {"pendientes": pendientes},
    )
    return toma


@transaction.atomic
def anular_toma(toma_id: int, *, motivo: str) -> TomaInventario:
    """Anula la toma (con motivo) y libera el almacén. Sus conteos quedan como rastro.

    Una toma ya aprobada también se anula: sus movimientos de ajuste se extornan.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise MotivoObligatorio()
    toma = _bloquear(toma_id)
    _exigir_estado(toma, tuple(e for e in EstadoToma if e != EstadoToma.ANULADA), "anular")
    if toma.estado == EstadoToma.APROBADA:
        # Ya movió el Kardex: se extornan sus ajustes. Si no se puede (p. ej. un sobrante que
        # ya se vendió) se rechaza todo y la toma sigue aprobada.
        numeracion.bloquear(toma.empresa)
        for movimiento in movimientos_de_ajuste(toma):
            if movimiento.estado == MovimientoInventario.Estado.EMITIDO:
                anular_movimiento(
                    movimiento,
                    motivo=f"Anulación de la toma de inventario N° {toma.numero:06d}: {motivo}",
                )
    contexto = obtener_contexto()
    toma.estado = EstadoToma.ANULADA
    toma.anulada_en = timezone.now()
    toma.anulada_por_id = contexto.usuario_id if contexto else None
    toma.motivo_anulacion = motivo
    toma.save(update_fields=["estado", "anulada_en", "anulada_por_id", "motivo_anulacion"])
    _auditar(toma, "anulada", f"Toma N° {toma.numero:06d} anulada", {"motivo": motivo[:200]})
    return toma


# ---------------------------------------------------------------------------
# Aprobación y ajuste del Kardex
# ---------------------------------------------------------------------------
REFERENCIA_TOMA = "toma_inventario"


@dataclass(frozen=True, slots=True)
class AjusteCalculado:
    """Lo que hay que ajustar de un producto contado.

    ``diferencia`` NO es contado menos stock al corte: antes se descuenta lo que el sistema
    movió entre el corte y el momento del conteo (ventas, compras, traspasos…). Así una venta
    hecha mientras se contaba no se confunde con un faltante.
    """

    detalle: DetalleToma
    movimientos_posteriores: Decimal
    diferencia: Decimal

    @property
    def tipo(self) -> str:
        return TipoMovimiento.ENTRADA if self.diferencia > 0 else TipoMovimiento.SALIDA

    @property
    def cantidad(self) -> Decimal:
        return abs(self.diferencia)

    @property
    def importe_estimado(self) -> Decimal:
        """Al costo de la foto; el costo definitivo de una salida es el promedio del Kardex."""
        return a_dos(self.cantidad * self.detalle.costo_unitario)


def netos_hasta(toma: TomaInventario, instantes: dict[int, datetime]) -> dict[int, Decimal]:
    """Lo que el sistema movió entre el corte y el instante en que se contó cada producto.

    ``instantes`` es ``{producto_id: instante en que se contó}``. Cuando se contó DESPUÉS del
    corte (lo normal) es entradas menos salidas entre el corte y el conteo. Cuando se contó ANTES
    del corte (un conteo importado de días atrás) es lo contrario: lo que se movió entre el conteo
    y el corte, con el signo cambiado. En los dos casos, ``stock al corte + neto`` es lo que el
    sistema debía tener en el momento del conteo. Se mira la hora de registro de cada movimiento
    (incluye extornos). No escribe nada.
    """
    if not instantes:
        return {}
    corte = toma.fecha_corte
    desde = min([corte, *instantes.values()])
    netos: dict[int, Decimal] = defaultdict(Decimal)
    lineas = (
        LineaMovimiento.objects.filter(
            empresa_id=toma.empresa_id,
            almacen_id=toma.almacen_id,
            producto_id__in=list(instantes),
            movimiento__creado_en__gt=desde,
        )
        .values_list("producto_id", "tipo", "cantidad", "movimiento__creado_en")
        .iterator(chunk_size=5000)
    )
    for producto_id, tipo, cantidad, creado_en in lineas:
        contado_en = instantes[producto_id]
        signo = 1 if tipo == TipoMovimiento.ENTRADA else -1
        if contado_en >= corte:
            if corte < creado_en <= contado_en:
                netos[producto_id] += signo * cantidad
        elif contado_en < creado_en <= corte:
            netos[producto_id] -= signo * cantidad
    return netos


def calcular_ajustes(toma: TomaInventario) -> list[AjusteCalculado]:
    """Un renglón por cada producto contado (la diferencia puede ser 0). No escribe nada."""
    if toma.fecha_corte is None:
        raise TomaEstadoInvalido("La toma todavía no se abrió: no hay nada que ajustar.")
    detalles = list(
        DetalleToma.objects.filter(toma=toma, cantidad_contada__isnull=False)
        .select_related("producto")
        .order_by("producto__nombre", "id")
    )
    if not detalles:
        return []
    netos = netos_hasta(toma, {d.producto_id: d.contado_en for d in detalles})
    return [
        AjusteCalculado(
            detalle=d,
            movimientos_posteriores=netos.get(d.producto_id, Decimal("0")),
            diferencia=d.cantidad_contada
            - (d.stock_sistema + netos.get(d.producto_id, Decimal("0"))),
        )
        for d in detalles
    ]


def resumen_ajustes(ajustes: list[AjusteCalculado]) -> dict:
    """Totales de lo que se va a ajustar (vista previa para quien aprueba)."""
    con_ajuste = [a for a in ajustes if a.diferencia != 0]
    entradas = [a for a in con_ajuste if a.diferencia > 0]
    salidas = [a for a in con_ajuste if a.diferencia < 0]
    importe_entradas = sum((a.importe_estimado for a in entradas), Decimal("0"))
    importe_salidas = sum((a.importe_estimado for a in salidas), Decimal("0"))
    return {
        "productos_contados": len(ajustes),
        "productos_a_ajustar": len(con_ajuste),
        "sobrantes": len(entradas),
        "faltantes": len(salidas),
        "unidades_sobrantes": sum((a.cantidad for a in entradas), Decimal("0")),
        "unidades_faltantes": sum((a.cantidad for a in salidas), Decimal("0")),
        "importe_sobrante": importe_entradas,
        "importe_faltante": -importe_salidas,
        "importe_neto": importe_entradas - importe_salidas,
        "sin_costo": sum(1 for a in con_ajuste if a.detalle.costo_unitario == 0),
        "requieren_series": sum(1 for a in con_ajuste if a.detalle.producto.lleva_serie),
    }


def _problemas_del_ajuste(
    toma: TomaInventario, con_ajuste: list[AjusteCalculado], series: dict[int, tuple[str, ...]]
) -> list[dict]:
    """Todo lo que impediría generar el ajuste, junto, para corregirlo de una vez."""
    problemas = []
    ids_ajustados = {a.detalle.producto_id for a in con_ajuste}
    for producto_id in series.keys() - ids_ajustados:
        problemas.append(
            {
                "producto": producto_id,
                "motivo": "Se indicaron series de un producto sin diferencia.",
            }
        )
    ids_salida = [a.detalle.producto_id for a in con_ajuste if a.diferencia < 0]
    disponibles = dict(
        SaldoStock.objects.filter(
            empresa_id=toma.empresa_id, almacen_id=toma.almacen_id, producto_id__in=ids_salida
        ).values_list("producto_id", "cantidad")
    )
    for a in con_ajuste:
        producto = a.detalle.producto
        indicadas = series.get(producto.pk)
        if producto.lleva_serie:
            if a.cantidad != a.cantidad.to_integral_value():
                motivo = "Lleva serie y la diferencia no es un número entero."
            elif indicadas is None or len(indicadas) != int(a.cantidad):
                accion = "salen" if a.diferencia < 0 else "entran"
                motivo = f"Indique las {int(a.cantidad)} series que {accion}."
            else:
                motivo = ""
        else:
            motivo = "No lleva serie: no indique series." if indicadas else ""
        if not motivo and a.diferencia < 0:
            hay = disponibles.get(producto.pk, Decimal("0"))
            if a.cantidad > hay:
                motivo = (
                    f"Faltan {a.cantidad.normalize():f} pero el sistema solo tiene "
                    f"{hay.normalize():f} ahora: se vendió o movió lo que no estaba."
                )
        if motivo:
            problemas.append({"producto": producto.pk, "nombre": producto.nombre, "motivo": motivo})
    return problemas


def _registrar_ajustes(
    toma: TomaInventario,
    con_ajuste: list[AjusteCalculado],
    fecha: date,
    nota: str,
    series: dict[int, tuple[str, ...]],
) -> tuple[list[MovimientoInventario], dict[int, LineaMovimiento]]:
    """Registra los movimientos de ajuste (sobrantes = entrada, faltantes = salida)."""
    ids_entrada = [a.detalle.producto_id for a in con_ajuste if a.diferencia > 0]
    costo_actual = dict(
        SaldoStock.objects.filter(
            empresa_id=toma.empresa_id, almacen_id=toma.almacen_id, producto_id__in=ids_entrada
        ).values_list("producto_id", "costo_unitario")
    )
    nuevas: dict[str, list[LineaNueva]] = {TipoMovimiento.SALIDA: [], TipoMovimiento.ENTRADA: []}
    for a in con_ajuste:
        producto = a.detalle.producto
        indicadas = tuple(series.get(producto.pk, ()))
        if a.tipo == TipoMovimiento.ENTRADA:
            # El sobrante entra al costo de la foto; si no tenía costo, al promedio de hoy.
            costo = a.detalle.costo_unitario or costo_actual.get(producto.pk, Decimal("0"))
            nuevas[a.tipo].append(
                LineaNueva(
                    producto, a.cantidad, importe=a_dos(a.cantidad * costo), series=indicadas
                )
            )
        else:
            nuevas[a.tipo].append(LineaNueva(producto, a.cantidad, series=indicadas))
    observacion = f"Toma de inventario físico N° {toma.numero:06d}"
    if nota:
        observacion = f"{observacion}: {nota}"
    movimientos, lineas = [], {}
    for tipo, pendientes in nuevas.items():
        for inicio in range(0, len(pendientes), MAX_LINEAS):
            movimiento = registrar_movimiento(
                empresa=toma.empresa,
                almacen=toma.almacen,
                tipo=tipo,
                origen=OrigenMovimiento.AJUSTE,
                fecha=fecha,
                tipo_operacion=AJUSTE_INVENTARIO,
                lineas=pendientes[inicio : inicio + MAX_LINEAS],
                observacion=observacion,
                referencia_tipo=REFERENCIA_TOMA,
                referencia_id=toma.pk,
            )
            movimientos.append(movimiento)
            for linea in movimiento.lineas.all():
                lineas[linea.producto_id] = linea
    return movimientos, lineas


@transaction.atomic
def aprobar_toma(
    toma_id: int,
    *,
    fecha: date | None = None,
    nota: str = "",
    series: dict[int, tuple[str, ...]] | None = None,
) -> tuple[TomaInventario, list[MovimientoInventario]]:
    """Aprueba una toma cerrada y genera el ajuste en el Kardex (origen AJUSTE, operación 28).

    Todo o nada: si algo del ajuste no se puede registrar (series que faltan, stock que ya no
    alcanza, periodo cerrado…) no se guarda nada y la toma sigue cerrada. Los productos sin
    contar no se ajustan.
    """
    toma = _bloquear(toma_id)
    _exigir_estado(toma, (EstadoToma.CERRADA,), "aprobar")
    # Cerrojo por empresa: ningún movimiento se cuela mientras se calcula y se registra el ajuste.
    numeracion.bloquear(toma.empresa)
    hoy = timezone.localdate()
    fecha = fecha or hoy
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise TomaInvalida("La fecha del ajuste no es válida.")
    if fecha > hoy:
        raise TomaInvalida("La fecha del ajuste no puede ser futura.")
    if fecha < timezone.localtime(toma.fecha_corte).date():
        raise TomaInvalida("La fecha del ajuste no puede ser anterior al corte de la toma.")
    nota = " ".join((nota or "").split())
    if len(nota) > 250:
        raise TomaInvalida("La nota admite hasta 250 caracteres.")
    series = {
        int(producto_id): tuple(" ".join(str(n).split()).upper() for n in numeros)
        for producto_id, numeros in (series or {}).items()
    }

    calculados = calcular_ajustes(toma)
    con_ajuste = [a for a in calculados if a.diferencia != 0]
    problemas = _problemas_del_ajuste(toma, con_ajuste, series)
    if problemas:
        primeros = "; ".join(
            f"{p.get('nombre', p['producto'])}: {p['motivo']}" for p in problemas[:3]
        )
        raise AjusteImposible(
            f"No se puede generar el ajuste ({len(problemas)} productos con problemas). {primeros}",
            detalle={"total": len(problemas), "productos": problemas[:50]},
        )
    movimientos, lineas = _registrar_ajustes(toma, con_ajuste, fecha, nota, series)

    for a in calculados:
        d = a.detalle
        d.movimientos_posteriores = a.movimientos_posteriores
        d.diferencia_ajuste = a.diferencia
        linea = lineas.get(d.producto_id)
        d.linea_ajuste = linea
        d.importe_ajuste = (
            Decimal("0.00")
            if linea is None
            else (linea.costo_total if a.diferencia > 0 else -linea.costo_total)
        )
    DetalleToma.objects.bulk_update(
        [a.detalle for a in calculados],
        ["movimientos_posteriores", "diferencia_ajuste", "linea_ajuste", "importe_ajuste"],
        batch_size=LOTE_DETALLES,
    )
    contexto = obtener_contexto()
    toma.estado = EstadoToma.APROBADA
    toma.aprobada_en = timezone.now()
    toma.aprobada_por_id = contexto.usuario_id if contexto else None
    toma.fecha_ajuste = fecha
    toma.nota_aprobacion = nota
    toma.save(
        update_fields=[
            "estado",
            "aprobada_en",
            "aprobada_por_id",
            "fecha_ajuste",
            "nota_aprobacion",
        ]
    )
    _auditar(
        toma,
        "aprobada",
        f"Toma N° {toma.numero:06d} aprobada: {len(con_ajuste)} productos ajustados",
        {
            "ajustes": len(con_ajuste),
            "movimientos": [m.numero for m in movimientos],
            "fecha": fecha,
        },
    )
    return toma, movimientos


def movimientos_de_ajuste(toma: TomaInventario) -> list[MovimientoInventario]:
    """Los movimientos de ajuste que generó la aprobación (vacío si todavía no se aprobó)."""
    return list(
        MovimientoInventario.objects.filter(
            empresa_id=toma.empresa_id,
            referencia_tipo=REFERENCIA_TOMA,
            referencia_id=toma.pk,
            origen=OrigenMovimiento.AJUSTE,
        ).order_by("numero")
    )


# ---------------------------------------------------------------------------
# Avance y resultado
# ---------------------------------------------------------------------------
def avance(toma: TomaInventario) -> dict:
    """Contados, por contar y porcentaje; y, aparte, el resultado (faltantes/sobrantes/conformes).

    El resultado revela el stock del sistema: quien arma la respuesta decide si se muestra.
    """
    detalles = DetalleToma.objects.filter(toma=toma)

    def cuenta(**filtro):
        return Count("id", filter=Q(**filtro))

    def suma(campo, **filtro):
        return Sum(campo, filter=Q(**filtro))

    datos = detalles.aggregate(
        total=Count("id"),
        contados=cuenta(cantidad_contada__isnull=False),
        por_recontar=cuenta(requiere_reconteo=True),
        conformes=cuenta(resultado=ResultadoToma.CONFORME),
        faltantes=cuenta(resultado=ResultadoToma.FALTANTE),
        sobrantes=cuenta(resultado=ResultadoToma.SOBRANTE),
        unidades_faltantes=suma("diferencia", resultado=ResultadoToma.FALTANTE),
        unidades_sobrantes=suma("diferencia", resultado=ResultadoToma.SOBRANTE),
        importe_faltante=suma("importe_diferencia", resultado=ResultadoToma.FALTANTE),
        importe_sobrante=suma("importe_diferencia", resultado=ResultadoToma.SOBRANTE),
    )
    total, contados = datos["total"], datos["contados"]
    porcentaje = (
        (Decimal(contados) * 100 / Decimal(total)).quantize(Decimal("0.1"), ROUND_HALF_UP)
        if total
        else Decimal("0.0")
    )
    cero = Decimal("0")
    faltante = datos["importe_faltante"] or cero
    sobrante = datos["importe_sobrante"] or cero
    por_categoria = [
        {
            "categoria_id": categoria_id,
            "categoria": nombre,
            "total": cantidad,
            "contados": hechos,
            "por_contar": cantidad - hechos,
        }
        for categoria_id, nombre, cantidad, hechos in detalles.values(
            "producto__categoria_id", "producto__categoria__nombre"
        )
        .annotate(
            cantidad=Count("id"), hechos=Count("id", filter=Q(cantidad_contada__isnull=False))
        )
        .order_by("producto__categoria__nombre")
        .values_list("producto__categoria_id", "producto__categoria__nombre", "cantidad", "hechos")
    ]
    return {
        "total": total,
        "contados": contados,
        "por_contar": total - contados,
        "porcentaje_avance": porcentaje,
        "por_recontar": datos["por_recontar"],
        "por_anotar": sin_nota(toma).count(),
        "por_categoria": por_categoria,
        "resultado": {
            "conformes": datos["conformes"],
            "faltantes": datos["faltantes"],
            "sobrantes": datos["sobrantes"],
            "unidades_faltantes": datos["unidades_faltantes"] or cero,
            "unidades_sobrantes": datos["unidades_sobrantes"] or cero,
            "importe_faltante": faltante,
            "importe_sobrante": sobrante,
            "importe_neto": faltante + sobrante,
        },
    }
