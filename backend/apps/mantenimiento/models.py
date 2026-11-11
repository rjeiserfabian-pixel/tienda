"""Maestros del módulo Mantenimiento: clientes, proveedores y personal.

Clientes y proveedores son datos de la ORGANIZACIÓN (los comparten todas sus empresas); el
personal es de cada EMPRESA. Ninguno se borra físicamente: «eliminar» es borrado lógico, y
«desactivar» (estado) los saca de las listas de selección sin perder su historial.
"""

import re
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.text import slugify

from apps.core.models import EmpresaScopedModel, OrganizacionScopedModel
from apps.organizacion.validators import ruc_es_valido

from .validators import normalizar_documento, validar_documento


class TipoDocumento(models.TextChoices):
    DNI = "DNI", "DNI"
    RUC = "RUC", "RUC"
    CE = "CE", "Carné de extranjería"
    PASAPORTE = "PASAPORTE", "Pasaporte"
    OTRO = "OTRO", "Otro"


class EstadoRegistro(models.TextChoices):
    ACTIVO = "ACTIVO", "Activo"
    INACTIVO = "INACTIVO", "Inactivo"


class Banco(models.TextChoices):
    BCP = "BCP", "BCP"
    BBVA = "BBVA", "BBVA"
    INTERBANK = "INTERBANK", "Interbank"
    SCOTIABANK = "SCOTIABANK", "Scotiabank"
    BANCO_NACION = "BANCO_NACION", "Banco de la Nación"
    BANBIF = "BANBIF", "BanBif"
    PICHINCHA = "PICHINCHA", "Banco Pichincha"
    MIBANCO = "MIBANCO", "Mibanco"
    OTRO = "OTRO", "Otro"


class Area(models.TextChoices):
    ADMINISTRACION = "ADMINISTRACION", "Administración"
    VENTAS = "VENTAS", "Ventas"
    TECNICO = "TECNICO", "Técnico"
    ALMACEN = "ALMACEN", "Almacén"
    OTRO = "OTRO", "Otro"


class ZonaFiscal(models.TextChoices):
    """Dónde está el cliente o proveedor respecto de la región con beneficio de la Amazonía."""

    DENTRO = "DENTRO", "Dentro de la región (Amazonía)"
    FUERA = "FUERA", "Fuera de la región"


class _ConDocumento(models.Model):
    """Documento de identidad con su validación (DNI, RUC, CE…)."""

    tipo_documento = models.CharField(
        max_length=10, choices=TipoDocumento.choices, default=TipoDocumento.DNI
    )
    numero_documento = models.CharField(max_length=20)

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        self.numero_documento = normalizar_documento(self.numero_documento)
        validar_documento(self.tipo_documento, self.numero_documento)


class _Contacto(models.Model):
    direccion = models.CharField(max_length=250, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    correo = models.EmailField(blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        abstract = True


class _Catalogo(models.Model):
    """Nombre + estado de un catálogo simple. El nombre no distingue mayúsculas al repetirse."""

    nombre = models.CharField(max_length=100)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())  # sin espacios de más
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})


def _slug_unico(modelo, organizacion_id: int, nombre: str, excluir_pk=None) -> str:
    """Dirección web a partir del nombre, sin repetir las de otros registros de la organización."""
    base = (slugify(nombre) or "sin-nombre")[:100].strip("-") or "sin-nombre"
    otros = modelo.objects.sin_ambito().filter(organizacion_id=organizacion_id)
    if excluir_pk is not None:
        otros = otros.exclude(pk=excluir_pk)
    usados = set(otros.filter(slug__startswith=base).values_list("slug", flat=True))
    slug, n = base, 2
    while slug in usados:
        slug = f"{base}-{n}"
        n += 1
    return slug


class _ConSlug(models.Model):
    """Dirección web estable (para la tienda): se genera al crear y no cambia si se renombra."""

    slug = models.SlugField(max_length=120, blank=True, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.slug and self.nombre and self.organizacion_id:
            self.slug = _slug_unico(type(self), self.organizacion_id, self.nombre, self.pk)
            campos = kwargs.get("update_fields")
            if campos is not None and "slug" not in campos:
                kwargs["update_fields"] = [*campos, "slug"]
        super().save(*args, **kwargs)


class Familia(_ConSlug, _Catalogo, OrganizacionScopedModel):
    """Grupo general de productos (p. ej. Repuestos). Compartida por todas las empresas."""

    class Meta:
        verbose_name = "familia"
        verbose_name_plural = "familias"
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_familia_nombre_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "slug"],
                condition=~Q(slug="") & Q(eliminado_en__isnull=True),
                name="uq_familia_slug_vigente",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_familia_org_estado")]


class Categoria(_ConSlug, _Catalogo, OrganizacionScopedModel):
    """Tipo específico dentro de una familia (p. ej. Teclado, dentro de Repuestos)."""

    familia = models.ForeignKey(Familia, on_delete=models.PROTECT, related_name="categorias")

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "familia",
                condition=Q(eliminado_en__isnull=True),
                name="uq_categoria_familia_nombre_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "slug"],
                condition=~Q(slug="") & Q(eliminado_en__isnull=True),
                name="uq_categoria_slug_vigente",
            ),
        ]
        indexes = [
            models.Index(fields=["organizacion", "familia"], name="ix_categoria_org_familia")
        ]

    def clean(self):
        super().clean()
        if (
            self.familia_id
            and self.organizacion_id
            and self.familia.organizacion_id != self.organizacion_id
        ):
            raise ValidationError({"familia": "La familia no pertenece a la organización."})


class Marca(_ConSlug, _Catalogo, OrganizacionScopedModel):
    """Marca de los productos. Compartida por todas las empresas."""

    class Meta:
        verbose_name = "marca"
        verbose_name_plural = "marcas"
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_marca_nombre_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "slug"],
                condition=~Q(slug="") & Q(eliminado_en__isnull=True),
                name="uq_marca_slug_vigente",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_marca_org_estado")]


