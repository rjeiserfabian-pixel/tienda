"""Servicio técnico: el taller que recibe equipos, los diagnostica, los repara y los entrega.

Una orden de servicio sigue a un equipo del cliente desde que entra hasta que sale. Pasa por
estados (ver ``flujo``) y cada cambio queda en un historial que no se edita. Los catálogos (tipos
de equipo, accesorios, lista de revisión, tipos de servicio) son de la organización; la orden y lo
que cuelga de ella son de una empresa.

A quién se asigna el trabajo es siempre un ``Personal`` (para comisiones y reportes), tenga o no
usuario del sistema. Si lo tiene, entra a ver y trabajar sus órdenes.
"""

import secrets
from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.crypto import CampoCifrado
from apps.core.exceptions import DocumentoInmutableError
from apps.core.models import EmpresaScopedModel, OrganizacionScopedModel
from apps.mantenimiento.models import EstadoRegistro


class EstadoOrden(models.TextChoices):
    RECIBIDO = "RECIBIDO", "Equipo recibido"
    PENDIENTE_DIAGNOSTICO = "PENDIENTE_DIAGNOSTICO", "Pendiente de diagnóstico"
    EN_DIAGNOSTICO = "EN_DIAGNOSTICO", "En diagnóstico"
    DIAGNOSTICADO = "DIAGNOSTICADO", "Diagnóstico realizado"
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION", "Pendiente de aprobación"
    APROBADO = "APROBADO", "Aprobado / Programado"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO", "En mantenimiento"
    EN_REPARACION = "EN_REPARACION", "En reparación"
    PENDIENTE_REPUESTO = "PENDIENTE_REPUESTO", "Pendiente de repuesto"
    EN_PRUEBAS = "EN_PRUEBAS", "En pruebas"
    TERMINADO = "TERMINADO", "Servicio terminado"
    LISTO_ENTREGA = "LISTO_ENTREGA", "Listo para entrega"
    ENTREGADO = "ENTREGADO", "Entregado / Cerrado"
    # Salidas que no son el camino feliz: sin ellas habría órdenes imposibles de cerrar.
    NO_APROBADO = "NO_APROBADO", "No aprobado / Cancelado"
    SIN_SOLUCION = "SIN_SOLUCION", "Sin solución"
    ABANDONADO = "ABANDONADO", "Abandonado"


class CategoriaServicio(models.TextChoices):
    """Decide por qué estados pasa la orden: un mantenimiento no pasa por «En reparación»."""

    DIAGNOSTICO = "DIAGNOSTICO", "Diagnóstico"
    MANTENIMIENTO = "MANTENIMIENTO", "Mantenimiento"
    REPARACION = "REPARACION", "Reparación"
    OTRO = "OTRO", "Otro"


