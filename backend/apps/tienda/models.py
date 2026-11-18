"""Configuración de la tienda virtual: una por organización."""

from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.crypto import CampoCifrado
from apps.core.models import OrganizacionScopedModel

validar_url = URLValidator(schemes=["http", "https"])
validar_color = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Use un color como #E2372A.")


def _ruta_logo(instancia, nombre: str) -> str:
    return f"tienda/{instancia.organizacion_id}/{nombre}"


def _ruta_voucher(instancia, nombre: str) -> str:
    return f"tienda/vouchers/{instancia.organizacion_id}/{nombre}"


class ConfiguracionTienda(OrganizacionScopedModel):
    """Cómo se muestra la tienda pública: qué precios y de qué almacenes sale el stock.

    La tienda es UNA por organización y sirve a todas sus empresas: el stock que se muestra es la
    suma de los almacenes elegidos aquí (de cualquier empresa).
    """

    activa = models.BooleanField(default=False, help_text="Si está apagada, la tienda no responde.")
    nombre = models.CharField(max_length=80, default="Tienda")
    lista_precio = models.ForeignKey(
        "mantenimiento.ListaPrecio",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Lista de precios que ve el público. Vacía = la principal.",
    )
    almacenes = models.ManyToManyField(
        "mantenimiento.Almacen",
        blank=True,
        related_name="+",
        help_text="Almacenes cuyo stock abastece la tienda.",
    )
    precios_con_igv = models.BooleanField(
        default=True, help_text="Mostrar el precio con el IGV sumado."
    )
    pocas_unidades = models.PositiveSmallIntegerField(
        default=5, help_text="Hasta cuántas unidades se avisa «pocas unidades»."
    )
    # --- Entrega ---
    permite_envio = models.BooleanField(default=True, help_text="Ofrecer envío a domicilio.")
    permite_recojo = models.BooleanField(default=True, help_text="Ofrecer recojo en tienda.")
    peso_por_defecto_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
        help_text="Peso que se usa para calcular el envío de un producto sin peso cargado.",
    )

    # --- Marca: el logo es de la TIENDA (une a las empresas), no el de cada empresa ---
    logo = models.FileField(upload_to=_ruta_logo, max_length=255, blank=True)
    logo_version = models.CharField(max_length=12, blank=True, default="")
    color_principal = models.CharField(max_length=7, blank=True, validators=[validar_color])
    nombre_junto_al_logo = models.BooleanField(
        default=True, help_text="Escribir el nombre de la tienda al lado del logo."
    )
    descripcion = models.CharField(max_length=200, blank=True)

    # --- Contacto (lo vacío se toma de la ficha de la empresa principal, salvo el WhatsApp) ---
    whatsapp = models.CharField(max_length=30, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(max_length=150, blank=True)
    direccion = models.CharField(max_length=250, blank=True)
    horario = models.CharField(max_length=200, blank=True)
    mapa_url = models.CharField(max_length=500, blank=True, validators=[validar_url])
    facebook = models.CharField(max_length=300, blank=True, validators=[validar_url])
    instagram = models.CharField(max_length=300, blank=True, validators=[validar_url])
    tiktok = models.CharField(max_length=300, blank=True, validators=[validar_url])
    youtube = models.CharField(max_length=300, blank=True, validators=[validar_url])

    # --- Textos de la tienda ---
    avisos = models.JSONField(
        default=list, blank=True, help_text="Hasta 3 frases de la barra superior."
    )
    portada_etiqueta = models.CharField(max_length=80, blank=True)
    portada_titulo = models.CharField(max_length=120, blank=True)
    portada_subtitulo = models.CharField(max_length=250, blank=True)
    servicio_visible = models.BooleanField(default=False)
    servicio_titulo = models.CharField(max_length=100, blank=True)
    servicio_texto = models.CharField(max_length=300, blank=True)
    servicio_puntos = models.JSONField(default=list, blank=True, help_text="Hasta 4 frases cortas.")
    garantia_texto = models.CharField(max_length=250, blank=True)
    entrega_texto = models.CharField(max_length=250, blank=True)

    # --- Posicionamiento y medición (opcional; la medición solo corre si el cliente acepta) ---
    seo_titulo_inicio = models.CharField(max_length=70, blank=True)
    google_verificacion = models.CharField(
        max_length=100,
        blank=True,
        validators=[RegexValidator(r"^[A-Za-z0-9_-]{10,100}$", "Pegue solo el código de Google.")],
    )
    ga4_id = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^G-[A-Z0-9]{4,15}$", "Use un código como G-ABC123XYZ.")],
    )
    meta_pixel_id = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\d{8,20}$", "Use solo los números del píxel.")],
    )

    # --- Legales ---
    libro_reclamaciones_url = models.CharField(max_length=500, blank=True, validators=[validar_url])
    terminos_url = models.CharField(max_length=500, blank=True, validators=[validar_url])
    privacidad_url = models.CharField(max_length=500, blank=True, validators=[validar_url])

    class Meta:
        verbose_name = "configuración de la tienda"
        verbose_name_plural = "configuraciones de la tienda"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configtienda_organizacion",
            )
        ]

    def __str__(self) -> str:
        return f"Tienda de la organización {self.organizacion_id}"


