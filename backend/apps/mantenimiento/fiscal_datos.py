"""Datos iniciales de los catálogos fiscales (tablas de SUNAT) que se cargan en cada organización.

Se cargan solos al crear la organización y con ``sync_permisos``; nunca pisan lo que el
administrador ya cambió (solo se agrega lo que falta). Los códigos son los de SUNAT.
"""

from datetime import date

# Tabla 10 de SUNAT: (código, nombre, abreviatura, electrónico, compras, ventas, lleva IGV, serie)
# La serie es una expresión regular; vacía = libre (comprobantes físicos o de otros emisores).
TIPOS_COMPROBANTE = (
    ("01", "Factura", "FAC", True, True, True, True, r"[FE][A-Z0-9]{3}|[0-9]{1,4}"),
    (
        "03",
        "Boleta de venta",
        "BOL",
        True,
        True,
        True,
        True,
        r"B[A-Z0-9]{3}|EB[A-Z0-9]{2}|[0-9]{1,4}",
    ),
    ("07", "Nota de crédito", "NCR", True, True, True, True, r"[FBE][A-Z0-9]{3}|[0-9]{1,4}"),
    ("08", "Nota de débito", "NDB", True, True, True, True, r"[FBE][A-Z0-9]{3}|[0-9]{1,4}"),
    ("02", "Recibo por honorarios", "RHE", True, True, False, False, ""),
    ("04", "Liquidación de compra", "LIQ", True, True, False, True, ""),
    ("09", "Guía de remisión - remitente", "GRR", True, True, True, False, ""),
    ("12", "Ticket o cinta de máquina registradora", "TKT", False, True, False, True, ""),
    ("14", "Recibo de servicios públicos", "RSP", False, True, False, True, ""),
    ("31", "Guía de remisión - transportista", "GRT", True, True, False, False, ""),
    ("50", "Declaración Aduanera de Mercancías (DAM)", "DAM", False, True, False, True, ""),
    ("00", "Otros", "OTR", False, True, True, False, ""),
    # Comprobante interno de venta, antes de la facturación electrónica: no es de SUNAT.
    ("NV", "Nota de venta", "NVT", False, False, True, True, ""),
    # Recibo que se entrega al cobrar cuotas de una venta a crédito: interno, sin IGV.
    ("RI", "Recibo de cobranza", "REC", False, False, True, False, ""),
    # Cotización: interna, sin IGV propio. Cada empresa (y sucursal) numera sus proformas.
    ("PF", "Proforma", "PRF", False, False, True, False, ""),
)

# Un ejemplo legible de serie por tipo, para mostrarlo en vez de la regla técnica.
EJEMPLOS_SERIE = {
    "01": "F001",
    "03": "B001",
    "07": "FC01",
    "08": "FD01",
}

# Catálogo 07 de SUNAT (tipo de afectación del IGV):
# (código, nombre, grupo, impuesto, gratuita, aplica en compras, aplica en ventas)
# En compras se ofrecen gravado, exonerado, inafecto e IVAP; el resto es de ventas.
AFECTACIONES_IGV = (
    ("10", "Gravado - Operación Onerosa", "GRAVADO", "IGV", False, True, True),
    ("11", "Gravado - Retiro por premio", "GRAVADO", "IGV", True, False, True),
    ("12", "Gravado - Retiro por donación", "GRAVADO", "IGV", True, False, True),
    ("13", "Gravado - Retiro", "GRAVADO", "IGV", True, False, True),
    ("14", "Gravado - Retiro por publicidad", "GRAVADO", "IGV", True, False, True),
    ("15", "Gravado - Bonificaciones", "GRAVADO", "IGV", True, False, True),
    ("16", "Gravado - Retiro por entrega a trabajadores", "GRAVADO", "IGV", True, False, True),
    ("17", "Gravado - IVAP", "GRAVADO", "IVAP", False, True, True),
    ("20", "Exonerado - Operación Onerosa", "EXONERADO", "NINGUNO", False, True, True),
    ("21", "Exonerado - Transferencia gratuita", "EXONERADO", "NINGUNO", True, False, True),
    ("30", "Inafecto - Operación Onerosa", "INAFECTO", "NINGUNO", False, True, True),
    ("31", "Inafecto - Retiro por bonificación", "INAFECTO", "NINGUNO", True, False, True),
    ("32", "Inafecto - Retiro", "INAFECTO", "NINGUNO", True, False, True),
    ("33", "Inafecto - Retiro por muestras médicas", "INAFECTO", "NINGUNO", True, False, True),
    ("34", "Inafecto - Retiro por convenio colectivo", "INAFECTO", "NINGUNO", True, False, True),
    ("35", "Inafecto - Retiro por premio", "INAFECTO", "NINGUNO", True, False, True),
    ("36", "Inafecto - Retiro por publicidad", "INAFECTO", "NINGUNO", True, False, True),
    ("37", "Inafecto - Transferencia gratuita", "INAFECTO", "NINGUNO", True, False, True),
    ("40", "Exportación de bienes o servicios", "EXPORTACION", "NINGUNO", False, False, True),
)

# Tasa del IGV (16 % de IGV + 2 % de Impuesto de Promoción Municipal), vigente desde marzo de 2011.
# No se carga la tasa del IVAP: no está verificada y debe fijarla el contador (Tasas de impuesto).
TASAS_INICIALES = (("IGV", "18.00", date(2011, 3, 1)),)

CODIGO_GRAVADO = "10"
CODIGO_EXONERADO = "20"
