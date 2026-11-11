"""Registrar, pagar y anular gastos generales.

Un gasto se registra con o sin comprobante y, según su forma de pago, se paga al instante (sale
dinero de una caja o cuenta, y queda en el libro de movimientos) o queda por pagar. Todo ocurre en
una sola transacción: si algo falla, no queda nada a medias.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.auditoria.servicios import registrar
from apps.caja import servicios as caja
from apps.caja.models import Origen
from apps.compras.exceptions import CompraInvalida
from apps.compras.servicios import PagoEntrada, _validar_pago
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento import fiscal
from apps.mantenimiento.models import (
    AfectacionIGV,
    CategoriaGasto,
    Correlativo,
    EstadoRegistro,
    Proveedor,
    TipoComprobante,
)
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Estado, Sucursal

from . import recurrentes
from .exceptions import GastoInvalido, GastoNoModificable
from .models import CERO, FormaPago, Gasto, GastoRecurrente, GastoReparto, Moneda, PagoGasto

logger = logging.getLogger(__name__)

CENTAVO = Decimal("0.01")
MAXIMO = Decimal("9999999999999.99")
TOLERANCIA_IGV = Decimal("0.05")
TOPE_POR_DEFECTO = Decimal("100.00")
_SERIE = re.compile(r"[A-Za-z0-9]{1,10}")
_NUMERO = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{0,19}")
FACTURA = "01"


@dataclass(frozen=True, slots=True)
class RepartoEntrada:
    empresa: Empresa
    porcentaje: Decimal


def _exigir_empresa(empresa: Empresa) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa.pk):
        raise EmpresaNoHabilitada()


def _texto(valor, maximo: int) -> str:
    return " ".join(str(valor or "").split())[:maximo]


def _dinero(valor, campo: str, *, minimo: Decimal = CERO) -> Decimal:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise GastoInvalido(f"{campo}: indique un número válido.")
    if valor != valor.quantize(CENTAVO):
        raise GastoInvalido(f"{campo}: admite hasta 2 decimales.")
    if valor < minimo:
        raise GastoInvalido(f"{campo}: no puede ser negativo.")
    if valor > MAXIMO:
        raise GastoInvalido(f"{campo}: el valor es demasiado grande.")
    return valor


def _siguiente_numero(empresa: Empresa) -> int:
    fila, _ = Correlativo.objects.get_or_create(
        organizacion_id=empresa.organizacion_id, clave=f"gastos:gasto:{empresa.pk}"
    )
    fila = Correlativo.objects.select_for_update().get(pk=fila.pk)
    fila.ultimo += 1
    fila.save(update_fields=["ultimo"])
    return fila.ultimo


def _tope_sin_comprobante(empresa: Empresa) -> Decimal:
    configuracion = ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=empresa).first()
    return configuracion.gasto_sin_comprobante_maximo if configuracion else TOPE_POR_DEFECTO


# ---------------------------------------------------------------------------
# Validación de lo que se registra
# ---------------------------------------------------------------------------
def _validar_cabecera(
    empresa, categoria, fecha, descripcion, moneda, tipo_cambio, sucursal
) -> tuple[str, Decimal, str]:
    if categoria.organizacion_id != empresa.organizacion_id:
        raise GastoInvalido("La categoría no pertenece a la organización.")
    if categoria.estado != EstadoRegistro.ACTIVO:
        raise GastoInvalido("La categoría está inactiva.")
    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise GastoInvalido("Indique la fecha del gasto.")
    if fecha > timezone.localdate():
        raise GastoInvalido("La fecha del gasto no puede ser futura.")
    descripcion = _texto(descripcion, 250)
    if len(descripcion) < 3:
        raise GastoInvalido("Describa el gasto (qué fue y para qué).")
    if moneda not in Moneda.values:
        raise GastoInvalido("La moneda no es válida.")
    if moneda == Moneda.PEN:
        tipo_cambio = Decimal("1")
    elif (
        not isinstance(tipo_cambio, Decimal)
        or not tipo_cambio.is_finite()
        or tipo_cambio <= 0
        or tipo_cambio != tipo_cambio.quantize(Decimal("0.0001"))
        or tipo_cambio > Decimal("9999.9999")
    ):
        raise GastoInvalido("Indique el tipo de cambio (hasta 4 decimales).")
    if sucursal is not None and (
        sucursal.empresa_id != empresa.pk or sucursal.estado != Estado.ACTIVO
    ):
        raise GastoInvalido("La sucursal no es válida.")
    return descripcion, tipo_cambio, moneda


def _validar_montos(
    empresa, fecha, con_comprobante, tipo, base, igv, no_gravado
) -> tuple[Decimal, Decimal, Decimal]:
    base = _dinero(base, "Base gravada")
    igv = _dinero(igv, "IGV")
    no_gravado = _dinero(no_gravado, "Importe sin IGV")
    if con_comprobante and tipo.lleva_igv and (base or igv):
        tasa = fiscal.tasa_vigente(empresa.organizacion_id, AfectacionIGV.Impuesto.IGV, fecha)
        esperado = (base * tasa / Decimal("100")).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        if abs(igv - esperado) > TOLERANCIA_IGV:
            raise GastoInvalido(
                f"El IGV no corresponde a la base ({tasa}%): debería ser {esperado}."
            )
    elif base or igv:
        raise GastoInvalido("Este comprobante no detalla el IGV: ponga todo el importe junto.")
    total = base + igv + no_gravado
    if total <= 0:
        raise GastoInvalido("El total del gasto debe ser mayor que cero.")
    if total > MAXIMO:
        raise GastoInvalido("El total del gasto es demasiado grande.")
    return base, igv, no_gravado


def _validar_comprobante(empresa, tipo, serie, numero, proveedor, fecha) -> tuple[str, str]:
    if tipo is None:
        raise GastoInvalido("Elija el tipo de comprobante.")
    if tipo.organizacion_id != empresa.organizacion_id or tipo.estado != EstadoRegistro.ACTIVO:
        raise GastoInvalido("El tipo de comprobante no es válido.")
    if not tipo.aplica_compras:
        raise GastoInvalido("Ese tipo de comprobante no se usa en gastos ni compras.")
    serie = _texto(serie, 10).upper()
    numero = _texto(numero, 20).upper()
    if serie and not _SERIE.fullmatch(serie):
        raise GastoInvalido("La serie solo lleva letras y números (hasta 10).")
    if not numero or not _NUMERO.fullmatch(numero):
        raise GastoInvalido("Indique el número del comprobante (letras, números y guion).")
    if proveedor is None and tipo.codigo == FACTURA:
        raise GastoInvalido("Una factura necesita el proveedor (su RUC).")
    if proveedor is not None and proveedor.organizacion_id != empresa.organizacion_id:
        raise GastoInvalido("El proveedor no pertenece a la organización.")
    if proveedor is not None and proveedor.estado != EstadoRegistro.ACTIVO:
        raise GastoInvalido("El proveedor está inactivo.")
    if proveedor is not None:
        repetido = Gasto.objects.filter(
            empresa=empresa,
            proveedor=proveedor,
            tipo_comprobante=tipo,
            comprobante_serie=serie,
            comprobante_numero=numero,
            estado=Gasto.Estado.EMITIDO,
        ).exists()
        if repetido:
            raise GastoInvalido("Ese comprobante de ese proveedor ya está registrado como gasto.")
    return serie, numero


def _validar_pagos(
    empresa, pagos: list[PagoEntrada], moneda: str, fecha: date
) -> list[PagoEntrada]:
    resultado = []
    for i, p in enumerate(pagos, start=1):
        etiqueta = f"Pago {i}" if len(pagos) > 1 else "Pago"
        try:
            resultado.append(_validar_pago(empresa, p, moneda, fecha, etiqueta))
        except CompraInvalida as e:
            raise GastoInvalido(str(e)) from None
    return resultado


def _repartir(
    empresa: Empresa, total: Decimal, reparto: list[RepartoEntrada] | None
) -> list[tuple[Empresa, Decimal, Decimal]]:
    """Valida el reparto y devuelve ``(empresa, porcentaje, monto)``; vacío si no se reparte."""
    if not reparto:
        return []
    contexto = obtener_contexto_requerido()
    vistas: set[int] = set()
    suma = CERO
    for r in reparto:
        e = r.empresa
        if e.pk in vistas:
            raise GastoInvalido("Una empresa aparece dos veces en el reparto.")
        vistas.add(e.pk)
        if e.organizacion_id != empresa.organizacion_id or e.estado != Estado.ACTIVO:
            raise GastoInvalido("Una empresa del reparto no es válida.")
        if not contexto.empresa_habilitada(e.pk):
            raise EmpresaNoHabilitada()
        pct = r.porcentaje
        if (
            not isinstance(pct, Decimal)
            or not pct.is_finite()
            or pct != pct.quantize(CENTAVO)
            or not (CERO < pct <= Decimal("100"))
        ):
            raise GastoInvalido("Cada porcentaje del reparto va de 0,01 a 100 (hasta 2 decimales).")
        suma += pct
    if suma != Decimal("100"):
        raise GastoInvalido(f"El reparto suma {suma}%: debe sumar exactamente 100%.")
    if len(reparto) == 1 and reparto[0].empresa.pk == empresa.pk:
        return []  # todo para la titular: es lo mismo que no repartir
    montos = [
        (total * r.porcentaje / Decimal("100")).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        for r in reparto
    ]
    # Lo que sobra o falta por redondeo se lo lleva la empresa con la mayor parte.
    montos[max(range(len(montos)), key=lambda i: reparto[i].porcentaje)] += total - sum(montos)
    return [(r.empresa, r.porcentaje, m) for r, m in zip(reparto, montos, strict=True)]


# ---------------------------------------------------------------------------
# Registrar
# ---------------------------------------------------------------------------
@transaction.atomic
def registrar_gasto(
    *,
    empresa: Empresa,
    categoria: CategoriaGasto,
    fecha: date,
    descripcion: str,
    con_comprobante: bool,
    tipo_comprobante: TipoComprobante | None = None,
    comprobante_serie: str = "",
    comprobante_numero: str = "",
    proveedor: Proveedor | None = None,
    base_gravada: Decimal = CERO,
    igv: Decimal = CERO,
    no_gravado: Decimal = CERO,
    gastado_por: str = "",
    sucursal: Sucursal | None = None,
    observacion: str = "",
    moneda: str = Moneda.PEN,
    tipo_cambio: Decimal | None = None,
    forma_pago: str = FormaPago.CONTADO,
    fecha_vencimiento: date | None = None,
    pagos: list[PagoEntrada] | None = None,
    reparto: list[RepartoEntrada] | None = None,
    puede_exceder_tope: bool = False,
    recurrente: GastoRecurrente | None = None,
) -> Gasto:
    """Registra un gasto con o sin comprobante, al contado o por pagar."""
    _exigir_empresa(empresa)
    descripcion, tipo_cambio, moneda = _validar_cabecera(
        empresa, categoria, fecha, descripcion, moneda, tipo_cambio, sucursal
    )
    if forma_pago not in FormaPago.values:
        raise GastoInvalido("La forma de pago no es válida.")
    if not isinstance(con_comprobante, bool):
        raise GastoInvalido("Indique si el gasto tiene comprobante.")

    if con_comprobante:
        serie, numero = _validar_comprobante(
            empresa, tipo_comprobante, comprobante_serie, comprobante_numero, proveedor, fecha
        )
        quien = _texto(gastado_por, 120)
    else:
        if tipo_comprobante or comprobante_serie or comprobante_numero or proveedor:
            raise GastoInvalido(
                "Un gasto sin comprobante no lleva datos de comprobante ni proveedor."
            )
        serie = numero = ""
        quien = _texto(gastado_por, 120)
        if len(quien) < 2:
            raise GastoInvalido("Indique quién hizo el gasto.")
        if base_gravada or igv:
            raise GastoInvalido("Un gasto sin comprobante lleva solo el importe total.")
    base, igv, no_gravado = _validar_montos(
        empresa, fecha, con_comprobante, tipo_comprobante, base_gravada, igv, no_gravado
    )
    total = base + igv + no_gravado

    if not con_comprobante and not puede_exceder_tope:
        tope = _tope_sin_comprobante(empresa)
        if total * tipo_cambio > tope:
            raise GastoInvalido(
                f"Un gasto sin comprobante no puede pasar de S/ {tope:,.2f}. "
                "Pida el comprobante o a quien pueda autorizarlo."
            )

    if forma_pago == FormaPago.CONTADO:
        if not pagos:
            raise GastoInvalido("Indique con qué se pagó el gasto.")
        if fecha_vencimiento is not None:
            raise GastoInvalido("Un gasto al contado no tiene vencimiento.")
        validos = _validar_pagos(empresa, pagos, moneda, fecha)
        if sum((p.monto for p in validos), CERO) != total:
            raise GastoInvalido("Los pagos deben sumar exactamente el total del gasto.")
    else:
        if pagos:
            raise GastoInvalido("Un gasto por pagar se paga después, con la opción de pagar.")
        if not isinstance(fecha_vencimiento, date) or fecha_vencimiento < fecha:
            raise GastoInvalido("Indique el vencimiento (no puede ser anterior al gasto).")
        validos = []

    partes = _repartir(empresa, total, reparto)
    if recurrente is not None:
        recurrentes.exigir_utilizable(empresa, recurrente)

    gasto = Gasto.objects.create(
        empresa=empresa,
        numero=_siguiente_numero(empresa),
        categoria=categoria,
        fecha=fecha,
        descripcion=descripcion,
        observacion=_texto(observacion, 250),
        sucursal=sucursal,
        con_comprobante=con_comprobante,
        tipo_comprobante=tipo_comprobante if con_comprobante else None,
        comprobante_serie=serie,
        comprobante_numero=numero,
        proveedor=proveedor if con_comprobante else None,
        gastado_por=quien,
        moneda=moneda,
        tipo_cambio=tipo_cambio,
        base_gravada=base,
        igv=igv,
        no_gravado=no_gravado,
        total=total,
        forma_pago=forma_pago,
        fecha_vencimiento=fecha_vencimiento,
        recurrente=recurrente,
    )
    if recurrente is not None:
        recurrentes.avanzar(recurrente, registrada=fecha)
    for destino, porcentaje, monto in partes:
        GastoReparto.objects.create(
            empresa=destino, gasto=gasto, porcentaje=porcentaje, monto=monto
        )
    _crear_pagos(gasto, validos)
    registrar(
        "gastos.gasto_registrado",
        recurso_tipo="gasto",
        recurso_id=gasto.pk,
        empresa_id=empresa.pk,
        resumen=f"Gasto N° {gasto.numero:06d}: {descripcion} ({moneda} {total})",
        detalle={
            "categoria": categoria.nombre,
            "con_comprobante": con_comprobante,
            "forma_pago": forma_pago,
            "repartido": bool(partes),
        },
    )
    return gasto


def _detalle_cambio(pago: PagoGasto, moneda: str) -> str:
    if pago.tipo_cambio is None:
        return ""
    return f" · T.C. {pago.tipo_cambio} ({moneda} {pago.monto} → {pago.monto_cuenta})"


def _crear_pagos(gasto: Gasto, pagos: list[PagoEntrada]) -> list[PagoGasto]:
    creados = []
    for p in pagos:
        pago = PagoGasto.objects.create(
            empresa=gasto.empresa,
            gasto=gasto,
            medio_pago=p.medio_pago,
            cuenta=p.cuenta,
            fecha=p.fecha,
            monto=p.monto,
            referencia=p.referencia,
            tipo_cambio=p.tipo_cambio,
            monto_cuenta=p.monto_cuenta,
        )
        caja.registrar_pago_de_gasto(
            empresa=gasto.empresa,
            cuenta=p.cuenta,
            monto=pago.monto_en_cuenta,
            fecha=p.fecha,
            referencia=p.referencia,
            glosa=(
                f"Gasto N° {gasto.numero:06d} · {gasto.descripcion}"
                f"{_detalle_cambio(pago, gasto.moneda)}"
            )[:250],
            pago_id=pago.pk,
            medio_pago=p.medio_pago,
            aporte_socio=p.aporte_socio,
        )
        creados.append(pago)
    return creados


# ---------------------------------------------------------------------------
# Pagar lo que quedó por pagar
# ---------------------------------------------------------------------------
@transaction.atomic
def pagar_gasto(gasto: Gasto, pagos: list[PagoEntrada]) -> list[PagoGasto]:
    """Paga todo o parte de un gasto pendiente, con uno o varios métodos."""
    gasto = Gasto.objects.select_for_update().select_related("empresa").get(pk=gasto.pk)
    _exigir_empresa(gasto.empresa)
    if gasto.estado != Gasto.Estado.EMITIDO:
        raise GastoNoModificable("El gasto está anulado: no se puede pagar.")
    if not pagos:
        raise GastoInvalido("Indique con qué se paga.")
    saldo = gasto.saldo()
    if saldo <= 0:
        raise GastoNoModificable("Este gasto ya está pagado.")
    validos = _validar_pagos(gasto.empresa, pagos, gasto.moneda, timezone.localdate())
    for p in validos:
        if p.fecha < gasto.fecha:
            raise GastoInvalido("El pago no puede ser anterior a la fecha del gasto.")
    if sum((p.monto for p in validos), CERO) > saldo:
        raise GastoInvalido(f"Los pagos pasan de lo que falta pagar ({gasto.moneda} {saldo}).")
    creados = _crear_pagos(gasto, validos)
    registrar(
        "gastos.gasto_pagado",
        recurso_tipo="gasto",
        recurso_id=gasto.pk,
        empresa_id=gasto.empresa_id,
        resumen=f"Pago del gasto N° {gasto.numero:06d}",
        detalle={"pagos": len(creados), "monto": sum((p.monto for p in validos), CERO)},
    )
    return creados


# ---------------------------------------------------------------------------
# Anular
# ---------------------------------------------------------------------------
def _anular_pago(pago: PagoGasto, motivo: str) -> None:
    caja.anular_por_origen(Origen.PAGO_GASTO, pago.pk, motivo=motivo)
    pago.anulado = True
    pago.anulado_en = timezone.now()
    pago.motivo_anulacion = motivo
    pago.save(update_fields=["anulado", "anulado_en", "motivo_anulacion"])


@transaction.atomic
def anular_pago(pago: PagoGasto, *, motivo: str) -> PagoGasto:
    """Anula un pago: el dinero vuelve a su caja y el gasto vuelve a deber ese monto."""
    pago = PagoGasto.objects.select_for_update().select_related("gasto", "empresa").get(pk=pago.pk)
    _exigir_empresa(pago.empresa)
    motivo = _texto(motivo, 250)
    if not motivo:
        raise GastoInvalido("Indique el motivo de la anulación.")
    if pago.anulado:
        raise GastoNoModificable("Ese pago ya está anulado.")
    if pago.gasto.estado != Gasto.Estado.EMITIDO:
        raise GastoNoModificable("El gasto está anulado.")
    if pago.gasto.forma_pago == FormaPago.CONTADO:
        raise GastoNoModificable("Un gasto al contado se corrige anulando el gasto completo.")
    _anular_pago(pago, f"Pago anulado: {motivo}")
    registrar(
        "gastos.pago_anulado",
        recurso_tipo="gasto",
        recurso_id=pago.gasto_id,
        empresa_id=pago.empresa_id,
        resumen=f"Pago del gasto N° {pago.gasto.numero:06d} anulado",
        detalle={"motivo": motivo, "monto": pago.monto},
    )
    return pago


@transaction.atomic
def anular_gasto(gasto: Gasto, *, motivo: str) -> Gasto:
    """Anula el gasto y devuelve el dinero de sus pagos a las cajas de donde salió."""
    gasto = Gasto.objects.select_for_update().select_related("empresa").get(pk=gasto.pk)
    _exigir_empresa(gasto.empresa)
    motivo_limpio = _texto(motivo, 250)
    gasto.anular(motivo=motivo_limpio)  # valida el motivo y que no esté anulado
    for pago in PagoGasto.objects.filter(gasto=gasto, anulado=False):
        _anular_pago(pago, f"Gasto anulado: {motivo_limpio}")
    registrar(
        "gastos.gasto_anulado",
        recurso_tipo="gasto",
        recurso_id=gasto.pk,
        empresa_id=gasto.empresa_id,
        resumen=f"Gasto N° {gasto.numero:06d} anulado",
        detalle={"motivo": motivo_limpio, "total": gasto.total},
    )
    return gasto
