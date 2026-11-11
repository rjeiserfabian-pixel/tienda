"""El trabajo sobre una orden abierta: diagnóstico, asignación del técnico y avisos al cliente."""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.auditoria.servicios import registrar
from apps.mantenimiento.models import Area, EstadoRegistro, Personal

from .exceptions import OrdenInvalida
from .models import AvisoCliente, EstadoOrden, MedioAviso, OrdenServicio, TipoServicio

logger = logging.getLogger(__name__)

# Campo → largo máximo de los textos del diagnóstico.
TEXTOS = {
    "diagnostico": 2000,
    "trabajos_a_realizar": 2000,
    "nota_interna": 1000,
    "nota_cliente": 1000,
}
HORAS_MAXIMAS = Decimal("999.9")
AVISO_MINIMO = 3
AVISO_MAXIMO = 500


def _orden_abierta(orden: OrdenServicio) -> OrdenServicio:
    """La orden bloqueada y al día; las ya entregadas no se tocan."""
    actual = OrdenServicio.objects.select_for_update().get(pk=orden.pk)
    if actual.estado == EstadoOrden.ENTREGADO:
        raise OrdenInvalida("La orden ya está entregada y cerrada.")
    return actual


def _texto(valor, maximo: int) -> str:
    # Conserva los saltos de línea de un diagnóstico, pero no los espacios de sobra.
    lineas = [" ".join(linea.split()) for linea in str(valor or "").strip().splitlines()]
    return "\n".join(lineas)[:maximo]


def _horas(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        horas = Decimal(str(valor))
    except InvalidOperation:
        raise OrdenInvalida("Las horas estimadas no son un número válido.") from None
    if not horas.is_finite() or horas < 0 or horas > HORAS_MAXIMAS:
        raise OrdenInvalida("Las horas estimadas van de 0 a 999.9.")
    if horas != horas.quantize(Decimal("0.1")):
        raise OrdenInvalida("Las horas estimadas admiten un decimal (por ejemplo 1.5).")
    return horas


@transaction.atomic
def registrar_diagnostico(
    orden: OrdenServicio, *, tipo_servicio: TipoServicio | None = None, **cambios
) -> OrdenServicio:
    """Guarda lo que el técnico concluye. Solo cambia lo que viene en ``cambios``.

    Admite ``diagnostico``, ``trabajos_a_realizar``, ``horas_estimadas``, ``nota_interna`` y
    ``nota_cliente``; ``tipo_servicio`` (el objeto, ya validado contra la organización).
    """
    desconocidos = set(cambios) - {*TEXTOS, "horas_estimadas"}
    if desconocidos:
        raise OrdenInvalida(f"Dato no válido: {', '.join(sorted(desconocidos))}.")
    actual = _orden_abierta(orden)
    modificados: list[str] = []
    for campo, maximo in TEXTOS.items():
        if campo in cambios:
            nuevo = _texto(cambios[campo], maximo)
            if nuevo != getattr(actual, campo):
                setattr(actual, campo, nuevo)
                modificados.append(campo)
    if "horas_estimadas" in cambios:
        horas = _horas(cambios["horas_estimadas"])
        if horas != actual.horas_estimadas:
            actual.horas_estimadas = horas
            modificados.append("horas_estimadas")
    if tipo_servicio is not None and tipo_servicio.pk != actual.tipo_servicio_id:
        if (
            tipo_servicio.organizacion_id != actual.empresa.organizacion_id
            or tipo_servicio.estado != EstadoRegistro.ACTIVO
        ):
            raise OrdenInvalida("El tipo de servicio no está disponible.")
        actual.tipo_servicio = tipo_servicio
        modificados.append("tipo_servicio")
    if modificados:
        actual.save(update_fields=modificados)
        # La auditoría dice qué cambió, no el texto del diagnóstico.
        registrar(
            "servicio_tecnico.diagnostico_guardado",
            recurso_tipo="orden_servicio",
            recurso_id=actual.pk,
            empresa_id=actual.empresa_id,
            resumen=f"{actual.codigo}: diagnóstico actualizado",
            detalle={"campos": modificados},
        )
    return actual


@transaction.atomic
def asignar_tecnico(orden: OrdenServicio, tecnico: Personal | None) -> OrdenServicio:
    """Asigna (o quita) el técnico de la orden. Debe ser personal técnico activo de la empresa."""
    actual = _orden_abierta(orden)
    if tecnico is not None and (
        tecnico.empresa_id != actual.empresa_id
        or tecnico.area != Area.TECNICO
        or tecnico.estado != EstadoRegistro.ACTIVO
    ):
        raise OrdenInvalida("El técnico debe ser personal técnico activo de esta empresa.")
    anterior = actual.tecnico_id
    if anterior == getattr(tecnico, "pk", None):
        return actual
    actual.tecnico = tecnico
    actual.save(update_fields=["tecnico"])
    registrar(
        "servicio_tecnico.tecnico_asignado",
        recurso_tipo="orden_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo}: "
        + (f"asignada a {tecnico.nombre_completo}" if tecnico else "sin técnico"),
        detalle={"antes": anterior, "despues": getattr(tecnico, "pk", None)},
    )
    return actual


@transaction.atomic
def registrar_aviso(orden: OrdenServicio, *, medio: str, mensaje: str) -> AvisoCliente:
    """Deja constancia de que se avisó al cliente (quién lo hizo queda en la huella)."""
    actual = _orden_abierta(orden)
    if medio not in MedioAviso.values:
        raise OrdenInvalida("El medio del aviso no es válido.")
    texto = _texto(mensaje, AVISO_MAXIMO)
    if len(texto) < AVISO_MINIMO:
        raise OrdenInvalida("Escriba qué se le dijo al cliente.")
    aviso = AvisoCliente.objects.create(
        empresa_id=actual.empresa_id, orden=actual, medio=medio, mensaje=texto
    )
    registrar(
        "servicio_tecnico.cliente_avisado",
        recurso_tipo="orden_servicio",
        recurso_id=actual.pk,
        empresa_id=actual.empresa_id,
        resumen=f"{actual.codigo}: cliente avisado por {aviso.get_medio_display()}",
    )
    return aviso