class Cliente(_ConDocumento, _Contacto, OrganizacionScopedModel):
    nombre = models.CharField("nombre o razón social", max_length=250)
    nombre_comercial = models.CharField(max_length=250, blank=True)
    # Código INEI de su distrito (opcional): la guía de remisión lo propone como ubigeo.
    ubigeo = models.CharField(max_length=6, blank=True)
    # Quién atiende al cliente: por defecto quien lo registra; solo quien tiene el permiso de
    # asignar asesor puede elegir o cambiar a otro.
    asesor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clientes_asesorados",
    )
    # Propone el IGV de la venta: dentro de la región = exonerado; fuera = gravado.
    zona = models.CharField(max_length=10, choices=ZonaFiscal.choices, blank=True)
    # Hasta cuánto (en soles) se le puede vender a crédito. Cero = no tiene crédito autorizado.
    limite_credito = models.DecimalField(
        "límite de crédito (S/)", max_digits=14, decimal_places=2, default=Decimal("0")
    )
    # Por defecto el crédito no tiene tope: se le vende a crédito sin importar cuánto deba. Quien
    # tiene el permiso puede ponerle un tope (``limite_credito``); en cero, no tiene crédito.
    credito_sin_limite = models.BooleanField("crédito sin tope", default=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "tipo_documento", "numero_documento"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_cliente_documento_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_cliente_org_estado")]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.numero_documento})"


class Proveedor(_ConDocumento, _Contacto, OrganizacionScopedModel):
    nombre = models.CharField("razón social", max_length=250)
    nombre_comercial = models.CharField(max_length=250, blank=True)
    # Código INEI de su distrito (opcional): la guía de remisión lo propone como ubigeo.
    ubigeo = models.CharField(max_length=6, blank=True)
    contacto = models.CharField("persona de contacto", max_length=150, blank=True)
    # Para pagarle: banco y número de cuenta (el número es sensible: no va a la auditoría).
    banco = models.CharField(max_length=20, choices=Banco.choices, blank=True)
    cuenta_bancaria = models.CharField("cuenta bancaria", max_length=30, blank=True)
    # Qué vende, en palabras libres: sirve para encontrar al proveedor por producto.
    productos_referencia = models.TextField("productos de referencia", max_length=1000, blank=True)
    # Propone el IGV de la compra: dentro de la región = exonerado; fuera (Lima) = gravado.
    zona = models.CharField(max_length=10, choices=ZonaFiscal.choices, blank=True)
    # De qué ciudad es (Lima, Arequipa, Tarapoto…): texto libre para ubicarlo y buscarlo.
    ciudad = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "tipo_documento", "numero_documento"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_proveedor_documento_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_proveedor_org_estado")]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.numero_documento})"

    def clean(self):
        super().clean()
        self.ciudad = " ".join((self.ciudad or "").split())
        self.cuenta_bancaria = " ".join((self.cuenta_bancaria or "").split())
        if self.cuenta_bancaria and not re.fullmatch(
            r"[0-9A-Za-z][0-9A-Za-z\- ]{4,29}", self.cuenta_bancaria
        ):
            raise ValidationError({"cuenta_bancaria": "Use de 5 a 30 letras, números o guiones."})
        if self.cuenta_bancaria and not self.banco:
            raise ValidationError({"banco": "Elija el banco de la cuenta."})


class Personal(_ConDocumento, _Contacto, EmpresaScopedModel):
    """Trabajador de una empresa. Puede o no tener usuario del sistema (vínculo futuro)."""

    nombres = models.CharField(max_length=150)
    apellidos = models.CharField(max_length=150)
    area = models.CharField(max_length=15, choices=Area.choices, default=Area.ADMINISTRACION)
    cargo = models.CharField(max_length=100, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    fecha_ingreso = models.DateField(null=True, blank=True)
    # Vínculo opcional: no todo trabajador usa el sistema ni todo usuario es trabajador.
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trabajador",
    )

    class Meta:
        verbose_name = "personal"
        verbose_name_plural = "personal"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_documento", "numero_documento"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_personal_documento_vigente",
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"], name="ix_personal_empresa_estado"),
            models.Index(fields=["empresa", "area"], name="ix_personal_empresa_area"),
        ]

    def __str__(self) -> str:
        return f"{self.nombre_completo} ({self.numero_documento})"

    def clean(self):
        super().clean()
        nacimiento = self.fecha_nacimiento
        if nacimiento and not date(1900, 1, 1) <= nacimiento <= date.today():
            raise ValidationError({"fecha_nacimiento": "Ingrese una fecha de nacimiento válida."})
        if nacimiento and self.fecha_ingreso and self.fecha_ingreso < nacimiento:
            raise ValidationError(
                {"fecha_ingreso": "El ingreso no puede ser anterior al nacimiento."}
            )

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}".strip()


class TipoAlmacen(models.TextChoices):
    PRINCIPAL = "PRINCIPAL", "Principal"
    EXHIBICION = "EXHIBICION", "Exhibición"
    SERVICIO_TECNICO = "SERVICIO_TECNICO", "Servicio técnico"
    MERMAS = "MERMAS", "Mermas o averiados"
    OTRO = "OTRO", "Otro"


class Almacen(EmpresaScopedModel):
    """Lugar donde una empresa guarda su mercadería. El stock se cuenta por almacén."""

    RESTRICCIONES = {
        "uq_almacen_codigo_vigente": (
            "codigo",
            "Ya existe un almacén con ese código en la empresa.",
        ),
        "uq_almacen_nombre_vigente": (
            "nombre",
            "Ya existe un almacén con ese nombre en la empresa.",
        ),
    }

    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=100)
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", on_delete=models.PROTECT, related_name="almacenes"
    )
    tipo = models.CharField(
        max_length=20, choices=TipoAlmacen.choices, default=TipoAlmacen.PRINCIPAL
    )
    permite_venta = models.BooleanField("se vende desde aquí", default=True)
    direccion = models.CharField(max_length=250, blank=True)
    # Código INEI de su distrito (opcional): la guía de remisión lo propone como ubigeo de partida.
    ubigeo = models.CharField(max_length=6, blank=True)
    responsable = models.ForeignKey(
        Personal,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="almacenes_a_cargo",
    )
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "almacén"
        verbose_name_plural = "almacenes"
        constraints = [
            models.UniqueConstraint(
                Lower("codigo"),
                "empresa",
                condition=Q(eliminado_en__isnull=True),
                name="uq_almacen_codigo_vigente",
            ),
            models.UniqueConstraint(
                Lower("nombre"),
                "empresa",
                condition=Q(eliminado_en__isnull=True),
                name="uq_almacen_nombre_vigente",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"], name="ix_almacen_empresa_estado"),
            models.Index(fields=["sucursal"], name="ix_almacen_sucursal"),
        ]

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
        if self.sucursal_id and self.sucursal.empresa_id != self.empresa_id:
            raise ValidationError({"sucursal": "La sucursal no pertenece a la empresa."})
        if self.responsable_id and self.responsable.empresa_id != self.empresa_id:
            raise ValidationError({"responsable": "El responsable debe ser de la misma empresa."})


class Ubicacion(EmpresaScopedModel):
    """Lugar físico dentro de un almacén (vitrina, estante, caja) para hallar rápido un producto."""

    RESTRICCIONES = {
        "uq_ubicacion_codigo_vigente": (
            "codigo",
            "Ya existe una ubicación con ese código en el almacén.",
        ),
    }

    almacen = models.ForeignKey(Almacen, on_delete=models.PROTECT, related_name="ubicaciones")
    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=100)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "ubicación"
        verbose_name_plural = "ubicaciones"
        constraints = [
            models.UniqueConstraint(
                Lower("codigo"),
                "almacen",
                condition=Q(eliminado_en__isnull=True),
                name="uq_ubicacion_codigo_vigente",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "almacen"], name="ix_ubicacion_empresa_almacen")]

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
        if self.almacen_id and self.almacen.empresa_id != self.empresa_id:
            raise ValidationError({"almacen": "El almacén no pertenece a la empresa."})


class UbicacionProducto(EmpresaScopedModel):
    """Dónde está un producto dentro de un almacén (una ubicación por almacén).

    Es independiente del stock: se puede asignar antes de que el producto tenga existencias.
    """

    almacen = models.ForeignKey(Almacen, on_delete=models.PROTECT, related_name="+")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT, related_name="ubicaciones")
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name="productos")

    class Meta:
        verbose_name = "ubicación de producto"
        verbose_name_plural = "ubicaciones de productos"
        constraints = [
            models.UniqueConstraint(
                fields=["almacen", "producto"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_ubicacionproducto_vigente",
            ),
        ]
        indexes = [models.Index(fields=["empresa", "ubicacion"], name="ix_ubicprod_empresa_ubic")]

    def __str__(self) -> str:
        return f"{self.producto_id} @ {self.ubicacion_id}"

    def clean(self):
        super().clean()
        if self.almacen_id and self.almacen.empresa_id != self.empresa_id:
            raise ValidationError({"almacen": "El almacén no pertenece a la empresa."})
        if self.ubicacion_id and self.ubicacion.almacen_id != self.almacen_id:
            raise ValidationError({"ubicacion": "La ubicación no es de ese almacén."})


class CentroCosto(OrganizacionScopedModel):
    """Área del negocio a la que se cargan los gastos. Compartido por todas las empresas."""

    RESTRICCIONES = {
        "uq_centrocosto_codigo_vigente": ("codigo", "Ya existe un centro de costo con ese código."),
        "uq_centrocosto_nombre_vigente": ("nombre", "Ya existe un centro de costo con ese nombre."),
    }

    codigo = models.CharField(max_length=20)
    nombre = models.CharField(max_length=100)
    padre = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="hijos"
    )
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "centro de costo"
        verbose_name_plural = "centros de costo"
        constraints = [
            models.UniqueConstraint(
                Lower("codigo"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_centrocosto_codigo_vigente",
            ),
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_centrocosto_nombre_vigente",
            ),
        ]
        indexes = [
            models.Index(fields=["organizacion", "estado"], name="ix_centrocosto_org_estado")
        ]

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
        if self.padre_id:
            if self.pk and self.padre_id == self.pk:
                raise ValidationError({"padre": "Un centro no puede estar dentro de sí mismo."})
            if self.padre.padre_id:  # solo dos niveles: grupo › centro
                raise ValidationError({"padre": "Elija un centro de primer nivel como grupo."})
            if self.pk and self.hijos.exists():
                raise ValidationError({"padre": "Un centro con centros dentro no puede ser hijo."})


