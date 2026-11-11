"""Conceptos de caja de fábrica y su carga en cada organización.

Se cargan al crear la organización y con ``sync_permisos``. Lo ya editado no se pisa y lo que la
organización eliminó no se vuelve a crear. Los ``automatico`` los usa el sistema por su cuenta.
"""

import logging

from django.db import transaction

from .models import ConceptoCaja

logger = logging.getLogger(__name__)

INGRESO = ConceptoCaja.Tipo.INGRESO
EGRESO = ConceptoCaja.Tipo.EGRESO

# Códigos que el sistema usa directamente (compras, ventas, transferencias, arqueos).
PAGO_PROVEEDOR = "PAGO_PROVEEDOR"
COBRO_VENTA = "COBRO_VENTA"
PAGO_GASTO = "PAGO_GASTO"
TRANSFERENCIA_ENTRADA = "TRANSFERENCIA_ENTRADA"
TRANSFERENCIA_SALIDA = "TRANSFERENCIA_SALIDA"
SOBRANTE_CAJA = "SOBRANTE_CAJA"
FALTANTE_CAJA = "FALTANTE_CAJA"

# (código, nombre, tipo, lo usa el sistema por su cuenta)
CONCEPTOS = (
    (PAGO_PROVEEDOR, "Pago a proveedor", EGRESO, True),
    (PAGO_GASTO, "Pago de gasto", EGRESO, True),
    (COBRO_VENTA, "Cobro de venta", INGRESO, True),
    ("DEVOLUCION_VENTA", "Devolución a un cliente", EGRESO, True),
    ("DEVOLUCION_COMPRA", "Devolución de un proveedor", INGRESO, True),
    ("ANTICIPO_PROVEEDOR", "Anticipo a proveedor", EGRESO, True),
    ("DEVOLUCION_ANTICIPO", "Devolución de un anticipo", INGRESO, True),
    ("ADELANTO_SERVICIO", "Adelanto de servicio técnico", INGRESO, True),
    ("DEVOLUCION_ADELANTO", "Devolución de adelanto", EGRESO, True),
    ("ADELANTO_PERSONAL", "Adelanto o préstamo a un trabajador", EGRESO, True),
    ("PAGO_PLANILLA", "Pago de sueldos (planilla)", EGRESO, True),
    ("DEPOSITO_CTS", "Depósito de CTS", EGRESO, True),
    (TRANSFERENCIA_SALIDA, "Transferencia enviada", EGRESO, True),
    (TRANSFERENCIA_ENTRADA, "Transferencia recibida", INGRESO, True),
    (FALTANTE_CAJA, "Faltante de caja", EGRESO, True),
    (SOBRANTE_CAJA, "Sobrante de caja", INGRESO, True),
    ("GASTOS_VARIOS", "Gastos varios", EGRESO, False),
    ("COMISION_BANCARIA", "Comisión bancaria", EGRESO, False),
    ("ITF", "ITF (impuesto a las transacciones financieras)", EGRESO, False),
    ("PAGO_PRESTAMO", "Pago de préstamo", EGRESO, False),
    ("RETIRO_DUENO", "Retiro del dueño", EGRESO, False),
    ("OTROS_EGRESOS", "Otros egresos", EGRESO, False),
    ("DEPOSITO_RECIBIDO", "Depósito recibido", INGRESO, False),
    ("INTERESES", "Intereses ganados", INGRESO, False),
    ("APORTE_CAPITAL", "Aporte de capital", INGRESO, False),
    ("PRESTAMO_RECIBIDO", "Préstamo recibido", INGRESO, False),
    ("OTROS_INGRESOS", "Otros ingresos", INGRESO, False),
)


def concepto_de_sistema(organizacion_id: int, codigo: str) -> ConceptoCaja:
    """El concepto de fábrica con ese código (``ConceptoCaja.DoesNotExist`` si no se ha cargado)."""
    return ConceptoCaja.objects.sin_ambito().get(organizacion_id=organizacion_id, codigo=codigo)


def asegurar_concepto(organizacion_id: int, codigo: str) -> ConceptoCaja:
    """El concepto de fábrica con ese código; si no está (nunca se cargó o se eliminó), se crea."""
    try:
        return concepto_de_sistema(organizacion_id, codigo)
    except ConceptoCaja.DoesNotExist:
        pass
    datos = {c[0]: c for c in CONCEPTOS}.get(codigo)
    if datos is None:
        raise ConceptoCaja.DoesNotExist(f"No existe el concepto de fábrica {codigo}.")
    _, nombre, tipo, automatico = datos
    sembrar_conceptos_caja(organizacion_id)
    try:
        return concepto_de_sistema(organizacion_id, codigo)
    except ConceptoCaja.DoesNotExist:
        # La organización lo había eliminado: se vuelve a crear porque el sistema lo necesita.
        existente = ConceptoCaja.objects.sin_ambito().filter(
            organizacion_id=organizacion_id, tipo=tipo, nombre__iexact=nombre
        )
        if existente.exists():
            concepto = existente.first()
            concepto.codigo = codigo
            concepto.save(update_fields=["codigo"])
            return concepto
        return ConceptoCaja.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            nombre=nombre,
            tipo=tipo,
            codigo=codigo,
            automatico=automatico,
        )


@transaction.atomic
def sembrar_conceptos_caja(organizacion_id: int) -> dict[str, int]:
    """Agrega lo que falte; no cambia lo editado ni vuelve a crear lo que se eliminó."""
    existentes = ConceptoCaja.objects.sin_ambito(incluir_eliminados=True).filter(
        organizacion_id=organizacion_id
    )
    por_codigo = {c.codigo for c in existentes if c.codigo}
    por_nombre = {(c.tipo, c.nombre.lower()): c for c in existentes}
    creados = 0
    for codigo, nombre, tipo, automatico in CONCEPTOS:
        if codigo in por_codigo:
            continue
        previo = por_nombre.get((tipo, nombre.lower()))
        if previo is not None:
            # La organización ya tenía uno con ese nombre: si el sistema lo necesita, lo adopta.
            if automatico and previo.eliminado_en is None:
                previo.codigo, previo.automatico = codigo, True
                previo.save(update_fields=["codigo", "automatico"])
            continue
        ConceptoCaja.objects.sin_ambito().create(
            organizacion_id=organizacion_id,
            nombre=nombre,
            tipo=tipo,
            codigo=codigo,
            automatico=automatico,
        )
        creados += 1
    if creados:
        logger.info("conceptos_caja_sembrados", extra={"organizacion_id": organizacion_id})
    return {"conceptos_caja": creados}
