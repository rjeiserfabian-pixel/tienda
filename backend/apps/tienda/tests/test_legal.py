"""Libro de Reclamaciones, páginas legales y métricas de la tienda."""

# ruff: noqa: F811

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import reclamos
from apps.tienda.models import PedidoTienda, Reclamo

from .conftest import _cache_limpia, tienda  # noqa: F401
from .test_cuentas import registrada
from .test_pagar import cobra, culqi_falso, pagar_pedido  # noqa: F401
from .test_pedidos import contexto, vende  # noqa: F401
from .test_pedidos_admin import estado, hacer_pedido

pytestmark = pytest.mark.django_db

LIBRO = "/api/v1/tienda/libro-de-reclamaciones"
RECLAMOS = "/api/v1/tienda/reclamos"
ADMIN_RECLAMOS = "/api/v1/tienda/admin/reclamos"
PAGINAS = "/api/v1/tienda/admin/paginas"
PUBLICA = "/api/v1/tienda/paginas"
CONFIG = "/api/v1/tienda/configuracion"
METRICAS = "/api/v1/tienda/admin/metricas/"


def anonimo():
    return APIClient(HTTP_X_REQUESTED_WITH="tienda")


def empresa_id(tienda):
    return tienda.e.e1.pk


def hoja(tienda, **extra):
    datos = {
        "empresa": empresa_id(tienda),
        "tipo": "RECLAMO",
        "nombre": "Ana Pérez Rojas",
        "documento_tipo": "DNI",
        "documento_numero": "12345678",
        "domicilio": "Av. Sol 100, Cusco",
        "telefono": "987654321",
        "correo": "ana@ejemplo.pe",
        "bien_tipo": "PRODUCTO",
        "monto": "250.00",
        "bien_descripcion": "Mouse inalámbrico",
        "pedido_numero": "T-000001",
        "detalle": "Llegó con el botón izquierdo roto.",
        "pedido_consumidor": "Quiero que me lo cambien.",
    }
    datos.update(extra)
    return datos


def registrar(tienda, **extra):
    return anonimo().post(RECLAMOS, hoja(tienda, **extra), format="json")


class TestPlazo:
    def test_15_dias_habiles_sin_contar_fines_de_semana(self):
        viernes = datetime(2026, 11, 6)  # viernes
        assert reclamos.sumar_dias_habiles(viernes, 1) == datetime(2026, 11, 9)  # lunes
        assert reclamos.sumar_dias_habiles(viernes, 5) == datetime(2026, 11, 13)
        assert reclamos.sumar_dias_habiles(viernes, 15) == datetime(2026, 11, 27)


class TestLibro:
    def test_el_formulario_publico_lista_las_empresas(self, tienda):
        d = anonimo().get(LIBRO).json()
        assert d["plazo_dias_habiles"] == 15
        assert {e["id"] for e in d["empresas"]} >= {tienda.e.e1.pk}
        assert {"razon_social", "ruc", "direccion"} <= set(d["empresas"][0])

    def test_registra_numera_y_manda_la_constancia(self, tienda):
        n = len(mail.outbox)
        r = registrar(tienda)
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["numero"] == f"0001-{timezone.now().year}"
        assert registrar(tienda, tipo="QUEJA").json()["numero"] == f"0002-{timezone.now().year}"
        constancia = next(m for m in mail.outbox[n:] if "ana@ejemplo.pe" in m.to)
        assert d["numero"] in constancia.subject
        assert "Mouse inalámbrico" in constancia.body and "15 días hábiles" in constancia.body
        fila = Reclamo.objects.sin_ambito().get(numero=d["numero"])
        assert fila.estado == "PENDIENTE" and fila.vence_en > timezone.now() + timedelta(days=14)

    def test_se_valida_lo_que_exige_la_norma(self, tienda):
        malos = [
            {"documento_numero": "123"},  # DNI de 8 dígitos
            {"documento_tipo": "RUC", "documento_numero": "12345678"},
            {"correo": "no-es-correo"},
            {"empresa": 999999},
            {"nombre": "   "},
            {"detalle": ""},
            {"pedido_consumidor": ""},
            {"menor_de_edad": True, "apoderado": ""},
            {"monto": "abc"},
        ]
        for extra in malos:
            assert registrar(tienda, **extra).status_code == 400, extra
        assert not Reclamo.objects.sin_ambito().exists()

    def test_un_menor_de_edad_con_apoderado_se_acepta(self, tienda):
        r = registrar(tienda, menor_de_edad=True, apoderado="María Rojas")
        assert r.status_code == 201

    def test_el_monto_es_opcional(self, tienda):
        assert registrar(tienda, monto="").status_code == 201

    def test_avisa_al_negocio(self, tienda):
        from apps.organizacion.models import Empresa

        Empresa.objects.sin_ambito().filter(pk=tienda.e.e1.pk).update(correo="ventas@negocio.pe")
        n = len(mail.outbox)
        registrar(tienda)
        assert any("ventas@negocio.pe" in m.to for m in mail.outbox[n:])

    def test_un_cliente_con_sesion_queda_vinculado(self, tienda):
        c = registrada()
        r = c.post(RECLAMOS, hoja(tienda), format="json")
        assert r.status_code == 201
        assert Reclamo.objects.sin_ambito().get().cuenta_id is not None


