"""Recursos humanos: parámetros y catálogos de la planilla (los comparten todas las empresas).

Nada legal está fijo en el código. Los valores que cambian con la ley (sueldo mínimo, UIT, tasas de
AFP…) son registros con FECHA DE VIGENCIA: cuando cambian se carga el valor nuevo con su fecha y
cada planilla usa el que correspondía a su mes. Cada empresa lleva su propia planilla y sus
trabajadores (el maestro «Personal»), pero estos parámetros son de la organización y valen para
todas.

Aquí viven:

* ``RegimenLaboral``: las reglas de cada régimen (general, pequeña empresa…).
* ``ParametroLaboral``: un valor legal con su vigencia (sueldo mínimo, UIT, ONP…).
* ``TasaAfp``: las tasas de cada AFP por periodo.
* ``TipoAsistencia``: los códigos que se marcan cada día (A, F, DS, V…) y cómo cuenta cada uno.
* ``Feriado``: los días feriados del calendario.
* ``ConceptoPlanilla``: el catálogo de ingresos, descuentos y aportes de la planilla.

Y de cada empresa (cada RUC lleva sus trabajadores y su planilla):

* ``DatosLaborales``: lo laboral de un trabajador de «Personal» (pensión, cuenta, opciones).
* ``ContratoLaboral``: sus contratos, con régimen y fechas; solo uno vigente a la vez.
* ``CambioSueldo``: el historial de sueldos de cada contrato, con su fecha de vigencia.
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.crypto import CampoCifrado
from apps.core.models import EmpresaScopedModel, OrganizacionScopedModel
from apps.mantenimiento.models import Banco, EstadoRegistro


def _estado():
    return models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )


# ---------------------------------------------------------------------------
# Régimen laboral
# ---------------------------------------------------------------------------
class RegimenLaboral(OrganizacionScopedModel):
    """Las reglas de un régimen laboral: lo que cambia entre general, pequeña empresa, etc."""

    RESTRICCIONES = {
        "uq_regimenlaboral_codigo_vigente": ("codigo", "Ya existe un régimen con ese código."),
    }

    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=80)
    # Lo que aporta el empleador a EsSalud, en porcentaje de la remuneración.
    tasa_essalud = models.DecimalField(
        "EsSalud del empleador (%)", max_digits=5, decimal_places=2, default=Decimal("9.00")
    )
    dias_vacaciones = models.PositiveSmallIntegerField("días de vacaciones al año", default=30)
    # Cuántos sueldos son cada gratificación (julio y diciembre) y cuánto sueldo es la CTS al año.
    factor_gratificacion = models.DecimalField(
        "sueldos por gratificación", max_digits=4, decimal_places=2, default=Decimal("1.00")
    )
    factor_cts = models.DecimalField(
        "sueldos de CTS al año", max_digits=4, decimal_places=2, default=Decimal("1.00")
    )
    estado = _estado()

    class Meta:
        verbose_name = "régimen laboral"
        verbose_name_plural = "regímenes laborales"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_regimenlaboral_codigo_vigente",
            ),
            models.CheckConstraint(
                condition=Q(tasa_essalud__gte=0) & Q(tasa_essalud__lte=100),
                name="ck_regimenlaboral_essalud",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_regimen_org_estado")]

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.codigo = "".join((self.codigo or "").split()).upper()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.codigo:
            raise ValidationError({"codigo": "Ingrese el código."})
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre del régimen."})
        if not 1 <= (self.dias_vacaciones or 0) <= 60:
            raise ValidationError({"dias_vacaciones": "Use entre 1 y 60 días."})
        for campo in ("factor_gratificacion", "factor_cts"):
            valor = getattr(self, campo)
            if valor is None or not Decimal("0") <= valor <= Decimal("3"):
                raise ValidationError({campo: "Use un valor entre 0 y 3 sueldos."})


# ---------------------------------------------------------------------------
# Parámetros legales con vigencia
# ---------------------------------------------------------------------------
class UnidadParametro(models.TextChoices):
    SOLES = "SOLES", "Soles"
    PORCENTAJE = "PORCENTAJE", "Porcentaje"
    NUMERO = "NUMERO", "Número"


class CodigoParametro(models.TextChoices):
    RMV = "RMV", "Remuneración mínima vital (RMV)"
    UIT = "UIT", "Unidad impositiva tributaria (UIT)"
    ASIGNACION_FAMILIAR = "ASIGNACION_FAMILIAR", "Asignación familiar (% de la RMV)"
    ONP = "ONP", "ONP (% de la remuneración)"
    REM_MAX_ASEGURABLE = "REM_MAX_ASEGURABLE", "Remuneración máxima asegurable (AFP)"
    BONIF_EXTRAORDINARIA = "BONIF_EXTRAORDINARIA", "Bonificación extraordinaria (%)"
    DIAS_MES = "DIAS_MES", "Días del mes para el valor del día"
    HORAS_JORNADA = "HORAS_JORNADA", "Horas de la jornada diaria"
    SOBRETASA_HE_PRIMERAS = "SOBRETASA_HE_PRIMERAS", "Sobretasa de las primeras horas extra (%)"
    SOBRETASA_HE_SIGUIENTES = (
        "SOBRETASA_HE_SIGUIENTES",
        "Sobretasa de las siguientes horas extra (%)",
    )
    HORAS_HE_PRIMERAS = "HORAS_HE_PRIMERAS", "Horas extra de cada día con la primera sobretasa"
    SOBRETASA_FERIADO = "SOBRETASA_FERIADO", "Sobretasa del trabajo en feriado (%)"
    DEDUCCION_RENTA5_UIT = "DEDUCCION_RENTA5_UIT", "Deducción de renta de 5.ª categoría (UIT)"


# código → (unidad, para qué sirve). Se muestra en la pantalla y valida el valor.
DETALLE_PARAMETROS: dict[str, tuple[str, str]] = {
    CodigoParametro.RMV: (UnidadParametro.SOLES, "Sueldo mínimo; base mínima de EsSalud."),
    CodigoParametro.UIT: (UnidadParametro.SOLES, "Para la renta de 5.ª categoría."),
    CodigoParametro.ASIGNACION_FAMILIAR: (
        UnidadParametro.PORCENTAJE,
        "Porcentaje de la RMV que se paga por hijos menores.",
    ),
    CodigoParametro.ONP: (UnidadParametro.PORCENTAJE, "Descuento al trabajador afiliado a la ONP."),
    CodigoParametro.REM_MAX_ASEGURABLE: (
        UnidadParametro.SOLES,
        "Tope sobre el que se cobra la prima de seguro de la AFP.",
    ),
    CodigoParametro.BONIF_EXTRAORDINARIA: (
        UnidadParametro.PORCENTAJE,
        "Se suma a las gratificaciones de julio y diciembre.",
    ),
    CodigoParametro.DIAS_MES: (
        UnidadParametro.NUMERO,
        "Valor del día = sueldo mensual ÷ estos días.",
    ),
    CodigoParametro.HORAS_JORNADA: (
        UnidadParametro.NUMERO,
        "Valor de la hora = valor del día ÷ estas horas.",
    ),
    CodigoParametro.SOBRETASA_HE_PRIMERAS: (
        UnidadParametro.PORCENTAJE,
        "Recargo de las primeras horas extra de cada día.",
    ),
    CodigoParametro.SOBRETASA_HE_SIGUIENTES: (
        UnidadParametro.PORCENTAJE,
        "Recargo de las horas extra siguientes.",
    ),
    CodigoParametro.HORAS_HE_PRIMERAS: (
        UnidadParametro.NUMERO,
        "Cuántas horas extra de cada día llevan la primera sobretasa; las demás, la siguiente.",
    ),
    CodigoParametro.SOBRETASA_FERIADO: (
        UnidadParametro.PORCENTAJE,
        "Recargo al trabajar un feriado o día de descanso.",
    ),
    CodigoParametro.DEDUCCION_RENTA5_UIT: (
        UnidadParametro.NUMERO,
        "UIT que se deducen de la renta anual de 5.ª categoría.",
    ),
}


class ParametroLaboral(OrganizacionScopedModel):
    """Un valor legal desde una fecha. El vigente en una fecha es el último con fecha anterior."""

    RESTRICCIONES = {
        "uq_parametrolaboral_vigencia": (
            "vigente_desde",
            "Ya hay un valor de ese parámetro con esa fecha de vigencia.",
        ),
    }

    codigo = models.CharField(max_length=30, choices=CodigoParametro.choices)
    valor = models.DecimalField(max_digits=14, decimal_places=4)
    vigente_desde = models.DateField()
    nota = models.CharField(
        max_length=200, blank=True, help_text="De dónde sale el valor (decreto, SBS…)."
    )
    estado = _estado()

    class Meta:
        verbose_name = "parámetro laboral"
        verbose_name_plural = "parámetros laborales"
        ordering = ["codigo", "-vigente_desde"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo", "vigente_desde"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_parametrolaboral_vigencia",
            ),
            models.CheckConstraint(condition=Q(valor__gte=0), name="ck_parametrolaboral_valor"),
        ]
        indexes = [
            models.Index(
                fields=["organizacion", "codigo", "vigente_desde"], name="ix_parametro_vigencia"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_codigo_display()} desde {self.vigente_desde:%d/%m/%Y}: {self.valor}"

    @property
    def unidad(self) -> str:
        return DETALLE_PARAMETROS[self.codigo][0]

    def clean(self):
        super().clean()
        if self.codigo not in DETALLE_PARAMETROS:
            raise ValidationError({"codigo": "Elija un parámetro de la lista."})
        if self.valor is None or self.valor < 0:
            raise ValidationError({"valor": "El valor no puede ser negativo."})
        if self.unidad == UnidadParametro.PORCENTAJE and self.valor > 100:
            raise ValidationError({"valor": "Un porcentaje no puede pasar de 100."})
        if self.codigo == CodigoParametro.DIAS_MES and not 28 <= self.valor <= 31:
            raise ValidationError({"valor": "Los días del mes van de 28 a 31 (normalmente 30)."})
        if self.codigo == CodigoParametro.HORAS_JORNADA and not 1 <= self.valor <= 24:
            raise ValidationError({"valor": "La jornada diaria va de 1 a 24 horas."})
        if self.codigo == CodigoParametro.HORAS_HE_PRIMERAS and not 0 <= self.valor <= 12:
            raise ValidationError({"valor": "Use entre 0 y 12 horas."})
        if not self.vigente_desde:
            raise ValidationError({"vigente_desde": "Indique desde cuándo rige."})


# ---------------------------------------------------------------------------
# Tasas de AFP
# ---------------------------------------------------------------------------
class NombreAfp(models.TextChoices):
    HABITAT = "HABITAT", "AFP Habitat"
    INTEGRA = "INTEGRA", "AFP Integra"
    PRIMA = "PRIMA", "Prima AFP"
    PROFUTURO = "PROFUTURO", "Profuturo AFP"


class TasaAfp(OrganizacionScopedModel):
    """Las tasas de una AFP desde una fecha (la SBS las actualiza cada cierto tiempo)."""

    RESTRICCIONES = {
        "uq_tasaafp_vigencia": ("vigente_desde", "Esa AFP ya tiene tasas con esa fecha."),
    }

    afp = models.CharField(max_length=10, choices=NombreAfp.choices)
    vigente_desde = models.DateField()
    aporte_obligatorio = models.DecimalField(
        "aporte obligatorio (%)", max_digits=5, decimal_places=2
    )
    prima_seguro = models.DecimalField("prima de seguro (%)", max_digits=5, decimal_places=2)
    comision_flujo = models.DecimalField("comisión sobre flujo (%)", max_digits=5, decimal_places=2)
    comision_mixta = models.DecimalField("comisión mixta (%)", max_digits=5, decimal_places=2)
    remuneracion_maxima_asegurable = models.DecimalField(
        "remuneración máxima asegurable (S/)", max_digits=12, decimal_places=2
    )
    nota = models.CharField(max_length=200, blank=True)
    estado = _estado()

    class Meta:
        verbose_name = "tasa de AFP"
        verbose_name_plural = "tasas de AFP"
        ordering = ["afp", "-vigente_desde"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "afp", "vigente_desde"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tasaafp_vigencia",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organizacion", "afp", "vigente_desde"], name="ix_tasaafp_vigencia"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_afp_display()} desde {self.vigente_desde:%d/%m/%Y}"

    def clean(self):
        super().clean()
        for campo in ("aporte_obligatorio", "prima_seguro", "comision_flujo", "comision_mixta"):
            valor = getattr(self, campo)
            if valor is None or not Decimal("0") <= valor <= Decimal("100"):
                raise ValidationError({campo: "Use un porcentaje entre 0 y 100."})
        if self.remuneracion_maxima_asegurable is None or self.remuneracion_maxima_asegurable < 0:
            raise ValidationError(
                {"remuneracion_maxima_asegurable": "El monto no puede ser negativo."}
            )
        if not self.vigente_desde:
            raise ValidationError({"vigente_desde": "Indique desde cuándo rigen."})


# ---------------------------------------------------------------------------
# Asistencia: qué significa cada código
# ---------------------------------------------------------------------------
class CategoriaAsistencia(models.TextChoices):
    """En qué cuenta la planilla un día marcado con ese código."""

    LABORADO = "LABORADO", "Día laborado"
    DESCANSO_SEMANAL = "DESCANSO_SEMANAL", "Descanso semanal"
    FALTA = "FALTA", "Falta o permiso sin goce"
    DESCANSO_PAGADO = "DESCANSO_PAGADO", "Descanso pagado"
    DESCANSO_MEDICO = "DESCANSO_MEDICO", "Descanso médico"
    VACACIONES = "VACACIONES", "Vacaciones"
    FERIADO = "FERIADO", "Feriado"
    TRABAJO_FERIADO = "TRABAJO_FERIADO", "Trabajo en feriado o descanso"
    OTRO = "OTRO", "Otro"


class TipoAsistencia(OrganizacionScopedModel):
    """Un código que se marca cada día en la asistencia (A, F, DS, V…)."""

    RESTRICCIONES = {
        "uq_tipoasistencia_codigo_vigente": ("codigo", "Ya existe un tipo con ese código."),
    }

    codigo = models.CharField(max_length=6)
    nombre = models.CharField(max_length=60)
    categoria = models.CharField(max_length=20, choices=CategoriaAsistencia.choices)
    se_paga = models.BooleanField("se paga el día", default=True)
    cuenta_dia_laborado = models.BooleanField(
        "cuenta como día trabajado",
        default=False,
        help_text="Cuenta para las horas trabajadas y los días laborados.",
    )
    estado = _estado()

    class Meta:
        verbose_name = "tipo de asistencia"
        verbose_name_plural = "tipos de asistencia"
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tipoasistencia_codigo_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_tipoasist_org_estado")]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"

    def clean(self):
        super().clean()
        self.codigo = "".join((self.codigo or "").split()).upper()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.codigo:
            raise ValidationError({"codigo": "Ingrese el código."})
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})


class Feriado(OrganizacionScopedModel):
    """Un día feriado del calendario (se usa en la asistencia y en la planilla)."""

    RESTRICCIONES = {
        "uq_feriado_fecha_vigente": ("fecha", "Ya hay un feriado en esa fecha."),
    }

    fecha = models.DateField()
    nombre = models.CharField(max_length=80)
    estado = _estado()

    class Meta:
        verbose_name = "feriado"
        verbose_name_plural = "feriados"
        ordering = ["-fecha"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "fecha"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_feriado_fecha_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "fecha"], name="ix_feriado_fecha")]

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m/%Y} · {self.nombre}"

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre del feriado."})
        if not self.fecha:
            raise ValidationError({"fecha": "Indique la fecha."})


# ---------------------------------------------------------------------------
# Conceptos de la planilla
# ---------------------------------------------------------------------------
class TipoConcepto(models.TextChoices):
    INGRESO = "INGRESO", "Ingreso"
    DESCUENTO = "DESCUENTO", "Descuento al trabajador"
    APORTE_EMPLEADOR = "APORTE_EMPLEADOR", "Aporte del empleador"


class ConceptoPlanilla(OrganizacionScopedModel):
    """Un renglón de la planilla: qué es y sobre qué está afecto (AFP/ONP, EsSalud, renta)."""

    RESTRICCIONES = {
        "uq_conceptoplanilla_codigo_vigente": ("codigo", "Ya existe un concepto con ese código."),
    }

    codigo = models.CharField(max_length=30)
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TipoConcepto.choices)
    afecto_pension = models.BooleanField(
        "afecto a AFP/ONP", default=False, help_text="Entra en la base del descuento de pensiones."
    )
    afecto_essalud = models.BooleanField("afecto a EsSalud", default=False)
    afecto_renta5 = models.BooleanField("afecto a renta de 5.ª", default=False)
    # El código con que se declara en el PLAME. Lo completa el contador: no se inventa aquí.
    codigo_plame = models.CharField("código PLAME", max_length=10, blank=True)
    orden = models.PositiveSmallIntegerField(default=100)
    # Los del sistema los usa el cálculo de la planilla: no se eliminan ni cambian de código.
    es_del_sistema = models.BooleanField(default=False, editable=False)
    estado = _estado()

    class Meta:
        verbose_name = "concepto de planilla"
        verbose_name_plural = "conceptos de planilla"
        ordering = ["tipo", "orden", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_conceptoplanilla_codigo_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "tipo"], name="ix_concepto_org_tipo")]

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.codigo = "".join((self.codigo or "").split()).upper()
        self.nombre = " ".join((self.nombre or "").split())
        self.codigo_plame = "".join((self.codigo_plame or "").split())
        if not self.codigo:
            raise ValidationError({"codigo": "Ingrese el código."})
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre del concepto."})


# ---------------------------------------------------------------------------
# Datos laborales de cada trabajador (por empresa)
# ---------------------------------------------------------------------------
class SistemaPension(models.TextChoices):
    ONP = "ONP", "ONP"
    AFP = "AFP", "AFP"
    NINGUNO = "NINGUNO", "Sin definir o no afiliado"


class TipoComision(models.TextChoices):
    FLUJO = "FLUJO", "Sobre el flujo (remuneración)"
    MIXTA = "MIXTA", "Mixta"


class MetodoPago(models.TextChoices):
    TRANSFERENCIA = "TRANSFERENCIA", "Transferencia a su cuenta"
    EFECTIVO = "EFECTIVO", "Efectivo"
    OTRO = "OTRO", "Otro medio"


class Sexo(models.TextChoices):
    MASCULINO = "M", "Masculino"
    FEMENINO = "F", "Femenino"


class DatosLaborales(EmpresaScopedModel):
    """Lo laboral de un trabajador de «Personal»: pensión, cómo se le paga y qué opciones tiene.

    Los datos de identificación (documento, nombres, dirección, correo) ya están en «Personal»: no
    se repiten. La cuenta bancaria va cifrada y solo la ve quien tiene el permiso de sueldos.
    """

    personal = models.OneToOneField(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="datos_laborales"
    )
    sexo = models.CharField(max_length=1, choices=Sexo.choices, blank=True)
    nacionalidad = models.CharField(max_length=40, default="Peruana")

    sistema_pension = models.CharField(
        max_length=10, choices=SistemaPension.choices, default=SistemaPension.NINGUNO
    )
    afp = models.CharField(max_length=10, choices=NombreAfp.choices, blank=True)
    tipo_comision = models.CharField(max_length=6, choices=TipoComision.choices, blank=True)
    cuspp = models.CharField("CUSPP", max_length=12, blank=True)

    # Opciones POR TRABAJADOR: unos las tienen y otros no.
    asignacion_familiar = models.BooleanField(
        "cobra asignación familiar", default=False, help_text="Tiene hijos que dan derecho a ella."
    )
    paga_renta_5ta = models.BooleanField(
        "se le retiene renta de 5.ª categoría",
        default=False,
        help_text="Su remuneración anual pasa de lo que se deduce de impuesto.",
    )
    subsidio_descanso_medico = models.BooleanField(
        "tiene subsidio por descanso médico",
        default=False,
        help_text="EsSalud cubre sus descansos médicos largos: la planilla los trata aparte.",
    )

    metodo_pago = models.CharField(
        max_length=15, choices=MetodoPago.choices, default=MetodoPago.TRANSFERENCIA
    )
    banco = models.CharField(max_length=15, choices=Banco.choices, blank=True)
    numero_cuenta = CampoCifrado(blank=True)
    cci = CampoCifrado(blank=True)

    class Meta:
        verbose_name = "datos laborales"
        verbose_name_plural = "datos laborales"

    def __str__(self) -> str:
        return f"Datos laborales de {self.personal_id}"

    def clean(self):
        super().clean()
        self.cuspp = "".join((self.cuspp or "").split()).upper()
        self.nacionalidad = " ".join((self.nacionalidad or "").split())
        if self.sistema_pension == SistemaPension.AFP:
            if not self.afp:
                raise ValidationError({"afp": "Elija la AFP del trabajador."})
            if not self.tipo_comision:
                raise ValidationError({"tipo_comision": "Elija el tipo de comisión."})
        elif self.afp or self.tipo_comision or self.cuspp:
            raise ValidationError(
                {"sistema_pension": "La AFP, la comisión y el CUSPP son solo de quien está en AFP."}
            )
        if self.cuspp and not re.fullmatch(r"[A-Z0-9]{12}", self.cuspp):
            raise ValidationError({"cuspp": "El CUSPP tiene 12 letras y números."})
        if self.personal_id and self.personal.empresa_id != self.empresa_id:
            raise ValidationError({"personal": "El trabajador es de otra empresa."})
        if not self.nacionalidad:
            raise ValidationError({"nacionalidad": "Indique la nacionalidad."})


# ---------------------------------------------------------------------------
# Contratos y sueldos
# ---------------------------------------------------------------------------
class TipoContrato(models.TextChoices):
    INDETERMINADO = "INDETERMINADO", "A plazo indeterminado"
    PLAZO_FIJO = "PLAZO_FIJO", "A plazo fijo"
    TIEMPO_PARCIAL = "TIEMPO_PARCIAL", "A tiempo parcial"
    PRACTICAS = "PRACTICAS", "Prácticas"
    OTRO = "OTRO", "Otro"


class CategoriaTrabajador(models.TextChoices):
    EMPLEADO = "EMPLEADO", "Empleado"
    OBRERO = "OBRERO", "Obrero"
    EJECUTIVO = "EJECUTIVO", "Ejecutivo"


class EstadoContrato(models.TextChoices):
    VIGENTE = "VIGENTE", "Vigente"
    FINALIZADO = "FINALIZADO", "Finalizado"


class ContratoLaboral(EmpresaScopedModel):
    """Un contrato de un trabajador: su régimen, su tipo y sus fechas. Solo uno vigente a la vez.

    El sueldo no está aquí sino en ``CambioSueldo``: así se conserva cada aumento con su fecha y la
    planilla de cada mes usa el sueldo que correspondía a ese mes.
    """

    RESTRICCIONES = {
        "uq_contratolaboral_un_vigente": (
            "personal",
            "El trabajador ya tiene un contrato vigente: finalícelo antes de registrar otro.",
        ),
    }

    personal = models.ForeignKey(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="contratos"
    )
    regimen = models.ForeignKey(RegimenLaboral, on_delete=models.PROTECT, related_name="contratos")
    tipo_contrato = models.CharField(
        max_length=15, choices=TipoContrato.choices, default=TipoContrato.INDETERMINADO
    )
    categoria = models.CharField(
        max_length=10, choices=CategoriaTrabajador.choices, default=CategoriaTrabajador.EMPLEADO
    )
    cargo = models.CharField(max_length=100)
    fecha_inicio = models.DateField()
    # Hasta cuándo dura (contrato a plazo fijo); vacío si no vence.
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoContrato.choices, default=EstadoContrato.VIGENTE, db_index=True
    )
    # Cuándo terminó de verdad (renuncia, despido, vencimiento…) y por qué.
    fecha_cese = models.DateField(null=True, blank=True)
    motivo_cese = models.CharField(max_length=200, blank=True)
    observacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "contrato laboral"
        verbose_name_plural = "contratos laborales"
        ordering = ["-fecha_inicio", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["personal"],
                condition=Q(estado="VIGENTE", eliminado_en__isnull=True),
                name="uq_contratolaboral_un_vigente",
            ),
            models.CheckConstraint(
                condition=Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=models.F("fecha_inicio")),
                name="ck_contratolaboral_fin",
            ),
            models.CheckConstraint(
                condition=Q(fecha_cese__isnull=True) | Q(fecha_cese__gte=models.F("fecha_inicio")),
                name="ck_contratolaboral_cese",
            ),
            models.CheckConstraint(
                condition=Q(estado="VIGENTE", fecha_cese__isnull=True)
                | Q(estado="FINALIZADO", fecha_cese__isnull=False),
                name="ck_contratolaboral_estado_cese",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"], name="ix_contrato_empresa_estado"),
            models.Index(fields=["personal", "fecha_inicio"], name="ix_contrato_personal"),
        ]

    def __str__(self) -> str:
        return f"Contrato de {self.personal_id} desde {self.fecha_inicio:%d/%m/%Y}"

    def clean(self):
        super().clean()
        self.cargo = " ".join((self.cargo or "").split())
        if not self.cargo:
            raise ValidationError({"cargo": "Indique el cargo."})
        if self.personal_id and self.personal.empresa_id != self.empresa_id:
            raise ValidationError({"personal": "El trabajador es de otra empresa."})
        if self.regimen_id and self.regimen.organizacion_id != self.empresa.organizacion_id:
            raise ValidationError({"regimen": "El régimen no es de esta organización."})
        if self.tipo_contrato == TipoContrato.PLAZO_FIJO and not self.fecha_fin:
            raise ValidationError(
                {"fecha_fin": "Un contrato a plazo fijo necesita su fecha de fin."}
            )
        if self.fecha_fin and self.fecha_inicio and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({"fecha_fin": "No puede ser anterior al inicio."})

    @property
    def vigente(self) -> bool:
        return self.estado == EstadoContrato.VIGENTE


class CambioSueldo(EmpresaScopedModel):
    """El sueldo mensual de un contrato desde una fecha (el vigente es el último hasta la fecha)."""

    RESTRICCIONES = {
        "uq_cambiosueldo_fecha": ("vigente_desde", "Ya hay un sueldo con esa fecha de vigencia."),
    }

    contrato = models.ForeignKey(
        ContratoLaboral, on_delete=models.PROTECT, related_name="cambios_sueldo"
    )
    monto = models.DecimalField("sueldo mensual (S/)", max_digits=12, decimal_places=2)
    vigente_desde = models.DateField()
    motivo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "cambio de sueldo"
        verbose_name_plural = "cambios de sueldo"
        ordering = ["-vigente_desde", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contrato", "vigente_desde"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_cambiosueldo_fecha",
            ),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_cambiosueldo_monto"),
        ]
        indexes = [models.Index(fields=["contrato", "vigente_desde"], name="ix_cambiosueldo")]

    def __str__(self) -> str:
        return f"S/ {self.monto} desde {self.vigente_desde:%d/%m/%Y}"

    def clean(self):
        super().clean()
        if self.monto is None or self.monto <= 0:
            raise ValidationError({"monto": "El sueldo debe ser mayor que cero."})
        if self.monto > Decimal("9999999.99"):
            raise ValidationError({"monto": "El sueldo es demasiado grande."})
        if self.contrato_id and self.contrato.empresa_id != self.empresa_id:
            raise ValidationError({"contrato": "El contrato es de otra empresa."})
        if (
            self.contrato_id
            and self.vigente_desde
            and self.vigente_desde < self.contrato.fecha_inicio
        ):
            raise ValidationError(
                {"vigente_desde": "El sueldo no puede regir antes del inicio del contrato."}
            )


# ---------------------------------------------------------------------------
# Asistencia diaria
# ---------------------------------------------------------------------------
MAX_HORAS_EXTRA = Decimal("12.00")


class AsistenciaDia(EmpresaScopedModel):
    """Lo que se marcó a un trabajador en un día (A, F, DS, V…) y sus horas extra.

    Un día sin fila es un día sin marcar: no se asume nada. La planilla de cada mes se calcula a
    partir de estas marcas.
    """

    personal = models.ForeignKey(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="asistencias"
    )
    fecha = models.DateField()
    tipo = models.ForeignKey(TipoAsistencia, on_delete=models.PROTECT, related_name="marcas")
    horas_extra = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0"))
    observacion = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "asistencia diaria"
        verbose_name_plural = "asistencia diaria"
        ordering = ["fecha", "personal_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["personal", "fecha"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_asistenciadia_personal_fecha",
            ),
            models.CheckConstraint(
                condition=Q(horas_extra__gte=0, horas_extra__lte=12),
                name="ck_asistenciadia_horas_extra",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_asistencia_empresa_fecha"),
            models.Index(fields=["personal", "fecha"], name="ix_asistencia_personal_fecha"),
        ]

    def __str__(self) -> str:
        return f"{self.personal_id} · {self.fecha:%d/%m/%Y} · {self.tipo_id}"

    def clean(self):
        super().clean()
        if self.horas_extra is None or not 0 <= self.horas_extra <= MAX_HORAS_EXTRA:
            raise ValidationError({"horas_extra": "Las horas extra van de 0 a 12 por día."})
        if self.personal_id and self.personal.empresa_id != self.empresa_id:
            raise ValidationError({"personal": "El trabajador es de otra empresa."})
        if self.tipo_id and self.horas_extra > 0 and not self.tipo.cuenta_dia_laborado:
            raise ValidationError({"horas_extra": "Solo un día trabajado puede tener horas extra."})


# ---------------------------------------------------------------------------
# Adelantos de sueldo y préstamos
# ---------------------------------------------------------------------------
class TipoAdelanto(models.TextChoices):
    ADELANTO = "ADELANTO", "Adelanto de sueldo"
    PRESTAMO = "PRESTAMO", "Préstamo"


class EstadoAdelanto(models.TextChoices):
    VIGENTE = "VIGENTE", "Vigente"
    ANULADO = "ANULADO", "Anulado"


class EstadoCuota(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Por descontar"
    DESCONTADA = "DESCONTADA", "Descontada"
    ANULADA = "ANULADA", "Anulada"


class AdelantoPersonal(EmpresaScopedModel):
    """Plata que la empresa entrega a un trabajador y que se le descuenta en la planilla.

    * Adelanto de sueldo: una sola cuota, en el mes que se elija (por defecto el de la entrega).
    * Préstamo: varias cuotas mensuales iguales desde el mes que se elija.

    La entrega sale de una caja o cuenta (movimiento de Caja). Cada cuota se descuenta en la
    planilla de su mes; si se anula el adelanto, se anula el movimiento de caja y las cuotas.
    """

    RESTRICCIONES = {
        "uq_adelantopersonal_numero": ("numero", "Número de adelanto repetido: intente de nuevo."),
    }

    numero = models.PositiveIntegerField()
    personal = models.ForeignKey(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="adelantos"
    )
    tipo = models.CharField(max_length=10, choices=TipoAdelanto.choices)
    fecha = models.DateField(help_text="Día en que se entregó el dinero.")
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    num_cuotas = models.PositiveSmallIntegerField(default=1)
    primer_periodo = models.DateField(help_text="Primer mes que se descuenta (día 1).")
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    referencia = models.CharField(max_length=60, blank=True)
    motivo = models.CharField(max_length=150, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoAdelanto.choices, default=EstadoAdelanto.VIGENTE, db_index=True
    )
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "adelanto o préstamo"
        verbose_name_plural = "adelantos y préstamos"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_adelantopersonal_numero",
            ),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_adelantopersonal_monto"),
            models.CheckConstraint(
                condition=Q(num_cuotas__gte=1, num_cuotas__lte=36),
                name="ck_adelantopersonal_cuotas",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_adelanto_empresa_fecha"),
            models.Index(fields=["personal", "estado"], name="ix_adelanto_personal_estado"),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} N° {self.numero:06d}"


class CuotaAdelanto(EmpresaScopedModel):
    """Lo que se descuenta de un adelanto o préstamo en la planilla de un mes."""

    adelanto = models.ForeignKey(AdelantoPersonal, on_delete=models.PROTECT, related_name="cuotas")
    numero = models.PositiveSmallIntegerField()
    periodo = models.DateField(help_text="Mes en que se descuenta (día 1).")
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(
        max_length=10, choices=EstadoCuota.choices, default=EstadoCuota.PENDIENTE, db_index=True
    )
    descontada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "cuota de adelanto"
        verbose_name_plural = "cuotas de adelanto"
        ordering = ["periodo", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["adelanto", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_cuotaadelanto_numero",
            ),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_cuotaadelanto_monto"),
        ]
        indexes = [
            models.Index(fields=["empresa", "periodo", "estado"], name="ix_cuotaadel_periodo")
        ]

    def __str__(self) -> str:
        return f"Cuota {self.numero} de {self.adelanto_id}"


# ---------------------------------------------------------------------------
# Tramos de la renta de 5.ª categoría (con vigencia, de la organización)
# ---------------------------------------------------------------------------
class TramoRenta5(OrganizacionScopedModel):
    """Un tramo de la escala del impuesto: hasta cuántas UIT y qué tasa se aplica en él.

    La escala completa es el conjunto de tramos con la misma fecha de vigencia, ordenados por
    ``orden``. El último no tiene tope (``hasta_uit`` vacío). Los valores los carga el contador.
    """

    RESTRICCIONES = {
        "uq_tramorenta5_orden": ("orden", "Ya hay un tramo con ese orden en esa escala."),
    }

    vigente_desde = models.DateField()
    orden = models.PositiveSmallIntegerField()
    hasta_uit = models.DecimalField(
        "hasta (UIT)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Vacío en el último tramo (sin tope).",
    )
    tasa = models.DecimalField("tasa (%)", max_digits=5, decimal_places=2)
    estado = _estado()

    class Meta:
        verbose_name = "tramo de renta de 5.ª"
        verbose_name_plural = "tramos de renta de 5.ª"
        ordering = ["-vigente_desde", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "vigente_desde", "orden"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tramorenta5_orden",
            ),
            models.CheckConstraint(
                condition=Q(tasa__gte=0) & Q(tasa__lte=100), name="ck_tramorenta5_tasa"
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "vigente_desde"], name="ix_tramorenta5")]

    def __str__(self) -> str:
        tope = "sin tope" if self.hasta_uit is None else f"hasta {self.hasta_uit} UIT"
        return f"{self.orden}. {tope}: {self.tasa} %"

    def clean(self):
        super().clean()
        if not self.vigente_desde:
            raise ValidationError({"vigente_desde": "Indique desde cuándo rige."})
        if self.orden is None or not 1 <= self.orden <= 20:
            raise ValidationError({"orden": "El orden va de 1 a 20."})
        if self.tasa is None or not Decimal("0") <= self.tasa <= Decimal("100"):
            raise ValidationError({"tasa": "Use un porcentaje entre 0 y 100."})
        if self.hasta_uit is not None and self.hasta_uit <= 0:
            raise ValidationError({"hasta_uit": "El tope debe ser mayor que cero."})


# ---------------------------------------------------------------------------
# Planilla mensual
# ---------------------------------------------------------------------------
class EstadoPlanilla(models.TextChoices):
    BORRADOR = "BORRADOR", "En revisión"
    CERRADA = "CERRADA", "Cerrada"


class Planilla(EmpresaScopedModel):
    """La planilla de un mes de una empresa: una por mes, con una fila por trabajador.

    Mientras está en revisión se recalcula cuantas veces haga falta. Al cerrarla quedan fijos los
    montos, se dan por descontadas las cuotas de adelantos y se bloquea la asistencia del mes.
    """

    RESTRICCIONES = {
        "uq_planilla_periodo": ("periodo", "Ya existe la planilla de ese mes."),
    }

    periodo = models.DateField(help_text="Mes de la planilla (día 1).")
    estado = models.CharField(
        max_length=10,
        choices=EstadoPlanilla.choices,
        default=EstadoPlanilla.BORRADOR,
        db_index=True,
    )
    calculada_en = models.DateTimeField(null=True, blank=True)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    cerrada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    reabierta_en = models.DateTimeField(null=True, blank=True)
    motivo_reapertura = models.CharField(max_length=250, blank=True)

    num_trabajadores = models.PositiveIntegerField(default=0)
    total_ingresos = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_descuentos = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_neto = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_aportes = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    num_errores = models.PositiveIntegerField(default=0)
    num_avisos = models.PositiveIntegerField(default=0)
    # Lo general que hay que revisar (valores legales sin cargar, escala de renta incompleta…).
    avisos = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "planilla"
        verbose_name_plural = "planillas"
        ordering = ["-periodo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "periodo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_planilla_periodo",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_planilla_empresa_estado")]

    def __str__(self) -> str:
        return f"Planilla {self.periodo:%m/%Y}"


class PlanillaTrabajador(EmpresaScopedModel):
    """La planilla de un trabajador en un mes: lo que se tomó en cuenta y los totales."""

    planilla = models.ForeignKey(Planilla, on_delete=models.PROTECT, related_name="trabajadores")
    personal = models.ForeignKey(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="planillas"
    )
    contrato = models.ForeignKey(ContratoLaboral, on_delete=models.PROTECT, related_name="+")
    # Lo que regía en el mes, para que la planilla cerrada no cambie si luego cambia la ficha.
    regimen_nombre = models.CharField(max_length=80)
    cargo = models.CharField(max_length=100, blank=True)
    sueldo_mensual = models.DecimalField(max_digits=12, decimal_places=2)
    sistema_pension = models.CharField(max_length=10, blank=True)
    afp = models.CharField(max_length=10, blank=True)
    tipo_comision = models.CharField(max_length=6, blank=True)
    metodo_pago = models.CharField(max_length=15, blank=True)

    dias_contrato = models.PositiveSmallIntegerField(default=0, help_text="Días con contrato.")
    dias_laborados = models.PositiveSmallIntegerField(default=0)
    dias_falta = models.PositiveSmallIntegerField(default=0, help_text="Días sin goce de sueldo.")
    dias_descanso_medico = models.PositiveSmallIntegerField(default=0)
    dias_vacaciones = models.PositiveSmallIntegerField(default=0)
    horas_trabajadas = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    horas_extra = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))

    base_pension = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    base_essalud = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_ingresos = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_descuentos = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    neto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    aporte_empleador = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    # [{"nivel": "ERROR" | "AVISO", "texto": "..."}]: lo que hay que revisar de este trabajador.
    avisos = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "planilla de trabajador"
        verbose_name_plural = "planillas de trabajadores"
        ordering = ["personal__apellidos", "personal__nombres", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["planilla", "personal"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_planillatrabajador",
            ),
        ]
        indexes = [models.Index(fields=["planilla"], name="ix_plantrab_planilla")]

    def __str__(self) -> str:
        return f"{self.personal_id} · {self.planilla_id}"


class PlanillaConcepto(EmpresaScopedModel):
    """Un renglón de la planilla de un trabajador (sueldo, faltas, AFP, un adelanto…)."""

    detalle = models.ForeignKey(
        PlanillaTrabajador, on_delete=models.PROTECT, related_name="conceptos"
    )
    concepto = models.ForeignKey(ConceptoPlanilla, on_delete=models.PROTECT, related_name="+")
    codigo = models.CharField(max_length=30)
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TipoConcepto.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    # Cómo se calculó, en palabras («5 faltas × S/ 50.00»).
    explicacion = models.CharField(max_length=200, blank=True)
    # Lo agregó una persona (bono, comisión, otro descuento): el recálculo lo conserva.
    manual = models.BooleanField(default=False)
    cuota = models.ForeignKey(
        CuotaAdelanto, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "concepto de planilla de trabajador"
        verbose_name_plural = "conceptos de planilla de trabajadores"
        ordering = ["tipo", "concepto__orden", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gte=0), name="ck_planillaconcepto_monto"),
        ]
        indexes = [models.Index(fields=["detalle"], name="ix_planconc_detalle")]

    def __str__(self) -> str:
        return f"{self.nombre}: {self.monto}"


# ---------------------------------------------------------------------------
# Pago de la planilla
# ---------------------------------------------------------------------------
class EstadoPago(models.TextChoices):
    PAGADO = "PAGADO", "Pagado"
    ANULADO = "ANULADO", "Anulado"


class PagoPlanilla(EmpresaScopedModel):
    """El sueldo neto de un trabajador pagado al cerrar la planilla (un egreso de Caja).

    Se paga el neto completo, una sola vez por trabajador. Anular el pago devuelve el dinero a la
    caja y deja al trabajador otra vez por pagar.
    """

    planilla = models.ForeignKey(Planilla, on_delete=models.PROTECT, related_name="pagos")
    detalle = models.ForeignKey(PlanillaTrabajador, on_delete=models.PROTECT, related_name="pagos")
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    referencia = models.CharField(max_length=60, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoPago.choices, default=EstadoPago.PAGADO, db_index=True
    )
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "pago de planilla"
        verbose_name_plural = "pagos de planilla"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["detalle"],
                condition=Q(estado="PAGADO", eliminado_en__isnull=True),
                name="uq_pagoplanilla_un_pago_vigente",
            ),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_pagoplanilla_monto"),
        ]
        indexes = [models.Index(fields=["planilla", "estado"], name="ix_pagoplanilla_planilla")]

    def __str__(self) -> str:
        return f"Pago {self.pk} de la planilla {self.planilla_id}"


# ---------------------------------------------------------------------------
# Vacaciones
# ---------------------------------------------------------------------------
class EstadoVacacion(models.TextChoices):
    REGISTRADA = "REGISTRADA", "Registrada"
    ANULADA = "ANULADA", "Anulada"


class VacacionPersonal(EmpresaScopedModel):
    """Un periodo de vacaciones que tomó un trabajador (descuenta de su saldo de días)."""

    personal = models.ForeignKey(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="vacaciones"
    )
    desde = models.DateField()
    hasta = models.DateField()
    dias = models.PositiveSmallIntegerField(help_text="Días corridos entre las dos fechas.")
    # Si se marcaron los días como «V» en la asistencia (no se hace con vacaciones antiguas).
    marco_asistencia = models.BooleanField(default=True)
    observacion = models.CharField(max_length=150, blank=True)
    estado = models.CharField(
        max_length=10,
        choices=EstadoVacacion.choices,
        default=EstadoVacacion.REGISTRADA,
        db_index=True,
    )
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "vacaciones"
        verbose_name_plural = "vacaciones"
        ordering = ["-desde", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(dias__gte=1), name="ck_vacacion_dias"),
            models.CheckConstraint(
                condition=Q(hasta__gte=models.F("desde")), name="ck_vacacion_fechas"
            ),
        ]
        indexes = [models.Index(fields=["personal", "estado"], name="ix_vacacion_personal")]

    def __str__(self) -> str:
        return f"Vacaciones {self.desde:%d/%m/%Y} a {self.hasta:%d/%m/%Y}"


# ---------------------------------------------------------------------------
# CTS (compensación por tiempo de servicios)
# ---------------------------------------------------------------------------
class PeriodoCts(models.TextChoices):
    MAYO = "MAYO", "Mayo (noviembre a abril)"
    NOVIEMBRE = "NOVIEMBRE", "Noviembre (mayo a octubre)"


class EstadoDepositoCts(models.TextChoices):
    CALCULADO = "CALCULADO", "En revisión"
    DEPOSITADO = "DEPOSITADO", "Depositado"


class DepositoCts(EmpresaScopedModel):
    """El cálculo de la CTS de un semestre para toda la empresa y, luego, su depósito."""

    RESTRICCIONES = {
        "uq_depositocts_periodo": ("periodo", "Ya existe el cálculo de la CTS de ese periodo."),
    }

    anio = models.PositiveSmallIntegerField()
    periodo = models.CharField(max_length=10, choices=PeriodoCts.choices)
    estado = models.CharField(
        max_length=10,
        choices=EstadoDepositoCts.choices,
        default=EstadoDepositoCts.CALCULADO,
        db_index=True,
    )
    calculado_en = models.DateTimeField(null=True, blank=True)
    fecha_deposito = models.DateField(null=True, blank=True)
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    referencia = models.CharField(max_length=60, blank=True)
    num_trabajadores = models.PositiveIntegerField(default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    num_errores = models.PositiveIntegerField(default=0)
    num_avisos = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "depósito de CTS"
        verbose_name_plural = "depósitos de CTS"
        ordering = ["-anio", "-periodo"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "anio", "periodo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_depositocts_periodo",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_depositocts_estado")]

    def __str__(self) -> str:
        return f"CTS {self.get_periodo_display()} {self.anio}"


class DepositoCtsTrabajador(EmpresaScopedModel):
    """La CTS de un trabajador en un semestre y cómo se calculó."""

    deposito = models.ForeignKey(DepositoCts, on_delete=models.PROTECT, related_name="trabajadores")
    personal = models.ForeignKey(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="cts"
    )
    regimen_nombre = models.CharField(max_length=80)
    meses = models.PositiveSmallIntegerField(default=0)
    dias = models.PositiveSmallIntegerField(default=0)
    dias_falta = models.PositiveSmallIntegerField(default=0)
    sueldo = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    asignacion_familiar = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    sexto_gratificacion = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    remuneracion_computable = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    monto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    avisos = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "CTS de trabajador"
        verbose_name_plural = "CTS de trabajadores"
        ordering = ["personal__apellidos", "personal__nombres", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["deposito", "personal"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_ctstrabajador",
            ),
            models.CheckConstraint(condition=Q(monto__gte=0), name="ck_ctstrabajador_monto"),
        ]
        indexes = [models.Index(fields=["deposito"], name="ix_ctstrab_deposito")]

    def __str__(self) -> str:
        return f"CTS de {self.personal_id}: {self.monto}"