# ---------------------------------------------------------------------------
# Cuentas de clientes de la tienda (separadas de los usuarios internos del sistema)
# ---------------------------------------------------------------------------
class CuentaCliente(OrganizacionScopedModel):
    """Quien compra en la tienda. NO es un usuario del sistema: no entra al panel ni tiene roles.

    El ``Cliente`` del sistema (con su documento) se crea o se vincula al pagar, cuando ya se
    conoce el DNI o RUC para el comprobante.
    """

    correo = models.EmailField(max_length=150)
    password = models.CharField(max_length=256)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    celular = models.CharField(max_length=20, blank=True)
    correo_verificado_en = models.DateTimeField(null=True, blank=True)
    acepta_terminos_en = models.DateTimeField(null=True, blank=True)
    acepta_ofertas = models.BooleanField(default=False)
    # Permiso del cliente para avisarle de sus pedidos por WhatsApp (por defecto, no).
    acepta_whatsapp = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)
    ultimo_ingreso = models.DateTimeField(null=True, blank=True)
    cliente = models.ForeignKey(
        "mantenimiento.Cliente",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cuentas_tienda",
    )

    class Meta:
        verbose_name = "cuenta de cliente de la tienda"
        verbose_name_plural = "cuentas de clientes de la tienda"
        constraints = [
            models.UniqueConstraint(
                Lower("correo"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_cuentatienda_correo_vigente",
            )
        ]

    def __str__(self) -> str:
        return self.correo

    @property
    def verificada(self) -> bool:
        return self.correo_verificado_en is not None


class SesionCuenta(models.Model):
    """Sesión abierta de un cliente. Solo se guarda la huella del token (nunca el token)."""

    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.CASCADE, related_name="sesiones")
    huella = models.CharField(max_length=64, unique=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    ultimo_uso = models.DateTimeField(auto_now_add=True)
    expira_en = models.DateTimeField(db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    dispositivo = models.CharField(max_length=200, blank=True)
    revocada = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Sesión de la cuenta {self.cuenta_id}"


class TokenCuenta(models.Model):
    """Enlace de un solo uso por correo: confirmar el correo o recuperar la contraseña."""

    class Tipo(models.TextChoices):
        VERIFICAR = "VERIFICAR", "Confirmar correo"
        RECUPERAR = "RECUPERAR", "Recuperar contraseña"

    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.CASCADE, related_name="tokens")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    huella = models.CharField(max_length=64, unique=True)
    expira_en = models.DateTimeField(db_index=True)
    usado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.tipo} de la cuenta {self.cuenta_id}"


class DireccionCuenta(OrganizacionScopedModel):
    """Dirección de entrega guardada por el cliente."""

    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.CASCADE, related_name="direcciones")
    etiqueta = models.CharField(max_length=40, blank=True)
    receptor = models.CharField("quién recibe", max_length=150)
    celular = models.CharField(max_length=20)
    ubigeo = models.CharField(max_length=6)
    direccion = models.CharField(max_length=250)
    referencia = models.CharField(max_length=200, blank=True)
    es_principal = models.BooleanField(default=False)

    class Meta:
        verbose_name = "dirección de entrega"
        verbose_name_plural = "direcciones de entrega"
        constraints = [
            models.UniqueConstraint(
                fields=["cuenta"],
                condition=Q(es_principal=True, eliminado_en__isnull=True),
                name="uq_direccioncuenta_principal",
            )
        ]


# ---------------------------------------------------------------------------
# Entrega: zonas con su tarifa por peso, y puntos de recojo
# ---------------------------------------------------------------------------
class ZonaEnvio(OrganizacionScopedModel):
    """Zona de entrega a domicilio: qué lugares cubre y cuánto cuesta según el peso."""

    class Modalidad(models.TextChoices):
        TIENDA = "TIENDA", "Reparto propio: el envío se cobra en la compra"
        DESTINO = "DESTINO", "Agencia: el cliente paga el flete al recibir"

    nombre = models.CharField(max_length=80)
    modalidad = models.CharField(max_length=10, choices=Modalidad.choices, default=Modalidad.TIENDA)
    plazo = models.CharField(max_length=100, blank=True, help_text="Ej.: 24 a 48 horas.")
    detalle = models.CharField(
        max_length=250, blank=True, help_text="Ej.: Enviamos por Olva o Shalom, a elección."
    )
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)
    envio_gratis_desde = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Compras desde este monto (S/) llevan el envío gratis. Vacío = nunca.",
    )  # fmt: skip
    kg_adicional = models.DecimalField(
        "costo por kg adicional", max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Suma por cada kg sobre el último tramo. Vacío = no se atiende ese peso.",
    )  # fmt: skip

    class Meta:
        verbose_name = "zona de envío"
        verbose_name_plural = "zonas de envío"
        ordering = ["orden", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_zonaenvio_nombre_vigente",
            )
        ]

    def __str__(self) -> str:
        return self.nombre


class CoberturaZona(OrganizacionScopedModel):
    """Un lugar que cubre la zona: un departamento (2 dígitos), provincia (4) o distrito (6) del
    ubigeo INEI. Un lugar solo puede estar en una zona; el más específico gana al cotizar."""

    zona = models.ForeignKey(ZonaEnvio, on_delete=models.CASCADE, related_name="coberturas")
    prefijo = models.CharField(max_length=6)

    class Meta:
        verbose_name = "cobertura de zona"
        verbose_name_plural = "coberturas de zona"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "prefijo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_coberturazona_prefijo_vigente",
            )
        ]

    def __str__(self) -> str:
        return f"{self.zona_id}: {self.prefijo}"


class TarifaZona(OrganizacionScopedModel):
    """Tramo de peso de una zona: hasta ``hasta_kg`` el envío cuesta ``costo``."""

    zona = models.ForeignKey(ZonaEnvio, on_delete=models.CASCADE, related_name="tarifas")
    hasta_kg = models.DecimalField(max_digits=7, decimal_places=2)
    costo = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = "tarifa de zona"
        verbose_name_plural = "tarifas de zona"
        ordering = ["hasta_kg"]
        constraints = [
            models.UniqueConstraint(
                fields=["zona", "hasta_kg"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tarifazona_tramo_vigente",
            )
        ]

    def __str__(self) -> str:
        return f"{self.zona_id}: hasta {self.hasta_kg} kg = {self.costo}"


class PuntoRecojo(OrganizacionScopedModel):
    """Local donde el cliente recoge su pedido. Solo ofrece lo que hay en SUS almacenes."""

    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=250)
    ubigeo = models.CharField(max_length=6, blank=True)
    horario = models.CharField(max_length=200, blank=True)
    indicaciones = models.CharField(max_length=250, blank=True)
    listo_en = models.CharField(max_length=80, blank=True, help_text="Ej.: Listo en 2 horas.")
    telefono = models.CharField(max_length=20, blank=True)
    activo = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)
    almacenes = models.ManyToManyField(
        "mantenimiento.Almacen",
        blank=True,
        related_name="+",
        help_text="Almacenes de este local (de cualquiera de las empresas).",
    )

    class Meta:
        verbose_name = "punto de recojo"
        verbose_name_plural = "puntos de recojo"
        ordering = ["orden", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_puntorecojo_nombre_vigente",
            )
        ]

    def __str__(self) -> str:
        return self.nombre