class TestPanel:
    def preparar(self, tienda):
        return registrar(tienda).json()["numero"]

    def test_lista_resume_y_filtra(self, tienda):
        self.preparar(tienda)
        registrar(tienda, nombre="Luis Díaz", documento_numero="87654321")
        a = cliente_de("admin")
        d = a.get(f"{ADMIN_RECLAMOS}/").json()
        assert d["count"] == 2 and d["resumen"]["pendientes"] == 2 and d["resumen"]["vencidos"] == 0
        assert a.get(f"{ADMIN_RECLAMOS}/", {"q": "Luis"}).json()["count"] == 1
        assert a.get(f"{ADMIN_RECLAMOS}/", {"estado": "RESPONDIDO"}).json()["count"] == 0
        fila = d["results"][0]
        assert fila["dias_restantes"] >= 14 and fila["vencido"] is False
        assert fila["documento"].startswith("DNI ")

    def test_por_vencer_y_vencidos(self, tienda):
        self.preparar(tienda)
        a = cliente_de("admin")
        Reclamo.objects.sin_ambito().update(vence_en=timezone.now() + timedelta(days=2))
        assert a.get(f"{ADMIN_RECLAMOS}/", {"estado": "por_vencer"}).json()["count"] == 1
        Reclamo.objects.sin_ambito().update(vence_en=timezone.now() - timedelta(days=1))
        d = a.get(f"{ADMIN_RECLAMOS}/").json()
        assert d["resumen"]["vencidos"] == 1 and d["results"][0]["vencido"] is True

    def test_responder_guarda_y_escribe_al_consumidor(self, tienda):
        self.preparar(tienda)
        r = Reclamo.objects.sin_ambito().get()
        n = len(mail.outbox)
        x = cliente_de("admin").post(
            f"{ADMIN_RECLAMOS}/{r.pk}/responder/",
            {"texto": "Lamentamos lo ocurrido; te enviamos un mouse nuevo."},
            format="json",
        )
        assert x.status_code == 200, x.content
        d = x.json()
        assert (
            d["estado"] == "RESPONDIDO"
            and d["respuesta_enviada"] is True
            and d["dias_restantes"] is None
        )
        correo = next(m for m in mail.outbox[n:] if "ana@ejemplo.pe" in m.to)
        assert "mouse nuevo" in correo.body and "INDECOPI" in correo.body
        # no se responde dos veces
        again = cliente_de("admin").post(
            f"{ADMIN_RECLAMOS}/{r.pk}/responder/",
            {"texto": "Otra respuesta distinta"},
            format="json",
        )
        assert again.status_code == 400

    def test_la_respuesta_debe_ser_completa(self, tienda):
        self.preparar(tienda)
        r = Reclamo.objects.sin_ambito().get()
        x = cliente_de("admin").post(
            f"{ADMIN_RECLAMOS}/{r.pk}/responder/", {"texto": "ok"}, format="json"
        )
        assert x.status_code == 400

    def test_sin_permiso_no_se_ve_ni_responde(self, tienda, nuevo_usuario):
        nuevo_usuario(tienda.org, "cajero", [tienda.e.e1], [("CAJERO", tienda.e.e1)])
        self.preparar(tienda)
        r = Reclamo.objects.sin_ambito().get()
        c = cliente_de("cajero")
        assert c.get(f"{ADMIN_RECLAMOS}/").status_code == 403
        assert (
            c.post(
                f"{ADMIN_RECLAMOS}/{r.pk}/responder/", {"texto": "x" * 20}, format="json"
            ).status_code
            == 403
        )
        assert APIClient().get(f"{ADMIN_RECLAMOS}/").status_code == 401

    def test_cada_organizacion_ve_los_suyos(self, tienda):
        self.preparar(tienda)
        assert cliente_de("otra_org").get(f"{ADMIN_RECLAMOS}/").json()["count"] == 0


