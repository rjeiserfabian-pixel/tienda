"""Sincroniza el catálogo en código (permisos, menú, roles plantilla) con la base de datos.

Todo es idempotente: se puede ejecutar en cada despliegue (``manage.py sync_permisos``).
"""

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.organizacion.models import Organizacion
from apps.seguridad import permisos_catalogo as cat
from apps.seguridad.models import Modulo, Permiso, Rol, RolPermiso, UsuarioPermiso
from apps.seguridad.services.permisos_engine import invalidar_organizacion

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResumenSync:
    permisos_creados: int
    permisos_actualizados: int
    permisos_desactivados: int
    modulos: int


def _migrar_renombres(existentes: dict[str, Permiso]) -> int:
    """Aplica ``RENOMBRES``: los roles y excepciones que tenían el permiso viejo conservan el nuevo.

    El primer nombre reutiliza la fila (todo lo que apuntaba a ella la sigue); los demás son
    permisos nuevos que copian los roles y excepciones vigentes del original. Es idempotente.
    """
    definiciones = {p.codigo: p for p in cat.PERMISOS}
    migrados = 0
    for viejo, nuevos in cat.RENOMBRES.items():
        permiso = existentes.get(viejo)
        if permiso is None or nuevos[0] in existentes:
            continue
        principal = definiciones[nuevos[0]]
        permiso.codigo, permiso.modulo, permiso.accion = (
            principal.codigo,
            principal.modulo,
            principal.accion,
        )
        permiso.save(update_fields=["codigo", "modulo", "accion"])
        existentes[principal.codigo] = permiso
        del existentes[viejo]
        for codigo in nuevos[1:]:
            if codigo in existentes:
                continue
            d = definiciones[codigo]
            nuevo = Permiso.objects.create(
                codigo=d.codigo,
                modulo=d.modulo,
                accion=d.accion,
                descripcion=d.descripcion,
                es_critico=d.critico,
            )
            existentes[codigo] = nuevo
            filas_rol = []
            for fila in RolPermiso.objects.sin_ambito().filter(permiso=permiso):
                copia = RolPermiso(
                    organizacion_id=fila.organizacion_id,
                    rol_id=fila.rol_id,
                    permiso=nuevo,
                    alcance=fila.alcance,
                )
                copia._sembrando = True
                filas_rol.append(copia)
            RolPermiso.objects.sin_ambito().bulk_create(filas_rol)
            UsuarioPermiso.objects.sin_ambito().bulk_create(
                [
                    UsuarioPermiso(
                        organizacion_id=f.organizacion_id,
                        usuario_id=f.usuario_id,
                        permiso=nuevo,
                        empresa_id=f.empresa_id,
                        tipo=f.tipo,
                        alcance=f.alcance,
                        vigente_hasta=f.vigente_hasta,
                        motivo=f.motivo,
                    )
                    for f in UsuarioPermiso.objects.sin_ambito().filter(permiso=permiso)
                ]
            )
        migrados += 1
    return migrados


@transaction.atomic
def sincronizar_catalogo() -> ResumenSync:
    """Refleja ``PERMISOS`` y ``MODULOS`` en la base. Lo que sale del catálogo se desactiva."""
    existentes = {p.codigo: p for p in Permiso.objects.all()}
    renombrados = _migrar_renombres(existentes)
    por_crear, por_actualizar = [], []
    for definicion in cat.PERMISOS:
        actual = existentes.get(definicion.codigo)
        if actual is None:
            por_crear.append(
                Permiso(
                    codigo=definicion.codigo,
                    modulo=definicion.modulo,
                    accion=definicion.accion,
                    descripcion=definicion.descripcion,
                    es_critico=definicion.critico,
                )
            )
        elif (
            actual.modulo,
            actual.accion,
            actual.descripcion,
            actual.es_critico,
            actual.activo,
        ) != (
            definicion.modulo,
            definicion.accion,
            definicion.descripcion,
            definicion.critico,
            True,
        ):
            actual.modulo, actual.accion = definicion.modulo, definicion.accion
            actual.descripcion, actual.es_critico, actual.activo = (
                definicion.descripcion,
                definicion.critico,
                True,
            )
            por_actualizar.append(actual)
    Permiso.objects.bulk_create(por_crear)
    Permiso.objects.bulk_update(
        por_actualizar, ["modulo", "accion", "descripcion", "es_critico", "activo"]
    )
    desactivados = (
        Permiso.objects.filter(activo=True).exclude(codigo__in=cat.CODIGOS).update(activo=False)
    )

    permisos = {p.codigo: p for p in Permiso.objects.all()}
    codigos_modulo: list[str] = []

    def guardar(definicion: cat.ModuloDef, padre: Modulo | None, orden: int) -> None:
        modulo, _ = Modulo.objects.update_or_create(
            codigo=definicion.codigo,
            defaults={
                "nombre": definicion.nombre,
                "ruta": definicion.ruta,
                "icono": definicion.icono,
                "padre": padre,
                "orden": orden,
                "permiso_ver": permisos.get(definicion.permiso_ver)
                if definicion.permiso_ver
                else None,
                "activo": True,
            },
        )
        codigos_modulo.append(definicion.codigo)
        for i, hijo in enumerate(definicion.hijos):
            guardar(hijo, modulo, i)

    for i, raiz in enumerate(cat.MODULOS):
        guardar(raiz, None, i)
    Modulo.objects.exclude(codigo__in=codigos_modulo).update(activo=False)

    if desactivados or por_crear or por_actualizar or renombrados:
        for organizacion_id in Organizacion.objects.values_list("pk", flat=True):
            invalidar_organizacion(organizacion_id)
    logger.info(
        "catalogo_sincronizado",
        extra={
            "creados": len(por_crear),
            "actualizados": len(por_actualizar),
            "desactivados": desactivados,
        },
    )
    return ResumenSync(len(por_crear), len(por_actualizar), desactivados, len(codigos_modulo))