class CarritoCuenta(OrganizacionScopedModel):
    """Carrito guardado de quien tiene cuenta (así lo encuentra en otro equipo).

    Solo ids y cantidades: el precio y la disponibilidad se calculan siempre al mostrarlo.
    """

    cuenta = models.OneToOneField(CuentaCliente, on_delete=models.CASCADE, related_name="carrito")
    lineas = models.JSONField(default=list)
    # Recordatorios de carrito abandonado ya enviados para ESTE contenido del carrito: si el
    # cliente lo cambia, la cuenta empieza de cero.
    recordatorios_enviados = models.PositiveSmallIntegerField(default=0)
    ultimo_recordatorio_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "carrito de cuenta"
        verbose_name_plural = "carritos de cuentas"

    def __str__(self) -> str:
        return f"Carrito de la cuenta {self.cuenta_id}"


class ConfiguracionCarritoAbandonado(OrganizacionScopedModel):
    """Recordatorios por correo a quien dejó productos en su carrito sin comprar.

    Solo a clientes con cuenta confirmada que aceptaron recibir ofertas (y pueden darse de baja con
    un enlace). Dos recordatorios como máximo por carrito: el primero a las ``horas_primero`` de
    dejarlo y el segundo ``horas_segundo`` después del primero, con un cupón de incentivo si se
    eligió.
    """

    activo = models.BooleanField(default=False)
    horas_primero = models.PositiveSmallIntegerField(default=2)
    horas_segundo = models.PositiveSmallIntegerField(default=24)
    cupon = models.ForeignKey(
        "tienda.Cupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "configuración de carrito abandonado"
        verbose_name_plural = "configuraciones de carrito abandonado"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configcarrito_organizacion",
            )
        ]

    def __str__(self) -> str:
        return f"Carrito abandonado de la organización {self.organizacion_id}"


class RecordatorioCarrito(OrganizacionScopedModel):
    """Un recordatorio enviado (queda para medir cuántos carritos se recuperan)."""

    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.CASCADE, related_name="+")
    numero = models.PositiveSmallIntegerField()  # 1 = primero, 2 = segundo
    total_carrito = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cupon_codigo = models.CharField(max_length=30, blank=True)
    recuperado_en = models.DateTimeField(null=True, blank=True)
    pedido = models.ForeignKey(
        "tienda.PedidoTienda", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "recordatorio de carrito"
        verbose_name_plural = "recordatorios de carritos"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.cuenta_id}: recordatorio {self.numero}"


class ConfiguracionPago(OrganizacionScopedModel):
    """Cómo cobra la tienda en línea (Culqi). Las llaves las pone el negocio desde el panel.

    La llave PÚBLICA es pública por diseño (el navegador la usa para abrir el cobro). La llave
    SECRETA se guarda cifrada y NUNCA se devuelve: ni a la tienda ni al panel.
    """

    class Modo(models.TextChoices):
        PRUEBA = "PRUEBA", "Pruebas (no cobra dinero real)"
        PRODUCCION = "PRODUCCION", "Producción (cobra dinero real)"

    culqi_activo = models.BooleanField(default=False)
    culqi_modo = models.CharField(max_length=12, choices=Modo.choices, default=Modo.PRUEBA)
    culqi_llave_publica = models.CharField(max_length=80, blank=True)
    culqi_llave_secreta = CampoCifrado(blank=True)
    acepta_tarjeta = models.BooleanField(default=True)
    acepta_yape = models.BooleanField(default=True)
    # Empresa cuya cuenta de Culqi recibe los pagos (la de la que son las llaves).
    empresa_cobra = models.ForeignKey(
        "organizacion.Empresa", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    # --- Pago con adelanto: el cliente paga una parte ahora y el resto al recoger en tienda ---
    class SiNoRecoge(models.TextChoices):
        REEMBOLSO = "REEMBOLSO", "Se devuelve el adelanto, menos la comisión de la pasarela"
        PENALIDAD = "PENALIDAD", "Se retiene el adelanto como penalidad (todo o una parte)"

    # --- Transferencia o depósito: el cliente paga a una cuenta y sube su comprobante ---
    transferencia_activa = models.BooleanField(default=False)
    transferencia_horas = models.PositiveSmallIntegerField(
        "horas para pagar por transferencia", default=24
    )
    transferencia_instrucciones = models.CharField(max_length=600, blank=True)
    # Las cuentas (de cualquier empresa) a las que el cliente puede transferir.
    cuentas_transferencia = models.ManyToManyField(
        "mantenimiento.CuentaFinanciera", blank=True, related_name="+"
    )

    adelanto_activo = models.BooleanField(default=False)
    adelanto_pct = models.DecimalField(
        "porcentaje que se paga por adelantado", max_digits=5, decimal_places=2, default=30
    )
    adelanto_minimo = models.DecimalField(
        "monto mínimo del pedido para ofrecerlo (soles, con IGV)",
        max_digits=10,
        decimal_places=2,
        default=200,
    )
    adelanto_dias = models.PositiveSmallIntegerField("días para recoger", default=5)
    adelanto_si_no_recoge = models.CharField(
        max_length=10, choices=SiNoRecoge.choices, default=SiNoRecoge.REEMBOLSO
    )
    adelanto_penalidad_pct = models.DecimalField(
        "qué parte del adelanto se retiene si no recoge (%)",
        max_digits=5,
        decimal_places=2,
        default=100,
    )
    # Lo que se queda la pasarela de cada cobro: se descuenta al devolver un adelanto.
    comision_pasarela_pct = models.DecimalField(max_digits=5, decimal_places=2, default=4)
    comision_pasarela_fija = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        verbose_name = "configuración de pagos de la tienda"
        verbose_name_plural = "configuraciones de pagos de la tienda"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configpago_organizacion",
            )
        ]

    def __str__(self) -> str:
        return f"Pagos de la organización {self.organizacion_id}"