class FuenteTipoCambio(models.TextChoices):
    SUNAT = "SUNAT", "SUNAT"
    SBS = "SBS", "SBS (promedio)"
    SBS_CONTABLE = "SBS_CONTABLE", "SBS (contable)"
    MANUAL = "MANUAL", "Manual"


class TipoCambio(OrganizacionScopedModel):
    """Soles por dólar en una fecha, según la fuente. Las oficiales vienen de Decolecta."""

    fecha = models.DateField(db_index=True)
    moneda = models.CharField(max_length=3, default="USD")
    fuente = models.CharField(max_length=15, choices=FuenteTipoCambio.choices)
    compra = models.DecimalField(max_digits=10, decimal_places=4)
    venta = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        verbose_name = "tipo de cambio"
        verbose_name_plural = "tipos de cambio"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "fecha", "moneda", "fuente"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tipocambio_vigente",
            ),
            models.CheckConstraint(
                condition=Q(compra__gt=0) & Q(venta__gt=0), name="ck_tipocambio_positivo"
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "moneda", "fecha"], name="ix_tc_org_fecha")]

    def __str__(self) -> str:
        return f"{self.get_fuente_display()} {self.fecha}: {self.compra} / {self.venta}"

    @property
    def es_manual(self) -> bool:
        return self.fuente == FuenteTipoCambio.MANUAL

    def clean(self):
        super().clean()
        if self.compra is not None and self.venta is not None:
            if self.compra <= 0 or self.venta <= 0:
                raise ValidationError({"compra": "El tipo de cambio debe ser mayor que cero."})
            if self.venta < self.compra:
                raise ValidationError({"venta": "La venta no puede ser menor que la compra."})
            if self.venta > self.compra * Decimal("1.15"):
                raise ValidationError(
                    {"venta": "La venta difiere demasiado de la compra: revisa los valores."}
                )
        if self.fecha and self.fecha > date.today():
            raise ValidationError({"fecha": "La fecha no puede ser futura."})


class ConsumoApi(models.Model):
    """Consultas hechas al proveedor externo en un mes (la cuota es de la cuenta)."""

    proveedor = models.CharField(max_length=20, default="decolecta")
    mes = models.CharField(max_length=7)  # AAAA-MM
    cantidad = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "consumo de API"
        verbose_name_plural = "consumo de API"
        constraints = [
            models.UniqueConstraint(fields=["proveedor", "mes"], name="uq_consumoapi_mes")
        ]

    def __str__(self) -> str:
        return f"{self.proveedor} {self.mes}: {self.cantidad}"


# ---------------------------------------------------------------------------
# Unidades de medida, listas de precios y productos
# ---------------------------------------------------------------------------
class UnidadMedida(_Catalogo, OrganizacionScopedModel):
    """Unidad en que se cuenta y se vende un producto (UND, KG, M, CAJA…)."""

    RESTRICCIONES = {
        "uq_unidadmedida_nombre_vigente": ("nombre", "Ya existe una unidad con ese nombre."),
        "uq_unidadmedida_abrev_vigente": (
            "abreviatura",
            "Ya existe una unidad con esa abreviatura.",
        ),
    }

    abreviatura = models.CharField(max_length=10)
    # Código del catálogo de unidades de SUNAT (NIU, KGM, MTR…): lo piden los comprobantes.
    codigo_sunat = models.CharField(max_length=5, blank=True)

    class Meta:
        verbose_name = "unidad de medida"
        verbose_name_plural = "unidades de medida"
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_unidadmedida_nombre_vigente",
            ),
            models.UniqueConstraint(
                Lower("abreviatura"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_unidadmedida_abrev_vigente",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_unidad_org_estado")]

    def clean(self):
        super().clean()
        self.abreviatura = "".join((self.abreviatura or "").split()).upper()
        self.codigo_sunat = "".join((self.codigo_sunat or "").split()).upper()
        if not self.abreviatura:
            raise ValidationError({"abreviatura": "Ingrese la abreviatura."})
        if self.codigo_sunat and not re.fullmatch(r"[A-Z0-9]{2,5}", self.codigo_sunat):
            raise ValidationError({"codigo_sunat": "Use de 2 a 5 letras o números (ej. NIU)."})


class UsoLista(models.TextChoices):
    """Para qué sirve una lista: Ventas decide el precio y el piso según este uso, no el nombre."""

    PUBLICO = "PUBLICO", "Precio público"
    DESCUENTO = "DESCUENTO", "Precio con descuento"
    TECNICO = "TECNICO", "Precio técnico"
    CREDITO = "CREDITO", "Precio a crédito"
    OTRA = "OTRA", "Otra"


class ListaPrecio(_Catalogo, OrganizacionScopedModel):
    """Nivel de precio de venta (Público, Descuento, Técnico, Crédito…); el nombre se configura."""

    RESTRICCIONES = {
        "uq_listaprecio_nombre_vigente": (
            "nombre",
            "Ya existe una lista de precios con ese nombre.",
        ),
    }

    orden = models.PositiveSmallIntegerField(default=1)
    # La principal es el precio «normal» de venta; hay exactamente una activa.
    es_principal = models.BooleanField(default=False)
    uso = models.CharField(max_length=10, choices=UsoLista.choices, default=UsoLista.OTRA)

    class Meta:
        verbose_name = "lista de precios"
        verbose_name_plural = "listas de precios"
        ordering = ["orden", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_listaprecio_nombre_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion"],
                condition=Q(es_principal=True, eliminado_en__isnull=True),
                name="uq_listaprecio_principal",
            ),
        ]


class Correlativo(models.Model):
    """Numeración automática por organización (código de producto; luego series de documentos)."""

    organizacion = models.ForeignKey("organizacion.Organizacion", on_delete=models.PROTECT)
    clave = models.CharField(max_length=40)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "clave"], name="uq_correlativo")
        ]

    def __str__(self) -> str:
        return f"{self.clave}: {self.ultimo}"


class TipoProducto(models.TextChoices):
    BIEN = "BIEN", "Bien"
    SERVICIO = "SERVICIO", "Servicio"


class TipoExistencia(models.TextChoices):
    """Tabla 5 de SUNAT (tipo de existencia), la que piden los libros de inventario."""

    MERCADERIA = "01", "Mercadería"
    PRODUCTO_TERMINADO = "02", "Producto terminado"
    MATERIA_PRIMA = "03", "Materia prima y auxiliares - materiales"
    ENVASES = "04", "Envases y embalajes"
    SUMINISTROS = "05", "Suministros diversos"
    OTROS = "99", "Otros"


