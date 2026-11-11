"""Configuración de cobros en línea (Culqi): llaves cifradas, validaciones y lo público."""

# ruff: noqa: F811

import pytest
from rest_framework.test import APIClient

from apps.seguridad.tests.conftest import cliente_de
from apps.tienda import culqi
from apps.tienda.models import ConfiguracionPago

from .conftest import _cache_limpia, tienda  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN = "/api/v1/tienda/admin/pagos/"
PROBAR = ADMIN + "probar/"
PUBLICA = "/api/v1/tienda/pagos/configuracion"
PK, SK = "pk_test_abc123", "sk_test_secretoSUPERlargo9876"


def admin_pagos():
    """El rol ADMIN no trae este permiso crítico: se da a un usuario de prueba."""
    return cliente_de("superadmin")


@pytest.fixture
def pagos(tienda, nuevo_usuario):  # noqa: F811
    e = tienda.e
    nuevo_usuario(tienda.org, "superadmin", [e.e1], [("SUPERADMIN", None)])
    return tienda


def configurar(c, **extra):
    datos = {
        "culqi_llave_publica": PK,
        "culqi_llave_secreta": SK,
        "empresa_cobra": None,
        **extra,
    }
    return c.patch(ADMIN, datos, format="json")


class TestPermisos:
    def test_solo_quien_tiene_el_permiso_critico(self, pagos):
        assert admin_pagos().get(ADMIN).status_code == 200
        assert cliente_de("almacenero").get(ADMIN).status_code == 403
        assert cliente_de("vendedor").patch(ADMIN, {}, format="json").status_code == 403
        assert APIClient().get(ADMIN).status_code == 401


class TestLlaves:
    def test_la_llave_secreta_se_guarda_cifrada_y_nunca_se_devuelve(self, pagos):
        c = admin_pagos()
        r = configurar(c)
        assert r.status_code == 200, r.content
        texto = r.content.decode()
        assert SK not in texto and r.json()["tiene_llave_secreta"] is True
        assert r.json()["llave_secreta_final"] == SK[-4:]
        assert SK not in c.get(ADMIN).content.decode()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("select culqi_llave_secreta from tienda_configuracionpago")
            guardado = cursor.fetchone()[0]
        assert SK not in guardado and guardado.startswith(("1:", "2:"))
        assert ConfiguracionPago.objects.sin_ambito().get().culqi_llave_secreta == SK

    def test_no_queda_en_la_auditoria(self, pagos):
        from apps.auditoria.models import AuditoriaEvento as EventoAuditoria

        configurar(admin_pagos())
        for e in EventoAuditoria.objects.all():
            assert SK not in str(e.detalle) and SK not in e.resumen

    def test_vacio_no_cambia_la_llave_y_se_puede_quitar(self, pagos):
        c = admin_pagos()
        configurar(c)
        c.patch(ADMIN, {"culqi_llave_secreta": ""}, format="json")
        assert c.get(ADMIN).json()["tiene_llave_secreta"] is True
        r = c.patch(ADMIN, {"quitar_llave_secreta": True}, format="json").json()
        assert r["tiene_llave_secreta"] is False and r["culqi_activo"] is False

    @pytest.mark.parametrize(
        "cambio",
        [
            {"culqi_llave_publica": "pk_live_xyz"},  # llave de producción en modo prueba
            {"culqi_llave_secreta": "sk_live_xyz"},
            {"culqi_llave_publica": "cualquier cosa"},
        ],
    )
    def test_las_llaves_deben_ser_del_modo(self, pagos, cambio):
        assert configurar(admin_pagos(), **cambio).status_code == 400

    def test_cambiar_a_produccion_con_llaves_de_prueba_se_rechaza(self, pagos):
        c = admin_pagos()
        configurar(c)
        assert c.patch(ADMIN, {"culqi_modo": "PRODUCCION"}, format="json").status_code == 400


class TestActivar:
    def test_exige_llaves_empresa_y_un_medio(self, pagos):
        c = admin_pagos()
        r = c.patch(ADMIN, {"culqi_activo": True}, format="json")
        assert r.status_code == 400 and "llave pública" in str(r.json())
        configurar(c)
        r = c.patch(ADMIN, {"culqi_activo": True}, format="json")
        assert r.status_code == 400 and "empresa" in str(r.json())
        r = c.patch(
            ADMIN,
            {
                "culqi_activo": True,
                "empresa_cobra": pagos.e.e1.pk,
                "acepta_tarjeta": False,
                "acepta_yape": False,
            },
            format="json",
        )
        assert r.status_code == 400 and "medio de pago" in str(r.json())

    def test_activa_y_lo_publico_solo_lleva_la_llave_publica(self, pagos):
        c = admin_pagos()
        assert APIClient().get(PUBLICA).json() == {"activo": False}
        configurar(c)
        r = c.patch(ADMIN, {"culqi_activo": True, "empresa_cobra": pagos.e.e1.pk}, format="json")
        assert r.status_code == 200 and r.json()["faltan_para_activar"] == []
        from django.core.cache import cache

        cache.clear()
        publico = APIClient().get(PUBLICA)
        assert publico.json() == {
            "activo": True,
            "proveedor": "culqi",
            "modo": "PRUEBA",
            "llave_publica": PK,
            "tarjeta": True,
            "yape": True,
        }
        assert SK not in publico.content.decode()

    def test_quitar_algo_esencial_apaga_el_cobro(self, pagos):
        c = admin_pagos()
        configurar(c)
        c.patch(ADMIN, {"culqi_activo": True, "empresa_cobra": pagos.e.e1.pk}, format="json")
        r = c.patch(ADMIN, {"empresa_cobra": None}, format="json").json()
        assert r["culqi_activo"] is False

    def test_empresa_de_otra_organizacion_no_vale(self, pagos):
        c = admin_pagos()
        assert c.patch(ADMIN, {"empresa_cobra": pagos.e.eb.pk}, format="json").status_code == 400


class TestProbar:
    def test_sin_llave_pide_guardarla(self, pagos):
        assert admin_pagos().post(PROBAR, {}, format="json").status_code == 400

    def test_responde_segun_culqi(self, pagos, monkeypatch):
        c = admin_pagos()
        configurar(c)
        visto = {}

        def falso(metodo, ruta, llave, cuerpo=None, **kw):
            visto["llave"] = llave
            return culqi.RespuestaCulqi(200, {})

        monkeypatch.setattr(culqi, "llamar", falso)
        r = c.post(PROBAR, {}, format="json").json()
        assert r["ok"] is True and visto["llave"] == SK and SK not in str(r)
        monkeypatch.setattr(culqi, "llamar", lambda *a, **k: culqi.RespuestaCulqi(401, {}))
        assert c.post(PROBAR, {}, format="json").json()["ok"] is False

        def cae(*a, **k):
            raise culqi.ErrorCulqi("No pudimos conectar con Culqi.")

        monkeypatch.setattr(culqi, "llamar", cae)
        assert "conectar" in c.post(PROBAR, {}, format="json").json()["mensaje"]
