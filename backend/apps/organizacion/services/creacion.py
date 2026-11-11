"""Alta de una organización con su primera empresa (reutilizable por comando y API)."""

from dataclasses import dataclass

from django.db import transaction

from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Organizacion, Sucursal


@dataclass(frozen=True, slots=True)
class OrganizacionCreada:
    organizacion: Organizacion
    empresa: Empresa
    sucursal: Sucursal
    configuracion: ConfiguracionEmpresa


@transaction.atomic
def crear_organizacion_con_empresa(
    *,
    nombre_organizacion: str,
    razon_social: str,
    ruc: str,
    nombre_comercial: str = "",
    codigo_sucursal: str = "001",
    nombre_sucursal: str = "Principal",
) -> OrganizacionCreada:
    """Crea Organización, Empresa, Sucursal principal y su configuración, todo o nada.

    Aún no existe un tenant activo (es el alta del tenant), por eso se omite la
    validación de unicidad de Django, que consulta el gestor con ámbito. La
    unicidad la garantizan las restricciones de la base de datos: un RUC o
    nombre duplicado lanza ``IntegrityError`` y la transacción se revierte.
    """
    sin_unicidad = {"validate_unique": False, "validate_constraints": False}

    organizacion = Organizacion(nombre=nombre_organizacion)
    organizacion.full_clean(**sin_unicidad)
    organizacion.save()

    empresa = Empresa(
        organizacion=organizacion,
        razon_social=razon_social,
        ruc=ruc,
        nombre_comercial=nombre_comercial,
    )
    empresa.full_clean(**sin_unicidad)
    empresa.save()

    sucursal = Sucursal(empresa=empresa, nombre=nombre_sucursal, codigo=codigo_sucursal)
    sucursal.full_clean(**sin_unicidad)
    sucursal.save()

    configuracion = ConfiguracionEmpresa(empresa=empresa)
    configuracion.full_clean(**sin_unicidad)
    configuracion.save()

    # Import local: ``seguridad`` depende de ``organizacion``, no al revés.
    from apps.seguridad.services.catalogo import sembrar_roles_plantilla

    sembrar_roles_plantilla(organizacion)
    # Tipos de comprobante, afectaciones del IGV y tasa del IGV de SUNAT (mantenimiento).
    from apps.mantenimiento.fiscal import sembrar_catalogos_fiscales
    from apps.mantenimiento.pagos import sembrar_catalogos_pago

    sembrar_catalogos_fiscales(organizacion.pk)
    sembrar_catalogos_pago(organizacion.pk)  # métodos de pago y periodicidades
    from apps.mantenimiento.conceptos_caja import sembrar_conceptos_caja

    sembrar_conceptos_caja(organizacion.pk)  # conceptos de caja
    from apps.mantenimiento.categorias_gasto import sembrar_categorias_gasto

    sembrar_categorias_gasto(organizacion.pk)  # categorías de gasto
    from apps.servicio_tecnico.catalogos import sembrar_catalogos_servicio

    sembrar_catalogos_servicio(organizacion.pk)  # tipos de equipo, accesorios, revisiones…

    return OrganizacionCreada(organizacion, empresa, sucursal, configuracion)
