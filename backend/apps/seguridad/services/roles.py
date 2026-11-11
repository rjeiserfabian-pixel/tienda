"""Gestión de roles, asignaciones y excepciones, con protección anti-escalada.

Reglas que se hacen cumplir AQUÍ (en el servidor), no en la interfaz:

* Nadie otorga permisos que no posee, ni con mayor alcance del que posee.
* Los roles de sistema son intocables.
* Nadie puede quitar (ni desactivar) al último administrador de la organización.
* Toda operación valida que usuario, rol y empresa son de la MISMA organización.
"""

import re
from collections.abc import Iterable
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.auditoria.servicios import diferencia, registrar
from apps.core.exceptions import ViolacionAmbito
from apps.organizacion.models import Empresa
from apps.seguridad.exceptions import (
    EscaladaDePrivilegios,
    MotivoRequerido,
    RolDeSistemaIntocable,
    RolEnUso,
    UltimoAdministrador,
)
from apps.seguridad.models import (
    Alcance,
    Permiso,
    Rol,
    RolPermiso,
    TipoExcepcion,
    Usuario,
    UsuarioPermiso,
    UsuarioRol,
)
from apps.seguridad.permisos_catalogo import CODIGOS
from apps.seguridad.services import permisos_engine as motor

_CODIGO_ROL = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")

GESTIONAR_ROLES = "SEGURIDAD.ROLES.GESTIONAR"
ASIGNAR_ROL = "SEGURIDAD.USUARIOS.ASIGNAR_ROL"
EXCEPCIONES = "SEGURIDAD.USUARIOS.EXCEPCIONES"


# ---------------------------------------------------------------------------
# Verificaciones comunes
# ---------------------------------------------------------------------------
def exigir_misma_organizacion(actor: Usuario, organizacion_id: int | None) -> None:
    if actor.es_admin_plataforma:
        return
    if actor.organizacion_id is None or actor.organizacion_id != organizacion_id:
        raise ViolacionAmbito()


def _empresas_objetivo(usuario: Usuario, empresa_id: int | None) -> list[int | None]:
    """Empresas donde tendrá efecto una asignación (todas las del usuario si no se indica)."""
    if empresa_id is not None:
        return [empresa_id]
    return list(motor.empresas_ids_de(usuario)) or [None]


def exigir_que_actor_posee(
    actor: Usuario, requeridos: dict[str, str], empresas: Iterable[int | None]
) -> None:
    """Anti-escalada: el solicitante debe poseer cada permiso, con alcance suficiente."""
    for empresa_id in empresas:
        poseidos = motor.permisos_de(actor, empresa_id).permisos
        for codigo, alcance in requeridos.items():
            if not motor.alcance_cubre(poseidos.get(codigo), alcance):
                raise EscaladaDePrivilegios(
                    detalle={"permiso": codigo, "alcance": alcance, "empresa": empresa_id}
                )


def _validar_alcance(alcance: str) -> None:
    if alcance not in Alcance.values:
        raise ValidationError({"alcance": f"Alcance inválido: {alcance}"})


def _validar_vencimiento(vigente_hasta: datetime | None) -> None:
    if vigente_hasta is not None and vigente_hasta <= timezone.now():
        raise ValidationError({"vigente_hasta": "La fecha de vencimiento debe ser futura."})


def _vigente(ahora: datetime) -> Q:
    return Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gt=ahora)


def exigir_otro_administrador(
    organizacion_id: int,
    *,
    excluyendo_asignacion: UsuarioRol | None = None,
    excluyendo_usuario: Usuario | None = None,
) -> None:
    """Falla si, al quitar lo indicado, ningún usuario ACTIVO conservaría un rol crítico vigente."""
    restantes = UsuarioRol.objects.sin_ambito().filter(
        _vigente(timezone.now()),
        organizacion_id=organizacion_id,
        rol__es_critico=True,
        rol__eliminado_en__isnull=True,
        usuario__is_active=True,
    )
    if excluyendo_asignacion is not None:
        restantes = restantes.exclude(pk=excluyendo_asignacion.pk)
    if excluyendo_usuario is not None:
        restantes = restantes.exclude(usuario=excluyendo_usuario)
    if not restantes.exists():
        raise UltimoAdministrador()


def usuario_tiene_rol_critico(usuario: Usuario) -> bool:
    return (
        UsuarioRol.objects.sin_ambito()
        .filter(
            _vigente(timezone.now()),
            usuario=usuario,
            rol__es_critico=True,
            rol__eliminado_en__isnull=True,
        )
        .exists()
    )


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def _validar_permisos_de_rol(permisos: dict[str, str]) -> None:
    for codigo, alcance in permisos.items():
        if codigo not in CODIGOS:
            raise ValidationError({"permisos": f"Permiso desconocido: {codigo}"})
        _validar_alcance(alcance)


