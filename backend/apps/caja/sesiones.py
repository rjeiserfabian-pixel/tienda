"""Sesiones de caja: abrir un turno, arquear, cerrar con diferencia y reabrir con permiso.

El efectivo que el sistema espera en una caja es su saldo del libro. Contar lo que hay y compararlo
es el arqueo; al cerrar, la diferencia (sobra o falta) se asienta como un movimiento automático
para que el saldo coincida con lo contado y la sesión quede cuadrada.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Correlativo, CuentaFinanciera, EstadoRegistro
from apps.organizacion.models import Empresa

from .exceptions import MovimientoInvalido, SesionInvalida
from .models import ArqueoCaja, MovimientoCaja, Origen, SesionCaja, TipoArqueo, TipoMovimiento
from .servicios import (
    CERO,
    DOS,
    _exigir_empresa,
    anular_movimiento,
    concepto_del_sistema,
    registrar_movimiento,
    saldo_de,
)
from .transferencias import registrar_transferencia

logger = logging.getLogger(__name__)

DENOMINACIONES = {
    "PEN": ("200", "100", "50", "20", "10", "5", "2", "1", "0.5", "0.2", "0.1"),
    "USD": ("100", "50", "20", "10", "5", "2", "1"),
}
MAXIMO_POR_DENOMINACION = 1_000_000


def nombre_de(usuario) -> str:
    return (usuario.get_full_name() or usuario.get_username() or "")[:150]


def contar(conteo: dict, moneda: str) -> tuple[dict[str, int], Decimal]:
    """Valida el conteo por denominación y devuelve (conteo limpio, total)."""
    permitidas = {Decimal(d): d for d in DENOMINACIONES[moneda]}
    limpio: dict[str, int] = {}
    total = CERO
    for clave, cantidad in (conteo or {}).items():
        try:
            valor = Decimal(str(clave))
        except InvalidOperation:
            raise MovimientoInvalido(f"La denominación «{clave}» no es válida.") from None
        if valor not in permitidas:
            raise MovimientoInvalido(f"No existe la denominación {clave} en esa moneda.")
        if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad < 0:
            raise MovimientoInvalido("Las cantidades son números enteros, de cero en adelante.")
        if cantidad > MAXIMO_POR_DENOMINACION:
            raise MovimientoInvalido("La cantidad es demasiado grande.")
        if cantidad:
            limpio[permitidas[valor]] = cantidad
            total += valor * cantidad
    return limpio, total.quantize(DOS)


def sesion_abierta(cuenta: CuentaFinanciera) -> SesionCaja | None:
    return SesionCaja.objects.filter(cuenta=cuenta, estado=SesionCaja.Estado.ABIERTA).first()


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"caja:sesion:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _bloquear(sesion: SesionCaja) -> SesionCaja:
    return (
        SesionCaja.objects.select_for_update().select_related("cuenta", "empresa").get(pk=sesion.pk)
    )


@transaction.atomic
def abrir_sesion(
    *,
    empresa: Empresa,
    cuenta: CuentaFinanciera,
    usuario,
    fondo: Decimal = CERO,
    desde_cuenta: CuentaFinanciera | None = None,
    observacion: str = "",
) -> SesionCaja:
    """Abre el turno de una caja; puede recibir su fondo inicial de otra (la principal)."""
    _exigir_empresa(empresa)
    if cuenta.empresa_id != empresa.pk or cuenta.tipo != CuentaFinanciera.Tipo.CAJA:
        raise SesionInvalida("Solo las cajas de efectivo de la empresa tienen sesión.")
    if cuenta.estado != EstadoRegistro.ACTIVO:
        raise SesionInvalida("La caja está inactiva.")
    if sesion_abierta(cuenta) is not None:
        raise SesionInvalida(f"«{cuenta.nombre}» ya tiene una sesión abierta.")
    if fondo < 0 or fondo != fondo.quantize(DOS):
        raise MovimientoInvalido("El fondo admite hasta 2 decimales y no puede ser negativo.")
    if fondo > 0:
        if desde_cuenta is None:
            raise MovimientoInvalido("Indique de qué caja sale el fondo inicial.")
        if (
            desde_cuenta.tipo != CuentaFinanciera.Tipo.CAJA
            or desde_cuenta.empresa_id != empresa.pk
            or desde_cuenta.moneda != cuenta.moneda
        ):
            raise MovimientoInvalido("El fondo sale de otra caja de efectivo de la misma moneda.")

    sesion = SesionCaja.objects.create(
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        cuenta=cuenta,
        responsable_id=usuario.pk,
        responsable_nombre=nombre_de(usuario),
        abierta_en=timezone.now(),
        saldo_apertura=saldo_de(cuenta),
        observacion=" ".join((observacion or "").split())[:250],
    )
    if fondo > 0:
        registrar_transferencia(
            empresa=empresa,
            cuenta_origen=desde_cuenta,
            cuenta_destino=cuenta,
            monto=fondo,
            glosa=f"Fondo inicial de la sesión {sesion.numero:06d}",
        )
        sesion.fondo_entregado = fondo
        sesion.save(update_fields=["fondo_entregado"])
    registrar(
        "caja.sesion_abierta",
        recurso_tipo="sesion_caja",
        recurso_id=sesion.pk,
        empresa_id=empresa.pk,
        resumen=f"Sesión {sesion.numero:06d} abierta en {cuenta.nombre}",
        detalle={"cuenta": cuenta.pk, "fondo": fondo, "saldo_apertura": sesion.saldo_apertura},
    )
    return sesion


def _exigir_responsable(sesion: SesionCaja, usuario, *, supervisor: bool) -> None:
    if str(sesion.responsable_id) != str(usuario.pk) and not supervisor:
        raise SesionInvalida(
            f"La sesión es de {sesion.responsable_nombre}: solo esa persona o un supervisor "
            "puede contar o cerrar la caja."
        )


def _arquear(sesion: SesionCaja, *, tipo, conteo, observacion, usuario) -> ArqueoCaja:
    limpio, contado = contar(conteo, sesion.cuenta.moneda)
    esperado = saldo_de(sesion.cuenta)
    return ArqueoCaja.objects.create(
        empresa=sesion.empresa,
        sesion=sesion,
        tipo=tipo,
        esperado=esperado,
        contado=contado,
        diferencia=contado - esperado,
        conteo=limpio,
        observacion=" ".join((observacion or "").split())[:250],
        hecho_por_id=usuario.pk,
        hecho_por_nombre=nombre_de(usuario),
    )


@transaction.atomic
def arquear_sesion(
    sesion: SesionCaja, *, conteo: dict, usuario, observacion: str = "", supervisor: bool = False
) -> ArqueoCaja:
    """Cuenta el efectivo sin cerrar: compara con lo que el sistema espera y lo deja anotado."""
    sesion = _bloquear(sesion)
    _exigir_empresa(sesion.empresa)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise SesionInvalida("La sesión ya está cerrada.")
    _exigir_responsable(sesion, usuario, supervisor=supervisor)
    arqueo = _arquear(
        sesion, tipo=TipoArqueo.PARCIAL, conteo=conteo, observacion=observacion, usuario=usuario
    )
    registrar(
        "caja.arqueo_hecho",
        recurso_tipo="sesion_caja",
        recurso_id=sesion.pk,
        empresa_id=sesion.empresa_id,
        resumen=f"Arqueo de la sesión {sesion.numero:06d}: diferencia {arqueo.diferencia}",
        detalle={"esperado": arqueo.esperado, "contado": arqueo.contado},
    )
    return arqueo


@transaction.atomic
def cerrar_sesion(
    sesion: SesionCaja, *, conteo: dict, usuario, observacion: str = "", supervisor: bool = False
) -> SesionCaja:
    """Cuenta el efectivo y cierra; lo que sobra o falta queda asentado en el libro."""
    sesion = _bloquear(sesion)
    _exigir_empresa(sesion.empresa)
    if sesion.estado != SesionCaja.Estado.ABIERTA:
        raise SesionInvalida("La sesión ya está cerrada.")
    _exigir_responsable(sesion, usuario, supervisor=supervisor)
    arqueo = _arquear(
        sesion, tipo=TipoArqueo.CIERRE, conteo=conteo, observacion=observacion, usuario=usuario
    )
    if arqueo.diferencia != CERO and not arqueo.observacion:
        raise MovimientoInvalido("Explique la diferencia en el campo de observación.")
    return _cerrar_con_arqueo(sesion, arqueo, usuario)


def _cerrar_con_arqueo(sesion: SesionCaja, arqueo: ArqueoCaja, usuario) -> SesionCaja:
    """Asienta lo que sobra o falta y cierra la sesión (lo comparten todos los cierres)."""
    if arqueo.diferencia != CERO:
        sobra = arqueo.diferencia > 0
        registrar_movimiento(
            empresa=sesion.empresa,
            cuenta=sesion.cuenta,
            tipo=TipoMovimiento.INGRESO if sobra else TipoMovimiento.EGRESO,
            monto=abs(arqueo.diferencia),
            concepto=concepto_del_sistema(
                sesion.empresa, "SOBRANTE_CAJA" if sobra else "FALTANTE_CAJA"
            ),
            glosa=f"Cierre de la sesión {sesion.numero:06d}: {arqueo.observacion}"[:250],
            origen_tipo=Origen.ARQUEO,
            origen_id=arqueo.pk,
        )
    sesion.estado = SesionCaja.Estado.CERRADA
    sesion.cerrada_en = timezone.now()
    sesion.cerrada_por_id = usuario.pk
    sesion.cerrada_por_nombre = nombre_de(usuario)
    sesion.esperado_cierre = arqueo.esperado
    sesion.contado_cierre = arqueo.contado
    sesion.diferencia = arqueo.diferencia
    sesion.save(
        update_fields=[
            "estado",
            "cerrada_en",
            "cerrada_por_id",
            "cerrada_por_nombre",
            "esperado_cierre",
            "contado_cierre",
            "diferencia",
        ]
    )
    registrar(
        "caja.sesion_cerrada",
        recurso_tipo="sesion_caja",
        recurso_id=sesion.pk,
        empresa_id=sesion.empresa_id,
        resumen=f"Sesión {sesion.numero:06d} cerrada en {sesion.cuenta.nombre}",
        detalle={"esperado": arqueo.esperado, "contado": arqueo.contado},
    )
    return sesion


@transaction.atomic
def reabrir_sesion(sesion: SesionCaja, *, motivo: str, usuario) -> SesionCaja:
    """Reabre la última sesión cerrada de la caja y deshace su sobrante o faltante."""
    sesion = _bloquear(sesion)
    _exigir_empresa(sesion.empresa)
    motivo = " ".join((motivo or "").split())[:250]
    if not motivo:
        raise MovimientoInvalido("Indique el motivo de la reapertura.")
    if sesion.estado != SesionCaja.Estado.CERRADA:
        raise SesionInvalida("La sesión no está cerrada.")
    if sesion_abierta(sesion.cuenta) is not None:
        raise SesionInvalida("La caja ya tiene otra sesión abierta.")
    if SesionCaja.objects.filter(cuenta=sesion.cuenta, numero__gt=sesion.numero).exists():
        raise SesionInvalida("Solo se puede reabrir la última sesión de la caja.")
    cierre = sesion.arqueos.filter(tipo=TipoArqueo.CIERRE).order_by("-id").first()
    if cierre is not None:
        vigentes = MovimientoCaja.objects.filter(
            origen_tipo=Origen.ARQUEO, origen_id=cierre.pk, estado=MovimientoCaja.Estado.EMITIDO
        )
        for movimiento in vigentes:
            anular_movimiento(
                movimiento,
                motivo=f"Reapertura: {motivo}",
                desde_origen=True,
                ignorar_sesion=True,
            )
    sesion.estado = SesionCaja.Estado.ABIERTA
    sesion.cerrada_en = None
    sesion.cerrada_por_id = None
    sesion.cerrada_por_nombre = ""
    sesion.esperado_cierre = sesion.contado_cierre = sesion.diferencia = None
    sesion.reaperturas += 1
    sesion.save()
    registrar(
        "caja.sesion_reabierta",
        recurso_tipo="sesion_caja",
        recurso_id=sesion.pk,
        empresa_id=sesion.empresa_id,
        resumen=f"Sesión {sesion.numero:06d} reabierta",
        detalle={"motivo": motivo, "por": nombre_de(usuario)},
    )
    return sesion
