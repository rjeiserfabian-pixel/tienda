"""El envío a la API: estados, reintentos, y que ninguna clave se guarde."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.facturacion import servicios
from apps.facturacion.exceptions import (
    ConfiguracionIncompleta,
    DocumentoNoEnviable,
    EnvioEnCurso,
    FacturacionNoActiva,
    YaEnviado,
)
from apps.facturacion.models import EnvioSunat, EstadoEnvio, OrigenDocumento

from .conftest import CON_ERROR, GRE_SECRETO, SOL_CLAVE, SOL_USUARIO, TICKET

pytestmark = pytest.mark.django_db

COMPROBANTE = OrigenDocumento.COMPROBANTE
GUIA = OrigenDocumento.GUIA


def guardado(envio) -> str:
    """Todo lo que quedó en la base de ese envío, como un solo texto."""
    campos = {c.name: getattr(envio, c.name) for c in envio._meta.concrete_fields}
    return json.dumps(campos, default=str)


class TestEnvioExitoso:
    def test_envia_a_la_api_y_guarda_lo_que_responde(self, fe, api_falsa):
        comp = fe.factura()
        envio = servicios.enviar_documento(COMPROBANTE, comp)
        assert envio.estado == EstadoEnvio.ENVIADO and envio.intentos == 1
        assert (envio.tipo_documento, envio.serie, envio.numero) == ("01", "F001", 1)
        assert envio.codigo_respuesta == "0" and "aceptada" in envio.mensaje
        assert envio.codigo_hash == "lWrNCNKcsQ+nmEqDWwkkvZTWUj0="
        assert envio.modo == "BETA" and envio.enviado_en is not None
        # Se conservan los archivos para interpretarlos después…
        assert "xml_base_64" in envio.respuesta and "cdr_base_64" in envio.respuesta
        # …pero no los datos de la sesión de SUNAT.
        assert "respuesta_sunat" not in envio.respuesta

    def test_la_llamada_lleva_las_claves_pero_nada_de_eso_se_guarda(self, fe, api_falsa):
        envio = servicios.enviar_documento(COMPROBANTE, fe.factura())
        (llamada,) = api_falsa.enviados
        assert llamada["url"] == "http://localhost/API_SUNAT/post.php"
        assert llamada["json"]["empresa"]["usu_secundario_produccion_password"] == SOL_CLAVE
        assert llamada["kwargs"]["allow_redirects"] is False and "timeout" in llamada["kwargs"]
        base = guardado(EnvioSunat.objects.sin_ambito().get(pk=envio.pk))
        assert SOL_CLAVE not in base and SOL_USUARIO not in base

    def test_la_guia_recibe_un_ticket_y_usa_su_propia_direccion(self, fe, api_falsa, settings):
        settings.SUNAT_ENDPOINTS = {**settings.SUNAT_ENDPOINTS, "09": "post_guia.php"}
        api_falsa.responder(TICKET)
        envio = servicios.enviar_documento(GUIA, fe.guia(fe.factura()))
        assert api_falsa.enviados[0]["url"].endswith("/API_SUNAT/post_guia.php")
        assert envio.estado == EstadoEnvio.ENVIADO and envio.codigo_respuesta == "TICKET_GENERADO"
        assert envio.ticket == "f03b2ead-5376-48c3-a09e-cee0d31db682"
        assert GRE_SECRETO not in guardado(envio) and "id-interno" not in guardado(envio)

    def test_sin_direccion_de_la_guia_no_se_intenta_enviar(self, fe, api_falsa):
        with pytest.raises(ConfiguracionIncompleta, match="SUNAT_ENDPOINT_GUIA"):
            servicios.enviar_documento(GUIA, fe.guia(fe.factura()))
        assert api_falsa.enviados == []
        assert EnvioSunat.objects.sin_ambito().count() == 0 or (
            EnvioSunat.objects.sin_ambito().get().estado != EstadoEnvio.EN_PROCESO
        )


class TestErrores:
    def test_si_la_api_devuelve_un_error_queda_registrado_y_se_puede_reintentar(
        self, fe, api_falsa
    ):
        comp = fe.factura()
        api_falsa.responder(CON_ERROR)
        envio = servicios.enviar_documento(COMPROBANTE, comp)
        assert envio.estado == EstadoEnvio.ERROR_API and envio.codigo_respuesta == "2800"
        assert "cliente" in envio.mensaje
        api_falsa.responder({"data": {"error": "false", "respuesta_sunat_codigo": "0"}})
        otra = servicios.enviar_documento(COMPROBANTE, comp)
        assert otra.pk == envio.pk and otra.estado == EstadoEnvio.ENVIADO and otra.intentos == 2

    def test_sin_conexion_no_revienta_y_queda_para_reintentar(self, fe, api_falsa):
        api_falsa.falla = api_falsa.error_conexion
        envio = servicios.enviar_documento(COMPROBANTE, fe.factura())
        assert envio.estado == EstadoEnvio.SIN_CONEXION and "conectar" in envio.mensaje

    def test_una_respuesta_que_no_es_la_esperada_es_error_de_la_api(self, fe, api_falsa):
        for cuerpo, estado in ((None, 500), ({"data": {"algo": 1}}, 200), ({"otra": 1}, 200)):
            api_falsa.responder(cuerpo, estado)
            comp = fe.factura()
            envio = servicios.enviar_documento(COMPROBANTE, comp)
            assert envio.estado == EstadoEnvio.ERROR_API and "inesperado" in envio.mensaje

    def test_un_fallo_inesperado_no_deja_el_envio_colgado(self, fe, api_falsa):
        api_falsa.falla = RuntimeError("boom")
        comp = fe.factura()
        with pytest.raises(RuntimeError):
            servicios.enviar_documento(COMPROBANTE, comp)
        envio = EnvioSunat.objects.sin_ambito().get(origen_id=comp.pk)
        assert envio.estado == EstadoEnvio.ERROR_API  # no «enviando» para siempre


class TestReglas:
    def test_lo_ya_enviado_no_se_vuelve_a_enviar(self, fe, api_falsa):
        comp = fe.factura()
        servicios.enviar_documento(COMPROBANTE, comp)
        with pytest.raises(YaEnviado):
            servicios.enviar_documento(COMPROBANTE, comp)
        assert len(api_falsa.enviados) == 1

    def test_un_envio_en_curso_se_respeta_pero_uno_colgado_se_libera(self, fe, api_falsa):
        comp = fe.factura()
        envio = EnvioSunat.objects.sin_ambito().create(
            empresa=fe.empresa,
            origen=COMPROBANTE,
            origen_id=comp.pk,
            tipo_documento="01",
            serie=comp.serie,
            numero=comp.numero,
            estado=EstadoEnvio.EN_PROCESO,
            intentos=1,
            iniciado_en=timezone.now(),
        )
        with pytest.raises(EnvioEnCurso):
            servicios.enviar_documento(COMPROBANTE, comp)
        EnvioSunat.objects.sin_ambito().filter(pk=envio.pk).update(
            iniciado_en=timezone.now() - timedelta(minutes=3)
        )
        assert servicios.enviar_documento(COMPROBANTE, comp).estado == EstadoEnvio.ENVIADO

    def test_con_la_facturacion_apagada_no_se_envia(self, fe, api_falsa):
        fe.config.sunat_activo = False
        fe.config.save()
        with pytest.raises(FacturacionNoActiva):
            servicios.enviar_documento(COMPROBANTE, fe.factura())
        assert api_falsa.enviados == []

    def test_con_la_configuracion_incompleta_dice_que_falta(self, fe, api_falsa):
        fe.config.sunat_clave_sol = ""
        fe.config.save()
        with pytest.raises(ConfiguracionIncompleta, match="Clave del usuario secundario"):
            servicios.enviar_documento(COMPROBANTE, fe.factura())
        assert api_falsa.enviados == []

    def test_una_nota_de_venta_no_es_electronica(self, fe, api_falsa):
        tienda = fe.tienda
        venta = tienda.vender(
            [tienda.linea(fe.producto, 1)], [tienda.cobro(tienda.efectivo, "118.00")]
        )  # nota de venta: serie interna
        with pytest.raises(DocumentoNoEnviable, match="no es electrónico"):
            servicios.enviar_documento(COMPROBANTE, venta.comprobantes.get())

    def test_un_documento_anulado_no_se_envia(self, fe, api_falsa):
        from apps.ventas import servicios as ventas

        venta = fe.factura().venta
        ventas.anular_venta(venta, motivo="Error de digitación")
        comprobante = servicios.documento(COMPROBANTE, venta.comprobantes.get().pk)
        with pytest.raises(DocumentoNoEnviable, match="anulado"):
            servicios.enviar_documento(COMPROBANTE, comprobante)


class TestConfiguracion:
    def test_los_secretos_se_escriben_pero_nunca_se_devuelven(self, fe):
        data = servicios.configuracion_json(fe.empresa, fe.config)
        texto = json.dumps(data)
        for secreto in (SOL_CLAVE, SOL_USUARIO, GRE_SECRETO):
            assert secreto not in texto
        assert data["clave_sol_puesta"] and data["gre_client_secret_puesto"]
        assert data["usuario_sol"].startswith("SI") and "ISTEMA" not in data["usuario_sol"]

    def test_un_secreto_vacio_no_borra_el_que_ya_estaba(self, fe):
        servicios.actualizar_configuracion(
            fe.empresa,
            {"clave_sol": "", "usuario_sol": "", "urbanizacion": "Residencial Monterrico"},
        )
        fe.config.refresh_from_db()
        assert fe.config.sunat_clave_sol == SOL_CLAVE and fe.config.sunat_usuario_sol == SOL_USUARIO
        assert fe.config.urbanizacion == "Residencial Monterrico"
        servicios.actualizar_configuracion(fe.empresa, {"clave_sol": "otra-clave-nueva"})
        fe.config.refresh_from_db()
        assert fe.config.sunat_clave_sol == "otra-clave-nueva"

    def test_no_se_activa_si_falta_algo(self, fe):
        fe.config.sunat_activo = False
        fe.config.sunat_clave_sol = ""
        fe.config.save()
        with pytest.raises(ConfiguracionIncompleta, match="Clave del usuario"):
            servicios.actualizar_configuracion(fe.empresa, {"activo": True})
        fe.config.refresh_from_db()
        assert fe.config.sunat_activo is False
        servicios.actualizar_configuracion(fe.empresa, {"activo": True, "clave_sol": "nueva-clave"})
        fe.config.refresh_from_db()
        assert fe.config.sunat_activo is True

    def test_un_ubigeo_que_no_existe_se_rechaza(self, fe):
        with pytest.raises(ConfiguracionIncompleta, match="ubigeo"):
            servicios.actualizar_configuracion(fe.empresa, {"ubigeo_fiscal": "999999"})