@transaction.atomic
def crear_rol(
    actor: Usuario,
    *,
    organizacion,
    codigo: str,
    nombre: str,
    descripcion: str = "",
    es_critico: bool = False,
    permisos: dict[str, str] | None = None,
) -> Rol:
    exigir_misma_organizacion(actor, organizacion.pk)
    motor.exigir_permiso(actor, GESTIONAR_ROLES)
    codigo = codigo.strip().upper()
    if not _CODIGO_ROL.match(codigo):
        raise ValidationError(
            {"codigo": "Use mayúsculas, números y guion bajo (2 a 40 caracteres)."}
        )
    if es_critico:
        # Un rol crítico concede privilegios de administración: solo quien ya los tiene.
        exigir_que_actor_posee(actor, {GESTIONAR_ROLES: "ORGANIZACION"}, [None])
    rol = Rol(
        organizacion=organizacion,
        codigo=codigo,
        nombre=nombre.strip(),
        descripcion=descripcion,
        es_critico=es_critico,
    )
    rol.full_clean(validate_unique=False, validate_constraints=False)
    try:
        with transaction.atomic():  # savepoint: la transacción externa sigue utilizable
            rol.save()
    except IntegrityError:
        raise ValidationError({"codigo": "Ya existe un rol con ese código."}) from None
    if permisos:
        establecer_permisos_de_rol(actor, rol, permisos)
    motor.invalidar_organizacion(organizacion.pk)
    registrar(
        "rol.creado",
        recurso_tipo="rol",
        recurso_id=rol.pk,
        resumen=f"Rol {rol.codigo} creado",
        detalle={"codigo": rol.codigo, "nombre": rol.nombre, "es_critico": es_critico},
    )
    return rol


@transaction.atomic
def actualizar_rol(actor: Usuario, rol: Rol, *, nombre: str, descripcion: str = "") -> Rol:
    exigir_misma_organizacion(actor, rol.organizacion_id)
    motor.exigir_permiso(actor, GESTIONAR_ROLES)
    if rol.es_sistema:
        raise RolDeSistemaIntocable()
    antes = {"nombre": rol.nombre, "descripcion": rol.descripcion}
    rol.nombre, rol.descripcion = nombre.strip(), descripcion
    rol.full_clean(validate_unique=False, validate_constraints=False)
    rol.save(update_fields=["nombre", "descripcion"])
    cambios = diferencia(antes, {"nombre": rol.nombre, "descripcion": rol.descripcion})
    if cambios:
        registrar(
            "rol.editado",
            recurso_tipo="rol",
            recurso_id=rol.pk,
            resumen=f"Rol {rol.codigo} modificado",
            detalle=cambios,
        )
    return rol


@transaction.atomic
def eliminar_rol(actor: Usuario, rol: Rol) -> None:
    exigir_misma_organizacion(actor, rol.organizacion_id)
    motor.exigir_permiso(actor, GESTIONAR_ROLES)
    if rol.es_sistema:
        raise RolDeSistemaIntocable()
    if UsuarioRol.objects.sin_ambito().filter(rol=rol).exists():
        raise RolEnUso()
    RolPermiso.objects.sin_ambito().filter(rol=rol).delete()
    rol.delete()
    motor.invalidar_organizacion(rol.organizacion_id)
    registrar(
        "rol.eliminado",
        recurso_tipo="rol",
        recurso_id=rol.pk,
        resumen=f"Rol {rol.codigo} eliminado",
        detalle={"codigo": rol.codigo, "nombre": rol.nombre},
    )


