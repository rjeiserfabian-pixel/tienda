"""Un modelo de prueba por ámbito nunca cruza datos (criterio de cierre de la Fase 1)."""

import pytest

from apps.core.exceptions import (
    ContextoTenantNoDefinido,
    EmpresaNoHabilitada,
    ViolacionAmbito,
)
from apps.core.tenant import contexto_tenant, obtener_contexto
from apps.core.tests.app_prueba.models import ItemEmpresa, ItemOrganizacion

pytestmark = pytest.mark.django_db


class TestAislamientoPorOrganizacion:
    def test_cada_organizacion_ve_solo_lo_suyo(self, escenario):
        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk]):
            ItemOrganizacion.objects.create(nombre="de A")
        with contexto_tenant(escenario.org_b.pk, [escenario.emp_b1.pk]):
            ItemOrganizacion.objects.create(nombre="de B")

        with contexto_tenant(escenario.org_a.pk, []):
            assert list(ItemOrganizacion.objects.values_list("nombre", flat=True)) == ["de A"]
        with contexto_tenant(escenario.org_b.pk, []):
            assert list(ItemOrganizacion.objects.values_list("nombre", flat=True)) == ["de B"]

    def test_no_se_puede_leer_por_id_un_registro_de_otra_organizacion(self, escenario):
        with contexto_tenant(escenario.org_b.pk, []):
            ajeno = ItemOrganizacion.objects.create(nombre="de B")
        with contexto_tenant(escenario.org_a.pk, []):
            with pytest.raises(ItemOrganizacion.DoesNotExist):
                ItemOrganizacion.objects.get(pk=ajeno.pk)

    def test_la_organizacion_se_toma_del_contexto_si_no_se_indica(self, escenario):
        with contexto_tenant(escenario.org_a.pk, []):
            item = ItemOrganizacion.objects.create(nombre="x")
        assert item.organizacion_id == escenario.org_a.pk

    def test_no_se_puede_crear_en_otra_organizacion(self, escenario):
        with contexto_tenant(escenario.org_a.pk, []):
            with pytest.raises(ViolacionAmbito):
                ItemOrganizacion(nombre="x", organizacion=escenario.org_b).save()

    def test_bulk_create_tambien_valida_el_ambito(self, escenario):
        with contexto_tenant(escenario.org_a.pk, []):
            with pytest.raises(ViolacionAmbito):
                ItemOrganizacion.objects.bulk_create(
                    [ItemOrganizacion(nombre="x", organizacion=escenario.org_b)]
                )

    def test_sin_contexto_falla_cerrado(self, escenario):
        assert obtener_contexto() is None
        with pytest.raises(ContextoTenantNoDefinido):
            list(ItemOrganizacion.objects.all())

    def test_sin_ambito_es_un_acceso_explicito(self, escenario):
        with contexto_tenant(escenario.org_a.pk, []):
            ItemOrganizacion.objects.create(nombre="de A")
        with contexto_tenant(escenario.org_b.pk, []):
            ItemOrganizacion.objects.create(nombre="de B")
        assert ItemOrganizacion.objects.sin_ambito().count() == 2


class TestAislamientoPorEmpresa:
    def test_solo_se_ven_las_empresas_habilitadas(self, escenario):
        todas = [escenario.emp_a1.pk, escenario.emp_a2.pk]
        with contexto_tenant(escenario.org_a.pk, todas):
            ItemEmpresa.objects.create(empresa=escenario.emp_a1, nombre="a1")
            ItemEmpresa.objects.create(empresa=escenario.emp_a2, nombre="a2")

        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk]):
            assert list(ItemEmpresa.objects.values_list("nombre", flat=True)) == ["a1"]
        with contexto_tenant(escenario.org_a.pk, todas):
            assert ItemEmpresa.objects.count() == 2

    def test_empresa_de_otra_organizacion_nunca_es_visible(self, escenario):
        with contexto_tenant(escenario.org_b.pk, [escenario.emp_b1.pk]):
            ItemEmpresa.objects.create(empresa=escenario.emp_b1, nombre="b1")
        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk, escenario.emp_a2.pk]):
            assert ItemEmpresa.objects.count() == 0

    def test_la_empresa_es_obligatoria_y_explicita(self, escenario):
        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk]):
            with pytest.raises(ViolacionAmbito):
                ItemEmpresa(nombre="sin empresa").save()

    def test_no_se_puede_crear_en_empresa_no_habilitada(self, escenario):
        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk]):
            with pytest.raises(EmpresaNoHabilitada):
                ItemEmpresa(empresa=escenario.emp_a2, nombre="x").save()

    def test_no_se_puede_mover_un_registro_a_empresa_no_habilitada(self, escenario):
        with contexto_tenant(escenario.org_a.pk, [escenario.emp_a1.pk]):
            item = ItemEmpresa.objects.create(empresa=escenario.emp_a1, nombre="x")
            item.empresa = escenario.emp_a2
            with pytest.raises(EmpresaNoHabilitada):
                item.save()

    def test_sin_contexto_falla_cerrado(self, escenario):
        with pytest.raises(ContextoTenantNoDefinido):
            list(ItemEmpresa.objects.all())
