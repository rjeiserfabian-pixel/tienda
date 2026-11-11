"""API de la facturación electrónica: permisos, documentos, vista previa, envío y configuración."""

import json

import pytest

from apps.facturacion.models import OrigenDocumento
from apps.seguridad.tests.conftest import cliente_de

from .conftest import CON_ERROR, GRE_SECRETO, SOL_CLAVE, SOL_USUARIO

pytestmark = pytest.mark.django_db

BASE = "/api/v1/facturacion"


def con(fe, usuario):
    """El cliente de ese usuario, con el contexto ya listo para seguir creando datos de prueba."""
    api = cliente_de(usuario)  # iniciar sesión limpia el contexto
    fe.contexto()
    return api


def enviar(api, origen, pk):
    return api.post(f"{BASE}/enviar/", {"origen": origen, "id": pk}, format="json")


class TestEnviar:
    def test_el_administrador_envia_y_el_resultado_vuelve_en_la_respuesta(self, fe, api_falsa):
        comp = fe.factura()
        r = enviar(cliente_de("admin"), "COMPROBANTE", comp.pk)
        assert r.status_code == 200, r.content
        datos = r.json()
        assert (datos["estado"], datos["intentos"], datos["serie"]) == ("ENVIADO", 1, "F001")
        assert datos["codigo_hash"] and "aceptada" in datos["mensaje"]
        assert SOL_CLAVE not in r.content.decode() and "xml_base_64" not in datos

    def test_quien_no_tiene_el_permiso_no_envia(self, fe, api_falsa):
        comp = fe.factura()
        for usuario in ("contador", "cajero", "vendedor"):
            assert enviar(cliente_de(usuario), "COMPROBANTE", comp.pk).status_code == 403
        assert api_falsa.enviados == []

    def test_enviar_dos_veces_se_rechaza_y_un_error_de_la_api_se_ve_en_el_estado(
        self, fe, api_falsa
    ):
        api = con(fe, "admin")
        comp = fe.factura()
        api_falsa.responder(CON_ERROR)
        r = enviar(api, "COMPROBANTE", comp.pk)
        assert r.status_code == 200 and r.json()["estado"] == "ERROR_API"
        api_falsa.responder({"data": {"error": "false"}})
        assert enviar(api, "COMPROBANTE", comp.pk).json()["estado"] == "ENVIADO"
        otra = enviar(api, "COMPROBANTE", comp.pk)
        assert otra.status_code == 409 and otra.json()["error"]["codigo"] == "ya_enviado"

    def test_lo_que_no_existe_o_viene_mal_pedido(self, fe, api_falsa):
        api = cliente_de("admin")
        assert enviar(api, "COMPROBANTE", 99999).status_code == 404
        assert enviar(api, "OTRA_COSA", 1).status_code == 400
        assert api.post(f"{BASE}/enviar/", {}, format="json").status_code == 400

    def test_con_la_facturacion_apagada_responde_conflicto_claro(self, fe, api_falsa):
        fe.config.sunat_activo = False
        fe.config.save()
        comp = fe.factura()
        r = enviar(cliente_de("admin"), "COMPROBANTE", comp.pk)
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "facturacion_no_activa"


class TestVistaPrevia:
    def test_muestra_el_json_con_las_claves_ocultas(self, fe):
        comp = fe.factura()
        r = cliente_de("contador").get(
            f"{BASE}/vista-previa/", {"origen": "COMPROBANTE", "id": comp.pk}
        )
        assert r.status_code == 200 and r["Cache-Control"] == "no-store"
        texto = r.content.decode()
        for secreto in (SOL_CLAVE, SOL_USUARIO, GRE_SECRETO):
            assert secreto not in texto
        datos = r.json()
        assert datos["tipo_documento"] == "01" and datos["faltantes"] == []
        assert datos["payload"]["empresa"]["usu_secundario_produccion_password"] == "********"
        assert datos["payload"]["venta"]["serie"] == "F001"

    def test_funciona_aunque_la_facturacion_este_apagada(self, fe):
        fe.config.sunat_activo = False
        fe.config.save()
        comp = fe.factura()
        r = cliente_de("admin").get(
            f"{BASE}/vista-previa/", {"origen": "COMPROBANTE", "id": comp.pk}
        )
        assert r.status_code == 200 and r.json()["activo"] is False

    def test_un_documento_que_no_se_puede_enviar_explica_por_que(self, fe):
        tienda = fe.tienda
        venta = tienda.vender(
            [tienda.linea(fe.producto, 1)], [tienda.cobro(tienda.efectivo, "118.00")]
        )
        comp = venta.comprobantes.get()
        r = cliente_de("admin").get(
            f"{BASE}/vista-previa/", {"origen": "COMPROBANTE", "id": comp.pk}
        )
        assert r.status_code == 409 and "no es electrónico" in r.json()["error"]["mensaje"]