@transaction.atomic
def establecer_permisos_de_rol(actor: Usuario, rol: Rol, permisos: dict[str, str]) -> None:
    """Reemplaza la matriz de permisos del rol. Solo se exige poseer lo que se AGREGA o AMPLÍA."""
    exigir_misma_organizacion(actor, rol.organizacion_id)
    motor.exigir_permiso(actor, GESTIONAR_ROLES)
    if rol.es_sistema:
        raise RolDeSistemaIntocable()
    _validar_permisos_de_rol(permisos)

    actuales = {
        f.permiso.codigo: f
        for f in RolPermiso.objects.sin_ambito().filter(rol=rol).select_related("permiso")
    }
    nuevos = {
        c: a
        for c, a in permisos.items()
        if c not in actuales or motor.ORDEN_ALCANCE[a] > motor.ORDEN_ALCANCE[actuales[c].alcance]
    }
    # El editor debe poseer lo agregado en TODAS las empresas donde él opera.
    empresas_editor = list(motor.empresas_ids_de(actor)) or [None]
    exigir_que_actor_posee(actor, nuevos, [None, *empresas_editor])

    quitar = [f.pk for c, f in actuales.items() if c not in permisos]
    if quitar:
        RolPermiso.objects.sin_ambito().filter(pk__in=quitar).delete()
    for codigo, alcance in permisos.items():
        existente = actuales.get(codigo)
        if existente is None:
            RolPermiso(
                organizacion_id=rol.organizacion_id,
                rol=rol,
                permiso=Permiso.objects.get(codigo=codigo, activo=True),
                alcance=alcance,
            ).save()
        elif existente.alcance != alcance:
            RolPermiso.objects.sin_ambito().filter(pk=existente.pk).update(alcance=alcance)
    motor.invalidar_organizacion(rol.organizacion_id)
    anteriores = {c: f.alcance for c, f in actuales.items()}
    agregados = {c: a for c, a in permisos.items() if c not in anteriores}
    quitados = sorted(c for c in anteriores if c not in permisos)
    cambiados = {
        c: [anteriores[c], a] for c, a in permisos.items() if c in anteriores and anteriores[c] != a
    }
    if agregados or quitados or cambiados:
        registrar(
            "rol.permisos_modificados",
            recurso_tipo="rol",
            recurso_id=rol.pk,
            resumen=f"Permisos del rol {rol.codigo} modificados",
            detalle={"agregados": agregados, "quitados": quitados, "cambiados": cambiados},
        )


# ---------------------------------------------------------------------------
# Asignación de roles a usuarios
# ---------------------------------------------------------------------------
def _empresa_o_none(empresa: Empresa | None) -> int | None:
    return empresa.pk if empresa is not None else None


def _exigir_acceso_a_empresa(usuario: Usuario, empresa_id: int | None) -> None:
    if empresa_id is not None and empresa_id not in motor.empresas_ids_de(usuario):
        raise ViolacionAmbito("El usuario no tiene acceso vigente a esa empresa.")


@transaction.atomic
def asignar_rol(
    actor: Usuario,
    *,
    usuario: Usuario,
    rol: Rol,
    empresa: Empresa | None = None,
    vigente_hasta: datetime | None = None,
) -> UsuarioRol:
    """Asigna ``rol`` al usuario (en una empresa o en todas las suyas)."""
    exigir_misma_organizacion(actor, rol.organizacion_id)
    if usuario.organizacion_id != rol.organizacion_id:
        raise ViolacionAmbito()
    empresa_id = _empresa_o_none(empresa)
    _exigir_acceso_a_empresa(usuario, empresa_id)
    _validar_vencimiento(vigente_hasta)

    destinos = _empresas_objetivo(usuario, empresa_id)
    motor.exigir_permiso_en_empresas(actor, ASIGNAR_ROL, destinos)
    requeridos = {
        f.permiso.codigo: f.alcance
        for f in RolPermiso.objects.sin_ambito().filter(rol=rol).select_related("permiso")
    }
    exigir_que_actor_posee(actor, requeridos, destinos)

    asignacion = (
        UsuarioRol.objects.sin_ambito()
        .filter(usuario=usuario, rol=rol, empresa_id=empresa_id)
        .first()
    )
    if asignacion is None:
        asignacion = UsuarioRol(
            organizacion_id=rol.organizacion_id,
            usuario=usuario,
            rol=rol,
            empresa=empresa,
            vigente_hasta=vigente_hasta,
        )
        asignacion.save()
    else:
        asignacion.vigente_hasta = vigente_hasta
        asignacion.save(update_fields=["vigente_hasta"])
    motor.invalidar_usuario(usuario.pk)
    registrar(
        "usuario.rol_asignado",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        empresa_id=empresa_id,
        resumen=f"Rol {rol.codigo} asignado a {usuario.username}",
        detalle={"rol": rol.codigo, "empresa": empresa_id, "vigente_hasta": vigente_hasta},
    )
    return asignacion


@transaction.atomic
def quitar_rol(actor: Usuario, asignacion: UsuarioRol) -> None:
    exigir_misma_organizacion(actor, asignacion.organizacion_id)
    destinos = _empresas_objetivo(asignacion.usuario, asignacion.empresa_id)
    motor.exigir_permiso_en_empresas(actor, ASIGNAR_ROL, destinos)
    if asignacion.rol.es_critico:
        exigir_otro_administrador(asignacion.organizacion_id, excluyendo_asignacion=asignacion)
    asignacion.delete()
    motor.invalidar_usuario(asignacion.usuario_id)
    registrar(
        "usuario.rol_quitado",
        recurso_tipo="usuario",
        recurso_id=asignacion.usuario_id,
        empresa_id=asignacion.empresa_id,
        resumen=f"Rol {asignacion.rol.codigo} quitado a {asignacion.usuario.username}",
        detalle={"rol": asignacion.rol.codigo, "empresa": asignacion.empresa_id},
    )


