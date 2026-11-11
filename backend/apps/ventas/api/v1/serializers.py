from decimal import Decimal

from rest_framework import serializers

from apps.ventas.models import (
    AbonoVenta,
    CobroVenta,
    ComprobanteVenta,
    CuotaVenta,
    DocumentoInterno,
    FormaPago,
    LineaVenta,
    Moneda,
    NotaCredito,
    Venta,
    VentaInterna,
)

DINERO = {"max_digits": 16, "decimal_places": 2}


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
class LineaEntradaSerializer(serializers.Serializer):
    producto = serializers.IntegerField(min_value=1)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    empresa = serializers.IntegerField(min_value=1)
    almacen = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    precio_unitario = serializers.DecimalField(
        max_digits=16, decimal_places=6, required=False, allow_null=True
    )
    series = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, max_length=500
    )
    afectacion = serializers.CharField(max_length=2, required=False, allow_blank=True)


class CobroEntradaSerializer(serializers.Serializer):
    medio_pago = serializers.IntegerField(min_value=1)
    monto = serializers.DecimalField(min_value=Decimal("0.01"), **DINERO)
    referencia = serializers.CharField(max_length=60, required=False, allow_blank=True)
    recibido = serializers.DecimalField(required=False, allow_null=True, **DINERO)


class CuotasEntradaSerializer(serializers.Serializer):
    cantidad = serializers.IntegerField(min_value=1, max_value=60)
    primera_fecha = serializers.DateField()
    periodicidad = serializers.IntegerField(min_value=1)


class CarritoEntrada(serializers.Serializer):
    """Lo que tienen en común la vista previa y la venta definitiva."""

    empresa = serializers.IntegerField(min_value=1)
    tipo_comprobante = serializers.CharField(max_length=2)
    cliente = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    moneda = serializers.ChoiceField(choices=Moneda.choices, required=False)
    tipo_cambio = serializers.DecimalField(
        max_digits=10, decimal_places=4, required=False, allow_null=True
    )
    lista = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    sucursal = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    lineas = LineaEntradaSerializer(many=True, allow_empty=False, max_length=100)
    # Si una empresa tiene varias series del tipo: {id de la empresa: id de la serie}.
    serie_por_empresa = serializers.DictField(
        child=serializers.IntegerField(min_value=1), required=False
    )
    forma_pago = serializers.ChoiceField(choices=FormaPago.choices, required=False)
    cuotas = CuotasEntradaSerializer(required=False, allow_null=True)
    # Solo la vista previa: lo que el cliente paga al momento en una venta a crédito.
    inicial = serializers.DecimalField(required=False, min_value=Decimal("0"), **DINERO)
    # Venta interna: un solo comprobante, de esta empresa, con mercadería de las dos. Pide el
    # permiso VENTAS.VENTA_INTERNA; sin ella la venta mixta sigue con un comprobante por empresa.
    facturar_por = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    documento_interno = serializers.ChoiceField(choices=DocumentoInterno.choices, required=False)
    # Solo si la empresa que factura tiene varios almacenes de venta:
    # {id del almacén de donde sale: id del almacén donde entra}.
    almacenes_internos = serializers.DictField(
        child=serializers.IntegerField(min_value=1), required=False
    )


class VentaEntrada(CarritoEntrada):
    # La proforma que esta venta cumple.
    proforma = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    vendedor = serializers.UUIDField(required=False, allow_null=True)
    observacion = serializers.CharField(max_length=250, required=False, allow_blank=True)
    # Al contado deben sumar el total; a crédito son el pago inicial y pueden no haber.
    cobros = CobroEntradaSerializer(many=True, required=False, max_length=10)


class AbonoEntrada(serializers.Serializer):
    abonos = CobroEntradaSerializer(many=True, allow_empty=False, max_length=10)
    # Si la empresa tiene varias series de recibos: con cuál se entrega este.
    serie_recibo = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    cuotas = serializers.ListField(
        child=serializers.IntegerField(min_value=1), required=False, max_length=60
    )


