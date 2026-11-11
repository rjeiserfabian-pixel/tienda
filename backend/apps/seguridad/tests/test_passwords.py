import pytest

from apps.seguridad.models import HistorialPassword, MotivoRevocacion, Sesion
from apps.seguridad.tests.conftest import PASSWORD, autenticar, iniciar_sesion

pytestmark = pytest.mark.django_db

URL = "/api/v1/seguridad/auth/cambiar-password/"
NUEVA = "Otra-Clave-Distinta-77#"


@pytest.fixture
def autenticado(usuario_a, api, login):
    autenticar(api, login(plataforma="MOVIL").json()["access"])
    return api


def cambiar(api, actual=PASSWORD, nueva=NUEVA):
    return api.post(URL, {"actual": actual, "nueva": nueva}, format="json")


def test_cambia_la_clave_y_ya_se_entra_con_la_nueva(autenticado, usuario_a, api):
    assert cambiar(autenticado).status_code == 204
    from rest_framework.test import APIClient

    assert iniciar_sesion(APIClient(), password=NUEVA).status_code == 200
    assert iniciar_sesion(APIClient(), password=PASSWORD).status_code == 401
    usuario_a.refresh_from_db()
    assert usuario_a.password_cambiada_en is not None


def test_exige_la_clave_actual(autenticado):
    r = cambiar(autenticado, actual="no-es-esta-clave")
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "password_actual_incorrecta"


@pytest.mark.parametrize("debil", ["corta1", "1234567890123", "password1234", "ana"])
def test_aplica_los_validadores_de_django(autenticado, debil):
    r = cambiar(autenticado, nueva=debil)
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "validacion"


def test_no_permite_repetir_la_clave_actual(autenticado):
    assert cambiar(autenticado, nueva=PASSWORD).json()["error"]["codigo"] == "password_reutilizada"


def test_no_permite_volver_a_una_de_las_ultimas_cinco(autenticado, usuario_a):
    claves = [f"Clave-Numero-{i}-Segura!" for i in range(1, 6)]
    anterior = PASSWORD
    for clave in claves:
        assert cambiar(autenticado, actual=anterior, nueva=clave).status_code == 204
        anterior = clave
    # La primera ya salió del historial de 5 (quedan las últimas 5 de 6 registradas)...
    assert HistorialPassword.objects.filter(usuario=usuario_a).count() == 5
    assert cambiar(autenticado, actual=anterior, nueva=claves[1]).status_code == 400
    # ...y la original, de más de 5 cambios atrás, ya puede reutilizarse.
    assert cambiar(autenticado, actual=anterior, nueva=PASSWORD).status_code == 204


def test_cierra_las_otras_sesiones_pero_conserva_la_actual(autenticado, api):
    from rest_framework.test import APIClient

    otra = iniciar_sesion(APIClient(), plataforma="WEB").json()["sesion_id"]
    assert cambiar(autenticado).status_code == 204
    assert Sesion.objects.get(pk=otra).motivo_revocacion == MotivoRevocacion.CAMBIO_PASSWORD
    assert api.get("/api/v1/seguridad/me/").status_code == 200  # la sesión actual sigue viva


def test_marca_de_cambio_obligatorio_se_limpia(usuario_a, api, login):
    usuario_a.debe_cambiar_password = True
    usuario_a.save()
    assert login(plataforma="MOVIL").json()["usuario"]["debe_cambiar_password"] is True
    autenticar(api, login(plataforma="MOVIL").json()["access"])
    cambiar(api)
    usuario_a.refresh_from_db()
    assert usuario_a.debe_cambiar_password is False


def test_exige_autenticacion(api):
    assert cambiar(api).status_code == 401
