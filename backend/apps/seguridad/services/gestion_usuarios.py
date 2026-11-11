"""Gestión de usuarios por parte de otro usuario (panel de administración).

Además del permiso de la operación, cada función aplica reglas que NO dependen de la
interfaz:

* Solo se gestionan usuarios de la misma organización.
* Nadie modifica a alguien con más privilegios que él (ni a sí mismo en lo crítico).
* Dar acceso a una empresa no puede ser un atajo para ampliar permisos: los roles globales
  del destinatario empiezan a regir en esa empresa, así que el solicitante debe poseerlos.
"""

import logging
import secrets
from collections.abc import Iterable
from datetime import datetime

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.auditoria.servicios import diferencia, registrar
from apps.core.exceptions import ViolacionAmbito
from apps.organizacion.models import Empresa, Estado, Sucursal
from apps.seguridad.exceptions import (
    EscaladaDePrivilegios,
    OperacionSobreSiMismo,
    UsuarioConMasPrivilegios,
)
from apps.seguridad.models import (
    AccesoEmpresa,
    AccesoSucursal,
    MotivoRevocacion,
    RolPermiso,
    TipoExcepcion,
    Usuario,
    UsuarioPermiso,
    UsuarioRol,
)
from apps.seguridad.services import mfa, passwords, roles, sesiones, usuarios
from apps.seguridad.services import permisos_engine as motor

logger = logging.getLogger(__name__)

VER = "SEGURIDAD.USUARIOS.VER"
CREAR = "SEGURIDAD.USUARIOS.CREAR"
EDITAR = "SEGURIDAD.USUARIOS.EDITAR"
DESACTIVAR = "SEGURIDAD.USUARIOS.DESACTIVAR"
RESTABLECER_CLAVE = "SEGURIDAD.USUARIOS.RESTABLECER_CLAVE"
CAMBIAR_USUARIO = "SEGURIDAD.USUARIOS.CAMBIAR_USUARIO"

CAMPOS_EDITABLES = ("first_name", "last_name", "email", "telefono", "documento_numero", "username")


def _vigente(ahora: datetime) -> Q:
    return Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gt=ahora)


# ---------------------------------------------------------------------------
# Visibilidad
# ---------------------------------------------------------------------------
def usuarios_visibles(actor: Usuario, codigo: str) -> QuerySet[Usuario]:
    """Usuarios que ``actor`` puede ver/gestionar con ese permiso.

    Son: él mismo, quienes comparten con él una empresa donde su alcance llega a la empresa
    entera, y quienes ya no tienen ningún acceso (para poder rehabilitarlos).
    """
    if actor.organizacion_id is None:
        return Usuario.objects.none()  # el administrador de plataforma opera por otra vía
    base = Usuario.objects.filter(organizacion_id=actor.organizacion_id)
    empresas = [
        empresa_id
        for empresa_id in motor.empresas_ids_de(actor)
        if motor.alcance_cubre(motor.alcance_de(actor, codigo, empresa_id), "EMPRESA")
    ]
    con_acceso = AccesoEmpresa.objects.filter(usuario=OuterRef("pk"))
    condicion = Q(pk=actor.pk) | ~Exists(con_acceso)
    if empresas:
        condicion |= Exists(con_acceso.filter(empresa_id__in=empresas))
    return base.filter(condicion)


def _empresas_del_objetivo(usuario: Usuario) -> list[int | None]:
    return list(motor.empresas_ids_de(usuario)) or [None]


def exigir_que_actor_cubre_a(actor: Usuario, usuario: Usuario) -> None:
    """El solicitante debe poseer todo lo que el objetivo posee, en cada empresa de este."""
    if actor.pk == usuario.pk:
        return
    for empresa_id in _empresas_del_objetivo(usuario):
        objetivo = motor.permisos_de(usuario, empresa_id).permisos
        try:
            roles.exigir_que_actor_posee(actor, objetivo, [empresa_id])
        except EscaladaDePrivilegios:
            raise UsuarioConMasPrivilegios() from None


def _permisos_globales(usuario: Usuario) -> dict[str, str]:
    """Permisos que el usuario tiene en TODAS sus empresas (roles y ALLOW sin empresa)."""
    ahora = timezone.now()
    roles_ids = UsuarioRol.objects.filter(
        _vigente(ahora), usuario=usuario, empresa__isnull=True, rol__eliminado_en__isnull=True
    ).values_list("rol_id", flat=True)
    resultado: dict[str, str] = {}
    for fila in RolPermiso.objects.filter(rol_id__in=list(roles_ids)).select_related("permiso"):
        resultado[fila.permiso.codigo] = (
            motor.mas_amplio(resultado.get(fila.permiso.codigo), fila.alcance) or fila.alcance
        )
    permitidos = UsuarioPermiso.objects.filter(
        _vigente(ahora), usuario=usuario, empresa__isnull=True, tipo=TipoExcepcion.ALLOW
    ).select_related("permiso")
    for fila in permitidos:
        resultado[fila.permiso.codigo] = (
            motor.mas_amplio(resultado.get(fila.permiso.codigo), fila.alcance) or fila.alcance
        )
    return resultado


