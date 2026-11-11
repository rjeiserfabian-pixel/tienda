"""Compras: el comprobante del proveedor, sus líneas, cómo se pagó y cómo ingresó al inventario.

Una compra es un documento INMUTABLE: no se edita ni se borra, solo se anula con motivo (lo que
revierte su entrada al inventario). Al registrarla se crea, en la misma operación, la ENTRADA de
inventario con su costo; el stock y el Kardex siempre van en la unidad base de cada producto.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.models import DocumentoInmutable, EmpresaScopedModel


class FormaPago(models.TextChoices):
    """Cuándo se paga: ahora (contado) o después, en cuotas (crédito)."""

    CONTADO = "CONTADO", "Contado"
    CREDITO = "CREDITO", "Crédito"


class Moneda(models.TextChoices):
    PEN = "PEN", "Soles"
    USD = "USD", "Dólares"


class Compra(DocumentoInmutable):
    """Comprobante de compra a un proveedor, con sus totales en la moneda del comprobante."""

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", on_delete=models.PROTECT, related_name="compras"
    )
    almacen = models.ForeignKey(
        "mantenimiento.Almacen", on_delete=models.PROTECT, related_name="compras"
    )
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante", on_delete=models.PROTECT, related_name="compras"
    )
    comprobante_serie = models.CharField(max_length=10, blank=True)
    comprobante_numero = models.CharField(max_length=20)
    fecha_emision = models.DateField(db_index=True)
    nro_guia = models.CharField("número de guía", max_length=30, blank=True)
    observacion = models.CharField(max_length=250, blank=True)

    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    # Cómo se escribieron los precios de las líneas: con o sin IGV.
    precios_incluyen_igv = models.BooleanField(default=False)
    # Si el IGV de lo gravado se sumó al costo del inventario (según la empresa en ese momento).
    igv_al_costo = models.BooleanField(default=False)

    # Totales del comprobante, en su moneda.
    op_gravada = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_ivap = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    ivap = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_exonerada = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_inafecta = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    ajuste_redondeo = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2)

    forma_pago = models.CharField(max_length=10, choices=FormaPago.choices)

    # Flete: pagado aparte, con el comprobante de la transportista; siempre en soles.
    flete = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    flete_al_costo = models.BooleanField(default=True)
    flete_comprobante_tipo = models.CharField(max_length=2, blank=True)
    flete_comprobante_serie = models.CharField(max_length=10, blank=True)
    flete_comprobante_numero = models.CharField(max_length=20, blank=True)

    movimiento = models.OneToOneField(
        "inventario.MovimientoInventario", on_delete=models.PROTECT, related_name="compra"
    )
    # La orden de compra contra la que se recibió esta mercadería (si la hubo).
    orden = models.ForeignKey(
        "compras.OrdenCompra",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="compras",
    )

    class Meta:
        verbose_name = "compra"
        verbose_name_plural = "compras"
        ordering = ["-fecha_emision", "-numero"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_compra_numero"),
            models.CheckConstraint(
                condition=Q(total__gte=0) & Q(flete__gte=0), name="ck_compra_no_negativa"
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha_emision"], name="ix_compra_empresa_fecha"),
            models.Index(fields=["empresa", "proveedor"], name="ix_compra_empresa_proveedor"),
        ]

    def __str__(self) -> str:
        return f"Compra {self.numero:06d} · {self.comprobante_serie}-{self.comprobante_numero}"

    @property
    def comprobante(self) -> str:
        serie = f"{self.comprobante_serie}-" if self.comprobante_serie else ""
        return f"{serie}{self.comprobante_numero}"


class LineaCompra(EmpresaScopedModel):
    """Una línea del comprobante: producto, cantidad en la unidad comprada y sus importes."""

    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="lineas")
    orden = models.PositiveSmallIntegerField()
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="lineas_compra"
    )
    presentacion = models.ForeignKey(
        "mantenimiento.PresentacionProducto",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lineas_compra",
    )
    # Copia de la unidad y la equivalencia de ese momento: el historial no cambia si luego se edita.
    unidad = models.CharField(max_length=60)
    factor = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1"))
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    cantidad_base = models.DecimalField(max_digits=14, decimal_places=3)

    afectacion = models.ForeignKey(
        "mantenimiento.AfectacionIGV", on_delete=models.PROTECT, related_name="lineas_compra"
    )
    afectacion_codigo = models.CharField(max_length=2)
    tasa = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))

    precio_unitario = models.DecimalField(max_digits=16, decimal_places=6)
    # Lote o partida que figura en el comprobante (informativo: el stock no se lleva por lote).
    lote = models.CharField(max_length=40, blank=True)
    valor_venta = models.DecimalField(max_digits=16, decimal_places=2)
    impuesto = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2)
    # Lo que entró al inventario por esta línea (en soles): valor, IGV si va al costo y flete.
    costo_soles = models.DecimalField(max_digits=16, decimal_places=2)
    flete_asignado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    # Si se recibió contra una orden: la línea de la orden y el precio que se había pactado
    # (el del comprobante manda; esto deja ver la diferencia después).
    linea_orden = models.ForeignKey(
        "compras.LineaOrdenCompra",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lineas_compra",
    )
    precio_pactado = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)

    class Meta:
        verbose_name = "línea de compra"
        verbose_name_plural = "líneas de compra"
        ordering = ["compra_id", "orden"]
        constraints = [
            models.UniqueConstraint(fields=["compra", "orden"], name="uq_lineacompra_orden"),
            models.CheckConstraint(
                condition=Q(cantidad__gt=0) & Q(cantidad_base__gt=0),
                name="ck_lineacompra_cantidad",
            ),
        ]
        indexes = [models.Index(fields=["producto"], name="ix_lineacompra_producto")]


class PagoCompra(EmpresaScopedModel):
    """Un pago de la compra al contado, o el del flete: con qué método y de qué caja o cuenta."""

    class Tipo(models.TextChoices):
        COMPRA = "COMPRA", "Compra"
        FLETE = "FLETE", "Flete"

    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="pagos")
    tipo = models.CharField(max_length=6, choices=Tipo.choices, default=Tipo.COMPRA)
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="pagos_compra"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="pagos_compra"
    )
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    # Si la caja o cuenta es de otra moneda que la compra: con qué tipo de cambio se convirtió y
    # cuánto salió de verdad de la cuenta (en su moneda). Vacíos = misma moneda, sale ``monto``.
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    monto_cuenta = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    # Al anular la compra (o este pago) queda marcado, no se borra: es rastro de auditoría.
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    @property
    def monto_en_cuenta(self) -> Decimal:
        """Lo que salió de la caja o cuenta, en la moneda de la cuenta."""
        return self.monto_cuenta if self.monto_cuenta is not None else self.monto

    class Meta:
        verbose_name = "pago de compra"
        verbose_name_plural = "pagos de compras"
        ordering = ["compra_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_pagocompra_monto"),
        ]
        indexes = [models.Index(fields=["empresa", "cuenta", "fecha"], name="ix_pagocompra_cuenta")]


class CuotaCompra(EmpresaScopedModel):
    """Una cuota de una compra a crédito: cuánto y para cuándo."""

    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="cuotas")
    numero = models.PositiveSmallIntegerField()
    fecha_vencimiento = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    # Cuánto de la cuota ya se pagó (lo mueven los pagos de Cuentas por pagar).
    pagado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "cuota de compra"
        verbose_name_plural = "cuotas de compras"
        ordering = ["compra_id", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["compra", "numero"], name="uq_cuotacompra_numero"),
            models.CheckConstraint(
                condition=Q(monto__gte=0) & Q(pagado__gte=0), name="ck_cuotacompra_montos"
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha_vencimiento"], name="ix_cuotacompra_vence"),
        ]

    @property
    def saldo(self) -> Decimal:
        return self.monto - self.pagado


class AplicacionPago(EmpresaScopedModel):
    """Cuánto de un pago a crédito se aplicó a cada cuota (un pago puede cubrir varias)."""

    pago = models.ForeignKey(PagoCompra, on_delete=models.PROTECT, related_name="aplicaciones")
    cuota = models.ForeignKey(CuotaCompra, on_delete=models.PROTECT, related_name="aplicaciones")
    monto = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "aplicación de pago"
        verbose_name_plural = "aplicaciones de pagos"
        ordering = ["pago_id", "cuota__numero"]
        constraints = [
            models.UniqueConstraint(fields=["pago", "cuota"], name="uq_aplicacionpago"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_aplicacionpago_monto"),
        ]


class DevolucionCompra(DocumentoInmutable):
    """Nota de crédito del proveedor por mercadería que se le devuelve de una compra.

    Es un documento INMUTABLE: se anula con motivo, no se edita. Siempre nace de una compra
    vigente, hereda su moneda y su IGV y saca del almacén lo devuelto, al costo de esa compra.
    Los importes están en la moneda de la compra; ``costo_soles`` es lo que salió del inventario.
    """

    class Motivo(models.TextChoices):
        TOTAL = "TOTAL", "Devolución total"
        POR_ITEM = "POR_ITEM", "Devolución por ítem"

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    compra = models.ForeignKey(Compra, on_delete=models.PROTECT, related_name="devoluciones")
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", on_delete=models.PROTECT, related_name="devoluciones_compra"
    )
    almacen = models.ForeignKey(
        "mantenimiento.Almacen", on_delete=models.PROTECT, related_name="devoluciones_compra"
    )
    # La nota de crédito que emitió el proveedor.
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante", on_delete=models.PROTECT, related_name="devoluciones"
    )
    comprobante_serie = models.CharField(max_length=10, blank=True)
    comprobante_numero = models.CharField(max_length=20)
    fecha_emision = models.DateField(db_index=True)
    # Total si con ésta ya no queda nada por devolver de la compra; por ítem en otro caso.
    motivo = models.CharField(max_length=10, choices=Motivo.choices)
    razon = models.CharField("por qué se devuelve", max_length=250)

    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    op_gravada = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_ivap = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    ivap = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_exonerada = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_inafecta = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    ajuste_redondeo = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2)
    # Lo que salió del inventario por esta devolución, en soles.
    costo_soles = models.DecimalField(max_digits=16, decimal_places=2)
    # A dónde fue el valor de la nota, en la moneda de la compra: lo que bajó de la deuda, lo que
    # el proveedor devolvió en dinero y lo que quedó como saldo a favor. Suman el total.
    aplicado_a_deuda = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    reembolsado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    saldo_a_favor = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))

    movimiento = models.OneToOneField(
        "inventario.MovimientoInventario",
        on_delete=models.PROTECT,
        related_name="devolucion_compra",
    )

    class Meta:
        verbose_name = "devolución de compra"
        verbose_name_plural = "devoluciones de compras"
        ordering = ["-fecha_emision", "-numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="uq_devolucioncompra_numero"
            ),
            models.CheckConstraint(
                condition=Q(total__gte=0) & Q(costo_soles__gte=0),
                name="ck_devolucioncompra_no_negativa",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha_emision"], name="ix_devcompra_empresa_fecha"),
            models.Index(fields=["empresa", "proveedor"], name="ix_devcompra_empresa_prov"),
            models.Index(fields=["compra", "estado"], name="ix_devcompra_compra_estado"),
        ]

    def __str__(self) -> str:
        return f"Devolución {self.numero:06d} · {self.comprobante_serie}-{self.comprobante_numero}"

    @property
    def comprobante(self) -> str:
        serie = f"{self.comprobante_serie}-" if self.comprobante_serie else ""
        return f"{serie}{self.comprobante_numero}"


class LineaDevolucionCompra(EmpresaScopedModel):
    """Lo devuelto de una línea de la compra: cantidad, importes y costo que salió del almacén."""

    devolucion = models.ForeignKey(
        DevolucionCompra, on_delete=models.PROTECT, related_name="lineas"
    )
    linea_compra = models.ForeignKey(
        LineaCompra, on_delete=models.PROTECT, related_name="devoluciones"
    )
    orden = models.PositiveSmallIntegerField()
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="lineas_devolucion_compra"
    )
    # En la unidad en que se compró (la de la línea de la compra) y en la unidad base.
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    cantidad_base = models.DecimalField(max_digits=14, decimal_places=3)
    valor_venta = models.DecimalField(max_digits=16, decimal_places=2)
    impuesto = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2)
    costo_soles = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "línea de devolución de compra"
        verbose_name_plural = "líneas de devoluciones de compras"
        ordering = ["devolucion_id", "orden"]
        constraints = [
            models.UniqueConstraint(
                fields=["devolucion", "orden"], name="uq_lineadevolucioncompra_orden"
            ),
            models.UniqueConstraint(
                fields=["devolucion", "linea_compra"], name="uq_lineadevolucioncompra_linea"
            ),
            models.CheckConstraint(
                condition=Q(cantidad__gt=0) & Q(cantidad_base__gt=0),
                name="ck_lineadevolucioncompra_cantidad",
            ),
        ]


class AplicacionDevolucion(EmpresaScopedModel):
    """Cuánto de lo que se debía de una cuota canceló una devolución (la cuota bajó de monto)."""

    devolucion = models.ForeignKey(
        DevolucionCompra, on_delete=models.PROTECT, related_name="aplicaciones"
    )
    cuota = models.ForeignKey(
        CuotaCompra, on_delete=models.PROTECT, related_name="aplicaciones_devolucion"
    )
    monto = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "aplicación de devolución"
        verbose_name_plural = "aplicaciones de devoluciones"
        ordering = ["devolucion_id", "cuota__numero"]
        constraints = [
            models.UniqueConstraint(fields=["devolucion", "cuota"], name="uq_aplicaciondevolucion"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_aplicaciondevolucion_monto"),
        ]


class ReembolsoCompra(EmpresaScopedModel):
    """Dinero que el proveedor devolvió por una devolución: a qué caja o cuenta entró."""

    devolucion = models.ForeignKey(
        DevolucionCompra, on_delete=models.PROTECT, related_name="reembolsos"
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="reembolsos_compra"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera",
        on_delete=models.PROTECT,
        related_name="reembolsos_compra",
    )
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)  # en la moneda de la compra
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    # Si la cuenta es de otra moneda que la compra: con qué tipo de cambio y cuánto entró de verdad.
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    monto_cuenta = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)

    @property
    def monto_en_cuenta(self) -> Decimal:
        """Lo que entró a la caja o cuenta, en la moneda de la cuenta."""
        return self.monto_cuenta if self.monto_cuenta is not None else self.monto

    class Meta:
        verbose_name = "reembolso de compra"
        verbose_name_plural = "reembolsos de compras"
        ordering = ["devolucion_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_reembolsocompra_monto"),
        ]
        indexes = [
            models.Index(fields=["empresa", "cuenta", "fecha"], name="ix_reembolsocompra_cuenta")
        ]


class CreditoProveedor(EmpresaScopedModel):
    """Saldo a favor de la empresa con un proveedor, nacido de una devolución ya pagada.

    Se usa después para pagar compras a crédito de ese proveedor, en su misma moneda.
    """

    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", on_delete=models.PROTECT, related_name="creditos"
    )
    # Nace de una devolución pagada O de un anticipo (uno u otro, nunca los dos).
    devolucion = models.OneToOneField(
        DevolucionCompra,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credito",
    )
    anticipo = models.OneToOneField(
        "compras.AnticipoProveedor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credito",
    )
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    usado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    anulado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "crédito con proveedor"
        verbose_name_plural = "créditos con proveedores"
        ordering = ["-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(monto__gt=0) & Q(usado__gte=0) & Q(usado__lte=models.F("monto")),
                name="ck_creditoproveedor_montos",
            ),
            models.CheckConstraint(
                condition=(Q(devolucion__isnull=False) & Q(anticipo__isnull=True))
                | (Q(devolucion__isnull=True) & Q(anticipo__isnull=False)),
                name="ck_creditoproveedor_origen",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "proveedor"], name="ix_creditoprov_emp_prov")]

    @property
    def disponible(self) -> Decimal:
        return Decimal("0") if self.anulado else self.monto - self.usado

    @property
    def fecha_origen(self):
        """La fecha del documento que lo originó (la nota de crédito o el anticipo)."""
        return self.devolucion.fecha_emision if self.devolucion_id else self.anticipo.fecha


class AplicacionCredito(EmpresaScopedModel):
    """Una vez que se usó el saldo a favor de un proveedor para pagar cuotas de una compra."""

    credito = models.ForeignKey(
        CreditoProveedor, on_delete=models.PROTECT, related_name="aplicaciones"
    )
    compra = models.ForeignKey(
        Compra, on_delete=models.PROTECT, related_name="aplicaciones_credito"
    )
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    anulada = models.BooleanField(default=False)
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "aplicación de crédito"
        verbose_name_plural = "aplicaciones de crédito"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_aplicacioncredito_monto"),
        ]
        indexes = [models.Index(fields=["compra", "anulada"], name="ix_aplcredito_compra")]


class DetalleAplicacionCredito(EmpresaScopedModel):
    """Cuánto del crédito aplicado fue a cada cuota (para deshacerlo exactamente)."""

    aplicacion = models.ForeignKey(
        AplicacionCredito, on_delete=models.PROTECT, related_name="detalles"
    )
    cuota = models.ForeignKey(
        CuotaCompra, on_delete=models.PROTECT, related_name="aplicaciones_credito"
    )
    monto = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "detalle de aplicación de crédito"
        verbose_name_plural = "detalles de aplicaciones de crédito"
        ordering = ["aplicacion_id", "cuota__numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["aplicacion", "cuota"], name="uq_detalleaplicacioncredito"
            ),
            models.CheckConstraint(
                condition=Q(monto__gt=0), name="ck_detalleaplicacioncredito_monto"
            ),
        ]


class OrdenCompra(EmpresaScopedModel):
    """Pedido formal a un proveedor, antes de comprar.

    Se edita solo en borrador. Cuando está emitida la mercadería se recibe por partes: cada
    recepción es una compra normal enlazada a la orden (ver la entrega de recepción). Los importes
    se calculan igual que en una compra, en la moneda de la orden.
    """

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        PENDIENTE = "PENDIENTE", "Por aprobar"
        EMITIDA = "EMITIDA", "Emitida"
        PARCIAL = "PARCIAL", "Recibida en parte"
        RECIBIDA = "RECIBIDA", "Recibida"
        CERRADA = "CERRADA", "Cerrada"
        ANULADA = "ANULADA", "Anulada"

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.BORRADOR, db_index=True
    )
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", on_delete=models.PROTECT, related_name="ordenes_compra"
    )
    almacen = models.ForeignKey(
        "mantenimiento.Almacen", on_delete=models.PROTECT, related_name="ordenes_compra"
    )
    fecha_emision = models.DateField(db_index=True)
    fecha_entrega = models.DateField("fecha de entrega esperada", null=True, blank=True)
    observacion = models.CharField(max_length=250, blank=True)

    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    precios_incluyen_igv = models.BooleanField(default=False)
    forma_pago = models.CharField(max_length=10, choices=FormaPago.choices)
    plazo_dias = models.PositiveSmallIntegerField(
        default=0, help_text="Días de crédito que pactó el proveedor (0 si es al contado)."
    )

    # Totales en la moneda de la orden; ``total_soles`` decide si necesita aprobación.
    op_gravada = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_ivap = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    ivap = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_exonerada = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    op_inafecta = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total_soles = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))

    # Quién y cuándo en cada paso (el usuario va sin clave foránea, como en el resto del sistema).
    emitida_en = models.DateTimeField(null=True, blank=True)
    aprobada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    aprobada_en = models.DateTimeField(null=True, blank=True)
    motivo_rechazo = models.CharField(max_length=250, blank=True)
    cerrada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    motivo_cierre = models.CharField(max_length=250, blank=True)
    anulada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)
    # La cotización de la que salió (si se creó al elegir un proveedor ganador).
    cotizacion = models.ForeignKey(
        "compras.SolicitudCotizacion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ordenes",
    )

    class Meta:
        verbose_name = "orden de compra"
        verbose_name_plural = "órdenes de compra"
        ordering = ["-fecha_emision", "-numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_ordencompra_numero",
            ),
            models.CheckConstraint(
                condition=Q(total__gte=0) & Q(total_soles__gte=0), name="ck_ordencompra_total"
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha_emision"], name="ix_ordencompra_empresa_fecha"),
            models.Index(fields=["empresa", "proveedor"], name="ix_ordencompra_empresa_prov"),
            models.Index(fields=["empresa", "estado"], name="ix_ordencompra_empresa_estado"),
        ]

    def __str__(self) -> str:
        return f"OC-{self.numero:06d}"

    @property
    def codigo(self) -> str:
        return f"OC-{self.numero:06d}"


class LineaOrdenCompra(EmpresaScopedModel):
    """Una línea de la orden: qué se pide, en qué cantidad, a qué precio y cuánto ya llegó."""

    orden = models.ForeignKey(OrdenCompra, on_delete=models.PROTECT, related_name="lineas")
    orden_linea = models.PositiveSmallIntegerField("posición")
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="lineas_orden_compra"
    )
    presentacion = models.ForeignKey(
        "mantenimiento.PresentacionProducto",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lineas_orden_compra",
    )
    # Copia de la unidad y la equivalencia de ese momento: el historial no cambia si luego se edita.
    unidad = models.CharField(max_length=60)
    factor = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1"))
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    cantidad_base = models.DecimalField(max_digits=14, decimal_places=3)
    # Lo que ya llegó, en la misma unidad de ``cantidad`` (lo mueven las recepciones).
    cantidad_recibida = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))

    afectacion = models.ForeignKey(
        "mantenimiento.AfectacionIGV", on_delete=models.PROTECT, related_name="lineas_orden_compra"
    )
    afectacion_codigo = models.CharField(max_length=2)
    tasa = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))

    precio_unitario = models.DecimalField(max_digits=16, decimal_places=6)
    valor_venta = models.DecimalField(max_digits=16, decimal_places=2)
    impuesto = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "línea de orden de compra"
        verbose_name_plural = "líneas de órdenes de compra"
        ordering = ["orden_id", "orden_linea"]
        constraints = [
            models.UniqueConstraint(
                fields=["orden", "orden_linea"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_lineaordencompra_posicion",
            ),
            models.CheckConstraint(
                condition=Q(cantidad__gt=0) & Q(cantidad_base__gt=0) & Q(cantidad_recibida__gte=0),
                name="ck_lineaordencompra_cantidad",
            ),
        ]
        indexes = [models.Index(fields=["producto"], name="ix_lineaordencompra_producto")]

    @property
    def pendiente(self) -> Decimal:
        return max(self.cantidad - self.cantidad_recibida, Decimal("0"))


# ---------------------------------------------------------------------------
# Cotizaciones: pedir precios a varios proveedores antes de comprar
# ---------------------------------------------------------------------------
class SolicitudCotizacion(EmpresaScopedModel):
    """Lo que se necesita comprar, para pedir precio a varios proveedores y compararlos.

    No compromete nada: no mueve stock ni deudas. Al elegir ganadores se crean órdenes de compra en
    borrador (una por proveedor). Todos los precios se piden en la misma moneda y con la misma base
    de IGV (con o sin IGV) para que la comparación sea justa.
    """

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        ABIERTA = "ABIERTA", "Abierta"
        ADJUDICADA = "ADJUDICADA", "Adjudicada"
        ANULADA = "ANULADA", "Anulada"

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.BORRADOR, db_index=True
    )
    almacen = models.ForeignKey(
        "mantenimiento.Almacen", on_delete=models.PROTECT, related_name="solicitudes_cotizacion"
    )
    fecha = models.DateField(db_index=True)
    fecha_limite = models.DateField(
        "responder hasta", null=True, blank=True, help_text="Hasta cuándo se esperan respuestas."
    )
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    precios_incluyen_igv = models.BooleanField(default=False)
    observacion = models.CharField(max_length=250, blank=True)
    enviada_en = models.DateTimeField(null=True, blank=True)
    adjudicada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    adjudicada_en = models.DateTimeField(null=True, blank=True)
    anulada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "solicitud de cotización"
        verbose_name_plural = "solicitudes de cotización"
        ordering = ["-fecha", "-numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_solicitudcotizacion_numero",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_solcotiz_empresa_fecha"),
            models.Index(fields=["empresa", "estado"], name="ix_solcotiz_empresa_estado"),
        ]

    def __str__(self) -> str:
        return f"COT-{self.numero:06d}"

    @property
    def codigo(self) -> str:
        return f"COT-{self.numero:06d}"


class LineaSolicitudCotizacion(EmpresaScopedModel):
    """Un producto que se pide cotizar, con la cantidad necesaria."""

    solicitud = models.ForeignKey(
        SolicitudCotizacion, on_delete=models.PROTECT, related_name="lineas"
    )
    posicion = models.PositiveSmallIntegerField()
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="lineas_cotizacion"
    )
    presentacion = models.ForeignKey(
        "mantenimiento.PresentacionProducto",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lineas_cotizacion",
    )
    unidad = models.CharField(max_length=60)
    factor = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1"))
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    # Quién ganó este producto y cuánto se le pidió (lo llena la adjudicación).
    adjudicada_a = models.ForeignKey(
        "compras.RespuestaCotizacion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="lineas_ganadas",
    )
    cantidad_adjudicada = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True
    )

    class Meta:
        verbose_name = "línea de solicitud de cotización"
        verbose_name_plural = "líneas de solicitudes de cotización"
        ordering = ["solicitud_id", "posicion"]
        constraints = [
            models.UniqueConstraint(
                fields=["solicitud", "posicion"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_lineasolcotiz_posicion",
            ),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_lineasolcotiz_cantidad"),
        ]


class RespuestaCotizacion(EmpresaScopedModel):
    """Lo que un proveedor contestó (o todavía no) a una solicitud: sus precios y condiciones."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Sin responder"
        RESPONDIDA = "RESPONDIDA", "Respondida"
        DECLINADA = "DECLINADA", "No cotiza"

    class Origen(models.TextChoices):
        MANUAL = "MANUAL", "Registrada a mano"
        ARCHIVO = "ARCHIVO", "Importada de un archivo"

    solicitud = models.ForeignKey(
        SolicitudCotizacion, on_delete=models.PROTECT, related_name="respuestas"
    )
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", on_delete=models.PROTECT, related_name="respuestas_cotizacion"
    )
    estado = models.CharField(
        max_length=10, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True
    )
    origen = models.CharField(max_length=7, choices=Origen.choices, blank=True)
    forma_pago = models.CharField(max_length=10, choices=FormaPago.choices, blank=True)
    plazo_dias = models.PositiveSmallIntegerField(default=0)
    plazo_entrega_dias = models.PositiveSmallIntegerField(
        default=0, help_text="En cuántos días entrega, contados desde la orden."
    )
    validez_hasta = models.DateField("precios válidos hasta", null=True, blank=True)
    observacion = models.CharField(max_length=250, blank=True)
    respondida_en = models.DateTimeField(null=True, blank=True)
    # La orden de compra que salió de esta respuesta al adjudicar.
    orden = models.ForeignKey(
        OrdenCompra,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="respuestas_origen",
    )

    class Meta:
        verbose_name = "respuesta de cotización"
        verbose_name_plural = "respuestas de cotización"
        ordering = ["solicitud_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["solicitud", "proveedor"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_respcotiz_proveedor",
            ),
        ]


