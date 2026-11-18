"""Garantía de un producto vendido: una por unidad si lleva serie o IMEI, o una por línea si no.

Se crea sola al vender (ver ``servicios.crear_de_comprobante``) y corre desde la fecha de la venta.
Los meses y el cliente se COPIAN al crearla: si luego cambian en el producto o en la ficha del
cliente, lo prometido en la venta no cambia.
"""

import secrets
from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import EmpresaScopedModel, OrganizacionScopedModel


def token_publico() -> str:
    """Código no adivinable para consultar la garantía desde el QR, sin iniciar sesión."""
    return secrets.token_urlsafe(12)


class EstadoGarantia(models.TextChoices):
    ACTIVA = "ACTIVA", "Activa"
    ANULADA = "ANULADA", "Anulada"  # la venta se anuló o la unidad se devolvió
    REEMPLAZADA = "REEMPLAZADA", "Reemplazada"  # se cambió por otra unidad (la nueva sigue activa)


class Garantia(EmpresaScopedModel):
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="garantias"
    )
    linea_venta = models.ForeignKey(
        "ventas.LineaVenta", on_delete=models.PROTECT, related_name="garantias"
    )
    comprobante = models.ForeignKey(
        "ventas.ComprobanteVenta", on_delete=models.PROTECT, related_name="garantias"
    )
    cliente = models.ForeignKey(
        "mantenimiento.Cliente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="garantias",
    )
    # Cómo se llamaba el cliente al vender (el comprobante no cambia si luego edita sus datos).
    cliente_nombre = models.CharField(max_length=250, blank=True)
    cliente_documento = models.CharField(max_length=20, blank=True, db_index=True)

    # Serie o IMEI de la unidad; vacío si el producto no lleva serie (entonces vale por la línea).
    numero_serie = models.CharField(max_length=40, blank=True, db_index=True)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("1"))

    fecha_inicio = models.DateField()
    meses = models.PositiveSmallIntegerField()
    vence_el = models.DateField(db_index=True)
    # Si esta garantía nació de un cambio por garantía, la que reemplaza (conserva el remanente).
    reemplaza_a = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reemplazos"
    )

    estado = models.CharField(
        max_length=12, choices=EstadoGarantia.choices, default=EstadoGarantia.ACTIVA
    )
    token_publico = models.CharField(max_length=20, unique=True, default=token_publico)
    anulada_en = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "garantía"
        verbose_name_plural = "garantías"
        ordering = ["-fecha_inicio", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["linea_venta", "numero_serie"],
                condition=~Q(numero_serie="") & Q(reemplaza_a__isnull=True),
                name="uq_garantia_linea_serie",
            ),
            models.UniqueConstraint(
                fields=["linea_venta"],
                condition=Q(numero_serie="") & Q(reemplaza_a__isnull=True),
                name="uq_garantia_linea_sin_serie",
            ),
            models.CheckConstraint(condition=Q(meses__gt=0), name="ck_garantia_meses"),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_garantia_cantidad"),
            models.CheckConstraint(
                condition=Q(vence_el__gte=models.F("fecha_inicio")), name="ck_garantia_fechas"
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "producto", "numero_serie"], name="ix_garantia_serie"),
            models.Index(fields=["empresa", "estado", "vence_el"], name="ix_garantia_vence"),
        ]

    def __str__(self) -> str:
        return f"Garantía {self.numero_serie or self.producto_id} hasta {self.vence_el}"

    def vigente(self, hoy=None) -> bool:
        hoy = hoy or timezone.localdate()
        return self.estado == EstadoGarantia.ACTIVA and hoy <= self.vence_el

    def dias_restantes(self, hoy=None) -> int:
        hoy = hoy or timezone.localdate()
        if self.estado != EstadoGarantia.ACTIVA:
            return 0
        return max((self.vence_el - hoy).days, 0)


class EstadoReclamo(models.TextChoices):
    ABIERTO = "ABIERTO", "Abierto"
    EN_SERVICIO = "EN_SERVICIO", "En servicio técnico"
    EN_PROVEEDOR = "EN_PROVEEDOR", "Con el proveedor"
    RESUELTO = "RESUELTO", "Resuelto"
    RECHAZADO = "RECHAZADO", "Rechazado"


ABIERTOS = (EstadoReclamo.ABIERTO, EstadoReclamo.EN_SERVICIO, EstadoReclamo.EN_PROVEEDOR)


class Resolucion(models.TextChoices):
    REPARADO = "REPARADO", "Reparado"
    CAMBIADO = "CAMBIADO", "Cambiado por otra unidad"
    NOTA_CREDITO = "NOTA_CREDITO", "Devolución con nota de crédito"
    RECHAZADO = "RECHAZADO", "Rechazado"


