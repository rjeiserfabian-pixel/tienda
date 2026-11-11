"""Conciliación bancaria: comparar el estado de cuenta del banco con el libro de movimientos.

Cada línea del extracto se empareja con un movimiento del libro (automática o manualmente), o se
registra como un movimiento nuevo si el banco la cobró y aún no estaba anotada (comisión, ITF,
intereses). Los movimientos del libro que el banco todavía no muestra (un depósito en tránsito) son
partidas legítimas. Cuando el banco ya no tiene nada sin explicar, el extracto se cierra.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.importacion import ErrorImportacion, _plano
from apps.mantenimiento.models import ConceptoCaja, Correlativo, CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa

from . import extractos
from .exceptions import ConciliacionInvalida, MovimientoInvalido
from .models import (
    EstadoCuenta,
    LineaEstadoCuenta,
    MovimientoCaja,
    Origen,
    TipoMovimiento,
)
from .servicios import (
    CERO,
    _exigir_empresa,
    _firmado,
    anular_movimiento,
    registrar_movimiento,
    saldo_de,
)
from .sesiones import nombre_de

logger = logging.getLogger(__name__)

DIAS_AUTOMATICOS = 3
DIAS_MAXIMOS = 31


def _exigir_cuenta_bancaria(empresa: Empresa, cuenta: CuentaFinanciera) -> None:
    if cuenta.empresa_id != empresa.pk or cuenta.tipo == CuentaFinanciera.Tipo.CAJA:
        raise ConciliacionInvalida("Solo se concilian cuentas de banco y billeteras de la empresa.")
    if cuenta.estado != EstadoRegistro.ACTIVO:
        raise ConciliacionInvalida("La cuenta está inactiva.")


def _exigir_abierto(estado: EstadoCuenta) -> None:
    if estado.estado != EstadoCuenta.Estado.ABIERTO:
        raise ConciliacionInvalida("El estado de cuenta está cerrado: reábralo para cambiarlo.")


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"caja:extracto:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


# ---------------------------------------------------------------------------
# Importar
# ---------------------------------------------------------------------------
def previsualizar(*, empresa: Empresa, cuenta: CuentaFinanciera, archivo) -> dict:
    """Lee el archivo y dice qué se importaría, sin guardar nada."""
    _exigir_empresa(empresa)
    _exigir_cuenta_bancaria(empresa, cuenta)
    lectura = extractos.leer(archivo)
    repetidas = _ya_importadas(cuenta, lectura.lineas)
    nuevas = [x for x in lectura.lineas if x.huella not in repetidas]
    return {
        "columnas": lectura.columnas,
        "total": len(lectura.lineas),
        "nuevas": len(nuevas),
        "repetidas": len(lectura.lineas) - len(nuevas),
        "ignoradas": lectura.ignoradas,
        "con_error": lectura.total_errores,
        "errores": lectura.errores,
        "desde": min((x.fecha for x in nuevas), default=None),
        "hasta": max((x.fecha for x in nuevas), default=None),
        "abonos": sum((x.monto for x in nuevas if x.monto > 0), CERO),
        "cargos": -sum((x.monto for x in nuevas if x.monto < 0), CERO),
        "muestra": [
            {
                "fecha": x.fecha,
                "descripcion": x.descripcion,
                "referencia": x.referencia,
                "monto": x.monto,
                "repetida": x.huella in repetidas,
            }
            for x in lectura.lineas[:15]
        ],
    }


def _ya_importadas(cuenta: CuentaFinanciera, lineas) -> set[str]:
    return set(
        LineaEstadoCuenta.objects.filter(
            cuenta=cuenta, huella__in=[x.huella for x in lineas]
        ).values_list("huella", flat=True)
    )


@transaction.atomic
def importar(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    archivo,
    usuario,
    saldo_inicial: Decimal | None = None,
    saldo_final: Decimal | None = None,
) -> EstadoCuenta:
    """Importa las líneas nuevas del extracto (las que ya se importaron antes se omiten)."""
    _exigir_empresa(empresa)
    _exigir_cuenta_bancaria(empresa, cuenta)
    lectura = extractos.leer(archivo)
    if lectura.total_errores:
        raise ErrorImportacion(
            f"El archivo tiene {lectura.total_errores} filas con problemas. "
            "Corrígelas y vuelve a subirlo."
        )
    if saldo_inicial is not None and saldo_final is not None:
        movimiento_total = sum((x.monto for x in lectura.lineas), CERO)
        if saldo_inicial + movimiento_total != saldo_final:
            raise ErrorImportacion(
                "Los saldos no cuadran con el extracto: el saldo inicial más los abonos y "
                f"cargos da {saldo_inicial + movimiento_total}, no {saldo_final}. "
                "Puede faltar alguna línea."
            )
    repetidas = _ya_importadas(cuenta, lectura.lineas)
    nuevas = [x for x in lectura.lineas if x.huella not in repetidas]
    if not nuevas:
        raise ErrorImportacion("Todas las líneas de este extracto ya estaban importadas.")

    estado = EstadoCuenta.objects.create(
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        cuenta=cuenta,
        desde=min(x.fecha for x in nuevas),
        hasta=max(x.fecha for x in nuevas),
        saldo_inicial_banco=saldo_inicial,
        saldo_final_banco=saldo_final,
        archivo_nombre=(archivo.name or "extracto")[:150],
        importado_por_id=usuario.pk,
        importado_por_nombre=nombre_de(usuario),
    )
    LineaEstadoCuenta.objects.bulk_create(
        [
            LineaEstadoCuenta(
                empresa=empresa,
                estado_cuenta=estado,
                cuenta=cuenta,
                orden=i,
                fecha=x.fecha,
                descripcion=x.descripcion,
                referencia=x.referencia,
                monto=x.monto,
                saldo=x.saldo,
                huella=x.huella,
            )
            for i, x in enumerate(nuevas, start=1)
        ]
    )
    registrar(
        "caja.extracto_importado",
        recurso_tipo="estado_cuenta",
        recurso_id=estado.pk,
        empresa_id=empresa.pk,
        resumen=f"Estado de cuenta {estado.numero:06d} de {cuenta.nombre}: {len(nuevas)} líneas",
        detalle={"archivo": estado.archivo_nombre, "repetidas": len(repetidas)},
    )
    return estado


# ---------------------------------------------------------------------------
# Emparejar
# ---------------------------------------------------------------------------
def _tipo_de(monto: Decimal) -> str:
    return TipoMovimiento.INGRESO if monto > 0 else TipoMovimiento.EGRESO


def candidatos(linea: LineaEstadoCuenta, dias: int = 5) -> list[MovimientoCaja]:
    """Movimientos del libro sin conciliar que podrían ser esta línea: mismo importe y cercanos."""
    dias = max(0, min(dias, DIAS_MAXIMOS))
    movimientos = (
        MovimientoCaja.objects.filter(
            cuenta_id=linea.cuenta_id,
            estado=MovimientoCaja.Estado.EMITIDO,
            tipo=_tipo_de(linea.monto),
            monto=abs(linea.monto),
            fecha__gte=linea.fecha - timedelta(days=dias),
            fecha__lte=linea.fecha + timedelta(days=dias),
            conciliaciones__isnull=True,
        )
        .select_related("concepto")
        .distinct()
    )
    ref = _plano(linea.referencia)
    return sorted(
        movimientos,
        key=lambda m: (
            0 if ref and _plano(m.referencia) == ref else 1,
            abs((m.fecha - linea.fecha).days),
            m.pk,
        ),
    )


def _unir(linea: LineaEstadoCuenta, movimiento: MovimientoCaja, como: str, usuario) -> None:
    linea.movimiento = movimiento
    linea.union = como
    linea.conciliada_en = timezone.now()
    linea.conciliada_por_nombre = nombre_de(usuario) if usuario else "Sistema"
    try:
        with transaction.atomic():
            linea.save(
                update_fields=["movimiento", "union", "conciliada_en", "conciliada_por_nombre"]
            )
    except IntegrityError:
        raise ConciliacionInvalida("Ese movimiento ya está conciliado con otra línea.") from None


@transaction.atomic
def conciliar_automaticamente(estado: EstadoCuenta, usuario) -> int:
    """Une las líneas que tienen un solo movimiento posible; deja las dudosas para revisarlas."""
    estado = EstadoCuenta.objects.select_for_update().get(pk=estado.pk)
    _exigir_empresa(estado.empresa)
    _exigir_abierto(estado)
    pendientes = list(estado.lineas.filter(movimiento__isnull=True))
    libres = list(
        MovimientoCaja.objects.filter(
            cuenta_id=estado.cuenta_id,
            estado=MovimientoCaja.Estado.EMITIDO,
            fecha__gte=estado.desde - timedelta(days=DIAS_AUTOMATICOS),
            fecha__lte=estado.hasta + timedelta(days=DIAS_AUTOMATICOS),
            conciliaciones__isnull=True,
        ).distinct()
    )

    def cerca(linea, m):
        return (
            m.tipo == _tipo_de(linea.monto)
            and m.monto == abs(linea.monto)
            and abs((m.fecha - linea.fecha).days) <= DIAS_AUTOMATICOS
        )

    usados: set[int] = set()
    unidas = 0
    for linea in pendientes:
        posibles = [m for m in libres if m.pk not in usados and cerca(linea, m)]
        ref = _plano(linea.referencia)
        por_ref = [m for m in posibles if ref and _plano(m.referencia) == ref]
        elegido = None
        if len(por_ref) == 1:
            elegido = por_ref[0]
        elif len(posibles) == 1:
            # Sin N° de operación que lo confirme, solo si ninguna otra línea lo reclama.
            rivales = [
                x
                for x in pendientes
                if x.pk != linea.pk and not x.movimiento_id and cerca(x, posibles[0])
            ]
            if not rivales:
                elegido = posibles[0]
        if elegido is not None:
            usados.add(elegido.pk)
            _unir(linea, elegido, LineaEstadoCuenta.Union.AUTOMATICA, usuario)
            unidas += 1
    if unidas:
        registrar(
            "caja.conciliacion_automatica",
            recurso_tipo="estado_cuenta",
            recurso_id=estado.pk,
            empresa_id=estado.empresa_id,
            resumen=f"Conciliación automática del estado de cuenta {estado.numero:06d}: {unidas}",
            detalle={"unidas": unidas},
        )
    return unidas


def _bloquear_linea(linea: LineaEstadoCuenta) -> LineaEstadoCuenta:
    linea = (
        LineaEstadoCuenta.objects.select_for_update()
        .select_related("estado_cuenta", "cuenta")
        .get(pk=linea.pk)
    )
    _exigir_empresa(linea.empresa)
    _exigir_abierto(linea.estado_cuenta)
    return linea


@transaction.atomic
def conciliar(linea: LineaEstadoCuenta, movimiento: MovimientoCaja, usuario) -> LineaEstadoCuenta:
    """Une una línea del banco con un movimiento del libro (mismo importe, misma cuenta)."""
    linea = _bloquear_linea(linea)
    if linea.movimiento_id:
        raise ConciliacionInvalida("La línea ya está conciliada.")
    if movimiento.cuenta_id != linea.cuenta_id:
        raise ConciliacionInvalida("El movimiento es de otra cuenta.")
    if movimiento.estado != MovimientoCaja.Estado.EMITIDO:
        raise ConciliacionInvalida("El movimiento está anulado.")
    if movimiento.tipo != _tipo_de(linea.monto) or movimiento.monto != abs(linea.monto):
        raise ConciliacionInvalida("El importe del movimiento no es el de la línea del banco.")
    _unir(linea, movimiento, LineaEstadoCuenta.Union.MANUAL, usuario)
    return linea


@transaction.atomic
def registrar_partida(
    linea: LineaEstadoCuenta, *, concepto: ConceptoCaja, usuario, glosa: str = ""
) -> LineaEstadoCuenta:
    """El banco cobró o abonó algo que no estaba en el libro: se anota y queda conciliado."""
    linea = _bloquear_linea(linea)
    if linea.movimiento_id:
        raise ConciliacionInvalida("La línea ya está conciliada.")
    movimiento = registrar_movimiento(
        empresa=linea.empresa,
        cuenta=linea.cuenta,
        tipo=_tipo_de(linea.monto),
        monto=abs(linea.monto),
        concepto=concepto,
        fecha=linea.fecha,
        glosa=glosa or linea.descripcion or "Según estado de cuenta",
        referencia=linea.referencia,
        origen_tipo=Origen.EXTRACTO,
        origen_id=linea.pk,
    )
    _unir(linea, movimiento, LineaEstadoCuenta.Union.REGISTRADA, usuario)
    return linea


@transaction.atomic
def desconciliar(linea: LineaEstadoCuenta, usuario) -> LineaEstadoCuenta:
    """Deshace la unión. Si el movimiento se creó desde el extracto, también se anula."""
    linea = _bloquear_linea(linea)
    movimiento = linea.movimiento
    if movimiento is None:
        raise ConciliacionInvalida("La línea no está conciliada.")
    linea.movimiento = None
    linea.union = ""
    linea.conciliada_en = None
    linea.conciliada_por_nombre = ""
    linea.save(update_fields=["movimiento", "union", "conciliada_en", "conciliada_por_nombre"])
    if movimiento.origen_tipo == Origen.EXTRACTO:
        anular_movimiento(
            movimiento,
            motivo="Se deshizo la conciliación del estado de cuenta",
            desde_origen=True,
            ignorar_sesion=True,
        )
    return linea


# ---------------------------------------------------------------------------
# Resumen y cierre
# ---------------------------------------------------------------------------
def resumen(estado: EstadoCuenta) -> dict:
    """Dónde está la conciliación: líneas, saldos y lo que falta explicar."""
    conteo = estado.lineas.aggregate(
        total=Count("id"),
        conciliadas=Count("id", filter=Q(movimiento__isnull=False)),
        pendientes=Count("id", filter=Q(movimiento__isnull=True)),
        neto_pendiente=Sum("monto", filter=Q(movimiento__isnull=True)),
    )
    neto_banco = conteo["neto_pendiente"] or CERO
    libros_sin_banco = MovimientoCaja.objects.filter(
        cuenta_id=estado.cuenta_id,
        estado=MovimientoCaja.Estado.EMITIDO,
        fecha__lte=estado.hasta,
        conciliaciones__isnull=True,
    )
    neto_libros = libros_sin_banco.aggregate(neto=Sum(_firmado()))["neto"] or CERO
    saldo_libros = saldo_de(estado.cuenta, hasta=estado.hasta)
    diferencia = None
    if estado.saldo_final_banco is not None:
        # Lo que el banco tendría sin lo que el libro no anotó, frente a lo que el libro tendría
        # sin lo que el banco aún no muestra: si todo está explicado, son iguales.
        diferencia = (estado.saldo_final_banco - neto_banco) - (saldo_libros - neto_libros)
    return {
        "lineas": conteo["total"],
        "conciliadas": conteo["conciliadas"],
        "pendientes": conteo["pendientes"],
        "banco_sin_libro": neto_banco,
        "libro_sin_banco": neto_libros,
        "libro_sin_banco_cantidad": libros_sin_banco.count(),
        "saldo_libros": saldo_libros,
        "saldo_banco": estado.saldo_final_banco,
        "diferencia": diferencia,
    }


@transaction.atomic
def cerrar(estado: EstadoCuenta, *, usuario, nota: str = "") -> EstadoCuenta:
    """Cierra la conciliación: el banco ya no tiene líneas sin explicar."""
    estado = EstadoCuenta.objects.select_for_update().select_related("cuenta").get(pk=estado.pk)
    _exigir_empresa(estado.empresa)
    _exigir_abierto(estado)
    r = resumen(estado)
    if r["pendientes"]:
        raise ConciliacionInvalida(
            f"Quedan {r['pendientes']} líneas del banco sin conciliar: únelas con un movimiento "
            "o regístralas."
        )
    nota = " ".join((nota or "").split())[:250]
    if r["diferencia"] is not None and r["diferencia"] != CERO and not nota:
        raise MovimientoInvalido(
            f"Los saldos no cuadran (diferencia {r['diferencia']}): explique el motivo en la nota."
        )
    estado.estado = EstadoCuenta.Estado.CERRADO
    estado.cerrado_en = timezone.now()
    estado.cerrado_por_nombre = nombre_de(usuario)
    estado.nota_cierre = nota
    estado.save(update_fields=["estado", "cerrado_en", "cerrado_por_nombre", "nota_cierre"])
    registrar(
        "caja.conciliacion_cerrada",
        recurso_tipo="estado_cuenta",
        recurso_id=estado.pk,
        empresa_id=estado.empresa_id,
        resumen=f"Estado de cuenta {estado.numero:06d} conciliado",
        detalle={"diferencia": r["diferencia"], "nota": nota},
    )
    return estado


@transaction.atomic
def reabrir(estado: EstadoCuenta, *, motivo: str, usuario) -> EstadoCuenta:
    estado = EstadoCuenta.objects.select_for_update().get(pk=estado.pk)
    _exigir_empresa(estado.empresa)
    motivo = " ".join((motivo or "").split())[:250]
    if not motivo:
        raise MovimientoInvalido("Indique el motivo de la reapertura.")
    if estado.estado != EstadoCuenta.Estado.CERRADO:
        raise ConciliacionInvalida("El estado de cuenta no está cerrado.")
    estado.estado = EstadoCuenta.Estado.ABIERTO
    estado.cerrado_en = None
    estado.cerrado_por_nombre = ""
    estado.nota_cierre = ""
    estado.reaperturas += 1
    estado.save(
        update_fields=["estado", "cerrado_en", "cerrado_por_nombre", "nota_cierre", "reaperturas"]
    )
    registrar(
        "caja.conciliacion_reabierta",
        recurso_tipo="estado_cuenta",
        recurso_id=estado.pk,
        empresa_id=estado.empresa_id,
        resumen=f"Estado de cuenta {estado.numero:06d} reabierto",
        detalle={"motivo": motivo, "por": nombre_de(usuario)},
    )
    return estado


@transaction.atomic
def descartar(estado: EstadoCuenta, usuario) -> None:
    """Quita un extracto importado por error (solo si no se concilió ninguna línea)."""
    estado = EstadoCuenta.objects.select_for_update().get(pk=estado.pk)
    _exigir_empresa(estado.empresa)
    _exigir_abierto(estado)
    if estado.lineas.filter(movimiento__isnull=False).exists():
        raise ConciliacionInvalida("Ya hay líneas conciliadas: deshaga esas uniones primero.")
    for linea in estado.lineas.all():
        linea.delete()
    estado.delete()
    registrar(
        "caja.extracto_descartado",
        recurso_tipo="estado_cuenta",
        recurso_id=estado.pk,
        empresa_id=estado.empresa_id,
        resumen=f"Estado de cuenta {estado.numero:06d} descartado",
        detalle={"por": nombre_de(usuario)},
    )
