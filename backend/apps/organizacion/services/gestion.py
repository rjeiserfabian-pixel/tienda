"""Alta y modificación de empresas y sucursales (la organización la define el tenant activo).

Las reglas de PERMISO las aplica la capa de API (``PermisoRBAC``); aquí viven las reglas del
dominio: el RUC no cambia, una organización conserva al menos una empresa activa y cada
empresa nace con su sucursal principal y su configuración.
"""

import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.auditoria.servicios import diferencia, registrar
from apps.core.tenant import contexto_tenant, obtener_contexto_requerido
from apps.organizacion.exceptions import RucBloqueado, UltimaEmpresaActiva, UltimaSucursalActiva
from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Estado, Organizacion, Sucursal

logger = logging.getLogger(__name__)

SIN_UNICIDAD = {"validate_unique": False, "validate_constraints": False}


def _guardar_unico(instancia, campo: str, mensaje: str, **kwargs) -> None:
    """Guarda y traduce la violación de unicidad de la base de datos en un error de campo."""
    try:
        with transaction.atomic():  # savepoint: la transacción externa sigue utilizable
            instancia.save(**kwargs)
    except IntegrityError:
        raise ValidationError({campo: mensaje}) from None


@transaction.atomic
def actualizar_organizacion(
    organizacion: Organizacion, *, nombre: str, mfa_obligatorio: bool, calculo_precios: str
) -> Organizacion:
    antes = {
        "nombre": organizacion.nombre,
        "mfa_obligatorio": organizacion.mfa_obligatorio,
        "calculo_precios": organizacion.calculo_precios,
    }
    organizacion.nombre = nombre.strip()
    organizacion.mfa_obligatorio = mfa_obligatorio
    organizacion.calculo_precios = calculo_precios
    organizacion.full_clean(**SIN_UNICIDAD)
    _guardar_unico(
        organizacion,
        "nombre",
        "Ya existe una organización con ese nombre.",
        update_fields=["nombre", "mfa_obligatorio", "calculo_precios"],
    )
    cambios = diferencia(
        antes,
        {
            "nombre": organizacion.nombre,
            "mfa_obligatorio": organizacion.mfa_obligatorio,
            "calculo_precios": organizacion.calculo_precios,
        },
    )
    if cambios:
        from apps.seguridad.services import politicas

        politicas.invalidar(organizacion.pk)  # la política rige desde la siguiente petición
        registrar(
            "organizacion.editada",
            recurso_tipo="organizacion",
            recurso_id=organizacion.pk,
            resumen="Datos o políticas de la organización modificados",
            detalle=cambios,
        )
    return organizacion


@transaction.atomic
def crear_empresa(
    *,
    organizacion: Organizacion,
    creador,
    razon_social: str,
    ruc: str,
    nombre_comercial: str = "",
    codigo_sucursal: str = "001",
    nombre_sucursal: str = "Principal",
) -> Empresa:
    """Crea la empresa con su sucursal principal, su configuración y el acceso de quien la crea."""
    from apps.seguridad.models import AccesoEmpresa  # seguridad depende de organizacion

    contexto = obtener_contexto_requerido()
    empresa = Empresa(
        organizacion=organizacion,
        razon_social=razon_social.strip(),
        ruc=ruc.strip(),
        nombre_comercial=nombre_comercial.strip(),
    )
    empresa.full_clean(**SIN_UNICIDAD)
    _guardar_unico(empresa, "ruc", "Ya existe una empresa activa con ese RUC.")

    # La empresa recién creada aún no figura en el token del solicitante: se amplía el
    # contexto solo durante este bloque para poder crear sus datos iniciales.
    with contexto_tenant(
        contexto.organizacion_id, {*contexto.empresa_ids, empresa.pk}, contexto.usuario_id
    ):
        sucursal = Sucursal(empresa=empresa, nombre=nombre_sucursal, codigo=codigo_sucursal)
        sucursal.full_clean(**SIN_UNICIDAD)
        sucursal.save()
        configuracion = ConfiguracionEmpresa(empresa=empresa)
        configuracion.full_clean(**SIN_UNICIDAD)
        configuracion.save()

    # Es la misma persona en todas sus empresas: el acceso nuevo hereda el cargo que ya tenía.
    cargo = (
        AccesoEmpresa.objects.sin_ambito()
        .filter(usuario=creador)
        .exclude(cargo="")
        .order_by("-pk")
        .values_list("cargo", flat=True)
        .first()
    )
    AccesoEmpresa(
        usuario=creador, empresa=empresa, organizacion=organizacion, cargo=cargo or ""
    ).save()
    registrar(
        "empresa.creada",
        recurso_tipo="empresa",
        recurso_id=empresa.pk,
        empresa_id=empresa.pk,
        resumen=f"Empresa {empresa.razon_social} creada",
        detalle={"ruc": empresa.ruc, "razon_social": empresa.razon_social},
    )
    logger.info(
        "empresa creada",
        extra={
            "empresa_id": empresa.pk,
            "organizacion_id": organizacion.pk,
            "usuario_id": creador.pk,
        },
    )
    return empresa