# ---------------------------------------------------------------------------
# Pedidos de la tienda
# ---------------------------------------------------------------------------
class PedidoTienda(OrganizacionScopedModel):
    """Pedido hecho en la tienda en línea. Guarda COPIA de lo que se acordó (precios, dirección,
    datos del comprobante): lo que el cliente vio es lo que queda aunque cambie el catálogo.
    """

    class Estado(models.TextChoices):
        PENDIENTE_PAGO = "PENDIENTE_PAGO", "Pendiente de pago"
        PAGADO = "PAGADO", "Pagado"
        EN_PREPARACION = "EN_PREPARACION", "En preparación"
        LISTO_PARA_RECOJO = "LISTO_PARA_RECOJO", "Listo para recoger"
        ENVIADO = "ENVIADO", "Enviado"
        ENTREGADO = "ENTREGADO", "Entregado"
        CANCELADO = "CANCELADO", "Cancelado"
        EXPIRADO = "EXPIRADO", "Vencido sin pago"
        # El dinero YA se cobró pero algo impidió terminar: requieren atención del negocio.
        ADELANTO_PAGADO = "ADELANTO_PAGADO", "Adelanto pagado: falta el saldo al recoger"
        NO_RECOGIDO = "NO_RECOGIDO", "No lo recogió a tiempo"
        POR_VERIFICAR = "POR_VERIFICAR", "Transferencia: falta verificar el pago"
        PAGADO_SIN_COMPROBANTE = "PAGADO_SIN_COMPROBANTE", "Pagado: falta el comprobante"
        PAGADO_FUERA_DE_PLAZO = "PAGADO_FUERA_DE_PLAZO", "Pagado fuera de plazo"
        # Reembolsos: lo interno ya se deshizo; falta o ya se devolvió el dinero al cliente.
        REEMBOLSO_PENDIENTE = "REEMBOLSO_PENDIENTE", "Reembolso pendiente en Culqi"
        REEMBOLSADO_PARCIAL = "REEMBOLSADO_PARCIAL", "Reembolsado en parte"
        REEMBOLSADO = "REEMBOLSADO", "Reembolsado"

    class Modalidad(models.TextChoices):
        ENVIO = "ENVIO", "Envío a domicilio"
        RECOJO = "RECOJO", "Recojo en tienda"

    numero = models.CharField(max_length=12)
    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.PROTECT, related_name="pedidos")
    estado = models.CharField(max_length=24, choices=Estado.choices, default=Estado.PENDIENTE_PAGO)
    modalidad = models.CharField(max_length=10, choices=Modalidad.choices)
    clave_idempotencia = models.UUIDField()
    expira_en = models.DateTimeField(db_index=True)

    # Entrega (copia)
    ubigeo_entrega = models.CharField(max_length=6, blank=True)
    ubicacion_entrega = models.CharField(max_length=200, blank=True)
    direccion_entrega = models.CharField(max_length=250, blank=True)
    referencia_entrega = models.CharField(max_length=200, blank=True)
    receptor = models.CharField(max_length=150, blank=True)
    celular_receptor = models.CharField(max_length=20, blank=True)
    punto = models.ForeignKey(
        PuntoRecojo, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    punto_nombre = models.CharField(max_length=100, blank=True)
    envio_zona = models.CharField(max_length=80, blank=True)
    envio_paga_en_destino = models.BooleanField(default=False)
    envio_plazo = models.CharField(max_length=100, blank=True)
    envio_detalle = models.CharField(max_length=250, blank=True)

    # Comprobante que pidió el cliente (copia)
    comprobante_tipo = models.CharField(max_length=2)  # 03 boleta, 01 factura
    documento_tipo = models.CharField(max_length=10, blank=True)
    documento_numero = models.CharField(max_length=20, blank=True)
    nombre_comprobante = models.CharField(max_length=250, blank=True)
    direccion_fiscal = models.CharField(max_length=250, blank=True)

    # Importes en soles
    zona_fiscal = models.CharField(max_length=10, blank=True)
    subtotal_productos = models.DecimalField(max_digits=14, decimal_places=2)
    costo_envio = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    igv = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    igv_exonerado = models.BooleanField(default=False)
    motivo_igv = models.CharField(max_length=200, blank=True)

    # Pago con adelanto (copia de lo acordado al crear el pedido: no cambia si luego se edita la
    # configuración). ``adelanto_monto`` es lo que se cobra ahora; el resto se paga al recoger.
    class PagoModo(models.TextChoices):
        COMPLETO = "COMPLETO", "Pago completo"
        ADELANTO = "ADELANTO", "Adelanto y saldo al recoger"

    pago_modo = models.CharField(max_length=10, choices=PagoModo.choices, default=PagoModo.COMPLETO)

    # Cómo paga: con tarjeta o Yape por Culqi, o por transferencia o depósito (con comprobante que
    # el personal verifica).
    class PagoMetodo(models.TextChoices):
        CULQI = "CULQI", "Tarjeta o Yape"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia o depósito"

    pago_metodo = models.CharField(
        max_length=14, choices=PagoMetodo.choices, default=PagoMetodo.CULQI
    )
    cuenta_transferencia = models.ForeignKey(
        "mantenimiento.CuentaFinanciera",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    voucher = models.FileField(upload_to=_ruta_voucher, max_length=255, blank=True)
    voucher_operacion = models.CharField(max_length=40, blank=True)
    voucher_subido_en = models.DateTimeField(null=True, blank=True)
    # Por qué se rechazó el último comprobante (lo ve el cliente para corregirlo).
    transferencia_rechazo = models.CharField(max_length=250, blank=True)
    adelanto_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    adelanto_monto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    adelanto_dias = models.PositiveSmallIntegerField(default=0)
    adelanto_vence_en = models.DateTimeField(null=True, blank=True, db_index=True)
    adelanto_politica = models.CharField(max_length=10, blank=True)  # REEMBOLSO | PENALIDAD
    adelanto_penalidad_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    adelanto_comision_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    adelanto_comision_fija = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    # Cómo terminó el adelanto de un pedido que no se recogió (lo devuelto y lo retenido).
    adelanto_devuelto = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    adelanto_retenido = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Cupón usado (copia de lo acordado): el código y cuánto se descontó en total (con IGV).
    cupon_codigo = models.CharField(max_length=30, blank=True)
    descuento_cupon = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Pago (Culqi) y venta
    culqi_cargo_id = models.CharField(max_length=40, blank=True)
    culqi_medio = models.CharField(max_length=10, blank=True)  # tarjeta | yape
    pagado_en = models.DateTimeField(null=True, blank=True)
    venta = models.ForeignKey(
        "ventas.Venta", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Por qué el pedido requiere atención (sin datos técnicos ni de la tarjeta).
    motivo_atencion = models.CharField(max_length=250, blank=True)
    reintentos_comprobante = models.PositiveSmallIntegerField(default=0)
    # Lo que el negocio le dice al cliente al enviar o dejar listo el pedido (guía, código, aviso).
    seguimiento = models.CharField(max_length=200, blank=True)
    # Dinero ya devuelto al cliente por Culqi (nunca supera el total cobrado).
    monto_reembolsado = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "pedido de la tienda"
        verbose_name_plural = "pedidos de la tienda"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_pedidotienda_numero",
            ),
            models.UniqueConstraint(
                fields=["cuenta", "clave_idempotencia"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_pedidotienda_clave",
            ),
        ]
        indexes = [models.Index(fields=["estado", "expira_en"], name="ix_pedidotienda_vence")]

    @property
    def monto_a_cobrar(self):
        """Lo que se le cobra al cliente en la tienda: el total, o solo el adelanto."""
        return self.adelanto_monto if self.pago_modo == self.PagoModo.ADELANTO else self.total

    @property
    def saldo(self):
        """Lo que falta pagar al recoger (cero si pagó todo)."""
        if self.pago_modo != self.PagoModo.ADELANTO:
            return 0
        return self.total - self.adelanto_monto

    def __str__(self) -> str:
        return self.numero


class LineaPedido(OrganizacionScopedModel):
    """Una línea del pedido: producto (o el envío) con la empresa y el almacén que lo surten."""

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    empresa = models.ForeignKey("organizacion.Empresa", on_delete=models.PROTECT, related_name="+")
    almacen = models.ForeignKey(
        "mantenimiento.Almacen", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    descripcion = models.CharField(max_length=250)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    precio_unitario = models.DecimalField(
        max_digits=14, decimal_places=2
    )  # final, con IGV si lo lleva
    base = models.DecimalField(max_digits=14, decimal_places=2)
    igv = models.DecimalField(max_digits=14, decimal_places=2)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    es_envio = models.BooleanField(default=False)
    # Lo que el cupón descontó en esta línea (con IGV); el precio de arriba ya lo trae aplicado.
    descuento = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # Productos que llevan número de serie: la que salió en el comprobante (se asigna sola al
    # pagar, la más antigua) y la que realmente se entregó si el almacén la cambió al preparar.
    series_asignadas = models.JSONField(default=list, blank=True)
    series_fisicas = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "línea de pedido"
        verbose_name_plural = "líneas de pedido"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.pedido_id}: {self.descripcion}"


class ReservaStock(OrganizacionScopedModel):
    """Stock apartado para un pedido mientras se paga. Resta de lo que la tienda ofrece; se
    libera al cancelar o vencer el pedido (la compra definitiva lo consume al pagar)."""

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.CASCADE, related_name="reservas")
    linea = models.OneToOneField(LineaPedido, on_delete=models.CASCADE, related_name="reserva")
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    almacen = models.ForeignKey("mantenimiento.Almacen", on_delete=models.PROTECT, related_name="+")
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    liberada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "reserva de stock"
        verbose_name_plural = "reservas de stock"
        indexes = [
            models.Index(
                fields=["almacen", "producto", "liberada_en"], name="ix_reservastock_activa"
            )
        ]

    def __str__(self) -> str:
        return f"{self.pedido_id}: {self.cantidad} de {self.producto_id}"


class IntentoPago(OrganizacionScopedModel):
    """Un intento de cobrar un pedido. Solo uno puede estar en curso a la vez (evita cobrar dos
    veces con dos clics). Nunca guarda el token, la tarjeta ni lo que responde Culqi."""

    class Estado(models.TextChoices):
        EN_CURSO = "EN_CURSO", "En curso"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        INCIERTO = "INCIERTO", "Sin confirmar (Culqi no respondió)"

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.CASCADE, related_name="intentos")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.EN_CURSO)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    culqi_cargo_id = models.CharField(max_length=40, blank=True)
    mensaje = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "intento de pago"
        verbose_name_plural = "intentos de pago"
        constraints = [
            models.UniqueConstraint(
                fields=["pedido"],
                condition=Q(estado="EN_CURSO", eliminado_en__isnull=True),
                name="uq_intentopago_en_curso",
            )
        ]

    def __str__(self) -> str:
        return f"Intento {self.pk} del pedido {self.pedido_id}: {self.estado}"


