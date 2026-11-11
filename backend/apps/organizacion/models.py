"""Organización → Empresa (RUC) → Sucursal. La organización es el límite duro de aislamiento."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models
from django.db.models import Q

from apps.core.crypto import CampoCifrado
from apps.core.models import EmpresaScopedModel, ModeloBase, OrganizacionScopedModel

from .validators import validar_ruc


class Estado(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    INACTIVO = "INACTIVO", "Inactivo"
    SUSPENDIDO = "SUSPENDIDO", "Suspendido"


class Organizacion(ModeloBase):
    """Raíz del sistema. Cliente que contrata: agrupa sus empresas, usuarios y datos."""

    nombre = models.CharField(max_length=200)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    # Si es True, todo usuario debe activar el segundo factor antes de operar.
    mfa_obligatorio = models.BooleanField(default=False)

    class CalculoPrecios(models.TextChoices):
        UTILIDAD = "UTILIDAD", "Utilidad sobre el costo"
        MARGEN = "MARGEN", "Margen sobre el precio de venta"

    # Cómo se piensa la ganancia al poner precios: utilidad (precio = costo × (1 + u)) o margen
    # (precio = costo ÷ (1 − m)). Solo cambia el porcentaje que se escribe y se muestra: el precio
    # es lo que se guarda, así que cambiar de forma no altera ningún precio.
    calculo_precios = models.CharField(
        max_length=10, choices=CalculoPrecios.choices, default=CalculoPrecios.UTILIDAD
    )

    class Meta:
        verbose_name = "organización"
        verbose_name_plural = "organizaciones"
        constraints = [
            models.UniqueConstraint(
                fields=["nombre"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_organizacion_nombre_vigente",
            )
        ]
        indexes = [models.Index(fields=["estado"], name="ix_organizacion_estado")]

    def __str__(self) -> str:
        return self.nombre


validar_url_web = URLValidator(schemes=["http", "https"])


def _ruta_logo(instancia, nombre: str) -> str:
    return f"empresas/{instancia.pk}/{nombre}"


class Empresa(OrganizacionScopedModel):
    """Entidad tributaria con RUC propio."""

    razon_social = models.CharField(max_length=250)
    ruc = models.CharField(max_length=11, validators=[validar_ruc])
    nombre_comercial = models.CharField(max_length=250, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)
    # Datos de la ficha que salen en los comprobantes y documentos que se entregan al cliente.
    direccion_fiscal = models.CharField(max_length=250, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    correo = models.EmailField(max_length=150, blank=True)
    sitio_web = models.CharField(max_length=200, blank=True, validators=[validar_url_web])
    tienda_web = models.CharField(max_length=200, blank=True, validators=[validar_url_web])
    # Logo ya re-codificado a PNG (``services/logo.py``). No es público: se sirve por la API.
    logo = models.FileField(upload_to=_ruta_logo, max_length=255, blank=True)
    # La empresa "cara" del grupo: la que da la imagen a la tienda virtual compartida.
    es_principal = models.BooleanField(default=False)

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        constraints = [
            models.UniqueConstraint(
                fields=["ruc"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_empresa_ruc_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(es_principal=True, eliminado_en__isnull=True),
                name="uq_empresa_principal_por_organizacion",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_empresa_org_estado")]

    def __str__(self) -> str:
        return f"{self.razon_social} ({self.ruc})"


class Sucursal(EmpresaScopedModel):
    """Sucursal de una empresa. Un local físico compartido = una sucursal por empresa."""

    nombre = models.CharField(max_length=150)
    codigo = models.CharField(max_length=10)
    # Identifica el local físico común entre sucursales de distintas empresas.
    local_fisico = models.CharField(max_length=50, blank=True)
    direccion = models.CharField(max_length=250, blank=True)
    # Código INEI de su distrito (opcional): la guía de remisión lo propone como ubigeo de partida.
    ubigeo = models.CharField(max_length=6, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVO)

    class Meta:
        verbose_name = "sucursal"
        verbose_name_plural = "sucursales"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_sucursal_empresa_codigo_vigente",
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"], name="ix_sucursal_empresa_estado"),
            models.Index(fields=["local_fisico"], name="ix_sucursal_local_fisico"),
        ]

    def __str__(self) -> str:
        return f"{self.nombre} [{self.codigo}]"


class RegimenIgv(models.TextChoices):
    NORMAL = "NORMAL", "Normal (18 %)"
    AMAZONIA = "AMAZONIA", "Beneficio de la Amazonía"


class ConfiguracionEmpresa(EmpresaScopedModel):
    """Parámetros fiscales y credenciales SUNAT (cifradas) de una empresa.

    El porcentaje del IGV ya no vive aquí: está en las tasas de impuesto de la organización
    (con su fecha de vigencia).
    """

    class ModoSunat(models.TextChoices):
        BETA = "BETA", "Beta (pruebas)"
        PRODUCCION = "PRODUCCION", "Producción"

    modo_sunat = models.CharField(max_length=10, choices=ModoSunat.choices, default=ModoSunat.BETA)
    sunat_usuario_sol = CampoCifrado(blank=True)
    sunat_clave_sol = CampoCifrado(blank=True)
    regimen_igv = models.CharField(
        "régimen del IGV",
        max_length=10,
        choices=RegimenIgv.choices,
        default=RegimenIgv.NORMAL,
        help_text="Normal: se vende con IGV. Amazonía: se vende exonerado dentro de la región "
        "y con IGV fuera de ella.",
    )
    igv_compras_al_costo = models.BooleanField(
        "el IGV de las compras gravadas se suma al costo",
        default=False,
        help_text="Si la empresa no usa ese IGV como crédito fiscal, forma parte del costo del "
        "producto. Lo aplica el módulo de Compras.",
    )
    moneda = models.CharField(max_length=3, default="PEN")

    # --- Facturación electrónica (API propia de facturación) ---------------------------------
    sunat_activo = models.BooleanField(
        "facturación electrónica activa",
        default=False,
        help_text="Mientras esté apagada, nada se envía a SUNAT.",
    )
    # Credenciales de la guía de remisión electrónica (se sacan desde la Clave SOL).
    sunat_gre_client_id = CampoCifrado(blank=True)
    sunat_gre_client_secret = CampoCifrado(blank=True)
    # Ubicación del domicilio fiscal (la API pide ubigeo, departamento, provincia y distrito).
    ubigeo_fiscal = models.CharField("ubigeo del domicilio fiscal", max_length=6, blank=True)
    urbanizacion = models.CharField(max_length=100, blank=True)
    # Código SUNAT que llevan los productos que no tienen uno propio.
    codigo_sunat_defecto = models.CharField(
        "código SUNAT por defecto de los productos", max_length=8, blank=True
    )
    gasto_sin_comprobante_maximo = models.DecimalField(
        "tope de un gasto sin comprobante (soles)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("100.00"),
        help_text="Un gasto sin comprobante (un taxi, por ejemplo) no puede pasar de este "
        "monto, salvo con un permiso especial.",
    )
    dias_stock_antiguo = models.PositiveSmallIntegerField(
        "días para considerar stock antiguo",
        default=90,
        validators=[MinValueValidator(1), MaxValueValidator(3650)],
        help_text="El stock que lleva más de estos días en el almacén se marca como antiguo "
        "(reporte de antigüedad y aviso al vender).",
    )
    orden_compra_monto_aprobacion = models.DecimalField(
        "monto desde el que una orden de compra necesita aprobación (soles)",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Una orden de compra que pase de este monto debe aprobarla quien tenga el "
        "permiso. Vacío = nunca pide aprobación.",
    )
    orden_compra_tolerancia = models.DecimalField(
        "tolerancia al recibir de más (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Cuánto más de lo pedido se puede recibir de una orden de compra. 0 = nada más.",
    )

    class Meta:
        verbose_name = "configuración de empresa"
        verbose_name_plural = "configuraciones de empresa"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configuracion_empresa_vigente",
            )
        ]

    def __str__(self) -> str:
        return f"Configuración de {self.empresa_id}"