def tiene_documentos_emitidos(empresa: Empresa) -> bool:
    """¿La empresa ya emitió documentos tributarios (comprobantes, series)?

    Mientras no existan esos módulos es siempre ``False``. Cuando se añadan (facturación,
    ventas), este es el único punto que hay que ampliar para que el RUC quede bloqueado.
    """
    return False


CAMPOS_FICHA = (
    "direccion_fiscal",
    "telefono",
    "correo",
    "sitio_web",
    "tienda_web",
    "es_principal",
)


@transaction.atomic
def actualizar_empresa(
    empresa: Empresa,
    *,
    razon_social: str,
    nombre_comercial: str,
    estado: str,
    ruc: str | None = None,
    direccion_fiscal: str = "",
    telefono: str = "",
    correo: str = "",
    sitio_web: str = "",
    tienda_web: str = "",
    es_principal: bool = False,
) -> Empresa:
    """Modifica los datos de la empresa.

    Cambiar el RUC (su identidad tributaria) es excepcional: la vista exige el permiso de
    gestionar la organización, y aquí se valida el RUC, que no esté en uso y que la empresa
    no haya emitido documentos todavía.
    """
    nuevo_ruc = (ruc or "").strip()
    cambia_ruc = bool(nuevo_ruc) and nuevo_ruc != empresa.ruc
    if cambia_ruc and tiene_documentos_emitidos(empresa):
        raise RucBloqueado()
    if estado not in Estado.values:
        raise ValidationError({"estado": f"Estado inválido: {estado}"})
    if estado != Estado.ACTIVO and empresa.estado == Estado.ACTIVO:
        otras = Empresa.objects.filter(estado=Estado.ACTIVO).exclude(pk=empresa.pk).exists()
        if not otras:
            raise UltimaEmpresaActiva()
    cambia_estado = estado != empresa.estado
    antes = {
        "ruc": empresa.ruc,
        "razon_social": empresa.razon_social,
        "nombre_comercial": empresa.nombre_comercial,
        "estado": empresa.estado,
        **{campo: getattr(empresa, campo) for campo in CAMPOS_FICHA},
    }
    if cambia_ruc:
        empresa.ruc = nuevo_ruc
    empresa.razon_social = razon_social.strip()
    empresa.nombre_comercial = nombre_comercial.strip()
    empresa.estado = estado
    empresa.direccion_fiscal = direccion_fiscal.strip()
    empresa.telefono = telefono.strip()
    empresa.correo = correo.strip()
    empresa.sitio_web = sitio_web.strip()
    empresa.tienda_web = tienda_web.strip()
    empresa.es_principal = es_principal
    empresa.full_clean(**SIN_UNICIDAD)
    if es_principal and not antes["es_principal"]:
        # Solo una empresa por organización es la principal: la anterior deja de serlo.
        Empresa.objects.filter(es_principal=True).exclude(pk=empresa.pk).update(es_principal=False)
    # El RUC es único en todo el sistema (incluidas otras organizaciones): se traduce el choque.
    _guardar_unico(
        empresa,
        "ruc",
        "Ya existe una empresa activa con ese RUC.",
        update_fields=["ruc", "razon_social", "nombre_comercial", "estado", *CAMPOS_FICHA],
    )
    cambios = diferencia(antes, {campo: getattr(empresa, campo) for campo in antes})
    if cambios:
        registrar(
            "empresa.editada",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"Empresa {empresa.razon_social} modificada",
            detalle=cambios,
        )
    if cambia_ruc:
        registrar(
            "empresa.ruc_cambiado",
            recurso_tipo="empresa",
            recurso_id=empresa.pk,
            empresa_id=empresa.pk,
            resumen=f"RUC de {empresa.razon_social} cambiado de {antes['ruc']} a {empresa.ruc}",
            detalle={"ruc_anterior": antes["ruc"], "ruc_nuevo": empresa.ruc},
        )
    if cambia_estado:
        from apps.seguridad.services import permisos_engine as motor

        # Una empresa inactiva deja de contar como acceso: se invalida el caché de permisos.
        motor.invalidar_organizacion(empresa.organizacion_id)
    return empresa