class Producto(OrganizacionScopedModel):
    """Producto o servicio que se compra y se vende. Catálogo único para todas las empresas."""

    RESTRICCIONES = {
        "uq_producto_codigo_vigente": ("codigo", "Ya existe un producto con ese código."),
        "uq_producto_barras_vigente": (
            "codigo_barras",
            "Ya existe un producto con ese código de barras.",
        ),
    }

    codigo = models.CharField(max_length=10)  # automático: 000001, 000002…
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(max_length=1000, blank=True)
    tipo = models.CharField(max_length=10, choices=TipoProducto.choices, default=TipoProducto.BIEN)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="productos")
    marca = models.ForeignKey(
        Marca, null=True, blank=True, on_delete=models.PROTECT, related_name="productos"
    )
    unidad = models.ForeignKey(UnidadMedida, on_delete=models.PROTECT, related_name="productos")
    codigo_fabricante = models.CharField(max_length=60, blank=True)
    codigo_barras = models.CharField(max_length=40, blank=True)
    # Código del catálogo de productos y servicios de SUNAT (8 dígitos): lo pide la factura
    # electrónica en cada línea. Vacío = se usa el de la configuración de la empresa.
    codigo_sunat = models.CharField("código SUNAT del producto", max_length=8, blank=True)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    tipo_existencia = models.CharField(
        max_length=2, choices=TipoExistencia.choices, default=TipoExistencia.MERCADERIA
    )
    controla_stock = models.BooleanField(default=True)
    lleva_serie = models.BooleanField("lleva serie o IMEI", default=False)
    precio_editable = models.BooleanField("se puede cambiar el precio al vender", default=False)
    # Excepción al IGV que proponen la zona y el régimen (p. ej. un producto siempre exonerado).
    afectacion_igv = models.ForeignKey(
        "AfectacionIGV",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="productos",
    )
    costo = models.DecimalField("costo en soles", max_digits=12, decimal_places=4, default=0)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    # --- Para la tienda virtual ---
    # Valores de las especificaciones de su categoría: {clave_del_campo: valor}. Texto, número
    # (como texto), opción de la lista o true/false. Se guardan con el producto para leerlos rápido.
    especificaciones = models.JSONField(default=dict, blank=True)
    publicado_web = models.BooleanField("se muestra en la tienda", default=False, db_index=True)
    destacado = models.BooleanField(default=False)
    es_nuevo = models.BooleanField("novedad", default=False)
    descripcion_web = models.TextField("descripción para la tienda", max_length=4000, blank=True)
    puntos_destacados = models.JSONField(default=list, blank=True)  # hasta 8 frases cortas
    slug = models.SlugField("dirección web", max_length=200, blank=True)
    garantia_meses = models.PositiveSmallIntegerField(null=True, blank=True)
    peso_kg = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    largo_cm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    ancho_cm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    alto_cm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "slug"],
                condition=~Q(slug="") & Q(eliminado_en__isnull=True),
                name="uq_producto_slug_vigente",
            ),
            models.CheckConstraint(
                condition=(Q(peso_kg__isnull=True) | Q(peso_kg__gte=0))
                & (Q(largo_cm__isnull=True) | Q(largo_cm__gte=0))
                & (Q(ancho_cm__isnull=True) | Q(ancho_cm__gte=0))
                & (Q(alto_cm__isnull=True) | Q(alto_cm__gte=0)),
                name="ck_producto_medidas",
            ),
            models.UniqueConstraint(
                Lower("codigo"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_producto_codigo_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "codigo_barras"],
                condition=~Q(codigo_barras="") & Q(eliminado_en__isnull=True),
                name="uq_producto_barras_vigente",
            ),
            models.CheckConstraint(
                condition=Q(costo__gte=0) & Q(stock_minimo__gte=0), name="ck_producto_no_negativo"
            ),
        ]
        indexes = [
            models.Index(fields=["organizacion", "estado"], name="ix_producto_org_estado"),
            models.Index(fields=["organizacion", "categoria"], name="ix_producto_org_categoria"),
            models.Index(fields=["organizacion", "nombre"], name="ix_producto_org_nombre"),
        ]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"

    @property
    def codigo_barras_efectivo(self) -> str:
        """El del fabricante si lo tiene; si no, el propio código del sistema (para etiquetas)."""
        return self.codigo_barras or self.codigo

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        self.codigo_fabricante = " ".join((self.codigo_fabricante or "").split())
        self.codigo_barras = "".join((self.codigo_barras or "").split()).upper()
        self.codigo_sunat = "".join((self.codigo_sunat or "").split())
        if self.codigo_sunat and not re.fullmatch(r"\d{8}", self.codigo_sunat):
            raise ValidationError({"codigo_sunat": "El código SUNAT tiene 8 dígitos."})
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre del producto."})
        if self.codigo_barras and not re.fullmatch(r"[0-9A-Z\-]{4,40}", self.codigo_barras):
            raise ValidationError({"codigo_barras": "Use de 4 a 40 números, letras o guiones."})
        if (
            self.codigo_barras
            and self.organizacion_id
            and PresentacionProducto.objects.sin_ambito()
            .filter(organizacion_id=self.organizacion_id, codigo_barras=self.codigo_barras)
            .exists()
        ):
            raise ValidationError(
                {"codigo_barras": "Ese código de barras ya lo tiene una presentación."}
            )
        if self.tipo == TipoProducto.SERVICIO:  # un servicio no tiene stock ni serie
            self.controla_stock = False
            self.lleva_serie = False
            self.stock_minimo = Decimal("0")
        if self.categoria_id and self.categoria.organizacion_id != self.organizacion_id:
            raise ValidationError({"categoria": "La categoría no pertenece a la organización."})
        if self.marca_id and self.marca.organizacion_id != self.organizacion_id:
            raise ValidationError({"marca": "La marca no pertenece a la organización."})
        if self.unidad_id and self.unidad.organizacion_id != self.organizacion_id:
            raise ValidationError({"unidad": "La unidad no pertenece a la organización."})


class TipoComprobante(OrganizacionScopedModel):
    """Tipo de comprobante de pago o documento (Tabla 10 de SUNAT): factura, boleta, etc."""

    RESTRICCIONES = {
        "uq_tipocomprobante_codigo_vigente": ("codigo", "Ya existe un tipo con ese código."),
    }

    codigo = models.CharField("código SUNAT", max_length=2)
    nombre = models.CharField(max_length=80)
    abreviatura = models.CharField(max_length=10)
    es_electronico = models.BooleanField("electrónico", default=False)
    aplica_compras = models.BooleanField("se usa en compras", default=True)
    aplica_ventas = models.BooleanField("se usa en ventas", default=False)
    lleva_igv = models.BooleanField("discrimina el IGV", default=True)
    # Cómo debe escribirse la serie: un ejemplo legible y, para quien lo necesite, la regla técnica
    # (expresión regular) con la que se valida; vacío = libre.
    ejemplo_serie = models.CharField("ejemplo de serie", max_length=10, blank=True)
    patron_serie = models.CharField("regla técnica de la serie", max_length=60, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "tipo de comprobante"
        verbose_name_plural = "tipos de comprobante"
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tipocomprobante_codigo_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_tipocomp_org_estado")]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"

    def clean(self):
        super().clean()
        self.codigo = (self.codigo or "").strip()
        self.nombre = " ".join((self.nombre or "").split())
        self.abreviatura = "".join((self.abreviatura or "").split()).upper()
        self.patron_serie = (self.patron_serie or "").strip()
        self.ejemplo_serie = "".join((self.ejemplo_serie or "").split()).upper()
        if not re.fullmatch(r"\d{2}", self.codigo):
            raise ValidationError({"codigo": "El código SUNAT son 2 números (por ejemplo, 01)."})
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})
        if not self.abreviatura:
            raise ValidationError({"abreviatura": "Ingrese la abreviatura."})
        if self.patron_serie:
            try:
                re.compile(self.patron_serie)
            except re.error:
                raise ValidationError(
                    {"patron_serie": "El formato de la serie no es una expresión válida."}
                ) from None


