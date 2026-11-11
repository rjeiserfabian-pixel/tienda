"""Gastos generales: luz, alquiler, internet, un taxi… lo que la empresa gasta y no revende.

Un gasto puede tener comprobante (factura, boleta, recibo de servicio, ticket) o no tenerlo (un
taxi, una propina). Se paga al contado (sale dinero de una caja o cuenta en el momento) o queda por
pagar con su vencimiento. Puede ir a una sola empresa o repartirse entre varias.

Es un documento inmutable: no se edita ni se borra, solo se anula con motivo. Cuánto se pagó no se
guarda en el gasto: sale de sus pagos vigentes.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.functions import Lower

from apps.core.models import DocumentoInmutable, EmpresaScopedModel

CERO = Decimal("0")


class Moneda(models.TextChoices):
    PEN = "PEN", "Soles"
    USD = "USD", "Dólares"


class FormaPago(models.TextChoices):
    CONTADO = "CONTADO", "Al contado"
    POR_PAGAR = "POR_PAGAR", "Por pagar"


class Gasto(DocumentoInmutable):
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    categoria = models.ForeignKey(
        "mantenimiento.CategoriaGasto", on_delete=models.PROTECT, related_name="gastos"
    )
    fecha = models.DateField(db_index=True)
    descripcion = models.CharField(max_length=250)
    observacion = models.CharField(max_length=250, blank=True)
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    # Con comprobante: tipo, serie y número (y el proveedor). Sin él, solo quién gastó.
    con_comprobante = models.BooleanField()
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gastos",
    )
    comprobante_serie = models.CharField(max_length=10, blank=True)
    comprobante_numero = models.CharField(max_length=20, blank=True)
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gastos",
    )
    gastado_por = models.CharField("quién lo gastó", max_length=120, blank=True)

    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    base_gravada = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    no_gravado = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=16, decimal_places=2)

    forma_pago = models.CharField(max_length=10, choices=FormaPago.choices)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    # Si se registró desde un gasto recurrente (el alquiler de cada mes, por ejemplo).
    recurrente = models.ForeignKey(
        "gastos.GastoRecurrente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gastos",
    )

    class Meta:
        verbose_name = "gasto"
        verbose_name_plural = "gastos"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_gasto_numero"),
            models.CheckConstraint(condition=Q(total__gt=0), name="ck_gasto_total"),
            models.CheckConstraint(
                condition=Q(total=F("base_gravada") + F("igv") + F("no_gravado")),
                name="ck_gasto_suma",
            ),
            models.CheckConstraint(
                condition=(Q(con_comprobante=True, tipo_comprobante__isnull=False))
                | Q(con_comprobante=False, tipo_comprobante__isnull=True),
                name="ck_gasto_comprobante",
            ),
            models.UniqueConstraint(
                fields=[
                    "empresa",
                    "proveedor",
                    "tipo_comprobante",
                    "comprobante_serie",
                    "comprobante_numero",
                ],
                condition=Q(con_comprobante=True, proveedor__isnull=False, estado="EMITIDO"),
                name="uq_gasto_comprobante_vigente",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_gasto_empresa_fecha"),
            models.Index(fields=["empresa", "categoria", "fecha"], name="ix_gasto_categoria"),
        ]

    def __str__(self) -> str:
        return f"Gasto {self.numero:06d}"

    @property
    def sin_sustento(self) -> bool:
        """Sin comprobante: no respalda crédito fiscal ni deducción, y se vigila aparte."""
        return not self.con_comprobante

    @property
    def comprobante(self) -> str:
        if not self.con_comprobante:
            return ""
        return f"{self.comprobante_serie}-{self.comprobante_numero}".strip("-")

    def pagado(self) -> Decimal:
        """Lo pagado hasta ahora, en la moneda del gasto (pagos vigentes)."""
        return (
            PagoGasto.objects.filter(gasto=self, anulado=False).aggregate(s=Sum("monto"))["s"]
            or CERO
        )

    def saldo(self) -> Decimal:
        if self.estado != self.Estado.EMITIDO:
            return CERO
        return self.total - self.pagado()


class PagoGasto(EmpresaScopedModel):
    """Un pago del gasto: con qué método y de qué caja o cuenta salió el dinero."""

    gasto = models.ForeignKey(Gasto, on_delete=models.PROTECT, related_name="pagos")
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="pagos_gasto"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="pagos_gasto"
    )
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    # Si la caja o cuenta es de otra moneda que el gasto: con qué tipo de cambio se convirtió y
    # cuánto salió de verdad de la cuenta (en su moneda).
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    monto_cuenta = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "pago de gasto"
        verbose_name_plural = "pagos de gastos"
        ordering = ["fecha", "id"]
        constraints = [models.CheckConstraint(condition=Q(monto__gt=0), name="ck_pagogasto_monto")]
        indexes = [models.Index(fields=["gasto"], name="ix_pagogasto_gasto")]

    @property
    def monto_en_cuenta(self) -> Decimal:
        return self.monto_cuenta if self.monto_cuenta is not None else self.monto


class GastoReparto(EmpresaScopedModel):
    """La parte de un gasto que le toca a una empresa (``empresa``), cuando se reparte.

    El comprobante y el IGV quedan en la empresa titular del gasto; el reparto es el costo que
    cada empresa asume, para sus reportes. Sin reparto, todo el gasto es de la titular.
    """

    gasto = models.ForeignKey(Gasto, on_delete=models.PROTECT, related_name="repartos")
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    monto = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "reparto de gasto"
        verbose_name_plural = "repartos de gastos"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["gasto", "empresa"], name="uq_gastoreparto_empresa"),
            models.CheckConstraint(
                condition=Q(porcentaje__gt=0, porcentaje__lte=100), name="ck_gastoreparto_pct"
            ),
        ]


def _ruta_adjunto(instancia, nombre: str) -> str:
    return f"gastos/{instancia.empresa_id}/{instancia.gasto_id}/{nombre}"


class AdjuntoGasto(EmpresaScopedModel):
    """El comprobante de un gasto (foto o PDF), guardado ya revisado."""

    gasto = models.ForeignKey(Gasto, on_delete=models.PROTECT, related_name="adjuntos")
    archivo = models.FileField(upload_to=_ruta_adjunto, max_length=255)
    tipo_contenido = models.CharField(max_length=40)
    nombre_original = models.CharField(max_length=120, blank=True)
    tamano = models.PositiveIntegerField()
    subido_por_nombre = models.CharField(max_length=150)

    class Meta:
        verbose_name = "adjunto de gasto"
        verbose_name_plural = "adjuntos de gastos"
        ordering = ["id"]
        indexes = [models.Index(fields=["gasto"], name="ix_adjuntogasto_gasto")]


class GastoRecurrente(EmpresaScopedModel):
    """Un gasto que se repite (el alquiler, la luz, el internet): el sistema avisa cuándo toca.

    No registra nada solo: cada vez hay que confirmar el importe y el comprobante, porque cambian.
    La plantilla propone los datos y, al registrar el gasto, pasa sola a la siguiente fecha.
    """

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"

    nombre = models.CharField(max_length=80)
    categoria = models.ForeignKey(
        "mantenimiento.CategoriaGasto", on_delete=models.PROTECT, related_name="recurrentes"
    )
    descripcion = models.CharField(max_length=250)
    con_comprobante = models.BooleanField(default=True)
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    importe_estimado = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    periodicidad = models.ForeignKey(
        "mantenimiento.Periodicidad", on_delete=models.PROTECT, related_name="+"
    )
    proxima_fecha = models.DateField()
    avisar_dias = models.PositiveSmallIntegerField(default=5)
    ultima_registrada = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)

    class Meta:
        verbose_name = "gasto recurrente"
        verbose_name_plural = "gastos recurrentes"
        ordering = ["proxima_fecha", "nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "empresa",
                condition=Q(eliminado_en__isnull=True),
                name="uq_gastorecurrente_nombre_vigente",
            ),
            models.CheckConstraint(
                condition=Q(avisar_dias__lte=30), name="ck_gastorecurrente_aviso"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "estado", "proxima_fecha"], name="ix_gastorec")]

    def __str__(self) -> str:
        return self.nombre
