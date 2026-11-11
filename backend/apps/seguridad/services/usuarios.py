"""Alta y desactivación de usuarios."""

from collections.abc import Iterable

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.core.exceptions import ViolacionAmbito
from apps.organizacion.models import Empresa, Organizacion
from apps.seguridad.models import AccesoEmpresa, Sesion, Usuario
from apps.seguridad.services import passwords, roles


def exigir_username_libre(username: str, *, excepto_pk=None) -> None:
    """El nombre de usuario no lleva «@» y no puede repetirse ni con otras mayúsculas.

    El ingreso busca el usuario sin distinguir mayúsculas: «Ana» y «ana» serían ambiguos.
    """
    if "@" in username:
        raise ValidationError({"username": "El nombre de usuario no puede contener '@'."})
    if " " in username or not username:
        raise ValidationError({"username": "Use un nombre de usuario sin espacios."})
    repetido = Usuario.objects.filter(username__iexact=username)
    if excepto_pk is not None:
        repetido = repetido.exclude(pk=excepto_pk)
    if repetido.exists():
        raise ValidationError({"username": "Ya existe un usuario con ese nombre."})


@transaction.atomic
def crear_usuario(
    *,
    organizacion: Organizacion,
    username: str,
    email: str,
    password: str,
    nombres: str = "",
    apellidos: str = "",
    empresa_ids: Iterable[int] = (),
    cargo: str = "",
    debe_cambiar_password: bool = False,
    telefono: str = "",
    documento_numero: str = "",
    activo: bool = True,
) -> Usuario:
    """Crea un usuario de la organización con acceso a las empresas indicadas."""
    username = username.strip()
    exigir_username_libre(username)

    empresa_ids = set(empresa_ids)
    validas = set(
        Empresa.objects.sin_ambito()
        .filter(pk__in=empresa_ids, organizacion=organizacion)
        .values_list("pk", flat=True)
    )
    if validas != empresa_ids:
        raise ViolacionAmbito("Alguna empresa no existe o no pertenece a la organización.")

    usuario = Usuario(
        username=username.strip(),
        email=email,
        first_name=nombres,
        last_name=apellidos,
        telefono=telefono.strip(),
        documento_numero=documento_numero.strip(),
        is_active=activo,
        organizacion=organizacion,
    )
    usuario.full_clean(exclude=["password"])
    validate_password(password, usuario)
    usuario.save()
    passwords.establecer_password(usuario, password, debe_cambiar=debe_cambiar_password)

    for empresa_id in sorted(empresa_ids):
        AccesoEmpresa(
            usuario=usuario, empresa_id=empresa_id, organizacion=organizacion, cargo=cargo
        ).save()
    return usuario


@transaction.atomic
def crear_admin_plataforma(*, username: str, email: str, password: str) -> Usuario:
    """Administrador de plataforma: sin organización; gestiona el sistema completo."""
    usuario = Usuario(
        username=username.strip(),
        email=email,
        is_staff=True,
        is_superuser=True,
        es_admin_plataforma=True,
    )
    usuario.full_clean(exclude=["password"])
    validate_password(password, usuario)
    usuario.save()
    passwords.establecer_password(usuario, password)
    return usuario


@transaction.atomic
def desactivar_usuario(usuario: Usuario) -> int:
    """Desactiva (nunca borra) y cierra todas sus sesiones. Devuelve sesiones cerradas."""
    if usuario.organizacion_id is not None and roles.usuario_tiene_rol_critico(usuario):
        roles.exigir_otro_administrador(usuario.organizacion_id, excluyendo_usuario=usuario)
    abiertas = Sesion.objects.filter(usuario=usuario, revocada=False).count()
    usuario.is_active = False
    # El receptor post_save de ``signals`` revoca las sesiones; se cuentan antes.
    usuario.save(update_fields=["is_active"])
    return abiertas