# ---------------------------------------------------------------------------
# Alta y edición
# ---------------------------------------------------------------------------
@transaction.atomic
def crear_usuario_gestionado(
    actor: Usuario,
    *,
    username: str,
    email: str,
    password: str,
    nombres: str = "",
    apellidos: str = "",
    empresa_ids: Iterable[int] = (),
    cargo: str = "",
    telefono: str = "",
    documento_numero: str = "",
    activo: bool = True,
    rol=None,
) -> Usuario:
    """Alta desde el panel: la contraseña es temporal, debe cambiarla en su primer ingreso.

    Con ``rol`` se asigna de una vez (en todas las empresas del usuario). Todo es atómico: si
    quien crea no puede otorgar ese rol, no se crea el usuario.
    """
    if actor.organizacion_id is None:
        raise ViolacionAmbito()
    empresa_ids = sorted(set(empresa_ids))
    if not empresa_ids:
        raise ValidationError({"empresa_ids": "Indique al menos una empresa de acceso."})
    # El solicitante solo da acceso a empresas donde él puede crear usuarios.
    motor.exigir_permiso_en_empresas(actor, CREAR, empresa_ids)
    usuario = usuarios.crear_usuario(
        organizacion=actor.organizacion,
        username=username,
        email=email,
        password=password,
        nombres=nombres,
        apellidos=apellidos,
        empresa_ids=empresa_ids,
        cargo=cargo,
        debe_cambiar_password=True,
        telefono=telefono,
        documento_numero=documento_numero,
        activo=activo,
    )
    if rol is not None:
        roles.asignar_rol(actor, usuario=usuario, rol=rol, empresa=None)
    logger.info(
        "usuario creado",
        extra={"usuario_id": str(usuario.pk), "actor_id": str(actor.pk), "empresas": empresa_ids},
    )
    registrar(
        "usuario.creado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        resumen=f"Alta del usuario {usuario.username}",
        detalle={
            "username": usuario.username,
            "email": usuario.email,
            "empresas": empresa_ids,
            "activo": activo,
            "rol": rol.codigo if rol is not None else None,
        },
    )
    return usuario


@transaction.atomic
def actualizar_usuario(actor: Usuario, usuario: Usuario, **cambios) -> Usuario:
    """Edita datos personales. El correo (futuro canal de recuperación) exige cubrir al usuario."""
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    motor.exigir_permiso_en_empresas(actor, EDITAR, _empresas_del_objetivo(usuario))
    desconocidos = set(cambios) - set(CAMPOS_EDITABLES)
    if desconocidos:
        raise ValidationError(dict.fromkeys(sorted(desconocidos), "Campo no editable."))
    usuario_anterior = usuario.username
    nuevo_usuario = (cambios.pop("username", None) or "").strip() or None
    cambia_username = nuevo_usuario is not None and nuevo_usuario != usuario_anterior
    if cambia_username:
        # Cambiar con qué nombre entra alguien es delicado: permiso propio, nunca sobre uno mismo
        # y solo sobre quien el solicitante cubre (como el correo o la contraseña).
        if actor.pk == usuario.pk:
            raise OperacionSobreSiMismo()
        motor.exigir_permiso_en_empresas(actor, CAMBIAR_USUARIO, _empresas_del_objetivo(usuario))
        exigir_que_actor_cubre_a(actor, usuario)
        usuarios.exigir_username_libre(nuevo_usuario, excepto_pk=usuario.pk)
        cambios["username"] = nuevo_usuario
    nuevo_email = (cambios.get("email") or "").strip().lower()
    if "email" in cambios and nuevo_email != usuario.email:
        exigir_que_actor_cubre_a(actor, usuario)
    antes = {campo: getattr(usuario, campo) for campo in cambios}
    for campo, valor in cambios.items():
        setattr(usuario, campo, valor)
    usuario.full_clean(exclude=["password"])
    usuario.save(update_fields=[*cambios, "actualizado_en"])
    cambiados = diferencia(antes, {campo: getattr(usuario, campo) for campo in cambios})
    if cambiados:
        registrar(
            "usuario.editado",
            recurso_tipo="usuario",
            recurso_id=usuario.pk,
            resumen=f"Datos de {usuario.username} modificados",
            detalle=cambiados,
        )
    if cambia_username:
        registrar(
            "usuario.username_cambiado",
            recurso_tipo="usuario",
            recurso_id=usuario.pk,
            resumen=f"Nombre de usuario cambiado de {usuario_anterior} a {usuario.username}",
            detalle={"anterior": usuario_anterior, "nuevo": usuario.username},
        )
    return usuario


