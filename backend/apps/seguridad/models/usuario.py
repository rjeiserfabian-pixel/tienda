import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone


class UsuarioManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Un superusuario de Django es administrador de plataforma (sin organización).
        extra_fields.setdefault("es_admin_plataforma", True)
        return super().create_superuser(username, email, password, **extra_fields)


class Usuario(AbstractUser):
    """Persona que opera el sistema. Pertenece a UNA organización y accede a N empresas.

    El acceso a cada empresa (y su cargo) vive en ``AccesoEmpresa``. Un administrador de
    plataforma no tiene organización. Los usuarios no se borran: se desactivan.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("correo electrónico", unique=True)
    organizacion = models.ForeignKey(
        "organizacion.Organizacion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="usuarios",
    )
    es_admin_plataforma = models.BooleanField(default=False)
    telefono = models.CharField(max_length=20, blank=True)
    documento_numero = models.CharField(max_length=15, blank=True)
    debe_cambiar_password = models.BooleanField(default=False)
    # Copia de ``MfaConfig`` confirmada: permite decidir en el login y en el gate sin otra consulta.
    mfa_activo = models.BooleanField(default=False)
    password_cambiada_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(default=timezone.now, editable=False)
    actualizado_en = models.DateTimeField(auto_now=True)

    objects = UsuarioManager()

    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [
            models.CheckConstraint(
                condition=Q(es_admin_plataforma=True) | Q(organizacion__isnull=False),
                name="ck_usuario_organizacion_o_plataforma",
            )
        ]
        indexes = [models.Index(fields=["organizacion", "is_active"], name="ix_usuario_org_activo")]

    def __str__(self) -> str:
        return self.username

    def clean(self):
        super().clean()
        self.email = (self.email or "").strip().lower()  # antes de validar la unicidad

    def save(self, *args, **kwargs):
        # Correo siempre en minúsculas: la unicidad y el login no distinguen mayúsculas.
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)
