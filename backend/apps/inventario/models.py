"""Inventario: existencias por almacén, movimientos (Kardex) y cierre de periodos.

Todo es de una EMPRESA (cada RUC lleva su propio stock y su propio costo); los productos son del
catálogo de la organización. El movimiento es un documento inmutable: solo se anula, y la
anulación crea un movimiento inverso (extorno) para que el Kardex conserve el rastro completo.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.models import DocumentoInmutable, EmpresaScopedModel


class TipoMovimiento(models.TextChoices):
    ENTRADA = "ENTRADA", "Entrada"
    SALIDA = "SALIDA", "Salida"


class OrigenMovimiento(models.TextChoices):
    COMPRA = "COMPRA", "Compra"
    VENTA = "VENTA", "Venta"
    DEVOLUCION_CLIENTE = "DEVOLUCION_CLIENTE", "Devolución de un cliente"
    DEVOLUCION_PROVEEDOR = "DEVOLUCION_PROVEEDOR", "Devolución a un proveedor"
    SALDO_INICIAL = "SALDO_INICIAL", "Saldo inicial"
    AJUSTE = "AJUSTE", "Ajuste de inventario"
    MERMA = "MERMA", "Merma o desmedro"
    TRASPASO = "TRASPASO", "Traspaso entre almacenes"
    SERVICIO_TECNICO = "SERVICIO_TECNICO", "Repuestos usados en un servicio técnico"
    VENTA_INTERNA = "VENTA_INTERNA", "Venta interna entre empresas"
    TRASLADO_EMPRESAS = "TRASLADO_EMPRESAS", "Traslado entre empresas"
    EXTORNO = "EXTORNO", "Extorno por anulación"


class Moneda(models.TextChoices):
    PEN = "PEN", "Soles"
    USD = "USD", "Dólares"


class SaldoStock(EmpresaScopedModel):
    """Existencias actuales de un producto en un almacén, con su costo promedio.

    Es una tabla de trabajo: siempre coincide con el saldo de la última línea del Kardex. Solo
    la modifican los servicios de ``movimientos``, con la fila bloqueada.
    """

    almacen = models.ForeignKey("mantenimiento.Almacen", on_delete=models.PROTECT)
    producto = models.ForeignKey("mantenimiento.Producto", on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    costo_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    costo_unitario = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal("0"))

    class Meta:
        verbose_name = "saldo de stock"
        verbose_name_plural = "saldos de stock"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "almacen", "producto"], name="uq_saldostock_almacen_producto"
            ),
            models.CheckConstraint(
                condition=Q(cantidad__gte=0) & Q(costo_total__gte=0),
                name="ck_saldostock_no_negativo",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "producto"], name="ix_saldostock_producto")]

    def __str__(self) -> str:
        return f"{self.producto_id} @ {self.almacen_id}: {self.cantidad}"


class MovimientoInventario(DocumentoInmutable):
    """Cabecera de un movimiento (una compra, una venta, un ajuste…) en un almacén."""

    almacen = models.ForeignKey(
        "mantenimiento.Almacen", on_delete=models.PROTECT, related_name="movimientos"
    )
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    tipo = models.CharField(max_length=7, choices=TipoMovimiento.choices)
    origen = models.CharField(max_length=20, choices=OrigenMovimiento.choices)
    # Tabla 12 de SUNAT (ver ``catalogos``).
    tipo_operacion = models.CharField(max_length=2)
    fecha = models.DateField(db_index=True)
    periodo = models.CharField(max_length=6, db_index=True, editable=False, help_text="AAAAMM")

    # Comprobante que respalda el movimiento (tabla 10 de SUNAT).
    comprobante_tipo = models.CharField(max_length=2, blank=True)
    comprobante_serie = models.CharField(max_length=10, blank=True)
    comprobante_numero = models.CharField(max_length=20, blank=True)
    comprobante_fecha = models.DateField(null=True, blank=True)
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor", null=True, blank=True, on_delete=models.PROTECT
    )
    cliente = models.ForeignKey(
        "mantenimiento.Cliente", null=True, blank=True, on_delete=models.PROTECT
    )

    # Importes del comprobante en SU moneda; el costo del inventario siempre va en soles.
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    tipo_cambio = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1"))
    precios_incluyen_igv = models.BooleanField(default=False)
    igv_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    subtotal = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    igv = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))

    observacion = models.CharField(max_length=250, blank=True)
    # Vínculo con el documento de origen de otro módulo (venta, compra…).
    referencia_tipo = models.CharField(max_length=30, blank=True)
    referencia_id = models.PositiveBigIntegerField(null=True, blank=True)
    # Un traspaso entre almacenes son DOS movimientos (salida y entrada) que comparten este código.
    traspaso_id = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    # Si es un extorno, el movimiento que anula.
    extorna = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="extorno"
    )

    class Meta:
        verbose_name = "movimiento de inventario"
        verbose_name_plural = "movimientos de inventario"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="uq_movinv_numero_por_empresa"
            ),
            # El comprobante de un proveedor no se registra dos veces (mientras no esté anulado).
            models.UniqueConstraint(
                fields=[
                    "empresa",
                    "proveedor",
                    "comprobante_tipo",
                    "comprobante_serie",
                    "comprobante_numero",
                ],
                condition=Q(estado="EMITIDO", proveedor__isnull=False) & ~Q(comprobante_numero=""),
                name="uq_movinv_comprobante_proveedor",
            ),
            # Los comprobantes propios de salida (ventas) tampoco se repiten.
            models.UniqueConstraint(
                fields=["empresa", "comprobante_tipo", "comprobante_serie", "comprobante_numero"],
                condition=Q(estado="EMITIDO", tipo="SALIDA", origen="VENTA")
                & ~Q(comprobante_numero=""),
                name="uq_movinv_comprobante_venta",
            ),
            models.CheckConstraint(
                condition=~(Q(proveedor__isnull=False) & Q(cliente__isnull=False)),
                name="ck_movinv_un_solo_tercero",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "fecha"], name="ix_movinv_empresa_fecha"),
            models.Index(fields=["empresa", "periodo"], name="ix_movinv_empresa_periodo"),
            models.Index(fields=["almacen", "fecha"], name="ix_movinv_almacen_fecha"),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} N° {self.numero:06d} ({self.fecha})"

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.periodo = f"{self.fecha:%Y%m}"
        super().save(*args, **kwargs)


class LineaMovimiento(EmpresaScopedModel):
    """Un producto dentro de un movimiento, con el saldo que quedó DESPUÉS de aplicarlo.

    Guardar el saldo en cada línea evita recalcular todo el historial al consultar el Kardex.
    Solo el servicio de movimientos escribe aquí: al registrar un movimiento con fecha atrasada
    se recalculan las líneas posteriores del mismo producto y almacén.
    """

    movimiento = models.ForeignKey(
        MovimientoInventario, on_delete=models.PROTECT, related_name="lineas"
    )
    # Copias de la cabecera que ordenan y filtran el Kardex sin unir tablas.
    almacen = models.ForeignKey("mantenimiento.Almacen", on_delete=models.PROTECT)
    fecha = models.DateField()
    tipo = models.CharField(max_length=7, choices=TipoMovimiento.choices)
    producto = models.ForeignKey("mantenimiento.Producto", on_delete=models.PROTECT)
    orden = models.PositiveSmallIntegerField(default=0)

    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    # Precio tal como figura en el comprobante (en su moneda). Las salidas pueden no tenerlo.
    precio_unitario = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    # Valor del movimiento en SOLES y sin IGV.
    costo_unitario = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal("0"))
    costo_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    # En las entradas y en los extornos el costo es un dato y no cambia al recalcular; en una
    # salida normal es el promedio vigente en su fecha.
    costo_fijo = models.BooleanField(default=False)

    saldo_cantidad = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    saldo_costo_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    saldo_costo_unitario = models.DecimalField(
        max_digits=16, decimal_places=6, default=Decimal("0")
    )

    class Meta:
        verbose_name = "línea de movimiento"
        verbose_name_plural = "líneas de movimiento"
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_lineamov_cantidad"),
            models.CheckConstraint(
                condition=Q(saldo_cantidad__gte=0) & Q(saldo_costo_total__gte=0),
                name="ck_lineamov_saldo_no_negativo",
            ),
        ]
        indexes = [
            # El Kardex de un producto en un almacén, en orden cronológico.
            models.Index(
                fields=["empresa", "almacen", "producto", "fecha", "movimiento", "id"],
                name="ix_lineamov_kardex",
            ),
            models.Index(fields=["movimiento"], name="ix_lineamov_movimiento"),
        ]

    def __str__(self) -> str:
        return f"{self.producto_id} x {self.cantidad}"


class CierrePeriodo(EmpresaScopedModel):
    """Un mes (AAAAMM) ya cerrado: no admite movimientos nuevos, ni cambios, ni anulaciones."""

    periodo = models.CharField(max_length=6)
    cerrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "cierre de periodo"
        verbose_name_plural = "cierres de periodo"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "periodo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_cierreperiodo_vigente",
            )
        ]

    def __str__(self) -> str:
        return f"{self.empresa_id} · {self.periodo}"


class EstadoSerie(models.TextChoices):
    EN_STOCK = "EN_STOCK", "En stock"
    SALIDO = "SALIDO", "Ya salió"


class SerieProducto(EmpresaScopedModel):
    """Una unidad física con número de serie o IMEI, durante su estadía en un almacén.

    Cada ENTRADA de un producto que «lleva serie» crea una fila por unidad; la SALIDA la cierra
    (queda como «ya salió» con la línea que la sacó). Si la unidad vuelve a entrar (devolución,
    traspaso) se crea una fila nueva: así cada serie conserva su historial completo.
    Una serie no puede estar en stock dos veces, ni siquiera en otra empresa.
    """

    producto = models.ForeignKey("mantenimiento.Producto", on_delete=models.PROTECT)
    numero = models.CharField(max_length=40)
    # Dato propio de esta unidad (color, garantía, estado…). Opcional: puede quedar vacío.
    otros_datos = models.CharField("otros datos", max_length=120, blank=True, default="")
    estado = models.CharField(
        max_length=10, choices=EstadoSerie.choices, default=EstadoSerie.EN_STOCK
    )
    almacen = models.ForeignKey("mantenimiento.Almacen", on_delete=models.PROTECT)
    entrada = models.ForeignKey(
        LineaMovimiento, on_delete=models.PROTECT, related_name="series_entrada"
    )
    salida = models.ForeignKey(
        LineaMovimiento,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="series_salida",
    )

    class Meta:
        verbose_name = "serie de producto"
        verbose_name_plural = "series de productos"
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "numero"],
                condition=Q(estado="EN_STOCK"),
                name="uq_serie_en_stock",
            ),
            models.CheckConstraint(
                condition=Q(estado="EN_STOCK") | Q(salida__isnull=False),
                name="ck_serie_salida_si_salio",
            ),
        ]
        indexes = [
            models.Index(fields=["producto", "numero"], name="ix_serie_producto_numero"),
            models.Index(
                fields=["empresa", "almacen", "producto", "estado"], name="ix_serie_almacen_estado"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.numero} ({self.get_estado_display()})"


# ---------------------------------------------------------------------------
# Toma de inventario físico
# ---------------------------------------------------------------------------
class EstadoToma(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    ABIERTA = "ABIERTA", "Abierta"
    EN_CONTEO = "EN_CONTEO", "En conteo"
    EN_RECONTEO = "EN_RECONTEO", "En reconteo"
    CERRADA = "CERRADA", "Cerrada"
    APROBADA = "APROBADA", "Aprobada"
    ANULADA = "ANULADA", "Anulada"


# Mientras una toma está en uno de estos estados, su almacén no admite otra toma.
ESTADOS_TOMA_VIGENTE = (
    EstadoToma.BORRADOR,
    EstadoToma.ABIERTA,
    EstadoToma.EN_CONTEO,
    EstadoToma.EN_RECONTEO,
    EstadoToma.CERRADA,
)


class AlcanceToma(models.TextChoices):
    TODO = "TODO", "Todo el almacén"
    CATEGORIAS = "CATEGORIAS", "Algunas categorías"


class TomaInventario(EmpresaScopedModel):
    """Una toma de inventario físico de UN almacén: foto del stock, conteo y diferencias.

    Al abrirla se congela el stock y el costo promedio de cada producto (``DetalleToma``); lo
    contado se compara siempre contra esa foto, no contra el stock que cambie después.
    """

    almacen = models.ForeignKey(
        "mantenimiento.Almacen", on_delete=models.PROTECT, related_name="tomas"
    )
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    estado = models.CharField(
        max_length=12, choices=EstadoToma.choices, default=EstadoToma.BORRADOR, db_index=True
    )
    alcance = models.CharField(max_length=10, choices=AlcanceToma.choices, default=AlcanceToma.TODO)
    categorias = models.ManyToManyField("mantenimiento.Categoria", blank=True, related_name="+")
    productos_excluidos = models.ManyToManyField(
        "mantenimiento.Producto",
        blank=True,
        related_name="+",
        help_text="Productos que no se cuentan (p. ej. mercadería de terceros).",
    )
    # Conteo a ciegas: quien cuenta no ve el stock del sistema ni las diferencias.
    conteo_ciego = models.BooleanField(default=True)
    responsable = models.ForeignKey(
        "mantenimiento.Personal",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    observacion = models.CharField(max_length=250, blank=True)
    # Una diferencia es relevante (pide reconteo y nota) si pasa CUALQUIERA de los dos umbrales.
    umbral_monto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("500"))
    umbral_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))

    fecha_corte = models.DateTimeField(null=True, blank=True, editable=False)
    abierta_en = models.DateTimeField(null=True, blank=True, editable=False)
    cerrada_en = models.DateTimeField(null=True, blank=True, editable=False)
    cerrada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    # Al aprobar se genera el ajuste en el Kardex (movimientos de origen AJUSTE, operación 28).
    aprobada_en = models.DateTimeField(null=True, blank=True, editable=False)
    aprobada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    fecha_ajuste = models.DateField(null=True, blank=True, editable=False)
    nota_aprobacion = models.CharField(max_length=250, blank=True, editable=False)
    anulada_en = models.DateTimeField(null=True, blank=True, editable=False)
    anulada_por_id = models.UUIDField(null=True, blank=True, editable=False)
    motivo_anulacion = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = "toma de inventario"
        verbose_name_plural = "tomas de inventario"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="uq_tomainv_numero_por_empresa"
            ),
            # Un almacén no puede tener dos tomas en curso a la vez.
            models.UniqueConstraint(
                fields=["almacen"],
                condition=Q(estado__in=ESTADOS_TOMA_VIGENTE, eliminado_en__isnull=True),
                name="uq_tomainv_una_vigente_por_almacen",
            ),
            models.CheckConstraint(
                condition=Q(umbral_monto__gte=0) & Q(umbral_porcentaje__gte=0),
                name="ck_tomainv_umbrales",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_tomainv_empresa_estado")]

    def __str__(self) -> str:
        return f"Toma N° {self.numero:06d} ({self.get_estado_display()})"


class ResultadoToma(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    CONFORME = "CONFORME", "Conforme"
    FALTANTE = "FALTANTE", "Faltante"
    SOBRANTE = "SOBRANTE", "Sobrante"


class EstadoFisico(models.TextChoices):
    BUENO = "BUENO", "Bueno"
    DEFECTUOSO = "DEFECTUOSO", "Defectuoso"
    GARANTIA = "GARANTIA", "En garantía"
    DE_TERCEROS = "DE_TERCEROS", "De terceros"


class DetalleToma(EmpresaScopedModel):
    """Un producto de la toma, con el stock y el costo que tenía al abrirla y lo que se contó."""

    toma = models.ForeignKey(TomaInventario, on_delete=models.PROTECT, related_name="detalles")
    producto = models.ForeignKey("mantenimiento.Producto", on_delete=models.PROTECT)
    stock_sistema = models.DecimalField(max_digits=14, decimal_places=3)
    costo_unitario = models.DecimalField(max_digits=16, decimal_places=6, default=Decimal("0"))
    # Nulo = todavía no se cuenta; 0 = se contó y no hay.
    cantidad_contada = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    importe_diferencia = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, help_text="Al costo, en soles."
    )
    resultado = models.CharField(
        max_length=10, choices=ResultadoToma.choices, default=ResultadoToma.PENDIENTE
    )
    estado_fisico = models.CharField(
        max_length=12, choices=EstadoFisico.choices, default=EstadoFisico.BUENO
    )
    nota = models.CharField(max_length=250, blank=True)
    numero_conteos = models.PositiveSmallIntegerField(default=0)
    requiere_reconteo = models.BooleanField(default=False)
    contado_por_id = models.UUIDField(null=True, blank=True, editable=False)
    contado_en = models.DateTimeField(null=True, blank=True, editable=False)
    # Se llenan al aprobar. ``movimientos_posteriores`` es lo que entró y salió del almacén entre
    # el corte y el conteo; ``diferencia_ajuste`` es lo contado menos lo que el sistema debía
    # tener en ese momento (es lo que de verdad se ajusta en el Kardex).
    movimientos_posteriores = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True, editable=False
    )
    diferencia_ajuste = models.DecimalField(
        max_digits=14, decimal_places=3, null=True, blank=True, editable=False
    )
    importe_ajuste = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True, editable=False
    )
    linea_ajuste = models.ForeignKey(
        LineaMovimiento,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        editable=False,
    )

    class Meta:
        verbose_name = "detalle de toma"
        verbose_name_plural = "detalles de toma"
        constraints = [
            models.UniqueConstraint(
                fields=["toma", "producto"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_detalletoma_producto",
            ),
            models.CheckConstraint(
                condition=Q(stock_sistema__gte=0)
                & (Q(cantidad_contada__isnull=True) | Q(cantidad_contada__gte=0)),
                name="ck_detalletoma_no_negativo",
            ),
        ]
        indexes = [
            models.Index(fields=["toma", "resultado"], name="ix_detalletoma_resultado"),
            models.Index(fields=["toma", "requiere_reconteo"], name="ix_detalletoma_reconteo"),
        ]

    def __str__(self) -> str:
        return f"{self.producto_id} x {self.cantidad_contada}"


class TurnoToma(EmpresaScopedModel):
    """Un turno de trabajo de la toma (fecha, horario y quiénes cuentan)."""

    class Turno(models.TextChoices):
        MANANA = "MANANA", "Mañana"
        TARDE = "TARDE", "Tarde"
        MANANA_Y_TARDE = "MANANA_Y_TARDE", "Mañana y tarde"

    toma = models.ForeignKey(TomaInventario, on_delete=models.PROTECT, related_name="turnos")
    fecha = models.DateField()
    turno = models.CharField(max_length=14, choices=Turno.choices)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField(null=True, blank=True)
    equipo = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "turno de toma"
        verbose_name_plural = "turnos de toma"
        indexes = [models.Index(fields=["toma", "fecha"], name="ix_turnotoma_fecha")]

    def __str__(self) -> str:
        return f"{self.fecha} {self.get_turno_display()}"


class ConteoToma(EmpresaScopedModel):
    """Cada vez que se cuenta un producto (1.º conteo, reconteos, correcciones). No se borra."""

    detalle = models.ForeignKey(DetalleToma, on_delete=models.PROTECT, related_name="conteos")
    numero = models.PositiveSmallIntegerField(help_text="1 = primer conteo, 2 = reconteo…")
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    turno = models.ForeignKey(
        TurnoToma, null=True, blank=True, on_delete=models.SET_NULL, related_name="conteos"
    )
    nota = models.CharField(max_length=250, blank=True)
    # Vino de un Excel (conteo hecho antes, en papel o en una hoja de cálculo).
    importado = models.BooleanField(default=False)

    class Meta:
        verbose_name = "conteo de toma"
        verbose_name_plural = "conteos de toma"
        constraints = [
            models.UniqueConstraint(fields=["detalle", "numero"], name="uq_conteotoma_numero"),
            models.CheckConstraint(condition=Q(cantidad__gte=0), name="ck_conteotoma_cantidad"),
        ]

    def __str__(self) -> str:
        return f"conteo {self.numero}: {self.cantidad}"
