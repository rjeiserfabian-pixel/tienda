"""El JSON que se arma para la API: factura, boleta, nota de crédito y guía de remisión."""

from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from apps.facturacion import constructores, servicios
from apps.facturacion.constructores import OCULTO
from apps.facturacion.exceptions import DocumentoNoEnviable
from apps.facturacion.models import OrigenDocumento
from apps.organizacion.models import ConfiguracionEmpresa

from .conftest import GRE_ID, GRE_SECRETO, SOL_CLAVE, SOL_USUARIO

pytestmark = pytest.mark.django_db


def armar(origen, doc, *, credenciales=True):
    return servicios.armar(origen, doc, credenciales=credenciales, exigir_activo=False)[1]


class TestFactura:
    def test_arma_el_json_con_la_forma_de_la_api(self, fe):
        comp = fe.factura(2)
        j = armar(OrigenDocumento.COMPROBANTE, comp)
        assert j["empresa"]["ruc"] == fe.empresa.ruc and j["empresa"]["modo"] == 0
        assert j["empresa"]["usu_secundario_produccion_user"] == SOL_USUARIO
        assert j["empresa"]["usu_secundario_produccion_password"] == SOL_CLAVE
        assert (j["empresa"]["ubigeo"], j["empresa"]["distrito"]) == ("220901", "Tarapoto")
        assert j["cliente"]["codigo_tipo_entidad"] == "6"
        venta = j["venta"]
        assert (venta["tipo_documento_codigo"], venta["serie"], venta["numero"]) == (
            "01",
            "F001",
            "00000001",
        )
        assert (venta["moneda_id"], venta["forma_pago_id"]) == (1, 1)
        assert (venta["total_gravada"], venta["total_igv"]) == (200.0, 36.0)
        assert venta["total_exonerada"] is None and venta["total_inafecta"] is None
        assert venta["fecha_emision"] == comp.fecha.isoformat()
        assert len(venta["hora_emision"]) == 8 and venta["hora_emision"].count(":") == 2
        (item,) = j["items"]
        assert item["producto"] == "Mouse inalámbrico"
        assert (item["cantidad"], item["precio_base"], item["tipo_igv_codigo"]) == (
            2.0,
            100.0,
            "10",
        )
        assert item["codigo_sunat"] == "43211503"  # el de la configuración: el producto no tiene
        assert item["codigo_unidad"] == "BG"
        assert (j["cuotas"], j["guias_adjuntas"], j["anticipos"]) == ([], [], [])

    def test_el_codigo_sunat_del_producto_manda_sobre_el_por_defecto(self, fe):
        fe.producto.codigo_sunat = "43211706"
        fe.producto.save()
        j = armar(OrigenDocumento.COMPROBANTE, fe.factura())
        assert j["items"][0]["codigo_sunat"] == "43211706"

    def test_sin_ningun_codigo_sunat_no_se_envia_y_dice_cual_producto(self, fe):
        fe.config.codigo_sunat_defecto = ""
        fe.config.save()
        with pytest.raises(DocumentoNoEnviable, match="Mouse inalámbrico"):
            armar(OrigenDocumento.COMPROBANTE, fe.factura())

    def test_en_la_vista_previa_las_claves_salen_ocultas(self, fe):
        j = armar(OrigenDocumento.COMPROBANTE, fe.factura(), credenciales=False)
        assert j["empresa"]["usu_secundario_produccion_user"] == OCULTO
        assert j["empresa"]["usu_secundario_produccion_password"] == OCULTO
        assert SOL_CLAVE not in str(j) and SOL_USUARIO not in str(j)

    def test_una_factura_necesita_cliente_con_ruc(self):
        # Ventas ya no deja vender una factura sin RUC; esta es la segunda barrera, por si acaso.
        venta = SimpleNamespace(
            cliente_tipo_documento="DNI",
            cliente_documento="45871236",
            cliente_nombre="Ana Ruiz",
            cliente_id=None,
            cliente=None,
            moneda="PEN",
        )
        with pytest.raises(DocumentoNoEnviable, match="RUC"):
            constructores._exigir_cliente("01", venta, D("118"))

    def test_una_venta_a_credito_todavia_no_se_envia(self, fe):
        tienda = fe.tienda
        producto = tienda.producto(
            "Teclado", costo="50", precios={"PUBLICO": "100", "CREDITO": "100"}
        )
        venta = tienda.credito([tienda.linea(producto, 1)], tipo_comprobante="01")
        with pytest.raises(DocumentoNoEnviable, match="crédito"):
            armar(OrigenDocumento.COMPROBANTE, venta.comprobantes.get())