class TestPaginasLegales:
    def test_se_edita_se_publica_y_se_lee(self, tienda):
        a = cliente_de("admin")
        d = a.get(f"{PAGINAS}/").json()["paginas"]
        assert [p["slug"] for p in d] == [
            "terminos",
            "privacidad",
            "cambios-y-devoluciones",
            "envios",
        ]
        assert all(not p["publicada"] and p["sugerencia"] for p in d)
        assert anonimo().get(f"{PUBLICA}/terminos").status_code == 404
        texto = "# Quiénes somos\n" + "Somos una tienda de tecnología. " * 5
        r = a.put(f"{PAGINAS}/terminos/", {"contenido": texto, "publicada": True}, format="json")
        assert r.status_code == 200, r.content
        pub = anonimo().get(f"{PUBLICA}/terminos").json()
        assert pub["titulo"] == "Términos y condiciones" and "Somos una tienda" in pub["contenido"]
        assert anonimo().get(CONFIG).json()["paginas"] == [
            {"slug": "terminos", "titulo": "Términos y condiciones"}
        ]

    def test_un_borrador_no_es_publico(self, tienda):
        a = cliente_de("admin")
        a.put(
            f"{PAGINAS}/envios/", {"contenido": "Borrador " * 20, "publicada": False}, format="json"
        )
        assert anonimo().get(f"{PUBLICA}/envios").status_code == 404
        assert anonimo().get(CONFIG).json()["paginas"] == []

    def test_no_se_publica_vacia_ni_con_una_pagina_inexistente(self, tienda):
        a = cliente_de("admin")
        assert (
            a.put(
                f"{PAGINAS}/terminos/", {"contenido": "corto", "publicada": True}, format="json"
            ).status_code
            == 400
        )
        assert (
            a.put(
                f"{PAGINAS}/inventada/", {"contenido": "x" * 80, "publicada": False}, format="json"
            ).status_code
            == 404
        )

    def test_el_html_se_guarda_como_texto_y_solo_edita_quien_configura(self, tienda):
        a = cliente_de("admin")
        a.put(
            f"{PAGINAS}/privacidad/",
            {"contenido": "<script>alert(1)</script> " + "texto " * 20, "publicada": True},
            format="json",
        )
        # se guarda tal cual (texto); la tienda lo muestra como texto, nunca como HTML
        assert "<script>" in anonimo().get(f"{PUBLICA}/privacidad").json()["contenido"]
        r = cliente_de("vendedor").put(
            f"{PAGINAS}/privacidad/", {"contenido": "x" * 80, "publicada": True}, format="json"
        )
        assert r.status_code == 403


class TestMetricas:
    def test_cuenta_ventas_embudo_y_top(self, cobra, culqi_falso):
        c = registrada()
        p, pedido = hacer_pedido(cobra, c, "Mouse")
        assert pagar_pedido(c, pedido["numero"]).status_code == 200
        # otro pedido que nunca se paga
        registrada("luis@ejemplo.pe")
        a = cliente_de("admin")
        d = a.get(METRICAS, {"dias": 7}).json()
        assert d["dias"] == 7 and len(d["ventas"]["serie"]) == 7
        assert d["ventas"]["pedidos"] == 1
        assert Decimal(d["ventas"]["total"]) == PedidoTienda.objects.sin_ambito().get().total
        assert d["ventas"]["serie"][-1]["pedidos"] == 1
        assert d["embudo"]["creados"] == 1 and d["embudo"]["cobrados"] == 1
        assert d["embudo"]["tasa_pago"] == 100.0
        assert d["pago"]["tarjeta"] + d["pago"]["yape"] == 1
        assert d["top_productos"][0]["nombre"].startswith("Mouse")
        assert d["clientes"]["compradores"] == 1 and d["clientes"]["nuevos"] >= 2

    def test_pide_atencion_por_lo_pendiente(self, cobra, culqi_falso):
        c = registrada()
        _, pedido = hacer_pedido(cobra, c, "Mouse")
        pagar_pedido(c, pedido["numero"])
        registrar(cobra)  # un reclamo
        d = cliente_de("admin").get(METRICAS).json()
        assert d["atencion"]["por_atender"] == 1 and d["atencion"]["reclamos_pendientes"] == 1
        assert estado(cliente_de("admin"), pedido["numero"], "EN_PREPARACION").status_code == 200
        assert cliente_de("admin").get(METRICAS).json()["atencion"]["por_atender"] == 0

    def test_dias_no_validos_usan_30_y_requiere_permiso(self, tienda, nuevo_usuario):
        nuevo_usuario(tienda.org, "cajero", [tienda.e.e1], [("CAJERO", tienda.e.e1)])
        a = cliente_de("admin")
        assert a.get(METRICAS, {"dias": "5"}).json()["dias"] == 30
        assert a.get(METRICAS, {"dias": "abc"}).json()["dias"] == 30
        assert cliente_de("cajero").get(METRICAS).status_code == 403

    def test_sin_datos_no_falla(self, tienda):
        d = cliente_de("admin").get(METRICAS).json()
        assert d["ventas"]["pedidos"] == 0 and d["ventas"]["ticket_promedio"] == "0.00"
        assert d["embudo"]["tasa_pago"] is None and d["top_productos"] == []
