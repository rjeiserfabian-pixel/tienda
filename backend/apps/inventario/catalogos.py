"""Catálogo de SUNAT que usan los movimientos de inventario (tabla 12, tipo de operación).

Está en código porque casi no cambia. Los tipos de comprobante (tabla 10) son un catálogo
editable de la organización: ``mantenimiento.TipoComprobante``. Se cargaron los códigos de uso
común; para ampliarlos basta agregar una línea al diccionario (el código SUNAT va como clave).
"""

# Tabla 12: tipo de operación.
TIPOS_OPERACION: dict[str, str] = {
    "01": "Venta",
    "02": "Compra",
    "03": "Consignación recibida",
    "04": "Consignación entregada",
    "05": "Devolución recibida",
    "06": "Devolución entregada",
    "07": "Bonificación",
    "08": "Siniestro",
    "09": "Importación",
    "10": "Exportación",
    "11": "Donación",
    "16": "Saldo inicial",
    "28": "Ajuste por diferencia de inventario",
    "99": "Otros",
}

SALDO_INICIAL = "16"
AJUSTE_INVENTARIO = "28"
OTROS = "99"
