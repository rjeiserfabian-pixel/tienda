# ruff: noqa: E501, F811  (XML de prueba en una línea; fixtures importadas de test_api)
"""Lectura de la factura XML del proveedor: el lector y el endpoint."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.compras.xml_proveedor import TAMANO_MAXIMO, XmlInvalido, leer_factura
from apps.mantenimiento.models import Proveedor
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

from .test_api import BASE, cuerpo, datos, registrar  # noqa: F401

pytestmark = pytest.mark.django_db

CABECERA = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
 xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
 xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">"""


def factura(
    *,
    ruc="20100000046",
    receptor="20100000001",
    tipo="01",
    identificador="F001-00001234",
    fecha="2026-10-20",
    moneda="PEN",
    pago="",
    lineas=None,
    total="118.00",
):
    lineas = lineas or [
        {
            "codigo": "ABC-1",
            "descripcion": "Mouse   inalámbrico",
            "cantidad": "2.00",
            "precio": "50.000000",
            "valor": "100.00",
            "afectacion": "10",
            "tributo": "1000",
        }
    ]
    xml_lineas = "".join(
        f"""<cac:InvoiceLine><cbc:ID>{i}</cbc:ID>
  <cbc:InvoicedQuantity unitCode="NIU">{ln["cantidad"]}</cbc:InvoicedQuantity>
  <cbc:LineExtensionAmount currencyID="{moneda}">{ln["valor"]}</cbc:LineExtensionAmount>
  <cac:TaxTotal><cbc:TaxAmount>0</cbc:TaxAmount><cac:TaxSubtotal><cbc:TaxableAmount>{ln["valor"]}</cbc:TaxableAmount><cbc:TaxAmount>0</cbc:TaxAmount>
   <cac:TaxCategory><cbc:TaxExemptionReasonCode>{ln["afectacion"]}</cbc:TaxExemptionReasonCode><cac:TaxScheme><cbc:ID>{ln["tributo"]}</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:Item><cbc:Description>{ln["descripcion"]}</cbc:Description><cac:SellersItemIdentification><cbc:ID>{ln["codigo"]}</cbc:ID></cac:SellersItemIdentification></cac:Item>
  <cac:Price><cbc:PriceAmount>{ln["precio"]}</cbc:PriceAmount></cac:Price></cac:InvoiceLine>"""
        for i, ln in enumerate(lineas, start=1)
    )
    return f"""{CABECERA}
 <cbc:InvoiceTypeCode>{tipo}</cbc:InvoiceTypeCode>
 <cbc:ID>{identificador}</cbc:ID><cbc:IssueDate>{fecha}</cbc:IssueDate>
 <cbc:DocumentCurrencyCode>{moneda}</cbc:DocumentCurrencyCode>
 <cac:AccountingSupplierParty><cac:Party><cac:PartyIdentification><cbc:ID schemeID="6">{ruc}</cbc:ID></cac:PartyIdentification>
  <cac:PartyLegalEntity><cbc:RegistrationName>DISTRIBUIDORA SELVA SAC</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
 <cac:AccountingCustomerParty><cac:Party><cac:PartyIdentification><cbc:ID schemeID="6">{receptor}</cbc:ID></cac:PartyIdentification></cac:Party></cac:AccountingCustomerParty>
 {pago}
 <cac:TaxTotal><cbc:TaxAmount>18.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:TaxableAmount>100.00</cbc:TaxableAmount><cbc:TaxAmount>18.00</cbc:TaxAmount>
  <cac:TaxCategory><cac:TaxScheme><cbc:ID>1000</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
 <cac:LegalMonetaryTotal><cbc:PayableAmount>{total}</cbc:PayableAmount></cac:LegalMonetaryTotal>
 {xml_lineas}
</Invoice>""".encode()


