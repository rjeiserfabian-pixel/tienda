"""Ficha laboral, contratos y sueldos de los trabajadores.

Reglas:

* El trabajador es el de «Personal» (cada uno es de UNA empresa); aquí se le agrega lo laboral.
* Un trabajador tiene a lo más UN contrato vigente. Para cambiar de contrato se finaliza el actual
  (con fecha y motivo) y se registra otro; un contrato finalizado ya no se toca.
* El sueldo vive en ``CambioSueldo`` (monto + vigente desde): el aumento no borra el anterior.
* La cuenta bancaria va cifrada y exige el permiso de sueldos; la auditoría deja constancia de QUÉ
  campos cambiaron pero nunca de sueldos ni cuentas.
"""

import logging
import re
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditoria.servicios import diferencia, registrar
from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.tenant import obtener_contexto_requerido
from apps.mantenimiento.models import EstadoRegistro, Personal

from . import catalogos
from .models import (
    CambioSueldo,
    CodigoParametro,
    ContratoLaboral,
    DatosLaborales,
    EstadoContrato,
    MetodoPago,
    RegimenLaboral,
    SistemaPension,
    TipoContrato,
)

logger = logging.getLogger(__name__)

AVISO_VENCIMIENTO = 30  # días antes del fin de un contrato a plazo fijo en que se avisa
MAX_DIAS_ADELANTO = 366  # un aumento puede programarse hasta con un año de anticipación

CAMPOS_COMUNES = (
    "sexo",
    "nacionalidad",
    "sistema_pension",
    "afp",
    "tipo_comision",
    "cuspp",
    "asignacion_familiar",
    "paga_renta_5ta",
    "subsidio_descanso_medico",
    "metodo_pago",
)
CAMPOS_BANCARIOS = ("banco", "numero_cuenta", "cci")
_CUENTA = re.compile(r"[0-9\-]{4,30}")
_CCI = re.compile(r"\d{20}")


class ErrorTrabajador(ValidationError):
    """Un dato de la ficha o del contrato no es válido (se muestra junto al campo)."""


def _exigir_empresa(empresa_id: int) -> None:
    if not obtener_contexto_requerido().empresa_habilitada(empresa_id):
        raise EmpresaNoHabilitada()


def _error(campo: str, mensaje: str) -> ErrorTrabajador:
    return ErrorTrabajador({campo: mensaje})


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def contrato_vigente(personal: Personal) -> ContratoLaboral | None:
    return (
        ContratoLaboral.objects.select_related("regimen")
        .filter(personal=personal, estado=EstadoContrato.VIGENTE)
        .first()
    )


def sueldo_vigente(contrato: ContratoLaboral, fecha: date | None = None) -> Decimal | None:
    """El sueldo del contrato en esa fecha (``None`` si todavía no rige ninguno)."""
    fecha = fecha or timezone.localdate()
    cambio = (
        CambioSueldo.objects.filter(contrato=contrato, vigente_desde__lte=fecha)
        .order_by("-vigente_desde", "-id")
        .first()
    )
    return None if cambio is None else cambio.monto


def dias_para_vencer(contrato: ContratoLaboral, hoy: date | None = None) -> int | None:
    """Días que faltan para que venza un contrato vigente (negativo = ya venció)."""
    if not contrato.vigente or contrato.fecha_fin is None:
        return None
    return (contrato.fecha_fin - (hoy or timezone.localdate())).days


def faltantes_ficha(personal: Personal, datos: DatosLaborales | None, contrato) -> list[str]:
    """Lo que falta para poder calcularle la planilla (vacío = ficha completa)."""
    falta = []
    if contrato is None:
        falta.append("Contrato vigente")
    if datos is None:
        return [*falta, "Datos laborales"]
    if datos.sistema_pension == SistemaPension.NINGUNO:
        falta.append("Sistema de pensión (ONP o AFP)")
    elif datos.sistema_pension == SistemaPension.AFP and not datos.cuspp:
        falta.append("CUSPP")
    if datos.metodo_pago == MetodoPago.TRANSFERENCIA and not (datos.banco and datos.numero_cuenta):
        falta.append("Banco y cuenta (se le paga por transferencia)")
    return falta


