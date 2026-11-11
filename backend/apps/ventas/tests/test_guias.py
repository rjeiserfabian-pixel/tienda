"""Guías de remisión: qué viaja, hacia dónde y quién lo lleva; sin pasar nunca de lo vendido."""

import itertools
from datetime import timedelta
from decimal import Decimal as D

import pytest

from apps.inventario.models import SaldoStock
from apps.seguridad.tests.conftest import cliente_de
from apps.ventas import guias, servicios
from apps.ventas.exceptions import VentaInvalida, VentaNoAnulable
from apps.ventas.models import GuiaRemision

pytestmark = pytest.mark.django_db

BASE = "/api/v1/ventas"
_claves = itertools.count(1)


@pytest.fixture
def venta(tienda):
    p = tienda.producto("Laptop", costo="50", precios={"PUBLICO": "100"})
    v = tienda.vender([tienda.linea(p, 4)], [tienda.cobro(tienda.efectivo, "472.00")])
    comp = v.comprobantes.get()
    return type("V", (), {"venta": v, "comp": comp, "linea": comp.lineas.get(), "producto": p})


def guia(tienda, venta, cantidad=1, **extra):
    datos = {
        "lineas": [(venta.linea, D(str(cantidad)))],
        "punto_partida": "Jr. Lima 123, Tarapoto",
        "punto_llegada": "Av. Grau 456, Moyobamba",
        "fecha_traslado": tienda.entorno.hoy,
        "modalidad": "02",
        "placa": "ABC-123",
        "conductor_nombre": "Luis Soto",
        "usuario_nombre": "Rosa",
    }
    return guias.crear_guia(venta.comp, **{**datos, **extra})


class TestCrear:
    def test_emite_la_guia_con_su_serie_y_sin_mover_stock(self, tienda, venta):
        antes = SaldoStock.objects.get(producto=venta.producto, empresa=tienda.a).cantidad
        g = guia(tienda, venta, 2)
        assert g.numero_completo == "T001-00000001" and g.estado == "EMITIDO"
        assert (g.destinatario_nombre, g.placa, g.bultos) == ("CLIENTES VARIOS", "ABC-123", 1)
        (ln,) = g.lineas.all()
        assert (ln.descripcion, ln.cantidad) == ("Laptop", D("2"))
        assert SaldoStock.objects.get(producto=venta.producto, empresa=tienda.a).cantidad == antes

    def test_los_envios_parciales_no_pasan_de_lo_vendido(self, tienda, venta):
        guia(tienda, venta, 3)
        pendiente = guias.pendiente_de_enviar(venta.comp)[0]
        assert (pendiente["enviado"], pendiente["pendiente"]) == (D("3"), D("1"))
        with pytest.raises(VentaInvalida, match="solo falta enviar 1"):
            guia(tienda, venta, 2)
        assert guia(tienda, venta, 1).numero == 2

    def test_anular_una_guia_libera_lo_que_enviaba(self, tienda, venta):
        g = guia(tienda, venta, 4)
        assert guias.pendiente_de_enviar(venta.comp)[0]["pendiente"] == D("0")
        guias.anular_guia(g, motivo="Se canceló el viaje")
        assert guias.pendiente_de_enviar(venta.comp)[0]["pendiente"] == D("4")
        assert GuiaRemision.objects.sin_ambito().get().estado == "ANULADO"

    def test_transporte_publico_exige_al_transportista_y_privado_la_placa(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="transportista"):
            guia(tienda, venta, modalidad="01")
        g = guia(
            tienda,
            venta,
            modalidad="01",
            transportista_nombre="Transportes El Rápido SAC",
            transportista_documento="20512345678",
            placa="",
            conductor_nombre="",
        )
        assert g.modalidad == "01"
        with pytest.raises(VentaInvalida, match="placa"):
            guia(tienda, venta, placa="", modalidad="02")

    @pytest.mark.parametrize(
        ("datos", "mensaje"),
        [
            ({"punto_llegada": ""}, "desde dónde y hasta dónde"),
            ({"bultos": 0}, "bultos"),
            ({"peso_kg": D("-1")}, "peso"),
            ({"motivo": "99"}, "motivo"),
            ({"lineas": []}, "qué se envía"),
        ],
    )
    def test_valida_los_datos(self, tienda, venta, datos, mensaje):
        with pytest.raises(VentaInvalida, match=mensaje):
            guia(tienda, venta, **datos)

    def test_la_fecha_de_traslado_no_es_anterior_a_hoy(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="anterior a hoy"):
            guia(tienda, venta, fecha_traslado=tienda.entorno.hoy - timedelta(days=1))

    def test_sin_serie_de_guia_no_se_emite(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("09")
        ).update(estado="INACTIVO")
        with pytest.raises(VentaInvalida, match="serie"):
            guia(tienda, venta)

    def test_un_comprobante_con_guias_vigentes_no_se_anula(self, tienda, venta):
        g = guia(tienda, venta)
        with pytest.raises(VentaNoAnulable, match="guías de remisión"):
            servicios.anular_comprobante(venta.comp, motivo="Error")
        guias.anular_guia(g, motivo="Error de datos")
        servicios.anular_comprobante(venta.comp, motivo="Error")

    def test_cada_empresa_emite_las_guias_de_su_comprobante(self, tienda):
        pb = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"}, stock={tienda.b: 10})
        v = tienda.vender(
            [tienda.linea(pb, 1, empresa=tienda.b)], [tienda.cobro(tienda.efectivo, "59.00")]
        )
        comp = v.comprobantes.get()
        g = guias.crear_guia(
            comp,
            lineas=[(comp.lineas.get(), D("1"))],
            punto_partida="Jr. Lima 123, Tarapoto",
            punto_llegada="Av. Grau 456, Moyobamba",
            fecha_traslado=tienda.entorno.hoy,
            modalidad="02",
            placa="XYZ-987",
            conductor_nombre="Ana Ruiz",
        )
        assert (g.empresa, g.serie) == (tienda.b, "T002")


