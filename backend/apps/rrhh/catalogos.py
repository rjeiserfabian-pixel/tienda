"""Valores base de los catálogos de RR.HH. y consulta de los parámetros vigentes.

Los valores base son un PUNTO DE PARTIDA editable (el contador los confirma): sirven para no empezar
de cero. Se agregan solo los que falten, sin tocar lo que ya se editó ni lo que se eliminó. Los
valores legales con plata (sueldo mínimo, UIT, tasas de AFP…) NO se siembran: los carga el contador
con su fecha de vigencia.
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.mantenimiento.models import EstadoRegistro

from .models import (
    DETALLE_PARAMETROS,
    CategoriaAsistencia,
    ConceptoPlanilla,
    ParametroLaboral,
    RegimenLaboral,
    TasaAfp,
    TipoAsistencia,
    TipoConcepto,
)

logger = logging.getLogger(__name__)

D = Decimal

# (código, nombre, EsSalud %, días de vacaciones, sueldos por gratificación, sueldos de CTS al año)
REGIMENES = (
    ("GENERAL", "Régimen general", D("9.00"), 30, D("1.00"), D("1.00")),
    ("PEQUENA", "Pequeña empresa (MYPE)", D("9.00"), 15, D("0.50"), D("0.50")),
)

# (código, nombre, categoría, se paga, cuenta como día trabajado): los códigos de la asistencia.
TIPOS_ASISTENCIA = (
    ("A", "Asistió", CategoriaAsistencia.LABORADO, True, True),
    ("DS", "Descanso semanal", CategoriaAsistencia.DESCANSO_SEMANAL, True, False),
    ("F", "Falta", CategoriaAsistencia.FALTA, False, False),
    ("PR", "Permiso sin goce", CategoriaAsistencia.FALTA, False, False),
    ("DP", "Descanso pagado", CategoriaAsistencia.DESCANSO_PAGADO, True, False),
    ("DM", "Descanso médico", CategoriaAsistencia.DESCANSO_MEDICO, True, False),
    ("V", "Vacaciones", CategoriaAsistencia.VACACIONES, True, False),
    ("FER", "Feriado", CategoriaAsistencia.FERIADO, True, False),
    ("TF", "Trabajó en feriado o descanso", CategoriaAsistencia.TRABAJO_FERIADO, True, True),
)

I, De, Ap = TipoConcepto.INGRESO, TipoConcepto.DESCUENTO, TipoConcepto.APORTE_EMPLEADOR  # noqa: E741
# (código, nombre, tipo, afecto a AFP/ONP, afecto a EsSalud, afecto a renta de 5.ª, orden)
CONCEPTOS = (
    ("SUELDO_BASICO", "Sueldo básico", I, True, True, True, 10),
    ("ASIGNACION_FAMILIAR", "Asignación familiar", I, True, True, True, 20),
    ("DESCANSO_PAGADO", "Descansos pagados", I, True, True, True, 30),
    ("TRABAJO_FERIADO", "Trabajo en feriado o descanso", I, True, True, True, 40),
    ("HORAS_EXTRA_PRIMERAS", "Horas extra (primeras horas)", I, True, True, True, 50),
    ("HORAS_EXTRA_SIGUIENTES", "Horas extra (siguientes)", I, True, True, True, 60),
    ("VACACIONES", "Vacaciones", I, True, True, True, 70),
    ("COMISIONES", "Comisiones", I, True, True, True, 80),
    ("BONIFICACION", "Bonificaciones", I, True, True, True, 90),
    ("ALIMENTACION", "Alimentación", I, False, False, False, 100),
    ("GRATIFICACION", "Gratificación", I, False, False, True, 110),
    ("BONIF_EXTRAORDINARIA", "Bonificación extraordinaria", I, False, False, False, 120),
    ("CTS", "CTS", I, False, False, False, 130),
    ("DESCUENTO_FALTAS", "Descuento por faltas y permisos sin goce", De, False, False, False, 10),
    ("ADELANTOS", "Adelantos de sueldo", De, False, False, False, 20),
    ("PRESTAMOS", "Préstamos", De, False, False, False, 30),
    ("RENTA_5TA", "Renta de 5.ª categoría", De, False, False, False, 40),
    ("ONP", "ONP", De, False, False, False, 50),
    ("AFP_APORTE", "AFP aporte obligatorio", De, False, False, False, 60),
    ("AFP_PRIMA", "AFP prima de seguro", De, False, False, False, 70),
    ("AFP_COMISION", "AFP comisión", De, False, False, False, 80),
    ("OTROS_DESCUENTOS", "Otros descuentos", De, False, False, False, 90),
    ("ESSALUD", "EsSalud del empleador", Ap, False, False, False, 10),
)


def _agregar(modelo, organizacion_id: int, filas: list[tuple[str, dict]]) -> int:
    """Crea lo que falte por código, sin tocar lo editado ni volver a crear lo eliminado."""
    existentes = {
        f.codigo
        for f in modelo.objects.sin_ambito(incluir_eliminados=True).filter(
            organizacion_id=organizacion_id
        )
    }
    creadas = 0
    for codigo, datos in filas:
        if codigo in existentes:
            continue
        modelo.objects.sin_ambito().create(organizacion_id=organizacion_id, codigo=codigo, **datos)
        creadas += 1
    return creadas


@transaction.atomic
def sembrar_regimenes(organizacion_id: int) -> int:
    return _agregar(
        RegimenLaboral,
        organizacion_id,
        [
            (
                codigo,
                {
                    "nombre": nombre,
                    "tasa_essalud": essalud,
                    "dias_vacaciones": dias,
                    "factor_gratificacion": grat,
                    "factor_cts": cts,
                },
            )
            for codigo, nombre, essalud, dias, grat, cts in REGIMENES
        ],
    )


@transaction.atomic
def sembrar_tipos_asistencia(organizacion_id: int) -> int:
    return _agregar(
        TipoAsistencia,
        organizacion_id,
        [
            (
                codigo,
                {
                    "nombre": nombre,
                    "categoria": categoria,
                    "se_paga": se_paga,
                    "cuenta_dia_laborado": laborado,
                },
            )
            for codigo, nombre, categoria, se_paga, laborado in TIPOS_ASISTENCIA
        ],
    )


@transaction.atomic
def sembrar_conceptos(organizacion_id: int) -> int:
    return _agregar(
        ConceptoPlanilla,
        organizacion_id,
        [
            (
                codigo,
                {
                    "nombre": nombre,
                    "tipo": tipo,
                    "afecto_pension": pension,
                    "afecto_essalud": essalud,
                    "afecto_renta5": renta,
                    "orden": orden,
                    "es_del_sistema": True,
                },
            )
            for codigo, nombre, tipo, pension, essalud, renta, orden in CONCEPTOS
        ],
    )


def sembrar_catalogos_rrhh(organizacion_id: int) -> dict[str, int]:
    """Agrega los valores base que falten (se llama en cada despliegue y desde la pantalla)."""
    resultado = {
        "regimenes": sembrar_regimenes(organizacion_id),
        "tipos_asistencia": sembrar_tipos_asistencia(organizacion_id),
        "conceptos": sembrar_conceptos(organizacion_id),
    }
    if any(resultado.values()):
        logger.info("catalogos_rrhh_sembrados", extra={"organizacion_id": organizacion_id})
    return resultado


# ---------------------------------------------------------------------------
# Lo vigente en una fecha
# ---------------------------------------------------------------------------
def valor_vigente(organizacion_id: int, codigo: str, fecha: date) -> Decimal | None:
    """El valor de un parámetro en esa fecha (``None`` si todavía no se cargó ninguno)."""
    fila = (
        ParametroLaboral.objects.sin_ambito()
        .filter(
            organizacion_id=organizacion_id,
            codigo=codigo,
            estado=EstadoRegistro.ACTIVO,
            vigente_desde__lte=fecha,
        )
        .order_by("-vigente_desde")
        .first()
    )
    return None if fila is None else fila.valor


def tasa_afp_vigente(organizacion_id: int, afp: str, fecha: date) -> TasaAfp | None:
    """Las tasas de esa AFP vigentes en la fecha (``None`` si no se cargaron)."""
    return (
        TasaAfp.objects.sin_ambito()
        .filter(
            organizacion_id=organizacion_id,
            afp=afp,
            estado=EstadoRegistro.ACTIVO,
            vigente_desde__lte=fecha,
        )
        .order_by("-vigente_desde")
        .first()
    )


def parametros_faltantes(organizacion_id: int, fecha: date) -> list[str]:
    """Los códigos de parámetros que no tienen ningún valor vigente en la fecha."""
    return [
        codigo
        for codigo in DETALLE_PARAMETROS
        if valor_vigente(organizacion_id, codigo, fecha) is None
    ]