class DeudaCobroTienda(OrganizacionScopedModel):
    """Lo que la empresa que recibió el pago de Culqi le debe a la otra empresa del mismo pedido.

    Un pedido con productos de las dos empresas se paga en UNA sola cuenta de Culqi (la de la
    empresa que cobra). La parte que corresponde a la otra empresa queda aquí hasta que se le
    transfiere el dinero; no lleva comisión.
    """

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.PROTECT, related_name="deudas")
    deudora = models.ForeignKey("organizacion.Empresa", on_delete=models.PROTECT, related_name="+")
    acreedora = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="+"
    )
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    liquidada_en = models.DateTimeField(null=True, blank=True)
    # Se llena cuando el pedido se anula o se reembolsa y la deuda se revierte (ver ``deuda_web``).
    revertida_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "deuda por cobro de la tienda"
        verbose_name_plural = "deudas por cobros de la tienda"
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_deudacobrotienda_monto"),
            models.UniqueConstraint(
                fields=["pedido", "acreedora"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_deudacobrotienda_pedido",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.deudora_id} debe {self.monto} a {self.acreedora_id}"


class HistorialPedido(models.Model):
    """Cada cambio de estado y cada nota interna de un pedido (quién, cuándo, qué)."""

    class Tipo(models.TextChoices):
        ESTADO = "ESTADO", "Cambio de estado"
        NOTA = "NOTA", "Nota interna"

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.CASCADE, related_name="historial")
    tipo = models.CharField(max_length=6, choices=Tipo.choices)
    estado = models.CharField(max_length=24, blank=True)
    texto = models.CharField(max_length=500, blank=True)
    usuario_id = models.UUIDField(null=True, blank=True)
    usuario_nombre = models.CharField(max_length=150, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "historial del pedido"
        verbose_name_plural = "historial de pedidos"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.pedido_id}: {self.tipo} {self.estado}"


class Cupon(OrganizacionScopedModel):
    """Código de descuento de la tienda.

    Reglas de la casa: un cupón por pedido; NO se combina con productos en oferta (salvo que el
    cupón lo permita expresamente); el descuento se reparte entre los productos a los que aplica y
    nunca baja un producto de su precio mínimo. El descuento de un cupón de monto o porcentaje se
    calcula sobre lo que paga el cliente (con IGV).
    """

    class Tipo(models.TextChoices):
        PORCENTAJE = "PORCENTAJE", "Porcentaje de descuento"
        MONTO = "MONTO", "Monto fijo de descuento"
        ENVIO_GRATIS = "ENVIO_GRATIS", "Envío gratis"

    class Alcance(models.TextChoices):
        TODO = "TODO", "Toda la tienda"
        CATEGORIAS = "CATEGORIAS", "Solo ciertas categorías"
        MARCAS = "MARCAS", "Solo ciertas marcas"
        PRODUCTOS = "PRODUCTOS", "Solo ciertos productos"

    codigo = models.CharField(max_length=30)  # siempre en mayúsculas
    nombre = models.CharField("para qué es (solo lo ve el negocio)", max_length=100, blank=True)
    tipo = models.CharField(max_length=14, choices=Tipo.choices)
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tope_descuento = models.DecimalField(
        "máximo a descontar (soles)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    compra_minima = models.DecimalField(
        "compra mínima en productos (soles, con IGV)", max_digits=10, decimal_places=2, default=0
    )
    inicia_en = models.DateTimeField(null=True, blank=True)
    termina_en = models.DateTimeField(null=True, blank=True)
    usos_maximos = models.PositiveIntegerField(null=True, blank=True)  # vacío = sin límite
    usos_por_cliente = models.PositiveSmallIntegerField(default=1)
    alcance = models.CharField(max_length=10, choices=Alcance.choices, default=Alcance.TODO)
    categorias = models.ManyToManyField("mantenimiento.Categoria", blank=True, related_name="+")
    marcas = models.ManyToManyField("mantenimiento.Marca", blank=True, related_name="+")
    productos = models.ManyToManyField("mantenimiento.Producto", blank=True, related_name="+")
    solo_primera_compra = models.BooleanField(default=False)
    incluye_ofertas = models.BooleanField("también en productos en oferta", default=False)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "cupón de la tienda"
        verbose_name_plural = "cupones de la tienda"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                Lower("codigo"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_cupon_codigo_vigente",
            ),
            models.CheckConstraint(condition=Q(valor__gte=0), name="ck_cupon_valor_no_negativo"),
        ]

    def __str__(self) -> str:
        return self.codigo