@transaction.atomic
def desactivar_usuario_gestionado(actor: Usuario, usuario: Usuario) -> int:
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    if actor.pk == usuario.pk:
        raise OperacionSobreSiMismo()
    motor.exigir_permiso_en_empresas(actor, DESACTIVAR, _empresas_del_objetivo(usuario))
    exigir_que_actor_cubre_a(actor, usuario)
    cerradas = usuarios.desactivar_usuario(usuario)
    motor.invalidar_usuario(usuario.pk)
    logger.info(
        "usuario desactivado", extra={"usuario_id": str(usuario.pk), "actor_id": str(actor.pk)}
    )
    registrar(
        "usuario.desactivado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        resumen=f"Usuario {usuario.username} desactivado",
        detalle={"sesiones_cerradas": cerradas},
    )
    return cerradas


@transaction.atomic
def reactivar_usuario(actor: Usuario, usuario: Usuario) -> Usuario:
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    motor.exigir_permiso_en_empresas(actor, DESACTIVAR, _empresas_del_objetivo(usuario))
    usuario.is_active = True
    usuario.save(update_fields=["is_active"])
    motor.invalidar_usuario(usuario.pk)
    logger.info(
        "usuario reactivado", extra={"usuario_id": str(usuario.pk), "actor_id": str(actor.pk)}
    )
    registrar(
        "usuario.reactivado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        resumen=f"Usuario {usuario.username} reactivado",
    )
    return usuario


@transaction.atomic
def restablecer_mfa(actor: Usuario, usuario: Usuario) -> None:
    """Quita el segundo factor de otro usuario que perdió su dispositivo.

    Es una operación de alto riesgo (debilita la cuenta): exige poder editar al usuario, cubrir
    sus permisos, y deja cerradas sus sesiones. Nadie lo hace sobre su propia cuenta.
    """
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    if actor.pk == usuario.pk:
        raise OperacionSobreSiMismo()
    motor.exigir_permiso_en_empresas(actor, EDITAR, _empresas_del_objetivo(usuario))
    exigir_que_actor_cubre_a(actor, usuario)
    mfa.restablecer(usuario)
    sesiones.revocar_sesiones_de_usuario(usuario, MotivoRevocacion.MFA_RESTABLECIDO)
    registrar(
        "mfa.restablecido",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        resumen=f"Segundo factor de {usuario.username} restablecido por un administrador",
    )


# Sin caracteres ambiguos (0/O, 1/l/I) para poder dictarla por teléfono sin errores.
_LETRAS = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_DIGITOS = "23456789"
_SIMBOLOS = "-_.@#"


def generar_password_temporal(usuario: Usuario | None = None, longitud: int = 14) -> str:
    """Contraseña aleatoria (CSPRNG) que cumple los validadores del sistema."""
    alfabeto = _LETRAS + _DIGITOS + _SIMBOLOS
    for _ in range(20):
        candidata = "".join(
            [secrets.choice(_LETRAS), secrets.choice(_DIGITOS), secrets.choice(_SIMBOLOS)]
            + [secrets.choice(alfabeto) for _ in range(longitud - 3)]
        )
        candidata = "".join(secrets.SystemRandom().sample(candidata, len(candidata)))
        try:
            validate_password(candidata, usuario)
        except ValidationError:
            continue
        return candidata
    raise RuntimeError("No se pudo generar una contraseña temporal válida.")


@transaction.atomic
def restablecer_password(actor: Usuario, usuario: Usuario) -> str:
    """Entrega una contraseña temporal a quien olvidó la suya (y no puede usar su correo).

    Devuelve la contraseña EN CLARO una sola vez: no se guarda ni se audita. El usuario deberá
    cambiarla al entrar, se cierran todas sus sesiones y queda el rastro de quién lo hizo.
    Nadie lo hace sobre su propia cuenta, y como exige poseer todo lo que posee el objetivo,
    un Administrador no puede restablecer a un Superadministrador.
    """
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    if actor.pk == usuario.pk:
        raise OperacionSobreSiMismo()
    motor.exigir_permiso_en_empresas(actor, RESTABLECER_CLAVE, _empresas_del_objetivo(usuario))
    exigir_que_actor_cubre_a(actor, usuario)
    temporal = generar_password_temporal(usuario)
    passwords.establecer_password(usuario, temporal, debe_cambiar=True)
    cerradas = sesiones.revocar_sesiones_de_usuario(usuario, MotivoRevocacion.CLAVE_RESTABLECIDA)
    registrar(
        "password.restablecida_admin",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        resumen=f"Contraseña de {usuario.username} restablecida por un administrador",
        detalle={"sesiones_cerradas": cerradas},
    )
    return temporal