class SerieComprobante(EmpresaScopedModel):
    """Serie con la que UNA empresa emite un tipo de comprobante, y su numeración.

    Cada empresa tiene las suyas (cada RUC numera por separado) y puede tener varias del mismo
    tipo, por ejemplo una por punto de venta. El número siguiente lo entrega ``series.
    siguiente_numero`` bajo bloqueo: no se repite ni se salta aunque dos personas emitan a la vez.
    """

    RESTRICCIONES = {
        "uq_seriecomprobante_vigente": (
            "serie",
            "Esa empresa ya tiene esa serie para ese tipo de comprobante.",
        ),
    }
    MAXIMO_NUMERO = 99_999_999  # el correlativo de SUNAT tiene hasta 8 dígitos

    tipo_comprobante = models.ForeignKey(
        TipoComprobante, on_delete=models.PROTECT, related_name="series"
    )
    serie = models.CharField(max_length=4)
    # Punto de venta: opcional. Sin sucursal, la serie sirve a toda la empresa.
    nombre = models.CharField("nombre o punto de venta", max_length=80, blank=True)
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    es_electronica = models.BooleanField("electrónica", default=True)
    # Último número entregado. Se puede ajustar (p. ej. al migrar de otro sistema), con las
    # reglas de ``series``: libre mientras no se haya emitido nada; después, solo hacia arriba.
    ultimo_numero = models.PositiveIntegerField(default=0)
    # Cuántos números ha entregado ya el sistema (no se edita).
    emitidos = models.PositiveIntegerField(default=0, editable=False)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "serie de comprobante"
        verbose_name_plural = "series de comprobantes"
        ordering = ["tipo_comprobante__codigo", "serie"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_comprobante", "serie"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_seriecomprobante_vigente",
            ),
            models.CheckConstraint(
                condition=Q(ultimo_numero__lte=99_999_999), name="ck_seriecomprobante_numero"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_serie_empresa_estado")]

    def __str__(self) -> str:
        return f"{self.serie} · {self.tipo_comprobante.nombre}"

    @property
    def proximo_numero(self) -> int:
        return self.ultimo_numero + 1

    def clean(self):
        super().clean()
        self.serie = "".join((self.serie or "").split()).upper()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.serie:
            raise ValidationError({"serie": "Ingrese la serie."})
        if not re.fullmatch(r"[0-9A-Z]{1,4}", self.serie):
            raise ValidationError({"serie": "La serie son hasta 4 letras o números."})
        if self.ultimo_numero > self.MAXIMO_NUMERO:
            raise ValidationError({"ultimo_numero": "El número no puede pasar de 99 999 999."})
        tipo = self.tipo_comprobante
        if self.empresa_id and tipo.organizacion_id != self.empresa.organizacion_id:
            raise ValidationError({"tipo_comprobante": "El tipo no pertenece a la organización."})
        if self.sucursal_id and self.sucursal.empresa_id != self.empresa_id:
            raise ValidationError({"sucursal": "La sucursal no pertenece a la empresa."})
        # Una serie electrónica empieza con letra (F001, B001…) y cumple el formato del tipo.
        formato_malo = self.serie.isdigit() or (
            tipo.patron_serie and not re.fullmatch(tipo.patron_serie, self.serie)
        )
        if self.es_electronica and formato_malo:
            ejemplo = f" (por ejemplo, {tipo.ejemplo_serie})" if tipo.ejemplo_serie else ""
            raise ValidationError(
                {"serie": f"La serie no tiene el formato de {tipo.nombre}{ejemplo}."}
            )


class AfectacionIGV(OrganizacionScopedModel):
    """Tipo de afectación del IGV (Catálogo 07 de SUNAT): gravado, exonerado, inafecto…

    Los códigos y su grupo son de SUNAT y no se cambian; se ajustan el nombre, dónde se usa y si
    está activa.
    """

    class Grupo(models.TextChoices):
        GRAVADO = "GRAVADO", "Gravado"
        EXONERADO = "EXONERADO", "Exonerado"
        INAFECTO = "INAFECTO", "Inafecto"
        EXPORTACION = "EXPORTACION", "Exportación"

    class Impuesto(models.TextChoices):
        IGV = "IGV", "IGV"
        IVAP = "IVAP", "IVAP"
        NINGUNO = "NINGUNO", "Sin impuesto"

    codigo = models.CharField("código SUNAT", max_length=2)
    nombre = models.CharField(max_length=100)
    grupo = models.CharField(max_length=12, choices=Grupo.choices)
    impuesto = models.CharField(max_length=8, choices=Impuesto.choices, default=Impuesto.NINGUNO)
    gratuita = models.BooleanField("operación gratuita", default=False)
    aplica_compras = models.BooleanField("se ofrece en compras", default=False)
    aplica_ventas = models.BooleanField("se ofrece en ventas", default=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "afectación del IGV"
        verbose_name_plural = "afectaciones del IGV"
        ordering = ["codigo"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_afectacionigv_codigo_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_afectigv_org_estado")]

    def __str__(self) -> str:
        return f"{self.codigo} · {self.nombre}"

    @property
    def paga_impuesto(self) -> bool:
        """¿Calcula IGV o IVAP sobre la base? Gravado sí; exonerado, inafecto y exportación no."""
        return self.impuesto != self.Impuesto.NINGUNO

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})


class TasaImpuesto(OrganizacionScopedModel):
    """Porcentaje de un impuesto desde una fecha. La vigente a un día es la última ya iniciada."""

    class Impuesto(models.TextChoices):
        IGV = "IGV", "IGV (incluye el IPM)"
        IVAP = "IVAP", "IVAP"

    RESTRICCIONES = {
        "uq_tasaimpuesto_vigencia": (
            "vigente_desde",
            "Ya hay una tasa de ese impuesto desde esa fecha.",
        ),
    }

    impuesto = models.CharField(max_length=8, choices=Impuesto.choices)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    vigente_desde = models.DateField()

    class Meta:
        verbose_name = "tasa de impuesto"
        verbose_name_plural = "tasas de impuesto"
        ordering = ["impuesto", "-vigente_desde"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "impuesto", "vigente_desde"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_tasaimpuesto_vigencia",
            ),
            models.CheckConstraint(
                condition=Q(porcentaje__gte=0) & Q(porcentaje__lte=100),
                name="ck_tasaimpuesto_rango",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.impuesto} {self.porcentaje}% desde {self.vigente_desde}"

    def clean(self):
        super().clean()
        if self.porcentaje is None or not (Decimal("0") <= self.porcentaje <= Decimal("100")):
            raise ValidationError({"porcentaje": "El porcentaje debe estar entre 0 y 100."})


class MedioPago(OrganizacionScopedModel):
    """Cómo se paga o se cobra: efectivo, tarjeta, Yape… Cada organización agrega los suyos."""

    class Tipo(models.TextChoices):
        EFECTIVO = "EFECTIVO", "Efectivo"
        TARJETA = "TARJETA", "Tarjeta"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia o depósito"
        BILLETERA = "BILLETERA", "Billetera digital (Yape, Plin…)"
        CHEQUE = "CHEQUE", "Cheque"
        OTRO = "OTRO", "Otro"

    RESTRICCIONES = {
        "uq_mediopago_nombre_vigente": ("nombre", "Ya existe un método de pago con ese nombre."),
    }

    nombre = models.CharField(max_length=60)
    tipo = models.CharField(max_length=15, choices=Tipo.choices, default=Tipo.OTRO)
    # Si al usarlo se pide el número de operación o de voucher (tarjeta, transferencia, Yape…).
    requiere_referencia = models.BooleanField("pide número de operación", default=False)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "método de pago"
        verbose_name_plural = "métodos de pago"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_mediopago_nombre_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_mediopago_org_estado")]

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})


