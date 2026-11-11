from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.seguridad.models import (
    AccesoEmpresa,
    AccesoSucursal,
    MotivoRevocacion,
    Rol,
    RolPermiso,
    Usuario,
    UsuarioPermiso,
    UsuarioRol,
)
from apps.seguridad.services import permisos_engine as motor
from apps.seguridad.services import sesiones


@receiver(post_save, sender=Usuario)
def cerrar_sesiones_si_se_desactiva(sender, instance: Usuario, created: bool, **kwargs):
    """Red de seguridad: desactivar un usuario por CUALQUIER vía (admin, shell, API)
    deja sus sesiones revocadas. El historial del usuario no se toca."""
    if not created and not instance.is_active:
        sesiones.revocar_sesiones_de_usuario(instance, MotivoRevocacion.USUARIO_INACTIVO)


# ---------------------------------------------------------------------------
# Invalidación de la caché de permisos (por versión). Las operaciones masivas con
# ``QuerySet.update()`` no disparan señales: los servicios invalidan explícitamente.
# ---------------------------------------------------------------------------
_CAMPOS_QUE_AFECTAN_PERMISOS = {
    "is_active",
    "es_admin_plataforma",
    "organizacion",
    "organizacion_id",
}


@receiver(post_save, sender=Usuario)
def invalidar_permisos_si_cambia_el_usuario(
    sender, instance: Usuario, update_fields=None, **kwargs
):
    if update_fields is None or _CAMPOS_QUE_AFECTAN_PERMISOS & set(update_fields):
        motor.invalidar_usuario(instance.pk)


@receiver([post_save, post_delete], sender=UsuarioRol)
@receiver([post_save, post_delete], sender=UsuarioPermiso)
@receiver([post_save, post_delete], sender=AccesoEmpresa)
def invalidar_permisos_del_usuario(sender, instance, **kwargs):
    motor.invalidar_usuario(instance.usuario_id)


@receiver([post_save, post_delete], sender=AccesoSucursal)
def invalidar_permisos_por_sucursal(sender, instance: AccesoSucursal, **kwargs):
    usuario_id = (
        AccesoEmpresa.objects.sin_ambito(incluir_eliminados=True)
        .filter(pk=instance.acceso_empresa_id)
        .values_list("usuario_id", flat=True)
        .first()
    )
    if usuario_id:
        motor.invalidar_usuario(usuario_id)


@receiver([post_save, post_delete], sender=RolPermiso)
@receiver([post_save, post_delete], sender=Rol)
def invalidar_permisos_de_la_organizacion(sender, instance, **kwargs):
    motor.invalidar_organizacion(instance.organizacion_id)
