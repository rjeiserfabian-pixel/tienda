"""Alta, edición y baja de los maestros de Mantenimiento, con su rastro de auditoría."""

import logging

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.auditoria.servicios import diferencia, registrar

logger = logging.getLogger(__name__)

SIN_UNICIDAD = {"validate_unique": False, "validate_constraints": False}

# Datos financieros: la auditoría deja constancia de que cambiaron, pero no de su valor.
CAMPOS_SENSIBLES = frozenset({"cuenta_bancaria", "numero_cuenta", "cci"})


def _guardar(instancia, mensaje_duplicado: str, campo: str = "numero_documento", **kwargs) -> None:
    """Guarda y traduce el choque de unicidad de la base en un error del campo indicado."""
    try:
        with transaction.atomic():  # savepoint: la transacción externa sigue utilizable
            instancia.save(**kwargs)
    except IntegrityError as error:
        # Si el modelo tiene varias restricciones únicas, se dice cuál campo chocó.
        restriccion = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        campo, mensaje_duplicado = getattr(instancia, "RESTRICCIONES", {}).get(
            restriccion, (campo, mensaje_duplicado)
        )
        raise ValidationError({campo: mensaje_duplicado}) from None


def _empresa_de(instancia) -> int | None:
    return getattr(instancia, "empresa_id", None)


def _valor(valor):
    """Valor apto para el rastro de auditoría (JSON): claves foráneas por su id, fechas en ISO."""
    if hasattr(valor, "pk"):
        return str(valor.pk)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    return valor


@transaction.atomic
def crear(
    modelo,
    /,
    *,
    recurso: str,
    duplicado: str,
    campo_duplicado: str = "numero_documento",
    **datos,
):
    # ``modelo`` es solo posicional: un campo del registro puede llamarse igual (el del vehículo).
    instancia = modelo(**datos)
    instancia.full_clean(**SIN_UNICIDAD)
    _guardar(instancia, duplicado, campo_duplicado)
    registrar(
        f"{recurso}.creado",
        recurso_tipo=recurso,
        recurso_id=instancia.pk,
        empresa_id=_empresa_de(instancia),
        resumen=f"{modelo._meta.verbose_name.capitalize()} {instancia} registrado",
    )
    return instancia


@transaction.atomic
def actualizar(
    instancia, *, recurso: str, duplicado: str, campo_duplicado: str = "numero_documento", **datos
):
    campos = list(datos)
    antes = {campo: _valor(getattr(instancia, campo)) for campo in campos}
    for campo, valor in datos.items():
        setattr(instancia, campo, valor)
    instancia.full_clean(**SIN_UNICIDAD)
    _guardar(instancia, duplicado, campo_duplicado, update_fields=campos)
    cambios = diferencia(antes, {campo: _valor(getattr(instancia, campo)) for campo in campos})
    for campo in CAMPOS_SENSIBLES & cambios.keys():
        cambios[campo] = "modificado"
    if cambios:
        registrar(
            f"{recurso}.editado",
            recurso_tipo=recurso,
            recurso_id=instancia.pk,
            empresa_id=_empresa_de(instancia),
            resumen=f"{type(instancia)._meta.verbose_name.capitalize()} {instancia} modificado",
            detalle=cambios,
        )
    return instancia


@transaction.atomic
def eliminar(instancia, *, recurso: str) -> None:
    """Borrado lógico: deja de aparecer, libera su documento y conserva el historial."""
    etiqueta = str(instancia)
    if getattr(instancia, "usuario_id", None):
        instancia.usuario = None  # libera al usuario para vincularlo a otro trabajador
        instancia.save(update_fields=["usuario"])
    instancia.delete()
    registrar(
        f"{recurso}.eliminado",
        recurso_tipo=recurso,
        recurso_id=instancia.pk,
        empresa_id=_empresa_de(instancia),
        resumen=f"{type(instancia)._meta.verbose_name.capitalize()} {etiqueta} eliminado",
    )