class ConceptoCaja(OrganizacionScopedModel):
    """Para qué entra o sale dinero de una caja o cuenta: pago a proveedor, comisión, aporte…

    Los de fábrica (``codigo``) los usa el sistema por su cuenta (pago de una compra, cobro de una
    venta, transferencias, arqueos): los marcados ``automatico`` no se eliminan, no se desactivan
    y no se ofrecen al registrar un movimiento a mano.
    """

    class Tipo(models.TextChoices):
        INGRESO = "INGRESO", "Ingreso"
        EGRESO = "EGRESO", "Egreso"

    RESTRICCIONES = {
        "uq_conceptocaja_nombre_vigente": (
            "nombre",
            "Ya existe un concepto de ese tipo con ese nombre.",
        ),
    }

    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=7, choices=Tipo.choices)
    codigo = models.CharField(max_length=30, blank=True)
    automatico = models.BooleanField(default=False)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "concepto de caja"
        verbose_name_plural = "conceptos de caja"
        ordering = ["tipo", "nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "tipo",
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_conceptocaja_nombre_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=~Q(codigo="") & Q(eliminado_en__isnull=True),
                name="uq_conceptocaja_codigo_vigente",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_conceptocaja_org_est")]

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})


class CategoriaGasto(OrganizacionScopedModel):
    """En qué se gasta: servicios, alquiler, movilidad… Agrupa los gastos para los reportes.

    Las de fábrica (``codigo``) las carga el sistema; cada organización puede agregar las suyas y
    desactivar las que no use.
    """

    RESTRICCIONES = {
        "uq_categoriagasto_nombre_vigente": (
            "nombre",
            "Ya existe una categoría de gasto con ese nombre.",
        ),
    }

    nombre = models.CharField(max_length=80)
    codigo = models.CharField(max_length=30, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "categoría de gasto"
        verbose_name_plural = "categorías de gasto"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_categoriagasto_nombre_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=~Q(codigo="") & Q(eliminado_en__isnull=True),
                name="uq_categoriagasto_codigo_vigente",
            ),
        ]
        indexes = [
            models.Index(fields=["organizacion", "estado"], name="ix_categoriagasto_org_est")
        ]

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})


class Periodicidad(OrganizacionScopedModel):
    """Cada cuánto vence una cuota (semanal, quincenal, mensual…). Arma el cronograma de pagos."""

    class Unidad(models.TextChoices):
        DIAS = "DIAS", "Días"
        MESES = "MESES", "Meses"

    RESTRICCIONES = {
        "uq_periodicidad_nombre_vigente": ("nombre", "Ya existe una periodicidad con ese nombre."),
    }
    MAXIMO_DIAS = 365
    MAXIMO_MESES = 12

    nombre = models.CharField(max_length=60)
    unidad = models.CharField(max_length=6, choices=Unidad.choices, default=Unidad.DIAS)
    cantidad = models.PositiveSmallIntegerField(
        help_text="Cada cuántos días o meses vence una cuota."
    )
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "periodicidad"
        verbose_name_plural = "periodicidades"
        ordering = ["unidad", "cantidad", "nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "organizacion",
                condition=Q(eliminado_en__isnull=True),
                name="uq_periodicidad_nombre_vigente",
            ),
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_periodicidad_cantidad"),
        ]
        indexes = [
            models.Index(fields=["organizacion", "estado"], name="ix_periodicidad_org_estado")
        ]

    def __str__(self) -> str:
        return self.nombre

    @property
    def descripcion(self) -> str:
        unidad = "día" if self.unidad == self.Unidad.DIAS else "mes"
        plural = "" if self.cantidad == 1 else ("s" if unidad == "día" else "es")
        return f"Cada {self.cantidad} {unidad}{plural}"

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})
        tope = self.MAXIMO_DIAS if self.unidad == self.Unidad.DIAS else self.MAXIMO_MESES
        if not self.cantidad or not (1 <= self.cantidad <= tope):
            unidad = "días" if self.unidad == self.Unidad.DIAS else "meses"
            raise ValidationError({"cantidad": f"Debe ser de 1 a {tope} {unidad}."})