CREDITO = """<cac:PaymentTerms><cbc:ID>FormaPago</cbc:ID><cbc:PaymentMeansID>Credito</cbc:PaymentMeansID><cbc:Amount>118.00</cbc:Amount></cac:PaymentTerms>
<cac:PaymentTerms><cbc:ID>FormaPago</cbc:ID><cbc:PaymentMeansID>Cuota001</cbc:PaymentMeansID><cbc:Amount>59.00</cbc:Amount><cbc:PaymentDueDate>2026-11-20</cbc:PaymentDueDate></cac:PaymentTerms>
<cac:PaymentTerms><cbc:ID>FormaPago</cbc:ID><cbc:PaymentMeansID>Cuota002</cbc:PaymentMeansID><cbc:Amount>59.00</cbc:Amount><cbc:PaymentDueDate>2026-12-20</cbc:PaymentDueDate></cac:PaymentTerms>"""


class TestLector:
    def test_lee_el_comprobante_el_proveedor_y_las_lineas(self):
        f = leer_factura(factura())
        assert (f.tipo_comprobante, f.serie, f.numero) == ("01", "F001", "1234")
        assert (f.fecha_emision.isoformat(), f.moneda, f.forma_pago) == (
            "2026-10-20",
            "PEN",
            "CONTADO",
        )
        assert (f.proveedor_tipo_documento, f.proveedor_documento) == ("RUC", "20100000046")
        assert f.proveedor_nombre == "DISTRIBUIDORA SELVA SAC"
        assert f.receptor_documento == "20100000001"
        ln = f.lineas[0]
        assert (ln.codigo, ln.unidad, ln.cantidad, ln.precio_unitario, ln.afectacion) == (
            "ABC-1",
            "NIU",
            Decimal("2.00"),
            Decimal("50"),
            "10",
        )
        assert ln.descripcion == "Mouse inalámbrico"  # espacios de más fuera
        assert f.totales["total"] == Decimal("118.00") and f.totales["igv"] == Decimal("18.00")

    def test_credito_con_sus_cuotas(self):
        f = leer_factura(factura(pago=CREDITO))
        assert f.forma_pago == "CREDITO"
        assert [(c["fecha_vencimiento"].isoformat(), c["monto"]) for c in f.cuotas] == [
            ("2026-11-20", Decimal("59.00")),
            ("2026-12-20", Decimal("59.00")),
        ]

    def test_exonerado_e_inafecto(self):
        lineas = [
            {
                "codigo": "A",
                "descripcion": "X",
                "cantidad": "1",
                "precio": "10",
                "valor": "10.00",
                "afectacion": "20",
                "tributo": "9997",
            },
            {
                "codigo": "B",
                "descripcion": "Y",
                "cantidad": "1",
                "precio": "5",
                "valor": "5.00",
                "afectacion": "30",
                "tributo": "9998",
            },
        ]
        f = leer_factura(factura(lineas=lineas))
        assert [ln.afectacion for ln in f.lineas] == ["20", "30"]

    @pytest.mark.parametrize(
        "contenido",
        [
            b"",
            b"no es xml",
            b"<a><b></a>",
            b'<?xml version="1.0"?><Otro xmlns="urn:x"/>',
            factura(tipo="07"),
            factura(identificador="SIN-GUION-NUMERO-X"),
            factura(moneda="EUR"),
            factura(fecha="2026-13-45"),
            factura(
                lineas=[
                    {
                        "codigo": "A",
                        "descripcion": "X",
                        "cantidad": "abc",
                        "precio": "1",
                        "valor": "1",
                        "afectacion": "10",
                        "tributo": "1000",
                    }
                ]
            ),
        ],
    )
    def test_archivos_que_no_sirven(self, contenido):
        with pytest.raises(XmlInvalido):
            leer_factura(contenido)

    def test_no_acepta_entidades_ni_dtd(self):
        maligno = b"""<?xml version="1.0"?>
<!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&xxe;</Invoice>"""
        with pytest.raises(XmlInvalido):
            leer_factura(maligno)
        bomba = b"""<?xml version="1.0"?>
<!DOCTYPE b [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>
<b>&b;</b>"""
        with pytest.raises(XmlInvalido):
            leer_factura(bomba)

    def test_tamano_maximo(self):
        with pytest.raises(XmlInvalido, match="grande"):
            leer_factura(b"<a>" + b"x" * TAMANO_MAXIMO + b"</a>")


