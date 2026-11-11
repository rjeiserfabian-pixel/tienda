"""API de órdenes y equipos: recibir, listar, ficha, permisos y aislamiento."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.auditoria.models import AuditoriaEvento
from apps.mantenimiento.models import Personal
from apps.seguridad.tests.conftest import cliente_de
from apps.servicio_tecnico import servicios
from apps.servicio_tecnico.models import (
    AccesorioEquipo,
    EstadoOrden,
    ItemChecklist,
    OrdenServicio,
    TipoEquipo,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/servicio-tecnico"


def _cuerpo(taller, **extra):
    datos = {
        "empresa": taller.empresa.pk,
        "cliente": taller.cliente.pk,
        "equipo": {
            "tipo": TipoEquipo.objects.sin_ambito().get(organizacion=taller.org, codigo="PC").pk,
            "marca": "Dell",
            "modelo": "Optiplex",
            "numero_serie": "xyz789",
        },
        "falla_reportada": "No da video",
    }
    datos.update(extra)
    return datos


def _enviar(api, cuerpo, clave=None):
    return api.post(
        f"{BASE}/ordenes/", cuerpo, format="json", HTTP_IDEMPOTENCY_KEY=clave or str(uuid.uuid4())
    )


class TestRecibir:
    def test_recepcion_registra_el_ingreso_completo(self, taller):
        api = cliente_de("admin")
        cargador = AccesorioEquipo.objects.sin_ambito().get(
            organizacion=taller.org, codigo="CARGADOR"
        )
        enciende = ItemChecklist.objects.sin_ambito().get(
            organizacion=taller.org, codigo="ENCIENDE"
        )
        r = _enviar(
            api,
            _cuerpo(
                taller,
                clave_equipo="patrón L",
                estado_fisico="Golpe en la esquina",
                accesorios=[{"accesorio": cargador.pk, "cantidad": 1}, {"nombre": "Mouse"}],
                revisiones=[{"item": enciende.pk, "resultado": "FALLA", "observacion": "Sin luz"}],
                tecnico=taller.personal.pk,
                prioridad="URGENTE",
                fecha_promesa=str(timezone.localdate() + timedelta(days=2)),
            ),
        )
        assert r.status_code == 201, r.content
        orden = r.json()
        assert (orden["codigo"], orden["estado"]) == ("OS-000001", "RECIBIDO")
        assert orden["tiene_clave"] is True
        assert "patrón" not in r.content.decode()  # la clave nunca viaja en la ficha
        assert [a["nombre"] for a in orden["accesorios"]] == [cargador.nombre, "Mouse"]
        assert orden["revisiones"][0]["resultado"] == "FALLA"
        assert orden["historial"][0]["estado_nuevo"] == "RECIBIDO"
        assert orden["tecnico_nombre"] == "Mario Quispe"
        assert orden["equipo_datos"]["numero_serie"] == "XYZ789"
        assert orden["emisor"]["ruc"] == taller.empresa.ruc

    def test_un_reintento_con_la_misma_clave_no_duplica(self, taller):
        api = cliente_de("admin")
        cuerpo = _cuerpo(taller)
        a = _enviar(api, cuerpo, clave="clave-repetida-0001")
        b = _enviar(api, cuerpo, clave="clave-repetida-0001")
        assert (a.status_code, b.status_code) == (201, 201)
        assert a.json()["id"] == b.json()["id"]
        assert b["Idempotency-Replayed"] == "true"
        assert OrdenServicio.objects.sin_ambito().count() == 1

    def test_sin_clave_de_idempotencia_se_rechaza(self, taller):
        r = cliente_de("admin").post(f"{BASE}/ordenes/", _cuerpo(taller), format="json")
        assert r.status_code == 400

    def test_falla_demasiado_corta(self, taller):
        r = _enviar(cliente_de("admin"), _cuerpo(taller, falla_reportada="no"))
        assert r.status_code == 400

    def test_equipo_ya_registrado(self, taller):
        r = _enviar(cliente_de("admin"), _cuerpo(taller, equipo={"id": taller.equipo.pk}))
        assert r.status_code == 201, r.content
        assert r.json()["equipo"] == taller.equipo.pk
        assert r.json()["n_ingresos_equipo"] == 1

    def test_datos_de_otra_organizacion_se_rechazan(self, taller):
        ajeno_cliente = taller.e.org_b
        from apps.core.tenant import limpiar_contexto
        from apps.mantenimiento.models import Cliente

        limpiar_contexto()  # el cliente ajeno se crea fuera del ámbito de la organización A
        ajeno = Cliente.objects.sin_ambito().create(
            organizacion=ajeno_cliente,
            tipo_documento="DNI",
            numero_documento="43211234",
            nombre="Otro",
        )
        api = cliente_de("admin")
        assert _enviar(api, _cuerpo(taller, cliente=ajeno.pk)).status_code == 400
        tipo_ajeno = TipoEquipo.objects.sin_ambito().filter(organizacion=ajeno_cliente).first()
        r = _enviar(api, _cuerpo(taller, equipo={"tipo": tipo_ajeno.pk, "marca": "HP"}))
        assert r.status_code == 400

    def test_tecnico_de_otra_empresa_se_rechaza(self, taller):
        r = _enviar(
            cliente_de("admin"),
            _cuerpo(taller, empresa=taller.otra_empresa.pk, tecnico=taller.personal.pk),
        )
        assert r.status_code == 400

    def test_el_vendedor_y_el_tecnico_no_reciben_equipos(self, taller):
        assert _enviar(cliente_de("vendedor"), _cuerpo(taller)).status_code == 403
        assert _enviar(cliente_de("tecnico"), _cuerpo(taller)).status_code == 403

    def test_empresa_sin_acceso(self, taller):
        r = _enviar(cliente_de("tecnico"), _cuerpo(taller, empresa=taller.otra_empresa.pk))
        assert r.status_code == 403


class TestListado:
    def test_lista_y_busca(self, taller):
        a = taller.orden()
        b = taller.orden(falla_reportada="Pantalla rota")
        api = cliente_de("admin")
        r = api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk})
        assert r.status_code == 200
        assert [o["id"] for o in r.json()["results"]] == [b.pk, a.pk]
        assert (
            api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk, "q": "OS-000001"}).json()[
                "count"
            ]
            == 1
        )
        assert (
            api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk, "q": "5cd123"}).json()[
                "count"
            ]
            == 2
        )
        assert (
            api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk, "q": "ramos"}).json()[
                "count"
            ]
            == 2
        )
        assert (
            api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk, "q": "zzz"}).json()["count"]
            == 0
        )

    def test_filtros(self, taller):
        a = taller.orden()
        b = taller.orden(estado=EstadoOrden.ENTREGADO)
        c = taller.orden(
            fecha_promesa=timezone.localdate() - timedelta(days=1), prioridad="URGENTE"
        )
        api = cliente_de("admin")
        base = {"empresa": taller.empresa.pk}

        def ids(**filtros):
            r = api.get(f"{BASE}/ordenes/", {**base, **filtros})
            assert r.status_code == 200, r.content
            return {o["id"] for o in r.json()["results"]}

        assert ids(estado="abiertas") == {a.pk, c.pk}
        assert ids(estado="ENTREGADO") == {b.pk}
        assert ids(atrasadas="1") == {c.pk}
        assert ids(prioridad="URGENTE") == {c.pk}
        assert ids(tecnico=taller.personal.pk) == {a.pk, b.pk, c.pk}
        hoy = str(timezone.localdate())
        assert ids(desde=hoy, hasta=hoy) == {a.pk, b.pk, c.pk}
        assert api.get(f"{BASE}/ordenes/", {**base, "estado": "NOEXISTE"}).status_code == 400
        assert api.get(f"{BASE}/ordenes/", {**base, "desde": "ayer"}).status_code == 400
        marcada = [
            o for o in api.get(f"{BASE}/ordenes/", base).json()["results"] if o["id"] == c.pk
        ]
        assert marcada[0]["atrasada"] is True

    def test_pagina_y_pide_la_empresa(self, taller):
        for _ in range(12):
            taller.orden()
        api = cliente_de("admin")
        r = api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk, "page_size": 10})
        assert (r.json()["count"], len(r.json()["results"])) == (12, 10)
        r = api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk, "page_size": 10, "page": 2})
        assert len(r.json()["results"]) == 2
        assert api.get(f"{BASE}/ordenes/").status_code == 400

    def test_el_tecnico_solo_ve_las_suyas(self, taller):
        suya = taller.orden()
        otro = Personal.objects.create(
            empresa=taller.empresa,
            tipo_documento="DNI",
            numero_documento="42345678",
            nombres="Luz",
            apellidos="Vega",
            area="TECNICO",
        )
        ajena = taller.orden(tecnico=otro)
        sin_tecnico = taller.orden(tecnico=None)
        api = cliente_de("tecnico")
        r = api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk})
        assert [o["id"] for o in r.json()["results"]] == [suya.pk]
        assert api.get(f"{BASE}/ordenes/{ajena.pk}/").status_code == 404
        assert api.get(f"{BASE}/ordenes/{sin_tecnico.pk}/").status_code == 404
        assert api.get(f"{BASE}/ordenes/{suya.pk}/").status_code == 200

    def test_el_vendedor_ve_todas_las_de_su_empresa_pero_no_las_de_otra(self, taller):
        a = taller.orden()
        b = taller.orden(empresa=taller.otra_empresa)
        api = cliente_de("vendedor")
        assert [
            o["id"]
            for o in api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk}).json()["results"]
        ] == [a.pk]
        assert api.get(f"{BASE}/ordenes/", {"empresa": taller.otra_empresa.pk}).status_code == 403
        assert (
            api.get(f"{BASE}/ordenes/{b.pk}/").status_code == 404
        )  # ni siquiera se sabe que existe

    def test_otra_organizacion_no_ve_nada(self, taller):
        orden = taller.orden()
        api = cliente_de("otra_org")
        assert api.get(f"{BASE}/ordenes/{orden.pk}/").status_code in (403, 404)
        assert api.get(f"{BASE}/ordenes/", {"empresa": taller.empresa.pk}).status_code == 403


class TestFicha:
    def test_el_historial_dice_quien_y_cuando(self, taller):
        orden = taller.orden()
        servicios.cambiar_estado(orden, EstadoOrden.EN_DIAGNOSTICO)
        r = cliente_de("admin").get(f"{BASE}/ordenes/{orden.pk}/")
        assert r.status_code == 200
        assert [h["estado_nuevo"] for h in r.json()["historial"]] == ["EN_DIAGNOSTICO"]
        assert r.json()["n_ingresos_equipo"] == 1

    def test_la_clave_solo_la_ve_quien_ejecuta_y_queda_en_auditoria(self, taller):
        orden = taller.orden(clave_equipo="mi-clave")
        r = cliente_de("tecnico").get(f"{BASE}/ordenes/{orden.pk}/clave/")
        assert (r.status_code, r.json()) == (200, {"clave": "mi-clave"})
        assert r["Cache-Control"] == "no-store"
        assert AuditoriaEvento.objects.filter(
            accion="servicio_tecnico.clave_consultada", recurso_id=str(orden.pk)
        ).exists()
        assert cliente_de("vendedor").get(f"{BASE}/ordenes/{orden.pk}/clave/").status_code == 403

    def test_el_tecnico_no_ve_la_clave_de_una_orden_ajena(self, taller):
        otro = Personal.objects.create(
            empresa=taller.empresa,
            tipo_documento="DNI",
            numero_documento="42345678",
            nombres="Luz",
            apellidos="Vega",
            area="TECNICO",
        )
        ajena = taller.orden(tecnico=otro, clave_equipo="secreta")
        assert cliente_de("tecnico").get(f"{BASE}/ordenes/{ajena.pk}/clave/").status_code == 404


class TestEquiposYConfiguracion:
    def test_equipos_del_cliente_con_sus_ingresos(self, taller):
        taller.orden()
        taller.orden()
        api = cliente_de("admin")
        r = api.get(
            f"{BASE}/equipos/", {"empresa": taller.empresa.pk, "cliente": taller.cliente.pk}
        )
        assert r.status_code == 200
        assert r.json()["results"][0]["n_ordenes"] == 2
        por_serie = api.get(f"{BASE}/equipos/", {"empresa": taller.empresa.pk, "serie": "5cd123"})
        assert por_serie.json()["count"] == 1
        assert (
            api.get(f"{BASE}/equipos/", {"empresa": taller.empresa.pk, "serie": "nada"}).json()[
                "count"
            ]
            == 0
        )

    def test_equipos_solo_para_recepcion(self, taller):
        assert (
            cliente_de("tecnico")
            .get(f"{BASE}/equipos/", {"empresa": taller.empresa.pk})
            .status_code
            == 403
        )

    def test_configuracion_trae_todo_lo_que_la_pantalla_necesita(self, taller):
        r = cliente_de("admin").get(f"{BASE}/configuracion/", {"empresa": taller.empresa.pk})
        assert r.status_code == 200
        datos = r.json()
        assert len(datos["tipos_equipo"]) == 9
        assert len(datos["revisiones"]) == 11
        assert [t["nombre"] for t in datos["tecnicos"]] == ["Mario Quispe"]
        assert datos["tecnicos"][0]["tiene_usuario"] is True
        assert {"valor": "REPARACION", "nombre": "Reparación"} in datos["categorias_servicio"]

    def test_configuracion_exige_empresa(self, taller):
        assert cliente_de("admin").get(f"{BASE}/configuracion/").status_code == 400