class Prioridad(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    URGENTE = "URGENTE", "Urgente"


class ResultadoRevision(models.TextChoices):
    OK = "OK", "Bien"
    FALLA = "FALLA", "Con falla"
    NO_PROBADO = "NO_PROBADO", "No se pudo probar"
    NO_APLICA = "NO_APLICA", "No aplica"


def _nombre_unico(nombre: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(
        Lower("nombre"),
        "organizacion",
        condition=Q(eliminado_en__isnull=True),
        name=nombre,
    )


def _codigo_unico(nombre: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(
        fields=["organizacion", "codigo"],
        condition=~Q(codigo="") & Q(eliminado_en__isnull=True),
        name=nombre,
    )


# ---------------------------------------------------------------------------
# Catálogos de la organización
# ---------------------------------------------------------------------------
class TipoEquipo(OrganizacionScopedModel):
    """Laptop, PC de escritorio, impresora… Las de fábrica llevan ``codigo``."""

    RESTRICCIONES = {
        "uq_tipoequipo_nombre_vigente": ("nombre", "Ya existe un tipo de equipo con ese nombre."),
    }

    nombre = models.CharField(max_length=80)
    codigo = models.CharField(max_length=30, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "tipo de equipo"
        verbose_name_plural = "tipos de equipo"
        ordering = ["nombre"]
        constraints = [
            _nombre_unico("uq_tipoequipo_nombre_vigente"),
            _codigo_unico("uq_tipoequipo_codigo_vigente"),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_tipoequipo_org_est")]

    def __str__(self) -> str:
        return self.nombre


class AccesorioEquipo(OrganizacionScopedModel):
    """Lo que el cliente deja junto al equipo: cargador, mouse, maletín…"""

    RESTRICCIONES = {
        "uq_accesorioequipo_nombre_vigente": ("nombre", "Ya existe un accesorio con ese nombre."),
    }

    nombre = models.CharField(max_length=80)
    codigo = models.CharField(max_length=30, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "accesorio de equipo"
        verbose_name_plural = "accesorios de equipo"
        ordering = ["nombre"]
        constraints = [
            _nombre_unico("uq_accesorioequipo_nombre_vigente"),
            _codigo_unico("uq_accesorioequipo_codigo_vigente"),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_accesorioeq_org_est")]

    def __str__(self) -> str:
        return self.nombre


class ItemChecklist(OrganizacionScopedModel):
    """Una revisión que se hace al recibir el equipo: ¿enciende?, ¿pantalla rota?, ¿puertos?…

    Sin ``tipo_equipo`` se revisa en todos los equipos; con él, solo en ese tipo.
    """

    RESTRICCIONES = {
        "uq_itemchecklist_nombre_vigente": ("nombre", "Ya existe una revisión con ese nombre."),
    }

    nombre = models.CharField(max_length=120)
    codigo = models.CharField(max_length=30, blank=True)
    tipo_equipo = models.ForeignKey(
        TipoEquipo,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revisiones",
    )
    orden = models.PositiveSmallIntegerField(default=0)
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "revisión de ingreso"
        verbose_name_plural = "revisiones de ingreso"
        ordering = ["orden", "nombre"]
        constraints = [
            _nombre_unico("uq_itemchecklist_nombre_vigente"),
            _codigo_unico("uq_itemchecklist_codigo_vigente"),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_itemcheck_org_est")]

    def __str__(self) -> str:
        return self.nombre


class TipoServicio(OrganizacionScopedModel):
    """Qué se le hace al equipo. Trae su categoría, su garantía y un precio de referencia."""

    RESTRICCIONES = {
        "uq_tiposervicio_nombre_vigente": (
            "nombre",
            "Ya existe un tipo de servicio con ese nombre.",
        ),
    }

    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=30, blank=True)
    categoria = models.CharField(
        max_length=15, choices=CategoriaServicio.choices, default=CategoriaServicio.REPARACION
    )
    garantia_dias = models.PositiveSmallIntegerField(
        default=0, help_text="Días de garantía del trabajo. Cero = sin garantía."
    )
    precio_referencial = models.DecimalField(
        "mano de obra referencial (S/)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    estado = models.CharField(
        max_length=10, choices=EstadoRegistro.choices, default=EstadoRegistro.ACTIVO
    )

    class Meta:
        verbose_name = "tipo de servicio"
        verbose_name_plural = "tipos de servicio"
        ordering = ["nombre"]
        constraints = [
            _nombre_unico("uq_tiposervicio_nombre_vigente"),
            _codigo_unico("uq_tiposervicio_codigo_vigente"),
            models.CheckConstraint(
                condition=Q(precio_referencial__gte=0), name="ck_tiposervicio_precio"
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "estado"], name="ix_tiposervicio_org_est")]

    def __str__(self) -> str:
        return self.nombre


# ---------------------------------------------------------------------------
# El equipo y la orden
# ---------------------------------------------------------------------------
class Equipo(OrganizacionScopedModel):
    """Un equipo de un cliente. Guarda su historia: cuántas veces entró y qué se le hizo."""

    cliente = models.ForeignKey(
        "mantenimiento.Cliente", on_delete=models.PROTECT, related_name="equipos"
    )
    tipo = models.ForeignKey(TipoEquipo, on_delete=models.PROTECT, related_name="equipos")
    marca = models.CharField(max_length=60, blank=True)
    modelo = models.CharField(max_length=80, blank=True)
    numero_serie = models.CharField("número de serie", max_length=80, blank=True)
    color = models.CharField(max_length=40, blank=True)
    descripcion = models.CharField(
        max_length=250, blank=True, help_text="Características: procesador, memoria, disco…"
    )

    class Meta:
        verbose_name = "equipo"
        verbose_name_plural = "equipos"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["organizacion", "numero_serie"], name="ix_equipo_org_serie"),
            models.Index(fields=["organizacion", "cliente"], name="ix_equipo_org_cliente"),
        ]

    def __str__(self) -> str:
        partes = [self.tipo.nombre if self.tipo_id else "", self.marca, self.modelo]
        texto = " ".join(p for p in partes if p)
        return f"{texto} (serie {self.numero_serie})" if self.numero_serie else texto


def _token_publico() -> str:
    """Código no adivinable para consultar el estado desde el QR, sin iniciar sesión."""
    return secrets.token_urlsafe(12)


class OrdenServicio(EmpresaScopedModel):
    numero = models.PositiveIntegerField(help_text="Correlativo interno por empresa.")
    sucursal = models.ForeignKey(
        "organizacion.Sucursal", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cliente = models.ForeignKey(
        "mantenimiento.Cliente", on_delete=models.PROTECT, related_name="ordenes_servicio"
    )
    equipo = models.ForeignKey(Equipo, on_delete=models.PROTECT, related_name="ordenes")
    tipo_servicio = models.ForeignKey(
        TipoServicio,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ordenes",
        help_text="Se define al diagnosticar si al recibir el equipo aún no se sabe.",
    )
    tecnico = models.ForeignKey(
        "mantenimiento.Personal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ordenes_servicio",
    )

    estado = models.CharField(
        max_length=25, choices=EstadoOrden.choices, default=EstadoOrden.RECIBIDO, db_index=True
    )
    # Solo mientras espera un repuesto: el estado al que vuelve cuando llega.
    estado_previo = models.CharField(max_length=25, choices=EstadoOrden.choices, blank=True)
    prioridad = models.CharField(max_length=10, choices=Prioridad.choices, default=Prioridad.NORMAL)

    falla_reportada = models.TextField("falla que reporta el cliente")
    estado_fisico = models.TextField(
        "estado físico al recibir", blank=True, help_text="Rayones, golpes, piezas faltantes…"
    )
    clave_equipo = CampoCifrado("clave o patrón del equipo", blank=True, default="")

    fecha_ingreso = models.DateTimeField(default=timezone.now, db_index=True)
    fecha_promesa = models.DateField("fecha prometida", null=True, blank=True)
    fecha_entrega = models.DateTimeField(null=True, blank=True)

    # Lo que el técnico concluye al revisar el equipo.
    diagnostico = models.TextField("diagnóstico", blank=True)
    trabajos_a_realizar = models.TextField("trabajos a realizar", blank=True)
    horas_estimadas = models.DecimalField(
        "horas estimadas", max_digits=5, decimal_places=1, null=True, blank=True
    )
    nota_interna = models.TextField("nota interna", blank=True, help_text="Solo la ve el taller.")
    nota_cliente = models.TextField(
        "nota para el cliente", blank=True, help_text="Lo que se le puede contar al cliente."
    )

    # Quién se llevó el equipo (se pide al entregar).
    recogio_nombre = models.CharField("quién recogió", max_length=120, blank=True)
    recogio_documento = models.CharField(max_length=20, blank=True)
    recogio_es_titular = models.BooleanField(null=True, blank=True)

    # La garantía del trabajo: sale del tipo de servicio y corre desde la entrega.
    garantia_dias = models.PositiveSmallIntegerField(default=0)
    garantia_hasta = models.DateField(null=True, blank=True, db_index=True)
    # El cliente aceptó recibir avisos de su orden por WhatsApp (se pide al recibir el equipo).
    acepta_whatsapp = models.BooleanField(default=False)

    # La comisión del técnico, congelada al entregar y cobrar (si luego cambia su porcentaje, esta
    # orden conserva el de ese día). Base: la mano de obra cobrada, sin IGV.
    comision_base = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    comision_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    comision_monto = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    # Un reingreso por garantía es una orden nueva ligada a la que se entregó antes; no se cobra.
    reingreso_de = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reingresos"
    )
    es_garantia = models.BooleanField(default=False)

    token_publico = models.CharField(max_length=20, unique=True, default=_token_publico)

    class Meta:
        verbose_name = "orden de servicio"
        verbose_name_plural = "órdenes de servicio"
        ordering = ["-fecha_ingreso", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_ordenservicio_numero"),
            models.CheckConstraint(
                condition=Q(estado_previo="") | Q(estado="PENDIENTE_REPUESTO"),
                name="ck_ordenservicio_previo",
            ),
            models.CheckConstraint(
                condition=Q(horas_estimadas__isnull=True) | Q(horas_estimadas__gte=0),
                name="ck_ordenservicio_horas",
            ),
            models.CheckConstraint(
                condition=Q(es_garantia=False) | Q(reingreso_de__isnull=False),
                name="ck_ordenservicio_garantia_ligada",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"], name="ix_orden_empresa_estado"),
            models.Index(fields=["empresa", "tecnico", "estado"], name="ix_orden_tecnico_estado"),
            models.Index(fields=["empresa", "fecha_ingreso"], name="ix_orden_empresa_ingreso"),
            models.Index(fields=["equipo", "-fecha_ingreso"], name="ix_orden_equipo"),
        ]

    def __str__(self) -> str:
        return self.codigo

    @property
    def codigo(self) -> str:
        return f"OS-{self.numero:06d}"

    @property
    def cerrada(self) -> bool:
        return self.estado == EstadoOrden.ENTREGADO


class OrdenAccesorio(EmpresaScopedModel):
    """Un accesorio que el cliente dejó con el equipo. El nombre queda como se anotó ese día."""

    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="accesorios")
    accesorio = models.ForeignKey(
        AccesorioEquipo, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    nombre = models.CharField(max_length=80)
    cantidad = models.PositiveSmallIntegerField(default=1)
    detalle = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "accesorio recibido"
        verbose_name_plural = "accesorios recibidos"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gte=1), name="ck_ordenaccesorio_cant")
        ]
        indexes = [models.Index(fields=["orden"], name="ix_ordenaccesorio_orden")]

    def __str__(self) -> str:
        return f"{self.cantidad} × {self.nombre}"


class OrdenRevision(EmpresaScopedModel):
    """Resultado de una revisión al recibir el equipo (la lista de ``ItemChecklist``)."""

    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="revisiones")
    item = models.ForeignKey(
        ItemChecklist, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    nombre = models.CharField(max_length=120)
    resultado = models.CharField(
        max_length=12, choices=ResultadoRevision.choices, default=ResultadoRevision.NO_PROBADO
    )
    observacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "revisión de la orden"
        verbose_name_plural = "revisiones de la orden"
        ordering = ["id"]
        indexes = [models.Index(fields=["orden"], name="ix_ordenrevision_orden")]

    def __str__(self) -> str:
        return f"{self.nombre}: {self.get_resultado_display()}"


class HistorialEstado(EmpresaScopedModel):
    """Cada cambio de estado de una orden: quién (``creado_por_id``), cuándo y por qué.

    No se edita ni se borra: es el rastro de lo que le pasó al equipo.
    """

    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="historial")
    estado_anterior = models.CharField(max_length=25, choices=EstadoOrden.choices, blank=True)
    estado_nuevo = models.CharField(max_length=25, choices=EstadoOrden.choices)
    motivo = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "cambio de estado"
        verbose_name_plural = "historial de estados"
        ordering = ["id"]
        indexes = [models.Index(fields=["orden", "id"], name="ix_historialestado_orden")]

    def __str__(self) -> str:
        return f"{self.orden_id}: {self.estado_anterior or '—'} → {self.estado_nuevo}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise DocumentoInmutableError("El historial de estados no se modifica.")
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise DocumentoInmutableError("El historial de estados no se borra.")


class MedioAviso(models.TextChoices):
    WHATSAPP = "WHATSAPP", "WhatsApp"
    LLAMADA = "LLAMADA", "Llamada"
    CORREO = "CORREO", "Correo"
    PRESENCIAL = "PRESENCIAL", "En persona"
    OTRO = "OTRO", "Otro medio"


class AvisoCliente(EmpresaScopedModel):
    """Constancia de que se le avisó al cliente (quién, cuándo, por qué medio y qué se le dijo).

    Por ahora se anota a mano; más adelante el aviso por WhatsApp se enviará solo.
    """

    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="avisos")
    medio = models.CharField(max_length=12, choices=MedioAviso.choices)
    mensaje = models.CharField(max_length=500)

    class Meta:
        verbose_name = "aviso al cliente"
        verbose_name_plural = "avisos al cliente"
        ordering = ["-id"]
        indexes = [models.Index(fields=["orden", "-id"], name="ix_aviso_orden")]

    def __str__(self) -> str:
        return f"{self.orden_id}: {self.get_medio_display()}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise DocumentoInmutableError("Un aviso registrado no se modifica.")
        super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise DocumentoInmutableError("Un aviso registrado no se borra.")


