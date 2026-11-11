"""Libro de movimientos de caja y bancos: todo el dinero que entra o sale de cada caja o cuenta.

El saldo de una caja o cuenta NO se guarda: es su saldo inicial más lo que muestra este libro. Un
movimiento es un documento inmutable: no se edita ni se borra, solo se anula con motivo (y deja de
contar). Cada movimiento sabe de dónde viene (a mano, un pago de compra, un cobro de venta…).
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.models import DocumentoInmutable, EmpresaScopedModel


class TipoMovimiento(models.TextChoices):
    INGRESO = "INGRESO", "Ingreso"
    EGRESO = "EGRESO", "Egreso"


class Origen:
    """De dónde viene un movimiento. Quien lo genera guarda su tipo y el id de su documento."""

    MANUAL = "MANUAL"
    PAGO_COMPRA = "PAGO_COMPRA"
    PAGO_GASTO = "PAGO_GASTO"
    COBRO_VENTA = "COBRO_VENTA"
    ABONO_VENTA = "ABONO_VENTA"  # lo que el cliente paga después de una venta a crédito
    REEMBOLSO_VENTA = "REEMBOLSO_VENTA"  # lo que se devuelve al cliente por una nota de crédito
    # Lo que un proveedor devuelve en dinero por mercadería que se le devolvió (Compras).
    REEMBOLSO_COMPRA = "REEMBOLSO_COMPRA"
    # Lo que un cliente deja por adelantado en el taller (recibo interno) y lo que se le devuelve.
    ADELANTO_SERVICIO = "ADELANTO_SERVICIO"
    DEVOLUCION_ADELANTO = "DEVOLUCION_ADELANTO"
    # Lo que se entrega a un trabajador como adelanto de sueldo o préstamo (RR.HH.).
    ADELANTO_PERSONAL = "ADELANTO_PERSONAL"
    # El sueldo que se paga a un trabajador al cerrar la planilla del mes (RR.HH.).
    PAGO_PLANILLA = "PAGO_PLANILLA"
    # El depósito de la CTS de un trabajador (RR.HH.).
    DEPOSITO_CTS = "DEPOSITO_CTS"
    COMISION_TARJETA = "COMISION_TARJETA"  # lo que retiene el procesador al liquidar tarjetas
    # La comisión que cobra el banco por un cheque rechazado.
    CHEQUE_RECHAZADO = "CHEQUE_RECHAZADO"
    # El dinero que se adelanta a un proveedor y el que él devuelve de ese adelanto (Compras).
    ANTICIPO_PROVEEDOR = "ANTICIPO_PROVEEDOR"
    DEVOLUCION_ANTICIPO = "DEVOLUCION_ANTICIPO"
    TRANSFERENCIA = "TRANSFERENCIA"
    ARQUEO = "ARQUEO"
    EXTRACTO = "EXTRACTO"  # lo que el banco cobró o abonó y se registró desde el estado de cuenta
    # Dinero que un socio puso de su bolsillo para un pago: entra a la caja y el pago lo gasta.
    APORTE_PAGO_COMPRA = "APORTE_PAGO_COMPRA"
    APORTE_PAGO_GASTO = "APORTE_PAGO_GASTO"

    AUTOMATICOS = (
        PAGO_COMPRA,
        PAGO_GASTO,
        COBRO_VENTA,
        ABONO_VENTA,
        COMISION_TARJETA,
        CHEQUE_RECHAZADO,
        ANTICIPO_PROVEEDOR,
        DEVOLUCION_ANTICIPO,
        REEMBOLSO_VENTA,
        REEMBOLSO_COMPRA,
        ADELANTO_SERVICIO,
        DEVOLUCION_ADELANTO,
        ADELANTO_PERSONAL,
        PAGO_PLANILLA,
        DEPOSITO_CTS,
        TRANSFERENCIA,
        ARQUEO,
        EXTRACTO,
        APORTE_PAGO_COMPRA,
        APORTE_PAGO_GASTO,
    )
    # Los que una persona ordena a mano: no van antes del saldo con que se abrió la cuenta.
    A_MANO = (MANUAL, TRANSFERENCIA)


class MovimientoCaja(DocumentoInmutable):
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="movimientos"
    )
    fecha = models.DateField(db_index=True)
    tipo = models.CharField(max_length=7, choices=TipoMovimiento.choices)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    concepto = models.ForeignKey(
        "mantenimiento.ConceptoCaja", on_delete=models.PROTECT, related_name="movimientos"
    )
    glosa = models.CharField(max_length=250, blank=True)
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    origen_tipo = models.CharField(max_length=20, default=Origen.MANUAL)
    origen_id = models.PositiveBigIntegerField(null=True, blank=True)
    # Con qué se pagó o cobró (efectivo, transferencia, Yape…). Opcional: si falta, se entiende
    # por el tipo de la cuenta (una caja es efectivo, un banco es banco).
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    # La sesión de caja en que se movió el efectivo (solo cajas de efectivo con sesión).
    sesion = models.ForeignKey(
        "caja.SesionCaja",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="movimientos",
    )

    class Meta:
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_movcaja_numero"),
            models.CheckConstraint(condition=Q(monto__gt=Decimal("0")), name="ck_movcaja_monto"),
        ]
        indexes = [
            models.Index(
                fields=["empresa", "cuenta", "fecha", "id"], name="ix_movcaja_cuenta_fecha"
            ),
            models.Index(fields=["origen_tipo", "origen_id"], name="ix_movcaja_origen"),
        ]

    def __str__(self) -> str:
        return f"Movimiento {self.numero:06d} ({self.tipo} {self.monto})"

    @property
    def moneda(self) -> str:
        return self.cuenta.moneda

    @property
    def es_manual(self) -> bool:
        return self.origen_tipo == Origen.MANUAL


class ClaseTransferencia(models.TextChoices):
    TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
    DEPOSITO = "DEPOSITO", "Depósito"
    RETIRO = "RETIRO", "Retiro"


class Transferencia(DocumentoInmutable):
    """Dinero que pasa de una caja o cuenta a otra (de la misma empresa o de otra, con permiso).

    Genera sus movimientos en el libro: la salida de la cuenta de origen, la entrada en la de
    destino y, si hubo, la comisión y el ITF. Anularla anula todos juntos. Entre monedas
    distintas lleva el tipo de cambio con que se convirtió.
    """

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa de origen.")
    empresa_destino = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="transferencias_recibidas"
    )
    cuenta_origen = models.ForeignKey(
        "mantenimiento.CuentaFinanciera",
        on_delete=models.PROTECT,
        related_name="transferencias_salidas",
    )
    cuenta_destino = models.ForeignKey(
        "mantenimiento.CuentaFinanciera",
        on_delete=models.PROTECT,
        related_name="transferencias_entradas",
    )
    clase = models.CharField(max_length=13, choices=ClaseTransferencia.choices)
    fecha = models.DateField(db_index=True)
    monto_origen = models.DecimalField(max_digits=16, decimal_places=2)
    monto_destino = models.DecimalField(max_digits=16, decimal_places=2)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    comision = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    itf = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    glosa = models.CharField(max_length=250, blank=True)
    referencia = models.CharField("número de operación", max_length=60, blank=True)

    class Meta:
        verbose_name = "transferencia"
        verbose_name_plural = "transferencias"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_transferencia_numero"),
            models.CheckConstraint(
                condition=Q(monto_origen__gt=0) & Q(monto_destino__gt=0),
                name="ck_transferencia_montos",
            ),
            models.CheckConstraint(
                condition=Q(comision__gte=0) & Q(itf__gte=0), name="ck_transferencia_gastos"
            ),
            models.CheckConstraint(
                condition=~Q(cuenta_origen=models.F("cuenta_destino")),
                name="ck_transferencia_cuentas_distintas",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_transferencia_empresa_fecha"),
            models.Index(fields=["empresa_destino", "fecha"], name="ix_transferencia_destino"),
        ]

    def __str__(self) -> str:
        return f"Transferencia {self.numero:06d}"


class SesionCaja(EmpresaScopedModel):
    """Un turno de una caja de efectivo: de que alguien la abre a que la cuenta y la cierra.

    Hay una sola sesión abierta por caja. Al cerrar se compara el efectivo contado con el que el
    sistema espera; la diferencia queda como sobrante o faltante en el libro y la sesión no admite
    más movimientos (reabrirla requiere un permiso aparte).
    """

    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "Abierta"
        CERRADA = "CERRADA", "Cerrada"

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="sesiones"
    )
    estado = models.CharField(
        max_length=8, choices=Estado.choices, default=Estado.ABIERTA, db_index=True
    )
    responsable_id = models.UUIDField()
    responsable_nombre = models.CharField(max_length=150)
    abierta_en = models.DateTimeField()
    # Lo que el sistema decía que había en la caja al abrirla, y el fondo que se le entregó.
    saldo_apertura = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    fondo_entregado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    cerrada_en = models.DateTimeField(null=True, blank=True)
    cerrada_por_id = models.UUIDField(null=True, blank=True)
    cerrada_por_nombre = models.CharField(max_length=150, blank=True)
    esperado_cierre = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    contado_cierre = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    observacion = models.CharField(max_length=250, blank=True)
    reaperturas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "sesión de caja"
        verbose_name_plural = "sesiones de caja"
        ordering = ["-abierta_en", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_sesioncaja_numero"),
            models.UniqueConstraint(
                fields=["cuenta"],
                condition=Q(estado="ABIERTA", eliminado_en__isnull=True),
                name="uq_sesioncaja_una_abierta",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"], name="ix_sesioncaja_empresa_estado"),
            models.Index(fields=["cuenta", "abierta_en"], name="ix_sesioncaja_cuenta"),
        ]

    def __str__(self) -> str:
        return f"Sesión {self.numero:06d} de {self.cuenta_id}"


class TipoArqueo(models.TextChoices):
    PARCIAL = "PARCIAL", "Arqueo parcial"
    CIERRE = "CIERRE", "Cierre"


class ArqueoCaja(EmpresaScopedModel):
    """Conteo del efectivo de una caja durante o al cerrar su sesión; no se edita."""

    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="arqueos")
    tipo = models.CharField(max_length=8, choices=TipoArqueo.choices)
    esperado = models.DecimalField(max_digits=16, decimal_places=2)
    contado = models.DecimalField(max_digits=16, decimal_places=2)
    diferencia = models.DecimalField(max_digits=16, decimal_places=2)
    # {"denominación": cantidad}, por ejemplo {"200": 3, "0.5": 4}.
    conteo = models.JSONField(default=dict)
    # Un mostrador compartido por dos empresas se cuenta UNA vez: los arqueos de sus cajas llevan el
    # mismo identificador y el conteo por billetes y monedas queda solo en uno de ellos.
    grupo = models.UUIDField(null=True, blank=True, db_index=True)
    observacion = models.CharField(max_length=250, blank=True)
    hecho_por_id = models.UUIDField()
    hecho_por_nombre = models.CharField(max_length=150)

    class Meta:
        verbose_name = "arqueo de caja"
        verbose_name_plural = "arqueos de caja"
        ordering = ["-creado_en", "-id"]
        indexes = [models.Index(fields=["sesion", "creado_en"], name="ix_arqueo_sesion")]


class EstadoCuenta(EmpresaScopedModel):
    """El extracto que el banco entregó de una cuenta, importado para conciliarlo con el libro.

    Se compara línea por línea con los movimientos de la cuenta. Cuando ya no queda nada del banco
    sin explicar, se cierra; cerrado, sus conciliaciones no se tocan salvo que se reabra.
    """

    class Estado(models.TextChoices):
        ABIERTO = "ABIERTO", "Abierto"
        CERRADO = "CERRADO", "Conciliado"

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="extractos"
    )
    desde = models.DateField()
    hasta = models.DateField()
    saldo_inicial_banco = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    saldo_final_banco = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    archivo_nombre = models.CharField(max_length=150)
    estado = models.CharField(
        max_length=8, choices=Estado.choices, default=Estado.ABIERTO, db_index=True
    )
    importado_por_id = models.UUIDField()
    importado_por_nombre = models.CharField(max_length=150)
    cerrado_en = models.DateTimeField(null=True, blank=True)
    cerrado_por_nombre = models.CharField(max_length=150, blank=True)
    nota_cierre = models.CharField(max_length=250, blank=True)
    reaperturas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "estado de cuenta"
        verbose_name_plural = "estados de cuenta"
        ordering = ["-hasta", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_estadocuenta_numero",
            ),
            models.CheckConstraint(
                condition=Q(desde__lte=models.F("hasta")), name="ck_estadocuenta_periodo"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "cuenta", "hasta"], name="ix_estadocuenta")]

    def __str__(self) -> str:
        return f"Estado de cuenta {self.numero:06d}"


class LineaEstadoCuenta(EmpresaScopedModel):
    """Una línea del extracto: positiva si el banco abonó, negativa si cargó."""

    class Union(models.TextChoices):
        AUTOMATICA = "AUTOMATICA", "Automática"
        MANUAL = "MANUAL", "Manual"
        REGISTRADA = "REGISTRADA", "Registrada desde el extracto"

    estado_cuenta = models.ForeignKey(EstadoCuenta, on_delete=models.PROTECT, related_name="lineas")
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    orden = models.PositiveIntegerField()
    fecha = models.DateField(db_index=True)
    descripcion = models.CharField(max_length=250, blank=True)
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    saldo = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    huella = models.CharField(max_length=40)
    movimiento = models.ForeignKey(
        MovimientoCaja,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="conciliaciones",
    )
    union = models.CharField(max_length=10, choices=Union.choices, blank=True)
    conciliada_en = models.DateTimeField(null=True, blank=True)
    conciliada_por_nombre = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "línea de estado de cuenta"
        verbose_name_plural = "líneas de estado de cuenta"
        ordering = ["fecha", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["cuenta", "huella"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_lineaextracto_huella",
            ),
            models.UniqueConstraint(
                fields=["movimiento"],
                condition=Q(movimiento__isnull=False, eliminado_en__isnull=True),
                name="uq_lineaextracto_movimiento",
            ),
            models.CheckConstraint(condition=~Q(monto=0), name="ck_lineaextracto_monto"),
        ]
        indexes = [models.Index(fields=["estado_cuenta", "fecha"], name="ix_lineaextracto")]


def _ruta_adjunto(instancia, nombre: str) -> str:
    return f"caja/{instancia.empresa_id}/{instancia.movimiento_id}/{nombre}"


class AdjuntoMovimiento(EmpresaScopedModel):
    """El voucher o comprobante de un movimiento (foto o PDF), guardado ya revisado."""

    movimiento = models.ForeignKey(
        MovimientoCaja, on_delete=models.PROTECT, related_name="adjuntos"
    )
    archivo = models.FileField(upload_to=_ruta_adjunto, max_length=255)
    tipo_contenido = models.CharField(max_length=40)
    nombre_original = models.CharField(max_length=120, blank=True)
    tamano = models.PositiveIntegerField()
    subido_por_nombre = models.CharField(max_length=150)

    class Meta:
        verbose_name = "adjunto de movimiento"
        verbose_name_plural = "adjuntos de movimientos"
        ordering = ["id"]
        indexes = [models.Index(fields=["movimiento"], name="ix_adjunto_movimiento")]


class RendicionCaja(DocumentoInmutable):
    """Rendición de la caja chica: los gastos sueltos se presentan y el fondo se repone.

    La caja chica es un fondo fijo para gastos menores. Cuando baja, se rinden los gastos hechos
    (con sus comprobantes) y otra caja repone exactamente lo gastado, para que el fondo vuelva a su
    monto. La reposición es una transferencia; anular la rendición la anula también.
    """

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="rendiciones"
    )
    cuenta_origen = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    transferencia = models.ForeignKey(Transferencia, on_delete=models.PROTECT, related_name="+")
    desde = models.DateField()
    hasta = models.DateField()
    total = models.DecimalField(max_digits=16, decimal_places=2)
    cantidad = models.PositiveIntegerField()
    glosa = models.CharField(max_length=250, blank=True)
    rendida_por_nombre = models.CharField(max_length=150)

    class Meta:
        verbose_name = "rendición de caja chica"
        verbose_name_plural = "rendiciones de caja chica"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_rendicion_numero"),
            models.CheckConstraint(condition=Q(total__gt=0), name="ck_rendicion_total"),
        ]
        indexes = [models.Index(fields=["empresa", "cuenta"], name="ix_rendicion_cuenta")]

    def __str__(self) -> str:
        return f"Rendición {self.numero:06d}"


class RendicionGasto(EmpresaScopedModel):
    """Un gasto de la caja chica incluido en una rendición (cada gasto se rinde una sola vez)."""

    rendicion = models.ForeignKey(RendicionCaja, on_delete=models.PROTECT, related_name="gastos")
    movimiento = models.ForeignKey(MovimientoCaja, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["movimiento"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_rendiciongasto_movimiento",
            )
        ]


class Cheque(EmpresaScopedModel):
    """Un cheque que se recibió de un cliente o que la empresa giró a un proveedor.

    * RECIBIDO: EN_CARTERA (lo tenemos) → DEPOSITADO (se llevó al banco) → COBRADO (el banco lo
      pagó) o RECHAZADO. Al cobrarlo, el dinero pasa de la cuenta donde se anotó al cobrar la venta
      («cuenta de cheques») al banco, como una transferencia.
    * EMITIDO: GIRADO (lo entregamos) → COBRADO (el banco ya lo pagó) o ANULADO.

    El registro de un cheque emitido NO mueve dinero: el pago al proveedor ya salió de la cuenta al
    registrarlo en Compras con el método «Cheque». Aquí solo se controla cuáles siguen sin cobrar.
    """

    class Tipo(models.TextChoices):
        RECIBIDO = "RECIBIDO", "Recibido de un cliente"
        EMITIDO = "EMITIDO", "Girado a un proveedor"

    class Estado(models.TextChoices):
        EN_CARTERA = "EN_CARTERA", "En cartera"
        DEPOSITADO = "DEPOSITADO", "Depositado"
        GIRADO = "GIRADO", "Girado"
        COBRADO = "COBRADO", "Cobrado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        ANULADO = "ANULADO", "Anulado"

    class Moneda(models.TextChoices):
        PEN = "PEN", "Soles"
        USD = "USD", "Dólares"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, db_index=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, db_index=True)
    numero = models.CharField("número del cheque", max_length=30)
    banco = models.CharField("banco del cheque", max_length=60)
    importe = models.DecimalField(max_digits=16, decimal_places=2)
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    fecha_emision = models.DateField(db_index=True)
    fecha_pago = models.DateField(
        "fecha de pago (cheque diferido)", null=True, blank=True, db_index=True
    )
    tercero = models.CharField(
        "quien lo giró o a quien se giró", max_length=150, help_text="Nombre tal como figura."
    )
    cliente = models.ForeignKey(
        "mantenimiento.Cliente", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Recibido: la cuenta donde se anotó al cobrar la venta (de donde sale al cobrarlo) y el banco
    # donde se depositó. Emitido: la cuenta del banco contra la que se giró.
    cuenta_cartera = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", null=True, blank=True, on_delete=models.PROTECT,
        related_name="+",
    )  # fmt: skip
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", null=True, blank=True, on_delete=models.PROTECT,
        related_name="+",
    )  # fmt: skip
    glosa = models.CharField(max_length=250, blank=True)
    depositado_en = models.DateField(null=True, blank=True)
    cobrado_en = models.DateField(null=True, blank=True)
    motivo = models.CharField("motivo del rechazo o la anulación", max_length=250, blank=True)
    transferencia = models.ForeignKey(
        "caja.Transferencia", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "cheque"
        verbose_name_plural = "cheques"
        ordering = ["-fecha_emision", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo", "banco", "numero"],
                condition=Q(eliminado_en__isnull=True) & ~Q(estado="ANULADO"),
                name="uq_cheque_numero_vigente",
            ),
            models.CheckConstraint(condition=Q(importe__gt=0), name="ck_cheque_importe"),
        ]
        indexes = [models.Index(fields=["empresa", "tipo", "estado"], name="ix_cheque_estado")]

    def __str__(self) -> str:
        return f"Cheque {self.numero} ({self.banco})"

    @property
    def vence(self):
        """Último día para cobrarlo: 30 días desde su fecha de pago (o de emisión)."""
        from datetime import timedelta

        return (self.fecha_pago or self.fecha_emision) + timedelta(days=30)