class UsoCupon(OrganizacionScopedModel):
    """Cada vez que un pedido usa un cupón. Se aparta al crear el pedido, se consume al pagar y se
    libera si el pedido vence o se cancela."""

    class Estado(models.TextChoices):
        RESERVADO = "RESERVADO", "Apartado (esperando el pago)"
        CONSUMIDO = "CONSUMIDO", "Usado"
        LIBERADO = "LIBERADO", "Liberado"

    cupon = models.ForeignKey(Cupon, on_delete=models.PROTECT, related_name="usos")
    pedido = models.OneToOneField(
        "tienda.PedidoTienda", on_delete=models.CASCADE, related_name="uso_cupon"
    )
    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.PROTECT, related_name="+")
    monto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.RESERVADO)

    class Meta:
        verbose_name = "uso de cupón"
        verbose_name_plural = "usos de cupones"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.cupon_id} en el pedido {self.pedido_id} ({self.estado})"


class AvisoPedido(OrganizacionScopedModel):
    """Un aviso automático al cliente por un pedido (uno por pedido, evento y canal).

    Es la bandeja de salida: se anota aquí, una tarea lo envía y aquí queda cómo salió. Sirve para
    que el negocio vea si el cliente fue avisado, y para no repetir un aviso.
    """

    class Canal(models.TextChoices):
        CORREO = "CORREO", "Correo"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ENVIADO = "ENVIADO", "Enviado"
        FALLIDO = "FALLIDO", "No se pudo enviar"
        OMITIDO = "OMITIDO", "No se envió"

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.CASCADE, related_name="avisos")
    evento = models.CharField(max_length=24)  # PEDIDO_PAGADO, PEDIDO_ENVIADO…
    canal = models.CharField(max_length=10, choices=Canal.choices)
    destino = models.CharField(max_length=150, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    intentos = models.PositiveSmallIntegerField(default=0)
    detalle = models.CharField(max_length=255, blank=True)
    externo_id = models.CharField(max_length=80, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "aviso de pedido"
        verbose_name_plural = "avisos de pedidos"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pedido", "evento", "canal"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_avisopedido_pedido_evento_canal",
            )
        ]

    def __str__(self) -> str:
        return f"{self.pedido_id}: {self.evento} por {self.canal} ({self.estado})"


class ConfiguracionArmador(OrganizacionScopedModel):
    """«Arma tu PC»: qué categorías llenan cada espacio y qué reglas de compatibilidad se usan.

    Es solo configuración (no toca los productos). ``espacios`` es una lista validada por
    ``armador.validar_configuracion``: [{clave, categorias:[ids], obligatorio, max_unidades}].
    ``reglas`` guarda lo ajustado de cada regla: {id: {activa, claves:{alias: clave}}}.
    """

    activo = models.BooleanField(default=False)
    espacios = models.JSONField(default=list, blank=True)
    reglas = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "configuración del armador"
        verbose_name_plural = "configuraciones del armador"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configarmador_organizacion",
            )
        ]

    def __str__(self) -> str:
        return f"Armador de la organización {self.organizacion_id}"


