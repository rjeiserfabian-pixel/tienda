"""Mostrador compartido: el efectivo de dos empresas en un solo cajón, contado una sola vez.

Cuando dos empresas venden desde el mismo local, cada una tiene su caja de efectivo (cada RUC
maneja su dinero) pero el cajón físico es uno. Las cajas de un mismo mostrador son las de
sucursales de distintas empresas con el mismo ``local_fisico``. Al contar o cerrar, se cuenta el
cajón UNA vez contra la suma de lo que espera el sistema en cada caja:

* Si cuadra, todas cuadran.
* Si sobra o falta, la diferencia se reparte entre las cajas en proporción a lo que cada una
  esperaba (cada empresa asume la parte que le corresponde del efectivo que manejó).

Cada caja conserva su propio arqueo y su propio movimiento de sobrante o faltante; los arqueos
del mismo conteo comparten un ``grupo``.
"""

import logging
import uuid
from decimal import ROUND_FLOOR, Decimal

from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import CuentaFinanciera, EstadoRegistro

from .exceptions import MovimientoInvalido, SesionInvalida
from .models import ArqueoCaja, SesionCaja, TipoArqueo
from .servicios import CERO, _exigir_empresa, saldo_de
from .sesiones import (
    _bloquear,
    _cerrar_con_arqueo,
    _exigir_responsable,
    abrir_sesion,
    contar,
    nombre_de,
    sesion_abierta,
)

logger = logging.getLogger(__name__)

CENTIMO = Decimal("0.01")


def hermanas_de(sesion: SesionCaja) -> list[SesionCaja]:
    """Las sesiones ABIERTAS de las otras empresas que comparten el mostrador de ``sesion``."""
    # Se lee de nuevo: el local físico puede haber cambiado desde que se cargó la sesión.
    cuenta = CuentaFinanciera.objects.select_related("sucursal").get(pk=sesion.cuenta_id)
    sucursal = cuenta.sucursal
    if (
        sucursal is None
        or not sucursal.local_fisico
        or cuenta.tipo != CuentaFinanciera.Tipo.CAJA
        or cuenta.rol_caja == CuentaFinanciera.RolCaja.CAJA_CHICA
    ):
        return []
    return list(
        SesionCaja.objects.sin_ambito()
        .select_related("cuenta", "empresa")
        .filter(
            estado=SesionCaja.Estado.ABIERTA,
            empresa__organizacion_id=sesion.empresa.organizacion_id,
            cuenta__tipo=CuentaFinanciera.Tipo.CAJA,
            cuenta__moneda=cuenta.moneda,
            cuenta__estado=EstadoRegistro.ACTIVO,
            cuenta__sucursal__local_fisico=sucursal.local_fisico,
        )
        .exclude(empresa_id=sesion.empresa_id)
        .exclude(cuenta__rol_caja=CuentaFinanciera.RolCaja.CAJA_CHICA)
        .order_by("-empresa__es_principal", "empresa_id", "id")
    )