class TestEndpoint:
    def _leer(self, datos, contenido, usuario="almacenero", empresa=None):
        return cliente_de(usuario).post(
            f"{BASE}/xml/leer/",
            {
                "empresa": empresa or datos.mundo.e1.pk,
                "archivo": SimpleUploadedFile("factura.xml", contenido, content_type="text/xml"),
            },
            format="multipart",
        )

    def _crear_proveedor(self, datos, ruc):
        return Proveedor.objects.sin_ambito().create(
            organizacion=datos.mundo.e.org_a,
            tipo_documento="RUC",
            numero_documento=ruc,
            nombre="Selva SAC",
            ciudad="Tarapoto",
        )

    def test_devuelve_lo_leido_y_las_coincidencias(self, datos):
        ruc = ruc_valido("2010000046")
        self._crear_proveedor(datos, ruc)
        producto = datos.mundo.producto("Mouse inalámbrico", codigo_fabricante="ABC-1")
        r = self._leer(datos, factura(ruc=ruc, receptor=datos.mundo.e1.ruc))
        assert r.status_code == 200, r.content
        d = r.json()
        assert d["comprobante"]["serie"] == "F001" and d["comprobante"]["numero"] == "1234"
        assert d["proveedor"]["existente"]["nombre"] == "Selva SAC"
        assert d["proveedor"]["existente"]["ciudad"] == "Tarapoto"
        assert (
            d["receptor_coincide"] is True and d["tipo_valido"] is True and d["duplicado"] is False
        )
        linea = d["lineas"][0]
        assert (linea["cantidad"], linea["precio_unitario"], linea["afectacion"]) == (
            "2",
            "50",
            "10",
        )
        assert linea["producto"]["id"] == producto.pk
        assert d["totales"]["total"] == "118"

    def test_sin_coincidencias_avisa(self, datos):
        r = self._leer(datos, factura(ruc=ruc_valido("2099999991"), receptor="20555555555"))
        d = r.json()
        assert d["proveedor"]["existente"] is None
        assert d["proveedor"]["numero_documento"] == ruc_valido("2099999991")
        assert d["receptor_coincide"] is False
        assert d["lineas"][0]["producto"] is None

    def test_detecta_un_comprobante_ya_registrado(self, datos):
        ruc = datos.proveedor.numero_documento
        c = cuerpo(datos, comprobante_serie="F001", comprobante_numero="1234")
        assert registrar(cliente_de("almacenero"), c).status_code == 201
        r = self._leer(datos, factura(ruc=ruc))
        assert r.json()["duplicado"] is True

    def test_credito_trae_las_cuotas(self, datos):
        d = self._leer(datos, factura(pago=CREDITO)).json()
        assert d["comprobante"]["forma_pago"] == "CREDITO"
        assert d["comprobante"]["cuotas"] == [
            {"fecha_vencimiento": "2026-11-20", "monto": "59"},
            {"fecha_vencimiento": "2026-12-20", "monto": "59"},
        ]

    def test_errores_claros(self, datos):
        malo = self._leer(datos, b"no es xml")
        assert malo.status_code == 400
        assert malo.json()["error"]["codigo"] == "xml_invalido"
        sin_archivo = cliente_de("almacenero").post(
            f"{BASE}/xml/leer/", {"empresa": datos.mundo.e1.pk}, format="multipart"
        )
        assert sin_archivo.status_code == 400

    def test_solo_quien_puede_registrar_compras(self, datos):
        assert self._leer(datos, factura(), usuario="contador").status_code == 403
        assert self._leer(datos, factura(), usuario="vendedor").status_code == 403
        assert self._leer(datos, factura(), usuario="vendedor_a2").status_code == 403

    def test_no_guarda_nada(self, datos):
        from apps.compras.models import Compra

        self._leer(datos, factura())
        assert Compra.objects.sin_ambito().count() == 0
        assert timezone.localdate() - timedelta(days=0)