class TestDocumentos:
    def test_lista_los_electronicos_con_el_estado_de_su_envio(self, fe, api_falsa):
        api = con(fe, "admin")
        enviado, pendiente = fe.factura(), fe.factura()
        enviar(api, "COMPROBANTE", enviado.pk)
        lista = api.get(f"{BASE}/documentos/", {"empresa": fe.empresa.pk, "origen": "COMPROBANTE"})
        assert lista.status_code == 200 and lista.json()["count"] == 2
        por_numero = {f["numero"]: f for f in lista.json()["results"]}
        assert por_numero["F001-00000001"]["envio"]["estado"] == "ENVIADO"
        assert por_numero["F001-00000002"]["envio"] is None
        assert por_numero["F001-00000002"]["cliente"] and por_numero["F001-00000002"]["total"]

        def ids(**filtro):
            r = api.get(
                f"{BASE}/documentos/",
                {"empresa": fe.empresa.pk, "origen": "COMPROBANTE", **filtro},
            )
            return [f["id"] for f in r.json()["results"]]

        assert ids(envio="enviado") == [enviado.pk] and ids(envio="sin_enviar") == [pendiente.pk]
        assert ids(envio="error") == [] and ids(q="2") == [pendiente.pk]

    def test_solo_aparecen_documentos_electronicos(self, fe):
        tienda = fe.tienda
        tienda.vender([tienda.linea(fe.producto, 1)], [tienda.cobro(tienda.efectivo, "118.00")])
        fe.factura()
        r = cliente_de("admin").get(
            f"{BASE}/documentos/", {"empresa": fe.empresa.pk, "origen": "COMPROBANTE"}
        )
        assert r.json()["count"] == 1  # la nota de venta no entra

    def test_notas_de_credito_y_guias_tienen_su_lista(self, fe):
        api = con(fe, "admin")
        comp = fe.factura(2)
        fe.nota_credito(comp, 1)
        fe.guia(comp)
        for origen, serie in (("NOTA_CREDITO", "FC01-00000001"), ("GUIA", "T001-00000001")):
            r = api.get(f"{BASE}/documentos/", {"empresa": fe.empresa.pk, "origen": origen})
            assert r.status_code == 200 and [f["numero"] for f in r.json()["results"]] == [serie]

    def test_parametros_malos_y_permisos(self, fe):
        api = cliente_de("admin")
        assert api.get(f"{BASE}/documentos/", {"empresa": fe.empresa.pk}).status_code == 400
        malo = api.get(
            f"{BASE}/documentos/",
            {"empresa": fe.empresa.pk, "origen": "COMPROBANTE", "envio": "x"},
        )
        assert malo.status_code == 400
        assert api.get(f"{BASE}/documentos/", {"origen": "COMPROBANTE"}).status_code == 400
        assert OrigenDocumento.GUIA == "GUIA"


class TestConfiguracionApi:
    def test_ver_la_configuracion_no_revela_ninguna_clave(self, fe):
        r = cliente_de("contador").get(f"{BASE}/configuracion/", {"empresa": fe.empresa.pk})
        assert r.status_code == 200
        texto = json.dumps(r.json())
        assert all(s not in texto for s in (SOL_CLAVE, SOL_USUARIO, GRE_SECRETO))
        datos = r.json()
        assert (datos["activo"], datos["modo"], datos["ubigeo_nombre"]) == (
            True,
            "BETA",
            "SAN MARTÍN - SAN MARTÍN - TARAPOTO",
        )

    def test_solo_quien_configura_puede_cambiarla(self, fe):
        cuerpo = {"empresa": fe.empresa.pk, "urbanizacion": "Centro"}
        assert (
            cliente_de("contador")
            .patch(f"{BASE}/configuracion/", cuerpo, format="json")
            .status_code
            == 403
        )
        r = cliente_de("admin").patch(f"{BASE}/configuracion/", cuerpo, format="json")
        assert r.status_code == 200 and r.json()["urbanizacion"] == "Centro"

    def test_cambiar_las_claves_las_guarda_sin_devolverlas(self, fe):
        r = cliente_de("admin").patch(
            f"{BASE}/configuracion/",
            {"empresa": fe.empresa.pk, "clave_sol": "clave-nueva-xyz", "modo": "PRODUCCION"},
            format="json",
        )
        assert r.status_code == 200 and "clave-nueva-xyz" not in r.content.decode()
        fe.config.refresh_from_db()
        assert (
            fe.config.sunat_clave_sol == "clave-nueva-xyz" and fe.config.modo_sunat == "PRODUCCION"
        )

    def test_activar_con_datos_que_faltan_da_un_error_claro(self, fe):
        r = cliente_de("admin").patch(
            f"{BASE}/configuracion/", {"empresa": fe.tienda.b.pk, "activo": True}, format="json"
        )
        assert r.status_code == 409 and r.json()["error"]["codigo"] == "configuracion_incompleta"
        assert "Usuario secundario" in r.json()["error"]["mensaje"]

    def test_valida_los_formatos(self, fe):
        api = cliente_de("admin")
        for malo in ({"ubigeo_fiscal": "123"}, {"codigo_sunat_defecto": "abc"}, {"modo": "X"}):
            r = api.patch(
                f"{BASE}/configuracion/", {"empresa": fe.empresa.pk, **malo}, format="json"
            )
            assert r.status_code == 400

    def test_probar_dice_si_la_api_responde_y_que_falta(self, fe, api_falsa):
        api = cliente_de("admin")
        r = api.post(f"{BASE}/configuracion/probar/", {"empresa": fe.empresa.pk}, format="json")
        assert r.status_code == 200
        assert (r.json()["api_alcanzable"], r.json()["faltantes"]) == (True, [])
        api_falsa.falla = api_falsa.error_conexion
        r = api.post(f"{BASE}/configuracion/probar/", {"empresa": fe.empresa.pk}, format="json")
        assert r.json()["api_alcanzable"] is False
        assert (
            cliente_de("contador")
            .post(f"{BASE}/configuracion/probar/", {"empresa": fe.empresa.pk}, format="json")
            .status_code
            == 403
        )