class PresupuestoOrden(EmpresaScopedModel):
    """El presupuesto de una orden: una proforma de Ventas con sus precios, IGV y vigencia.

    Cada vez que se rearma, la proforma anterior se anula y nace una versión nueva; solo una está
    vigente. Al aprobarse queda registrado quién lo aprobó, cómo y cuándo, y deja de poder editarse.
    """

    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="presupuestos")
    proforma = models.OneToOneField(
        "ventas.Proforma", on_delete=models.PROTECT, related_name="presupuesto_servicio"
    )
    version = models.PositiveSmallIntegerField(default=1)
    vigente = models.BooleanField(default=True)

    aprobado_en = models.DateTimeField(null=True, blank=True)
    aprobado_por_id = models.UUIDField(null=True, blank=True, editable=False)
    aprobacion_medio = models.CharField(max_length=12, choices=MedioAviso.choices, blank=True)
    aprobacion_nota = models.CharField(max_length=500, blank=True)

    # La venta con que se cobró al entregar el equipo (un comprobante por cada empresa que surtió).
    venta = models.OneToOneField(
        "ventas.Venta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="presupuesto_servicio",
    )
    # Si se entregó sin cobrar (garantía, cortesía): por qué (quién, en la huella del registro).
    entregado_sin_cobro = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "presupuesto de servicio"
        verbose_name_plural = "presupuestos de servicio"
        ordering = ["orden_id", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["orden", "version"], name="uq_presupuesto_version"),
            models.UniqueConstraint(
                fields=["orden"], condition=Q(vigente=True), name="uq_presupuesto_vigente"
            ),
        ]

    def __str__(self) -> str:
        return f"Presupuesto v{self.version} de {self.orden_id}"

    @property
    def aprobado(self) -> bool:
        return self.aprobado_en is not None