def emitir(usuario, comprobante_id, cuerpo):
    return cliente_de(usuario).post(
        f"{BASE}/comprobantes/{comprobante_id}/guia-remision/",
        cuerpo,
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"guia-{next(_claves):06d}",
    )


def cuerpo(tienda, venta, **extra):
    base = {
        "lineas": [{"linea": venta.linea.pk, "cantidad": "2"}],
        "fecha_traslado": str(tienda.entorno.hoy),
        "modalidad": "02",
        "punto_partida": "Jr. Lima 123, Tarapoto",
        "punto_llegada": "Av. Grau 456, Moyobamba",
        "placa": "abc-123",
        "conductor_nombre": "Luis Soto",
        "bultos": 2,
        "peso_kg": "15.5",
    }
    return {**base, **extra}


class TestApi:
    def test_propone_los_datos_y_emite(self, tienda, venta):
        c = cliente_de("vendedor")
        envio = c.get(f"{BASE}/comprobantes/{venta.comp.pk}/envio/").json()
        assert envio["lineas"][0]["pendiente"] == "4.000" and envio["destinatario"]
        r = emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta))
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["numero_completo"] == "T001-00000001" and d["placa"] == "ABC-123"
        assert (d["bultos"], d["peso_kg"], d["emisor"]["ruc"]) == (2, "15.500", tienda.a.ruc)
        # Para dibujar el logo de la empresa en la guía impresa (la imagen se pide aparte).
        assert d["emisor"]["empresa"] == tienda.a.pk and d["emisor"]["tiene_logo"] is False
        assert d["lineas"][0]["cantidad"] == "2.000"
        despues = c.get(f"{BASE}/comprobantes/{venta.comp.pk}/envio/").json()
        assert despues["lineas"][0]["pendiente"] == "2.000"

    def test_el_contador_no_emite_pero_ve(self, tienda, venta):
        assert emitir("contador", venta.comp.pk, cuerpo(tienda, venta)).status_code == 403
        emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta))
        r = cliente_de("contador").get(f"{BASE}/guias-remision/", {"empresa": tienda.a.pk})
        assert r.status_code == 200 and r.json()["count"] == 1

    def test_un_reintento_con_la_misma_clave_no_emite_dos_guias(self, tienda, venta):
        c = cliente_de("vendedor")
        for _ in range(2):
            r = c.post(
                f"{BASE}/comprobantes/{venta.comp.pk}/guia-remision/",
                cuerpo(tienda, venta),
                format="json",
                HTTP_IDEMPOTENCY_KEY="guia-clave-001",
            )
            assert r.status_code == 201
        assert GuiaRemision.objects.sin_ambito().count() == 1

    def test_errores_claros_y_anulacion(self, tienda, venta):
        r = emitir(
            "vendedor",
            venta.comp.pk,
            cuerpo(tienda, venta, lineas=[{"linea": venta.linea.pk, "cantidad": "9"}]),
        )
        assert r.status_code == 400 and "solo falta enviar" in r.json()["error"]["mensaje"]
        g = emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta)).json()
        url = f"{BASE}/guias-remision/{g['id']}/anular/"
        assert cliente_de("vendedor").post(url, {"motivo": ""}, format="json").status_code == 400
        r = cliente_de("vendedor").post(url, {"motivo": "Se canceló"}, format="json")
        assert r.status_code == 200 and r.json()["estado"] == "ANULADO"
        lista = cliente_de("vendedor").get(
            f"{BASE}/guias-remision/", {"empresa": tienda.a.pk, "estado": "ANULADO"}
        )
        assert lista.json()["count"] == 1