# ---------------------------------------------------------------------------
# Accesos a empresas y sucursales
# ---------------------------------------------------------------------------
def _validar_acceso(estado: str, vigente_hasta: datetime | None) -> None:
    if estado not in Estado.values:
        raise ValidationError({"estado": f"Estado inválido: {estado}"})
    if vigente_hasta is not None and vigente_hasta <= timezone.now():
        raise ValidationError({"vigente_hasta": "La fecha de vencimiento debe ser futura."})


def _sincronizar_sucursales(acceso: AccesoEmpresa, sucursal_ids: set[int]) -> None:
    validas = set(
        Sucursal.objects.filter(empresa_id=acceso.empresa_id, pk__in=sucursal_ids).values_list(
            "pk", flat=True
        )
    )
    if validas != sucursal_ids:
        raise ValidationError({"sucursales": "Alguna sucursal no pertenece a la empresa."})
    actuales = {
        fila.sucursal_id: fila for fila in AccesoSucursal.objects.filter(acceso_empresa=acceso)
    }
    sobrantes = [fila.pk for sid, fila in actuales.items() if sid not in sucursal_ids]
    if sobrantes:
        AccesoSucursal.objects.filter(pk__in=sobrantes).delete()  # borrado lógico
    for sucursal_id in sorted(sucursal_ids - set(actuales)):
        AccesoSucursal(
            acceso_empresa=acceso, sucursal_id=sucursal_id, organizacion_id=acceso.organizacion_id
        ).save()


@transaction.atomic
def establecer_acceso(
    actor: Usuario,
    usuario: Usuario,
    empresa_id: int,
    *,
    cargo: str = "",
    estado: str = Estado.ACTIVO,
    vigente_hasta: datetime | None = None,
    sucursal_ids: Iterable[int] = (),
) -> AccesoEmpresa:
    """Crea o actualiza el acceso de ``usuario`` a una empresa (y sus sucursales)."""
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    if actor.pk == usuario.pk:
        raise OperacionSobreSiMismo()
    _validar_acceso(estado, vigente_hasta)
    empresa = Empresa.objects.filter(pk=empresa_id).first()
    if empresa is None:
        raise ValidationError({"empresa": "La empresa no existe."})
    motor.exigir_permiso(actor, EDITAR, empresa_id)

    acceso = AccesoEmpresa.objects.filter(usuario=usuario, empresa=empresa).first()
    quedaria_activo = estado == Estado.ACTIVO
    if quedaria_activo and (acceso is None or not acceso.esta_vigente()):
        # Los roles globales del destinatario pasan a regir aquí: debe poseerlos el solicitante.
        roles.exigir_que_actor_posee(actor, _permisos_globales(usuario), [empresa_id])
    if not quedaria_activo and acceso is not None and acceso.esta_vigente():
        exigir_que_actor_cubre_a(actor, usuario)  # restringir a un superior no es válido

    if acceso is None:
        acceso = AccesoEmpresa(
            usuario=usuario,
            empresa=empresa,
            organizacion_id=usuario.organizacion_id,
            cargo=cargo.strip(),
            estado=estado,
            vigente_hasta=vigente_hasta,
        )
        acceso.save()
    else:
        acceso.cargo, acceso.estado, acceso.vigente_hasta = cargo.strip(), estado, vigente_hasta
        acceso.save(update_fields=["cargo", "estado", "vigente_hasta"])
    _sincronizar_sucursales(acceso, set(sucursal_ids))
    motor.invalidar_usuario(usuario.pk)
    registrar(
        "usuario.acceso_establecido",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        empresa_id=empresa_id,
        resumen=f"Acceso de {usuario.username} a la empresa {empresa_id}",
        detalle={
            "estado": estado,
            "cargo": cargo,
            "vigente_hasta": vigente_hasta,
            "sucursales": sorted(set(sucursal_ids)),
        },
    )
    return acceso


@transaction.atomic
def quitar_acceso(actor: Usuario, usuario: Usuario, empresa_id: int) -> None:
    roles.exigir_misma_organizacion(actor, usuario.organizacion_id)
    if actor.pk == usuario.pk:
        raise OperacionSobreSiMismo()
    motor.exigir_permiso(actor, EDITAR, empresa_id)
    acceso = AccesoEmpresa.objects.filter(usuario=usuario, empresa_id=empresa_id).first()
    if acceso is None:
        raise ValidationError({"empresa": "El usuario no tiene acceso a esa empresa."})
    exigir_que_actor_cubre_a(actor, usuario)
    AccesoSucursal.objects.filter(acceso_empresa=acceso).delete()  # borrado lógico
    acceso.delete()
    motor.invalidar_usuario(usuario.pk)
    registrar(
        "usuario.acceso_quitado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        empresa_id=empresa_id,
        resumen=f"Se quitó el acceso de {usuario.username} a la empresa {empresa_id}",
    )
