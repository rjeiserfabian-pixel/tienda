"""Lectura de la factura electrónica del proveedor (XML UBL 2.1 de SUNAT) para precargar la compra.

Solo se LEE: no se guarda el archivo ni se registra nada. El XML viene de afuera, así que se
analiza con ``defusedxml`` (sin DTD ni entidades externas: nada de XXE ni «bombas» de expansión) y
con un tamaño máximo. Lo que no se pueda leer se avisa con un mensaje claro y la compra se registra
a mano como siempre.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from apps.core.exceptions import ErrorDominio

TAMANO_MAXIMO = 2 * 1024 * 1024  # 2 MB: una factura real pesa unos pocos KB
MAX_LINEAS = 200

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

# Código de tributo de SUNAT (Catálogo 05) → a qué total del comprobante corresponde.
TRIBUTOS = {
    "1000": "igv",
    "1016": "ivap",
    "9997": "exonerada",
    "9998": "inafecta",
    "9996": "gratuita",
}
TIPOS_ADMITIDOS = {"01": "Factura", "03": "Boleta de venta"}
MONEDAS = {"PEN", "USD"}


class XmlInvalido(ErrorDominio):
    status_code = 400
    codigo = "xml_invalido"
    mensaje = "El archivo no es una factura electrónica válida."


@dataclass(slots=True)
class LineaXml:
    numero: int
    descripcion: str
    codigo: str
    unidad: str
    cantidad: Decimal
    precio_unitario: Decimal  # valor unitario, SIN IGV
    valor_venta: Decimal
    afectacion: str  # código del Catálogo 07 (10 gravado, 20 exonerado, 30 inafecto…)


@dataclass(slots=True)
class FacturaXml:
    tipo_comprobante: str
    serie: str
    numero: str
    fecha_emision: date
    moneda: str
    proveedor_tipo_documento: str
    proveedor_documento: str
    proveedor_nombre: str
    receptor_documento: str
    forma_pago: str  # CONTADO | CREDITO
    cuotas: list[dict] = field(default_factory=list)
    lineas: list[LineaXml] = field(default_factory=list)
    totales: dict = field(default_factory=dict)


def _t(nodo, ruta: str) -> str:
    """Texto del primer elemento en ``ruta`` (vacío si no existe)."""
    encontrado = nodo.find(ruta, NS) if nodo is not None else None
    return (encontrado.text or "").strip() if encontrado is not None else ""


def _dec(texto: str, campo: str) -> Decimal:
    try:
        valor = Decimal(texto)
    except (InvalidOperation, ValueError):
        raise XmlInvalido(f"El XML trae un importe no válido en «{campo}».") from None
    if not valor.is_finite():
        raise XmlInvalido(f"El XML trae un importe no válido en «{campo}».")
    return valor


def _fecha(texto: str) -> date:
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        raise XmlInvalido("La fecha de emisión del XML no es válida.") from None


def _tipo_documento(codigo: str) -> str:
    """Catálogo 06 de SUNAT: 6 = RUC, 1 = DNI, 4 = carnet de extranjería, 7 = pasaporte."""
    return {"6": "RUC", "1": "DNI", "4": "CE", "7": "PASAPORTE"}.get(codigo, "RUC")


def _parte(parte) -> tuple[str, str, str]:
    """``(tipo de documento, número, nombre)`` de un participante (proveedor o cliente)."""
    identificacion = (
        parte.find("cac:Party/cac:PartyIdentification/cbc:ID", NS) if parte is not None else None
    )
    numero = (identificacion.text or "").strip() if identificacion is not None else ""
    tipo = _tipo_documento(
        identificacion.get("schemeID", "6") if identificacion is not None else "6"
    )
    nombre = _t(parte, "cac:Party/cac:PartyLegalEntity/cbc:RegistrationName") or _t(
        parte, "cac:Party/cac:PartyName/cbc:Name"
    )
    return tipo, numero, nombre


def _forma_pago(raiz) -> tuple[str, list[dict]]:
    forma, cuotas = "CONTADO", []
    for termino in raiz.findall("cac:PaymentTerms", NS):
        medio = _t(termino, "cbc:PaymentMeansID")
        if medio.lower() == "credito":
            forma = "CREDITO"
        elif medio.lower().startswith("cuota"):
            cuotas.append(
                {
                    "fecha_vencimiento": _fecha(_t(termino, "cbc:PaymentDueDate")),
                    "monto": _dec(_t(termino, "cbc:Amount") or "0", "cuota"),
                }
            )
    return forma, (cuotas if forma == "CREDITO" else [])


def _linea(nodo, posicion: int) -> LineaXml:
    cantidad = _dec(_t(nodo, "cbc:InvoicedQuantity") or "0", "cantidad")
    cantidad_nodo = nodo.find("cbc:InvoicedQuantity", NS)
    precio = _dec(_t(nodo, "cac:Price/cbc:PriceAmount") or "0", "precio")
    afectacion = ""
    for subtotal in nodo.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        tributo = _t(subtotal, "cac:TaxCategory/cac:TaxScheme/cbc:ID")
        if tributo in ("1000", "1016", "9997", "9998", "9996"):
            afectacion = _t(subtotal, "cac:TaxCategory/cbc:TaxExemptionReasonCode")
            break
    return LineaXml(
        numero=posicion,
        descripcion=" ".join(_t(nodo, "cac:Item/cbc:Description").split())[:250],
        codigo=_t(nodo, "cac:Item/cac:SellersItemIdentification/cbc:ID")[:60],
        unidad=(cantidad_nodo.get("unitCode", "") if cantidad_nodo is not None else "")[:10],
        cantidad=cantidad,
        precio_unitario=precio,
        valor_venta=_dec(_t(nodo, "cbc:LineExtensionAmount") or "0", "valor de la línea"),
        afectacion=afectacion,
    )


def _totales(raiz) -> dict:
    totales = {
        "gravada": Decimal(0),
        "igv": Decimal(0),
        "exonerada": Decimal(0),
        "inafecta": Decimal(0),
        "ivap": Decimal(0),
    }
    for subtotal in raiz.findall("cac:TaxTotal/cac:TaxSubtotal", NS):
        tributo = TRIBUTOS.get(_t(subtotal, "cac:TaxCategory/cac:TaxScheme/cbc:ID"))
        base = _dec(_t(subtotal, "cbc:TaxableAmount") or "0", "base imponible")
        monto = _dec(_t(subtotal, "cbc:TaxAmount") or "0", "impuesto")
        if tributo == "igv":
            totales["gravada"] += base
            totales["igv"] += monto
        elif tributo == "ivap":
            totales["ivap"] += monto
        elif tributo in ("exonerada", "inafecta"):
            totales[tributo] += base
    totales["total"] = _dec(
        _t(raiz, "cac:LegalMonetaryTotal/cbc:PayableAmount")
        or _t(raiz, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")
        or "0",
        "importe total",
    )
    return totales


def leer_factura(contenido: bytes) -> FacturaXml:
    """Lee una factura o boleta electrónica (UBL 2.1). Lanza ``XmlInvalido`` si no se puede."""
    if not contenido:
        raise XmlInvalido("El archivo está vacío.")
    if len(contenido) > TAMANO_MAXIMO:
        raise XmlInvalido("El archivo es demasiado grande para ser una factura.")
    try:
        raiz = ElementTree.fromstring(
            contenido, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (ElementTree.ParseError, DefusedXmlException, UnicodeDecodeError, ValueError):
        raise XmlInvalido(
            "El archivo no es un XML válido (o trae contenido no permitido)."
        ) from None
    if raiz.tag != f"{{{NS['inv']}}}Invoice":
        raise XmlInvalido("El XML no es una factura o boleta electrónica (se esperaba «Invoice»).")

    tipo = _t(raiz, "cbc:InvoiceTypeCode")
    if tipo not in TIPOS_ADMITIDOS:
        raise XmlInvalido(
            "Solo se leen facturas (01) y boletas (03). Otras notas se registran a mano."
        )
    identificador = _t(raiz, "cbc:ID")
    coincidencia = re.fullmatch(r"([A-Za-z0-9]{1,10})-0*(\d{1,20})", identificador)
    if coincidencia is None:
        raise XmlInvalido("No se pudo leer la serie y el número del comprobante.")
    moneda = _t(raiz, "cbc:DocumentCurrencyCode") or "PEN"
    if moneda not in MONEDAS:
        raise XmlInvalido(f"La moneda {moneda} no se admite (solo soles o dólares).")
    tipo_doc, documento, nombre = _parte(raiz.find("cac:AccountingSupplierParty", NS))
    if not documento:
        raise XmlInvalido("El XML no trae el documento del proveedor.")
    lineas_xml = raiz.findall("cac:InvoiceLine", NS)
    if not lineas_xml:
        raise XmlInvalido("El XML no trae productos.")
    if len(lineas_xml) > MAX_LINEAS:
        raise XmlInvalido(f"El XML trae más de {MAX_LINEAS} productos.")
    forma, cuotas = _forma_pago(raiz)
    return FacturaXml(
        tipo_comprobante=tipo,
        serie=coincidencia.group(1).upper(),
        numero=coincidencia.group(2),
        fecha_emision=_fecha(_t(raiz, "cbc:IssueDate")),
        moneda=moneda,
        proveedor_tipo_documento=tipo_doc,
        proveedor_documento=documento,
        proveedor_nombre=nombre,
        receptor_documento=_parte(raiz.find("cac:AccountingCustomerParty", NS))[1],
        forma_pago=forma,
        cuotas=cuotas,
        lineas=[_linea(nodo, i) for i, nodo in enumerate(lineas_xml, start=1)],
        totales=_totales(raiz),
    )