class TestBoleta:
    def test_sin_cliente_va_como_clientes_varios(self, fe):
        tienda = fe.tienda
        venta = tienda.vender(
            [tienda.linea(fe.producto, 1)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            tipo_comprobante="03",
        )
        j = armar(OrigenDocumento.COMPROBANTE, venta.comprobantes.get())
        assert j["venta"]["tipo_documento_codigo"] == "03" and j["venta"]["serie"] == "B001"
        assert j["cliente"] == {
            "codigo_tipo_entidad": "0",
            "numero_documento": "00000000",
            "razon_social_nombres": "CLIENTES VARIOS",
            "cliente_direccion": "-",
        }

    def test_una_boleta_de_mas_de_700_pide_el_documento_del_cliente(self):
        # Ventas ya lo exige al vender; esta es la segunda barrera.
        varios = SimpleNamespace(
            cliente_tipo_documento="",
            cliente_documento="",
            cliente_nombre="",
            cliente_id=None,
            cliente=None,
            moneda="PEN",
        )
        with pytest.raises(DocumentoNoEnviable, match="700"):
            constructores._exigir_cliente("03", varios, D("700.01"))
        constructores._exigir_cliente("03", varios, D("700.00"))  # justo 700: se permite

    def test_con_dni_el_cliente_va_identificado(self, fe):
        tienda = fe.tienda
        venta = tienda.vender(
            [tienda.linea(fe.producto, 6)],
            [tienda.cobro(tienda.efectivo, "708.00")],
            tipo_comprobante="03",
            cliente=tienda.cliente(numero="75733846", tipo="DNI", nombre="x"),
        )
        j = armar(OrigenDocumento.COMPROBANTE, venta.comprobantes.get())
        assert (j["cliente"]["codigo_tipo_entidad"], j["cliente"]["numero_documento"]) == (
            "1",
            "75733846",
        )


class TestNotaDeCredito:
    def test_lleva_el_comprobante_que_corrige_y_el_motivo(self, fe):
        comp = fe.factura(2)
        nota = fe.nota_credito(comp, 1)
        j = armar(OrigenDocumento.NOTA_CREDITO, nota)
        v = j["venta"]
        assert (v["tipo_documento_codigo"], v["serie"], v["numero"]) == ("07", "FC01", "00000001")
        assert (v["relacionado_serie"], v["relacionado_numero"]) == ("F001", "00000001")
        assert (v["relacionado_tipo_documento"], v["relacionado_motivo_codigo"]) == ("01", "07")
        assert (v["total_gravada"], v["total_igv"]) == (100.0, 18.0)
        (item,) = j["items"]
        assert (item["cantidad"], item["precio_base"]) == (1.0, 100.0)  # lo devuelto, no lo vendido


class TestGuia:
    def test_transporte_privado_con_vehiculo_y_conductor(self, fe):
        guia = fe.guia(fe.factura(2))
        j = armar(OrigenDocumento.GUIA, guia)
        assert j["empresa"]["modo"] == "0"  # la guía lo recibe como texto
        assert j["empresa"]["gre_client_id"] == GRE_ID
        assert j["empresa"]["gre_client_secret"] == GRE_SECRETO
        assert "cuenta_detraccion" not in j["empresa"]
        assert j["remitente"] == {
            "codigo_tipo_entidad": "6",
            "numero_documento": fe.empresa.ruc,
            "razon_social_nombres": fe.empresa.razon_social,
        }
        g = j["guia"]
        assert (g["tipo_documento_codigo"], g["serie"], g["numero"]) == ("09", "T001", "00000001")
        assert (g["motivo_traslado_codigo"], g["transporte_publico"]) == ("01", False)
        assert (g["unidad_peso"], g["cantidad_bultos"]) == ("KGM", 1)
        assert g["fecha_inicio_traslado"] == g["fecha_entrega_bienes_transportista"]
        assert (g["ubigeo_partida"], g["ubigeo_llegada"]) == ("220901", "220901")
        assert j["transportista"] == {}
        assert j["vehiculos"] == [{"placa": "ABC123", "principal": True}]  # sin guion
        assert j["conductores"] == [
            {
                "tipo_documento": "1",
                "numero_documento": "",
                "nombres": "Jeiser Fabian",
                "apellidos": "Rojas Diaz",
                "licencia": "Q12345678",
                "principal": True,
            }
        ]
        assert j["documentos_relacionados"] == [
            {
                "tipo_documento": "01",
                "serie": "F001",
                "numero": "00000001",
                "ruc_emisor": fe.empresa.ruc,
            }
        ]
        assert j["items"][0]["codigo_unidad"] == "BG" and j["items"][0]["cantidad"] == 1.0
        assert j["evento"] == {}

    def test_en_vehiculo_liviano_no_van_vehiculo_ni_conductor(self, fe):
        guia = fe.guia(fe.factura(2), traslado_m1_l=True, placa="", conductor_nombre="")
        j = armar(OrigenDocumento.GUIA, guia)
        assert (j["vehiculos"], j["conductores"]) == ([], [])

    def test_el_transporte_publico_todavia_no_se_envia(self, fe):
        tienda = fe.tienda
        guia = fe.guia(
            fe.factura(2),
            modalidad="01",
            transportista_nombre="Transportes Selva SAC",
            transportista_documento="20100000017",
            placa="",
            conductor_nombre="",
        )
        with pytest.raises(DocumentoNoEnviable, match="transporte público"):
            armar(OrigenDocumento.GUIA, guia)
        assert tienda  # (la guía sí existe: solo el envío no está definido)


class TestEmpresa:
    def test_modo_produccion_es_1(self, fe):
        fe.config.modo_sunat = ConfiguracionEmpresa.ModoSunat.PRODUCCION
        fe.config.save()
        assert constructores.bloque_empresa(fe.empresa, fe.config, credenciales=False)["modo"] == 1

    def test_lo_que_falta_se_dice_con_nombre(self, fe):
        assert constructores.faltantes(fe.empresa, fe.config, guia=True) == []
        fe.config.sunat_gre_client_secret = ""
        fe.config.ubigeo_fiscal = ""
        fe.config.save()
        falta = constructores.faltantes(fe.empresa, fe.config, guia=True)
        assert "Client secret de la guía de remisión" in falta
        assert "Ubigeo del domicilio fiscal" in falta
        assert constructores.faltantes(fe.empresa, None) == ["Configuración de la empresa"]

    def test_un_ubigeo_que_no_existe_cuenta_como_falta(self, fe):
        fe.config.ubigeo_fiscal = "999999"
        fe.config.save()
        assert any("no existe" in f for f in constructores.faltantes(fe.empresa, fe.config))

    def test_partir_el_nombre_del_conductor(self):
        assert constructores._partir_nombre("Luis Soto") == ("Luis", "Soto")
        assert constructores._partir_nombre("Juan Perez Garcia") == ("Juan", "Perez Garcia")
        assert constructores._partir_nombre("Jeiser Fabian Rojas Diaz") == (
            "Jeiser Fabian",
            "Rojas Diaz",
        )
        assert constructores._partir_nombre("") == ("", "")
        assert D("1")  # (nada más que comprobar)