# ---------------------------------------------------------------------------
# Ofertas y banners de la tienda
# ---------------------------------------------------------------------------
class OfertaProducto(OrganizacionScopedModel):
    """Precio especial SOLO para la tienda en línea, con fecha de inicio y de fin.

    ``precio_oferta`` va SIN IGV (igual que las listas de precios). El estado se calcula con la
    fecha: programada, vigente o vencida; ``activa`` permite pausarla sin borrarla.
    """

    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    precio_oferta = models.DecimalField(max_digits=14, decimal_places=2)
    desde = models.DateTimeField()
    hasta = models.DateTimeField()
    etiqueta = models.CharField(max_length=30, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "oferta de producto"
        verbose_name_plural = "ofertas de productos"
        ordering = ["-desde", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(hasta__gt=models.F("desde")), name="ck_oferta_fechas"
            ),
            models.CheckConstraint(condition=Q(precio_oferta__gt=0), name="ck_oferta_precio"),
        ]
        indexes = [
            models.Index(fields=["producto", "desde", "hasta"], name="ix_oferta_producto_fechas"),
            models.Index(
                fields=["organizacion", "activa", "desde", "hasta"], name="ix_oferta_vigencia"
            ),
        ]

    def __str__(self) -> str:
        return f"Oferta de {self.producto_id}: {self.precio_oferta}"


def _ruta_banner(instancia, nombre: str) -> str:
    return f"tienda/{instancia.organizacion_id}/banners/{nombre}"


class BannerTienda(OrganizacionScopedModel):
    """Imagen promocional del inicio de la tienda (carrusel)."""

    titulo = models.CharField(max_length=100)
    subtitulo = models.CharField(max_length=160, blank=True)
    boton_texto = models.CharField(max_length=30, blank=True)
    # Dirección DENTRO de la tienda («/ofertas», «/categoria/laptops») o una URL https.
    enlace = models.CharField(max_length=300, blank=True)
    # Texto alternativo de la imagen (lo lee quien usa lector de pantalla).
    alt = models.CharField(max_length=150)
    imagen_escritorio = models.FileField(upload_to=_ruta_banner, max_length=255, blank=True)
    imagen_movil = models.FileField(upload_to=_ruta_banner, max_length=255, blank=True)
    version = models.CharField(max_length=12, blank=True, default="")
    orden = models.PositiveSmallIntegerField(default=0)
    desde = models.DateTimeField(null=True, blank=True)
    hasta = models.DateTimeField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "banner de la tienda"
        verbose_name_plural = "banners de la tienda"
        ordering = ["orden", "id"]
        indexes = [
            models.Index(fields=["organizacion", "activo", "orden"], name="ix_banner_activo")
        ]

    def __str__(self) -> str:
        return self.titulo


class CambioSerie(OrganizacionScopedModel):
    """Quién cambió la serie de una línea de pedido, de cuál a cuál y por qué (solo se agrega)."""

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.CASCADE, related_name="cambios_serie")
    linea = models.ForeignKey(LineaPedido, on_delete=models.CASCADE, related_name="cambios_serie")
    serie_anterior = models.CharField(max_length=40)
    serie_nueva = models.CharField(max_length=40)
    motivo = models.CharField(max_length=200)
    usuario_id = models.UUIDField(null=True, blank=True)

    class Meta:
        verbose_name = "cambio de serie"
        verbose_name_plural = "cambios de serie"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.serie_anterior} → {self.serie_nueva}"


class ReembolsoPedido(OrganizacionScopedModel):
    """Una devolución de dinero de un pedido pagado con Culqi (total o parcial).

    Se crea DESPUÉS de deshacer lo interno (anular la venta o emitir la nota de crédito) y antes
    de llamar a Culqi: así, si Culqi falla, queda anotado qué falta devolver y se reintenta sin
    volver a tocar nada interno. ``clave`` es la clave de idempotencia ante Culqi.
    """

    class Tipo(models.TextChoices):
        ANULACION = "ANULACION", "Anulación de la venta"
        NOTA_CREDITO = "NOTA_CREDITO", "Nota de crédito (devolución)"
        SOLO_DINERO = "SOLO_DINERO", "Solo devolver el dinero"

    class Estado(models.TextChoices):
        SOLICITADO = "SOLICITADO", "Solicitado (falta confirmar en Culqi)"
        APROBADO = "APROBADO", "Aprobado por Culqi"

    class Motivo(models.TextChoices):
        SOLICITUD_CLIENTE = "SOLICITUD_CLIENTE", "Lo pidió el cliente"
        DUPLICADO = "DUPLICADO", "Cobro duplicado"
        FRAUDE = "FRAUDE", "Sospecha de fraude"
        SIN_STOCK = "SIN_STOCK", "No se puede entregar (sin stock)"
        NO_RECOGIDO = "NO_RECOGIDO", "No recogió su pedido a tiempo"
        OTRO = "OTRO", "Otro motivo"

    pedido = models.ForeignKey(PedidoTienda, on_delete=models.PROTECT, related_name="reembolsos")
    tipo = models.CharField(max_length=14, choices=Tipo.choices)
    estado_previo = models.CharField(max_length=24)
    motivo_tipo = models.CharField(max_length=20, choices=Motivo.choices)
    motivo = models.CharField(max_length=250)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.SOLICITADO)
    clave = models.CharField(max_length=64, unique=True)
    culqi_reembolso_id = models.CharField(max_length=40, blank=True)
    # Notas de crédito emitidas y si se anuló la venta (rastro de lo interno).
    notas_credito = models.JSONField(default=list, blank=True)
    venta_anulada = models.BooleanField(default=False)
    usuario_id = models.UUIDField(null=True, blank=True)
    usuario_nombre = models.CharField(max_length=150, blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    mensaje = models.CharField(max_length=250, blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "reembolso de pedido"
        verbose_name_plural = "reembolsos de pedidos"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.pedido_id}: {self.tipo} {self.monto}"


class ConfiguracionResenas(OrganizacionScopedModel):
    """Cómo se piden las reseñas: un correo unos días después de entregar el pedido.

    Las reseñas se publican solas; el dueño puede ocultarlas. Este correo es opcional, va solo a
    clientes que aceptaron recibir comunicaciones y lleva su enlace de baja.
    """

    pedir_activo = models.BooleanField(default=False)
    pedir_dias = models.PositiveSmallIntegerField("días después de entregar", default=3)

    class Meta:
        verbose_name = "configuración de reseñas"
        verbose_name_plural = "configuraciones de reseñas"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configresenas_organizacion",
            )
        ]

    def __str__(self) -> str:
        return f"Reseñas de la organización {self.organizacion_id}"