class CuentaFinanciera(EmpresaScopedModel):
    """Una caja de efectivo, cuenta de banco o billetera digital de una empresa.

    Es DE DÓNDE sale o A DÓNDE entra el dinero de cada pago y cobro. Cada empresa tiene las suyas
    (cada RUC maneja su propio dinero) y puede asignarlas a una sucursal: una caja por tienda.
    El tipo y la moneda no cambian después de crearla; si hubo un error se crea otra.
    """

    class Tipo(models.TextChoices):
        CAJA = "CAJA", "Caja de efectivo"
        BANCO = "BANCO", "Cuenta de banco"
        BILLETERA = "BILLETERA", "Billetera digital"

    class Moneda(models.TextChoices):
        PEN = "PEN", "Soles"
        USD = "USD", "Dólares"

    class RolCaja(models.TextChoices):
        PRINCIPAL = "PRINCIPAL", "Caja principal"
        MOSTRADOR = "MOSTRADOR", "Mostrador"
        CAJA_CHICA = "CAJA_CHICA", "Caja chica (fondo fijo)"

    RESTRICCIONES = {
        "uq_cuentafinanciera_nombre_vigente": (
            "nombre",
            "La empresa ya tiene una caja o cuenta con ese nombre.",
        ),
    }

    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.PEN)
    # Una caja por tienda: con sucursal es de esa tienda; sin ella sirve a toda la empresa.
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Datos del banco: son sensibles, los ve quien puede editar (los demás, solo los últimos 4).
    banco = models.CharField(max_length=60, blank=True)
    numero_cuenta = models.CharField("número de cuenta o celular", max_length=30, blank=True)
    cci = models.CharField("código de cuenta interbancario", max_length=20, blank=True)
    saldo_inicial = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    fecha_saldo_inicial = models.DateField(null=True, blank=True)
    # Solo cajas de efectivo. La principal (caja fuerte) es una por tienda; las demás son
    # mostradores. Con sesión obligatoria, no se mueve efectivo si la caja no está abierta.
    rol_caja = models.CharField(max_length=10, choices=RolCaja.choices, blank=True)
    fondo_inicial = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    exige_sesion = models.BooleanField(default=False)
    # Las cajas de efectivo nunca quedan en negativo; un banco o billetera solo con sobregiro.
    permite_saldo_negativo = models.BooleanField(default=False)
    # Por debajo de este saldo el sistema avisa que hay que reponer (opcional).
    saldo_minimo = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    # Para el Libro Caja y Bancos electrónico (PLE): cuenta del plan contable (101, 1041…) y
    # código SUNAT de la entidad financiera (solo bancos).
    cuenta_contable = models.CharField(max_length=20, blank=True)
    codigo_entidad = models.CharField(max_length=2, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "caja o cuenta"
        verbose_name_plural = "cajas y cuentas"
        ordering = ["tipo", "nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                "empresa",
                condition=Q(eliminado_en__isnull=True),
                name="uq_cuentafinanciera_nombre_vigente",
            ),
            models.CheckConstraint(
                condition=Q(saldo_inicial__gte=0), name="ck_cuentafinanciera_saldo_inicial"
            ),
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_cuenta_empresa_estado")]

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        self.banco = " ".join((self.banco or "").split())
        self.numero_cuenta = "".join((self.numero_cuenta or "").split())
        self.cci = "".join((self.cci or "").split())
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre."})
        if self.sucursal_id and self.sucursal.empresa_id != self.empresa_id:
            raise ValidationError({"sucursal": "La sucursal no pertenece a la empresa."})
        if self.tipo == self.Tipo.CAJA and (self.banco or self.numero_cuenta or self.cci):
            raise ValidationError({"banco": "Una caja de efectivo no lleva datos de banco."})
        if self.tipo == self.Tipo.BANCO and not self.banco:
            raise ValidationError({"banco": "Indique el banco."})
        if self.tipo == self.Tipo.BILLETERA and self.cci:
            raise ValidationError({"cci": "Una billetera digital no tiene código interbancario."})
        if self.numero_cuenta and not re.fullmatch(r"[0-9\-]{4,30}", self.numero_cuenta):
            raise ValidationError({"numero_cuenta": "Use de 4 a 30 números (y guiones)."})
        if self.cci and not re.fullmatch(r"\d{20}", self.cci):
            raise ValidationError({"cci": "El código interbancario son 20 números."})
        self.cuenta_contable = "".join((self.cuenta_contable or "").split())
        self.codigo_entidad = "".join((self.codigo_entidad or "").split())
        if self.cuenta_contable and not re.fullmatch(r"\d{2,20}", self.cuenta_contable):
            raise ValidationError({"cuenta_contable": "Use de 2 a 20 números, por ejemplo 1041."})
        if self.codigo_entidad and not re.fullmatch(r"\d{2}", self.codigo_entidad):
            raise ValidationError({"codigo_entidad": "Son 2 números (código SUNAT del banco)."})
        if self.codigo_entidad and self.tipo == self.Tipo.CAJA:
            raise ValidationError({"codigo_entidad": "Una caja de efectivo no tiene entidad."})
        if self.saldo_minimo is not None and self.saldo_minimo < 0:
            raise ValidationError({"saldo_minimo": "El saldo mínimo no puede ser negativo."})
        if self.tipo == self.Tipo.CAJA and self.permite_saldo_negativo:
            raise ValidationError(
                {"permite_saldo_negativo": "Una caja de efectivo no puede quedar en negativo."}
            )
        if self.tipo != self.Tipo.CAJA:
            if self.rol_caja or self.exige_sesion or self.fondo_inicial:
                raise ValidationError(
                    {"rol_caja": "Solo las cajas de efectivo llevan rol, fondo y sesión."}
                )
        else:
            if self.rol_caja and self.rol_caja not in self.RolCaja.values:
                raise ValidationError({"rol_caja": "Elija el rol de la caja."})
            if self.fondo_inicial is None or self.fondo_inicial < 0:
                raise ValidationError({"fondo_inicial": "El fondo inicial no puede ser negativo."})
            if self.rol_caja == self.RolCaja.PRINCIPAL and self.estado == EstadoRegistro.ACTIVO:
                otra = (
                    CuentaFinanciera.objects.filter(
                        empresa_id=self.empresa_id,
                        sucursal_id=self.sucursal_id,
                        rol_caja=self.RolCaja.PRINCIPAL,
                        estado=EstadoRegistro.ACTIVO,
                    )
                    .exclude(pk=self.pk)
                    .first()
                )
                if otra is not None:
                    raise ValidationError(
                        {"rol_caja": f"«{otra.nombre}» ya es la caja principal de esa tienda."}
                    )
        if self.saldo_inicial is None or self.saldo_inicial < 0:
            raise ValidationError({"saldo_inicial": "El saldo inicial no puede ser negativo."})
        if self.saldo_inicial > 0 and self.fecha_saldo_inicial is None:
            raise ValidationError({"fecha_saldo_inicial": "Indique desde qué fecha es ese saldo."})
        if self.fecha_saldo_inicial and self.fecha_saldo_inicial > date.today():
            raise ValidationError({"fecha_saldo_inicial": "La fecha no puede ser futura."})


class PrecioProducto(OrganizacionScopedModel):
    """Precio de venta de un producto en una lista, con su utilidad sobre el costo."""

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="precios")
    lista = models.ForeignKey(ListaPrecio, on_delete=models.PROTECT, related_name="precios")
    precio = models.DecimalField(max_digits=12, decimal_places=4)
    # Porcentaje sobre el costo; queda vacío si el costo es cero.
    utilidad = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "precio de producto"
        verbose_name_plural = "precios de productos"
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "lista"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_precioproducto_vigente",
            ),
            models.CheckConstraint(
                condition=Q(precio__gte=0), name="ck_precioproducto_no_negativo"
            ),
        ]


class PresentacionProducto(OrganizacionScopedModel):
    """Otra unidad en que se compra o vende un producto (caja, docena…), con su equivalencia.

    El producto tiene una unidad BASE (``Producto.unidad``): el stock y el Kardex siempre van en
    ella. Una presentación dice cuántas unidades base contiene: 1 caja = 12 unidades. Tiene sus
    propios precios y, si quiere, su propio código de barras.
    """

    RESTRICCIONES = {
        "uq_presentacion_unidad_vigente": ("unidad", "El producto ya tiene esa unidad."),
        "uq_presentacion_barras_vigente": (
            "codigo_barras",
            "Ya existe una presentación con ese código de barras.",
        ),
    }
    FACTOR_MAXIMO = Decimal("1000000")

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="presentaciones")
    unidad = models.ForeignKey(
        UnidadMedida, on_delete=models.PROTECT, related_name="presentaciones"
    )
    # Cuántas unidades base trae: la caja de 12 tiene factor 12.
    factor = models.DecimalField(max_digits=12, decimal_places=3)
    codigo_barras = models.CharField(max_length=40, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "presentación de producto"
        verbose_name_plural = "presentaciones de productos"
        ordering = ["producto_id", "factor"]
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "unidad"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_presentacion_unidad_vigente",
            ),
            models.UniqueConstraint(
                fields=["organizacion", "codigo_barras"],
                condition=~Q(codigo_barras="") & Q(eliminado_en__isnull=True),
                name="uq_presentacion_barras_vigente",
            ),
            models.CheckConstraint(condition=Q(factor__gt=0), name="ck_presentacion_factor"),
        ]
        indexes = [models.Index(fields=["producto", "estado"], name="ix_presentacion_prod_estado")]

    def __str__(self) -> str:
        return f"{self.unidad.nombre} (x{self.factor.normalize():f}) de {self.producto_id}"

    @property
    def equivalencia(self) -> str:
        """``1 Caja = 12 Unidad``."""
        return f"1 {self.unidad.nombre} = {self.factor.normalize():f} {self.producto.unidad.nombre}"

    def clean(self):
        super().clean()
        self.codigo_barras = "".join((self.codigo_barras or "").split()).upper()
        if self.codigo_barras and not re.fullmatch(r"[0-9A-Z\-]{4,40}", self.codigo_barras):
            raise ValidationError({"codigo_barras": "Use de 4 a 40 números, letras o guiones."})
        if self.factor is None or self.factor <= 0 or self.factor > self.FACTOR_MAXIMO:
            raise ValidationError({"factor": "Indique cuántas unidades base trae (mayor que 0)."})
        if self.factor == 1:
            raise ValidationError({"factor": "Si trae 1 unidad base, no es otra presentación."})
        producto, unidad = self.producto, self.unidad
        if producto.organizacion_id != self.organizacion_id or (
            unidad.organizacion_id != self.organizacion_id
        ):
            raise ValidationError({"unidad": "La unidad no pertenece a la organización."})
        if unidad.pk == producto.unidad_id:
            raise ValidationError({"unidad": "Esa ya es la unidad base del producto."})
        if producto.tipo != TipoProducto.BIEN:
            raise ValidationError({"producto": "Un servicio no tiene presentaciones."})
        if producto.lleva_serie:
            raise ValidationError(
                {"producto": "Un producto con serie o IMEI solo se maneja en su unidad base."}
            )
        if self.codigo_barras and (
            Producto.objects.sin_ambito()
            .filter(organizacion_id=self.organizacion_id, codigo_barras=self.codigo_barras)
            .exists()
        ):
            raise ValidationError(
                {"codigo_barras": "Ese código de barras ya lo tiene un producto."}
            )


