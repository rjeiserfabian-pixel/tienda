"""Consulta de DNI/RUC (servicio externo simulado) y vínculo opcional trabajador ↔ usuario."""

import pytest
import requests
from django.core.cache import cache

from apps.auditoria import servicios
from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento import consultas
from apps.mantenimiento.models import Personal
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"
RUC = ruc_valido("2060308400")

DNI_RESPUESTA = {
    "first_name": "ROXANA KARINA",
    "first_last_name": "DELGADO",
    "second_last_name": "HUAMANI",
    "full_name": "DELGADO HUAMANI ROXANA KARINA",
    "document_number": "46027897",
}
RUC_RESPUESTA = {
    "razon_social": "REXTIE S.A.C.",
    "numero_documento": RUC,
    "estado": "ACTIVO",
    "condicion": "HABIDO",
    "direccion": "AV. JOSE GALVEZ BARRENECHEA NRO 566 ",
    "distrito": "SAN ISIDRO",
    "provincia": "LIMA",
    "departamento": "LIMA",
}


class RespuestaFalsa:
    def __init__(self, estado=200, cuerpo=None, json_valido=True):
        self.status_code = estado
        self._cuerpo = cuerpo
        self._json_valido = json_valido

    def json(self):
        if not self._json_valido:
            raise ValueError("no es JSON")
        return self._cuerpo


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())
    cache.clear()


