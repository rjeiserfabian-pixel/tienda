import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.db import connection
from django.test import override_settings

from apps.core import crypto
from apps.core.tenant import contexto_tenant
from apps.core.tests.app_prueba.models import SecretoPrueba

pytestmark = pytest.mark.django_db


def test_cifrar_y_descifrar():
    cifrado = crypto.cifrar("clave-sol-123")
    assert cifrado != "clave-sol-123"
    assert cifrado.startswith("1:")
    assert crypto.descifrar(cifrado) == "clave-sol-123"


def test_dato_corrupto_o_sin_formato_falla_con_error_controlado():
    with pytest.raises(crypto.ErrorDescifrado):
        crypto.descifrar("sin-formato")
    with pytest.raises(crypto.ErrorDescifrado):
        crypto.descifrar("1:token-invalido")


def test_el_campo_guarda_cifrado_y_lee_en_claro(escenario):
    with contexto_tenant(escenario.org_a.pk, []):
        obj = SecretoPrueba.objects.create(secreto="mi-clave")
        with connection.cursor() as cursor:
            cursor.execute("SELECT secreto FROM app_prueba_secretoprueba WHERE id = %s", [obj.pk])
            crudo = cursor.fetchone()[0]
        assert "mi-clave" not in crudo
        assert SecretoPrueba.objects.get(pk=obj.pk).secreto == "mi-clave"


def test_rotacion_de_clave_conserva_los_datos(escenario, settings):
    with contexto_tenant(escenario.org_a.pk, []):
        obj = SecretoPrueba.objects.create(secreto="mi-clave")  # cifrado con versión 1

    settings.CIFRADO_CLAVE_ACTUAL = "2"
    call_command("rotar_clave_cifrado")

    with connection.cursor() as cursor:
        cursor.execute("SELECT secreto FROM app_prueba_secretoprueba WHERE id = %s", [obj.pk])
        assert cursor.fetchone()[0].startswith("2:")
    with contexto_tenant(escenario.org_a.pk, []):
        assert SecretoPrueba.objects.get(pk=obj.pk).secreto == "mi-clave"


def test_clave_desconocida_es_error_de_configuracion():
    from django.core.exceptions import ImproperlyConfigured

    with override_settings(CIFRADO_CLAVES={"1": Fernet.generate_key().decode()}):
        valor = crypto.cifrar("x")
    with override_settings(CIFRADO_CLAVES={"9": Fernet.generate_key().decode()}):
        with pytest.raises(ImproperlyConfigured):
            crypto.descifrar(valor)