# ---------------------------------------------------------------------------
# Datos laborales
# ---------------------------------------------------------------------------
@transaction.atomic
def guardar_datos_laborales(
    personal: Personal, datos: dict, *, puede_cuenta: bool
) -> DatosLaborales:
    """Crea o actualiza los datos laborales. La cuenta solo la cambia quien tiene el permiso."""
    _exigir_empresa(personal.empresa_id)
    personal = Personal.objects.select_for_update().get(pk=personal.pk)
    if any(datos.get(c) for c in CAMPOS_BANCARIOS) and not puede_cuenta:
        raise _error("banco", "No tienes permiso para cambiar la cuenta bancaria.")
    if datos.get("numero_cuenta") and not _CUENTA.fullmatch(datos["numero_cuenta"]):
        raise _error("numero_cuenta", "Use de 4 a 30 números (y guiones).")
    if datos.get("cci") and not _CCI.fullmatch(datos["cci"]):
        raise _error("cci", "El CCI tiene 20 dígitos.")

    fila = DatosLaborales.objects.select_for_update().filter(personal=personal).first()
    nueva = fila is None
    if nueva:
        fila = DatosLaborales(empresa=personal.empresa, personal=personal)
    antes = {c: str(getattr(fila, c)) for c in (*CAMPOS_COMUNES, "banco")}
    for campo in CAMPOS_COMUNES:
        if campo in datos:
            setattr(fila, campo, datos[campo])
    # Quien deja la AFP no arrastra sus datos: se limpian solos.
    if fila.sistema_pension != SistemaPension.AFP:
        fila.afp = fila.tipo_comision = fila.cuspp = ""
    for campo in CAMPOS_BANCARIOS:
        if datos.get(campo):  # vacío o ausente = se conserva la que ya estaba
            setattr(fila, campo, datos[campo])
    try:
        fila.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise ErrorTrabajador(error.message_dict) from None
    fila.save()
    cambios = diferencia(antes, {c: str(getattr(fila, c)) for c in antes})
    cuenta = [c for c in ("numero_cuenta", "cci") if datos.get(c)]
    if nueva or cambios or cuenta:
        registrar(
            "rrhh.datos_laborales_editados",
            recurso_tipo="personal",
            recurso_id=personal.pk,
            empresa_id=personal.empresa_id,
            resumen=f"Datos laborales de {personal.nombre_completo} "
            f"{'registrados' if nueva else 'modificados'}",
            # La cuenta nunca se detalla: solo se anota que se cambió.
            detalle={
                **{c: v for c, v in cambios.items() if c != "banco"},
                "cuenta_cambiada": bool(cuenta),
            },
        )
    return fila


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
def _advertencias_sueldo(personal: Personal, tipo: str, monto: Decimal, fecha: date) -> list[str]:
    """Avisos que no impiden guardar (p. ej. un sueldo por debajo del mínimo)."""
    if tipo in (TipoContrato.TIEMPO_PARCIAL, TipoContrato.PRACTICAS):
        return []
    rmv = catalogos.valor_vigente(personal.empresa.organizacion_id, CodigoParametro.RMV, fecha)
    if rmv is not None and monto < rmv:
        return [f"El sueldo es menor que la remuneración mínima vigente (S/ {rmv:,.2f})."]
    return []


@transaction.atomic
def crear_contrato(
    personal: Personal,
    *,
    regimen: RegimenLaboral,
    tipo_contrato: str,
    categoria: str,
    cargo: str,
    fecha_inicio: date,
    fecha_fin: date | None,
    sueldo: Decimal,
    observacion: str = "",
) -> tuple[ContratoLaboral, list[str]]:
    """Registra un contrato con su primer sueldo. Devuelve el contrato y los avisos."""
    _exigir_empresa(personal.empresa_id)
    personal = Personal.objects.select_for_update().select_related("empresa").get(pk=personal.pk)
    if personal.estado != EstadoRegistro.ACTIVO:
        raise _error("personal", "El trabajador está inactivo: reactívalo antes de contratarlo.")
    if regimen.estado != EstadoRegistro.ACTIVO:
        raise _error("regimen", "Ese régimen está inactivo.")
    if ContratoLaboral.objects.filter(personal=personal, estado=EstadoContrato.VIGENTE).exists():
        raise _error(
            "personal",
            "El trabajador ya tiene un contrato vigente: finalícelo antes de registrar otro.",
        )
    anterior = (
        ContratoLaboral.objects.filter(personal=personal, estado=EstadoContrato.FINALIZADO)
        .order_by("-fecha_cese")
        .first()
    )
    if anterior and anterior.fecha_cese >= fecha_inicio:
        raise _error(
            "fecha_inicio",
            f"Debe ser posterior al cese del contrato anterior ({anterior.fecha_cese:%d/%m/%Y}).",
        )
    contrato = ContratoLaboral(
        empresa=personal.empresa,
        personal=personal,
        regimen=regimen,
        tipo_contrato=tipo_contrato,
        categoria=categoria,
        cargo=cargo,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        observacion=" ".join((observacion or "").split()),
    )
    primero = CambioSueldo(
        empresa=personal.empresa,
        contrato=contrato,
        monto=sueldo,
        vigente_desde=fecha_inicio,
        motivo="Sueldo inicial",
    )
    try:
        contrato.full_clean(validate_unique=False, validate_constraints=False)
        with transaction.atomic():
            contrato.save()
        primero.contrato = contrato
        primero.full_clean(validate_unique=False, validate_constraints=False)
        primero.save()
    except ValidationError as error:
        raise ErrorTrabajador(error.message_dict) from None
    except IntegrityError:
        raise _error("personal", "El trabajador ya tiene un contrato vigente.") from None
    registrar(
        "rrhh.contrato_creado",
        recurso_tipo="contrato_laboral",
        recurso_id=contrato.pk,
        empresa_id=contrato.empresa_id,
        resumen=f"Contrato de {personal.nombre_completo} registrado "
        f"({contrato.get_tipo_contrato_display()})",
        detalle={"regimen": regimen.codigo, "inicio": fecha_inicio, "fin": fecha_fin},
    )
    return contrato, _advertencias_sueldo(personal, tipo_contrato, sueldo, fecha_inicio)


