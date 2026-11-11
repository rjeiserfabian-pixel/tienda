"""Catálogos fiscales: tipos de comprobante, afectaciones y tasas del IGV, régimen y sugerencia."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.auditoria import servicios
from apps.mantenimiento import fiscal
from apps.mantenimiento.exceptions import AfectacionNoDisponible, TasaNoVigente
from apps.mantenimiento.models import (
    AfectacionIGV,
    Categoria,
    Cliente,
    Familia,
    Producto,
    Proveedor,
    TasaImpuesto,
    TipoComprobante,
    UnidadMedida,
)
from apps.organizacion.models import ConfiguracionEmpresa
from apps.seguridad.tests.conftest import cliente_de
from conftest import ruc_valido

pytestmark = pytest.mark.django_db

BASE = "/api/v1/mantenimiento"


@pytest.fixture(autouse=True)
def _auditoria_al_instante(monkeypatch):
    monkeypatch.setattr(servicios.transaction, "on_commit", lambda funcion: funcion())


@pytest.fixture
def equipo(rbac, nuevo_usuario):
    e = rbac
    return {
        "e": e,
        "super": nuevo_usuario(e.org_a, "super", [e.emp_a1, e.emp_a2], [("SUPERADMIN", None)]),
        "contador": nuevo_usuario(e.org_a, "contador", [e.emp_a1], [("CONTADOR", None)]),
        "almacenero": nuevo_usuario(e.org_a, "almacenero", [e.emp_a1], [("ALMACENERO", None)]),
        "vendedor": nuevo_usuario(e.org_a, "vendedor", [e.emp_a1], [("VENDEDOR", None)]),
        "otra_org": nuevo_usuario(e.org_b, "otra_org", [e.emp_b1], [("SUPERADMIN", None)]),
    }


def _hoy():
    return timezone.localdate()


def _regimen(empresa, regimen):
    configuracion, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=empresa)
    configuracion.regimen_igv = regimen
    configuracion.save()


def _afectacion(org, codigo):
    return AfectacionIGV.objects.sin_ambito().get(organizacion=org, codigo=codigo)


# ---------------------------------------------------------------------------
# Carga inicial
# ---------------------------------------------------------------------------
class TestCargaInicial:
    def test_cada_organizacion_trae_los_catalogos_de_sunat(self, equipo):
        org = equipo["e"].org_a
        assert TipoComprobante.objects.sin_ambito().filter(organizacion=org).count() == 15
        assert AfectacionIGV.objects.sin_ambito().filter(organizacion=org).count() == 19
        assert fiscal.tasa_vigente(org.pk, "IGV") == Decimal("18.00")

    def test_en_compras_se_ofrecen_gravado_exonerado_inafecto_e_ivap(self, equipo):
        org = equipo["e"].org_a
        codigos = set(
            AfectacionIGV.objects.sin_ambito()
            .filter(organizacion=org, aplica_compras=True)
            .values_list("codigo", flat=True)
        )
        assert codigos == {"10", "17", "20", "30"}

    def test_volver_a_cargar_no_repite_ni_pisa_lo_editado(self, equipo):
        org = equipo["e"].org_a
        factura = TipoComprobante.objects.sin_ambito().get(organizacion=org, codigo="01")
        factura.nombre = "Factura electrónica"
        factura.save()
        assert fiscal.sembrar_catalogos_fiscales(org.pk) == {
            "tipos_comprobante": 0,
            "afectaciones_igv": 0,
            "tasas": 0,
        }
        factura.refresh_from_db()
        assert factura.nombre == "Factura electrónica"

    def test_un_codigo_eliminado_no_se_vuelve_a_crear(self, equipo):
        org = equipo["e"].org_a
        TipoComprobante.objects.sin_ambito().get(organizacion=org, codigo="12").delete()
        assert fiscal.sembrar_catalogos_fiscales(org.pk)["tipos_comprobante"] == 0
        assert not TipoComprobante.objects.sin_ambito().filter(organizacion=org, codigo="12")

    def test_no_se_carga_una_tasa_de_ivap_sin_verificar(self, equipo):
        org = equipo["e"].org_a
        assert not TasaImpuesto.objects.sin_ambito().filter(organizacion=org, impuesto="IVAP")
        with pytest.raises(TasaNoVigente):
            fiscal.tasa_vigente(org.pk, "IVAP")


# ---------------------------------------------------------------------------
# Tasas con vigencia
# ---------------------------------------------------------------------------
class TestTasaVigente:
    def test_toma_la_ultima_ya_iniciada(self, equipo):
        org = equipo["e"].org_a
        for porcentaje, desde in (
            ("19.00", _hoy() - timedelta(days=10)),
            ("20.00", _hoy() + timedelta(days=5)),
        ):
            TasaImpuesto.objects.sin_ambito().create(
                organizacion=org,
                impuesto="IGV",
                porcentaje=Decimal(porcentaje),
                vigente_desde=desde,
            )
        assert fiscal.tasa_vigente(org.pk, "IGV") == Decimal("19.00")
        assert fiscal.tasa_vigente(org.pk, "IGV", _hoy() - timedelta(days=20)) == Decimal("18.00")
        assert fiscal.tasa_vigente(org.pk, "IGV", _hoy() + timedelta(days=6)) == Decimal("20.00")

    def test_antes_de_la_primera_tasa_avisa(self, equipo):
        with pytest.raises(TasaNoVigente):
            fiscal.tasa_vigente(equipo["e"].org_a.pk, "IGV", _hoy().replace(year=2005))

    def test_cada_organizacion_tiene_sus_tasas(self, equipo):
        e = equipo["e"]
        TasaImpuesto.objects.sin_ambito().create(
            organizacion=e.org_a,
            impuesto="IGV",
            porcentaje=Decimal("19"),
            vigente_desde=_hoy() - timedelta(days=1),
        )
        assert fiscal.tasa_vigente(e.org_a.pk, "IGV") == Decimal("19")
        assert fiscal.tasa_vigente(e.org_b.pk, "IGV") == Decimal("18")


# ---------------------------------------------------------------------------
# IGV que propone cada operación
# ---------------------------------------------------------------------------
class TestSugerencia:
    @pytest.mark.parametrize("zona", ["", "DENTRO", "FUERA"])
    @pytest.mark.parametrize("operacion", ["COMPRA", "VENTA"])
    def test_regimen_normal_siempre_es_gravado(self, equipo, zona, operacion):
        r = fiscal.sugerir_afectacion(empresa=equipo["e"].emp_a1, operacion=operacion, zona=zona)
        assert (r.afectacion.codigo, r.porcentaje) == ("10", Decimal("18.00"))

    @pytest.mark.parametrize(
        ("operacion", "zona", "codigo"),
        [
            ("COMPRA", "FUERA", "10"),  # a Lima: viene gravado
            ("COMPRA", "DENTRO", "20"),  # a un proveedor de la región: exonerado
            ("COMPRA", "", "10"),  # sin zona, las compras se toman como gravadas
            ("VENTA", "DENTRO", "20"),  # a un cliente de la región: exonerado
            ("VENTA", "FUERA", "10"),  # a un cliente de fuera: con IGV
            ("VENTA", "", "20"),  # sin zona, la venta de la empresa amazónica es exonerada
        ],
    )
    def test_regimen_amazonia_segun_la_zona(self, equipo, operacion, zona, codigo):
        _regimen(equipo["e"].emp_a1, "AMAZONIA")
        r = fiscal.sugerir_afectacion(empresa=equipo["e"].emp_a1, operacion=operacion, zona=zona)
        assert r.afectacion.codigo == codigo
        assert r.porcentaje == (Decimal("18.00") if codigo == "10" else Decimal("0"))
        assert r.motivo

    def test_la_afectacion_del_producto_manda_si_aplica(self, equipo):
        e = equipo["e"]
        _regimen(e.emp_a1, "AMAZONIA")
        producto = _producto(e.org_a)
        producto.afectacion_igv = _afectacion(e.org_a, "30")  # inafecto, vale en compras y ventas
        producto.save()
        r = fiscal.sugerir_afectacion(
            empresa=e.emp_a1, operacion="COMPRA", zona="FUERA", producto=producto
        )
        assert r.afectacion.codigo == "30"

    def test_si_la_del_producto_no_aplica_a_la_operacion_se_ignora(self, equipo):
        e = equipo["e"]
        producto = _producto(e.org_a)
        producto.afectacion_igv = _afectacion(e.org_a, "40")  # exportación: solo ventas
        producto.save()
        compra = fiscal.sugerir_afectacion(empresa=e.emp_a1, operacion="COMPRA", producto=producto)
        venta = fiscal.sugerir_afectacion(empresa=e.emp_a1, operacion="VENTA", producto=producto)
        assert (compra.afectacion.codigo, venta.afectacion.codigo) == ("10", "40")

    def test_una_afectacion_inactiva_se_avisa(self, equipo):
        e = equipo["e"]
        _regimen(e.emp_a1, "AMAZONIA")
        AfectacionIGV.objects.sin_ambito().filter(organizacion=e.org_a, codigo="20").update(
            estado="INACTIVO"
        )
        with pytest.raises(AfectacionNoDisponible):
            fiscal.sugerir_afectacion(empresa=e.emp_a1, operacion="VENTA", zona="DENTRO")

    def test_la_tasa_es_la_de_la_fecha(self, equipo):
        e = equipo["e"]
        TasaImpuesto.objects.sin_ambito().create(
            organizacion=e.org_a,
            impuesto="IGV",
            porcentaje=Decimal("19"),
            vigente_desde=_hoy() - timedelta(days=3),
        )
        hoy = fiscal.sugerir_afectacion(empresa=e.emp_a1, operacion="COMPRA")
        antes = fiscal.sugerir_afectacion(
            empresa=e.emp_a1, operacion="COMPRA", fecha=_hoy() - timedelta(days=30)
        )
        assert (hoy.porcentaje, antes.porcentaje) == (Decimal("19"), Decimal("18"))

    def test_la_operacion_debe_ser_compra_o_venta(self, equipo):
        with pytest.raises(ValueError, match="COMPRA o VENTA"):
            fiscal.sugerir_afectacion(empresa=equipo["e"].emp_a1, operacion="OTRA")


def _producto(org):
    familia = Familia.objects.sin_ambito().create(organizacion=org, nombre="General")
    categoria = Categoria.objects.sin_ambito().create(
        organizacion=org, familia=familia, nombre="Accesorios"
    )
    unidad = UnidadMedida.objects.sin_ambito().create(
        organizacion=org, nombre="Unidad", abreviatura="UND", codigo_sunat="NIU"
    )
    return Producto.objects.sin_ambito().create(
        organizacion=org, codigo="000001", nombre="Mouse", categoria=categoria, unidad=unidad
    )


# ---------------------------------------------------------------------------
# Serie y número según el tipo de comprobante
# ---------------------------------------------------------------------------
class TestSerieNumero:
    def _tipo(self, equipo, codigo):
        return TipoComprobante.objects.sin_ambito().get(
            organizacion=equipo["e"].org_a, codigo=codigo
        )

    @pytest.mark.parametrize("serie", ["F001", "f001", "E001", "FA12", "0001"])
    def test_series_validas_de_factura(self, equipo, serie):
        assert (
            fiscal.validar_serie_numero(self._tipo(equipo, "01"), serie, "1245")[0] == serie.upper()
        )

    @pytest.mark.parametrize("serie", ["B001", "FF", "F0001", "X001"])
    def test_series_invalidas_de_factura(self, equipo, serie):
        with pytest.raises(ValueError, match="no tiene el formato"):
            fiscal.validar_serie_numero(self._tipo(equipo, "01"), serie, "1")

    def test_boleta_acepta_b001_y_eb01(self, equipo):
        tipo = self._tipo(equipo, "03")
        assert fiscal.validar_serie_numero(tipo, "B001", "7")[0] == "B001"
        assert fiscal.validar_serie_numero(tipo, "EB01", "7")[0] == "EB01"

    def test_el_numero_electronico_son_hasta_8_digitos(self, equipo):
        tipo = self._tipo(equipo, "01")
        assert fiscal.validar_serie_numero(tipo, "F001", "00001245")[1] == "00001245"
        for malo in ("123456789", "12A4"):
            with pytest.raises(ValueError, match="8 dígitos"):
                fiscal.validar_serie_numero(tipo, "F001", malo)

    def test_un_tipo_sin_formato_acepta_cualquier_serie(self, equipo):
        assert fiscal.validar_serie_numero(self._tipo(equipo, "00"), "ABC-9", "X1")[0] == "ABC-9"


# ---------------------------------------------------------------------------
# API: tipos de comprobante
# ---------------------------------------------------------------------------
class TestApiTiposComprobante:
    def test_lista_y_filtra(self, equipo):
        api = cliente_de("vendedor")
        todos = api.get(f"{BASE}/tipos-comprobante/", {"page_size": 50}).json()
        assert todos["count"] == 15
        ventas = api.get(f"{BASE}/tipos-comprobante/", {"aplica_ventas": "1"}).json()["results"]
        assert {t["codigo"] for t in ventas} >= {"01", "03", "07", "08"}
        assert all(t["aplica_ventas"] for t in ventas)
        assert api.get(f"{BASE}/tipos-comprobante/", {"aplica_ventas": "si"}).status_code == 400

    def test_el_vendedor_no_los_cambia(self, equipo):
        api = cliente_de("vendedor")
        cuerpo = {"codigo": "05", "nombre": "Boleto", "abreviatura": "BOL5"}
        assert api.post(f"{BASE}/tipos-comprobante/", cuerpo, format="json").status_code == 403

    def test_el_contador_crea_y_edita(self, equipo):
        api = cliente_de("contador")
        r = api.post(
            f"{BASE}/tipos-comprobante/",
            {
                "codigo": "05",
                "nombre": " Boleto de viaje aéreo ",
                "abreviatura": "bva",
                "patron_serie": "[A-Z]{2}[0-9]{2}",
            },
            format="json",
        )
        assert r.status_code == 201, r.content
        nuevo = r.json()
        assert (nuevo["nombre"], nuevo["abreviatura"], nuevo["estado"]) == (
            "Boleto de viaje aéreo",
            "BVA",
            "ACTIVO",
        )
        r = api.patch(
            f"{BASE}/tipos-comprobante/{nuevo['id']}/", {"aplica_ventas": True}, format="json"
        )
        assert r.status_code == 200 and r.json()["aplica_ventas"] is True

    def test_trae_un_ejemplo_legible_de_la_serie(self, equipo):
        api = cliente_de("contador")
        tipos = {
            t["codigo"]: t
            for t in api.get(f"{BASE}/tipos-comprobante/", {"page_size": 50}).json()["results"]
        }
        assert (tipos["01"]["ejemplo_serie"], tipos["03"]["ejemplo_serie"]) == ("F001", "B001")
        assert tipos["02"]["ejemplo_serie"] == ""  # sin regla: serie libre
        r = api.patch(
            f"{BASE}/tipos-comprobante/{tipos['01']['id']}/",
            {"ejemplo_serie": " f 002 "},
            format="json",
        )
        assert r.status_code == 200 and r.json()["ejemplo_serie"] == "F002"

    def test_el_codigo_no_se_repite_ni_cambia(self, equipo):
        api = cliente_de("contador")
        repetido = {"codigo": "01", "nombre": "Otra", "abreviatura": "OT"}
        r = api.post(f"{BASE}/tipos-comprobante/", repetido, format="json")
        assert r.status_code == 400 and "codigo" in str(r.json()).lower()
        factura = api.get(f"{BASE}/tipos-comprobante/", {"q": "Factura"}).json()["results"][0]
        r = api.patch(f"{BASE}/tipos-comprobante/{factura['id']}/", {"codigo": "99"}, format="json")
        assert r.status_code == 400

    @pytest.mark.parametrize(
        "malo",
        [
            {"codigo": "A1"},
            {"codigo": "123"},
            {"patron_serie": "[F"},
            {"nombre": ""},
            {"abreviatura": ""},
        ],
    )
    def test_datos_invalidos(self, equipo, malo):
        cuerpo = {"codigo": "05", "nombre": "Boleto", "abreviatura": "BOL5", **malo}
        r = cliente_de("contador").post(f"{BASE}/tipos-comprobante/", cuerpo, format="json")
        assert r.status_code == 400, r.content

    def test_se_elimina_si_nadie_lo_uso_y_queda_auditado(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        api = cliente_de("super")
        creado = api.post(
            f"{BASE}/tipos-comprobante/",
            {"codigo": "05", "nombre": "Boleto", "abreviatura": "BOL5"},
            format="json",
        ).json()
        assert api.delete(f"{BASE}/tipos-comprobante/{creado['id']}/").status_code == 204
        acciones = set(AuditoriaEvento.objects.values_list("accion", flat=True))
        assert {"tipo_comprobante.creado", "tipo_comprobante.eliminado"} <= acciones

    def test_cada_organizacion_ve_los_suyos(self, equipo):
        otra = cliente_de("otra_org")
        propio = otra.get(f"{BASE}/tipos-comprobante/", {"page_size": 50}).json()
        assert propio["count"] == 15
        ids_a = set(
            TipoComprobante.objects.sin_ambito()
            .filter(organizacion=equipo["e"].org_a)
            .values_list("id", flat=True)
        )
        assert not ids_a & {t["id"] for t in propio["results"]}
        un_id_de_a = next(iter(ids_a))
        assert otra.get(f"{BASE}/tipos-comprobante/{un_id_de_a}/").status_code == 404


# ---------------------------------------------------------------------------
# API: afectaciones del IGV
# ---------------------------------------------------------------------------
class TestApiAfectaciones:
    def test_lista_el_catalogo_07(self, equipo):
        r = cliente_de("vendedor").get(f"{BASE}/afectaciones-igv/", {"page_size": 50}).json()
        assert r["count"] == 19
        gravado = next(a for a in r["results"] if a["codigo"] == "10")
        assert (gravado["grupo"], gravado["impuesto"]) == ("GRAVADO", "IGV")

    def test_no_se_crean_ni_se_eliminan(self, equipo):
        api = cliente_de("super")
        r = api.post(f"{BASE}/afectaciones-igv/", {"nombre": "X"}, format="json")
        assert r.status_code == 405
        una = api.get(f"{BASE}/afectaciones-igv/").json()["results"][0]
        assert api.delete(f"{BASE}/afectaciones-igv/{una['id']}/").status_code == 405

    def test_se_ajusta_donde_se_ofrece(self, equipo):
        api = cliente_de("contador")
        once = api.get(f"{BASE}/afectaciones-igv/", {"q": "Retiro por premio"}).json()["results"][0]
        r = api.patch(
            f"{BASE}/afectaciones-igv/{once['id']}/", {"aplica_compras": True}, format="json"
        )
        assert r.status_code == 200 and r.json()["aplica_compras"] is True

    def test_gravado_y_exonerado_no_se_desactivan(self, equipo):
        api = cliente_de("super")
        for codigo in ("10", "20"):
            fila = api.get(f"{BASE}/afectaciones-igv/", {"q": codigo}).json()["results"][0]
            r = api.patch(
                f"{BASE}/afectaciones-igv/{fila['id']}/", {"estado": "INACTIVO"}, format="json"
            )
            assert r.status_code == 400
            r = api.patch(
                f"{BASE}/afectaciones-igv/{fila['id']}/", {"aplica_ventas": False}, format="json"
            )
            assert r.status_code == 400

    def test_el_vendedor_no_las_cambia(self, equipo):
        api = cliente_de("vendedor")
        una = api.get(f"{BASE}/afectaciones-igv/").json()["results"][0]
        r = api.patch(f"{BASE}/afectaciones-igv/{una['id']}/", {"nombre": "X"}, format="json")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# API: tasas
# ---------------------------------------------------------------------------
class TestApiTasas:
    def test_lista_con_su_situacion(self, equipo):
        api = cliente_de("contador")
        api.post(
            f"{BASE}/tasas-impuesto/",
            {
                "impuesto": "IGV",
                "porcentaje": "19",
                "vigente_desde": (_hoy() - timedelta(days=2)).isoformat(),
            },
            format="json",
        )
        api.post(
            f"{BASE}/tasas-impuesto/",
            {
                "impuesto": "IGV",
                "porcentaje": "20",
                "vigente_desde": (_hoy() + timedelta(days=9)).isoformat(),
            },
            format="json",
        )
        filas = api.get(f"{BASE}/tasas-impuesto/", {"impuesto": "IGV"}).json()["results"]
        por_porcentaje = {f["porcentaje"]: f for f in filas}
        assert por_porcentaje["18.00"]["situacion"] == "ANTERIOR"
        assert por_porcentaje["19.00"]["situacion"] == "VIGENTE"
        assert por_porcentaje["20.00"]["situacion"] == "FUTURA"
        assert por_porcentaje["18.00"]["vigente_hasta"] == (_hoy() - timedelta(days=3)).isoformat()
        assert por_porcentaje["20.00"]["vigente_hasta"] is None

    @pytest.mark.parametrize(
        "malo",
        [
            {"porcentaje": "150"},
            {"porcentaje": "-1"},
            {"vigente_desde": "1999-12-31"},
            {"vigente_desde": "no es fecha"},
            {"impuesto": "ISC"},
        ],
    )
    def test_datos_invalidos(self, equipo, malo):
        cuerpo = {
            "impuesto": "IGV",
            "porcentaje": "19",
            "vigente_desde": _hoy().isoformat(),
            **malo,
        }
        assert (
            cliente_de("contador")
            .post(f"{BASE}/tasas-impuesto/", cuerpo, format="json")
            .status_code
            == 400
        )

    def test_no_se_repite_la_fecha_de_inicio(self, equipo):
        api = cliente_de("contador")
        cuerpo = {"impuesto": "IGV", "porcentaje": "19", "vigente_desde": "2011-03-01"}
        r = api.post(f"{BASE}/tasas-impuesto/", cuerpo, format="json")
        assert r.status_code == 400 and "vigente_desde" in str(r.json())

    def test_solo_se_quita_una_futura(self, equipo):
        api = cliente_de("super")
        futura = api.post(
            f"{BASE}/tasas-impuesto/",
            {
                "impuesto": "IGV",
                "porcentaje": "19",
                "vigente_desde": (_hoy() + timedelta(days=30)).isoformat(),
            },
            format="json",
        ).json()
        assert api.delete(f"{BASE}/tasas-impuesto/{futura['id']}/").status_code == 204
        vigente = api.get(f"{BASE}/tasas-impuesto/", {"impuesto": "IGV"}).json()["results"][0]
        assert api.delete(f"{BASE}/tasas-impuesto/{vigente['id']}/").status_code == 409
        assert fiscal.tasa_vigente(equipo["e"].org_a.pk, "IGV") == Decimal("18.00")

    def test_una_tasa_futura_se_edita_libremente(self, equipo):
        api = cliente_de("contador")
        futura = api.post(
            f"{BASE}/tasas-impuesto/",
            {
                "impuesto": "IGV",
                "porcentaje": "19",
                "vigente_desde": (_hoy() + timedelta(days=30)).isoformat(),
            },
            format="json",
        ).json()
        nueva_fecha = (_hoy() + timedelta(days=60)).isoformat()
        r = api.patch(
            f"{BASE}/tasas-impuesto/{futura['id']}/",
            {"porcentaje": "20", "vigente_desde": nueva_fecha},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert (r.json()["porcentaje"], r.json()["vigente_desde"]) == ("20.00", nueva_fecha)

    def test_una_tasa_ya_iniciada_se_corrige_si_ningun_documento_la_uso(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        api = cliente_de("contador")
        vigente = api.get(f"{BASE}/tasas-impuesto/", {"impuesto": "IGV"}).json()["results"][0]
        r = api.patch(
            f"{BASE}/tasas-impuesto/{vigente['id']}/", {"porcentaje": "17.5"}, format="json"
        )
        assert r.status_code == 200, r.content
        assert fiscal.tasa_vigente(equipo["e"].org_a.pk, "IGV") == Decimal("17.50")
        evento = AuditoriaEvento.objects.get(accion="tasa_impuesto.editado")
        assert evento.detalle["porcentaje"] == ["18.00", "17.50"]

    def test_no_se_cambia_el_impuesto_de_una_tasa(self, equipo):
        api = cliente_de("contador")
        fila = api.get(f"{BASE}/tasas-impuesto/").json()["results"][0]
        r = api.patch(f"{BASE}/tasas-impuesto/{fila['id']}/", {"impuesto": "IVAP"}, format="json")
        assert r.status_code == 400

    def test_al_editar_tampoco_se_repite_la_fecha(self, equipo):
        api = cliente_de("contador")
        otra = api.post(
            f"{BASE}/tasas-impuesto/",
            {
                "impuesto": "IGV",
                "porcentaje": "19",
                "vigente_desde": (_hoy() + timedelta(days=30)).isoformat(),
            },
            format="json",
        ).json()
        r = api.patch(
            f"{BASE}/tasas-impuesto/{otra['id']}/", {"vigente_desde": "2011-03-01"}, format="json"
        )
        assert r.status_code == 400 and "vigente_desde" in str(r.json())

    @pytest.mark.parametrize(
        "malo", [{"porcentaje": "150"}, {"porcentaje": "-2"}, {"vigente_desde": "1999-01-01"}]
    )
    def test_edicion_con_datos_invalidos(self, equipo, malo):
        api = cliente_de("contador")
        fila = api.get(f"{BASE}/tasas-impuesto/").json()["results"][0]
        assert (
            api.patch(f"{BASE}/tasas-impuesto/{fila['id']}/", malo, format="json").status_code
            == 400
        )

    def test_el_vendedor_no_edita_tasas(self, equipo):
        fila = cliente_de("vendedor").get(f"{BASE}/tasas-impuesto/").json()["results"][0]
        r = cliente_de("vendedor").patch(
            f"{BASE}/tasas-impuesto/{fila['id']}/", {"porcentaje": "10"}, format="json"
        )
        assert r.status_code == 403

    def test_permisos(self, equipo):
        cuerpo = {"impuesto": "IGV", "porcentaje": "19", "vigente_desde": _hoy().isoformat()}
        assert cliente_de("vendedor").get(f"{BASE}/tasas-impuesto/").status_code == 200
        assert (
            cliente_de("vendedor")
            .post(f"{BASE}/tasas-impuesto/", cuerpo, format="json")
            .status_code
            == 403
        )
        assert (
            cliente_de("almacenero")
            .post(f"{BASE}/tasas-impuesto/", cuerpo, format="json")
            .status_code
            == 403
        )


# ---------------------------------------------------------------------------
# API: régimen por empresa
# ---------------------------------------------------------------------------
class TestApiRegimen:
    def test_por_defecto_es_normal(self, equipo):
        e = equipo["e"]
        r = (
            cliente_de("vendedor")
            .get(f"{BASE}/igv/configuracion/", {"empresa": e.emp_a1.pk})
            .json()
        )
        assert (r["regimen_igv"], r["igv_compras_al_costo"]) == ("NORMAL", False)

    def test_el_contador_lo_cambia_y_queda_auditado(self, equipo):
        from apps.auditoria.models import AuditoriaEvento

        e = equipo["e"]
        api = cliente_de("contador")
        r = api.patch(
            f"{BASE}/igv/configuracion/",
            {"empresa": e.emp_a1.pk, "regimen_igv": "AMAZONIA", "igv_compras_al_costo": True},
            format="json",
        )
        assert r.status_code == 200, r.content
        assert (r.json()["regimen_igv"], r.json()["igv_compras_al_costo"]) == ("AMAZONIA", True)
        evento = AuditoriaEvento.objects.get(accion="empresa.igv_configurado")
        assert evento.detalle["regimen_igv"] == ["NORMAL", "AMAZONIA"]
        assert evento.detalle["igv_compras_al_costo"] == [False, True]
        # La otra empresa no cambió.
        # Y quien no tiene acceso a la otra empresa no puede consultarla.
        assert api.get(f"{BASE}/igv/configuracion/", {"empresa": e.emp_a2.pk}).status_code == 403
        otra = (
            cliente_de("super").get(f"{BASE}/igv/configuracion/", {"empresa": e.emp_a2.pk}).json()
        )
        assert otra["regimen_igv"] == "NORMAL"

    def test_el_vendedor_no_lo_cambia(self, equipo):
        e = equipo["e"]
        r = cliente_de("vendedor").patch(
            f"{BASE}/igv/configuracion/",
            {"empresa": e.emp_a1.pk, "regimen_igv": "AMAZONIA"},
            format="json",
        )
        assert r.status_code == 403

    def test_regimen_invalido_y_empresa_ajena(self, equipo):
        e = equipo["e"]
        api = cliente_de("contador")
        malo = api.patch(
            f"{BASE}/igv/configuracion/",
            {"empresa": e.emp_a1.pk, "regimen_igv": "X"},
            format="json",
        )
        assert malo.status_code == 400
        ajena = cliente_de("otra_org").get(f"{BASE}/igv/configuracion/", {"empresa": e.emp_a1.pk})
        assert ajena.status_code in (400, 403, 404)
        assert ConfiguracionEmpresa.objects.sin_ambito().filter(empresa=e.emp_a1).count() <= 1

    def test_exige_la_empresa(self, equipo):
        assert cliente_de("contador").get(f"{BASE}/igv/configuracion/").status_code == 400


# ---------------------------------------------------------------------------
# API: sugerencia
# ---------------------------------------------------------------------------
class TestApiSugerencia:
    def _pedir(self, usuario, **params):
        return cliente_de(usuario).get(f"{BASE}/igv/sugerencia/", params)

    def test_proveedor_de_lima_viene_gravado(self, equipo):
        e = equipo["e"]
        _regimen(e.emp_a1, "AMAZONIA")
        lima = Proveedor.objects.sin_ambito().create(
            organizacion=e.org_a,
            nombre="Importadora Lima",
            numero_documento=ruc_valido("2055555555"),
            tipo_documento="RUC",
            zona="FUERA",
        )
        local = Proveedor.objects.sin_ambito().create(
            organizacion=e.org_a,
            nombre="Ferretería Tarapoto",
            numero_documento=ruc_valido("2066666666"),
            tipo_documento="RUC",
            zona="DENTRO",
        )
        a = self._pedir(
            "vendedor", empresa=e.emp_a1.pk, operacion="COMPRA", proveedor=lima.pk
        ).json()
        b = self._pedir(
            "vendedor", empresa=e.emp_a1.pk, operacion="COMPRA", proveedor=local.pk
        ).json()
        assert (a["afectacion"]["codigo"], a["porcentaje"], a["zona"]) == ("10", "18.00", "FUERA")
        assert (b["afectacion"]["codigo"], b["porcentaje"], b["zona"]) == ("20", "0", "DENTRO")
        assert b["motivo"]

    def test_cliente_de_la_region_sale_exonerado_y_el_de_fuera_con_igv(self, equipo):
        e = equipo["e"]
        _regimen(e.emp_a1, "AMAZONIA")
        dentro = Cliente.objects.sin_ambito().create(
            organizacion=e.org_a, nombre="Cliente local", numero_documento="45871236", zona="DENTRO"
        )
        fuera = Cliente.objects.sin_ambito().create(
            organizacion=e.org_a, nombre="Cliente Lima", numero_documento="45871237", zona="FUERA"
        )
        d = self._pedir(
            "vendedor", empresa=e.emp_a1.pk, operacion="VENTA", cliente=dentro.pk
        ).json()
        f = self._pedir("vendedor", empresa=e.emp_a1.pk, operacion="VENTA", cliente=fuera.pk).json()
        assert (d["afectacion"]["codigo"], f["afectacion"]["codigo"]) == ("20", "10")

    def test_trae_si_el_igv_va_al_costo(self, equipo):
        e = equipo["e"]
        configuracion, _ = ConfiguracionEmpresa.objects.sin_ambito().get_or_create(empresa=e.emp_a1)
        configuracion.igv_compras_al_costo = True
        configuracion.save()
        r = self._pedir("vendedor", empresa=e.emp_a1.pk, operacion="COMPRA").json()
        assert r["igv_compras_al_costo"] is True

    def test_validaciones(self, equipo):
        e = equipo["e"]
        assert self._pedir("vendedor", empresa=e.emp_a1.pk).status_code == 400
        assert self._pedir("vendedor", empresa=e.emp_a1.pk, operacion="X").status_code == 400
        assert (
            self._pedir(
                "vendedor", empresa=e.emp_a1.pk, operacion="VENTA", zona="LEJOS"
            ).status_code
            == 400
        )
        assert (
            self._pedir(
                "vendedor", empresa=e.emp_a1.pk, operacion="VENTA", proveedor="9999"
            ).status_code
            == 400
        )
        assert (
            self._pedir(
                "vendedor", empresa=e.emp_a1.pk, operacion="VENTA", producto="abc"
            ).status_code
            == 400
        )
        assert (
            self._pedir(
                "vendedor", empresa=e.emp_a1.pk, operacion="VENTA", fecha="ayer"
            ).status_code
            == 400
        )
        assert self._pedir("vendedor", operacion="VENTA").status_code == 400

    def test_exige_sesion_y_permiso(self, equipo, api):
        e = equipo["e"]
        assert api.get(
            f"{BASE}/igv/sugerencia/", {"empresa": e.emp_a1.pk, "operacion": "VENTA"}
        ).status_code in (401, 403)


# ---------------------------------------------------------------------------
# Zona en clientes y proveedores, afectación en productos
# ---------------------------------------------------------------------------
class TestZonaYProducto:
    def test_la_zona_se_guarda_en_clientes_y_proveedores(self, equipo):
        api = cliente_de("super")
        r = api.post(
            f"{BASE}/proveedores/",
            {
                "tipo_documento": "RUC",
                "numero_documento": ruc_valido("2077777777"),
                "nombre": "Proveedor Lima",
                "zona": "FUERA",
            },
            format="json",
        )
        assert r.status_code == 201, r.content
        assert r.json()["zona"] == "FUERA"
        r = api.patch(f"{BASE}/proveedores/{r.json()['id']}/", {"zona": "DENTRO"}, format="json")
        assert r.json()["zona"] == "DENTRO"
        c = api.post(
            f"{BASE}/clientes/",
            {
                "tipo_documento": "DNI",
                "numero_documento": "45871236",
                "nombre": "Ana",
                "zona": "DENTRO",
            },
            format="json",
        )
        assert c.status_code == 201 and c.json()["zona"] == "DENTRO"

    def test_zona_invalida(self, equipo):
        r = cliente_de("super").post(
            f"{BASE}/clientes/",
            {
                "tipo_documento": "DNI",
                "numero_documento": "45871236",
                "nombre": "Ana",
                "zona": "LEJOS",
            },
            format="json",
        )
        assert r.status_code == 400

    def test_el_producto_puede_tener_su_afectacion(self, equipo):
        e = equipo["e"]
        producto = _producto(e.org_a)
        api = cliente_de("super")
        inafecto = _afectacion(e.org_a, "30")
        r = api.patch(
            f"{BASE}/productos/{producto.pk}/", {"afectacion_igv": inafecto.pk}, format="json"
        )
        assert r.status_code == 200, r.content
        assert (r.json()["afectacion_igv"], r.json()["afectacion_igv_nombre"]) == (
            inafecto.pk,
            inafecto.nombre,
        )
        r = api.patch(f"{BASE}/productos/{producto.pk}/", {"afectacion_igv": None}, format="json")
        assert r.json()["afectacion_igv"] is None

    def test_no_acepta_una_afectacion_de_otra_organizacion(self, equipo):
        e = equipo["e"]
        producto = _producto(e.org_a)
        ajena = _afectacion(e.org_b, "30")
        r = cliente_de("super").patch(
            f"{BASE}/productos/{producto.pk}/", {"afectacion_igv": ajena.pk}, format="json"
        )
        assert r.status_code == 400