@pytest.fixture
def servicio(monkeypatch, settings):
    """Simula el servicio externo y registra con qué se le llamó."""
    settings.DECOLECTA_TOKEN = "token-de-prueba"
    settings.DECOLECTA_URL = "https://proveedor.example"
    llamadas = []
    respuestas = {
        "DNI": RespuestaFalsa(200, DNI_RESPUESTA),
        "RUC": RespuestaFalsa(200, RUC_RESPUESTA),
    }

    def falso_get(url, params=None, headers=None, timeout=None):
        llamadas.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        respuesta = respuestas["DNI" if "reniec" in url else "RUC"]
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(consultas.requests, "get", falso_get)
    return type("Servicio", (), {"llamadas": llamadas, "respuestas": respuestas})


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "cajero": nuevo_usuario(e.org_a, "cajero", [e.emp_a1], [("CAJERO", None)]),
        "tecnico": nuevo_usuario(e.org_a, "tecnico", [e.emp_a1], [("TECNICO", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


# ---------------------------------------------------------------------------
# Consulta de DNI y RUC
# ---------------------------------------------------------------------------
class TestConsulta:
    def test_dni_devuelve_nombres_y_apellidos_sin_exponer_el_token(self, equipo, servicio):
        r = cliente_de("vendedor").get(f"{BASE}/consultas/dni/46027897/")
        assert r.status_code == 200, r.content
        assert r.json() == {
            "numero": "46027897",
            "nombres": "ROXANA KARINA",
            "apellidos": "DELGADO HUAMANI",
            "nombre_completo": "DELGADO HUAMANI ROXANA KARINA",
        }
        assert r["Cache-Control"] == "no-store"
        llamada = servicio.llamadas[0]
        assert llamada["url"] == "https://proveedor.example/v1/reniec/dni"
        assert llamada["params"] == {"numero": "46027897"}
        assert llamada["headers"]["Authorization"] == "Bearer token-de-prueba"
        assert llamada["timeout"] > 0
        assert "token-de-prueba" not in r.content.decode()

    def test_ruc_devuelve_razon_social_direccion_y_estado(self, equipo, servicio):
        r = cliente_de("vendedor").get(f"{BASE}/consultas/ruc/{RUC}/")
        assert r.status_code == 200, r.content
        cuerpo = r.json()
        assert cuerpo["razon_social"] == "REXTIE S.A.C."
        assert (
            cuerpo["direccion"] == "AV. JOSE GALVEZ BARRENECHEA NRO 566, SAN ISIDRO - LIMA - LIMA"
        )
        assert (cuerpo["estado"], cuerpo["condicion"], cuerpo["es_activo"]) == (
            "ACTIVO",
            "HABIDO",
            True,
        )

    def test_un_ruc_dado_de_baja_no_es_activo(self, equipo, servicio):
        servicio.respuestas["RUC"] = RespuestaFalsa(
            200, {**RUC_RESPUESTA, "estado": "BAJA DEFINITIVA"}
        )
        r = cliente_de("vendedor").get(f"{BASE}/consultas/ruc/{RUC}/")
        assert r.json()["es_activo"] is False

    def test_formato_invalido_no_llama_al_servicio(self, equipo, servicio):
        api = cliente_de("vendedor")
        assert api.get(f"{BASE}/consultas/dni/123/").status_code == 400
        assert (
            api.get(f"{BASE}/consultas/ruc/20100000018/").status_code == 400
        )  # dígito verificador
        assert api.get(f"{BASE}/consultas/otro/123/").status_code == 404
        assert servicio.llamadas == []

    def test_el_resultado_se_guarda_en_cache_y_no_gasta_cuota(self, equipo, servicio):
        api = cliente_de("vendedor")
        api.get(f"{BASE}/consultas/dni/46027897/")
        api.get(f"{BASE}/consultas/dni/46027897/")
        assert len(servicio.llamadas) == 1

    def test_no_encontrado_y_fallos_del_proveedor_se_traducen(self, equipo, servicio):
        api = cliente_de("vendedor")
        servicio.respuestas["DNI"] = RespuestaFalsa(404, {})
        assert (
            api.get(f"{BASE}/consultas/dni/46027897/").json()["error"]["codigo"]
            == "documento_no_encontrado"
        )
        for falla in (
            RespuestaFalsa(500, {}),
            RespuestaFalsa(401, {}),  # token rechazado: no se le cuenta el detalle al usuario
            RespuestaFalsa(200, None, json_valido=False),
            requests.Timeout("lento"),
        ):
            servicio.respuestas["DNI"] = falla
            r = api.get(f"{BASE}/consultas/dni/46027897/")
            assert (r.status_code, r.json()["error"]["codigo"]) == (
                502,
                "servicio_consulta_no_disponible",
            )

    def test_sin_token_configurado_avisa_sin_llamar(self, equipo, servicio, settings):
        settings.DECOLECTA_TOKEN = ""
        r = cliente_de("vendedor").get(f"{BASE}/consultas/dni/46027897/")
        assert (r.status_code, r.json()["error"]["codigo"]) == (503, "consulta_no_configurada")
        assert servicio.llamadas == []

    def test_exige_el_permiso_de_consulta(self, equipo, servicio):
        assert cliente_de("cajero").get(f"{BASE}/consultas/dni/46027897/").status_code == 403
        assert cliente_de("tecnico").get(f"{BASE}/consultas/dni/46027897/").status_code == 403
        assert servicio.llamadas == []

    def test_queda_registrado_quien_consulto(self, equipo, servicio):
        cliente_de("vendedor").get(f"{BASE}/consultas/dni/46027897/")
        evento = AuditoriaEvento.objects.get(accion="documento.consultado")
        assert (evento.recurso_tipo, evento.recurso_id) == ("dni", "46027897")

    def test_limita_la_cantidad_de_consultas_por_usuario(self, equipo, servicio, monkeypatch):
        from rest_framework.settings import api_settings

        from apps.core.throttles import ConsultaDocumentoThrottle

        tasas = {**api_settings.DEFAULT_THROTTLE_RATES, "consultas": "2/min"}
        monkeypatch.setattr(ConsultaDocumentoThrottle, "THROTTLE_RATES", tasas)
        api = cliente_de("vendedor")
        estados = [api.get(f"{BASE}/consultas/dni/4602789{i}/").status_code for i in range(4)]
        assert estados[:2] == [200, 200]
        assert 429 in estados


# ---------------------------------------------------------------------------
# Vínculo trabajador ↔ usuario
# ---------------------------------------------------------------------------
def personal_json(empresa, **extra):
    return {
        "empresa": empresa.pk,
        "tipo_documento": "DNI",
        "numero_documento": "71234567",
        "nombres": "Luis",
        "apellidos": "Ramos Soto",
        "area": "TECNICO",
        **extra,
    }


class TestVinculo:
    def test_se_vincula_se_ve_en_ambos_lados_y_se_desvincula(self, equipo):
        e, tecnico = equipo["e"], equipo["tecnico"]
        api = cliente_de("super")
        r = api.post(
            f"{BASE}/personal/", personal_json(e.emp_a1, usuario=str(tecnico.pk)), format="json"
        )
        assert r.status_code == 201, r.content
        assert (r.json()["usuario"], r.json()["usuario_username"]) == (str(tecnico.pk), "tecnico")
        # Desde el usuario se ve el trabajador vinculado.
        ficha = api.get(f"/api/v1/seguridad/usuarios/{tecnico.pk}/").json()
        assert ficha["trabajador"]["nombre"] == "Luis Ramos Soto"
        # Se puede desvincular sin borrar al trabajador.
        quitar = api.patch(f"{BASE}/personal/{r.json()['id']}/", {"usuario": None}, format="json")
        assert quitar.status_code == 200 and quitar.json()["usuario"] is None
        assert api.get(f"/api/v1/seguridad/usuarios/{tecnico.pk}/").json()["trabajador"] is None

    def test_un_usuario_solo_se_vincula_a_un_trabajador(self, equipo):
        e, tecnico = equipo["e"], equipo["tecnico"]
        api = cliente_de("super")
        api.post(
            f"{BASE}/personal/", personal_json(e.emp_a1, usuario=str(tecnico.pk)), format="json"
        )
        otro = personal_json(e.emp_a1, numero_documento="71234568", usuario=str(tecnico.pk))
        r = api.post(f"{BASE}/personal/", otro, format="json")
        assert (r.status_code, r.json()["error"]["codigo"]) == (409, "usuario_ya_vinculado")

    def test_no_se_vincula_un_usuario_de_otra_organizacion_ni_inexistente(self, equipo):
        e, ajeno = equipo["e"], equipo["otra_org"]
        api = cliente_de("super")
        for usuario in (str(ajeno.pk), "00000000-0000-0000-0000-000000000000"):
            r = api.post(
                f"{BASE}/personal/", personal_json(e.emp_a1, usuario=usuario), format="json"
            )
            assert r.status_code == 400

    def test_vincular_exige_poder_ver_usuarios(self, equipo, nuevo_usuario):
        from apps.seguridad.models import Permiso, UsuarioPermiso
        from apps.seguridad.services import permisos_engine as motor

        e = equipo["e"]
        rrhh = nuevo_usuario(e.org_a, "rrhh", [e.emp_a1], [("ADMIN", None)])
        UsuarioPermiso.objects.sin_ambito().create(
            organizacion=e.org_a,
            usuario=rrhh,
            permiso=Permiso.objects.get(codigo="SEGURIDAD.USUARIOS.VER"),
            tipo="DENY",
            alcance="ORGANIZACION",
            motivo="Prueba: sin ver usuarios",
        )
        motor.invalidar_usuario(rrhh.pk)
        api = cliente_de("rrhh")
        con_vinculo = personal_json(e.emp_a1, usuario=str(equipo["tecnico"].pk))
        assert api.post(f"{BASE}/personal/", con_vinculo, format="json").status_code == 403
        # Sin vincular, el mismo usuario sí registra al trabajador.
        assert (
            api.post(f"{BASE}/personal/", personal_json(e.emp_a1), format="json").status_code == 201
        )

    def test_al_eliminar_al_trabajador_el_usuario_queda_libre(self, equipo):
        e, tecnico = equipo["e"], equipo["tecnico"]
        api = cliente_de("super")
        creado = api.post(
            f"{BASE}/personal/", personal_json(e.emp_a1, usuario=str(tecnico.pk)), format="json"
        ).json()
        assert api.delete(f"{BASE}/personal/{creado['id']}/").status_code == 204
        nuevo = personal_json(e.emp_a1, numero_documento="71234568", usuario=str(tecnico.pk))
        assert api.post(f"{BASE}/personal/", nuevo, format="json").status_code == 201
        assert Personal.objects.sin_ambito().filter(usuario=tecnico).count() == 1

    def test_editar_la_fecha_de_ingreso_queda_en_auditoria(self, equipo):
        e = equipo["e"]
        api = cliente_de("super")
        creado = api.post(f"{BASE}/personal/", personal_json(e.emp_a1), format="json").json()
        r = api.patch(
            f"{BASE}/personal/{creado['id']}/", {"fecha_ingreso": "2025-03-01"}, format="json"
        )
        assert r.status_code == 200
        evento = AuditoriaEvento.objects.filter(accion="personal.editado").latest("id")
        assert evento.detalle["fecha_ingreso"] == [None, "2025-03-01"]