class EstadoRepuesto(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Sin reservar"
    RESERVADO = "RESERVADO", "Reservado"
    CONSUMIDO = "CONSUMIDO", "Usado"
    LIBERADO = "LIBERADO", "Liberado"


class RepuestoOrden(EmpresaScopedModel):
    """Un repuesto del presupuesto y lo que pasó con su stock.

    Al aprobar se reserva: pasa del almacén de venta al almacén «Servicio técnico» de la empresa
    que lo surte (así nadie lo vende). Al empezar el trabajo sale de ahí como consumo; si el
    servicio no sigue, vuelve al almacén de origen. La empresa es la que surte el repuesto.
    """

    presupuesto = models.ForeignKey(
        PresupuestoOrden, on_delete=models.PROTECT, related_name="repuestos"
    )
    linea = models.OneToOneField(
        "ventas.LineaProforma", on_delete=models.PROTECT, related_name="repuesto_servicio"
    )
    producto = models.ForeignKey(
        "mantenimiento.Producto", on_delete=models.PROTECT, related_name="+"
    )
    cantidad = models.DecimalField(max_digits=14, decimal_places=3)
    estado = models.CharField(
        max_length=10, choices=EstadoRepuesto.choices, default=EstadoRepuesto.PENDIENTE
    )
    # De dónde salió al reservar (para devolverlo si el servicio no sigue).
    almacen_origen = models.ForeignKey(
        "mantenimiento.Almacen", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    traspaso_reserva = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="La salida del traspaso con que se reservó.",
    )
    movimiento_consumo = models.ForeignKey(
        "inventario.MovimientoInventario",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    # Lo que costó al salir del stock (promedio de ese momento): para la utilidad del servicio.
    costo_total = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "repuesto de la orden"
        verbose_name_plural = "repuestos de la orden"
        ordering = ["presupuesto_id", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_repuesto_cantidad")
        ]
        indexes = [models.Index(fields=["presupuesto", "estado"], name="ix_repuesto_estado")]

    def __str__(self) -> str:
        return f"{self.cantidad} × {self.producto_id} ({self.get_estado_display()})"


class ComisionTecnico(EmpresaScopedModel):
    """Qué porcentaje de la mano de obra cobrada gana un técnico. Sin fila, no gana comisión."""

    personal = models.OneToOneField(
        "mantenimiento.Personal", on_delete=models.PROTECT, related_name="comision_servicio"
    )
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = "comisión del técnico"
        verbose_name_plural = "comisiones de técnicos"
        constraints = [
            models.CheckConstraint(
                condition=Q(porcentaje__gte=0) & Q(porcentaje__lte=100), name="ck_comision_rango"
            )
        ]

    def __str__(self) -> str:
        return f"{self.personal_id}: {self.porcentaje}%"


class ConfiguracionAvisos(EmpresaScopedModel):
    """Qué avisos automáticos por WhatsApp manda el taller de una empresa (apagados de inicio)."""

    whatsapp_activo = models.BooleanField(default=False)
    aviso_recibido = models.BooleanField("al recibir el equipo", default=True)
    aviso_presupuesto = models.BooleanField("cuando hay presupuesto por aprobar", default=True)
    aviso_listo = models.BooleanField("cuando el equipo está listo", default=True)
    aviso_entregado = models.BooleanField("al entregarlo (garantía)", default=False)

    class Meta:
        verbose_name = "configuración de avisos"
        verbose_name_plural = "configuraciones de avisos"
        constraints = [
            models.UniqueConstraint(
                fields=["empresa"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_configavisos_empresa",
            )
        ]

    def __str__(self) -> str:
        return f"Avisos de la empresa {self.empresa_id}"


class EventoAviso(models.TextChoices):
    RECIBIDO = "RECIBIDO", "Equipo recibido"
    PRESUPUESTO = "PRESUPUESTO", "Presupuesto por aprobar"
    LISTO = "LISTO", "Equipo listo para recoger"
    ENTREGADO = "ENTREGADO", "Equipo entregado"


class EstadoNotificacion(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    ENVIADO = "ENVIADO", "Enviado"
    FALLIDO = "FALLIDO", "No se pudo enviar"
    OMITIDO = "OMITIDO", "No se envió"


class NotificacionServicio(EmpresaScopedModel):
    """Un aviso automático al cliente (uno por orden y evento). Es la bandeja de salida: se encola,
    una tarea lo envía y aquí queda cómo salió. No se edita a mano."""

    orden = models.ForeignKey(
        OrdenServicio, on_delete=models.PROTECT, related_name="notificaciones"
    )
    evento = models.CharField(max_length=12, choices=EventoAviso.choices)
    canal = models.CharField(max_length=10, default="WHATSAPP")
    telefono = models.CharField(max_length=20, blank=True)
    mensaje = models.CharField(max_length=500)
    estado = models.CharField(
        max_length=10, choices=EstadoNotificacion.choices, default=EstadoNotificacion.PENDIENTE
    )
    intentos = models.PositiveSmallIntegerField(default=0)
    detalle = models.CharField(max_length=255, blank=True)
    externo_id = models.CharField(max_length=80, blank=True)
    enviado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "aviso automático"
        verbose_name_plural = "avisos automáticos"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["orden", "evento"], name="uq_notificacion_evento")
        ]
        indexes = [models.Index(fields=["estado", "creado_en"], name="ix_notificacion_estado")]

    def __str__(self) -> str:
        return f"{self.orden_id}: {self.get_evento_display()} ({self.get_estado_display()})"


class EstadoAdelanto(models.TextChoices):
    VIGENTE = "VIGENTE", "Vigente"
    DEVUELTO = "DEVUELTO", "Devuelto al cliente"
    ANULADO = "ANULADO", "Anulado"


class AdelantoServicio(EmpresaScopedModel):
    """Dinero que el cliente deja por adelantado: se le da un recibo interno (no es comprobante).

    El dinero entra a la caja el día que se recibe. Al facturar el servicio se descuenta de lo que
    el cliente paga (el comprobante sale por el total); si el servicio no se hace, se le devuelve
    con un egreso de caja y no hace falta nota de crédito porque nunca se facturó. Mientras no se
    aplique ni se devuelva, queda «por devolver»: nunca se pierde en silencio.
    """

    orden = models.ForeignKey(OrdenServicio, on_delete=models.PROTECT, related_name="adelantos")
    numero = models.PositiveIntegerField(help_text="Correlativo del recibo, por empresa.")
    monto = models.DecimalField(max_digits=16, decimal_places=2)
    medio_pago = models.ForeignKey(
        "mantenimiento.MedioPago", on_delete=models.PROTECT, related_name="+"
    )
    cuenta = models.ForeignKey(
        "mantenimiento.CuentaFinanciera", on_delete=models.PROTECT, related_name="+"
    )
    referencia = models.CharField(max_length=60, blank=True)
    fecha = models.DateField(db_index=True)
    estado = models.CharField(
        max_length=10, choices=EstadoAdelanto.choices, default=EstadoAdelanto.VIGENTE
    )
    movimiento_caja = models.ForeignKey(
        "caja.MovimientoCaja", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    # Si se descontó de un comprobante (si este se anula, el adelanto vuelve a estar disponible).
    comprobante = models.ForeignKey(
        "ventas.ComprobanteVenta",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="adelantos_servicio",
    )
    aplicado_en = models.DateTimeField(null=True, blank=True)

    devuelto_en = models.DateTimeField(null=True, blank=True)
    devolucion_motivo = models.CharField(max_length=250, blank=True)
    anulado_en = models.DateTimeField(null=True, blank=True)
    anulacion_motivo = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "adelanto de servicio"
        verbose_name_plural = "adelantos de servicio"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_adelanto_numero"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_adelanto_monto"),
        ]
        indexes = [models.Index(fields=["orden", "estado"], name="ix_adelanto_orden")]

    def __str__(self) -> str:
        return self.codigo

    @property
    def codigo(self) -> str:
        return f"RA-{self.numero:04d}"
