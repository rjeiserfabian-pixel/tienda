"""Ventas: una venta puede salir de una o de dos empresas y emite un comprobante por cada una.

* ``Venta``: lo que el cliente compró en una sola operación (el carrito). Un documento inmutable.
* ``ComprobanteVenta``: el comprobante de UNA empresa (su RUC, su serie y su numeración, su IGV).
* ``LineaVenta``: un producto vendido, con el precio de lista, el precio final, el mínimo
  permitido y el costo con que salió del Kardex (de ahí sale el margen).
* ``CobroVenta``: cada parte del cobro, en la caja o cuenta de la empresa del comprobante.
* ``CuentaDeCobro``: en qué caja o cuenta entra cada método de pago de una empresa.
* ``NotaCredito``: una devolución a un cliente sobre un comprobante: vuelve el stock, se corrigen
  las cuotas por cobrar y se reembolsa lo que ya se había cobrado.
* ``GuiaRemision``: el documento que acompaña la mercadería vendida hasta el cliente.
* ``Proforma``: la cotización de un carrito (no mueve stock ni dinero); se vende después.
* ``LiquidacionTarjeta``: el dinero de las ventas con tarjeta que pasa del POS al banco, menos la
  comisión que retiene el procesador.
* ``VentaInterna``: cuando el carrito mezcla dos empresas y se factura con una sola, lo que la otra
  le «vende» a la que factura, al costo y al contado, para que el stock y el Kardex cuadren.
* ``CuotaVenta``: una cuota de un comprobante vendido a crédito; ``AbonoVenta`` lo que el cliente
  paga después y ``AplicacionAbono`` a qué cuotas se aplicó.

Los precios de lista no incluyen IGV: el impuesto se suma encima según la afectación de la línea.
Nada se edita ni se borra: se anula con motivo y el stock y el dinero vuelven con sus extornos.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q

from apps.core.exceptions import EmpresaNoHabilitada
from apps.core.models import DocumentoInmutable, EmpresaScopedModel
from apps.core.tenant import obtener_contexto

CERO = Decimal("0")


class Moneda(models.TextChoices):
    PEN = "PEN", "Soles"
    USD = "USD", "Dólares"


class FormaPago(models.TextChoices):
    CONTADO = "CONTADO", "Al contado"
    CREDITO = "CREDITO", "A crédito"


class Venta(DocumentoInmutable):
    """El carrito cobrado: agrupa los comprobantes (uno por empresa) de una misma operación."""

    # La empresa donde se hizo la venta (el mostrador); los comprobantes pueden ser de otras.
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    fecha = models.DateField(db_index=True)
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    cliente = models.ForeignKey(
        "mantenimiento.Cliente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ventas",
    )
    # Cómo se llamaba el cliente al vender: el comprobante no cambia si luego edita sus datos.
    cliente_nombre = models.CharField(max_length=250, blank=True)
    cliente_tipo_documento = models.CharField(max_length=10, blank=True)
    cliente_documento = models.CharField(max_length=20, blank=True)

    vendedor_id = models.UUIDField(null=True, blank=True)
    vendedor_nombre = models.CharField(max_length=150, blank=True)

    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    lista = models.ForeignKey(
        "mantenimiento.ListaPrecio",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    forma_pago = models.CharField(
        max_length=10, choices=FormaPago.choices, default=FormaPago.CONTADO
    )
    observacion = models.CharField(max_length=250, blank=True)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    # La proforma que esta venta cumplió, si salió de una.
    proforma = models.ForeignKey(
        "ventas.Proforma",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ventas",
    )

    class Meta:
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_venta_numero"),
            models.CheckConstraint(condition=Q(total__gt=0), name="ck_venta_total"),
        ]
        indexes = [models.Index(fields=["empresa", "fecha"], name="ix_venta_empresa_fecha")]

    def __str__(self) -> str:
        return f"Venta {self.numero:06d}"


class ComprobanteVenta(DocumentoInmutable):
    """El comprobante que emite UNA empresa por lo que ella surtió en la venta."""

    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name="comprobantes")
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante", on_delete=models.PROTECT, related_name="ventas"
    )
    serie_comprobante = models.ForeignKey(
        "mantenimiento.SerieComprobante", on_delete=models.PROTECT, related_name="ventas"
    )
    serie = models.CharField(max_length=10)
    numero = models.PositiveIntegerField()
    fecha = models.DateField(db_index=True)

    op_gravada = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    op_exonerada = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    op_inafecta = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "comprobante de venta"
        verbose_name_plural = "comprobantes de venta"
        ordering = ["-fecha", "-id"]
        constraints = [
            # El número no se vuelve a usar ni siquiera si el comprobante se anula.
            models.UniqueConstraint(
                fields=["empresa", "tipo_comprobante", "serie", "numero"],
                name="uq_comprobanteventa_numero",
            ),
            models.CheckConstraint(condition=Q(total__gt=0), name="ck_comprobanteventa_total"),
            models.CheckConstraint(
                condition=Q(
                    total=F("op_gravada") + F("op_exonerada") + F("op_inafecta") + F("igv")
                ),
                name="ck_comprobanteventa_suma",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_comprobanteventa_fecha"),
        ]

    def __str__(self) -> str:
        return self.numero_completo

    @property
    def numero_completo(self) -> str:
        return f"{self.serie}-{self.numero:08d}"


class LineaVenta(EmpresaScopedModel):
    """Un producto vendido. Los importes están en la moneda de la venta; el costo, en soles."""

    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name="lineas")
    comprobante = models.ForeignKey(
        ComprobanteVenta, on_delete=models.PROTECT, related_name="lineas"
    )
    orden = models.PositiveSmallIntegerField(default=0)
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    # El nombre como salió en el comprobante.
    descripcion = models.CharField(max_length=250)
    almacen = models.ForeignKey(
        "mantenimiento.Almacen", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)

    afectacion = models.ForeignKey(
        "mantenimiento.AfectacionIGV", on_delete=models.PROTECT, related_name="+"
    )
    tasa_igv = models.DecimalField(max_digits=5, decimal_places=2, default=CERO)

    # Precio de la lista elegida, el que se cobró y el mínimo que se permitía (todos SIN IGV).
    lista = models.ForeignKey(
        "mantenimiento.ListaPrecio",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    precio_lista = models.DecimalField(max_digits=16, decimal_places=6)
    precio_unitario = models.DecimalField(max_digits=16, decimal_places=6)
    precio_minimo = models.DecimalField(max_digits=16, decimal_places=6)
    # Se vendió bajo el mínimo con el permiso de un administrador.
    bajo_minimo = models.BooleanField(default=False)

    valor_venta = models.DecimalField(max_digits=16, decimal_places=2)
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=16, decimal_places=2)

    # Lo que costó la mercadería (en soles), tal como salió del Kardex.
    costo_unitario = models.DecimalField(max_digits=16, decimal_places=6, default=CERO)
    costo_total = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    series = models.JSONField(default=list, blank=True)
    movimiento = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "línea de venta"
        verbose_name_plural = "líneas de venta"
        ordering = ["comprobante_id", "orden"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_lineaventa_cantidad"),
            models.CheckConstraint(
                condition=Q(total=F("valor_venta") + F("igv")), name="ck_lineaventa_suma"
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "producto"], name="ix_lineaventa_producto"),
            models.Index(fields=["comprobante", "orden"], name="ix_lineaventa_orden"),
        ]

    def __str__(self) -> str:
        return f"{self.descripcion} × {self.cantidad}"

    def margen(self, tipo_cambio: Decimal) -> Decimal:
        """Utilidad en soles: lo vendido (sin IGV) menos lo que costó."""
        return (self.valor_venta * tipo_cambio).quantize(Decimal("0.01")) - self.costo_total


class CobroVenta(EmpresaScopedModel):
    """Una parte del cobro, en la caja o cuenta de la empresa del comprobante."""

    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name="cobros")
    comprobante = models.ForeignKey(
        ComprobanteVenta, on_delete=models.PROTECT, related_name="cobros"
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="+"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    # Lo cobrado, en la moneda de la venta; y lo que entró a la cuenta, en la moneda de la cuenta.
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    monto_cuenta = models.DecimalField(max_digits=16, decimal_places=2)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    referencia = models.CharField(max_length=60, blank=True)
    # Solo el efectivo: lo que entregó el cliente y el vuelto (el cobro registra lo que se quedó).
    recibido = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    vuelto = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    # Un adelanto que el cliente dejó antes (recibo interno): su dinero ya está en caja desde
    # entonces, así que este cobro no genera otro movimiento.
    es_adelanto = models.BooleanField(default=False)

    class Meta:
        verbose_name = "cobro de venta"
        verbose_name_plural = "cobros de venta"
        ordering = ["comprobante_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_cobroventa_monto"),
            models.CheckConstraint(condition=Q(vuelto__gte=0), name="ck_cobroventa_vuelto"),
        ]
        indexes = [models.Index(fields=["empresa", "creado_en"], name="ix_cobroventa_empresa")]

    def __str__(self) -> str:
        return f"Cobro {self.monto} ({self.medio_pago})"


class CuentaDeCobro(EmpresaScopedModel):
    """En qué caja o cuenta de la empresa entra lo que se cobra con un método de pago.

    Puede ser general (para toda la empresa) o de una sucursal: una billetera Yape por tienda.
    El efectivo, si no se indica nada, entra a la única caja de efectivo de la empresa.
    """

    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="+"
    )
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "cuenta de cobro"
        verbose_name_plural = "cuentas de cobro"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "medio_pago", "sucursal"],
                condition=Q(sucursal__isnull=False, eliminado_en__isnull=True),
                name="uq_cuentadecobro_sucursal",
            ),
            models.UniqueConstraint(
                fields=["empresa", "medio_pago"],
                condition=Q(sucursal__isnull=True, eliminado_en__isnull=True),
                name="uq_cuentadecobro_general",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.medio_pago} → {self.cuenta}"


class CuotaVenta(EmpresaScopedModel):
    """Una cuota de un comprobante vendido a crédito: cuánto y para cuándo.

    Cada empresa cobra lo suyo: una venta de dos empresas a crédito tiene las cuotas de cada
    comprobante por separado, con las mismas fechas.
    """

    comprobante = models.ForeignKey(
        ComprobanteVenta, on_delete=models.PROTECT, related_name="cuotas"
    )
    numero = models.PositiveSmallIntegerField()
    fecha_vencimiento = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    # Cuánto de la cuota ya se cobró (lo mueven los abonos).
    pagado = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)

    class Meta:
        verbose_name = "cuota de venta"
        verbose_name_plural = "cuotas de ventas"
        ordering = ["comprobante_id", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["comprobante", "numero"], name="uq_cuotaventa_numero"),
            # Una nota de crédito puede dejar una cuota en cero: ya no hay nada que cobrar.
            models.CheckConstraint(
                condition=Q(monto__gte=0) & Q(pagado__gte=0) & Q(pagado__lte=F("monto")),
                name="ck_cuotaventa_montos",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha_vencimiento"], name="ix_cuotaventa_vence")
        ]

    @property
    def saldo(self) -> Decimal:
        return self.monto - self.pagado


class AbonoVenta(EmpresaScopedModel):
    """Lo que un cliente paga de una venta a crédito, con un método, a la caja de la empresa."""

    comprobante = models.ForeignKey(
        ComprobanteVenta, on_delete=models.PROTECT, related_name="abonos"
    )
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="+"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    fecha = models.DateField()
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    referencia = models.CharField("número de operación", max_length=60, blank=True)
    recibido = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    vuelto = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    # El recibo que se entregó al cobrar (uno por cobro, aunque se pague con varios métodos).
    recibo = models.ForeignKey(
        "ReciboCobranza", null=True, blank=True, on_delete=models.PROTECT, related_name="abonos"
    )
    # Al anularlo queda marcado, no se borra: es rastro de auditoría.
    anulado = models.BooleanField(default=False)
    anulado_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "abono de venta"
        verbose_name_plural = "abonos de ventas"
        ordering = ["comprobante_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_abonoventa_monto"),
            models.CheckConstraint(condition=Q(vuelto__gte=0), name="ck_abonoventa_vuelto"),
        ]
        indexes = [models.Index(fields=["empresa", "cuenta", "fecha"], name="ix_abonoventa_cuenta")]


class AplicacionAbono(EmpresaScopedModel):
    """Cuánto de un abono se aplicó a cada cuota (un abono puede cubrir varias)."""

    abono = models.ForeignKey(AbonoVenta, on_delete=models.PROTECT, related_name="aplicaciones")
    cuota = models.ForeignKey(CuotaVenta, on_delete=models.PROTECT, related_name="aplicaciones")
    monto = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "aplicación de abono"
        verbose_name_plural = "aplicaciones de abonos"
        ordering = ["abono_id", "cuota__numero"]
        constraints = [
            models.UniqueConstraint(fields=["abono", "cuota"], name="uq_aplicacionabono"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_aplicacionabono_monto"),
        ]


class ReciboCobranza(EmpresaScopedModel):
    """El recibo que se entrega al cliente cuando paga cuotas de una venta a crédito.

    Cada cobro tiene su recibo, con el número de la serie de recibos de la empresa (por ejemplo
    ``RI01``). Un recibo cubre todos los métodos de pago de ese cobro. Si se anulan todos sus
    abonos, el recibo queda anulado; su número no se reutiliza.
    """

    comprobante = models.ForeignKey(
        ComprobanteVenta, on_delete=models.PROTECT, related_name="recibos"
    )
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante", on_delete=models.PROTECT, related_name="+"
    )
    serie_comprobante = models.ForeignKey(
        "mantenimiento.SerieComprobante", on_delete=models.PROTECT, related_name="+"
    )
    serie = models.CharField(max_length=10)
    numero = models.PositiveIntegerField()
    fecha = models.DateField(db_index=True)
    cajero_nombre = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "recibo de cobranza"
        verbose_name_plural = "recibos de cobranza"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_comprobante", "serie", "numero"], name="uq_recibo_numero"
            ),
        ]

    def __str__(self) -> str:
        return self.numero_completo

    @property
    def numero_completo(self) -> str:
        return f"{self.serie}-{self.numero:08d}"


class LiquidacionTarjeta(DocumentoInmutable):
    """Lo que el procesador de tarjetas deposita días después: del POS al banco, menos su comisión.

    Lo cobrado con tarjeta entra a la cuenta del POS al vender. Al liquidar, de esa cuenta sale el
    importe bruto: ``neto`` va al banco (una transferencia) y ``comision`` se asienta como egreso.
    """

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    fecha = models.DateField(db_index=True)
    cuenta_pos = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    cuenta_destino = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    bruto = models.DecimalField(max_digits=16, decimal_places=2)
    comision = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    neto = models.DecimalField(max_digits=16, decimal_places=2)
    referencia = models.CharField("lote o número de operación", max_length=60, blank=True)
    observacion = models.CharField(max_length=250, blank=True)
    transferencia = models.ForeignKey(
        "caja.Transferencia", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "liquidación de tarjeta"
        verbose_name_plural = "liquidaciones de tarjeta"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="uq_liquidaciontarjeta_numero"
            ),
            models.CheckConstraint(
                condition=Q(bruto__gt=0) & Q(comision__gte=0) & Q(neto=F("bruto") - F("comision")),
                name="ck_liquidaciontarjeta_montos",
            ),
        ]

    def __str__(self) -> str:
        return f"Liquidación {self.numero:06d}"


class Proforma(DocumentoInmutable):
    """Cotización: lo que se ofrece a un cliente, con precios e IGV, válida hasta una fecha.

    No toca el stock ni el dinero. Cuando el cliente acepta, se vende desde el punto de venta con
    las mismas líneas (la venta guarda de qué proforma salió). Se puede anular con motivo.
    """

    numero = models.PositiveIntegerField(help_text="Correlativo dentro de su serie.")
    # La serie de proformas con que se numeró (P001…); las anteriores a las series no la tienen.
    serie = models.CharField(max_length=10, blank=True)
    serie_comprobante = models.ForeignKey(
        "mantenimiento.SerieComprobante",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    fecha = models.DateField(db_index=True)
    valida_hasta = models.DateField()
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Un cliente registrado, o solo el nombre de quien pidió la cotización.
    cliente = models.ForeignKey(
        "mantenimiento.Cliente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proformas",
    )
    cliente_nombre = models.CharField(max_length=250, blank=True)
    cliente_documento = models.CharField(max_length=20, blank=True)
    cliente_contacto = models.CharField("teléfono o correo", max_length=120, blank=True)
    vendedor_id = models.UUIDField(null=True, blank=True)
    vendedor_nombre = models.CharField(max_length=150, blank=True)
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    lista = models.ForeignKey(
        "mantenimiento.ListaPrecio",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    condiciones = models.CharField("condiciones u observación", max_length=500, blank=True)
    # Con qué precios se cotizó: contado (lista elegida) o crédito (la lista de crédito).
    forma_pago = models.CharField(
        max_length=10, choices=FormaPago.choices, default=FormaPago.CONTADO
    )
    cliente_direccion = models.CharField("dirección del cliente", max_length=250, blank=True)
    fecha_entrega = models.DateField(null=True, blank=True)
    atencion = models.CharField("con atención a", max_length=120, blank=True)
    lugar_entrega = models.CharField(max_length=250, blank=True)
    total = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "proforma"
        verbose_name_plural = "proformas"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "serie", "numero"], name="uq_proforma_serie_numero"
            ),
            models.CheckConstraint(condition=Q(total__gt=0), name="ck_proforma_total"),
        ]
        indexes = [models.Index(fields=["empresa", "fecha"], name="ix_proforma_empresa_fecha")]

    @property
    def numero_completo(self) -> str:
        """``P001-00000012``; las anteriores a las series se muestran con su número de 6 cifras."""
        return f"{self.serie}-{self.numero:08d}" if self.serie else f"{self.numero:06d}"

    def __str__(self) -> str:
        return f"Proforma {self.numero_completo}"


class LineaProforma(EmpresaScopedModel):
    """Un producto cotizado. La empresa de la línea es la que lo surtiría al vender."""

    proforma = models.ForeignKey(Proforma, on_delete=models.PROTECT, related_name="lineas")
    orden = models.PositiveSmallIntegerField(default=0)
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    descripcion = models.CharField(max_length=250)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    afectacion = models.ForeignKey(
        "mantenimiento.AfectacionIGV", on_delete=models.PROTECT, related_name="+"
    )
    tasa_igv = models.DecimalField(max_digits=5, decimal_places=2, default=CERO)
    precio_lista = models.DecimalField(max_digits=16, decimal_places=6)
    precio_unitario = models.DecimalField(max_digits=16, decimal_places=6)
    valor_venta = models.DecimalField(max_digits=16, decimal_places=2)
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "línea de proforma"
        verbose_name_plural = "líneas de proforma"
        ordering = ["proforma_id", "orden"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_lineaproforma_cantidad"),
        ]

    def __str__(self) -> str:
        return f"{self.descripcion} × {self.cantidad}"


class MotivoNota(models.TextChoices):
    """Motivos de una nota de crédito (los que devuelven mercadería, del catálogo 09 de SUNAT)."""

    ANULACION = "01", "Anulación de la operación"
    DEVOLUCION_TOTAL = "06", "Devolución total"
    DEVOLUCION_ITEM = "07", "Devolución por ítem"


# Los motivos que devuelven todo lo que queda del comprobante, sin elegir líneas.
MOTIVOS_TOTALES = (MotivoNota.ANULACION, MotivoNota.DEVOLUCION_TOTAL)


class NotaCredito(DocumentoInmutable):
    """Devolución a un cliente sobre un comprobante de la empresa.

    Tiene su propia serie y numeración. Lo devuelto vuelve al almacén al costo con que salió; si el
    comprobante era a crédito, primero reduce lo que el cliente debe y solo el resto se reembolsa.
    """

    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name="notas_credito")
    comprobante = models.ForeignKey(
        ComprobanteVenta, on_delete=models.PROTECT, related_name="notas_credito"
    )
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante", on_delete=models.PROTECT, related_name="+"
    )
    serie_comprobante = models.ForeignKey(
        "mantenimiento.SerieComprobante", on_delete=models.PROTECT, related_name="+"
    )
    serie = models.CharField(max_length=10)
    numero = models.PositiveIntegerField()
    fecha = models.DateField(db_index=True)
    motivo = models.CharField(max_length=2, choices=MotivoNota.choices)
    descripcion = models.CharField(max_length=250, blank=True)
    reingresa_stock = models.BooleanField(default=True)
    emitida_por_id = models.UUIDField(null=True, blank=True)
    emitida_por_nombre = models.CharField(max_length=150, blank=True)

    op_gravada = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    op_exonerada = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    op_inafecta = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    # Cuánto del total redujo lo que el cliente debía y cuánto se le devolvió en dinero.
    a_cuotas = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    reembolsado = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)

    class Meta:
        verbose_name = "nota de crédito"
        verbose_name_plural = "notas de crédito"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_comprobante", "serie", "numero"],
                name="uq_notacredito_numero",
            ),
            models.CheckConstraint(condition=Q(total__gt=0), name="ck_notacredito_total"),
            models.CheckConstraint(
                condition=Q(
                    total=F("op_gravada") + F("op_exonerada") + F("op_inafecta") + F("igv")
                ),
                name="ck_notacredito_suma",
            ),
            models.CheckConstraint(
                condition=Q(total=F("a_cuotas") + F("reembolsado")), name="ck_notacredito_destino"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "fecha"], name="ix_notacredito_fecha")]

    def __str__(self) -> str:
        return self.numero_completo

    @property
    def numero_completo(self) -> str:
        return f"{self.serie}-{self.numero:08d}"


class LineaNotaCredito(EmpresaScopedModel):
    """Lo que se devuelve de una línea de la venta."""

    nota = models.ForeignKey(NotaCredito, on_delete=models.PROTECT, related_name="lineas")
    linea_venta = models.ForeignKey(
        LineaVenta, on_delete=models.PROTECT, related_name="devoluciones"
    )
    orden = models.PositiveSmallIntegerField(default=0)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    valor_venta = models.DecimalField(max_digits=16, decimal_places=2)
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    total = models.DecimalField(max_digits=16, decimal_places=2)
    # El costo (en soles) con que vuelve al almacén; sirve para descontar la utilidad devuelta.
    costo_total = models.DecimalField(max_digits=16, decimal_places=2, default=CERO)
    series = models.JSONField(default=list, blank=True)
    movimiento = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "línea de nota de crédito"
        verbose_name_plural = "líneas de notas de crédito"
        ordering = ["nota_id", "orden"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="ck_lineanotacredito_cantidad"
            ),
        ]


class ReembolsoNota(EmpresaScopedModel):
    """Dinero que sale de una caja o cuenta para devolverlo al cliente."""

    nota = models.ForeignKey(NotaCredito, on_delete=models.PROTECT, related_name="reembolsos")
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="+"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    referencia = models.CharField("número de operación", max_length=60, blank=True)

    class Meta:
        verbose_name = "reembolso de nota de crédito"
        verbose_name_plural = "reembolsos de notas de crédito"
        ordering = ["nota_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_reembolsonota_monto")
        ]


class ReduccionCuota(EmpresaScopedModel):
    """Cuánto bajó una nota de crédito de cada cuota que el cliente todavía debía."""

    nota = models.ForeignKey(NotaCredito, on_delete=models.PROTECT, related_name="reducciones")
    cuota = models.ForeignKey(CuotaVenta, on_delete=models.PROTECT, related_name="reducciones")
    monto = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "reducción de cuota"
        verbose_name_plural = "reducciones de cuotas"
        ordering = ["nota_id", "cuota__numero"]
        constraints = [
            models.UniqueConstraint(fields=["nota", "cuota"], name="uq_reduccioncuota"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_reduccioncuota_monto"),
        ]


class MotivoTraslado(models.TextChoices):
    """Motivos de traslado del catálogo 20 de SUNAT que se usan con ventas."""

    VENTA = "01", "Venta"
    ENTRE_ESTABLECIMIENTOS = "04", "Traslado entre establecimientos de la misma empresa"
    OTROS = "13", "Otros"


class ModalidadTransporte(models.TextChoices):
    PUBLICO = "01", "Transporte público (lo lleva una empresa de transporte)"
    PRIVADO = "02", "Transporte privado (lo lleva la propia empresa o el cliente)"


class GuiaRemision(DocumentoInmutable):
    """Guía de remisión del remitente: qué se envía, a dónde y quién lo transporta.

    Es un documento interno que se numera con su propia serie (tipo 09). No mueve stock. Sale de
    una de dos cosas:

    * **Un comprobante de venta:** la mercadería ya salió con la venta. De un comprobante pueden
      salir varias guías (envíos parciales) sin pasar nunca de lo vendido.
    * **Un traspaso entre almacenes:** el stock ya se movió con el traspaso (``movimiento_salida``
      es su mitad de salida). Viaja todo lo traspasado y hay una sola guía vigente por traspaso.
    """

    comprobante = models.ForeignKey(
        ComprobanteVenta, null=True, blank=True, on_delete=models.PROTECT, related_name="guias"
    )
    movimiento_salida = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="guias_de_traslado",
    )
    tipo_comprobante = models.ForeignKey(
        "mantenimiento.TipoComprobante", on_delete=models.PROTECT, related_name="+"
    )
    serie_comprobante = models.ForeignKey(
        "mantenimiento.SerieComprobante", on_delete=models.PROTECT, related_name="+"
    )
    serie = models.CharField(max_length=10)
    numero = models.PositiveIntegerField()
    fecha_emision = models.DateField(db_index=True)
    fecha_traslado = models.DateField()
    motivo = models.CharField(max_length=2, choices=MotivoTraslado.choices)
    modalidad = models.CharField(max_length=2, choices=ModalidadTransporte.choices)

    # A quién va: por defecto el cliente de la venta, pero puede ser otro cliente registrado.
    destinatario = models.ForeignKey(
        "mantenimiento.Cliente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    destinatario_nombre = models.CharField(max_length=250)
    destinatario_tipo_documento = models.CharField(max_length=10, blank=True)
    destinatario_documento = models.CharField(max_length=20, blank=True)
    punto_partida = models.CharField(max_length=250)
    ubigeo_partida = models.CharField(max_length=6, blank=True)
    punto_llegada = models.CharField(max_length=250)
    ubigeo_llegada = models.CharField(max_length=6, blank=True)
    almacen_origen = models.ForeignKey(
        "mantenimiento.Almacen",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    # Traslado en vehículos de categoría M1 o L (livianos): no exige conductor ni placa.
    traslado_m1_l = models.BooleanField(default=False)

    # Quién lo lleva. Se guardan los datos tal como estaban al emitir (el catálogo puede cambiar).
    transportista = models.ForeignKey(
        "mantenimiento.EmpresaTransporte",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    transportista_nombre = models.CharField(max_length=250, blank=True)
    transportista_documento = models.CharField(max_length=20, blank=True)
    transportista_mtc = models.CharField(max_length=30, blank=True)
    transportista_certificado = models.CharField(max_length=30, blank=True)
    conductor = models.ForeignKey(
        "mantenimiento.Conductor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    conductor_nombre = models.CharField(max_length=150, blank=True)
    conductor_documento = models.CharField(max_length=20, blank=True)
    conductor_licencia = models.CharField(max_length=20, blank=True)
    vehiculo = models.ForeignKey(
        "mantenimiento.Vehiculo",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    placa = models.CharField(max_length=10, blank=True)
    vehiculo_descripcion = models.CharField(max_length=120, blank=True)
    placas_secundarias = models.JSONField(default=list, blank=True)
    peso_kg = models.DecimalField(max_digits=12, decimal_places=3, default=CERO)
    bultos = models.PositiveIntegerField(default=1)
    observacion = models.CharField(max_length=250, blank=True)
    emitida_por_nombre = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "guía de remisión"
        verbose_name_plural = "guías de remisión"
        ordering = ["-fecha_emision", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_comprobante", "serie", "numero"], name="uq_guia_numero"
            ),
            # Sale de un comprobante o de un traspaso, nunca de los dos ni de ninguno.
            models.CheckConstraint(
                condition=(Q(comprobante__isnull=False) & Q(movimiento_salida__isnull=True))
                | (Q(comprobante__isnull=True) & Q(movimiento_salida__isnull=False)),
                name="ck_guia_un_origen",
            ),
            # Un traspaso tiene una sola guía vigente (si se anula, se puede emitir otra).
            models.UniqueConstraint(
                fields=["movimiento_salida"],
                condition=Q(estado="EMITIDO", movimiento_salida__isnull=False),
                name="uq_guia_traspaso_vigente",
            ),
        ]

    def __str__(self) -> str:
        return self.numero_completo

    @property
    def numero_completo(self) -> str:
        return f"{self.serie}-{self.numero:08d}"


class LineaGuia(EmpresaScopedModel):
    """Lo que viaja en la guía: una línea de la venta (o un producto traspasado) y la cantidad."""

    guia = models.ForeignKey(GuiaRemision, on_delete=models.PROTECT, related_name="lineas")
    linea_venta = models.ForeignKey(
        LineaVenta, null=True, blank=True, on_delete=models.PROTECT, related_name="envios"
    )
    # En la guía de un traspaso no hay línea de venta: se guarda el producto que viaja.
    producto = models.ForeignKey(
        "mantenimiento.Producto", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    orden = models.PositiveSmallIntegerField(default=0)
    descripcion = models.CharField(max_length=250)
    unidad = models.CharField(max_length=10, blank=True)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    peso_kg = models.DecimalField(max_digits=12, decimal_places=3, default=CERO)

    class Meta:
        verbose_name = "línea de guía"
        verbose_name_plural = "líneas de guías"
        ordering = ["guia_id", "orden"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_lineaguia_cantidad"),
            models.CheckConstraint(
                condition=Q(linea_venta__isnull=False) | Q(producto__isnull=False),
                name="ck_lineaguia_origen",
            ),
        ]


class DocumentoInterno(models.TextChoices):
    """Con qué respaldo pasa la mercadería de una empresa a la otra."""

    INTERNO = "INTERNO", "Documento interno"
    FACTURA = "FACTURA", "Factura electrónica"


class VentaInterna(DocumentoInmutable):
    """La venta de una empresa a la otra para poder facturar todo con un solo comprobante.

    ``empresa`` es la que ENTREGA la mercadería y ``empresa_destino`` la que la recibe y factura
    al cliente. Pasa al costo (el costo promedio del Kardex de quien entrega, sin margen) y al
    contado: no deja deuda entre las empresas. La mercadería sale del almacén de una y entra al
    de la otra en la misma operación que la venta al cliente.
    """

    # Une las dos mitades (salida y entrada) en el Kardex de cada empresa (``traspaso_id``).
    codigo = models.UUIDField(unique=True, editable=False)
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    fecha = models.DateField(db_index=True)
    empresa_destino = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="+"
    )
    # La venta al cliente que motivó este traslado (la del comprobante único). Sin venta es un
    # «traslado entre empresas»: mercadería que pasa de una empresa a la otra sin vender a nadie.
    venta = models.ForeignKey(
        Venta, null=True, blank=True, on_delete=models.PROTECT, related_name="ventas_internas"
    )
    # Solo en un traslado sin venta: la tienda desde la que se entrega (agrupa lo que se liquida).
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    observacion = models.CharField(max_length=250, blank=True)
    documento = models.CharField(
        max_length=10, choices=DocumentoInterno.choices, default=DocumentoInterno.INTERNO
    )
    # Lo que costó la mercadería trasladada (soles): es también lo que vale la operación.
    total_costo = models.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        verbose_name = "venta interna"
        verbose_name_plural = "ventas internas"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_ventainterna_numero"),
            models.CheckConstraint(condition=Q(total_costo__gt=0), name="ck_ventainterna_costo"),
            models.CheckConstraint(
                condition=~Q(empresa=F("empresa_destino")), name="ck_ventainterna_empresas"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "fecha"], name="ix_ventainterna_fecha")]

    def __str__(self) -> str:
        return f"Venta interna {self.numero:06d}"

    def validar_ambito(self) -> None:
        super().validar_ambito()
        contexto = obtener_contexto()
        if contexto is not None and not contexto.empresa_habilitada(self.empresa_destino_id):
            raise EmpresaNoHabilitada()


class LineaVentaInterna(EmpresaScopedModel):
    """Un producto trasladado, con el costo al que salió y los dos movimientos del Kardex."""

    venta_interna = models.ForeignKey(VentaInterna, on_delete=models.PROTECT, related_name="lineas")
    orden = models.PositiveSmallIntegerField(default=0)
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    descripcion = models.CharField(max_length=250)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    # La línea de la venta al cliente que salió de esta mercadería: sabiendo cuál es, una
    # devolución sabe qué parte vuelve a la empresa que la entregó.
    linea_venta = models.OneToOneField(
        "ventas.LineaVenta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="origen_interno",
    )
    # Salió al costo promedio del almacén que entrega (soles); así entró al que recibe.
    costo_unitario = models.DecimalField(max_digits=16, decimal_places=6)
    costo_total = models.DecimalField(max_digits=16, decimal_places=2)
    series = models.JSONField(default=list, blank=True)
    # Un repuesto del taller ya salió del stock al usarse en la reparación: no hay almacén de
    # destino ni movimientos (solo queda la deuda por su costo con la empresa que lo surtió).
    almacen_origen = models.ForeignKey(
        "mantenimiento.Almacen", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    almacen_destino = models.ForeignKey(
        "mantenimiento.Almacen", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    movimiento_salida = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    movimiento_entrada = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "línea de venta interna"
        verbose_name_plural = "líneas de venta interna"
        ordering = ["venta_interna_id", "orden"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_lineaventainterna_cant"),
        ]

    def __str__(self) -> str:
        return f"{self.descripcion} × {self.cantidad}"


class DevolucionInterna(EmpresaScopedModel):
    """Lo que volvió a la empresa que entregó cuando el cliente devolvió mercadería de una venta
    interna (``empresa`` es la que entregó). Vuelve al mismo costo con que salió."""

    venta_interna = models.ForeignKey(
        VentaInterna, on_delete=models.PROTECT, related_name="devoluciones"
    )
    nota = models.ForeignKey(
        "ventas.NotaCredito", on_delete=models.PROTECT, related_name="devoluciones_internas"
    )
    linea = models.ForeignKey(
        LineaVentaInterna, on_delete=models.PROTECT, related_name="devoluciones"
    )
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    costo_total = models.DecimalField(max_digits=16, decimal_places=2)
    series = models.JSONField(default=list, blank=True)
    movimiento_salida = models.ForeignKey(
        "inventario.MovimientoInventario", on_delete=models.PROTECT, related_name="+"
    )
    movimiento_entrada = models.ForeignKey(
        "inventario.MovimientoInventario", on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        verbose_name = "devolución de venta interna"
        verbose_name_plural = "devoluciones de ventas internas"
        ordering = ["venta_interna_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_devolucioninterna_cant"),
        ]

    def __str__(self) -> str:
        return f"Devolución interna × {self.cantidad}"


class LiquidacionInterna(DocumentoInmutable):
    """El cierre de cuentas entre las dos empresas por sus ventas internas.

    ``empresa`` es la que PAGA (a lo neto le debía más a la otra) y ``empresa_destino`` la que
    recibe. Junta todas las partidas pendientes de un local (las ventas, menos las devoluciones y
    anulaciones) y las salda con UNA transferencia entre sus cajas o cuentas. Si las deudas se
    compensan exactamente, no hay transferencia y el monto es cero.
    """

    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa que paga.")
    empresa_destino = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="+"
    )
    # La tienda donde se vendió (para elegir las cajas) y el local físico que agrupa las partidas.
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    local = models.CharField(max_length=60, blank=True)
    fecha = models.DateField(db_index=True)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    transferencia = models.ForeignKey(
        "caja.Transferencia", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    referencia = models.CharField(max_length=60, blank=True)
    observacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "liquidación interna"
        verbose_name_plural = "liquidaciones internas"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="uq_liquidacioninterna_numero"
            ),
            models.CheckConstraint(condition=Q(monto__gte=0), name="ck_liquidacioninterna_monto"),
            models.CheckConstraint(
                condition=~Q(empresa=F("empresa_destino")), name="ck_liquidacioninterna_empresas"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "fecha"], name="ix_liqinterna_fecha")]

    def __str__(self) -> str:
        return f"Liquidación interna {self.numero:06d}"

    def validar_ambito(self) -> None:
        super().validar_ambito()
        contexto = obtener_contexto()
        if contexto is not None and not contexto.empresa_habilitada(self.empresa_destino_id):
            raise EmpresaNoHabilitada()


class MotivoDeuda(models.TextChoices):
    VENTA = "VENTA", "Venta interna"
    DEVOLUCION = "DEVOLUCION", "Devolución del cliente"
    ANULACION = "ANULACION", "Anulación de la venta"


class OrigenDeuda(models.TextChoices):
    VENTA_INTERNA = "VENTA_INTERNA", "Venta interna entre empresas"
    COBRO_TIENDA = "COBRO_TIENDA", "Cobro de la tienda virtual"


class DeudaInterna(EmpresaScopedModel):
    """Una partida de lo que una empresa le debe a la otra por una venta interna.

    ``empresa`` es la DEUDORA. Una venta interna suma una partida (la que factura le debe a la que
    entregó, al costo); una devolución o una anulación suma otra en sentido contrario. Lo que una
    empresa debe en neto es la suma de sus partidas sin liquidar menos las de la otra. Al liquidar,
    cada partida queda ligada a su liquidación; si esta se anula, se sueltan.
    """

    acreedora = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="+"
    )
    # De dónde viene la partida: una venta interna (lleva ``venta_interna``) o un cobro de la tienda
    # virtual que una empresa recibió por cuenta de la otra (lleva ``origen_id``: el id de la
    # ``DeudaCobroTienda`` y ``referencia``: el número del pedido; ``ventas`` no conoce ese modelo).
    origen = models.CharField(
        max_length=14, choices=OrigenDeuda.choices, default=OrigenDeuda.VENTA_INTERNA
    )
    origen_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    referencia = models.CharField(max_length=60, blank=True)
    venta_interna = models.ForeignKey(
        VentaInterna, null=True, blank=True, on_delete=models.PROTECT, related_name="partidas"
    )
    devolucion = models.ForeignKey(
        DevolucionInterna, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    motivo = models.CharField(max_length=10, choices=MotivoDeuda.choices)
    fecha = models.DateField(db_index=True)
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # El local físico (o la tienda, si no tiene) en que se vendió: agrupa lo que se liquida junto.
    local = models.CharField(max_length=60, blank=True, db_index=True)
    liquidacion = models.ForeignKey(
        LiquidacionInterna,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="partidas",
    )

    class Meta:
        verbose_name = "deuda interna"
        verbose_name_plural = "deudas internas"
        ordering = ["fecha", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_deudainterna_monto"),
            models.CheckConstraint(
                condition=~Q(empresa=F("acreedora")), name="ck_deudainterna_empresas"
            ),
            # Cada partida tiene su origen: una venta interna o un cobro de la tienda.
            models.CheckConstraint(
                condition=(
                    Q(origen="VENTA_INTERNA", venta_interna__isnull=False)
                    | Q(origen="COBRO_TIENDA", origen_id__isnull=False)
                ),
                name="ck_deudainterna_origen",
            ),
            # Un cobro de la tienda deja una sola partida por cada motivo (no se duplica).
            models.UniqueConstraint(
                fields=["origen", "origen_id", "motivo"],
                condition=Q(origen="COBRO_TIENDA", eliminado_en__isnull=True),
                name="uq_deudainterna_cobro_tienda",
            ),
        ]
        indexes = [
            models.Index(fields=["local", "liquidacion"], name="ix_deudainterna_pendiente"),
        ]

    def __str__(self) -> str:
        return f"{self.get_motivo_display()}: {self.monto}"


class TransferenciaPuente(models.Model):
    """Una transferencia de «reconocimiento» de una liquidación de cobros de la tienda virtual.

    Cuando una empresa cobró con Culqi lo que era de la otra, ese dinero quedó anotado en la cuenta
    puente de la otra. Al liquidar, primero se pasa de esa cuenta puente a la cuenta de Culqi de
    quien cobró (donde el dinero está de verdad) y recién después esa empresa paga lo neto. Cada
    transferencia queda ligada a su liquidación para poder deshacerla en orden.
    """

    liquidacion = models.ForeignKey(
        LiquidacionInterna, on_delete=models.PROTECT, related_name="transferencias_puente"
    )
    transferencia = models.ForeignKey(
        "caja.Transferencia", on_delete=models.PROTECT, related_name="+"
    )
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "transferencia puente de una liquidación"
        verbose_name_plural = "transferencias puente de liquidaciones"
        ordering = ["orden", "id"]

    def __str__(self) -> str:
        return f"Puente de la liquidación {self.liquidacion_id}"