def repartir_diferencia(diferencia: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte lo que sobra o falta en proporción a ``pesos``, en céntimos exactos (con signo).

    Método del mayor resto: cada parte se redondea hacia abajo al céntimo y los céntimos que
    faltan van a las partes con mayor resto. Sin pesos positivos todo va a la primera.
    """
    signo = -1 if diferencia < 0 else 1
    monto = abs(diferencia)
    pesos = [max(p, CERO) for p in pesos]
    total = sum(pesos, CERO)
    if total <= 0:
        partes = [monto] + [CERO] * (len(pesos) - 1)
    else:
        cuotas = [monto * p / total for p in pesos]
        partes = [c.quantize(CENTIMO, rounding=ROUND_FLOOR) for c in cuotas]
        faltan = int(((monto - sum(partes, CERO)) / CENTIMO).to_integral_value())
        orden = sorted(range(len(pesos)), key=lambda i: (-(cuotas[i] - partes[i]), i))
        for i in orden[:faltan]:
            partes[i] += CENTIMO
    return [signo * p for p in partes]


def _preparar(sesion: SesionCaja, usuario, supervisor: bool) -> list[SesionCaja]:
    """Las sesiones del mostrador (la pedida primero), bloqueadas y verificadas."""
    base = _bloquear(sesion)
    hermanas = hermanas_de(base)
    if not hermanas:
        raise SesionInvalida(
            "Esta caja no comparte mostrador con otra empresa que tenga su caja abierta."
        )
    todas = [base] + [_bloquear(h) for h in hermanas]
    for s in todas:
        _exigir_empresa(s.empresa)
        if s.estado != SesionCaja.Estado.ABIERTA:
            raise SesionInvalida("Una de las sesiones del mostrador ya está cerrada.")
        _exigir_responsable(s, usuario, supervisor=supervisor)
    return todas


def _arqueos(
    sesiones: list[SesionCaja], *, tipo, conteo, observacion, usuario
) -> tuple[list[ArqueoCaja], Decimal, Decimal]:
    """Un arqueo por caja a partir de UN conteo del cajón: ``(arqueos, esperado, contado)``."""
    limpio, contado = contar(conteo, sesiones[0].cuenta.moneda)
    esperados = [saldo_de(s.cuenta) for s in sesiones]
    esperado = sum(esperados, CERO)
    partes = repartir_diferencia(contado - esperado, esperados)
    observacion = " ".join((observacion or "").split())[:250]
    if partes and any(p != CERO for p in partes) and not observacion and tipo == TipoArqueo.CIERRE:
        raise MovimientoInvalido("Explique la diferencia en el campo de observación.")
    grupo = uuid.uuid4()
    arqueos = []
    for posicion, (s, e, parte) in enumerate(zip(sesiones, esperados, partes, strict=True)):
        arqueos.append(
            ArqueoCaja.objects.create(
                empresa=s.empresa,
                sesion=s,
                tipo=tipo,
                esperado=e,
                contado=e + parte,
                diferencia=parte,
                conteo=limpio if posicion == 0 else {},
                grupo=grupo,
                observacion=observacion,
                hecho_por_id=usuario.pk,
                hecho_por_nombre=nombre_de(usuario),
            )
        )
    return arqueos, esperado, contado


@transaction.atomic
def arquear_mostrador(
    sesion: SesionCaja, *, conteo: dict, usuario, observacion: str = "", supervisor: bool = False
) -> list[ArqueoCaja]:
    """Cuenta el cajón compartido sin cerrar: un arqueo por caja, con un solo conteo."""
    sesiones = _preparar(sesion, usuario, supervisor)
    arqueos, esperado, contado = _arqueos(
        sesiones, tipo=TipoArqueo.PARCIAL, conteo=conteo, observacion=observacion, usuario=usuario
    )
    registrar(
        "caja.arqueo_mostrador_hecho",
        recurso_tipo="sesion_caja",
        recurso_id=sesion.pk,
        empresa_id=sesion.empresa_id,
        resumen=f"Arqueo del mostrador compartido: diferencia {contado - esperado}",
        detalle={"esperado": esperado, "contado": contado, "cajas": [s.pk for s in sesiones]},
    )
    return arqueos


@transaction.atomic
def cerrar_mostrador(
    sesion: SesionCaja, *, conteo: dict, usuario, observacion: str = "", supervisor: bool = False
) -> list[SesionCaja]:
    """Cuenta el cajón compartido y cierra las cajas de todas las empresas que lo usan."""
    sesiones = _preparar(sesion, usuario, supervisor)
    arqueos, esperado, contado = _arqueos(
        sesiones, tipo=TipoArqueo.CIERRE, conteo=conteo, observacion=observacion, usuario=usuario
    )
    cerradas = [
        _cerrar_con_arqueo(s, arqueo, usuario) for s, arqueo in zip(sesiones, arqueos, strict=True)
    ]
    registrar(
        "caja.mostrador_cerrado",
        recurso_tipo="sesion_caja",
        recurso_id=sesion.pk,
        empresa_id=sesion.empresa_id,
        resumen=f"Mostrador compartido cerrado: diferencia {contado - esperado}",
        detalle={"esperado": esperado, "contado": contado, "cajas": [s.pk for s in sesiones]},
    )
    return cerradas


def cajas_hermanas(cuenta: CuentaFinanciera) -> list[CuentaFinanciera]:
    """Las cajas de efectivo de otras empresas en el mismo local físico que ``cuenta``."""
    cuenta = CuentaFinanciera.objects.select_related("sucursal", "empresa").get(pk=cuenta.pk)
    sucursal = cuenta.sucursal
    if (
        sucursal is None
        or not sucursal.local_fisico
        or cuenta.tipo != CuentaFinanciera.Tipo.CAJA
        or cuenta.rol_caja == CuentaFinanciera.RolCaja.CAJA_CHICA
    ):
        return []
    return list(
        CuentaFinanciera.objects.sin_ambito()
        .select_related("empresa")
        .filter(
            empresa__organizacion_id=cuenta.empresa.organizacion_id,
            tipo=CuentaFinanciera.Tipo.CAJA,
            moneda=cuenta.moneda,
            estado=EstadoRegistro.ACTIVO,
            sucursal__local_fisico=sucursal.local_fisico,
        )
        .exclude(empresa_id=cuenta.empresa_id)
        .exclude(rol_caja=CuentaFinanciera.RolCaja.CAJA_CHICA)
        .order_by("-empresa__es_principal", "empresa_id", "id")
    )


@transaction.atomic
def abrir_mostrador(*, empresa, cuenta: CuentaFinanciera, usuario, **datos) -> list[SesionCaja]:
    """Abre la caja pedida y, sin fondo, las cerradas de las otras empresas del mismo local.

    Así quien atiende el mostrador empieza el turno de todas las cajas del cajón de una vez.
    """
    abiertas = [abrir_sesion(empresa=empresa, cuenta=cuenta, usuario=usuario, **datos)]
    for hermana in cajas_hermanas(cuenta):
        if sesion_abierta(hermana) is None:
            abiertas.append(abrir_sesion(empresa=hermana.empresa, cuenta=hermana, usuario=usuario))
    return abiertas