def _insertar_permisos_de_rol(rol: Rol, definicion: dict[str, str], permisos: dict[str, Permiso]):
    filas = []
    for codigo, alcance in definicion.items():
        permiso = permisos.get(codigo)
        if permiso is None:
            continue
        fila = RolPermiso(
            organizacion_id=rol.organizacion_id, rol=rol, permiso=permiso, alcance=alcance
        )
        fila._sembrando = True  # alta confiable: no repite validaciones por fila
        filas.append(fila)
    RolPermiso.objects.sin_ambito().bulk_create(filas)


@transaction.atomic
def sembrar_roles_plantilla(organizacion: Organizacion) -> dict[str, str]:
    """Crea los roles plantilla que falten en la organización.

    * Si el rol no existe: se crea con los permisos de la plantilla.
    * Si existe y es de SISTEMA (SUPERADMIN): se deja EXACTAMENTE como la plantilla.
    * Si existe y es editable: no se toca (la organización pudo personalizarlo).

    Devuelve ``{codigo_rol: "creado" | "sincronizado" | "intacto"}``.
    """
    sincronizar_catalogo_si_falta()
    permisos = {p.codigo: p for p in Permiso.objects.filter(activo=True)}
    resultado: dict[str, str] = {}

    for plantilla in cat.ROLES_PLANTILLA:
        rol = (
            Rol.objects.sin_ambito()
            .filter(organizacion=organizacion, codigo=plantilla.codigo)
            .first()
        )
        if rol is None:
            rol = Rol(
                organizacion=organizacion,
                codigo=plantilla.codigo,
                nombre=plantilla.nombre,
                descripcion=plantilla.descripcion,
                es_sistema=plantilla.es_sistema,
                es_critico=plantilla.es_critico,
            )
            rol._sembrando = True
            rol.save()
            _insertar_permisos_de_rol(rol, plantilla.permisos, permisos)
            resultado[plantilla.codigo] = "creado"
        elif rol.es_sistema:
            actuales = {
                fila.permiso.codigo: fila
                for fila in RolPermiso.objects.sin_ambito()
                .filter(rol=rol)
                .select_related("permiso")
            }
            sobrantes = [
                f.pk
                for c, f in actuales.items()
                if c not in plantilla.permisos or c not in permisos
            ]
            if sobrantes:
                RolPermiso.objects.sin_ambito().filter(pk__in=sobrantes).delete()
            faltantes = {c: a for c, a in plantilla.permisos.items() if c not in actuales}
            for codigo, fila in actuales.items():
                esperado = plantilla.permisos.get(codigo)
                if esperado and fila.alcance != esperado:
                    RolPermiso.objects.sin_ambito().filter(pk=fila.pk).update(alcance=esperado)
            _insertar_permisos_de_rol(rol, faltantes, permisos)
            resultado[plantilla.codigo] = "sincronizado"
        else:
            resultado[plantilla.codigo] = "intacto"

    invalidar_organizacion(organizacion.pk)
    return resultado


def sincronizar_catalogo_si_falta() -> None:
    """Garantiza que el catálogo exista (primer uso); si ya está completo, no hace nada."""
    if Permiso.objects.filter(activo=True).count() < len(cat.CODIGOS):
        sincronizar_catalogo()
