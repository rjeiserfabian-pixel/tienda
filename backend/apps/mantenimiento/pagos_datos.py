"""Datos iniciales de los métodos de pago y las periodicidades de cuotas de cada organización.

Se cargan solos al crear la organización y con ``sync_permisos``. Después la organización los
ajusta a su gusto: lo ya editado no se pisa y lo eliminado no se vuelve a crear.
"""

# (nombre, tipo, pide número de operación)
MEDIOS_DE_PAGO = (
    ("Efectivo", "EFECTIVO", False),
    ("Tarjeta", "TARJETA", True),
    ("Transferencia o depósito", "TRANSFERENCIA", True),
    ("Yape", "BILLETERA", True),
    ("Plin", "BILLETERA", True),
)

# (nombre, unidad, cada cuántas unidades)
PERIODICIDADES = (
    ("Semanal", "DIAS", 7),
    ("Quincenal", "DIAS", 15),
    ("Mensual", "MESES", 1),
)
