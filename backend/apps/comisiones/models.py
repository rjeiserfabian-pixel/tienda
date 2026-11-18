"""Reglas de comisión: qué porcentaje gana un vendedor según lo que vende.

Una regla dice «a este vendedor (o a todos) se le paga tal porcentaje por este producto, marca,
categoría o por cualquier venta». Si varias reglas encajan, gana la MÁS ESPECÍFICA (ver
``servicios.porcentaje_para``). Las reglas son de la organización: valen para todas sus empresas.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.models import EmpresaScopedModel, OrganizacionScopedModel


class Alcance(models.TextChoices):
    GENERAL = "GENERAL", "Cualquier venta"
    CATEGORIA = "CATEGORIA", "Una categoría"
    MARCA = "MARCA", "Una marca"
    PRODUCTO = "PRODUCTO", "Un producto"


class ReglaComision(OrganizacionScopedModel):
    alcance = models.CharField(max_length=10, choices=Alcance.choices)
    categoria = models.ForeignKey(
        "mantenimiento.Categoria", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    marca = models.ForeignKey(
        "mantenimiento.Marca", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    producto = models.ForeignKey(
        "mantenimiento.Producto", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Id del usuario vendedor; vacío = vale para todos los vendedores.
    vendedor_id = models.UUIDField(null=True, blank=True, db_index=True)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    nota = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "regla de comisión"
        verbose_name_plural = "reglas de comisión"
        ordering = ["alcance", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(porcentaje__gte=Decimal("0")) & Q(porcentaje__lte=Decimal("100")),
                name="ck_regla_comision_porcentaje",
            ),
            # Cada alcance apunta a UNA cosa: la general a ninguna, las demás a la suya.
            models.CheckConstraint(
                condition=(
                    Q(alcance="GENERAL", categoria=None, marca=None, producto=None)
                    | Q(alcance="CATEGORIA", categoria__isnull=False, marca=None, producto=None)
                    | Q(alcance="MARCA", marca__isnull=False, categoria=None, producto=None)
                    | Q(alcance="PRODUCTO", producto__isnull=False, categoria=None, marca=None)
                ),
                name="ck_regla_comision_alcance",
            ),
            models.CheckConstraint(
                condition=Q(vigente_desde__isnull=True)
                | Q(vigente_hasta__isnull=True)
                | Q(vigente_hasta__gte=models.F("vigente_desde")),
                name="ck_regla_comision_fechas",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "activa", "alcance"], name="ix_regla_com")]

    def __str__(self) -> str:
        return f"{self.get_alcance_display()} {self.porcentaje} %"


class ComisionComprobante(EmpresaScopedModel):
    """Lo que un comprobante puede pagarle a su vendedor, fijado al vender.

    Se guarda el porcentaje de cada línea TAL COMO ERA al vender: si luego se cambian las reglas,
    las ventas ya hechas no cambian. Todo en soles (las ventas en dólares se convierten con el
    tipo de cambio de la venta).
    """

    comprobante = models.OneToOneField(
        "ventas.ComprobanteVenta", on_delete=models.PROTECT, related_name="comision"
    )
    vendedor_id = models.UUIDField(db_index=True)
    vendedor_nombre = models.CharField(max_length=150, blank=True)
    fecha_venta = models.DateField()
    base_neta = models.DecimalField(max_digits=16, decimal_places=2)
    comision_total = models.DecimalField(max_digits=16, decimal_places=2)
    # [{"linea", "producto", "neta", "porcentaje", "comision", "regla", "general"}], una por línea
    # vendida; «general» = no tuvo regla de producto, marca o categoría (la escala la puede mover).
    detalle = models.JSONField(default=list)
    # Porcentaje que fijó la escala mensual para las líneas «generales» (vacío = sin escala).
    escala_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "comisión de un comprobante"
        verbose_name_plural = "comisiones de comprobantes"
        indexes = [models.Index(fields=["empresa", "vendedor_id"], name="ix_comision_comp_vend")]

    def __str__(self) -> str:
        return f"Comisión de {self.comprobante_id}: {self.comision_total}"


class MovimientoComision(EmpresaScopedModel):
    """Una vez que la comisión sube o baja: al cobrar, al devolver, al anular.

    Solo se AGREGAN filas (nunca se editan ni se borran): lo ganado por un comprobante es la suma
    de sus movimientos, y el mes se cierra sumando por fecha.
    """

    class Motivo(models.TextChoices):
        COBRO = "COBRO", "Cobro"
        AJUSTE = "AJUSTE", "Ajuste por devolución o abono anulado"
        ANULACION = "ANULACION", "Venta anulada"

    plan = models.ForeignKey(
        ComisionComprobante, on_delete=models.PROTECT, related_name="movimientos"
    )
    vendedor_id = models.UUIDField(db_index=True)
    fecha = models.DateField(db_index=True)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    motivo = models.CharField(max_length=10, choices=Motivo.choices)
    detalle = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "movimiento de comisión"
        verbose_name_plural = "movimientos de comisión"
        ordering = ["fecha", "id"]
        constraints = [
            models.CheckConstraint(condition=~Q(monto=Decimal("0")), name="ck_mov_comision_monto")
        ]
        indexes = [
            models.Index(fields=["empresa", "vendedor_id", "fecha"], name="ix_mov_comision_vend")
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Un movimiento de comisión no se modifica: se agrega otro.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Un movimiento de comisión no se elimina.")


class EscalaComision(OrganizacionScopedModel):
    """Una escala mensual: cuanto más vende el vendedor en el mes, mayor su porcentaje.

    Se mide con la venta neta del mes (sin IGV, en soles, menos devoluciones). El porcentaje del
    tramo alcanzado se aplica a TODO lo vendido del mes que no tenga una regla específica de
    producto, marca o categoría (esas son fijas). Sin ``vendedor_id`` vale para todos.
    """

    nombre = models.CharField(max_length=80)
    vendedor_id = models.UUIDField(null=True, blank=True, db_index=True)
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "escala de comisión"
        verbose_name_plural = "escalas de comisión"
        ordering = ["-id"]

    def __str__(self) -> str:
        return self.nombre


class TramoEscala(OrganizacionScopedModel):
    """Desde cuánto vendido en el mes (inclusive) rige un porcentaje."""

    escala = models.ForeignKey(EscalaComision, on_delete=models.CASCADE, related_name="tramos")
    desde = models.DecimalField(max_digits=16, decimal_places=2)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = "tramo de escala"
        verbose_name_plural = "tramos de escala"
        ordering = ["desde"]
        constraints = [
            # Los tramos «borrados» se conservan marcados: no deben estorbar a los nuevos.
            models.UniqueConstraint(
                fields=["escala", "desde"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tramo_escala_desde",
            ),
            models.CheckConstraint(condition=Q(desde__gte=Decimal("0")), name="ck_tramo_desde"),
            models.CheckConstraint(
                condition=Q(porcentaje__gte=Decimal("0")) & Q(porcentaje__lte=Decimal("100")),
                name="ck_tramo_porcentaje",
            ),
        ]


class MetaBono(OrganizacionScopedModel):
    """Un premio fijo: si el vendedor vende al menos ``meta`` en el mes, gana ``bono``."""

    nombre = models.CharField(max_length=80)
    vendedor_id = models.UUIDField(null=True, blank=True, db_index=True)
    meta = models.DecimalField(max_digits=16, decimal_places=2)
    bono = models.DecimalField(max_digits=16, decimal_places=2)
    vigente_desde = models.DateField(null=True, blank=True)
    vigente_hasta = models.DateField(null=True, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "meta con bono"
        verbose_name_plural = "metas con bono"
        ordering = ["meta", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(meta__gt=Decimal("0")), name="ck_meta_monto"),
            models.CheckConstraint(condition=Q(bono__gt=Decimal("0")), name="ck_meta_bono"),
        ]

    def __str__(self) -> str:
        return f"{self.nombre}: {self.meta} → {self.bono}"


class BonoGanado(OrganizacionScopedModel):
    """Un bono ya otorgado a un vendedor por cumplir una meta en un mes (uno por meta y mes)."""

    vendedor_id = models.UUIDField(db_index=True)
    periodo = models.CharField(max_length=7)  # «2026-11»
    meta = models.ForeignKey(MetaBono, on_delete=models.PROTECT, related_name="otorgados")
    nombre = models.CharField(max_length=80)  # como se llamaba la meta al otorgarlo
    ventas_mes = models.DecimalField(max_digits=16, decimal_places=2)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    fecha = models.DateField()

    class Meta:
        verbose_name = "bono ganado"
        verbose_name_plural = "bonos ganados"
        ordering = ["periodo", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "vendedor_id", "periodo", "meta"],
                name="uq_bono_vendedor_periodo_meta",
            )
        ]


class LiquidacionComision(OrganizacionScopedModel):
    """El cierre de un mes: lo que ganó cada persona y cuánto se le paga.

    Un mes cerrado no se mueve: lo que pase después (una devolución, un cobro atrasado) se anota en
    el mes que sigue. Los meses se cierran en orden, uno por uno.
    """

    periodo = models.CharField(max_length=7)  # «2026-11»
    cerrada_en = models.DateTimeField()
    cerrada_por_id = models.UUIDField(null=True, blank=True)
    total_a_pagar = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "liquidación de comisiones"
        verbose_name_plural = "liquidaciones de comisiones"
        ordering = ["-periodo"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "periodo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_liquidacion_comision_periodo",
            )
        ]

    def __str__(self) -> str:
        return f"Comisiones {self.periodo}"


class LineaLiquidacion(OrganizacionScopedModel):
    """Lo de UNA persona en una liquidación (vendedor, técnico o ambas cosas)."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Por pagar"
        EN_PLANILLA = "EN_PLANILLA", "En la planilla"
        PAGADA_APARTE = "PAGADA_APARTE", "Pagada aparte"
        SIN_MONTO = "SIN_MONTO", "Nada que pagar"

    liquidacion = models.ForeignKey(
        LiquidacionComision, on_delete=models.PROTECT, related_name="lineas"
    )
    # «P:12» si tiene ficha de personal, «U:<uuid>» si solo es un usuario vendedor.
    clave = models.CharField(max_length=50)
    vendedor_id = models.UUIDField(null=True, blank=True, db_index=True)
    personal = models.ForeignKey(
        "mantenimiento.Personal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    nombre = models.CharField(max_length=200)

    comisiones_ventas = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    bonos = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    comisiones_tecnico = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    # Lo que quedó debiendo el mes anterior (devoluciones mayores a lo ganado): negativo o cero.
    arrastre_anterior = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    a_pagar = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    arrastre_nuevo = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    # El detalle venta por venta, bonos y órdenes de servicio, para explicar cada sol.
    detalle = models.JSONField(default=dict)

    estado = models.CharField(max_length=14, choices=Estado.choices, default=Estado.PENDIENTE)
    planilla = models.ForeignKey(
        "rrhh.Planilla", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    planilla_concepto = models.ForeignKey(
        "rrhh.PlanillaConcepto", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    enviada_en = models.DateTimeField(null=True, blank=True)
    pagada_en = models.DateTimeField(null=True, blank=True)
    pagada_nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "línea de liquidación"
        verbose_name_plural = "líneas de liquidación"
        ordering = ["nombre", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["liquidacion", "clave"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_linea_liquidacion_clave",
            ),
            models.CheckConstraint(condition=Q(a_pagar__gte=Decimal("0")), name="ck_linea_a_pagar"),
            models.CheckConstraint(
                condition=Q(arrastre_nuevo__lte=Decimal("0")), name="ck_linea_arrastre"
            ),
        ]