class ReclamoGarantia(EmpresaScopedModel):
    """Un cliente reclama la garantía de un producto: cómo se atendió y cómo terminó."""

    garantia = models.ForeignKey(Garantia, on_delete=models.PROTECT, related_name="reclamos")
    numero = models.PositiveIntegerField()
    fecha = models.DateField()
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("1"))
    descripcion = models.TextField(max_length=1000)
    estado = models.CharField(
        max_length=12, choices=EstadoReclamo.choices, default=EstadoReclamo.ABIERTO
    )

    # Si el equipo pasó por Servicio Técnico (orden de la misma empresa).
    orden_servicio = models.ForeignKey(
        "servicio_tecnico.OrdenServicio",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reclamos_garantia",
    )
    # Si se envió al proveedor para que lo repare o lo reponga (RMA).
    proveedor = models.ForeignKey(
        "mantenimiento.Proveedor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reclamos_garantia",
    )
    rma_numero = models.CharField(max_length=40, blank=True)
    enviado_proveedor_el = models.DateField(null=True, blank=True)
    respuesta_proveedor = models.CharField(max_length=500, blank=True)
    respondido_proveedor_el = models.DateField(null=True, blank=True)

    resolucion = models.CharField(max_length=12, choices=Resolucion.choices, blank=True)
    resolucion_detalle = models.CharField(max_length=500, blank=True)
    resuelto_el = models.DateField(null=True, blank=True)
    resuelto_por_id = models.UUIDField(null=True, blank=True)
    # Si se cambió por otra unidad: la garantía nueva y lo que salió del almacén.
    garantia_nueva = models.ForeignKey(
        Garantia, null=True, blank=True, on_delete=models.PROTECT, related_name="nacida_de"
    )
    movimiento = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        verbose_name = "reclamo de garantía"
        verbose_name_plural = "reclamos de garantía"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"], name="uq_reclamo_garantia_numero"
            ),
            # Una garantía no tiene dos reclamos abiertos a la vez.
            models.UniqueConstraint(
                fields=["garantia"],
                condition=Q(estado__in=["ABIERTO", "EN_SERVICIO", "EN_PROVEEDOR"]),
                name="uq_reclamo_garantia_abierto",
            ),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_reclamo_cantidad"),
        ]
        indexes = [models.Index(fields=["empresa", "estado"], name="ix_reclamo_gar_estado")]

    def __str__(self) -> str:
        return f"Reclamo {self.numero_completo}"

    @property
    def numero_completo(self) -> str:
        return f"RG-{self.numero:06d}"

    @property
    def abierto(self) -> bool:
        return self.estado in ABIERTOS


class ConfiguracionGarantias(OrganizacionScopedModel):
    """Cómo se avisa a los clientes que su garantía está por vencer (una fila por organización).

    Los avisos nacen APAGADOS: el negocio decide si los quiere y con cuántos días de anticipación.
    """

    avisos_activos = models.BooleanField(default=False)
    dias_antes = models.PositiveSmallIntegerField(default=30)

    class Meta:
        verbose_name = "configuración de garantías"
        verbose_name_plural = "configuraciones de garantías"
        constraints = [
            models.UniqueConstraint(fields=["organizacion"], name="uq_config_garantias_org"),
            models.CheckConstraint(
                condition=Q(dias_antes__gte=1) & Q(dias_antes__lte=90), name="ck_garantias_dias"
            ),
        ]


class EstadoAviso(models.TextChoices):
    ENVIADO = "ENVIADO", "Enviado"
    FALLIDO = "FALLIDO", "Falló"
    OMITIDO = "OMITIDO", "No se envió"


class AvisoGarantia(EmpresaScopedModel):
    """El aviso de «tu garantía está por vencer» de una garantía: uno solo por garantía."""

    garantia = models.OneToOneField(Garantia, on_delete=models.PROTECT, related_name="aviso")
    estado = models.CharField(max_length=10, choices=EstadoAviso.choices)
    correo = models.CharField(max_length=254, blank=True)
    detalle = models.CharField(max_length=250, blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "aviso de garantía"
        verbose_name_plural = "avisos de garantía"


class BajaAvisoGarantia(OrganizacionScopedModel):
    """Un correo que pidió no recibir más avisos de garantía (enlace de baja del correo)."""

    correo = models.CharField(max_length=254)

    class Meta:
        verbose_name = "baja de avisos de garantía"
        verbose_name_plural = "bajas de avisos de garantía"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "correo"], name="uq_baja_aviso_garantia"
            )
        ]