def vehiculo_ajeno(tienda):
    """Un vehículo de OTRA organización (se crea sin pasar por el ámbito activo)."""
    from apps.core.tenant import contexto_tenant
    from apps.mantenimiento.models import Vehiculo

    org_b = tienda.entorno.e.org_b
    with contexto_tenant(org_b.pk, []):
        return Vehiculo.objects.create(organizacion=org_b, placa="ZZZ999")


def catalogos(tienda):
    """Una empresa de transporte, un conductor y dos vehículos de la organización."""
    from types import SimpleNamespace

    from apps.mantenimiento.models import Conductor, EmpresaTransporte, Vehiculo

    org = tienda.a.organizacion_id
    return SimpleNamespace(
        org=org,
        empresa=EmpresaTransporte.objects.sin_ambito().create(
            organizacion_id=org,
            nombre="Transportes El Rápido SAC",
            ruc="20100070970",
            registro_mtc="MTC-001",
            certificado_inspeccion="CI-77",
        ),
        conductor=Conductor.objects.sin_ambito().create(
            organizacion_id=org,
            nombre="Henry Ramírez",
            tipo_documento="DNI",
            numero_documento="43512345",
            licencia="Q43512345",
        ),
        vehiculo=Vehiculo.objects.sin_ambito().create(
            organizacion_id=org, placa="0315WS", marca="Yamaha", modelo="XTZ150"
        ),
        remolque=Vehiculo.objects.sin_ambito().create(
            organizacion_id=org, placa="REM456", marca="Carreta"
        ),
    )