class LineaRespuestaCotizacion(EmpresaScopedModel):
    """El precio que un proveedor dio por un producto (vacío = no lo cotiza)."""

    respuesta = models.ForeignKey(
        RespuestaCotizacion, on_delete=models.PROTECT, related_name="lineas"
    )
    linea = models.ForeignKey(
        LineaSolicitudCotizacion, on_delete=models.PROTECT, related_name="ofertas"
    )
    precio_unitario = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    cantidad_ofrecida = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Si no puede dar todo lo pedido. Vacío = toda la cantidad.",
    )
    observacion = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "línea de respuesta de cotización"
        verbose_name_plural = "líneas de respuestas de cotización"
        constraints = [
            models.UniqueConstraint(
                fields=["respuesta", "linea"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_lineaespcotiz",
            ),
            models.CheckConstraint(
                condition=Q(precio_unitario__isnull=True) | Q(precio_unitario__gte=0),
                name="ck_lineaespcotiz_precio",
            ),
        ]


class AnticipoProveedor(DocumentoInmutable):
    """Dinero que se adelanta a un proveedor antes de recibir la mercadería o de tener su factura.

    Sale de una caja o cuenta al registrarlo y deja un saldo a favor con ese proveedor (el mismo
    que dejan las devoluciones), que luego se usa para pagar sus compras a crédito. Puede estar
    ligado a una orden de compra. Si el proveedor devuelve el dinero, se registra como devolución
    del anticipo.
    """

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    fecha = models.DateField(db_index=True)
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", on_delete=models.PROTECT, related_name="anticipos"
    )
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    glosa = models.CharField(max_length=250, blank=True)
    orden = models.ForeignKey(
        "compras.OrdenCompra",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="anticipos",
    )

    class Meta:
        verbose_name = "anticipo a proveedor"
        verbose_name_plural = "anticipos a proveedores"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_anticipo_numero"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_anticipo_monto"),
        ]
        indexes = [models.Index(fields=["empresa", "proveedor"], name="ix_anticipo_emp_prov")]

    def __str__(self) -> str:
        return f"Anticipo {self.numero:06d}"

    @property
    def codigo(self) -> str:
        return f"ANT-{self.numero:06d}"
