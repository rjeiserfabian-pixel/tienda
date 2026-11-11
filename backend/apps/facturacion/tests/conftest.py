"""Escenario de facturación electrónica: la tienda de Ventas con la empresa A1 ya configurada y una
API de facturación simulada (nada sale a internet en las pruebas)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests

from apps.core.tenant import establecer_contexto
from apps.facturacion import cliente
from apps.organizacion.models import ConfiguracionEmpresa, Empresa
from apps.ventas import guias, notas_credito
from apps.ventas.tests.conftest import (  # noqa: F401
    _aislar_estado_global,
    _auditoria_al_instante,
    api,
    compras,
    conceptos,
    dec,
    entorno,
    mundo,
    nuevo_usuario,
    rbac,
    tienda,
)

D = Decimal
SOL_USUARIO = "SISTEMA2"
SOL_CLAVE = "Clave#Secreta-123"
GRE_ID = "id-de-guia-0000"
GRE_SECRETO = "secreto-de-guia-0000"

# Respuestas con la forma de las reales de la API (recortadas).
ACEPTADA = {
    "data": {
        "error": "false",
        "respuesta_sunat_codigo": "0",
        "respuesta_sunat_descripcion": "La Factura numero F001-00000001, ha sido aceptada",
        "ruta_xml": "http://localhost/API_SUNAT/files/FIRMA/x.xml",
        "ruta_cdr": "http://localhost/API_SUNAT/files/CDR/R-x.xml",
        "codigo_hash": "lWrNCNKcsQ+nmEqDWwkkvZTWUj0=",
        "xml_base_64": "UEsDBAoAAAAI",
        "cdr_base_64": "UEsDBBQAAgAI",
        "respuesta_sunat": {"jwt_payload": {"userdata": {"login": "20614707373SISTEMA2"}}},
    }
}
TICKET = {
    "data": {
        "error": "false",
        "respuesta_sunat_codigo": "TICKET_GENERADO",
        "respuesta_sunat_descripcion": "Documento GRE enviado correctamente.",
        "num_ticket": "f03b2ead-5376-48c3-a09e-cee0d31db682",
        "codigo_hash": "DoFljIwGKE7t5FlRmeXgs/Ou0j0=",
        "xml_base_64": "UEsDBAoAAAAI",
        "respuesta_sunat": {"jwt_payload": {"clientId": "id-interno"}},
    }
}
CON_ERROR = {
    "data": {
        "error": "true",
        "respuesta_sunat_codigo": "2800",
        "respuesta_sunat_descripcion": "El numero de documento del cliente no es valido",
    }
}


class _RespuestaFalsa:
    def __init__(self, cuerpo, estado=200):
        self._cuerpo, self.status_code = cuerpo, estado

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin JSON")
        return self._cuerpo


class ApiFalsa:
    """Guarda lo que se le envía y responde lo que la prueba le diga."""

    def __init__(self):
        self.enviados: list[dict] = []  # (url, json)
        self.cuerpo, self.estado, self.falla = ACEPTADA, 200, None

    def responder(self, cuerpo, estado=200):
        self.cuerpo, self.estado = cuerpo, estado

    def post(self, url, json=None, **kwargs):
        self.enviados.append({"url": url, "json": json, "kwargs": kwargs})
        if self.falla:
            raise self.falla
        return _RespuestaFalsa(self.cuerpo, self.estado)

    def get(self, url, **kwargs):
        if self.falla:
            raise self.falla
        return _RespuestaFalsa(None, 404)


@pytest.fixture
def api_falsa(monkeypatch):
    falsa = ApiFalsa()
    monkeypatch.setattr(cliente.requests, "post", falsa.post)
    monkeypatch.setattr(cliente.requests, "get", falsa.get)
    falsa.error_conexion = requests.ConnectionError("sin red")
    return falsa


@pytest.fixture
def fe(tienda):  # noqa: F811
    """La empresa A1 lista para facturar (beta), con los documentos de ejemplo a mano."""
    a = tienda.a
    Empresa.objects.sin_ambito().filter(pk=a.pk).update(direccion_fiscal="Jr. Leguia 484, Tarapoto")
    a.refresh_from_db()
    config, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=a)
    config.sunat_activo = True
    config.sunat_usuario_sol = SOL_USUARIO
    config.sunat_clave_sol = SOL_CLAVE
    config.sunat_gre_client_id = GRE_ID
    config.sunat_gre_client_secret = GRE_SECRETO
    config.ubigeo_fiscal = "220901"
    config.codigo_sunat_defecto = "43211503"
    config.save()

    producto = tienda.producto("Mouse inalámbrico", costo="50", precios={"PUBLICO": "100"})

    def factura(cantidad=2, **extra):
        monto = D(cantidad) * D("118.00")
        venta = tienda.vender(
            [tienda.linea(producto, cantidad)],
            [tienda.cobro(tienda.efectivo, str(monto))],
            tipo_comprobante="01",
            cliente=extra.pop("cliente", tienda.cliente()),
            **extra,
        )
        return venta.comprobantes.get()

    def nota_credito(comprobante, cantidad=1):
        linea = comprobante.lineas.get()
        return notas_credito.crear_nota_credito(
            comprobante,
            motivo="07",
            devueltas=[notas_credito.LineaDevuelta(linea, D(str(cantidad)))],
            reembolsos=[tienda.cobro(tienda.efectivo, str(D(cantidad) * D("118.00")))],
        )

    def guia(comprobante, **extra):
        datos = {
            "lineas": [(comprobante.lineas.get(), D("1"))],
            "punto_partida": "Jr. Leguia 484, Tarapoto",
            "punto_llegada": "Jr. Andres Asenjo 92, Tarapoto",
            "ubigeo_partida": "220901",
            "ubigeo_llegada": "220901",
            "fecha_traslado": tienda.entorno.hoy,
            "modalidad": "02",
            "placa": "ABC-123",
            "conductor_nombre": "Jeiser Fabian Rojas Diaz",
            "conductor_licencia": "Q12345678",
            "usuario_nombre": "Rosa",
        }
        return guias.crear_guia(comprobante, **{**datos, **extra})

    def contexto():
        """Vuelve a activar el contexto de la organización (cada petición HTTP lo limpia)."""
        establecer_contexto(
            tienda.entorno.e.org_a.pk,
            [tienda.a.pk, tienda.b.pk],
            tienda.entorno.e.usuario_id,
        )

    return SimpleNamespace(
        tienda=tienda,
        contexto=contexto,
        empresa=a,
        config=config,
        producto=producto,
        factura=factura,
        nota_credito=nota_credito,
        guia=guia,
    )