class TestSerieElegible:
    def _otra_serie(self, tienda, serie="T009"):
        from apps.mantenimiento.models import SerieComprobante

        return SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("09"), serie=serie
        )

    def test_con_varias_series_hay_que_elegir(self, tienda, venta):
        otra = self._otra_serie(tienda)
        with pytest.raises(VentaInvalida, match="elija una"):
            guia(tienda, venta)
        g = guia(tienda, venta, serie_id=otra.pk)
        assert g.numero_completo == "T009-00000001"

    def test_una_serie_de_otra_empresa_o_inactiva_no_sirve(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        ajena = SerieComprobante.objects.sin_ambito().get(empresa=tienda.b, serie="T002")
        with pytest.raises(VentaInvalida, match="no sirve"):
            guia(tienda, venta, serie_id=ajena.pk)
        otra = self._otra_serie(tienda)
        SerieComprobante.objects.sin_ambito().filter(pk=otra.pk).update(estado="INACTIVO")
        assert guia(tienda, venta).numero_completo == "T001-00000001"  # solo queda una activa

    def test_sin_serie_dice_cual_crear(self, tienda, venta):
        from apps.mantenimiento.models import SerieComprobante

        SerieComprobante.objects.sin_ambito().filter(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("09")
        ).update(estado="INACTIVO")
        with pytest.raises(VentaInvalida, match="por ejemplo T001"):
            guia(tienda, venta)


class TestTransporteDeLasListas:
    def test_publico_con_la_empresa_de_transporte_elegida(self, tienda, venta):
        c = catalogos(tienda)
        g = guia(
            tienda, venta, modalidad="01", transportista=c.empresa, placa="", conductor_nombre=""
        )
        assert (g.transportista_nombre, g.transportista_documento) == (
            "Transportes El Rápido SAC",
            "20100070970",
        )
        assert (g.transportista_mtc, g.transportista_certificado) == ("MTC-001", "CI-77")
        assert g.transportista_id == c.empresa.pk

    def test_lo_guardado_no_cambia_si_despues_se_edita_el_catalogo(self, tienda, venta):
        c = catalogos(tienda)
        g = guia(tienda, venta, modalidad="01", transportista=c.empresa, placa="")
        c.empresa.nombre = "Otro nombre SAC"
        c.empresa.save()
        g.refresh_from_db()
        assert g.transportista_nombre == "Transportes El Rápido SAC"

    def test_privado_lleva_la_propia_empresa_con_conductor_y_vehiculos(self, tienda, venta):
        c = catalogos(tienda)
        g = guia(
            tienda,
            venta,
            conductor=c.conductor,
            vehiculo=c.vehiculo,
            vehiculos_secundarios=[c.remolque],
            placa="",
            conductor_nombre="",
        )
        assert (g.transportista_nombre, g.transportista_documento) == (
            tienda.a.razon_social,
            tienda.a.ruc,
        )
        assert (g.conductor_nombre, g.conductor_documento, g.conductor_licencia) == (
            "Henry Ramírez",
            "43512345",
            "Q43512345",
        )
        assert (g.placa, g.vehiculo_descripcion) == ("0315WS", "0315WS · Yamaha XTZ150")
        assert g.placas_secundarias == ["REM456"]

    def test_un_vehiculo_secundario_no_repite_al_principal(self, tienda, venta):
        c = catalogos(tienda)
        with pytest.raises(VentaInvalida, match="secundario"):
            guia(tienda, venta, vehiculo=c.vehiculo, vehiculos_secundarios=[c.vehiculo])

    def test_en_vehiculo_m1_o_l_no_se_exige_conductor_ni_placa(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="placa"):
            guia(tienda, venta, placa="", conductor_nombre="")
        g = guia(tienda, venta, placa="", conductor_nombre="", traslado_m1_l=True)
        assert g.traslado_m1_l is True and g.placa == "" and g.conductor_nombre == ""

    def test_lo_de_otra_organizacion_o_inactivo_no_se_puede_elegir(self, tienda, venta):
        ajeno = vehiculo_ajeno(tienda)
        with pytest.raises(VentaInvalida, match="no existe"):
            guia(tienda, venta, vehiculo=ajeno)
        c = catalogos(tienda)
        c.conductor.estado = "INACTIVO"
        c.conductor.save()
        with pytest.raises(VentaInvalida, match="inactivo"):
            guia(tienda, venta, conductor=c.conductor, placa="")


class TestPesosAlmacenYDestinatario:
    def test_el_peso_total_es_la_suma_de_las_lineas(self, tienda, venta):
        g = guia(tienda, venta, lineas=[(venta.linea, D("2"), D("3.250"))], peso_kg=None)
        assert g.peso_kg == D("3.250") and g.lineas.get().peso_kg == D("3.250")

    def test_el_peso_escrito_manda_sobre_la_suma(self, tienda, venta):
        g = guia(tienda, venta, lineas=[(venta.linea, D("2"), D("3.250"))], peso_kg=D("10"))
        assert g.peso_kg == D("10") and g.lineas.get().peso_kg == D("3.250")

    @pytest.mark.parametrize("peso", [D("-1"), D("1.2345")])
    def test_el_peso_de_una_linea_se_valida(self, tienda, venta, peso):
        with pytest.raises(VentaInvalida, match="peso"):
            guia(tienda, venta, lineas=[(venta.linea, D("1"), peso)])

    def test_el_almacen_de_origen_sale_de_las_lineas(self, tienda, venta):
        g = guia(tienda, venta)
        assert g.almacen_origen == tienda.almacen(tienda.a)

    def test_el_almacen_de_otra_empresa_no_sirve(self, tienda, venta):
        with pytest.raises(VentaInvalida, match="almacén"):
            guia(tienda, venta, almacen_origen=tienda.almacen(tienda.b))

    def test_el_destinatario_por_defecto_es_el_cliente_de_la_venta(self, tienda):
        cliente = tienda.cliente("1000")
        p = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"})
        v = tienda.vender(
            [tienda.linea(p, 2)],
            [tienda.cobro(tienda.efectivo, "118.00")],
            tipo_comprobante="01",
            cliente=cliente,
        )
        comp = v.comprobantes.get()
        g = guias.crear_guia(
            comp,
            lineas=[(comp.lineas.get(), D("2"))],
            punto_partida="Jr. Lima 123, Tarapoto",
            punto_llegada="Av. Grau 456, Moyobamba",
            fecha_traslado=tienda.entorno.hoy,
            modalidad="02",
            placa="ABC-123",
            conductor_nombre="Luis",
        )
        assert (g.destinatario_id, g.destinatario_tipo_documento, g.destinatario_documento) == (
            cliente.pk,
            "RUC",
            "20100000017",
        )

    def test_se_puede_enviar_a_otro_cliente_registrado(self, tienda, venta):
        otro = tienda.cliente("0", numero="71234567", tipo="DNI", nombre="Ana Ruiz")
        g = guia(tienda, venta, destinatario=otro)
        assert (g.destinatario_nombre, g.destinatario_tipo_documento) == (otro.nombre, "DNI")
        assert (g.destinatario_documento, g.destinatario_id) == ("71234567", otro.pk)


class TestUbigeo:
    def test_se_guarda_el_de_partida_y_el_de_llegada(self, tienda, venta):
        g = guia(tienda, venta, ubigeo_partida="220901", ubigeo_llegada="150101")
        assert (g.ubigeo_partida, g.ubigeo_llegada) == ("220901", "150101")

    def test_es_opcional(self, tienda, venta):
        g = guia(tienda, venta)
        assert (g.ubigeo_partida, g.ubigeo_llegada) == ("", "")

    @pytest.mark.parametrize("codigo", ["999999", "2209", "22090a"])
    def test_debe_existir_en_la_lista_del_inei(self, tienda, venta, codigo):
        with pytest.raises(VentaInvalida, match="ubigeo"):
            guia(tienda, venta, ubigeo_llegada=codigo)


class TestEnviables:
    URL = f"{BASE}/comprobantes/enviables/"

    def test_busca_comprobantes_con_algo_por_enviar(self, tienda, venta):
        c = cliente_de("vendedor")
        r = c.get(self.URL, {"empresa": tienda.a.pk}).json()
        assert r["count"] == 1
        fila = r["results"][0]
        assert (fila["id"], fila["numero_completo"]) == (venta.comp.pk, venta.comp.numero_completo)
        for q, cuenta in (
            (venta.comp.serie, 1),
            (venta.comp.numero_completo, 1),
            ("zzz", 0),
        ):
            assert c.get(self.URL, {"empresa": tienda.a.pk, "q": q}).json()["count"] == cuenta, q
        assert c.get(self.URL, {"empresa": tienda.b.pk}).json()["count"] == 0

    def test_deja_de_salir_al_enviarse_todo_y_vuelve_si_se_anula(self, tienda, venta):
        g = guia(tienda, venta, 4)
        c = cliente_de("vendedor")
        assert c.get(self.URL, {"empresa": tienda.a.pk}).json()["count"] == 0
        anulada = c.post(
            f"{BASE}/guias-remision/{g.pk}/anular/",
            {"motivo": "Se canceló el viaje"},
            format="json",
        )
        assert anulada.status_code == 200
        assert c.get(self.URL, {"empresa": tienda.a.pk}).json()["count"] == 1

    def test_no_trae_comprobantes_anulados_y_exige_permiso_y_empresa(self, tienda, venta):
        servicios.anular_venta(venta.venta, motivo="Error")
        assert cliente_de("vendedor").get(self.URL).status_code == 400
        assert cliente_de("contador").get(self.URL, {"empresa": tienda.a.pk}).status_code == 403
        r = cliente_de("admin").get(self.URL, {"empresa": tienda.a.pk})
        assert r.json()["count"] == 0


class TestApiNueva:
    def test_el_envio_propone_remitente_destinatario_partida_y_series(self, tienda, venta):
        almacen = tienda.almacen(tienda.a)
        type(almacen).objects.sin_ambito().filter(pk=almacen.pk).update(
            direccion="Jr. Sofía Delgado 156, Tarapoto", ubigeo="220901"
        )
        d = cliente_de("vendedor").get(f"{BASE}/comprobantes/{venta.comp.pk}/envio/").json()
        assert d["remitente"] == {"nombre": tienda.a.razon_social, "ruc": tienda.a.ruc}
        assert d["punto_partida"] == "Jr. Sofía Delgado 156, Tarapoto"
        assert d["ubigeo_partida"] == {
            "codigo": "220901",
            "nombre": "SAN MARTÍN - SAN MARTÍN - TARAPOTO",
        }
        assert d["almacen_origen"] == {"id": almacen.pk, "nombre": almacen.nombre}
        assert d["destinatario"] == d["destinatario_datos"]["nombre"]
        assert [s["serie"] for s in d["series"]] == ["T001"] and d["serie_sugerida"]
        assert d["series"][0]["proximo"] == "T001-00000001"
        assert d["se_puede_enviar"] is True and d["tipo_nombre"]
        (ln,) = d["lineas"]
        assert ln["codigo"] and ln["pendiente"] == "4.000"

    def test_la_llegada_se_propone_con_la_direccion_y_el_ubigeo_del_cliente(self, tienda):
        cliente = tienda.cliente("1000", direccion="JR. MIGUEL GRAU 242", ubigeo="150101")
        p = tienda.producto("Mouse", costo="20", precios={"PUBLICO": "50"})
        v = tienda.vender(
            [tienda.linea(p, 1)],
            [tienda.cobro(tienda.efectivo, "59.00")],
            tipo_comprobante="01",
            cliente=cliente,
        )
        comp = v.comprobantes.get()
        d = cliente_de("vendedor").get(f"{BASE}/comprobantes/{comp.pk}/envio/").json()
        assert d["punto_llegada"] == "JR. MIGUEL GRAU 242"
        assert d["ubigeo_llegada"]["codigo"] == "150101"
        assert d["destinatario_datos"]["documento"] == "20100000017"

    def test_emite_con_los_catalogos_el_ubigeo_la_serie_y_los_pesos(self, tienda, venta):
        c = catalogos(tienda)
        from apps.mantenimiento.models import SerieComprobante

        otra = SerieComprobante.objects.sin_ambito().create(
            empresa=tienda.a, tipo_comprobante=tienda.tipo("09"), serie="T009"
        )
        cuerpo_nuevo = {
            "lineas": [{"linea": venta.linea.pk, "cantidad": "3", "peso_kg": "4.5"}],
            "fecha_traslado": str(tienda.entorno.hoy),
            "modalidad": "02",
            "serie_guia": otra.pk,
            "punto_partida": "Jr. Sofía Delgado 156, Tarapoto",
            "ubigeo_partida": "220901",
            "punto_llegada": "Jr. Miguel Grau 242, Tarapoto",
            "ubigeo_llegada": "220901",
            "conductor": c.conductor.pk,
            "vehiculo": c.vehiculo.pk,
            "vehiculos_secundarios": [c.remolque.pk],
        }
        r = emitir("vendedor", venta.comp.pk, cuerpo_nuevo)
        assert r.status_code == 201, r.content
        d = r.json()
        assert d["numero_completo"] == "T009-00000001"
        assert (d["conductor_nombre"], d["placa"], d["placas_secundarias"]) == (
            "Henry Ramírez",
            "0315WS",
            ["REM456"],
        )
        assert d["ubigeo_partida_nombre"] == "SAN MARTÍN - SAN MARTÍN - TARAPOTO"
        assert d["almacen_origen"] == tienda.almacen(tienda.a).pk
        assert (d["peso_kg"], d["lineas"][0]["peso_kg"]) == ("4.500", "4.500")
        assert d["transportista_nombre"] == tienda.a.razon_social  # transporte privado

    def test_publico_con_la_empresa_de_transporte(self, tienda, venta):
        c = catalogos(tienda)
        r = emitir(
            "vendedor",
            venta.comp.pk,
            cuerpo(tienda, venta, modalidad="01", transportista=c.empresa.pk, placa=""),
        )
        assert r.status_code == 201, r.content
        d = r.json()
        assert (d["transportista_documento"], d["transportista_mtc"]) == ("20100070970", "MTC-001")

    def test_errores_de_lo_elegido(self, tienda, venta):
        ajeno = vehiculo_ajeno(tienda)
        inexistente = emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta, vehiculo=ajeno.pk))
        assert inexistente.status_code == 400 and "vehiculo" in str(inexistente.json()).lower()
        malo = emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta, ubigeo_llegada="999999"))
        assert malo.status_code == 400 and "ubigeo" in str(malo.json()).lower()
        secundario = emitir(
            "vendedor", venta.comp.pk, cuerpo(tienda, venta, vehiculos_secundarios=[ajeno.pk])
        )
        assert secundario.status_code == 400

    def test_el_listado_trae_usuario_documento_transporte_y_busca(self, tienda, venta):
        g = emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta)).json()
        c = cliente_de("vendedor")
        url = f"{BASE}/guias-remision/"
        fila = c.get(url, {"empresa": tienda.a.pk}).json()["results"][0]
        assert fila["usuario"] == "vendedor" or fila["usuario"]
        assert (fila["bultos"], fila["peso_kg"], fila["placa"]) == (2, "15.500", "ABC-123")
        assert fila["comprobante_tipo"] and fila["comprobante_fecha"]
        for q, cuenta in (
            (g["numero_completo"], 1),
            ("T001-1", 1),
            (venta.comp.serie, 1),
            ("abc", 1),
            ("zzz", 0),
        ):
            assert c.get(url, {"empresa": tienda.a.pk, "q": q}).json()["count"] == cuenta, q

    def test_el_excel_baja_lo_filtrado(self, tienda, venta):
        from io import BytesIO

        from openpyxl import load_workbook

        emitir("vendedor", venta.comp.pk, cuerpo(tienda, venta))
        url = f"{BASE}/guias-remision/excel/"
        assert cliente_de("vendedor").get(url, {"empresa": tienda.a.pk}).status_code == 403
        r = cliente_de("admin").get(url, {"empresa": tienda.a.pk})
        assert r.status_code == 200 and "spreadsheetml" in r["Content-Type"]
        assert r["Content-Disposition"].startswith('attachment; filename="ventas-guias-remision_')
        hoja = load_workbook(BytesIO(r.content)).active
        filas = [[c.value for c in fila] for fila in hoja.iter_rows(min_row=6)]
        assert filas[0][1] == "Guía" and filas[1][1] == "T001-00000001"
        assert filas[1][8] == "Privado" and float(filas[1][15]) == 15.5
        vacio = cliente_de("admin").get(url, {"empresa": tienda.a.pk, "q": "zzz"})
        assert len(list(load_workbook(BytesIO(vacio.content)).active.iter_rows(min_row=6))) == 1