@transaction.atomic
def crear_sucursal(
    *,
    empresa: Empresa,
    nombre: str,
    codigo: str,
    local_fisico: str = "",
    direccion: str = "",
    ubigeo: str = "",
) -> Sucursal:
    sucursal = Sucursal(
        empresa=empresa,
        nombre=nombre.strip(),
        codigo=codigo.strip().upper(),
        local_fisico=local_fisico.strip(),
        direccion=direccion.strip(),
        ubigeo=ubigeo.strip(),
    )
    sucursal.full_clean(**SIN_UNICIDAD)
    _guardar_unico(sucursal, "codigo", "Ya existe una sucursal con ese código en la empresa.")
    registrar(
        "sucursal.creada",
        recurso_tipo="sucursal",
        recurso_id=sucursal.pk,
        empresa_id=empresa.pk,
        resumen=f"Sucursal {sucursal.codigo} creada",
        detalle={"codigo": sucursal.codigo, "nombre": sucursal.nombre},
    )
    return sucursal


@transaction.atomic
def actualizar_sucursal(
    sucursal: Sucursal,
    *,
    nombre: str,
    local_fisico: str,
    direccion: str,
    ubigeo: str = "",
    estado: str,
) -> Sucursal:
    if estado not in Estado.values:
        raise ValidationError({"estado": f"Estado inválido: {estado}"})
    if estado != Estado.ACTIVO and sucursal.estado == Estado.ACTIVO:
        otras = (
            Sucursal.objects.filter(empresa_id=sucursal.empresa_id, estado=Estado.ACTIVO)
            .exclude(pk=sucursal.pk)
            .exists()
        )
        if not otras:
            raise UltimaSucursalActiva()
    campos = ("nombre", "local_fisico", "direccion", "ubigeo", "estado")
    antes = {campo: getattr(sucursal, campo) for campo in campos}
    sucursal.nombre = nombre.strip()
    sucursal.local_fisico = local_fisico.strip()
    sucursal.direccion = direccion.strip()
    sucursal.ubigeo = ubigeo.strip()
    sucursal.estado = estado
    sucursal.full_clean(**SIN_UNICIDAD)
    sucursal.save(update_fields=list(campos))
    cambios = diferencia(antes, {campo: getattr(sucursal, campo) for campo in campos})
    if cambios:
        registrar(
            "sucursal.editada",
            recurso_tipo="sucursal",
            recurso_id=sucursal.pk,
            empresa_id=sucursal.empresa_id,
            resumen=f"Sucursal {sucursal.codigo} modificada",
            detalle=cambios,
        )
    return sucursal