@transaction.atomic
def asignar_rol_de_sistema(
    usuario: Usuario, codigo_rol: str, empresa: Empresa | None = None
) -> UsuarioRol:
    """Asignación SIN solicitante, solo para comandos y semillas (alta inicial de un admin)."""
    rol = Rol.objects.sin_ambito().get(organizacion_id=usuario.organizacion_id, codigo=codigo_rol)
    asignacion, _ = UsuarioRol.objects.sin_ambito().get_or_create(
        usuario=usuario,
        rol=rol,
        empresa=empresa,
        defaults={"organizacion_id": rol.organizacion_id},
    )
    motor.invalidar_usuario(usuario.pk)
    return asignacion


# ---------------------------------------------------------------------------
# Excepciones individuales
# ---------------------------------------------------------------------------
@transaction.atomic
def otorgar_excepcion(
    actor: Usuario,
    *,
    usuario: Usuario,
    codigo: str,
    tipo: str,
    motivo: str,
    empresa: Empresa | None = None,
    alcance: str = Alcance.EMPRESA,
    vigente_hasta: datetime | None = None,
) -> UsuarioPermiso:
    """ALLOW/DENY individual, siempre con motivo. Un ALLOW también pasa por la anti-escalada."""
    exigir_misma_organizacion(actor, usuario.organizacion_id)
    if not (motivo or "").strip():
        raise MotivoRequerido()
    if codigo not in CODIGOS:
        raise ValidationError({"codigo": f"Permiso desconocido: {codigo}"})
    if tipo not in TipoExcepcion.values:
        raise ValidationError({"tipo": f"Tipo inválido: {tipo}"})
    _validar_alcance(alcance)
    _validar_vencimiento(vigente_hasta)

    empresa_id = _empresa_o_none(empresa)
    _exigir_acceso_a_empresa(usuario, empresa_id)
    destinos = _empresas_objetivo(usuario, empresa_id)
    motor.exigir_permiso_en_empresas(actor, EXCEPCIONES, destinos)
    if tipo == TipoExcepcion.ALLOW:
        exigir_que_actor_posee(actor, {codigo: alcance}, destinos)

    permiso = Permiso.objects.get(codigo=codigo, activo=True)
    excepcion = (
        UsuarioPermiso.objects.sin_ambito()
        .filter(usuario=usuario, permiso=permiso, empresa_id=empresa_id)
        .first()
    )
    if excepcion is None:
        excepcion = UsuarioPermiso(
            organizacion_id=usuario.organizacion_id,
            usuario=usuario,
            permiso=permiso,
            empresa=empresa,
            tipo=tipo,
            alcance=alcance,
            vigente_hasta=vigente_hasta,
            motivo=motivo.strip(),
        )
        excepcion.save()
    else:
        excepcion.tipo, excepcion.alcance = tipo, alcance
        excepcion.vigente_hasta, excepcion.motivo = vigente_hasta, motivo.strip()
        excepcion.save(update_fields=["tipo", "alcance", "vigente_hasta", "motivo"])
    motor.invalidar_usuario(usuario.pk)
    registrar(
        "usuario.excepcion_otorgada",
        recurso_tipo="usuario",
        recurso_id=usuario.pk,
        empresa_id=empresa_id,
        resumen=f"{tipo} sobre {codigo} para {usuario.username}",
        detalle={
            "permiso": codigo,
            "tipo": tipo,
            "alcance": alcance,
            "motivo": motivo.strip(),
            "vigente_hasta": vigente_hasta,
        },
    )
    return excepcion


@transaction.atomic
def revocar_excepcion(actor: Usuario, excepcion: UsuarioPermiso) -> None:
    exigir_misma_organizacion(actor, excepcion.organizacion_id)
    destinos = _empresas_objetivo(excepcion.usuario, excepcion.empresa_id)
    motor.exigir_permiso_en_empresas(actor, EXCEPCIONES, destinos)
    excepcion.delete()
    motor.invalidar_usuario(excepcion.usuario_id)
    registrar(
        "usuario.excepcion_revocada",
        recurso_tipo="usuario",
        recurso_id=excepcion.usuario_id,
        empresa_id=excepcion.empresa_id,
        resumen=f"Excepción sobre {excepcion.permiso.codigo} quitada",
        detalle={"permiso": excepcion.permiso.codigo, "tipo": excepcion.tipo},
    )