class ResenaProducto(OrganizacionScopedModel):
    """La opinión de un cliente que ya recibió el producto (una por cliente y producto)."""

    class Estado(models.TextChoices):
        PUBLICADA = "PUBLICADA", "Publicada"
        OCULTA = "OCULTA", "Oculta"

    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.PROTECT, related_name="resenas")
    # El pedido entregado que da derecho a opinar.
    pedido = models.ForeignKey(PedidoTienda, on_delete=models.PROTECT, related_name="resenas")
    estrellas = models.PositiveSmallIntegerField()
    titulo = models.CharField(max_length=80, blank=True)
    comentario = models.CharField(max_length=1000, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PUBLICADA)
    oculta_motivo = models.CharField(max_length=200, blank=True)
    respuesta = models.CharField(max_length=600, blank=True)
    respuesta_en = models.DateTimeField(null=True, blank=True)
    respuesta_por = models.CharField(max_length=150, blank=True)
    editada_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "reseña de producto"
        verbose_name_plural = "reseñas de productos"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["cuenta", "producto"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_resena_cuenta_producto",
            ),
            models.CheckConstraint(
                condition=Q(estrellas__gte=1, estrellas__lte=5), name="ck_resena_estrellas"
            ),
        ]
        indexes = [models.Index(fields=["producto", "estado"], name="ix_resena_producto_estado")]

    def __str__(self) -> str:
        return f"{self.producto_id}: {self.estrellas}★ de {self.cuenta_id}"


class Favorito(OrganizacionScopedModel):
    """Un producto que el cliente guardó para verlo después (el corazón de la tienda)."""

    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.CASCADE, related_name="favoritos")
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.CASCADE, related_name="+"
    )

    class Meta:
        verbose_name = "favorito"
        verbose_name_plural = "favoritos"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["cuenta", "producto"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_favorito_cuenta_producto",
            )
        ]

    def __str__(self) -> str:
        return f"{self.cuenta_id}: {self.producto_id}"


class AvisoDisponibilidad(OrganizacionScopedModel):
    """«Avísame cuando llegue»: el cliente pidió que le escribamos cuando haya stock.

    Se avisa una sola vez por pedido de aviso (queda ``avisado_en``); si no llega nunca, vence solo.
    """

    cuenta = models.ForeignKey(CuentaCliente, on_delete=models.CASCADE, related_name="avisos_stock")
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.CASCADE, related_name="+"
    )
    avisado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "aviso de disponibilidad"
        verbose_name_plural = "avisos de disponibilidad"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["cuenta", "producto"],
                condition=Q(eliminado_en__isnull=True, avisado_en__isnull=True),
                name="uq_avisodisp_cuenta_producto_pendiente",
            )
        ]
        indexes = [
            models.Index(fields=["producto", "avisado_en"], name="ix_avisodisp_prod_avisado")
        ]

    def __str__(self) -> str:
        estado = "avisado" if self.avisado_en else "pendiente"
        return f"{self.cuenta_id}: {self.producto_id} ({estado})"


class Reclamo(OrganizacionScopedModel):
    """Hoja de reclamación del Libro de Reclamaciones virtual (obligatorio en Perú).

    Se registra con todos los datos que pide la norma (consumidor, bien contratado, detalle y pedido
    del consumidor) y un número correlativo por año. El negocio debe responder en 15 días hábiles
    (``vence_en``); esa respuesta se guarda y se manda al correo del consumidor.
    """

    class Tipo(models.TextChoices):
        RECLAMO = "RECLAMO", "Reclamo"
        QUEJA = "QUEJA", "Queja"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Por responder"
        RESPONDIDO = "RESPONDIDO", "Respondido"

    numero = models.CharField(max_length=12)  # «0001-2026»
    empresa = models.ForeignKey("organizacion.Empresa", on_delete=models.PROTECT, related_name="+")
    cuenta = models.ForeignKey(
        CuentaCliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tipo = models.CharField(max_length=8, choices=Tipo.choices)
    # --- Consumidor ---
    nombre = models.CharField(max_length=150)
    documento_tipo = models.CharField(max_length=10)
    documento_numero = models.CharField(max_length=20)
    domicilio = models.CharField(max_length=250)
    telefono = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(max_length=150)
    menor_de_edad = models.BooleanField(default=False)
    apoderado = models.CharField(max_length=150, blank=True)
    # --- Bien contratado ---
    bien_tipo = models.CharField(max_length=10)  # PRODUCTO | SERVICIO
    monto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    bien_descripcion = models.CharField(max_length=300)
    pedido_numero = models.CharField(max_length=20, blank=True)
    # --- Detalle ---
    detalle = models.CharField(max_length=2000)
    pedido_consumidor = models.CharField(max_length=1000)
    # --- Seguimiento ---
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    vence_en = models.DateTimeField()
    respuesta = models.CharField(max_length=2000, blank=True)
    respondido_en = models.DateTimeField(null=True, blank=True)
    respondido_por = models.CharField(max_length=150, blank=True)
    respuesta_enviada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "reclamo"
        verbose_name_plural = "reclamos"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "numero"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_reclamo_numero",
            )
        ]
        indexes = [
            models.Index(fields=["organizacion", "estado", "vence_en"], name="ix_reclamo_estado")
        ]

    def __str__(self) -> str:
        return f"Reclamo {self.numero} ({self.estado})"


class PaginaLegal(OrganizacionScopedModel):
    """Una página de texto de la tienda (términos, privacidad, cambios…) que edita el negocio."""

    slug = models.SlugField(max_length=40)
    titulo = models.CharField(max_length=120)
    contenido = models.TextField(max_length=30000, blank=True)
    publicada = models.BooleanField(default=False)

    class Meta:
        verbose_name = "página legal"
        verbose_name_plural = "páginas legales"
        ordering = ["slug"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "slug"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_paginalegal_slug",
            )
        ]

    def __str__(self) -> str:
        return f"{self.slug} ({'publicada' if self.publicada else 'borrador'})"