@transaction.atomic
def actualizar_contrato(contrato: ContratoLaboral, datos: dict) -> ContratoLaboral:
    """Corrige un contrato vigente. El inicio y el sueldo no se tocan aquí (rompe el historial)."""
    _exigir_empresa(contrato.empresa_id)
    contrato = (
        ContratoLaboral.objects.select_for_update().select_related("regimen").get(pk=contrato.pk)
    )
    if not contrato.vigente:
        raise _error("estado", "Un contrato finalizado ya no se modifica.")
    antes = {c: str(getattr(contrato, c)) for c in datos}
    for campo, valor in datos.items():
        setattr(contrato, campo, valor)
    try:
        contrato.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as error:
        raise ErrorTrabajador(error.message_dict) from None
    if (
        contrato.regimen_id
        and contrato.regimen.estado != EstadoRegistro.ACTIVO
        and "regimen" in datos
    ):
        raise _error("regimen", "Ese régimen está inactivo.")
    contrato.save(update_fields=list(datos))
    cambios = diferencia(antes, {c: str(getattr(contrato, c)) for c in datos})
    if cambios:
        registrar(
            "rrhh.contrato_editado",
            recurso_tipo="contrato_laboral",
            recurso_id=contrato.pk,
            empresa_id=contrato.empresa_id,
            resumen=f"Contrato {contrato.pk} modificado",
            detalle=cambios,
        )
    return contrato


@transaction.atomic
def finalizar_contrato(
    contrato: ContratoLaboral, *, fecha_cese: date, motivo: str
) -> ContratoLaboral:
    """Termina el contrato (renuncia, despido, vencimiento…). No se puede deshacer."""
    _exigir_empresa(contrato.empresa_id)
    contrato = ContratoLaboral.objects.select_for_update().get(pk=contrato.pk)
    motivo = " ".join((motivo or "").split())
    if not contrato.vigente:
        raise _error("estado", "El contrato ya está finalizado.")
    if not motivo:
        raise _error("motivo", "Indique el motivo del cese.")
    if fecha_cese < contrato.fecha_inicio:
        raise _error("fecha_cese", "No puede ser anterior al inicio del contrato.")
    if fecha_cese > timezone.localdate():
        raise _error("fecha_cese", "La fecha del cese no puede ser futura.")
    contrato.estado = EstadoContrato.FINALIZADO
    contrato.fecha_cese = fecha_cese
    contrato.motivo_cese = motivo[:200]
    contrato.save(update_fields=["estado", "fecha_cese", "motivo_cese"])
    registrar(
        "rrhh.contrato_finalizado",
        recurso_tipo="contrato_laboral",
        recurso_id=contrato.pk,
        empresa_id=contrato.empresa_id,
        resumen=f"Contrato {contrato.pk} finalizado el {fecha_cese:%d/%m/%Y}",
        detalle={"motivo": contrato.motivo_cese},
    )
    return contrato


@transaction.atomic
def registrar_cambio_sueldo(
    contrato: ContratoLaboral, *, monto: Decimal, vigente_desde: date, motivo: str = ""
) -> tuple[CambioSueldo, list[str]]:
    """Registra un sueldo nuevo desde una fecha (el anterior se conserva en el historial)."""
    _exigir_empresa(contrato.empresa_id)
    contrato = (
        ContratoLaboral.objects.select_for_update()
        .select_related("personal__empresa")
        .get(pk=contrato.pk)
    )
    if not contrato.vigente:
        raise _error("estado", "El contrato está finalizado: no se le cambia el sueldo.")
    if vigente_desde > timezone.localdate() + timedelta(days=MAX_DIAS_ADELANTO):
        raise _error("vigente_desde", "Esa fecha está demasiado lejos.")
    cambio = CambioSueldo(
        empresa=contrato.empresa,
        contrato=contrato,
        monto=monto,
        vigente_desde=vigente_desde,
        motivo=" ".join((motivo or "").split())[:100],
    )
    try:
        cambio.full_clean(validate_unique=False, validate_constraints=False)
        with transaction.atomic():
            cambio.save()
    except ValidationError as error:
        raise ErrorTrabajador(error.message_dict) from None
    except IntegrityError:
        raise _error("vigente_desde", "Ya hay un sueldo con esa fecha de vigencia.") from None
    registrar(
        "rrhh.sueldo_cambiado",
        recurso_tipo="contrato_laboral",
        recurso_id=contrato.pk,
        empresa_id=contrato.empresa_id,
        resumen=f"Sueldo del contrato {contrato.pk} cambiado desde {vigente_desde:%d/%m/%Y}",
        detalle={"desde": vigente_desde},  # el monto no se registra: es un dato sensible
    )
    return cambio, _advertencias_sueldo(
        contrato.personal, contrato.tipo_contrato, monto, vigente_desde
    )
