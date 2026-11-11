import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction

from apps.organizacion.models import ConfiguracionEmpresa, Empresa, Organizacion, Sucursal
from apps.organizacion.services.creacion import crear_organizacion_con_empresa
from apps.organizacion.validators import ruc_es_valido, validar_ruc
from conftest import ruc_valido

pytestmark = pytest.mark.django_db


class TestRuc:
    def test_acepta_un_ruc_con_digito_verificador_correcto(self):
        assert ruc_es_valido(ruc_valido("2010000001"))

    @pytest.mark.parametrize(
        "ruc",
        ["", "123", "20100000012", "abcdefghijk", "30100000015", "2010000001a"],
    )
    def test_rechaza_rucs_invalidos(self, ruc):
        assert not ruc_es_valido(ruc)
        with pytest.raises(ValidationError):
            validar_ruc(ruc)


class TestCreacion:
    def test_crea_toda_la_estructura(self):
        creada = crear_organizacion_con_empresa(
            nombre_organizacion="Grupo Demo",
            razon_social="Demo SAC",
            ruc=ruc_valido("2012345678"),
        )
        assert creada.empresa.organizacion_id == creada.organizacion.pk
        assert creada.sucursal.empresa_id == creada.empresa.pk
        assert creada.configuracion.regimen_igv == "NORMAL"
        assert creada.configuracion.igv_compras_al_costo is False
        assert creada.configuracion.moneda == "PEN"
        # La organización nace con los catálogos fiscales de SUNAT y la tasa vigente del IGV.
        from apps.mantenimiento.fiscal import tasa_vigente
        from apps.mantenimiento.models import AfectacionIGV, TipoComprobante

        org = creada.organizacion.pk
        assert TipoComprobante.objects.sin_ambito().filter(organizacion_id=org).count() == 15
        assert AfectacionIGV.objects.sin_ambito().filter(organizacion_id=org).count() == 19
        assert tasa_vigente(org, "IGV") == 18

    def test_ruc_invalido_no_deja_nada_a_medias(self):
        with pytest.raises(ValidationError):
            crear_organizacion_con_empresa(
                nombre_organizacion="Grupo Demo", razon_social="Demo SAC", ruc="12345678901"
            )
        assert not Organizacion.objects.filter(nombre="Grupo Demo").exists()

    def test_el_ruc_es_unico(self):
        ruc = ruc_valido("2012345678")
        crear_organizacion_con_empresa(nombre_organizacion="Uno", razon_social="Uno", ruc=ruc)
        with pytest.raises(IntegrityError), transaction.atomic():
            crear_organizacion_con_empresa(nombre_organizacion="Dos", razon_social="Dos", ruc=ruc)
        assert not Organizacion.objects.filter(nombre="Dos").exists()

    def test_el_ruc_de_una_empresa_eliminada_se_puede_reutilizar(self):
        ruc = ruc_valido("2012345678")
        creada = crear_organizacion_con_empresa(
            nombre_organizacion="Uno", razon_social="U", ruc=ruc
        )
        creada.empresa.delete()
        crear_organizacion_con_empresa(nombre_organizacion="Dos", razon_social="D", ruc=ruc)

    def test_el_codigo_de_sucursal_es_unico_por_empresa(self):
        creada = crear_organizacion_con_empresa(
            nombre_organizacion="Uno", razon_social="U", ruc=ruc_valido("2012345678")
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Sucursal(empresa=creada.empresa, nombre="Otra", codigo="001").save()

    def test_comando_crear_organizacion(self):
        call_command(
            "crear_organizacion",
            nombre="Desde comando",
            razon_social="Cmd SAC",
            ruc=ruc_valido("2099999999"),
        )
        assert Empresa.objects.sin_ambito().filter(razon_social="Cmd SAC").exists()

    def test_comando_con_datos_invalidos_da_error_claro(self):
        with pytest.raises(CommandError):
            call_command("crear_organizacion", nombre="X", razon_social="Y", ruc="1")


class TestCredencialesSunat:
    def test_las_credenciales_se_guardan_cifradas(self):
        from django.db import connection

        creada = crear_organizacion_con_empresa(
            nombre_organizacion="Uno", razon_social="U", ruc=ruc_valido("2012345678")
        )
        config = creada.configuracion
        config.sunat_clave_sol = "SECRETO-SOL"
        config.save()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sunat_clave_sol FROM organizacion_configuracionempresa WHERE id = %s",
                [config.pk],
            )
            assert "SECRETO-SOL" not in cursor.fetchone()[0]
        assert (
            ConfiguracionEmpresa.objects.sin_ambito().get(pk=config.pk).sunat_clave_sol
            == "SECRETO-SOL"
        )
