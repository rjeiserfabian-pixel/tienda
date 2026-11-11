"""Recibir un equipo: la orden nace en «Equipo recibido», con su historial y sus validaciones."""

from datetime import timedelta
from decimal import Decimal  # noqa: F401

import pytest
from django.utils import timezone

from apps.mantenimiento.models import Cliente, EstadoRegistro, Personal
from apps.servicio_tecnico import recepcion
from apps.servicio_tecnico.catalogos import ACCESORIOS, REVISIONES
from apps.servicio_tecnico.exceptions import OrdenInvalida
from apps.servicio_tecnico.models import (
    AccesorioEquipo,
    Equipo,
    EstadoOrden,
    HistorialEstado,
    ItemChecklist,
    OrdenAccesorio,
    OrdenRevision,
    OrdenServicio,
    ResultadoRevision,
    TipoEquipo,
)

pytestmark = pytest.mark.django_db


def _nuevo(taller, **extra):
    datos = {
        "tipo": TipoEquipo.objects.get(codigo="PC"),
        "marca": "Dell",
        "modelo": "Optiplex",
        "numero_serie": " abc 123 ",
    }
    datos.update(extra)
    return recepcion.EquipoEntrada(**datos)


def _recibir(taller, **extra):
    datos = {
        "empresa": taller.empresa,
        "cliente": taller.cliente,
        "equipo": _nuevo(taller),
        "falla_reportada": "No da video",
    }
    datos.update(extra)
    return recepcion.recibir_equipo(**datos)


class TestRecibir:
    def test_crea_la_orden_recibida_con_su_historial(self, taller):
        orden = _recibir(taller)
        assert (orden.estado, orden.codigo) == (EstadoOrden.RECIBIDO, "OS-000001")
        cambio = HistorialEstado.objects.get(orden=orden)
        assert (cambio.estado_anterior, cambio.estado_nuevo) == ("", EstadoOrden.RECIBIDO)
        assert cambio.creado_por_id == taller.e.usuario_id

    def test_crea_el_equipo_nuevo_con_los_datos_limpios(self, taller):
        orden = _recibir(taller)
        assert orden.equipo.numero_serie == "ABC 123"
        assert orden.equipo.cliente_id == taller.cliente.pk
        assert (orden.equipo.marca, orden.equipo.modelo) == ("Dell", "Optiplex")

    def test_usa_un_equipo_ya_registrado_sin_duplicarlo(self, taller):
        antes = Equipo.objects.count()
        a = _recibir(taller, equipo=recepcion.EquipoEntrada(existente=taller.equipo))
        b = _recibir(taller, equipo=recepcion.EquipoEntrada(existente=taller.equipo))
        assert Equipo.objects.count() == antes
        assert a.equipo_id == b.equipo_id == taller.equipo.pk
        assert OrdenServicio.objects.filter(equipo=taller.equipo).count() == 2

    def test_no_acepta_el_equipo_de_otro_cliente(self, taller):
        otro = Cliente.objects.sin_ambito().create(
            organizacion=taller.org, tipo_documento="DNI", numero_documento="40123456", nombre="Ana"
        )
        with pytest.raises(OrdenInvalida, match="no es de este cliente"):
            _recibir(taller, cliente=otro, equipo=recepcion.EquipoEntrada(existente=taller.equipo))

    def test_guarda_accesorios_revisiones_y_clave(self, taller):
        cargador = AccesorioEquipo.objects.get(codigo="CARGADOR")
        enciende = ItemChecklist.objects.get(codigo="ENCIENDE")
        orden = _recibir(
            taller,
            clave_equipo="1234",
            estado_fisico="Rayón en la tapa",
            accesorios=[
                recepcion.AccesorioEntrada(accesorio=cargador, cantidad=1),
                recepcion.AccesorioEntrada(nombre="  Mouse   gamer ", cantidad=2, detalle="Rojo"),
            ],
            revisiones=[
                recepcion.RevisionEntrada(item=enciende, resultado=ResultadoRevision.FALLA)
            ],
        )
        assert [a.nombre for a in OrdenAccesorio.objects.filter(orden=orden)] == [
            cargador.nombre,
            "Mouse gamer",
        ]
        revision = OrdenRevision.objects.get(orden=orden)
        assert (revision.nombre, revision.resultado) == (enciende.nombre, "FALLA")
        orden.refresh_from_db()
        assert orden.clave_equipo == "1234"

    def test_numera_por_empresa(self, taller):
        a = _recibir(taller)
        b = _recibir(taller)
        c = _recibir(taller, empresa=taller.otra_empresa)
        assert (a.numero, b.numero, c.numero) == (1, 2, 1)

    def test_si_algo_falla_no_queda_nada(self, taller):
        ordenes, equipos = OrdenServicio.objects.count(), Equipo.objects.count()
        with pytest.raises(OrdenInvalida):
            _recibir(
                taller,
                accesorios=[recepcion.AccesorioEntrada(nombre="Mouse", cantidad=500)],
            )
        assert (OrdenServicio.objects.count(), Equipo.objects.count()) == (ordenes, equipos)
        assert not HistorialEstado.objects.filter(estado_nuevo=EstadoOrden.RECIBIDO).exists()


