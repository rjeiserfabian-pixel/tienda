"""Roles, permisos y excepciones individuales (RBAC multiempresa).

* ``Permiso`` y ``Modulo`` son GLOBALES y se cargan desde ``permisos_catalogo.py``.
* ``Rol``, ``RolPermiso``, ``UsuarioRol`` y ``UsuarioPermiso`` son de la ORGANIZACIÓN.
* Una asignación puede ser de una empresa concreta o de todas las del usuario (empresa vacía).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import ViolacionAmbito
from apps.core.models import OrganizacionScopedModel
from apps.organizacion.models import Empresa
from apps.seguridad.exceptions import MotivoRequerido, RolDeSistemaIntocable


class Alcance(models.TextChoices):
    """Hasta dónde llega un permiso, de menor a mayor amplitud."""

    PROPIO = "PROPIO", "Solo lo que el usuario creó"
    ASIGNADO = "ASIGNADO", "Solo lo asignado al usuario"
    SUCURSAL = "SUCURSAL", "Sus sucursales"
    EMPRESA = "EMPRESA", "Toda la empresa"
    ORGANIZACION = "ORGANIZACION", "Toda la organización"


class TipoExcepcion(models.TextChoices):
    ALLOW = "ALLOW", "Permitir"
    DENY = "DENY", "Denegar"


class Permiso(models.Model):
    """Acción atómica del sistema. El catálogo vive en código; esta tabla lo refleja."""

    codigo = models.CharField(max_length=100, unique=True)
    modulo = models.CharField(max_length=50, db_index=True)
    accion = models.CharField(max_length=50)
    descripcion = models.CharField(max_length=250, blank=True)
    es_critico = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)  # se desactiva si sale del catálogo

    class Meta:
        verbose_name = "permiso"
        verbose_name_plural = "permisos"
        ordering = ["codigo"]

    def __str__(self) -> str:
        return self.codigo


class Modulo(models.Model):
    """Nodo del menú. ``permiso_ver`` decide si aparece para el usuario."""

    codigo = models.CharField(max_length=60, unique=True)
    nombre = models.CharField(max_length=100)
    ruta = models.CharField(max_length=150, blank=True)
    icono = models.CharField(max_length=40, blank=True)
    padre = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="hijos"
    )
    orden = models.PositiveSmallIntegerField(default=0)
    permiso_ver = models.ForeignKey(
        Permiso, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "módulo"
        verbose_name_plural = "módulos"
        ordering = ["orden", "id"]

    def __str__(self) -> str:
        return self.codigo


def _misma_organizacion(*pares: tuple[str, int | None]) -> None:
    """Todos los ids de organización informados deben coincidir."""
    ids = {org_id for _, org_id in pares if org_id is not None}
    if len(ids) > 1:
        detalle = ", ".join(nombre for nombre, _ in pares)
        raise ViolacionAmbito(
            f"Los registros deben pertenecer a la misma organización ({detalle})."
        )


class Rol(OrganizacionScopedModel):
    """Conjunto de permisos con nombre. Los de sistema no se tocan desde la aplicación."""

    codigo = models.CharField(max_length=40)
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=250, blank=True)
    es_sistema = models.BooleanField(default=False, editable=False)
    es_critico = models.BooleanField(default=False)

    class Meta:
        verbose_name = "rol"
        verbose_name_plural = "roles"
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "codigo"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_rol_organizacion_codigo_vigente",
            )
        ]

    def __str__(self) -> str:
        return self.codigo

    def save(self, *args, **kwargs):
        if not self._state.adding and self.es_sistema and not getattr(self, "_sembrando", False):
            raise RolDeSistemaIntocable()
        super().save(*args, **kwargs)


class RolPermiso(OrganizacionScopedModel):
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="permisos")
    permiso = models.ForeignKey(Permiso, on_delete=models.PROTECT, related_name="+")
    alcance = models.CharField(max_length=15, choices=Alcance.choices, default=Alcance.EMPRESA)

    class Meta:
        verbose_name = "permiso de rol"
        verbose_name_plural = "permisos de roles"
        constraints = [
            models.UniqueConstraint(
                fields=["rol", "permiso"],
                condition=Q(eliminado_en__isnull=True),
                name="uq_rolpermiso_vigente",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "rol"], name="ix_rolpermiso_org_rol")]

    def __str__(self) -> str:
        return f"{self.rol_id}:{self.permiso_id}:{self.alcance}"

    def validar_ambito(self) -> None:
        if getattr(self, "_sembrando", False) and self.organizacion_id is not None:
            return  # alta masiva confiable desde el servicio de sembrado (ya validada)
        if self.organizacion_id is None and self.rol_id is not None:
            self.organizacion_id = (
                Rol.objects.sin_ambito(incluir_eliminados=True)
                .filter(pk=self.rol_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
        super().validar_ambito()
        rol = (
            Rol.objects.sin_ambito(incluir_eliminados=True)
            .filter(pk=self.rol_id)
            .values("organizacion_id", "es_sistema")
            .first()
        )
        if rol is None or rol["organizacion_id"] != self.organizacion_id:
            raise ViolacionAmbito("El rol no pertenece a la organización.")
        if rol["es_sistema"] and not getattr(self, "_sembrando", False):
            raise RolDeSistemaIntocable()


class UsuarioRol(OrganizacionScopedModel):
    """Asigna un rol a un usuario: en una empresa o (empresa vacía) en todas las suyas."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="roles_asignados"
    )
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, related_name="asignaciones")
    empresa = models.ForeignKey(
        Empresa, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    vigente_hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "rol de usuario"
        verbose_name_plural = "roles de usuarios"
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "rol"],
                condition=Q(empresa__isnull=True, eliminado_en__isnull=True),
                name="uq_usuariorol_global_vigente",
            ),
            models.UniqueConstraint(
                fields=["usuario", "rol", "empresa"],
                condition=Q(empresa__isnull=False, eliminado_en__isnull=True),
                name="uq_usuariorol_empresa_vigente",
            ),
        ]
        indexes = [models.Index(fields=["usuario", "empresa"], name="ix_usuariorol_usuario_emp")]

    def __str__(self) -> str:
        return f"{self.usuario_id} → {self.rol_id} ({self.empresa_id or 'todas'})"

    def esta_vigente(self, ahora=None) -> bool:
        ahora = ahora or timezone.now()
        return self.eliminado_en is None and (
            self.vigente_hasta is None or self.vigente_hasta > ahora
        )

    def validar_ambito(self) -> None:
        from .usuario import Usuario

        if self.organizacion_id is None and self.rol_id is not None:
            self.organizacion_id = (
                Rol.objects.sin_ambito(incluir_eliminados=True)
                .filter(pk=self.rol_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
        super().validar_ambito()
        usuario_org = (
            Usuario.objects.filter(pk=self.usuario_id)
            .values_list("organizacion_id", flat=True)
            .first()
        )
        rol_org = (
            Rol.objects.sin_ambito(incluir_eliminados=True)
            .filter(pk=self.rol_id)
            .values_list("organizacion_id", flat=True)
            .first()
        )
        empresa_org = None
        if self.empresa_id is not None:
            empresa_org = (
                Empresa.objects.sin_ambito()
                .filter(pk=self.empresa_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
            if empresa_org is None:
                raise ViolacionAmbito("La empresa no existe.")
        _misma_organizacion(
            ("usuario", usuario_org),
            ("rol", rol_org),
            ("empresa", empresa_org),
            ("registro", self.organizacion_id),
        )
        if usuario_org is None or rol_org is None:
            raise ViolacionAmbito("El usuario y el rol deben pertenecer a una organización.")


class UsuarioPermiso(OrganizacionScopedModel):
    """Excepción individual a los roles: permitir o denegar un permiso (con motivo)."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="excepciones"
    )
    permiso = models.ForeignKey(Permiso, on_delete=models.PROTECT, related_name="+")
    empresa = models.ForeignKey(
        Empresa, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tipo = models.CharField(max_length=5, choices=TipoExcepcion.choices)
    alcance = models.CharField(max_length=15, choices=Alcance.choices, default=Alcance.EMPRESA)
    vigente_hasta = models.DateTimeField(null=True, blank=True)
    motivo = models.TextField()

    class Meta:
        verbose_name = "excepción de permiso"
        verbose_name_plural = "excepciones de permisos"
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "permiso"],
                condition=Q(empresa__isnull=True, eliminado_en__isnull=True),
                name="uq_usuariopermiso_global_vigente",
            ),
            models.UniqueConstraint(
                fields=["usuario", "permiso", "empresa"],
                condition=Q(empresa__isnull=False, eliminado_en__isnull=True),
                name="uq_usuariopermiso_empresa_vigente",
            ),
            models.CheckConstraint(condition=~Q(motivo=""), name="ck_usuariopermiso_motivo"),
        ]
        indexes = [models.Index(fields=["usuario", "empresa"], name="ix_usuarioperm_usuario_emp")]

    def __str__(self) -> str:
        return f"{self.tipo} {self.permiso_id} → {self.usuario_id}"

    def esta_vigente(self, ahora=None) -> bool:
        ahora = ahora or timezone.now()
        return self.eliminado_en is None and (
            self.vigente_hasta is None or self.vigente_hasta > ahora
        )

    def validar_ambito(self) -> None:
        from .usuario import Usuario

        if not (self.motivo or "").strip():
            raise MotivoRequerido()
        if self.organizacion_id is None:
            self.organizacion_id = (
                Usuario.objects.filter(pk=self.usuario_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
        super().validar_ambito()
        usuario_org = (
            Usuario.objects.filter(pk=self.usuario_id)
            .values_list("organizacion_id", flat=True)
            .first()
        )
        empresa_org = None
        if self.empresa_id is not None:
            empresa_org = (
                Empresa.objects.sin_ambito()
                .filter(pk=self.empresa_id)
                .values_list("organizacion_id", flat=True)
                .first()
            )
            if empresa_org is None:
                raise ViolacionAmbito("La empresa no existe.")
        _misma_organizacion(
            ("usuario", usuario_org), ("empresa", empresa_org), ("registro", self.organizacion_id)
        )