class PrecioPresentacion(OrganizacionScopedModel):
    """Precio de venta de una presentación en una lista, con su utilidad sobre su costo."""

    presentacion = models.ForeignKey(
        PresentacionProducto, on_delete=models.PROTECT, related_name="precios"
    )
    lista = models.ForeignKey(
        ListaPrecio, on_delete=models.PROTECT, related_name="precios_presentacion"
    )
    precio = models.DecimalField(max_digits=12, decimal_places=4)
    # Porcentaje sobre el costo de la presentación (costo base × factor); vacío si no hay costo.
    utilidad = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "precio de presentación"
        verbose_name_plural = "precios de presentaciones"
        constraints = [
            models.UniqueConstraint(
                fields=["presentacion", "lista"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_preciopresentacion_vigente",
            ),
            models.CheckConstraint(condition=Q(precio__gte=0), name="ck_preciopresentacion_precio"),
        ]


def _ruta_foto(instancia, nombre: str) -> str:
    return f"productos/{instancia.organizacion_id}/{instancia.producto_id}/{nombre}"


class FotoProducto(OrganizacionScopedModel):
    """Foto de un producto. Se guarda ya procesada (WebP sin metadatos) con su miniatura."""

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="fotos")
    imagen = models.FileField(upload_to=_ruta_foto, max_length=255)
    miniatura = models.FileField(upload_to=_ruta_foto, max_length=255)
    es_principal = models.BooleanField(default=False)
    orden = models.PositiveSmallIntegerField(default=0)
    nombre_original = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "foto de producto"
        verbose_name_plural = "fotos de productos"
        ordering = ["-es_principal", "orden", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["producto"],
                condition=Q(es_principal=True, eliminado_en__isnull=True),
                name="uq_fotoproducto_principal",
            )
        ]


class Ubigeo(models.Model):
    """Código de ubicación del INEI de 6 dígitos: departamento, provincia y distrito.

    Es una lista de referencia que comparte todo el sistema (no es de ninguna organización) y se
    carga con la migración desde ``datos/ubigeos_inei.csv``. La guía de remisión electrónica de
    SUNAT pide el ubigeo del punto de partida y del de llegada.
    """

    codigo = models.CharField(max_length=6, unique=True)
    departamento = models.CharField(max_length=60)
    provincia = models.CharField(max_length=60)
    distrito = models.CharField(max_length=60)
    # Código y nombres sin tildes ni mayúsculas: sobre esto se busca (ver ``ubigeos``).
    busqueda = models.CharField(max_length=220, editable=False, default="")

    class Meta:
        verbose_name = "ubigeo"
        verbose_name_plural = "ubigeos"
        ordering = ["codigo"]

    def __str__(self) -> str:
        return self.nombre_completo

    @property
    def nombre_completo(self) -> str:
        return f"{self.departamento} - {self.provincia} - {self.distrito}".upper()


class EmpresaTransporte(OrganizacionScopedModel):
    """Una empresa que lleva la mercadería (transporte público): su RUC y sus registros del MTC.

    Se registra una vez y se elige en la guía de remisión. La propia empresa que vende no va aquí:
    en el transporte privado la guía usa a la empresa emisora.
    """

    RESTRICCIONES = {
        "uq_empresatransporte_ruc_vigente": (
            "ruc",
            "Ya existe una empresa de transporte con ese RUC.",
        ),
    }

    nombre = models.CharField("razón social", max_length=250)
    ruc = models.CharField(max_length=11)
    registro_mtc = models.CharField("N° de registro MTC", max_length=30, blank=True)
    certificado_inspeccion = models.CharField(max_length=30, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "empresa de transporte"
        verbose_name_plural = "empresas de transporte"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "ruc"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_empresatransporte_ruc_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_emptransp_org_estado")]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.ruc})"

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        self.ruc = normalizar_documento(self.ruc)
        self.registro_mtc = " ".join((self.registro_mtc or "").split()).upper()
        self.certificado_inspeccion = " ".join((self.certificado_inspeccion or "").split()).upper()
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre de la empresa de transporte."})
        if not ruc_es_valido(self.ruc):
            raise ValidationError({"ruc": "El RUC no es válido."})


class Conductor(_ConDocumento, OrganizacionScopedModel):
    """Quien maneja el vehículo que lleva la mercadería: su documento y su licencia."""

    RESTRICCIONES = {
        "uq_conductor_documento_vigente": (
            "numero_documento",
            "Ya existe un conductor con ese documento.",
        ),
    }

    nombre = models.CharField("nombres y apellidos", max_length=150)
    licencia = models.CharField("licencia de conducir", max_length=20, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "conductor"
        verbose_name_plural = "conductores"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "tipo_documento", "numero_documento"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_conductor_documento_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_conductor_org_estado")]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.numero_documento})"

    def clean(self):
        super().clean()
        self.nombre = " ".join((self.nombre or "").split())
        self.licencia = " ".join((self.licencia or "").split()).upper()
        if not self.nombre:
            raise ValidationError({"nombre": "Ingrese el nombre del conductor."})


class Vehiculo(OrganizacionScopedModel):
    """Un vehículo que lleva la mercadería: su placa, marca y modelo."""

    RESTRICCIONES = {
        "uq_vehiculo_placa_vigente": ("placa", "Ya existe un vehículo con esa placa."),
    }

    placa = models.CharField(max_length=10)
    marca = models.CharField(max_length=60, blank=True)
    modelo = models.CharField(max_length=60, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "vehículo"
        verbose_name_plural = "vehículos"
        ordering = ["placa"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "placa"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_vehiculo_placa_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_vehiculo_org_estado")]

    def __str__(self) -> str:
        detalle = " ".join(x for x in (self.marca, self.modelo) if x)
        return f"{self.placa} · {detalle}" if detalle else self.placa

    def clean(self):
        super().clean()
        self.placa = normalizar_documento(self.placa)  # sin espacios ni guiones y en mayúsculas
        self.marca = " ".join((self.marca or "").split())
        self.modelo = " ".join((self.modelo or "").split())
        if not re.fullmatch(r"[A-Z0-9]{5,8}", self.placa):
            raise ValidationError({"placa": "La placa debe tener de 5 a 8 letras o números."})


class CampoEspecificacion(OrganizacionScopedModel):
    """Un dato técnico que se pide a los productos de una categoría (RAM, DPI, socket…).

    Cada categoría tiene su plantilla de campos. Los valores de cada producto viven en
    ``Producto.especificaciones`` bajo la ``clave`` del campo; por eso la clave nunca cambia
    aunque se renombre el campo. Un campo que se quita no se borra: queda INACTIVO.
    """

    class Tipo(models.TextChoices):
        TEXTO = "TEXTO", "Texto"
        NUMERO = "NUMERO", "Número"
        LISTA = "LISTA", "Lista de opciones"
        SI_NO = "SI_NO", "Sí o no"

    categoria = models.ForeignKey(
        Categoria, on_delete=models.PROTECT, related_name="campos_especificacion"
    )
    clave = models.SlugField(max_length=60, help_text="Identificador estable del campo.")
    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.TEXTO)
    unidad = models.CharField(max_length=20, blank=True, help_text="GB, MHz, pulgadas…")
    opciones = models.JSONField(default=list, blank=True)  # solo para listas
    seccion = models.CharField(max_length=60, default="General")
    orden = models.PositiveSmallIntegerField(default=0)
    es_filtro = models.BooleanField("sirve como filtro en la tienda", default=False)
    en_tarjeta = models.BooleanField("se ve en la tarjeta del listado", default=False)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "campo de especificación"
        verbose_name_plural = "campos de especificación"
        ordering = ["categoria_id", "orden", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["categoria", "clave"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_campoespec_clave_vigente",
            ),
        ]
        indexes = [models.Index(fields=["categoria", "estado"], name="ix_campoespec_cat_estado")]

    def __str__(self) -> str:
        return f"{self.categoria_id} · {self.nombre}"