class TestValidaciones:
    def test_la_falla_es_obligatoria(self, taller):
        with pytest.raises(OrdenInvalida, match="falla"):
            _recibir(taller, falla_reportada="  no ")

    def test_equipo_nuevo_pide_tipo_y_marca_o_modelo(self, taller):
        with pytest.raises(OrdenInvalida, match="tipo de equipo"):
            _recibir(taller, equipo=recepcion.EquipoEntrada(marca="HP"))
        with pytest.raises(OrdenInvalida, match="marca o el modelo"):
            _recibir(
                taller,
                equipo=recepcion.EquipoEntrada(tipo=TipoEquipo.objects.get(codigo="PC")),
            )

    def test_tipo_de_equipo_inactivo(self, taller):
        tipo = TipoEquipo.objects.get(codigo="PC")
        tipo.estado = EstadoRegistro.INACTIVO
        tipo.save()
        with pytest.raises(OrdenInvalida, match="inactivo"):
            _recibir(taller, equipo=recepcion.EquipoEntrada(tipo=tipo, marca="HP"))

    def test_cliente_inactivo(self, taller):
        taller.cliente.estado = EstadoRegistro.INACTIVO
        taller.cliente.save()
        with pytest.raises(OrdenInvalida, match="cliente"):
            _recibir(taller)

    def test_el_tecnico_debe_ser_del_area_tecnica_de_la_empresa(self, taller):
        administrativo = Personal.objects.create(
            empresa=taller.empresa,
            tipo_documento="DNI",
            numero_documento="41234567",
            nombres="Eva",
            apellidos="Ríos",
            area="ADMINISTRACION",
        )
        with pytest.raises(OrdenInvalida, match="técnico"):
            _recibir(taller, tecnico=administrativo)
        with pytest.raises(OrdenInvalida, match="técnico"):
            _recibir(taller, empresa=taller.otra_empresa, tecnico=taller.personal)

    def test_fecha_prometida_no_puede_ser_pasada(self, taller):
        ayer = timezone.localdate() - timedelta(days=1)
        with pytest.raises(OrdenInvalida, match="fecha prometida"):
            _recibir(taller, fecha_promesa=ayer)
        orden = _recibir(taller, fecha_promesa=timezone.localdate() + timedelta(days=3))
        assert orden.fecha_promesa is not None

    def test_prioridad_invalida(self, taller):
        with pytest.raises(OrdenInvalida, match="prioridad"):
            _recibir(taller, prioridad="MAXIMA")

    def test_revision_repetida(self, taller):
        item = ItemChecklist.objects.get(codigo="ENCIENDE")
        with pytest.raises(OrdenInvalida, match="repetida"):
            _recibir(
                taller,
                revisiones=[
                    recepcion.RevisionEntrada(item=item, resultado="OK"),
                    recepcion.RevisionEntrada(item=item, resultado="FALLA"),
                ],
            )

    def test_accesorio_inactivo_o_cantidad_invalida(self, taller):
        mouse = AccesorioEquipo.objects.get(codigo="MOUSE")
        mouse.estado = EstadoRegistro.INACTIVO
        mouse.save()
        with pytest.raises(OrdenInvalida, match="accesorios"):
            _recibir(taller, accesorios=[recepcion.AccesorioEntrada(accesorio=mouse)])
        with pytest.raises(OrdenInvalida, match="cantidad"):
            _recibir(taller, accesorios=[recepcion.AccesorioEntrada(nombre="Cable", cantidad=0)])

    def test_accesorio_sin_nombre(self, taller):
        with pytest.raises(OrdenInvalida, match="nombre"):
            _recibir(taller, accesorios=[recepcion.AccesorioEntrada(nombre="  ")])

    def test_los_catalogos_de_fabrica_alcanzan_para_un_ingreso_completo(self, taller):
        accesorios = [
            recepcion.AccesorioEntrada(accesorio=a) for a in AccesorioEquipo.objects.all()
        ]
        revisiones = [
            recepcion.RevisionEntrada(item=i, resultado="OK") for i in ItemChecklist.objects.all()
        ]
        orden = _recibir(taller, accesorios=accesorios, revisiones=revisiones)
        assert orden.accesorios.count() == len(ACCESORIOS)
        assert orden.revisiones.count() == len(REVISIONES)