class AnulacionVentaEntrada(serializers.Serializer):
    motivo = serializers.CharField(max_length=250)


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
class LineaVentaSerializer(serializers.ModelSerializer):
    unidad = serializers.CharField(source="producto.unidad.abreviatura", read_only=True)
    afectacion_nombre = serializers.CharField(source="afectacion.nombre", read_only=True)
    codigo = serializers.CharField(source="producto.codigo", read_only=True)

    class Meta:
        model = LineaVenta
        fields = [
            "id",
            "producto",
            "codigo",
            "descripcion",
            "unidad",
            "cantidad",
            "afectacion_nombre",
            "tasa_igv",
            "precio_lista",
            "precio_unitario",
            "bajo_minimo",
            "valor_venta",
            "igv",
            "total",
            "series",
        ]
        read_only_fields = fields


class CobroVentaSerializer(serializers.ModelSerializer):
    medio_pago_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    medio_pago_tipo = serializers.CharField(source="medio_pago.tipo", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)

    class Meta:
        model = CobroVenta
        fields = [
            "id",
            "medio_pago",
            "medio_pago_nombre",
            "medio_pago_tipo",
            "cuenta",
            "cuenta_nombre",
            "monto",
            "referencia",
            "recibido",
            "vuelto",
        ]
        read_only_fields = fields


class CuotaVentaSerializer(serializers.ModelSerializer):
    saldo = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = CuotaVenta
        fields = ["id", "numero", "fecha_vencimiento", "monto", "pagado", "saldo"]
        read_only_fields = fields


class AbonoVentaSerializer(serializers.ModelSerializer):
    medio_pago_nombre = serializers.CharField(source="medio_pago.nombre", read_only=True)
    cuenta_nombre = serializers.CharField(source="cuenta.nombre", read_only=True)
    cuotas = serializers.SerializerMethodField()
    recibo_numero = serializers.CharField(
        source="recibo.numero_completo", default="", read_only=True
    )

    class Meta:
        model = AbonoVenta
        fields = [
            "id",
            "recibo",
            "recibo_numero",
            "fecha",
            "medio_pago",
            "medio_pago_nombre",
            "cuenta_nombre",
            "monto",
            "referencia",
            "recibido",
            "vuelto",
            "cuotas",
            "anulado",
            "motivo_anulacion",
        ]
        read_only_fields = fields

    def get_cuotas(self, abono) -> list[int]:
        # ``aplicaciones`` viene precargado con su cuota.
        return [a.cuota.numero for a in abono.aplicaciones.all()]


class NotaResumenSerializer(serializers.ModelSerializer):
    numero_completo = serializers.CharField(read_only=True)

    class Meta:
        model = NotaCredito
        fields = ["id", "numero_completo", "fecha", "total", "motivo"]
        read_only_fields = fields


class ComprobanteVentaSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.SerializerMethodField()
    empresa_ruc = serializers.CharField(source="empresa.ruc", read_only=True)
    empresa_direccion = serializers.CharField(source="empresa.direccion_fiscal", read_only=True)
    empresa_telefono = serializers.CharField(source="empresa.telefono", read_only=True)
    empresa_sitio_web = serializers.CharField(source="empresa.sitio_web", read_only=True)
    empresa_tienda_web = serializers.CharField(source="empresa.tienda_web", read_only=True)
    empresa_tiene_logo = serializers.SerializerMethodField()
    local = serializers.SerializerMethodField()
    hora = serializers.SerializerMethodField()
    tipo_codigo = serializers.CharField(source="tipo_comprobante.codigo", read_only=True)
    tipo_nombre = serializers.CharField(source="tipo_comprobante.nombre", read_only=True)
    numero_completo = serializers.CharField(read_only=True)
    lineas = LineaVentaSerializer(many=True, read_only=True)
    cobros = CobroVentaSerializer(many=True, read_only=True)
    cuotas = CuotaVentaSerializer(many=True, read_only=True)
    abonos = AbonoVentaSerializer(many=True, read_only=True)
    notas_credito = NotaResumenSerializer(many=True, read_only=True)
    saldo = serializers.SerializerMethodField()
    series_recibo = serializers.SerializerMethodField()

    class Meta:
        model = ComprobanteVenta
        fields = [
            "id",
            "empresa",
            "empresa_nombre",
            "empresa_ruc",
            "empresa_direccion",
            "empresa_telefono",
            "empresa_sitio_web",
            "empresa_tienda_web",
            "empresa_tiene_logo",
            "local",
            "hora",
            "tipo_codigo",
            "tipo_nombre",
            "serie",
            "numero",
            "numero_completo",
            "fecha",
            "op_gravada",
            "op_exonerada",
            "op_inafecta",
            "igv",
            "total",
            "estado",
            "anulado_en",
            "motivo_anulacion",
            "lineas",
            "cobros",
            "cuotas",
            "abonos",
            "notas_credito",
            "saldo",
            "series_recibo",
        ]
        read_only_fields = fields

    def get_empresa_nombre(self, comprobante) -> str:
        return comprobante.empresa.nombre_comercial or comprobante.empresa.razon_social

    def get_empresa_tiene_logo(self, comprobante) -> bool:
        return bool(comprobante.empresa.logo)

    def get_local(self, comprobante) -> str:
        """Donde se vendió: la dirección de la sucursal o, si no tiene, la fiscal de la empresa."""
        sucursal = comprobante.venta.sucursal
        return (sucursal.direccion if sucursal and sucursal.direccion else "") or (
            comprobante.empresa.direccion_fiscal
        )

    def get_hora(self, comprobante) -> str:
        return comprobante.creado_en.astimezone().strftime("%H:%M")

    def get_series_recibo(self, comprobante) -> list[dict]:
        """Con qué series se puede entregar el recibo de un cobro (solo en ventas a crédito)."""
        if comprobante.estado != ComprobanteVenta.Estado.EMITIDO or not comprobante.cuotas.all():
            return []
        from apps.ventas.cuentas_por_cobrar import series_de_recibo

        return series_de_recibo(comprobante.empresa_id)

    def get_saldo(self, comprobante) -> str:
        """Lo que falta cobrar (solo tiene sentido en un comprobante vendido a crédito)."""
        if comprobante.estado != ComprobanteVenta.Estado.EMITIDO:
            return "0.00"
        # ``cuotas`` viene precargado: no se consulta por comprobante.
        return f"{sum((c.monto - c.pagado for c in comprobante.cuotas.all()), Decimal('0')):.2f}"


class ComprobanteResumenSerializer(serializers.ModelSerializer):
    empresa_nombre = serializers.SerializerMethodField()
    tipo_codigo = serializers.CharField(source="tipo_comprobante.codigo", read_only=True)
    numero_completo = serializers.CharField(read_only=True)

    class Meta:
        model = ComprobanteVenta
        fields = [
            "id",
            "empresa",
            "empresa_nombre",
            "tipo_codigo",
            "numero_completo",
            "total",
            "estado",
        ]
        read_only_fields = fields

    def get_empresa_nombre(self, comprobante) -> str:
        return comprobante.empresa.nombre_comercial or comprobante.empresa.razon_social


