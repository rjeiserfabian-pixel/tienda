"""Borrado lógico, huella de auditoría y documentos inmutables."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.exceptions import (
    DocumentoInmutableError,
    DocumentoYaAnulado,
    MotivoObligatorio,
)
from apps.core.tenant import contexto_tenant
from apps.core.tests.app_prueba.models import ComprobantePrueba, ItemOrganizacion

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx(escenario):
    with contexto_tenant(
        escenario.org_a.pk, [escenario.emp_a1.pk], usuario_id=escenario.usuario_id
    ) as contexto:
        yield contexto


class TestBorradoLogico:
    def test_delete_oculta_pero_no_borra_fisicamente(self, ctx):
        item = ItemOrganizacion.objects.create(nombre="x")
        item.delete()
        assert ItemOrganizacion.objects.count() == 0
        assert ItemOrganizacion.objects.con_eliminados().count() == 1

    def test_delete_masivo_tambien_es_logico(self, ctx):
        ItemOrganizacion.objects.create(nombre="1")
        ItemOrganizacion.objects.create(nombre="2")
        ItemOrganizacion.objects.all().delete()
        assert ItemOrganizacion.objects.count() == 0
        assert ItemOrganizacion.objects.con_eliminados().count() == 2

    def test_restaurar(self, ctx):
        item = ItemOrganizacion.objects.create(nombre="x")
        item.delete()
        eliminado = ItemOrganizacion.objects.con_eliminados().get(pk=item.pk)
        eliminado.restaurar()
        assert ItemOrganizacion.objects.filter(pk=item.pk).exists()

    def test_los_eliminados_siguen_aislados_por_organizacion(self, escenario, ctx):
        ItemOrganizacion.objects.create(nombre="x").delete()
        with contexto_tenant(escenario.org_b.pk, []):
            assert ItemOrganizacion.objects.con_eliminados().count() == 0


class TestHuellaDeAuditoria:
    def test_registra_quien_crea_y_quien_modifica(self, escenario, ctx):
        item = ItemOrganizacion.objects.create(nombre="x")
        assert item.creado_por_id == escenario.usuario_id
        assert item.actualizado_por_id == escenario.usuario_id
        assert item.creado_en and item.actualizado_en

    def test_save_con_update_fields_actualiza_la_huella(self, ctx):
        item = ItemOrganizacion.objects.create(nombre="x")
        pasado = timezone.now() - timedelta(days=1)  # evita depender de la resolución del reloj
        ItemOrganizacion.objects.sin_ambito().filter(pk=item.pk).update(actualizado_en=pasado)
        item.refresh_from_db()
        item.nombre = "y"
        item.save(update_fields=["nombre"])
        item.refresh_from_db()
        assert item.actualizado_en > pasado
        assert item.actualizado_por_id == ctx.usuario_id


class TestDocumentoInmutable:
    def _emitir(self, escenario):
        return ComprobantePrueba.objects.create(empresa=escenario.emp_a1, numero="F001-1")

    def test_no_se_edita_un_documento_emitido(self, escenario, ctx):
        doc = self._emitir(escenario)
        doc.numero = "F001-2"
        with pytest.raises(DocumentoInmutableError):
            doc.save()

    def test_no_se_elimina_un_documento_emitido(self, escenario, ctx):
        doc = self._emitir(escenario)
        with pytest.raises(DocumentoInmutableError):
            doc.delete()

    def test_update_y_delete_masivos_estan_bloqueados(self, escenario, ctx):
        self._emitir(escenario)
        with pytest.raises(DocumentoInmutableError):
            ComprobantePrueba.objects.all().update(numero="X")
        with pytest.raises(DocumentoInmutableError):
            ComprobantePrueba.objects.all().delete()

    def test_anular_requiere_motivo(self, escenario, ctx):
        doc = self._emitir(escenario)
        with pytest.raises(MotivoObligatorio):
            doc.anular(motivo="   ")

    def test_anular_registra_quien_cuando_y_por_que(self, escenario, ctx):
        doc = self._emitir(escenario)
        doc.anular(motivo="Error en el monto")
        doc.refresh_from_db()
        assert doc.estado == ComprobantePrueba.Estado.ANULADO
        assert doc.motivo_anulacion == "Error en el monto"
        assert doc.anulado_por_id == escenario.usuario_id
        assert doc.anulado_en is not None

    def test_no_se_anula_dos_veces(self, escenario, ctx):
        doc = self._emitir(escenario)
        doc.anular(motivo="uno")
        copia = ComprobantePrueba.objects.get(pk=doc.pk)
        with pytest.raises(DocumentoYaAnulado):
            copia.anular(motivo="dos")

    def test_tras_anular_sigue_inmutable(self, escenario, ctx):
        doc = self._emitir(escenario)
        doc.anular(motivo="uno")
        doc.numero = "otro"
        with pytest.raises(DocumentoInmutableError):
            doc.save()
