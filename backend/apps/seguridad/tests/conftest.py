import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from apps.core.tenant import limpiar_contexto
from apps.seguridad.services.usuarios import crear_usuario

PASSWORD = "Clave-Segura-2026!"


@pytest.fixture(autouse=True)
def _aislar_estado_global():
    """Caché (bloqueos, sesiones revocadas) y contexto de tenant limpios entre pruebas."""
    for alias in ("default", "throttle"):
        caches[alias].clear()
    limpiar_contexto()
    yield
    limpiar_contexto()


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def usuario_a(escenario):
    """Usuario de la organización A con acceso a las dos empresas A1 y A2."""
    return crear_usuario(
        organizacion=escenario.org_a,
        username="ana",
        email="Ana@Ejemplo.com",
        password=PASSWORD,
        nombres="Ana",
        apellidos="Pérez",
        empresa_ids=[escenario.emp_a1.pk, escenario.emp_a2.pk],
        cargo="Vendedora",
    )


@pytest.fixture
def api():
    return APIClient()


def iniciar_sesion(api, identificador="ana", password=PASSWORD, **extra):
    datos = {"identificador": identificador, "password": password, **extra}
    return api.post("/api/v1/seguridad/auth/login/", datos, format="json")


@pytest.fixture
def login(api):
    return lambda *a, **kw: iniciar_sesion(api, *a, **kw)


def autenticar(api, access):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
@pytest.fixture
def rbac(escenario):
    """Catálogo sincronizado y roles plantilla sembrados en las dos organizaciones."""
    from apps.seguridad.services.catalogo import sembrar_roles_plantilla, sincronizar_catalogo

    sincronizar_catalogo()
    sembrar_roles_plantilla(escenario.org_a)
    sembrar_roles_plantilla(escenario.org_b)
    return escenario


@pytest.fixture
def nuevo_usuario(rbac):
    """Fábrica: ``nuevo_usuario(org, "nombre", [empresas], roles=[("VENDEDOR", empresa|None)])``."""
    from apps.seguridad.services.roles import asignar_rol_de_sistema

    def crear(organizacion, username, empresas, roles=()):
        usuario = crear_usuario(
            organizacion=organizacion,
            username=username,
            email=f"{username}@ejemplo.com",
            password=PASSWORD,
            empresa_ids=[e.pk for e in empresas],
        )
        for codigo, empresa in roles:
            asignar_rol_de_sistema(usuario, codigo, empresa)
        return usuario

    return crear


def cliente_de(username: str) -> APIClient:
    """Cliente ya autenticado como ``username`` (clientes móviles: refresh en el cuerpo)."""
    api = APIClient()
    respuesta = iniciar_sesion(api, username, plataforma="MOVIL")
    assert respuesta.status_code == 200, respuesta.content
    autenticar(api, respuesta.json()["access"])
    return api