class VentaSerializer(serializers.ModelSerializer):
    """La venta tal como la ve quien pregunta.

    Una venta puede traer comprobantes de varias empresas. Cada persona ve los de las empresas que
    puede ver; en el listado de una empresa que no hizo la venta, solo los de esa empresa. Cuando
    se oculta alguno, ``parcial`` es verdadero y ``total`` es la suma de lo que se ve.
    """

    comprobantes = ComprobanteResumenSerializer(many=True, read_only=True)
    mostrador = serializers.IntegerField(source="empresa_id", read_only=True)
    mostrador_nombre = serializers.SerializerMethodField()
    parcial = serializers.SerializerMethodField()

    def get_mostrador_nombre(self, venta) -> str:
        return venta.empresa.nombre_comercial or venta.empresa.razon_social

    def _empresas_a_ver(self, venta) -> set[int] | None:
        """Las empresas cuyos comprobantes se muestran; ``None`` = todos."""
        visibles = self.context.get("empresas_visibles")
        vista = self.context.get("empresa_vista")
        if visibles is None and vista is None:
            return None
        todas = {c.empresa_id for c in venta.comprobantes.all()} | {venta.empresa_id}
        ver = todas if visibles is None else todas & visibles
        if vista is not None and venta.empresa_id != vista:
            ver = ver & {vista}
        return ver

    def get_parcial(self, venta) -> bool:
        ver = self._empresas_a_ver(venta)
        return ver is not None and any(c.empresa_id not in ver for c in venta.comprobantes.all())

    def to_representation(self, venta):
        datos = super().to_representation(venta)
        ver = self._empresas_a_ver(venta)
        if ver is not None and datos["parcial"]:
            datos["comprobantes"] = [c for c in datos["comprobantes"] if c["empresa"] in ver]
            datos["total"] = str(
                sum(
                    (c.total for c in venta.comprobantes.all() if c.empresa_id in ver),
                    Decimal("0"),
                ).quantize(Decimal("0.01"))
            )
        return datos

    class Meta:
        model = Venta
        fields = [
            "id",
            "numero",
            "fecha",
            "cliente",
            "cliente_nombre",
            "cliente_tipo_documento",
            "cliente_documento",
            "vendedor_nombre",
            "moneda",
            "tipo_cambio",
            "total",
            "forma_pago",
            "estado",
            "comprobantes",
            "mostrador",
            "mostrador_nombre",
            "parcial",
            "creado_en",
        ]
        read_only_fields = fields


class VentaInternaSerializer(serializers.ModelSerializer):
    """Qué mercadería pasó de una empresa a la otra para poder facturar todo junto (sin costos)."""

    entrega = serializers.SerializerMethodField()
    recibe = serializers.SerializerMethodField()
    documento_nombre = serializers.CharField(source="get_documento_display", read_only=True)
    devolucion = serializers.SerializerMethodField()

    class Meta:
        model = VentaInterna
        fields = [
            "id",
            "numero",
            "fecha",
            "empresa",
            "entrega",
            "empresa_destino",
            "recibe",
            "documento",
            "documento_nombre",
            "estado",
            "devolucion",
        ]
        read_only_fields = fields

    def get_devolucion(self, interna) -> str:
        """Cuánto de lo trasladado ya volvió a quien lo entregó: NINGUNA, PARCIAL o TOTAL."""
        # ``lineas`` y ``devoluciones`` vienen precargadas: no se consulta por venta interna.
        total = sum((ln.cantidad for ln in interna.lineas.all()), Decimal("0"))
        devuelto = sum((d.cantidad for d in interna.devoluciones.all()), Decimal("0"))
        if devuelto <= 0:
            return "NINGUNA"
        return "TOTAL" if devuelto >= total else "PARCIAL"

    def get_entrega(self, interna) -> str:
        return interna.empresa.nombre_comercial or interna.empresa.razon_social

    def get_recibe(self, interna) -> str:
        return interna.empresa_destino.nombre_comercial or interna.empresa_destino.razon_social


class VentaDetalleSerializer(VentaSerializer):
    comprobantes = ComprobanteVentaSerializer(many=True, read_only=True)
    ventas_internas = VentaInternaSerializer(many=True, read_only=True)
    lista_nombre = serializers.CharField(source="lista.nombre", default="", read_only=True)
    cliente_direccion = serializers.SerializerMethodField()

    def get_cliente_direccion(self, venta) -> str:
        """La dirección registrada del cliente (para la hoja A4 del comprobante)."""
        return venta.cliente.direccion if venta.cliente_id else ""

    class Meta(VentaSerializer.Meta):
        fields = [
            *VentaSerializer.Meta.fields,
            "observacion",
            "lista_nombre",
            "cliente_direccion",
            "ventas_internas",
            "anulado_en",
            "motivo_anulacion",
        ]
        read_only_fields = fields
